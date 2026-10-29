"""Column decisions at review (Connect data C1b, docs/connect-data-spec.md § 6.7): a person says what is personal, leaves out what the
BI need not hold, fixes a column's kind (and sees what does not fit), names a row key, and the decisions hold for every later sync."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from bi import accounts
from bi.connect import files, store
from bi.connect.files import Storage, process_sync, receive

from .conftest import PoolFactory, database_url
from .fakes import csv_file

DB = 'bi_columns_test'
HEADER = ['Record', 'Civil ID', 'Phone', 'Gender', 'Opened', 'Amount']


def rows(n: int = 24) -> list[list[Any]]:
    out: list[list[Any]] = [
        [f'R-{i}', f'2890{i:08d}', f'+965 5{i:07d}', 'F' if i % 2 else 'M', dt.date(2026, 9, 1 + i % 28).isoformat(), str(i * 10)]
        for i in range(1, n + 1)
    ]
    out[0][4], out[1][4] = 'soon', '31/02/2026'  # two values that are not dates
    return out


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    p = await make_pool(DB)
    await accounts.create_user(p, 'admin@example.org', 'Admin', 'a-long-password-0123', is_admin=True)
    return p


async def waiting(pool: AsyncConnectionPool, tmp_path: Path, name: str) -> tuple[str, Storage]:
    storage = Storage(f'file://{tmp_path}/files')
    source_id = await store.create_source(pool, name=name, type='file', dataset=None, owner=None)
    path = csv_file(tmp_path / f'{name}.csv', rows(), header=HEADER)
    with path.open('rb') as data:
        sync_id = await receive(pool, storage, source_id=source_id, user_id=None, as_of=dt.date(2026, 10, 1), sheet=None,
                                file_name=path.name, data=data)  # fmt: skip
    assert await process_sync(pool, storage, database_url(DB), sync_id, 2) == 'review'
    return sync_id, storage


def column(review: dict[str, Any], name: str) -> dict[str, Any]:
    return next(c for c in review['columns'] if c['name'] == name)


async def test_a_person_decides_each_column_and_the_decisions_hold(pool: AsyncConnectionPool, tmp_path: Path) -> None:
    sync_id, storage = await waiting(pool, tmp_path, 'Desk export')
    first = await files.review(pool, sync_id)
    assert first is not None
    assert column(first, 'Civil ID')['kind'] == 'personal' and column(first, 'Civil ID')['suggest_leave_out']
    assert column(first, 'Phone')['suggest_leave_out'] and not column(first, 'Opened')['suggest_leave_out']

    assert column(first, 'Gender')['detected_describing'] and not column(first, 'Gender')['suggest_leave_out']  # counted, kept
    with pytest.raises(files.DecisionError, match='say why'):
        await files.decide(pool, sync_id, {'Phone': {'personal': 'none'}}, None, None, 2)
    with pytest.raises(files.DecisionError, match='no column'):
        await files.decide(pool, sync_id, {'Shoe size': {'keep': False}}, None, None, 2)
    with pytest.raises(files.DecisionError, match='row key cannot be left out'):
        await files.decide(pool, sync_id, {'Phone': {'keep': False}}, ['Phone'], None, 2)

    await files.decide(
        pool,
        sync_id,
        {
            'Civil ID': {'personal': 'identifying', 'keep': False},
            'Phone': {'keep': False},
            'Gender': {'personal': 'describing', 'reason': 'counted by, never shown alone'},
            'Opened': {'kind': 'date', 'label': {'en': 'Opened on'}},
        },
        ['Record'],
        None,
        2,
    )
    after = await files.review(pool, sync_id)
    assert after is not None
    gender = column(after, 'Gender')
    assert gender['kind'] == 'category' and gender['decision']['personal'] == 'describing'  # counted, small counts hidden
    assert column(after, 'Opened')['kind'] == 'date' and column(after, 'Opened')['invalid'] == 2
    assert 'do not fit' in column(after, 'Opened')['summary']
    assert column(after, 'Opened')['decision']['label'] == {'en': 'Opened on'}
    assert after['row_key'] == {'columns': ['Record'], 'check': {'empty': 0, 'repeated': 0}}
    assert not column(after, 'Civil ID')['suggest_leave_out']  # decided

    await files.approve(pool, sync_id, None, None, 'admin@example.org')  # type: ignore[arg-type]
    assert await process_sync(pool, storage, database_url(DB), sync_id, 2) == 'loaded'
    table = (await store.get_sync(pool, sync_id) or {})['raw_table']
    with psycopg.connect(database_url(DB)) as conn:
        names = [
            r[0]
            for r in conn.execute(
                "select column_name from information_schema.columns where table_schema = 'raw' and table_name = %s", [table]
            )
        ]
    assert 'Civil ID' not in names and 'Phone' not in names and {'Record', 'Gender', 'Opened'} <= set(names)

    # The next file of the stream keeps the decisions: nothing left out reaches raw.
    path = csv_file(tmp_path / 'again.csv', rows(30), header=HEADER)
    source_id = (await store.get_sync(pool, sync_id) or {})['source_id']
    with path.open('rb') as data:
        again = await receive(pool, storage, source_id=source_id, user_id=None, as_of=dt.date(2026, 10, 2), sheet=None,
                              file_name=path.name, data=data)  # fmt: skip
    assert await process_sync(pool, storage, database_url(DB), again, 2) == 'loaded'
    with psycopg.connect(database_url(DB)) as conn:
        names = [
            r[0]
            for r in conn.execute(
                "select column_name from information_schema.columns where table_schema = 'raw' and table_name = %s", [table]
            )
        ]
        count = conn.execute(sql.SQL('select count(*) from {}').format(sql.Identifier('raw', table))).fetchone()
    assert 'Civil ID' not in names and count == (24 + 30,)


async def test_a_repeated_key_is_reported_before_approval(pool: AsyncConnectionPool, tmp_path: Path) -> None:
    sync_id, _ = await waiting(pool, tmp_path, 'Repeats')
    await files.decide(pool, sync_id, {}, ['Gender'], None, 2)
    review = await files.review(pool, sync_id)
    assert review is not None and review['row_key']['check'] == {'empty': 0, 'repeated': 22}  # two genders, 24 rows
