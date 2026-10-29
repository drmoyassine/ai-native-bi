"""Who an MCP call acts for (docs/mcp-spec.md section 5). One principal, whichever issuer signed the person in: the tools see only this.
Two issuers today: the BI's own personal access tokens, and an OpenID Connect issuer such as the AMS (contract 6.2), whose tokens carry
the person's BI role and scope."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

import jwt
from mcp.server.auth.provider import AccessToken
from psycopg_pool import AsyncConnectionPool

from .oidc import OidcIssuer

PREFIX = 'bi_pat_'
EXPIRY_DAYS = (7, 30, 90, 365)
ROLES = ('viewer', 'steward', 'admin')


@dataclass(frozen=True)
class Principal:
    issuer: str
    subject: str
    """The person's id in the BI (app_user.id) once known."""
    email: str
    name: str
    role: str
    scope: str
    """'all' until data scope is enforced in Cube (docs/mcp-spec.md section 5); anything else is refused, never ignored."""
    client_id: str

    def claims(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ('issuer', 'subject', 'email', 'name', 'role', 'scope', 'client_id')}

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> Principal:
        return cls(**{k: str(claims[k]) for k in ('issuer', 'subject', 'email', 'name', 'role', 'scope', 'client_id')})


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_token(pool: AsyncConnectionPool, user_id: str, name: str, days: int) -> tuple[dict[str, Any], str]:
    """A new token for a person: its record and the token itself, which is never stored and never shown again."""
    if days not in EXPIRY_DAYS:
        raise ValueError(f'a token lasts {", ".join(map(str, EXPIRY_DAYS))} days')
    token = PREFIX + secrets.token_urlsafe(32)
    expires = dt.datetime.now(dt.UTC) + dt.timedelta(days=days)
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """insert into access_token (user_id, name, token_hash, hint, expires_at) values (%s, %s, %s, %s, %s)
                   returning id::text, name, hint, created_at, expires_at""",
                [user_id, name.strip(), _hash(token), token[: len(PREFIX) + 4], expires],
            )
        ).fetchone()
    assert row is not None
    keys = ('id', 'name', 'hint', 'created_at', 'expires_at')
    return {**dict(zip(keys, row, strict=True)), 'last_used_at': None, 'revoked_at': None}, token


async def list_tokens(pool: AsyncConnectionPool, user_id: str | None) -> list[dict[str, Any]]:
    """A person's tokens, newest first; with user_id None, everyone's (for an admin), with the owner's email."""
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """select t.id::text, t.name, t.hint, t.created_at, t.expires_at, t.last_used_at, t.revoked_at, u.email
                   from access_token t join app_user u on u.id = t.user_id
                   where %(user)s::uuid is null or t.user_id = %(user)s::uuid order by t.created_at desc limit 500""",
                {'user': user_id},
            )
        ).fetchall()
    keys = ('id', 'name', 'hint', 'created_at', 'expires_at', 'last_used_at', 'revoked_at', 'owner')
    return [dict(zip(keys, r, strict=True)) for r in rows]


