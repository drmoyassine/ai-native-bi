"""Files are not made to fit (ROADMAP-009): an export with other column names is loaded as it is, its columns are matched to what the
dataset needs, a person approves a match that is not exact, and only then is the dataset's analytics built from it."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import httpx
import pytest
from psycopg_pool import AsyncConnectionPool

from bi import accounts, mapping
from bi.api import AppDeps, create_app
from bi.app import AppContext
from bi.uploads import Storage, process_upload, rebuild

from .conftest import AMS, PoolFactory, database_url
from .fakes import FALL, HEADER, students, xlsx

PASSWORD = 'a-long-password-0123'
APP = {'x-bi-app': '1'}
# What an export from another system might look like: other names, an extra column, the terms' code in a column called Semester.
EXPORT = ['Student Number', 'Semester', 'Semester Label', 'Start Date', 'Major', 'Student Level', 'Enrollment Status', 'Advisor Notes']


def export_rows() -> list[list[object]]:
    return [
        ['S-1', 'F26', 'Fall 2026', dt.date(2026, 8, 24), 'BSME', 'Bachelor', 'Enrolled', 'x'],
        ['S-2', 'F26', 'Fall 2026', dt.date(2026, 8, 24), 'BSCE', 'Bachelor', 'Enrolled', None],
    ]


def test_columns_are_matched_by_their_own_name_first_then_by_the_names_exports_use() -> None:
    exact, ok = mapping.propose('enrollment', ['student_id', 'Term Code', 'TERM', 'term start', 'extra'])
    assert ok and exact['student_id'] == 'student_id' and exact['term_code'] == 'Term Code' and exact['term'] == 'TERM'
    assert exact['term_start'] == 'term start' and exact['program'] is None
    guess, ok = mapping.propose('enrollment', EXPORT)
    assert not ok  # every needed part is found, but not by its own name: a person looks
    assert guess['student_id'] == 'Student Number' and guess['term_code'] == 'Semester' and guess['term_start'] == 'Start Date'
    assert guess['program'] == 'Major' and guess['term'] is None
    # a column named by one part is not taken by another through an alias
    assert mapping.propose('enrollment', ['Term', 'Student ID', 'Term Start'])[0]['term_code'] is None
    with pytest.raises(mapping.MappingError, match='no column is chosen for: term_code'):
        mapping.check('enrollment', {'student_id': 'a', 'term_start': 'b'}, ['a', 'b'])
    with pytest.raises(mapping.MappingError, match='no column "zzz"'):
        mapping.check('enrollment', {'student_id': 'zzz'}, ['a'])


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    p = await make_pool('bi_mapping_test')
    await accounts.create_user(p, 'ie@example.edu', 'IE Office', PASSWORD, is_admin=True)
    return p


async def test_an_export_with_other_names_waits_for_a_person_then_builds_and_a_file_of_another_layout_says_so(
    pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    queued: list[str] = []
    rebuilt: list[str] = []

    async def enqueue(id: str) -> None:
        queued.append(id)

    async def enqueue_rebuild(dataset: str) -> None:
        rebuilt.append(dataset)

    storage = Storage(f'file://{tmp_path}/files')
    context = AppContext(pool=pool, storage=storage, enqueue_load=enqueue, enqueue_rebuild=enqueue_rebuild, cube=None, cookie_secure=False)
    api = create_app(AppDeps(pool=pool, api_key='k' * 16, ams_origin=AMS, enqueue=enqueue, app=context))
    db = database_url('bi_mapping_test')

    async def upload(client: httpx.AsyncClient, name: str, header: list[str], rows: list[list[object]]) -> str:
        data = xlsx(tmp_path / name, rows, header=header).read_bytes()
        res = await client.post(
            '/app/api/uploads', data={'dataset': 'enrollment', 'asOf': '2026-10-20'}, files={'file': (name, data)}, headers=APP
        )
        assert res.status_code == 202
        return queued[-1]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url='http://bi') as client:
        res = await client.post('/app/api/session', json={'email': 'ie@example.edu', 'password': PASSWORD}, headers=APP)
        assert res.status_code == 200

        first = await upload(client, 'other.xlsx', EXPORT, export_rows())
        assert await process_upload(pool, storage, db, first) == 'loaded'  # not a failure: the file is kept, its columns are known
        row = next(u for u in (await client.get('/app/api/uploads')).json()['uploads'] if u['id'] == first)
        assert row['status'] == 'loaded' and row['tests'] is None and 'Choose which column is which' in row['note']
        assert 'student_number' in row['note'] and 'advisor_notes' in row['note']  # the names raw keeps
        async with pool.connection() as conn:
            built = await (await conn.execute("select to_regclass('analytics.enrollment') is not null")).fetchone()
        assert built is not None and not built[0]  # nothing was built from columns nobody approved

        proposal = (await client.get('/app/api/datasets/enrollment/mapping')).json()
        assert proposal['status'] == 'proposed' and 'advisor_notes' in proposal['columns']
        assert proposal['mapping']['student_id'] == 'student_number'

        refused = await client.put('/app/api/datasets/enrollment/mapping', json={'mapping': {'student_id': 'student_number'}}, headers=APP)
        assert refused.status_code == 422 and 'term_code' in refused.json()['detail']
        assert (await client.put('/app/api/datasets/enrollment/mapping', json={'mapping': proposal['mapping']})).status_code == 403
        approved = await client.put('/app/api/datasets/enrollment/mapping', json={'mapping': proposal['mapping']}, headers=APP)
        assert approved.status_code == 200 and rebuilt == ['enrollment']

        built_models, note = await rebuild(pool, db, 'enrollment')  # what the worker does for the queued rebuild
        assert built_models is not None and note is None and built_models.tests > 0
        async with pool.connection() as conn:
            rows = await (
                await conn.execute('select student_id, term_code, program, level, status, term_start from analytics.enrollment order by 1')
            ).fetchall()
        assert rows == [
            ('S-1', 'F26', 'BSME', 'bachelor', 'enrolled', dt.date(2026, 8, 24)),
            ('S-2', 'F26', 'BSCE', 'bachelor', 'enrolled', dt.date(2026, 8, 24)),
        ]
        assert (await client.get('/app/api/datasets/enrollment/mapping')).json()['status'] == 'approved'

        # The same export again builds with the approved mapping, nobody asked.
        second = await upload(
            client,
            'again.xlsx',
            EXPORT,
            [*export_rows(), ['S-3', 'F26', 'Fall 2026', dt.date(2026, 8, 24), 'MSDS', 'Master', 'Enrolled', None]],
        )
        assert await process_upload(pool, storage, db, second) == 'loaded'
        # A file with another layout (the dataset's own names) cannot be read together with the earlier ones through one mapping: the
        # upload fails, says which files, and the analytics stay as they were.
        third = await upload(client, 'plain.xlsx', HEADER, students(FALL, (1001, 'BSME', 'Bachelor')))
        assert await process_upload(pool, storage, db, third) == 'failed'
        listed = {u['id']: u for u in (await client.get('/app/api/uploads')).json()['uploads']}
        assert listed[second]['tests'] > 0 and listed[second]['note'] is None
        assert 'another layout' in listed[third]['error'] and 'other.xlsx' in listed[third]['error']
        async with pool.connection() as conn:
            count = await (await conn.execute('select count(*) from analytics.enrollment')).fetchone()
        assert count is not None and count[0] == 3
