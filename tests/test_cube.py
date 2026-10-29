"""End to end on the real Cube: a made-up file -> raw -> dbt -> analytics -> Cube -> the worker -> the AMS's callback."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from bi.collect import Accepted, accept_collect
from bi.connect.files import Storage, load_now
from bi.cube import CubeClient
from bi.db import migrate
from bi.metrics import CubeMetricSource
from bi.queue import CollectDeps, process_collect
from bi.sources import SourceRegistry

from .conftest import ADMIN, AMS, CUBE_DB
from .fakes import FALL, SPRING, students, xlsx

DB = ADMIN.rsplit('/', 1)[0] + f'/{CUBE_DB}'


@pytest.fixture(scope='module')
async def pool(cube_env: tuple[str, str], tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[AsyncConnectionPool]:
    with psycopg.connect(ADMIN, autocommit=True) as admin:
        if not admin.execute('select 1 from pg_database where datname = %s', [CUBE_DB]).fetchone():
            admin.execute(f'create database {CUBE_DB}')
    with psycopg.connect(DB, autocommit=True) as conn:
        # A database for these tests only (Cube keeps its connection, so it is reset rather than dropped).
        for schema in ('raw', 'draft', 'staging', 'analytics', 'public'):
            conn.execute(f'drop schema if exists {schema} cascade')
        conn.execute('create schema public')
    files = tmp_path_factory.mktemp('files')
    fall = students(FALL, (1001, 'BSME', 'Bachelor'), (1002, 'BSME', 'Bachelor'), (1003, 'BSCE', 'Bachelor'), (1004, 'MSDS', 'Master'))
    spring = students(SPRING, (1001, 'BSME', 'Bachelor'))
    async with AsyncConnectionPool(DB, open=False) as p:
        await migrate(p)
        for name, rows in (('fall.xlsx', fall), ('spring.xlsx', spring)):
            path = xlsx(files / name, rows)
            ended = await load_now(p, Storage(f'file://{files}'), DB, path, source_name='Registrar', dataset='enrollment',
                                   as_of=dt.date(2026, 10, 20))  # fmt: skip
            assert ended['status'] == 'loaded', ended
        yield p


def collect_request(period: dict[str, Any], token: str) -> dict[str, Any]:
    return {
        'runId': 'run-1',
        'evidence': {
            'id': 'ev-1',
            'title': 'Enrollment headcount',
            'type': 'dataset',
            'definition': 'Students enrolled per program',
            'columns': [
                {'key': 'program', 'label': 'Program', 'type': 'text', 'required': True},
                {'key': 'n', 'label': 'Headcount', 'type': 'integer', 'required': True},
            ],
        },
        'period': period,
        'query': {
            'metric': 'enrollment_headcount',
            'dimensions': ['program'],
            'filters': [{'field': 'level', 'op': 'eq', 'value': 'bachelor'}],
            'grain': 'semester',
        },
        'callbackUrl': f'{AMS}/api/bi/v0/runs/run-1/supply',
        'callbackToken': token,
    }


async def work(pool: AsyncConnectionPool, cube_env: tuple[str, str], body: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    accepted = await accept_collect(pool, body, AMS)
    assert isinstance(accepted, Accepted)
    calls: list[dict[str, Any]] = []

    def ams(req: httpx.Request) -> httpx.Response:
        calls.append(json.loads(req.content))
        return httpx.Response(200, json={})

    async with httpx.AsyncClient() as cube_http, httpx.AsyncClient(transport=httpx.MockTransport(ams)) as ams_http:
        source = CubeMetricSource(CubeClient(cube_http, *cube_env))
        deps = CollectDeps(pool=pool, sources=SourceRegistry([source]), callback_timeout_ms=5000, client=ams_http)
        return await process_collect(deps, accepted.id), calls


async def test_answers_the_ams_from_cube(pool: AsyncConnectionPool, cube_env: tuple[str, str]) -> None:
    outcome, calls = await work(pool, cube_env, collect_request({'label': 'Fall 2026', 'start': '2026-08-24', 'end': '2026-12-18'}, 'fall'))
    assert outcome == 'supplied'
    assert len(calls) == 1
    body = calls[0]
    assert sorted(body['rows'], key=lambda r: r['program']) == [{'program': 'BSCE', 'n': 1}, {'program': 'BSME', 'n': 2}]
    assert body['asOf'] == '2026-10-20'
    assert body['lineage']['metric'] == 'enrollment_headcount' and body['lineage']['model'] == 'analytics.enrollment'


async def test_a_period_without_data_is_no_supply(pool: AsyncConnectionPool, cube_env: tuple[str, str]) -> None:
    outcome, calls = await work(
        pool, cube_env, collect_request({'label': 'Fall 2030', 'start': '2030-08-24', 'end': '2030-12-18'}, 'empty')
    )
    assert outcome == 'no_data'
    assert calls == []


async def test_the_agents_tools_work_on_the_real_cube(pool: AsyncConnectionPool, cube_env: tuple[str, str]) -> None:
    """Count measures come from Cube's own `aggType`, so small-cell hiding works on the real metadata; the as-of date rides along."""
    from bi.agent.suppress import count_measures
    from bi.agent.tools import AgentDeps, query_metric
    from bi.charts import ChartQuery

    async with httpx.AsyncClient() as http:
        cube = CubeClient(http, *cube_env)
        members = await cube.meta()
        assert 'enrollment.headcount' in count_measures(members) and 'enrollment.as_of' not in count_measures(members)

        class Ctx:  # the part of Pydantic AI's RunContext the tool reads
            deps = AgentDeps(
                pool=pool,
                cube=cube,
                user_id='u',
                conversation_id='c',
                run_id='r',
                suppression_threshold=2,
                emit=lambda t, p: asyncio.sleep(0),
            )

        query = ChartQuery.model_validate({'measures': ['enrollment.headcount'], 'dimensions': ['enrollment.program']})
        result = await query_metric(Ctx(), query)  # type: ignore[arg-type]
    rows = {r['enrollment.program']: r for r in result['rows']}
    assert rows['BSME']['enrollment.headcount'] == 2 and result['as_of'] == '2026-10-20'
    assert rows['BSCE']['enrollment.headcount'] is None and rows['BSCE']['suppressed'] == [
        'enrollment.headcount'
    ]  # one student: under the threshold of 2
    assert result['suppressed_cells'] >= 1 and 'enrollment.as_of' not in str(result['rows'])


