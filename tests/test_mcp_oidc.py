"""The AMS as the BI's authorization server (contract 6.2, docs/mcp-spec.md step 3c): its signed access tokens act for a person on the
MCP server. A fake AMS publishes its discovery document and Ed25519 keys; tokens are signed here as the AMS would sign them."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import httpx
import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from jwt.algorithms import OKPAlgorithm
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from psycopg_pool import AsyncConnectionPool

from bi import accounts
from bi.api import AppDeps, create_app
from bi.app import AppContext
from bi.connect.files import Storage
from bi.cube import CubeClient
from bi.mcp.oidc import OidcIssuer
from bi.mcp.principal import PrincipalVerifier, scope_of
from bi.mcp.server import McpContext

from .agent_fakes import FakeCube
from .conftest import AMS, PoolFactory

BASE = 'http://bi'
ISSUER = 'https://ams.example.edu/api/auth'
AUDIENCE = f'{BASE}/mcp'
KEY = Ed25519PrivateKey.generate()
OTHER_KEY = Ed25519PrivateKey.generate()
INSTITUTION = [{'type': 'institution', 'id': str(uuid.uuid4()), 'role': 'viewer'}]


class FakeAms:
    """The AMS's discovery document and keys (contract 6.2), counting how often the keys are fetched."""

    def __init__(self) -> None:
        self.key_fetches = 0
        self.kid = 'k1'

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == '/api/auth/.well-known/openid-configuration':
            return httpx.Response(200, json={'issuer': ISSUER, 'jwks_uri': 'https://ams.example.edu/api/auth/jwks'})
        if request.url.path == '/api/auth/jwks':
            self.key_fetches += 1
            jwk = OKPAlgorithm.to_jwk(KEY.public_key(), as_dict=True)
            return httpx.Response(200, json={'keys': [{**jwk, 'kid': self.kid, 'use': 'sig', 'alg': 'EdDSA'}]})
        return httpx.Response(404)


def token(key: Ed25519PrivateKey = KEY, kid: str = 'k1', typ: str = 'at+jwt', **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        'iss': ISSUER, 'aud': AUDIENCE, 'sub': 'ams-person-1', 'iat': now, 'exp': now + 600, 'client_id': 'claude',
        'email': 'dean@example.edu', 'name': 'The Dean', 'bi_role': 'viewer', 'bi_scope': INSTITUTION,
    }  # fmt: skip
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm='EdDSA', headers={'kid': kid, 'typ': typ})


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    p = await make_pool('bi_mcp_oidc_test')
    await accounts.create_user(p, 'local@example.edu', 'Local Person', 'a-long-password-0123')
    return p


@asynccontextmanager
async def ams_issuer() -> AsyncIterator[tuple[OidcIssuer, FakeAms]]:
    fake = FakeAms()
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as http:
        yield OidcIssuer(issuer=ISSUER, audience=AUDIENCE, http=http), fake


def build(pool: AsyncConnectionPool, tmp_path: Path, issuer: OidcIssuer) -> FastAPI:
    async def noop(id: str) -> None:
        pass

    cube = cast(CubeClient, FakeCube())
    return create_app(
        AppDeps(
            pool=pool,
            api_key='k' * 16,
            ams_origin=AMS,
            enqueue=noop,
            app=AppContext(
                pool=pool, storage=Storage(f'file://{tmp_path}'), enqueue_load=noop, cube=cube, cookie_secure=False, public_url=BASE
            ),
            mcp=McpContext(pool=pool, cube=cube, public_url=BASE, issuers=[issuer]),
        )
    )


@asynccontextmanager
async def mcp_session(app: FastAPI, bearer: str) -> AsyncIterator[ClientSession]:
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE, headers={'authorization': f'Bearer {bearer}'})
    async with http, streamable_http_client(f'{BASE}/mcp', http_client=http) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


