"""The administrator made from ADMIN_EMAIL and ADMIN_PASSWORD at start: created once, never changed, never shown."""

from __future__ import annotations

import pytest
from psycopg_pool import AsyncConnectionPool

from bi import accounts
from bi.config import admin_from_env, load_env

from .conftest import PoolFactory

BASE = {'DATABASE_URL': 'postgres://x/y', 'BI_API_KEY': 'k' * 16, 'AMS_CALLBACK_ORIGIN': 'https://ams.example.edu'}
PASSWORD = 'a-long-password-0123'


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    return await make_pool('bi_admin_env_test')


def test_both_variables_make_an_administrator_and_neither_makes_none() -> None:
    assert admin_from_env(load_env(BASE)) is None
    assert admin_from_env(load_env({**BASE, 'ADMIN_EMAIL': '', 'ADMIN_PASSWORD': ''})) is None  # a copied .env.example: blank means not set
    env = load_env({**BASE, 'ADMIN_EMAIL': 'admin@example.edu', 'ADMIN_PASSWORD': PASSWORD})
    assert admin_from_env(env) == ('admin@example.edu', PASSWORD, 'Administrator')
    assert admin_from_env(load_env({**BASE, 'ADMIN_EMAIL': 'a@b.edu', 'ADMIN_PASSWORD': PASSWORD, 'ADMIN_NAME': 'Dean'}))[2] == 'Dean'  # type: ignore[index]


def test_one_variable_alone_is_a_mistake_and_the_password_never_shows() -> None:
    for only in ({'ADMIN_EMAIL': 'admin@example.edu'}, {'ADMIN_PASSWORD': PASSWORD}):
        with pytest.raises(ValueError, match='together'):
            admin_from_env(load_env({**BASE, **only}))
    env = load_env({**BASE, 'ADMIN_EMAIL': 'admin@example.edu', 'ADMIN_PASSWORD': PASSWORD})
    assert PASSWORD not in repr(env) and PASSWORD not in str(env)


async def test_the_administrator_is_made_once_and_an_existing_account_is_left_alone(pool: AsyncConnectionPool) -> None:
    assert await accounts.ensure_admin(pool, 'Boss@Example.edu', PASSWORD, 'The Boss') is True
    signed = await accounts.sign_in(pool, 'boss@example.edu', PASSWORD)
    assert signed is not None and signed[0].is_admin and signed[0].name == 'The Boss'
    # a restart with other values changes nothing: not the password, the name, nor a second account under another spelling
    assert await accounts.ensure_admin(pool, 'boss@example.edu', 'another-long-password-9', 'Someone Else') is False
    assert await accounts.sign_in(pool, 'boss@example.edu', PASSWORD) is not None
    assert await accounts.sign_in(pool, 'boss@example.edu', 'another-long-password-9') is None
    async with pool.connection() as conn:
        row = await (await conn.execute("select count(*) from app_user where lower(email) = 'boss@example.edu'")).fetchone()
    assert row is not None and row[0] == 1


async def test_a_too_short_password_is_refused_without_repeating_it(pool: AsyncConnectionPool) -> None:
    with pytest.raises(accounts.AccountError) as e:
        await accounts.ensure_admin(pool, 'short@example.edu', 'tooshort', 'Short')
    assert 'at least' in str(e.value) and 'tooshort' not in str(e.value)
