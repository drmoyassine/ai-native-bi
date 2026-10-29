"""The secret store (DEC-020): values encrypted with AES-GCM in the `secret` table, behind a small interface the organization's vault can
replace. The agent, the model and the logs only ever see a handle (`secret://name`), never a value."""

from __future__ import annotations

import base64
import os
import re
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg_pool import AsyncConnectionPool

HANDLE = re.compile(r'^secret://[a-z0-9][a-z0-9._-]{0,99}$')


class SecretError(ValueError):
    """The secret is missing, its handle is malformed, or the key does not open it."""


class SecretStore(Protocol):
    async def put(self, handle: str, value: str, created_by: str | None = None) -> str: ...

    async def get(self, handle: str) -> str: ...

    async def delete(self, handle: str) -> None: ...


def parse_key(key: str) -> bytes:
    """BI_SECRETS_KEY: 32 random bytes, base64url (what scripts/make_env.py writes)."""
    try:
        raw = base64.urlsafe_b64decode(key.strip() + '=' * (-len(key.strip()) % 4))
    except ValueError as e:
        raise SecretError('BI_SECRETS_KEY is not base64url') from e
    if len(raw) != 32:
        raise SecretError('BI_SECRETS_KEY must be 32 bytes (43 base64url characters)')
    return raw


class DbSecretStore:
    def __init__(self, pool: AsyncConnectionPool, key: str) -> None:
        self._pool = pool
        self._aead = AESGCM(parse_key(key))

    @staticmethod
    def _check(handle: str) -> None:
        if not HANDLE.match(handle):
            raise SecretError(f'"{handle}" is not a secret handle (secret://name)')

    async def put(self, handle: str, value: str, created_by: str | None = None) -> str:
        self._check(handle)
        nonce = os.urandom(12)
        ciphertext = self._aead.encrypt(nonce, value.encode(), handle.encode())  # the handle is authenticated: a value cannot be moved
        async with self._pool.connection() as conn:
            await conn.execute(
                """insert into secret (handle, nonce, ciphertext, created_by) values (%s, %s, %s, %s)
                   on conflict (handle) do update set nonce = excluded.nonce, ciphertext = excluded.ciphertext""",
                [handle, nonce, ciphertext, created_by],
            )
        return handle

    async def get(self, handle: str) -> str:
        self._check(handle)
        async with self._pool.connection() as conn:
            row = await (
                await conn.execute('update secret set last_used_at = now() where handle = %s returning nonce, ciphertext', [handle])
            ).fetchone()
        if row is None:
            raise SecretError(f'no secret {handle}')
        try:
            return self._aead.decrypt(bytes(row[0]), bytes(row[1]), handle.encode()).decode()
        except InvalidTag as e:
            raise SecretError(f'{handle} cannot be opened with this BI_SECRETS_KEY') from e

    async def delete(self, handle: str) -> None:
        self._check(handle)
        async with self._pool.connection() as conn:
            await conn.execute('delete from secret where handle = %s', [handle])