async def test_only_a_valid_ams_access_token_for_this_server_acts_for_a_person(pool: AsyncConnectionPool) -> None:
    async with ams_issuer() as (issuer, fake):
        verifier = PrincipalVerifier(pool, [issuer])
        principal = await verifier.principal(token())
        assert principal is not None
        assert (principal.issuer, principal.role, principal.scope, principal.client_id) == ('ams', 'viewer', 'all', 'ams:claude')
        now = int(time.time())
        refused = {
            'another audience (a token for some other service)': token(aud='https://other.example.edu'),
            'another issuer': token(iss='https://evil.example.edu/api/auth'),
            'expired': token(iat=now - 3600, exp=now - 120),
            'signed by a key the AMS did not publish': token(key=OTHER_KEY),
            'an ID token, not an access token': token(typ='JWT'),
            'no BI role': token(bi_role=None),
            'an unknown BI role': token(bi_role='superuser'),
            'no email': token(email=None),
            'not a token at all': 'abc.def.ghi',
        }
        for why, bad in refused.items():
            assert await verifier.principal(bad) is None, why
        unsigned = jwt.encode({'iss': ISSUER, 'aud': AUDIENCE, 'sub': 'x', 'exp': now + 60}, key=None, algorithm='none')  # type: ignore[arg-type]
        assert await verifier.principal(unsigned) is None
        assert fake.key_fetches == 1  # the keys are cached, not fetched per token


async def test_a_rotated_key_is_fetched_once_not_on_every_unknown_key_id(pool: AsyncConnectionPool) -> None:
    async with ams_issuer() as (issuer, fake):
        verifier = PrincipalVerifier(pool, [issuer])
        assert await verifier.principal(token()) is not None
        for _ in range(5):  # an unknown key id within the minute does not hammer the AMS
            assert await verifier.principal(token(kid='rotated')) is None
        assert fake.key_fetches == 1
        issuer._fetched_at -= 120  # a minute later the AMS has rotated: the new key id is fetched and works
        fake.kid = 'rotated'
        assert await verifier.principal(token(kid='rotated')) is not None and fake.key_fetches == 2


async def test_an_ams_person_gets_a_local_record_once_and_an_existing_account_with_their_email_is_theirs(
    pool: AsyncConnectionPool,
) -> None:
    async with ams_issuer() as (issuer, _):
        verifier = PrincipalVerifier(pool, [issuer])
        first = await verifier.principal(token(sub='ams-new', email='new@example.edu', name='New Person'))
        again = await verifier.principal(token(sub='ams-new', email='new@example.edu', name='New Name'))
        linked = await verifier.principal(token(sub='ams-local', email='LOCAL@example.edu'))
    assert first and again and linked and first.subject == again.subject
    async with pool.connection() as conn:
        row = await (await conn.execute('select name, password_hash from app_user where id = %s', [first.subject])).fetchone()
        local = await (await conn.execute("select id::text from app_user where email = 'local@example.edu'")).fetchone()
    assert row == ('New Name', None) and local is not None and linked.subject == local[0]
    assert await accounts.sign_in(pool, 'new@example.edu', '') is None  # no password: they cannot sign in with one


def test_scope_all_means_the_institution_and_anything_narrower_is_limited() -> None:
    assert scope_of(INSTITUTION) == 'all'
    assert scope_of([{'type': 'org_unit', 'id': 'u', 'role': 'steward'}]) == 'limited'
    assert scope_of([]) == 'none' and scope_of(None) == 'none'


async def test_mcp_clients_are_told_to_sign_in_at_the_ams_and_its_tokens_work(pool: AsyncConnectionPool, tmp_path: Path) -> None:
    async with ams_issuer() as (issuer, _):
        app = build(pool, tmp_path, issuer)
        async with app.router.lifespan_context(app), httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as http:
            meta = await http.get('/.well-known/oauth-protected-resource/mcp')
            assert meta.status_code == 200
            assert meta.json()['authorization_servers'] == [ISSUER] and meta.json()['resource'] == AUDIENCE
            refused = await http.post(
                '/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
                headers={'accept': 'application/json, text/event-stream', 'content-type': 'application/json'},
            )  # fmt: skip
            assert refused.status_code == 401
            assert 'oauth-protected-resource/mcp' in refused.headers.get('www-authenticate', '')  # where to learn how to sign in

            async with mcp_session(app, token(sub='ams-dean', email='dean@example.edu')) as session:
                listed = await session.call_tool('list_datasets', {})
                assert not listed.is_error

            limited = token(sub='ams-unit', email='unit@example.edu', bi_scope=[{'type': 'org_unit', 'id': 'u', 'role': 'viewer'}])
            async with mcp_session(app, limited) as session:
                result = await session.call_tool('list_datasets', {})
                assert result.is_error and 'limited to some units' in str(result.content)
    async with pool.connection() as conn:
        rows = await (await conn.execute("select client_id, issuer from access_log where tool = 'list_datasets' order by id")).fetchall()
    assert ('ams:claude', 'ams') in rows
