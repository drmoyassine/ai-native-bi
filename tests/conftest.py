from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from bi import definitions
from bi.db import ensure_database, migrate

ADMIN = os.environ.get('TEST_DATABASE_ADMIN_URL', 'postgres://postgres:postgres@localhost:5432/postgres')
AMS = 'https://ams.example.org'


def database_url(name: str) -> str:
    """An address on the test server for the role and database `name` (password `<name>_pw`)."""
    u = urlsplit(ADMIN)
    return urlunsplit((u.scheme, f'{name}:{name}_pw@{u.hostname}:{u.port or 5432}', f'/{name}', '', ''))


async def fresh_database(name: str) -> str:
    async with await psycopg.AsyncConnection.connect(ADMIN, autocommit=True) as admin:
        await admin.execute(f'drop database if exists {name} with (force)')
        await admin.execute(f'drop role if exists {name}')
    url = database_url(name)
    await ensure_database(ADMIN, url)
    return url


PoolFactory = Callable[[str], Coroutine[Any, Any, AsyncConnectionPool]]


@pytest.fixture(scope='session')
async def make_pool() -> AsyncIterator[PoolFactory]:
    pools: list[AsyncConnectionPool] = []

    async def make(name: str) -> AsyncConnectionPool:
        url = await fresh_database(name)
        pool = AsyncConnectionPool(url, open=False)
        await pool.open()
        await migrate(pool)
        await definitions.install_template(pool, 'higher-education')  # the tests' made-up data is this template's (DEC-037)
        pools.append(pool)
        return pool

    yield make
    for pool in pools:
        await pool.close()


CUBE_DB = 'bi_cube_test'
"""The database the test Cube reads (CUBEJS_DB_NAME); created before Cube starts, never dropped by the tests."""


@pytest.fixture(scope='session')
def cube_env() -> tuple[str, str]:
    """Cube's address and secret for the integration tests: CUBE_TEST_URL and CUBE_TEST_SECRET. Without them the tests skip locally;
    CI sets REQUIRE_CUBE=1, which turns a missing Cube into a failure instead."""
    url, secret = os.environ.get('CUBE_TEST_URL'), os.environ.get('CUBE_TEST_SECRET')
    if not url or not secret:
        if os.environ.get('REQUIRE_CUBE') == '1':
            pytest.fail('REQUIRE_CUBE=1 but CUBE_TEST_URL or CUBE_TEST_SECRET is not set')
        pytest.skip('no Cube: set CUBE_TEST_URL and CUBE_TEST_SECRET (Cube reading the database bi_cube_test)')
    return url, secret
