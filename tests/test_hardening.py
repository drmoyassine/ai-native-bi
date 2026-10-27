"""Sign-in throttling and changing one's password (TASK-010, TASK-011): through the real app over HTTP."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool

from bi import accounts
from bi.api import AppDeps, create_app
from bi.app import AppContext
from bi.uploads import Storage

from .conftest import AMS, PoolFactory

PASSWORD = 'a-long-password-0123'
NEW = 'another-long-password-456'
APP = {'x-bi-app': '1'}
BASE = 'http://bi'


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    p = await make_pool('bi_hardening_test')
    for email in ('boss@example.edu', 'other@example.edu', 'victim@example.edu', 'pw@example.edu', 'gone@example.edu'):
        await accounts.create_user(p, email, email.split('@')[0].title(), PASSWORD)
    async with p.connection() as conn:  # a person signed in by another service has no password here
        await conn.execute("insert into app_user (email, name, password_hash) values ('ams@example.edu', 'Ams', null)")
    return p


@pytest.fixture(autouse=True)
async def clean(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        await conn.execute('delete from sign_in_failure')
        await conn.execute('delete from app_session')


def build(pool: AsyncConnectionPool, tmp_path: Path, proxy_hops: int = 0) -> FastAPI:
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
                cube=None,
                cookie_secure=False,
                throttle=accounts.Throttle(window_minutes=15, per_email=3, per_ip=5),
                proxy_hops=proxy_hops,
            ),
        )
    )


@asynccontextmanager
async def http(app: FastAPI) -> AsyncIterator[Callable[..., httpx.Response]]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        yield client  # type: ignore[misc]


async def sign_in(client: httpx.AsyncClient, email: str, password: str, headers: dict[str, str] | None = None) -> httpx.Response:
    return await client.post('/app/api/session', json={'email': email, 'password': password}, headers={**APP, **(headers or {})})


async def test_repeated_failures_for_one_email_refuse_even_the_right_password_with_a_wait(
    pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app = build(pool, tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        for _ in range(3):
            assert (await sign_in(client, 'boss@example.edu', 'wrong-password-123')).status_code == 401
        refused = await sign_in(client, 'boss@example.edu', PASSWORD)  # the right password, but the account is cooling down
        assert refused.status_code == 429 and 'Too many failed sign-in attempts' in refused.json()['detail']
        assert 0 < int(refused.headers['retry-after']) <= 15 * 60
        assert (await sign_in(client, 'other@example.edu', PASSWORD)).status_code == 200  # another account is untouched

    # An email that does not exist is counted and refused the same way: nothing says whether it exists (another address, so the
    # address's own limit is not what is being tested).
    transport = httpx.ASGITransport(app=app, client=('203.0.113.77', 4000))
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        for _ in range(3):
            assert (await sign_in(client, 'nobody@example.edu', 'wrong-password-123')).status_code == 401
        assert (await sign_in(client, 'nobody@example.edu', 'wrong-password-123')).status_code == 429


async def test_failures_leave_the_window_and_a_success_clears_them(pool: AsyncConnectionPool, tmp_path: Path) -> None:
    app = build(pool, tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        for _ in range(2):
            assert (await sign_in(client, 'boss@example.edu', 'wrong-password-123')).status_code == 401
        assert (await sign_in(client, 'boss@example.edu', PASSWORD)).status_code == 200  # under the limit: signs in, forgets the typos
        async with pool.connection() as conn:
            left = await (await conn.execute("select count(*) from sign_in_failure where email = 'boss@example.edu'")).fetchone()
        assert left is not None and left[0] == 0

        for _ in range(3):
            await sign_in(client, 'boss@example.edu', 'wrong-password-123')
        assert (await sign_in(client, 'boss@example.edu', PASSWORD)).status_code == 429
        async with pool.connection() as conn:  # the window passes
            await conn.execute("update sign_in_failure set at = now() - interval '16 minutes'")
        assert (await sign_in(client, 'boss@example.edu', PASSWORD)).status_code == 200


async def test_one_address_trying_many_emails_is_refused_and_a_forwarded_address_is_read_only_as_far_as_trusted(
    pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    emails = [f'guess{i}@example.edu' for i in range(5)]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build(pool, tmp_path), client=('203.0.113.9', 5000)), base_url=BASE
    ) as c:
        for email in emails:  # five different emails from one address: no email reaches its own limit, the address does
            assert (await sign_in(c, email, 'wrong-password-123')).status_code == 401
        assert (await sign_in(c, 'victim@example.edu', PASSWORD)).status_code == 429
        # Not trusting a proxy: a made-up X-Forwarded-For does not buy a fresh allowance.
        assert (await sign_in(c, 'victim@example.edu', PASSWORD, {'x-forwarded-for': '198.51.100.1'})).status_code == 429

    await clean_failures(pool)
    app = build(pool, tmp_path, proxy_hops=1)  # behind one proxy that appends the address it saw: that is the client
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('10.0.0.1', 1)), base_url=BASE) as c:
        for email in emails:
            await sign_in(c, email, 'wrong-password-123', {'x-forwarded-for': '203.0.113.9'})
        assert (await sign_in(c, 'victim@example.edu', PASSWORD, {'x-forwarded-for': '203.0.113.9'})).status_code == 429
        assert (await sign_in(c, 'victim@example.edu', PASSWORD, {'x-forwarded-for': '198.51.100.7'})).status_code == 200  # another client
        # A blocked client that puts a made-up address at the front of the header still arrives as the one the proxy appended.
        spoofed = {'x-forwarded-for': '198.51.100.99, 203.0.113.9'}
        assert (await sign_in(c, 'victim@example.edu', PASSWORD, spoofed)).status_code == 429


async def clean_failures(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        await conn.execute('delete from sign_in_failure')


async def test_changing_a_password_needs_the_current_one_and_ends_the_other_sessions(pool: AsyncConnectionPool, tmp_path: Path) -> None:
    app = build(pool, tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url=BASE) as mine,
        httpx.AsyncClient(transport=transport, base_url=BASE) as other,
    ):
        assert (await sign_in(mine, 'pw@example.edu', PASSWORD)).status_code == 200
        assert (await sign_in(other, 'pw@example.edu', PASSWORD)).status_code == 200  # the same person on another device
        change = {'current_password': PASSWORD, 'new_password': NEW}

        assert (await mine.post('/app/api/password', json=change)).status_code == 403  # no X-BI-App header
        wrong = await mine.post('/app/api/password', json={**change, 'current_password': 'not-my-password-1'}, headers=APP)
        assert wrong.status_code == 403 and 'current password is wrong' in wrong.json()['detail']
        short = await mine.post('/app/api/password', json={**change, 'new_password': 'short'}, headers=APP)
        assert short.status_code == 422 and 'at least' in short.json()['detail']
        same = await mine.post('/app/api/password', json={**change, 'new_password': PASSWORD}, headers=APP)
        assert same.status_code == 422 and 'different' in same.json()['detail']

        assert (await mine.post('/app/api/password', json=change, headers=APP)).status_code == 204
        assert (await mine.get('/app/api/me')).status_code == 200  # the session in use stays
        assert (await other.get('/app/api/me')).status_code == 401  # every other session of theirs is over

    async with httpx.AsyncClient(transport=transport, base_url=BASE) as fresh:
        assert (await sign_in(fresh, 'pw@example.edu', PASSWORD)).status_code == 401  # the old password no longer works
        assert (await sign_in(fresh, 'pw@example.edu', NEW)).status_code == 200


async def test_a_stolen_session_cannot_guess_the_password_forever_and_an_ams_account_has_none_to_change(
    pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app = build(pool, tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        assert (await sign_in(client, 'gone@example.edu', PASSWORD)).status_code == 200
        bad = {'current_password': 'not-my-password-1', 'new_password': NEW}
        for _ in range(3):
            assert (await client.post('/app/api/password', json=bad, headers=APP)).status_code == 403
        assert (await client.post('/app/api/password', json=bad, headers=APP)).status_code == 429  # the same limit as signing in

    async with pool.connection() as conn:
        ams = await (await conn.execute("select id::text from app_user where email = 'ams@example.edu'")).fetchone()
    assert ams is not None
    with pytest.raises(accounts.AccountError, match='another service'):
        await accounts.change_password(pool, ams[0], 'x' * 12, NEW, None)
    assert await accounts.sign_in(pool, 'ams@example.edu', PASSWORD) is None
