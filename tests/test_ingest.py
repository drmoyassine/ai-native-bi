from __future__ import annotations

import datetime as dt
from pathlib import Path

import psycopg
import pytest

from bi import dbt
from bi.ingest import IngestError, cell_text, load_file, read_rows

from .conftest import ADMIN
from .fakes import FALL, HEADER, SPRING, csv_file, students, xlsx

AS_OF = dt.date(2026, 10, 20)


@pytest.fixture(scope='module')
def db() -> str:
    """A database of its own (dlt and dbt are synchronous: plain psycopg here)."""
    url = ADMIN.rsplit('/', 1)[0] + '/bi_ingest_test'
    with psycopg.connect(ADMIN, autocommit=True) as admin:
        admin.execute('drop database if exists bi_ingest_test with (force)')
        admin.execute('create database bi_ingest_test')
    return url


@pytest.fixture(autouse=True)
def empty(db: str) -> None:
    with psycopg.connect(db, autocommit=True) as conn:
        conn.execute('drop schema if exists raw cascade; drop schema if exists staging cascade; drop schema if exists analytics cascade')


def load(db: str, path: Path, tmp_path: Path, as_of: dt.date = AS_OF) -> None:
    load_file(path, dataset='enrollment', as_of=as_of, database_url=db, files_url=f'file://{tmp_path}/files')


def query(db: str, sql: str) -> list[tuple[object, ...]]:
    with psycopg.connect(db) as conn:
        return conn.execute(sql).fetchall()


def test_cells_are_kept_as_written() -> None:
    assert [cell_text(v) for v in [12345.0, 1.5, '  BSME ', '', None, True, dt.date(2026, 8, 24)]] == [
        '12345',
        '1.5',
        'BSME',
        None,
        None,
        'true',
        '2026-08-24',
    ]


def test_reads_a_spreadsheet_and_a_csv_alike(tmp_path: Path) -> None:
    rows = students(FALL, (1001, 'BSME', 'Bachelor'))
    from_xlsx = list(read_rows(xlsx(tmp_path / 'a.xlsx', rows)))
    from_csv = list(read_rows(csv_file(tmp_path / 'a.csv', rows)))
    assert (
        from_xlsx
        == from_csv
        == [dict(zip(HEADER, ['1001', '202610', 'Fall 2026', '2026-08-24', '2026-12-18', 'BSME', 'Bachelor', 'Enrolled'], strict=True))]
    )


def test_refuses_what_it_cannot_read_as_a_table(tmp_path: Path) -> None:
    with pytest.raises(IngestError, match='same name twice'):
        list(read_rows(xlsx(tmp_path / 'dup.xlsx', [[1, 2]], header=['ID', 'ID'])))
    with pytest.raises(IngestError, match='no sheet "Other"'):
        list(read_rows(xlsx(tmp_path / 's.xlsx', [[1]], header=['ID']), sheet='Other'))
    (tmp_path / 'a.pdf').write_bytes(b'%PDF')
    with pytest.raises(IngestError, match='only'):
        list(read_rows(tmp_path / 'a.pdf'))


def test_loads_a_file_once_keeps_it_unchanged_and_keeps_every_column(db: str, tmp_path: Path) -> None:
    rows = students(FALL, (1001, 'BSME', 'Bachelor'), (1002, 'BSCE', 'Bachelor'))
    path = xlsx(tmp_path / 'fall.xlsx', [[*r, None] for r in rows], header=[*HEADER, 'Advisor'])
    first = load_file(path, dataset='enrollment', as_of=AS_OF, database_url=db, files_url=f'file://{tmp_path}/files')
    again = load_file(path, dataset='enrollment', as_of=AS_OF, database_url=db, files_url=f'file://{tmp_path}/files')
    assert (first.rows, first.repeat, again.repeat) == (2, False, True)
    assert Path(first.stored_at.removeprefix('file://')).read_bytes() == path.read_bytes()
    assert Path(first.stored_at.removeprefix('file://')).stat().st_mode & 0o777 == 0o400
    assert query(db, 'select student_id, advisor, _bi_row, _bi_as_of, _bi_file_name from raw.enrollment order by _bi_row') == [
        ('1001', None, 2, '2026-10-20', 'fall.xlsx'),
        ('1002', None, 3, '2026-10-20', 'fall.xlsx'),
    ]
    with pytest.raises(IngestError, match='not a dataset name'):
        load_file(path, dataset='Enrollment', as_of=AS_OF, database_url=db, files_url=f'file://{tmp_path}/files')


def test_builds_analytics_and_a_new_upload_of_a_term_replaces_it(db: str, tmp_path: Path) -> None:
    load(db, xlsx(tmp_path / 'fall.xlsx', students(FALL, (1001, 'BSME', 'Bachelor'), (1002, 'BSCE', 'Bachelor'))), tmp_path)
    load(db, csv_file(tmp_path / 'spring.csv', students(SPRING, (1001, 'BSME', 'Bachelor'))), tmp_path)
    built = dbt.build(db)
    assert built.models == 2 and built.tests > 0
    assert query(db, 'select term_code, count(*) from analytics.enrollment group by 1 order by 1') == [('202610', 2), ('202620', 1)]

    corrected = students(FALL, (1001, 'BSME', 'Bachelor'), (1002, 'BSCE', 'Bachelor'), (1003, 'MSDS', 'Master'))
    load(db, xlsx(tmp_path / 'fall-corrected.xlsx', corrected), tmp_path, as_of=dt.date(2026, 10, 25))
    dbt.build(db)
    assert query(db, "select count(*), max(as_of) from analytics.enrollment where term_code = '202610'") == [(3, dt.date(2026, 10, 25))]
    assert query(db, "select level from analytics.enrollment where student_id = '1003'") == [('master',)]


def test_a_student_twice_in_a_term_fails_the_build(db: str, tmp_path: Path) -> None:
    load(db, xlsx(tmp_path / 'dup.xlsx', students(FALL, (1001, 'BSME', 'Bachelor'), (1001, 'BSCE', 'Bachelor'))), tmp_path)
    with pytest.raises(dbt.TransformError, match='unique'):
        dbt.build(db)
