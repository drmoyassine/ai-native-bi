from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from psycopg_pool import AsyncConnectionPool

from bi.collect import Accepted, Refused, accept_collect, key_matches
from bi.config import load_env
from bi.contract import CollectRequest, SupplyBody
from bi.db import ensure_database, migrate, migration_names
from bi.queue import COLLECT_QUEUE, CallbackError, CollectDeps, CollectRetry, create_queue, enqueue_collect, process_collect
from bi.sources import SourceRegistry

from .conftest import ADMIN, AMS, PoolFactory, database_url


def request(**over: Any) -> dict[str, Any]:
    return {
        'runId': 'run-1',
        'evidence': {
            'id': 'ev-1',
            'title': 'Enrollment headcount',
            'type': 'dataset',
            'definition': None,
            'columns': [{'key': 'n', 'label': 'N', 'type': 'integer', 'required': True}],
        },
        'period': {'label': 'Fall 2026', 'start': '2026-08-24', 'end': None},
        'query': {'metric': 'enrollment_headcount'},
        'callbackUrl': f'{AMS}/api/bi/v0/runs/run-1/supply',
        'callbackToken': 'tok-1',
    } | over


class Headcount:
    name = 'test'

    async def can_answer(self, req: CollectRequest) -> bool:
        return req.query is not None and req.query.metric == 'enrollment_headcount'

    async def answer(self, req: CollectRequest) -> SupplyBody:
        return SupplyBody(rows=[{'n': 120}], as_of='2026-10-20', lineage={'source': 'test'})


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    return await make_pool('bi_test')


