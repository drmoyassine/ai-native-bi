from __future__ import annotations

from typing import Any

import httpx
import pytest
from psycopg_pool import AsyncConnectionPool

from bi.api import AppDeps, create_app

from .conftest import AMS, PoolFactory

KEY = 'test-key-0123456789'


def body(run_id: str = 'run-1', token: str = 'tok-1') -> dict[str, Any]:
    return {
        'runId': run_id,
        'evidence': {'id': 'ev-1', 'title': 'Headcount', 'type': 'dataset', 'definition': None},
        'period': {'label': 'Fall 2026', 'start': '2026-08-24', 'end': None},
        'query': None,
        'callbackUrl': f'{AMS}/api/bi/v0/runs/{run_id}/supply',
        'callbackToken': token,
    }


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    return await make_pool('bi_api_test')


@pytest.fixture
async def api(pool: AsyncConnectionPool) -> Any:
    queued: list[str] = []

    async def enqueue(id: str) -> None:
        queued.append(id)

    app = create_app(AppDeps(pool=pool, api_key=KEY, ams_origin=AMS, enqueue=enqueue))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://bi') as client:
        client.queued = queued  # type: ignore[attr-defined]
        yield client


async def post(api: httpx.AsyncClient, path: str, b: Any, key: str | None = KEY) -> httpx.Response:
    return await api.post(path, json=b, headers={'authorization': f'Bearer {key}'} if key else {})


async def test_answers_202_and_queues_the_work_once_per_attempt_on_the_default_path_and_a_named_one(api: httpx.AsyncClient) -> None:
    assert (await post(api, '/ams/collect', body())).status_code == 202
    assert (await post(api, '/ams/collect', body())).status_code == 202
    assert (await post(api, '/ams/collect/warehouse', body('run-2'))).status_code == 202
    assert len(api.queued) == 2  # type: ignore[attr-defined]


async def test_refuses_a_wrong_key_a_body_that_does_not_fit_and_a_foreign_callback(api: httpx.AsyncClient) -> None:
    assert (await post(api, '/ams/collect', body(), 'wrong')).status_code == 401
    assert (await post(api, '/ams/collect', body(), None)).status_code == 401
    assert (await post(api, '/ams/collect', {'runId': 'x'})).status_code == 422
    bad_json = await api.post('/ams/collect', content=b'{', headers={'authorization': f'Bearer {KEY}'})
    assert bad_json.status_code == 400
    foreign = await post(api, '/ams/collect', {**body(), 'callbackUrl': 'https://evil.example.org/api/bi/v0/runs/run-1/supply'})
    assert foreign.status_code == 422
    assert foreign.json()['issues'][0]['path'] == 'callbackUrl'


async def test_refuses_a_bad_endpoint_name(api: httpx.AsyncClient) -> None:
    assert (await post(api, '/ams/collect/bad name', body())).status_code in (404, 422)


async def test_is_healthy(api: httpx.AsyncClient) -> None:
    assert (await api.get('/healthz')).status_code == 200
