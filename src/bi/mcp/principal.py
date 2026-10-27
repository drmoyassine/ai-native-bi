"""Who an MCP call acts for (docs/mcp-spec.md section 5). One principal, whichever issuer signed the person in: the tools see only this.
Step 3a has one issuer, the BI's own personal access tokens; the AMS's and the institution's tokens are added later (issue 10)."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

from mcp.server.auth.provider import AccessToken
from psycopg_pool import AsyncConnectionPool

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


class PrincipalVerifier:
    """The MCP SDK's TokenVerifier: dispatches a bearer token to the issuer it belongs to. Step 3a knows one issuer (the BI's own
    tokens); a token of any other shape is refused until its issuer is configured."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    async def verify_token(self, token: str) -> AccessToken | None:
        principal = await verify_pat(self.pool, token)
        if principal is None:
            return None
        return AccessToken(
            token=token, client_id=principal.client_id, scopes=[principal.role], subject=principal.subject, claims=principal.claims()
        )