@pytest.fixture(autouse=True)
async def empty(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        await conn.execute('delete from collect_request')


async def accepted(pool: AsyncConnectionPool, **over: Any) -> str:
    r = await accept_collect(pool, request(**over), AMS)
    assert isinstance(r, Accepted)
    return r.id


async def test_migrates_once_and_creates_the_database_once(pool: AsyncConnectionPool) -> None:
    await ensure_database(ADMIN, database_url('bi_test'))  # again: nothing to do
    assert migration_names() == [
        '0001_collect_request.sql',
        '0002_procrastinate.sql',
        '0003_collect_no_data.sql',
        '0004_app.sql',
        '0005_agent.sql',
        '0006_mcp.sql',
        '0007_external_identity.sql',
        '0008_sign_in_failure.sql',
        '0009_column_mapping.sql',
        '0010_connect.sql',
        '0011_setup_agent.sql',
    ]
    assert await migrate(pool) == []


def test_the_ams_key_matches_only_the_exact_bearer_key() -> None:
    assert key_matches('Bearer secret-key-0123456789', 'secret-key-0123456789')
    assert not key_matches('Bearer wrong', 'secret-key-0123456789')
    assert not key_matches(None, 'secret-key-0123456789')
    assert not key_matches('secret-key-0123456789', 'secret-key-0123456789')


def test_the_environment() -> None:
    env = load_env(
        {'DATABASE_URL': 'postgres://x', 'BI_API_KEY': 'k' * 16, 'AMS_CALLBACK_ORIGIN': 'https://AMS.example.org:443/x', 'PORT': ''}
    )
    assert (env.AMS_CALLBACK_ORIGIN, env.PORT, env.BI_DATABASE_ADMIN_URL) == ('https://ams.example.org', 4000, None)
    with pytest.raises(ValueError):
        load_env({'DATABASE_URL': 'postgres://x', 'BI_API_KEY': 'short', 'AMS_CALLBACK_ORIGIN': AMS})


async def test_keeps_a_request_once_per_attempt_and_a_retry_with_a_new_token_as_a_new_one(pool: AsyncConnectionPool) -> None:
    a = await accept_collect(pool, request(), AMS)
    again = await accept_collect(pool, request(), AMS)
    retry = await accept_collect(pool, request(callbackToken='tok-2'), AMS)
    assert isinstance(a, Accepted) and not a.repeat
    assert isinstance(again, Accepted) and again.repeat and again.id == a.id
    assert isinstance(retry, Accepted) and not retry.repeat
    async with pool.connection() as conn:
        stored = await (await conn.execute('select request from collect_request limit 1')).fetchone()
    assert stored is not None and 'callbackToken' not in stored[0] and stored[0]['runId'] == 'run-1'


async def test_refuses_a_callback_anywhere_but_the_runs_own_supply_route_on_the_ams(pool: AsyncConnectionPool) -> None:
    for callback_url in [
        'https://evil.example.org/api/bi/v0/runs/run-1/supply',
        f'{AMS}/api/bi/v0/runs/run-2/supply',
        f'{AMS}/somewhere',
        f'{AMS}/api/bi/v0/runs/run-1/supply?x=1',
        'http://ams.example.org/api/bi/v0/runs/run-1/supply',
    ]:
        r = await accept_collect(pool, request(callbackUrl=callback_url), AMS)
        assert isinstance(r, Refused) and r.status == 422 and r.issues[0].path == 'callbackUrl'
    r = await accept_collect(pool, {'runId': 'x'}, AMS)
    assert isinstance(r, Refused) and r.status == 422


Call = dict[str, Any]


def answering(calls: list[Call], status: int, body: Any = None) -> httpx.AsyncClient:
    def handle(req: httpx.Request) -> httpx.Response:
        calls.append({'url': str(req.url), 'auth': req.headers.get('authorization'), 'body': json.loads(req.content)})
        return httpx.Response(status, json=body or {})

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


def deps(pool: AsyncConnectionPool, client: httpx.AsyncClient) -> CollectDeps:
    return CollectDeps(pool=pool, sources=SourceRegistry([Headcount()]), callback_timeout_ms=1000, client=client)


async def row(pool: AsyncConnectionPool, id: str, columns: str) -> tuple[Any, ...]:
    async with pool.connection() as conn:
        r = await (await conn.execute(f'select {columns} from collect_request where id = %s', [id])).fetchone()  # noqa: S608 (test columns)
    assert r is not None
    return tuple(r)


async def test_answers_from_a_source_calls_the_ams_back_with_the_one_time_token_then_forgets_it(pool: AsyncConnectionPool) -> None:
    calls: list[Call] = []
    id = await accepted(pool)
    async with answering(calls, 200) as client:
        assert await process_collect(deps(pool, client), id) == 'supplied'
        assert calls == [
            {
                'url': f'{AMS}/api/bi/v0/runs/run-1/supply',
                'auth': 'Bearer tok-1',
                'body': {'rows': [{'n': 120}], 'asOf': '2026-10-20', 'lineage': {'source': 'test'}},
            }
        ]
        status, token, finished = await row(pool, id, 'status, callback_token, finished_at')
        assert (status, token) == ('supplied', None) and finished is not None
        assert await process_collect(deps(pool, client), id) == 'skipped'


async def test_never_calls_back_without_a_source_no_data_means_no_supply(pool: AsyncConnectionPool) -> None:
    calls: list[Call] = []
    id = await accepted(pool, query={'metric': 'graduation_rate'})
    async with answering(calls, 200) as client:
        assert await process_collect(deps(pool, client), id) == 'no_source'
    assert calls == []
    assert await row(pool, id, 'last_error') == ('no source answers metric "graduation_rate"',)


async def test_ends_on_401_409_and_422_and_leaves_a_network_error_to_the_queue(pool: AsyncConnectionPool) -> None:
    calls: list[Call] = []
    a = await accepted(pool, callbackToken='a')
    async with answering(calls, 409) as client:
        assert await process_collect(deps(pool, client), a) == 'refused'
    b = await accepted(pool, callbackToken='b')
    async with answering(calls, 422, {'issues': [{'path': 'rows.0.n', 'message': 'enter a whole number'}]}) as client:
        assert await process_collect(deps(pool, client), b) == 'failed'
    assert 'rows.0.n' in (await row(pool, b, 'last_error'))[0]

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError('connect ECONNREFUSED')

    c = await accepted(pool, callbackToken='c')
    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as client:
        with pytest.raises(CallbackError, match='ECONNREFUSED'):
            await process_collect(deps(pool, client), c)
    assert await row(pool, c, 'status, callback_token') == ('running', 'c')


async def test_never_follows_a_redirect(pool: AsyncConnectionPool) -> None:
    calls: list[Call] = []
    id = await accepted(pool)

    def redirect(req: httpx.Request) -> httpx.Response:
        calls.append({'url': str(req.url)})
        return httpx.Response(307, headers={'location': 'https://evil.example.org/'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect)) as client:
        with pytest.raises(CallbackError, match='307'):
            await process_collect(deps(pool, client), id)
    assert len(calls) == 1


class _Job:
    def __init__(self, attempts: int) -> None:
        self.attempts = attempts


@pytest.mark.parametrize(('attempts', 'seconds'), [(0, 60), (1, 120), (4, 960), (5, None)])
def test_retries_a_failed_job_five_times_with_backoff(attempts: int, seconds: int | None) -> None:
    retry: Callable[..., Any] = CollectRetry().get_retry_decision
    decision = retry(exception=CallbackError('down'), job=_Job(attempts))
    if seconds is None:
        assert decision is None
    else:
        assert decision is not None and decision.retry_at is not None
        assert abs((decision.retry_at - datetime.now(UTC)).total_seconds() - seconds) < 5


async def test_the_queue_runs_a_deferred_request_on_the_migrated_schema(pool: AsyncConnectionPool) -> None:
    calls: list[Call] = []
    id = await accepted(pool, callbackToken='queued')
    async with answering(calls, 200) as client:
        queue = create_queue(database_url('bi_test'), deps(pool, client))
        async with queue.open_async():
            await enqueue_collect(queue, id)
            await queue.run_worker_async(queues=[COLLECT_QUEUE], wait=False, install_signal_handlers=False)
    assert [c['auth'] for c in calls] == ['Bearer queued']
    assert await row(pool, id, 'status') == ('supplied',)


def unreachable() -> httpx.AsyncClient:
    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError('connect ECONNREFUSED')

    return httpx.AsyncClient(transport=httpx.MockTransport(down))


async def run_once(pool: AsyncConnectionPool, id: str, client: httpx.AsyncClient, retry: CollectRetry) -> None:
    queue = create_queue(database_url('bi_test'), deps(pool, client), retry=retry)
    async with queue.open_async():
        await enqueue_collect(queue, id)
        await queue.run_worker_async(queues=[COLLECT_QUEUE], wait=False, install_signal_handlers=False)


async def test_a_failed_job_keeps_its_token_while_retries_remain(pool: AsyncConnectionPool) -> None:
    id = await accepted(pool, callbackToken='retrying')
    async with unreachable() as client:
        await run_once(pool, id, client, CollectRetry())
    assert await row(pool, id, 'status, callback_token, finished_at') == ('running', 'retrying', None)


async def test_a_job_out_of_retries_ends_failed_and_forgets_its_token(pool: AsyncConnectionPool) -> None:
    id = await accepted(pool, callbackToken='last')
    async with unreachable() as client:
        await run_once(pool, id, client, CollectRetry(max_retries=0))
    status, token, finished, error = await row(pool, id, 'status, callback_token, finished_at, last_error')
    assert (status, token) == ('failed', None) and finished is not None
    assert 'gave up after 1 attempt' in error and 'ECONNREFUSED' in error
