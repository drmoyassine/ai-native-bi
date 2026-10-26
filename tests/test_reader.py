"""TASK-007: Cube's role reads analytics and nothing else, also after dbt rebuilds it (CLAUDE.md rule 5)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from bi import dbt
from bi.db import ensure_reader_role, grant_analytics
from bi.ingest import load_file

from .conftest import ADMIN, PoolFactory, database_url
from .fakes import FALL, students, xlsx

READER = 'bi_reader_test_cube'


def reader_url(db: str) -> str:
    u = urlsplit(ADMIN)
    return urlunsplit((u.scheme, f'{READER}:reader-pw-0123456789@{u.hostname}:{u.port or 5432}', f'/{db}', '', ''))


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    p = await make_pool('bi_reader_test')
    await ensure_reader_role(ADMIN, READER, 'old-password-0123456789')
    await ensure_reader_role(ADMIN, READER, 'reader-pw-0123456789')  # again: the password is reset, nothing else happens
    await grant_analytics(p, READER)
    return p


def can_read(table: str) -> bool:
    with psycopg.connect(reader_url('bi_reader_test')) as conn:
        try:
            conn.execute(f'select count(*) from {table}')  # noqa: S608 (test tables)
        except psycopg.errors.InsufficientPrivilege:
            return False
    return True


def test_cube_reads_analytics_only_also_after_a_rebuild(pool: AsyncConnectionPool, tmp_path: Path) -> None:
    owner = database_url('bi_reader_test')
    load_file(
        xlsx(tmp_path / 'fall.xlsx', students(FALL, (1001, 'BSME', 'Bachelor'))),
        dataset='enrollment',
        as_of=dt.date(2026, 10, 20),
        database_url=owner,
        files_url=f'file://{tmp_path}/files',
    )
    dbt.build(owner)
    assert can_read('analytics.enrollment')
    assert not can_read('raw.enrollment')
    assert not can_read('staging.stg_enrollment')
    assert not can_read('collect_request')
    dbt.build(owner)  # dbt replaces the table: the new one is readable too (default privileges)
    assert can_read('analytics.enrollment')
