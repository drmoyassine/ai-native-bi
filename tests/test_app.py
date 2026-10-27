from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from psycopg_pool import AsyncConnectionPool
from pydantic import ValidationError

from bi import accounts
from bi.api import AppDeps, create_app
from bi.app import AppContext
from bi.charts import ChartDefinition, cube_query, unknown_members
from bi.cube import CubeClient, CubeError, CubeNoData
from bi.uploads import Storage, process_upload

from .conftest import AMS, PoolFactory, database_url
from .fakes import FALL, students, xlsx

PASSWORD = 'a-long-password-0123'
APP = {'x-bi-app': '1'}
MEMBERS = [
    {'name': 'enrollment.headcount', 'kind': 'measure', 'title': 'Headcount', 'type': 'number'},
    {'name': 'enrollment.program', 'kind': 'dimension', 'title': 'Program', 'type': 'string'},
    {'name': 'enrollment.term_start', 'kind': 'dimension', 'title': 'Term start', 'type': 'time'},
]


class FakeCube:
    def __init__(self) -> None:
        self.queries: list[dict[str, Any]] = []
        self.fail: Exception | None = None

    async def meta(self) -> list[dict[str, Any]]:
        return MEMBERS

    async def load(self, query: dict[str, Any], fresh: bool = False) -> list[dict[str, Any]]:
        self.queries.append(query)
        if self.fail:
            raise self.fail
        if query.get('timeDimensions', [{}])[0].get('granularity'):
            return [
                {
                    'enrollment.term_start.year': '2026-01-01T00:00:00.000',
                    'enrollment.term_start': '2026-01-01T00:00:00.000',
                    'enrollment.headcount': '3',
                }
            ]
        return [{'enrollment.program': 'BSME', 'enrollment.headcount': '2'}]


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    p = await make_pool('bi_app_test')
    await accounts.create_user(p, 'ie@example.edu', 'IE Office', PASSWORD, is_admin=True)
    return p