async def revoke_token(pool: AsyncConnectionPool, token_id: str, user_id: str, is_admin: bool) -> bool:
    """Revokes a token of the person (or anyone's, for an admin). False if there is no such token they may revoke."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            """update access_token set revoked_at = coalesce(revoked_at, now())
               where id::text = %s and (user_id = %s or %s)""",
            [token_id, user_id, is_admin],
        )
    return cur.rowcount > 0


async def verify_pat(pool: AsyncConnectionPool, token: str) -> Principal | None:
    """The principal of a live personal access token: not revoked, not expired, its person not disabled."""
    if not token.startswith(PREFIX):
        return None
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """select t.id::text, u.id::text, u.email, u.name, u.is_admin from access_token t join app_user u on u.id = t.user_id
                   where t.token_hash = %s and t.revoked_at is null and t.expires_at > now() and u.disabled_at is null""",
                [_hash(token)],
            )
        ).fetchone()
        if row is None:
            return None
        await conn.execute(
            """update access_token set last_used_at = now()
               where id = %s and (last_used_at is null or last_used_at < now() - interval '1 minute')""",
            [row[0]],
        )
    return Principal(
        issuer='bi', subject=row[1], email=row[2], name=row[3], role='admin' if row[4] else 'viewer', scope='all', client_id=f'pat:{row[0]}'
    )


async def link_identity(pool: AsyncConnectionPool, issuer: str, subject: str, email: str, name: str) -> str:
    """The local person for an issuer's subject, made the first time it is seen. The issuer is trusted to say who has an email, so a
    BI account with the same email is that person (their drafts and log entries stay theirs); roles are never taken from it."""
    async with pool.connection() as conn, conn.transaction():
        row = await (
            await conn.execute(
                'update external_identity set last_seen_at = now() where issuer = %s and subject = %s returning user_id::text',
                [issuer, subject],
            )
        ).fetchone()
        if row:
            await conn.execute('update app_user set name = %s where id = %s and name <> %s', [name, row[0], name])
            return str(row[0])
        user = await (await conn.execute('select id::text from app_user where lower(email) = lower(%s)', [email])).fetchone()
        if user is None:
            user = await (
                await conn.execute(
                    'insert into app_user (email, name, password_hash) values (%s, %s, null) returning id::text', [email, name]
                )
            ).fetchone()
        assert user is not None
        await conn.execute(
            'insert into external_identity (issuer, subject, user_id) values (%s, %s, %s) on conflict do nothing',
            [issuer, subject, user[0]],
        )
    return str(user[0])


def scope_of(entries: Any) -> str:
    """'all' when the person may see the whole organization (the AMS's scope type for it, contract 6.2); 'limited' for narrower
    scopes (refused until Cube enforces it)."""
    if not isinstance(entries, list):
        return 'none'
    if any(isinstance(e, dict) and e.get('type') == 'institution' for e in entries):
        return 'all'
    return 'limited' if entries else 'none'


async def verify_oidc(pool: AsyncConnectionPool, issuer: OidcIssuer, token: str) -> Principal | None:
    claims = await issuer.verify(token)
    if claims is None:
        return None
    role, email = claims.get('bi_role'), claims.get('email')
    if role not in ROLES or not isinstance(email, str) or '@' not in email:
        return None  # the issuer would not issue such a token; refuse rather than guess a role
    subject = str(claims['sub'])
    name = str(claims.get('name') or email)
    user_id = await link_identity(pool, issuer.name, subject, email, name)
    client = str(claims.get('client_id') or claims.get('azp') or 'unknown')
    return Principal(
        issuer=issuer.name, subject=user_id, email=email, name=name, role=role, scope=scope_of(claims.get('bi_scope')),
        client_id=f'{issuer.name}:{client}',
    )  # fmt: skip


class PrincipalVerifier:
    """The MCP SDK's TokenVerifier: dispatches a bearer token to the issuer it belongs to. A personal access token goes to the BI's
    own table; a JWT goes to the configured issuer named in its `iss` (and is then checked properly); anything else is refused."""

    def __init__(self, pool: AsyncConnectionPool, issuers: list[OidcIssuer] | None = None) -> None:
        self.pool = pool
        self.issuers = {i.issuer.rstrip('/'): i for i in issuers or []}

    async def principal(self, token: str) -> Principal | None:
        if token.startswith(PREFIX):
            return await verify_pat(self.pool, token)
        if not self.issuers or token.count('.') != 2:
            return None
        try:  # only to choose the issuer: the chosen issuer then checks the signature, audience and expiry
            claimed = jwt.decode(token, options={'verify_signature': False}).get('iss')
        except jwt.PyJWTError:
            return None
        issuer = self.issuers.get(str(claimed).rstrip('/'))
        return await verify_oidc(self.pool, issuer, token) if issuer else None

    async def verify_token(self, token: str) -> AccessToken | None:
        principal = await self.principal(token)
        if principal is None:
            return None
        return AccessToken(
            token=token, client_id=principal.client_id, scopes=[principal.role], subject=principal.subject, claims=principal.claims()
        )