async def test_before_anything_is_loaded_the_real_cube_means_no_data_not_failure(
    pool: AsyncConnectionPool, cube_env: tuple[str, str]
) -> None:
    """A fresh deployment has no analytics table until its first file is loaded: charts show no data and the AMS gets no supply."""
    from bi import tools
    from bi.charts import ChartDefinition
    from bi.cube import CubeNoData

    async with pool.connection() as conn:
        await conn.execute('alter table analytics.enrollment rename to enrollment_hidden')
    try:
        async with httpx.AsyncClient() as http:
            cube = CubeClient(http, *cube_env)
            with pytest.raises(CubeNoData):
                await cube.load({'measures': ['enrollment.headcount'], 'dimensions': ['enrollment.level']}, fresh=True)
            chart = ChartDefinition.model_validate(
                {'title': 'By level', 'query': {'measures': ['enrollment.headcount'], 'dimensions': ['enrollment.level']},
                 'visual': {'type': 'bar', 'x': 'enrollment.level'}}
            )  # fmt: skip
            assert await tools.chart_rows(cube, chart) == []
        outcome, calls = await work(
            pool, cube_env, collect_request({'label': 'Spring 2027', 'start': '2027-01-18', 'end': '2027-05-14'}, 'none')
        )
        # A period no other test asks for, so Cube has not cached its answer and really reads the (missing) table.
        assert outcome == 'no_data' and calls == []  # no supply, and not a failure to retry
    finally:
        async with pool.connection() as conn:
            await conn.execute('alter table analytics.enrollment_hidden rename to enrollment')


async def test_the_model_carries_the_organizations_words(cube_env: tuple[str, str]) -> None:
    """Words in other languages, synonyms and the glossary view come through Cube's /meta; search finds the metric by an Arabic synonym."""
    from bi import knowledge

    async with httpx.AsyncClient() as http:
        cube = CubeClient(http, *cube_env)
        members = await cube.meta()
        words = await cube.words()
    assert all(m['cube'] != 'Organization' for m in members)  # the view carries words, not metrics
    assert words['instructions'] and any(g['term']['en'] == 'Census date' for g in words['glossary'])
    found = knowledge.search(members, words, 'عدد المسجلين')
    assert found['members'][0]['name'] == 'enrollment.headcount'