@pytest.fixture
async def app(pool: AsyncConnectionPool, tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, list[str], FakeCube]]:
    queued: list[str] = []
    cube = FakeCube()

    async def enqueue(id: str) -> None:
        queued.append(id)

    async def enqueue_collect(id: str) -> None:
        pass

    context = AppContext(pool=pool, storage=Storage(f'file://{tmp_path}/files'), enqueue_load=enqueue, cube=cube, cookie_secure=False)  # type: ignore[arg-type]
    web = tmp_path / 'web'
    web.mkdir()
    (web / 'index.html').write_text('<!doctype html><title>BI</title>')
    api = create_app(AppDeps(pool=pool, api_key='k' * 16, ams_origin=AMS, enqueue=enqueue_collect, app=context, web_dir=str(web)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url='http://bi') as client:
        yield client, queued, cube


async def signed_in(client: httpx.AsyncClient) -> None:
    res = await client.post('/app/api/session', json={'email': 'IE@example.edu', 'password': PASSWORD}, headers=APP)
    assert res.status_code == 200


async def test_signs_in_with_an_httponly_strict_cookie_and_out_again(app: tuple[httpx.AsyncClient, list[str], FakeCube]) -> None:
    client, _, _ = app
    assert (await client.get('/app/api/me')).status_code == 401
    assert (
        await client.post('/app/api/session', json={'email': 'ie@example.edu', 'password': 'wrong-password-123'}, headers=APP)
    ).status_code == 401
    assert (
        await client.post('/app/api/session', json={'email': 'nobody@example.edu', 'password': PASSWORD}, headers=APP)
    ).status_code == 401
    assert (await client.post('/app/api/session', json={'email': 'ie@example.edu', 'password': PASSWORD})).status_code == 403
    res = await client.post('/app/api/session', json={'email': 'ie@example.edu', 'password': PASSWORD}, headers=APP)
    cookie = res.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie
    me = (await client.get('/app/api/me')).json()
    assert me['user']['email'] == 'ie@example.edu' and me['datasets'] == ['enrollment']
    assert (await client.delete('/app/api/session', headers=APP)).status_code == 204
    client.cookies.clear()
    assert (await client.get('/app/api/me')).status_code == 401


async def test_a_change_needs_the_app_header_even_when_signed_in(
    app: tuple[httpx.AsyncClient, list[str], FakeCube], tmp_path: Path
) -> None:
    client, queued, _ = app
    await signed_in(client)
    path = xlsx(tmp_path / 'fall.xlsx', students(FALL, (1001, 'BSME', 'Bachelor')))
    res = await client.post(
        '/app/api/uploads', data={'dataset': 'enrollment', 'asOf': '2026-10-20'}, files={'file': ('fall.xlsx', path.read_bytes())}
    )
    assert res.status_code == 403 and queued == []


async def test_takes_an_upload_and_refuses_what_it_cannot_load(app: tuple[httpx.AsyncClient, list[str], FakeCube], tmp_path: Path) -> None:
    client, queued, _ = app
    await signed_in(client)
    data = xlsx(tmp_path / 'fall.xlsx', students(FALL, (1001, 'BSME', 'Bachelor'))).read_bytes()

    async def post(name: str, dataset: str = 'enrollment', as_of: str = '2026-10-20', content: bytes = data) -> httpx.Response:
        return await client.post('/app/api/uploads', data={'dataset': dataset, 'asOf': as_of}, files={'file': (name, content)}, headers=APP)

    assert (await post('notes.pdf')).status_code == 422
    assert (await post('fall.xlsx', dataset='payroll')).status_code == 422
    assert (await post('fall.xlsx', as_of=(dt.date.today() + dt.timedelta(days=1)).isoformat())).status_code == 422
    assert (await post('empty.csv', content=b'')).status_code == 422
    res = await post('../../etc/fall 2026.xlsx')
    assert res.status_code == 202 and queued == [res.json()['id']]
    stored = list((tmp_path / 'files' / 'incoming').rglob('*.xlsx'))
    assert [p.name for p in stored] == ['fall 2026.xlsx'] and stored[0].read_bytes() == data
    listed = (await client.get('/app/api/uploads')).json()['uploads']
    assert listed[0]['status'] == 'queued' and listed[0]['name'] == 'IE Office'


async def test_the_worker_loads_an_upload_or_says_why_it_failed(
    pool: AsyncConnectionPool, app: tuple[httpx.AsyncClient, list[str], FakeCube], tmp_path: Path
) -> None:
    client, queued, _ = app
    await signed_in(client)
    storage = Storage(f'file://{tmp_path}/files')
    good = xlsx(tmp_path / 'good.xlsx', students(FALL, (1001, 'BSME', 'Bachelor'), (1002, 'BSCE', 'Bachelor'))).read_bytes()
    dup = xlsx(tmp_path / 'dup.xlsx', students(FALL, (1001, 'BSME', 'Bachelor'), (1001, 'BSCE', 'Bachelor'))).read_bytes()
    for name, content in (('good.xlsx', good), ('dup.xlsx', dup)):
        res = await client.post(
            '/app/api/uploads', data={'dataset': 'enrollment', 'asOf': '2026-10-20'}, files={'file': (name, content)}, headers=APP
        )
        assert res.status_code == 202
    good_id, dup_id = queued
    db = database_url('bi_app_test')
    assert await process_upload(pool, storage, db, good_id) == 'loaded'
    assert await process_upload(pool, storage, db, good_id) == 'skipped'
    assert await process_upload(pool, storage, db, dup_id) == 'failed'
    by_id = {u['id']: u for u in (await client.get('/app/api/uploads')).json()['uploads']}
    assert by_id[good_id]['status'] == 'loaded' and by_id[good_id]['rows'] == 2 and by_id[good_id]['tests'] > 0
    assert by_id[dup_id]['status'] == 'failed' and 'unique' in by_id[dup_id]['error']


async def test_charts_only_governed_members_and_returns_cubes_rows(app: tuple[httpx.AsyncClient, list[str], FakeCube]) -> None:
    client, _, cube = app
    await signed_in(client)
    assert [m['name'] for m in (await client.get('/app/api/members')).json()['members']] == [m['name'] for m in MEMBERS]
    chart = {
        'title': 'Headcount by program',
        'query': {'measures': ['enrollment.headcount'], 'dimensions': ['enrollment.program']},
        'visual': {'type': 'bar', 'x': 'enrollment.program'},
    }
    res = await client.post('/app/api/charts/data', json=chart, headers=APP)
    assert res.json() == {'rows': [{'enrollment.program': 'BSME', 'enrollment.headcount': '2'}]}
    ungoverned = chart | {'query': {'measures': ['enrollment.student_id'], 'dimensions': ['enrollment.program']}}
    assert (await client.post('/app/api/charts/data', json=ungoverned, headers=APP)).status_code == 422
    by_year = {
        'title': 'Headcount by year',
        'query': {'measures': ['enrollment.headcount'], 'time': {'dimension': 'enrollment.term_start', 'granularity': 'year'}},
        'visual': {'type': 'line', 'x': 'enrollment.term_start'},
    }
    rows = (await client.post('/app/api/charts/data', json=by_year, headers=APP)).json()['rows']
    assert rows == [{'enrollment.term_start': '2026-01-01T00:00:00.000', 'enrollment.headcount': '3'}]
    assert cube.queries[-1]['timeDimensions'] == [{'dimension': 'enrollment.term_start', 'granularity': 'year'}]


async def test_nothing_loaded_yet_is_no_data_and_a_cube_failure_says_why_without_a_gateway_status(
    app: tuple[httpx.AsyncClient, list[str], FakeCube],
) -> None:
    client, _, cube = app
    await signed_in(client)
    chart = {
        'title': 'Headcount by level',
        'query': {'measures': ['enrollment.headcount'], 'dimensions': ['enrollment.program']},
        'visual': {'type': 'bar', 'x': 'enrollment.program'},
    }
    try:
        cube.fail = CubeNoData('Cube answered 400: Error: relation "analytics.enrollment" does not exist')
        res = await client.post('/app/api/charts/data', json=chart, headers=APP)
        assert res.status_code == 200 and res.json() == {'rows': []}  # the page says "No data", not an outage
        cube.fail = CubeError('Cube answered 500: out of memory')
        res = await client.post('/app/api/charts/data', json=chart, headers=APP)
        # Not 502/503/504: a proxy in front replaces those with its own page and the reason is lost.
        assert res.status_code == 424 and 'out of memory' in res.json()['detail']
    finally:
        cube.fail = None


async def test_the_cube_client_tells_a_missing_table_from_a_failure() -> None:
    def cube(request: httpx.Request) -> httpx.Response:
        if b'missing' in request.content:
            return httpx.Response(400, json={'error': 'Error: relation "analytics.enrollment" does not exist'})
        return httpx.Response(400, json={'error': 'Error: column "x" does not exist'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(cube)) as http:
        client = CubeClient(http, 'http://cube:4000', 's' * 32)
        with pytest.raises(CubeNoData):
            await client.load({'measures': ['missing']})
        with pytest.raises(CubeError) as other:
            await client.load({'measures': ['enrollment.headcount']})
        assert not isinstance(other.value, CubeNoData)


async def test_serves_the_web_app_beside_the_apis(app: tuple[httpx.AsyncClient, list[str], FakeCube]) -> None:
    client, _, _ = app
    assert '<title>BI</title>' in (await client.get('/')).text
    assert (await client.get('/healthz')).json() == {'ok': True}


@pytest.mark.parametrize(
    ('visual', 'query', 'reason'),
    [
        ({'type': 'number'}, {'measures': ['a.m'], 'dimensions': ['a.d']}, 'one measure, without dimensions'),
        ({'type': 'bar'}, {'measures': ['a.m'], 'dimensions': ['a.d']}, 'needs x'),
        ({'type': 'pie', 'x': 'a.d'}, {'measures': ['a.m', 'a.n'], 'dimensions': ['a.d']}, 'one measure by one dimension'),
        ({'type': 'bar', 'x': 'a.d', 'series': 'a.d'}, {'measures': ['a.m'], 'dimensions': ['a.d']}, 'series is another dimension'),
    ],
)
def test_a_definition_whose_visual_does_not_fit_its_query_is_refused(visual: dict[str, Any], query: dict[str, Any], reason: str) -> None:
    with pytest.raises(ValidationError, match=reason):
        ChartDefinition.model_validate({'title': 't', 'query': query, 'visual': visual})


def test_a_definition_is_a_governed_cube_query() -> None:
    chart = ChartDefinition.model_validate(
        {
            'title': 'Bachelor headcount',
            'query': {
                'measures': ['enrollment.headcount'],
                'dimensions': ['enrollment.program'],
                'filters': [{'member': 'enrollment.level', 'operator': 'equals', 'values': ['bachelor']}],
                'time': {'dimension': 'enrollment.term_start', 'dateRange': ['2026-08-24', '2026-12-18']},
            },
            'visual': {'type': 'table'},
        }
    )
    assert cube_query(chart)['timeDimensions'] == [{'dimension': 'enrollment.term_start', 'dateRange': ['2026-08-24', '2026-12-18']}]
    assert unknown_members(chart, MEMBERS) == ['enrollment.level']
    with pytest.raises(ValidationError):
        ChartDefinition.model_validate({'title': 't', 'query': {'measures': ['x']}, 'visual': {'type': 'table'}, 'sql': 'select 1'})


async def test_accounts_refuse_weak_passwords_duplicates_and_disabled_users(pool: AsyncConnectionPool) -> None:
    with pytest.raises(accounts.AccountError, match='at least 12'):
        await accounts.create_user(pool, 'a@example.edu', 'A', 'short')
    with pytest.raises(accounts.AccountError, match='already has an account'):
        await accounts.create_user(pool, 'IE@EXAMPLE.EDU', 'Again', PASSWORD)
    user = await accounts.create_user(pool, 'gone@example.edu', 'Gone', PASSWORD)
    signed = await accounts.sign_in(pool, 'gone@example.edu', PASSWORD)
    assert signed is not None
    async with pool.connection() as conn:
        await conn.execute('update app_user set disabled_at = now() where id = %s', [user.id])
    assert await accounts.session_user(pool, signed[1]) is None
    assert await accounts.sign_in(pool, 'gone@example.edu', PASSWORD) is None
