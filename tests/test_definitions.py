"""Definitions (docs/data-model-spec.md, M1) and the models generated from them (M0b), on a second domain unlike the template's, so the
code path is shown to know none (DEC-037, DEC-038): a service desk's tickets."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from bi import accounts, definitions, generate, mapping
from bi.connect.files import Storage, load_now

from .conftest import PoolFactory, database_url
from .fakes import csv_file

DB = 'bi_definitions_test'
DESK: dict[str, Any] = {'label': {'en': 'Service desk'}, 'steward': 'lead@example.org'}
TICKET: dict[str, Any] = {
    'subject': 'desk',
    'label': {'en': 'Ticket', 'he': 'פנייה'},  # a right-to-left language's words, as data
    'grain': ['ticket_id'],
    'parts': [
        {'name': 'ticket_id', 'needed': True, 'expects': 'key', 'label': {'en': 'Ticket'}},
        {'name': 'opened_on', 'needed': True, 'expects': 'date', 'label': {'en': 'Opened'}},
        {'name': 'queue', 'normalize': 'lower', 'label': {'en': 'Queue'}},
        {'name': 'minutes', 'expects': 'number', 'label': {'en': 'Minutes to resolve'}},
    ],
}
PASSWORD = 'a-long-password-0123'


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    p = await make_pool(DB)
    await accounts.create_user(p, 'admin@example.org', 'Admin', PASSWORD, is_admin=True)
    await accounts.create_user(p, 'lead@example.org', 'Lead', PASSWORD)
    await accounts.create_user(p, 'other@example.org', 'Other', PASSWORD)
    return p


def test_generation_is_a_pure_function_of_the_event() -> None:
    event = definitions.parse('event', TICKET)
    files = generate.dbt_files({'ticket': event})
    staging = files['models/staging/stg_ticket.sql']
    assert 'cast(raw."opened_on" as date)' in staging and 'cast(raw."minutes" as numeric)' in staging
    assert 'lower(raw."queue")' in staging and 'latest' not in staging  # not a state: nothing replaces earlier loads
    assert "ref('stg_ticket')" in files['models/analytics/ticket.sql']
    assert '"ticket_id"' in files['models/generated.yml'] and generate.dbt_files({'ticket': event}) == files
    snapshot = definitions.parse('event', {**TICKET, 'snapshot_by': ['queue']})
    assert 'group by "queue"' in generate.staging_sql('ticket', snapshot)


@pytest.mark.parametrize(
    ('change', 'reason'),
    [
        ({'grain': ['nope']}, 'the grain names no part'),
        ({'parts': [{'name': 'as_of'}]}, 'may not be named as_of'),
        ({'parts': [{'name': 'a'}, {'name': 'a'}]}, 'same name'),
        ({'surprise': 1}, 'Extra inputs'),
    ],
)
def test_a_definition_is_checked(change: dict[str, Any], reason: str) -> None:
    with pytest.raises(definitions.DefinitionError, match=reason):
        definitions.parse('event', {**TICKET, **change})


async def test_drafts_are_approved_into_versions(pool: AsyncConnectionPool) -> None:
    with pytest.raises(definitions.DefinitionError, match='no approved subject'):
        await definitions.save_draft(pool, 'event', 'ticket', TICKET, None)
    assert await definitions.save_draft(pool, 'subject', 'desk', DESK, None) == 1
    assert 'desk' not in await definitions.current(pool, 'subject')  # a draft is not current
    await definitions.approve(pool, 'subject', 'desk', None)
    await definitions.save_draft(pool, 'event', 'ticket', TICKET, None)
    await definitions.approve(pool, 'event', 'ticket', None)
    changed = {**TICKET, 'label': {'en': 'Support ticket'}}
    assert await definitions.save_draft(pool, 'event', 'ticket', changed, None) == 2
    assert (await definitions.events(pool))['ticket'].label['en'] == 'Ticket'  # still the approved version
    entry = next(d for d in await definitions.listing(pool) if d['name'] == 'ticket')
    assert entry['current']['version'] == 1 and entry['draft']['version'] == 2
    await definitions.approve(pool, 'event', 'ticket', None)
    assert (await definitions.events(pool))['ticket'].label['en'] == 'Support ticket'
    with pytest.raises(definitions.DefinitionError, match='no draft'):
        await definitions.approve(pool, 'event', 'ticket', None)
    assert 'ticket' in await mapping.installed_datasets(pool)


async def test_any_approved_event_is_loaded_and_built_by_generated_models(pool: AsyncConnectionPool, tmp_path: Path) -> None:
    rows = [['T-1', dt.date(2026, 10, 1), 'Network', '30'], ['T-2', dt.date(2026, 10, 2), 'ACCESS', '']]
    path = csv_file(tmp_path / 'tickets.csv', rows, header=['ticket_id', 'opened_on', 'queue', 'minutes'])
    ended = await load_now(
        pool,
        Storage(f'file://{tmp_path}/files'),
        database_url(DB),
        path,
        source_name='Desk export',
        dataset='ticket',
        as_of=dt.date(2026, 10, 3),
    )
    assert ended['status'] == 'loaded', ended
    with psycopg.connect(database_url(DB)) as conn:
        built = conn.execute('select ticket_id, opened_on, queue, minutes from analytics.ticket order by ticket_id').fetchall()
    assert built == [('T-1', dt.date(2026, 10, 1), 'network', 30), ('T-2', dt.date(2026, 10, 2), 'access', None)]


async def test_a_template_never_overrides_the_organizations_own_definition_and_uninstalls_cleanly(pool: AsyncConnectionPool) -> None:
    own = {'subject': 'desk', 'label': {'en': 'Our own'}, 'parts': [{'name': 'x', 'needed': True}]}
    await definitions.save_draft(pool, 'event', 'enrollment', own, None)  # the template's event name, defined here first
    await definitions.approve(pool, 'event', 'enrollment', None)
    made = await definitions.install_template(pool, 'higher-education')  # already installed by the fixture: makes nothing new
    assert 'event:enrollment' not in made
    await definitions.uninstall_template(pool, 'higher-education')
    async with pool.connection() as conn:
        files = await (await conn.execute("select count(*) from cube_model.file where source like 'template:%'")).fetchone()
    assert files == (0,)
    assert 'academics' not in await definitions.current(pool, 'subject')
    assert (await definitions.events(pool))['enrollment'].label['en'] == 'Our own'  # what the organization defined stays
    await definitions.install_template(pool, 'higher-education')
    assert 'academics' in await definitions.current(pool, 'subject')


async def test_the_subjects_steward_drafts_and_approves_and_nobody_else(pool: AsyncConnectionPool, tmp_path: Path) -> None:
    from .test_app import APP, app_for

    async with app_for(pool, tmp_path) as client:

        async def sign_in(email: str) -> None:
            client.cookies.clear()
            assert (await client.post('/app/api/session', json={'email': email, 'password': PASSWORD}, headers=APP)).status_code == 200

        body = {**TICKET, 'label': {'en': 'Desk ticket'}}
        await sign_in('other@example.org')
        assert (await client.put('/app/api/model/event/ticket', json=body, headers=APP)).status_code == 403
        await sign_in('lead@example.org')
        assert (await client.put('/app/api/model/event/ticket', json=body, headers=APP)).status_code == 200
        await sign_in('other@example.org')
        assert (await client.post('/app/api/model/event/ticket/approve', headers=APP)).status_code == 403
        await sign_in('lead@example.org')
        assert (await client.post('/app/api/model/event/ticket/approve', headers=APP)).status_code == 200
        listed = (await client.get('/app/api/model')).json()['definitions']
        assert next(d for d in listed if d['name'] == 'ticket')['current']['body']['label'] == {'en': 'Desk ticket'}
        bad = await client.put('/app/api/model/event/ticket', json={**body, 'grain': ['nope']}, headers=APP)
        assert bad.status_code == 422


DERIVED: list[dict[str, Any]] = [
    {'name': 'team', 'rule': {'type': 'group', 'part': 'queue', 'groups': {'network': 'Infrastructure', 'access': 'Identity'}}},
    {'name': 'opened_month', 'rule': {'type': 'date_part', 'part': 'opened_on', 'unit': 'month'}},
    {'name': 'hours', 'rule': {'type': 'arithmetic', 'left': 'minutes', 'op': '/', 'right': 60}},
    {'name': 'speed', 'rule': {'type': 'bucket', 'part': 'minutes', 'edges': [15, 60], 'labels': ['fast', 'normal', 'slow']}},
    {'name': 'label', 'rule': {'type': 'join', 'parts': ['ticket_id', 'queue'], 'separator': ' / '}},
]


@pytest.mark.parametrize(
    ('derived', 'reason'),
    [
        ({'name': 'x', 'rule': {'type': 'date_part', 'part': 'queue', 'unit': 'year'}}, 'is not a date'),
        ({'name': 'x', 'rule': {'type': 'arithmetic', 'left': 'queue', 'op': '+', 'right': 1}}, 'not every part it uses is a number'),
        ({'name': 'queue', 'rule': {'type': 'first_of', 'parts': ['queue', 'ticket_id']}}, 'already used'),
        ({'name': 'x', 'rule': {'type': 'bucket', 'part': 'minutes', 'edges': [5, 1], 'labels': ['a', 'b', 'c']}}, 'must go up'),
        ({'name': 'x', 'rule': {'type': 'group', 'part': 'nope', 'groups': {'a': 'b'}}}, 'not a part'),
        ({'name': 'x', 'rule': {'type': 'sql', 'text': 'drop table'}}, 'does not match any of the expected tags'),
    ],
)
def test_a_derived_part_is_checked(derived: dict[str, Any], reason: str) -> None:
    with pytest.raises(definitions.DefinitionError, match=reason):
        definitions.parse('event', {**TICKET, 'derived': [derived]})


def test_a_derived_value_cannot_escape_its_literal() -> None:
    hostile = {'name': 'x', 'rule': {'type': 'group', 'part': 'queue', 'groups': {"a'); drop table x; --": '{{ evil }}'}}}
    sql = generate.staging_sql('ticket', definitions.parse('event', {**TICKET, 'derived': [hostile]}))
    assert "'a''); drop table x; --'" in sql and '{{ evil' not in sql


async def test_derived_parts_are_built_and_the_preview_says_what_changes(pool: AsyncConnectionPool, tmp_path: Path) -> None:
    body = {**TICKET, 'label': {'en': 'Ticket'}, 'derived': DERIVED}
    await definitions.save_draft(pool, 'event', 'ticket', body, None)
    preview = await definitions.changes(pool, 'event', 'ticket')
    assert 'adds the derived part "team"' in preview['changes'] and not preview['new']
    await definitions.approve(pool, 'event', 'ticket', None)
    rows = [['T-9', dt.date(2026, 11, 5), 'Network', '30'], ['T-10', dt.date(2026, 11, 6), 'Mail', '90']]
    path = csv_file(tmp_path / 'more.csv', rows, header=['ticket_id', 'opened_on', 'queue', 'minutes'])
    ended = await load_now(
        pool,
        Storage(f'file://{tmp_path}/files'),
        database_url(DB),
        path,
        source_name='Desk export',
        dataset='ticket',
        as_of=dt.date(2026, 11, 7),
    )
    assert ended['status'] == 'loaded', ended
    with psycopg.connect(database_url(DB)) as conn:
        built = conn.execute(
            'select team, opened_month, round(hours, 2), speed, label from analytics.ticket'
            " where ticket_id in ('T-9', 'T-10') order by ticket_id"
        ).fetchall()
    assert built == [(None, 11, 1.5, 'slow', 'T-10 / mail'), ('Infrastructure', 11, 0.5, 'normal', 'T-9 / network')]

    shrunk = {**body, 'parts': [p for p in TICKET['parts'] if p['name'] != 'queue'], 'derived': []}
    await definitions.save_draft(pool, 'event', 'ticket', shrunk, None)
    preview = await definitions.changes(pool, 'event', 'ticket')
    assert 'removes the part "queue"' in preview['changes'] and 'removes the derived part "team"' in preview['changes']
    assert any('supply "queue"' in w for w in preview['warnings'])
