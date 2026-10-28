"""The MCP server (docs/mcp-spec.md step 3a) through the SDK's real client over HTTP: personal access tokens, the tools, refusals,
rate limits and the access log. The app runs in-process (httpx2's ASGI transport) with its lifespan, as in production."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from psycopg_pool import AsyncConnectionPool

from bi import accounts
from bi.api import AppDeps, create_app
from bi.app import AppContext
from bi.connect.files import Storage
from bi.cube import CubeClient
from bi.mcp.server import McpContext

from .agent_fakes import FakeCube
from .conftest import AMS, PoolFactory

PASSWORD = 'a-long-password-0123'
APP = {'x-bi-app': '1'}
BASE = 'http://bi'
TOOLS = {'list_metrics', 'search_knowledge', 'query_metric', 'save_chart', 'get_chart', 'list_datasets', 'describe_dataset'}


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    p = await make_pool('bi_mcp_test')
    await accounts.create_user(p, 'admin@example.edu', 'Admin', PASSWORD, is_admin=True)
    await accounts.create_user(p, 'person@example.edu', 'Person', PASSWORD)
    await accounts.create_user(p, 'other@example.edu', 'Other', PASSWORD)
    return p


def build(pool: AsyncConnectionPool, tmp_path: Path, cube: FakeCube, per_minute: int = 60) -> FastAPI:
    async def noop(id: str) -> None:
        pass

    return create_app(
        AppDeps(
            pool=pool,
            api_key='k' * 16,
            ams_origin=AMS,
            enqueue=noop,
            app=AppContext(
                pool=pool,
                storage=Storage(f'file://{tmp_path}'),
                enqueue_load=noop,
                cube=cast(CubeClient, cube),
                cookie_secure=False,
                public_url=BASE,
            ),
            mcp=McpContext(pool=pool, cube=cast(CubeClient, cube), public_url=BASE, calls_per_minute=per_minute),
        )
    )


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[FastAPI]:
    async with app.router.lifespan_context(app):  # the MCP session manager lives in the app's lifespan
        yield app


@asynccontextmanager
async def signed_in(app: FastAPI, email: str) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        assert (await client.post('/app/api/session', json={'email': email, 'password': PASSWORD}, headers=APP)).status_code == 200
        yield client


async def new_token(app: FastAPI, email: str, name: str = 'laptop') -> str:
    async with signed_in(app, email) as client:
        res = await client.post('/app/api/tokens', json={'name': name, 'days': 30}, headers=APP)
    assert res.status_code == 201, res.text
    token: str = res.json()['token']
    return token


@asynccontextmanager
async def mcp_session(app: FastAPI, token: str) -> AsyncIterator[ClientSession]:
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE, headers={'authorization': f'Bearer {token}'})
    async with http, streamable_http_client(f'{BASE}/mcp', http_client=http) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


def structured(result: Any) -> dict[str, Any]:
    assert not result.is_error, result.content
    data: dict[str, Any] = result.structured_content
    return data


async def test_tokens_are_shown_once_listed_without_the_secret_and_revoked_by_their_owner(
    pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app = build(pool, tmp_path, FakeCube())
    async with running(app), signed_in(app, 'person@example.edu') as person, signed_in(app, 'other@example.edu') as other:
        made = await person.post('/app/api/tokens', json={'name': 'Claude Code', 'days': 90}, headers=APP)
        assert made.status_code == 201 and made.json()['token'].startswith('bi_pat_')
        token, record = made.json()['token'], made.json()['record']
        listed = (await person.get('/app/api/tokens')).json()
        assert listed['mcp_url'] == f'{BASE}/mcp' and token not in str(listed)  # never shown again
        assert [t['name'] for t in listed['tokens']] == ['Claude Code'] and token.startswith(listed['tokens'][0]['hint'])
        assert (await person.post('/app/api/tokens', json={'name': 'x', 'days': 1000}, headers=APP)).status_code == 422
        assert (await person.get('/app/api/tokens?everyone=true')).status_code == 403
        assert (await other.delete(f'/app/api/tokens/{record["id"]}', headers=APP)).status_code == 404  # not theirs
        assert (await person.delete(f'/app/api/tokens/{record["id"]}', headers=APP)).status_code == 204
        assert (await person.get('/app/api/tokens')).json()['tokens'][0]['revoked_at'] is not None
        async with signed_in(app, 'admin@example.edu') as admin:
            owners = {t['owner'] for t in (await admin.get('/app/api/tokens?everyone=true')).json()['tokens']}
        assert 'person@example.edu' in owners


async def test_a_real_client_lists_and_calls_the_governed_tools(pool: AsyncConnectionPool, tmp_path: Path) -> None:
    cube = FakeCube(
        rows=[
            {'enrollment.program': 'BSME', 'enrollment.headcount': '120', 'enrollment.as_of': '20261020'},
            {'enrollment.program': 'MSDS', 'enrollment.headcount': '3', 'enrollment.as_of': '20261020'},
        ]
    )
    app = build(pool, tmp_path, cube)
    async with running(app):
        token = await new_token(app, 'person@example.edu')
        async with mcp_session(app, token) as session:
            listed = (await session.list_tools()).tools
            assert {t.name for t in listed} == TOOLS
            by_name = {t.name: t for t in listed}
            assert by_name['query_metric'].annotations and by_name['query_metric'].annotations.read_only_hint is True
            assert 'as-of date' in (by_name['query_metric'].description or '')  # the same docstring the chat agent reads

            members = structured(await session.call_tool('list_metrics', {}))['members']
            assert 'enrollment.headcount' in {m['name'] for m in members}

            query = {'measures': ['enrollment.headcount'], 'dimensions': ['enrollment.program']}
            answer = structured(await session.call_tool('query_metric', {'query': query}))
            counts = {r['enrollment.program']: r['enrollment.headcount'] for r in answer['rows']}
            assert counts == {'BSME': 120, 'MSDS': None} and answer['suppressed_cells'] == 1 and answer['as_of'] == '2026-10-20'
            assert '"3"' not in str(answer) and ': 3,' not in str(answer)  # the small count never leaves

            chart = {'version': 1, 'title': 'Headcount by program', 'query': query, 'visual': {'type': 'bar', 'x': 'enrollment.program'}}
            saved = structured(await session.call_tool('save_chart', {'chart': chart}))
            got = structured(await session.call_tool('get_chart', {'chart_id': saved['draft_id']}))
            assert got['suppressed_cells'] == 1 and {r['enrollment.program'] for r in got['rows']} == {'BSME', 'MSDS'}

            unknown = await session.call_tool('query_metric', {'query': {'measures': ['students.names']}})
            assert 'not governed' in str(structured(unknown))  # an error the model can read and correct
            assert structured(await session.call_tool('describe_dataset', {'dataset': 'nope'}))['error']

        other = await new_token(app, 'other@example.edu')
        async with mcp_session(app, other) as session:  # another person's draft is not theirs to read
            refused = await session.call_tool('get_chart', {'chart_id': saved['draft_id']})
            assert refused.is_error and 'no such chart' in str(refused.content)

    async with pool.connection() as conn:
        rows = await (await conn.execute('select tool, outcome, rows, suppressed_cells from access_log order by id')).fetchall()
    assert ('query_metric', 'ok', 2, 1) in rows and ('get_chart', 'error', None, None) in rows
    assert all(r[1] in ('ok', 'error') for r in rows)
    async with pool.connection() as conn:  # the person's draft is owned by them, made by an agent
        draft = await (await conn.execute('select built_by from draft where id::text = %s', [saved['draft_id']])).fetchone()
    assert draft is not None and draft[0] == 'agent'


async def test_no_token_a_wrong_one_a_revoked_one_an_expired_one_or_a_disabled_person_is_refused(
    pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app = build(pool, tmp_path, FakeCube())
    ping = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}
    headers = {'accept': 'application/json, text/event-stream', 'content-type': 'application/json'}
    async with running(app), httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as http:

        async def status(token: str | None, host: str = 'bi') -> int:
            auth = {'authorization': f'Bearer {token}'} if token else {}
            res = await http.post('/mcp', json=ping, headers={**headers, **auth, 'host': host})
            return int(res.status_code)

        assert await status(None) == 401
        assert await status('bi_pat_not-a-real-token') == 401
        assert await status('eyJhbGciOiJIUzI1NiJ9.e30.x') == 401  # a JWT from an issuer that is not configured
        token = await new_token(app, 'other@example.edu', 'revoke me')
        assert await status(token) == 200
        assert await status(token, host='evil.example') >= 400  # DNS-rebinding protection: only the app's own host
        async with pool.connection() as conn:
            await conn.execute("update access_token set expires_at = now() - interval '1 second' where name = 'revoke me'")
        assert await status(token) == 401
        async with pool.connection() as conn:
            await conn.execute("update access_token set expires_at = now() + interval '1 day', revoked_at = now() where name = 'revoke me'")
        assert await status(token) == 401
        disabled = await new_token(app, 'other@example.edu', 'disabled')
        async with pool.connection() as conn:
            await conn.execute("update app_user set disabled_at = now() where email = 'other@example.edu'")
        try:
            assert await status(disabled) == 401
        finally:
            async with pool.connection() as conn:
                await conn.execute("update app_user set disabled_at = null where email = 'other@example.edu'")


async def test_the_rate_limit_refuses_with_a_reason_and_is_logged(pool: AsyncConnectionPool, tmp_path: Path) -> None:
    app = build(pool, tmp_path, FakeCube(), per_minute=2)
    async with running(app):
        token = await new_token(app, 'admin@example.edu', 'limited')
        async with pool.connection() as conn:
            await conn.execute("delete from access_log where user_id = (select id from app_user where email = 'admin@example.edu')")
        async with mcp_session(app, token) as session:
            for _ in range(2):
                structured(await session.call_tool('list_datasets', {}))
            third = await session.call_tool('list_datasets', {})
            assert third.is_error and 'calls a minute' in str(third.content)
    async with pool.connection() as conn:
        outcomes = await (
            await conn.execute(
                """select outcome from access_log where user_id = (select id from app_user where email = 'admin@example.edu')
                   order by id"""
            )
        ).fetchall()
    assert [o[0] for o in outcomes] == ['ok', 'ok', 'limited']
