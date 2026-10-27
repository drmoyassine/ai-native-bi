"""The BI's own accounts and their sessions (ROADMAP-009; single sign-on with the institution comes later, ROADMAP-005).

Passwords are hashed with Argon2id. A session is a random token in an HttpOnly cookie; only its SHA-256 is stored, so a copy of the
database signs nobody in.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from psycopg_pool import AsyncConnectionPool

SESSION_HOURS = 12
MIN_PASSWORD = 12
_HASHER = PasswordHasher()
# Checked against when the email is unknown, so a wrong email and a wrong password take the same time.
_DUMMY_HASH = _HASHER.hash(secrets.token_urlsafe(16))


class AccountError(ValueError):
    """The account cannot be created as asked (a short password, an email already in use)."""


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str
    is_admin: bool


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_user(pool: AsyncConnectionPool, email: str, name: str, password: str, is_admin: bool = False) -> User:
    email, name = email.strip(), name.strip()
    if '@' not in email or not name:
        raise AccountError('give an email address and a name')
    if len(password) < MIN_PASSWORD:
        raise AccountError(f'the password must have at least {MIN_PASSWORD} characters')
    async with pool.connection() as conn:
        if await (await conn.execute('select 1 from app_user where lower(email) = lower(%s)', [email])).fetchone():
            raise AccountError(f'{email} already has an account')
        row = await (
            await conn.execute(
                'insert into app_user (email, name, password_hash, is_admin) values (%s, %s, %s, %s) returning id::text',
                [email, name, _HASHER.hash(password), is_admin],
            )
        ).fetchone()
    assert row is not None
    return User(id=row[0], email=email, name=name, is_admin=is_admin)


async def ensure_admin(pool: AsyncConnectionPool, email: str, password: str, name: str) -> bool:
    """Makes the administrator of the deployment (ADMIN_EMAIL, ADMIN_PASSWORD) when that email has no account yet; True if it did.
    An existing account is never touched: not its password, its name or its rights, so changing the variables later changes nothing
    and a person's own password change survives a restart."""
    async with pool.connection() as conn:
        exists = await (await conn.execute('select 1 from app_user where lower(email) = lower(%s)', [email.strip()])).fetchone()
    if exists:
        return False
    await create_user(pool, email, name, password, is_admin=True)
    return True


async def sign_in(pool: AsyncConnectionPool, email: str, password: str) -> tuple[User, str] | None:
    """The user and a new session token, or None (which of email or password was wrong is not said)."""
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """select id::text, email, name, is_admin, password_hash from app_user
                   where lower(email) = lower(%s) and disabled_at is null""",
                [email.strip()],
            )
        ).fetchone()
        try:
            _HASHER.verify(row[4] if row else _DUMMY_HASH, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return None
        if row is None:
            return None
        token = secrets.token_urlsafe(32)
        expires = dt.datetime.now(dt.UTC) + dt.timedelta(hours=SESSION_HOURS)
        await conn.execute(
            'insert into app_session (token_hash, user_id, expires_at) values (%s, %s, %s)', [_token_hash(token), row[0], expires]
        )
        if _HASHER.check_needs_rehash(row[4]):
            await conn.execute('update app_user set password_hash = %s where id = %s', [_HASHER.hash(password), row[0]])
    return User(id=row[0], email=row[1], name=row[2], is_admin=row[3]), token


async def session_user(pool: AsyncConnectionPool, token: str | None) -> User | None:
    """Whose session this is, if it is alive and its user is not disabled."""
    if not token:
        return None
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """select u.id::text, u.email, u.name, u.is_admin from app_session s join app_user u on u.id = s.user_id
                   where s.token_hash = %s and s.expires_at > now() and u.disabled_at is null""",
                [_token_hash(token)],
            )
        ).fetchone()
    return User(id=row[0], email=row[1], name=row[2], is_admin=row[3]) if row else None


async def sign_out(pool: AsyncConnectionPool, token: str | None) -> None:
    if token:
        async with pool.connection() as conn:
            await conn.execute('delete from app_session where token_hash = %s or expires_at < now()', [_token_hash(token)])
