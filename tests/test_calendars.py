"""The organization's calendars (TASK-043, docs/data-model-spec.md section 4): periods it defines, listed or repeating, and a derived
part that says which period a date falls in, generated into the warehouse. On the service desk domain of test_definitions (DEC-038)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from bi import accounts, calendars, definitions, generate
from bi.connect.files import Storage, load_now

from .conftest import PoolFactory, database_url
from .fakes import csv_file
from .test_definitions import DESK, PASSWORD, TICKET

DB = 'bi_calendars_test'
SHIFTS: dict[str, Any] = {
    'label': {'en': 'Rotation', 'he': 'סבב'},
    'periods': [
        {'code': 'R1', 'starts': '2026-09-01', 'ends': '2026-10-15'},
        {'code': "R2 'late'", 'starts': '2026-10-20', 'ends': '2026-12-31', 'label': {'en': 'Second rotation'}},
    ],
}
FISCAL: dict[str, Any] = {'label': {'en': 'Budget year'}, 'repeat': {'every': 'year', 'starts': '07-01', 'named_by': 'end'}}


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    p = await make_pool(DB)
    await accounts.create_user(p, 'admin@example.org', 'Admin', PASSWORD, is_admin=True)
    await accounts.create_user(p, 'other@example.org', 'Other', PASSWORD)
    await definitions.save_draft(p, 'subject', 'desk', DESK, None)
    await definitions.approve(p, 'subject', 'desk', None)
    return p


@pytest.mark.parametrize(
    ('body', 'reason'),
    [
        ({**SHIFTS, 'periods': [*SHIFTS['periods'], {'code': 'R3', 'starts': '2026-10-01', 'ends': '2026-10-30'}]}, 'overlap'),
        ({**SHIFTS, 'periods': [*SHIFTS['periods'], {'code': 'R1', 'starts': '2027-01-01', 'ends': '2027-02-01'}]}, 'same code'),
        ({**SHIFTS, 'periods': [{'code': 'X', 'starts': '2026-02-01', 'ends': '2026-01-01'}]}, 'ends before it starts'),
        ({**FISCAL, 'periods': SHIFTS['periods']}, 'not both'),
        ({**FISCAL, 'repeat': {'every': 'year', 'starts': '02-30'}}, 'repeat.starts'),
    ],
)
def test_a_calendar_is_checked(body: dict[str, Any], reason: str) -> None:
    with pytest.raises(calendars.CalendarError, match=reason):
        calendars.parse(body)


@pytest.mark.parametrize(
    'repeat',
    [
        {'every': 'year', 'starts': '01-01'},
        {'every': 'year', 'starts': '07-01', 'named_by': 'end'},
        {'every': 'quarter', 'starts': '09-15'},
        {'every': 'quarter', 'starts': '04-28', 'named_by': 'end'},
    ],
)
async def test_the_generated_sql_finds_the_same_period_as_the_definition(pool: AsyncConnectionPool, repeat: dict[str, Any]) -> None:
    calendar = calendars.parse({'label': {'en': 'x'}, 'repeat': repeat})
    days = [dt.date(2025, 1, 1) + dt.timedelta(days=n) for n in range(800)]
    query = sql.SQL('select d::date, {} from unnest(%s::date[]) d').format(sql.SQL(generate.period_sql('d::date', calendar)))
    async with pool.connection() as conn:
        rows = await (await conn.execute(query, [days])).fetchall()
    assert [code for _, code in rows] == [calendar.code_for(d) for d, _ in rows]


def test_a_repeating_year_is_named_as_the_organization_says() -> None:
    fiscal = calendars.parse(FISCAL)
    assert fiscal.code_for(dt.date(2026, 6, 30)) == '2026' and fiscal.code_for(dt.date(2026, 7, 1)) == '2027'
    quarters = calendars.parse({'label': {'en': 'q'}, 'repeat': {'every': 'quarter', 'starts': '07-01'}})
    assert quarters.code_for(dt.date(2026, 7, 1)) == '2026-Q1' and quarters.code_for(dt.date(2027, 6, 30)) == '2026-Q4'


async def test_an_event_is_cut_by_the_organizations_periods(pool: AsyncConnectionPool, tmp_path: Path) -> None:
    derived = [
        {'name': 'rotation', 'rule': {'type': 'period', 'part': 'opened_on', 'calendar': 'shifts'}},
        {'name': 'budget_year', 'rule': {'type': 'period', 'part': 'opened_on', 'calendar': 'fiscal'}},
    ]
    with pytest.raises(definitions.DefinitionError, match='no calendar named fiscal, shifts'):
        await definitions.save_draft(pool, 'event', 'ticket', {**TICKET, 'derived': derived}, None)
    bad = {**TICKET, 'derived': [{'name': 'r', 'rule': {'type': 'period', 'part': 'queue', 'calendar': 'shifts'}}]}
    with pytest.raises(definitions.DefinitionError, match='not a date'):
        await definitions.save_draft(pool, 'event', 'ticket', bad, None)

    await calendars.save(pool, 'shifts', SHIFTS, None)
    await calendars.save(pool, 'fiscal', FISCAL, None)
    await definitions.save_draft(pool, 'event', 'ticket', {**TICKET, 'derived': derived}, None)
    await definitions.approve(pool, 'event', 'ticket', None)
    with pytest.raises(calendars.CalendarError, match='used by ticket'):
        await calendars.remove(pool, 'shifts')

    rows = [
        ['T-1', dt.date(2026, 9, 1), 'Network', '30'],
        ['T-2', dt.date(2026, 10, 17), 'Mail', '10'],  # between the rotations: no period
        ['T-3', dt.date(2026, 12, 31), 'Mail', '10'],
    ]
    path = csv_file(tmp_path / 'tickets.csv', rows, header=['ticket_id', 'opened_on', 'queue', 'minutes'])
    ended = await load_now(
        pool, Storage(f'file://{tmp_path}/files'), database_url(DB), path, source_name='Desk', dataset='ticket', as_of=dt.date(2027, 1, 1)
    )
    assert ended['status'] == 'loaded', ended
    with psycopg.connect(database_url(DB)) as conn:
        built = conn.execute('select ticket_id, rotation, budget_year from analytics.ticket order by ticket_id').fetchall()
    assert built == [('T-1', 'R1', '2027'), ('T-2', None, '2027'), ('T-3', "R2 'late'", '2027')]


async def test_only_an_admin_changes_the_calendars(pool: AsyncConnectionPool, tmp_path: Path) -> None:
    from .test_app import APP, app_for

    async with app_for(pool, tmp_path) as client:

        async def sign_in(email: str) -> None:
            client.cookies.clear()
            assert (await client.post('/app/api/session', json={'email': email, 'password': PASSWORD}, headers=APP)).status_code == 200

        await sign_in('other@example.org')
        assert (await client.put('/app/api/calendars/seasons', json=FISCAL, headers=APP)).status_code == 403
        listed = (await client.get('/app/api/calendars')).json()['calendars']
        assert all(c['name'] != 'seasons' for c in listed)
        await sign_in('admin@example.org')
        assert (
            await client.put('/app/api/calendars/seasons', json={**FISCAL, 'periods': SHIFTS['periods']}, headers=APP)
        ).status_code == 422
        assert (await client.put('/app/api/calendars/Bad-Name', json=FISCAL, headers=APP)).status_code == 422
        saved = await client.put('/app/api/calendars/seasons', json=FISCAL, headers=APP)
        assert saved.status_code == 200 and any(c['name'] == 'seasons' and c['used_by'] == [] for c in saved.json()['calendars'])
        assert (await client.delete('/app/api/calendars/seasons', headers=APP)).status_code == 200
        assert (await client.delete('/app/api/calendars/seasons', headers=APP)).status_code == 409
