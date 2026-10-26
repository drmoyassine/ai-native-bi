"""Loads a file (.xlsx, .xlsb, .xls, .ods, .csv) into raw storage: the file itself, unchanged, under its SHA-256, and its rows into
the `raw` schema (dlt), one table per dataset. Raw is immutable and replayable: every load is appended with where it came from; dbt
types and picks the current rows (transform/). Cells are kept as text exactly as written (dates in ISO form); typing is dbt's job.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import os
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dlt
import fsspec
import psycopg
from dlt.common.schema.typing import TColumnSchema
from psycopg import sql
from python_calamine import CalamineWorkbook

SPREADSHEETS = {'.xlsx', '.xlsm', '.xlsb', '.xls', '.ods'}
DATASET = re.compile(r'^[a-z][a-z0-9_]{0,62}$')
RAW_SCHEMA = 'raw'


class IngestError(ValueError):
    """The file cannot be loaded as asked (format, dataset name, empty sheet, duplicate headers)."""


@dataclass
class Loaded:
    dataset: str
    sha256: str
    stored_at: str
    rows: int
    repeat: bool


def cell_text(value: Any) -> str | None:
    """A cell as text, as written: 12345.0 -> '12345', dates in ISO form, empty -> None."""
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _headers(row: list[Any], where: str) -> list[str]:
    names = [cell_text(v) or f'column_{i + 1}' for i, v in enumerate(row)]
    seen = {n for n in names if names.count(n) > 1}
    if seen:
        raise IngestError(f'{where}: the header has the same name twice: {", ".join(sorted(seen))}')
    return names


def read_rows(path: Path, sheet: str | None = None) -> Iterator[dict[str, str | None]]:
    """The rows of one sheet (the first, or `sheet`) or of a CSV, keyed by the header row; empty rows are left out."""
    suffix = path.suffix.lower()
    if suffix == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as f:
            table: list[list[Any]] = list(csv.reader(f))
        where = path.name
    elif suffix in SPREADSHEETS:
        book = CalamineWorkbook.from_path(str(path))
        name = sheet or book.sheet_names[0]
        if name not in book.sheet_names:
            raise IngestError(f'{path.name} has no sheet "{name}" (it has: {", ".join(book.sheet_names)})')
        table = book.get_sheet_by_name(name).to_python()
        where = f'{path.name}, sheet "{name}"'
    else:
        raise IngestError(f'{path.name}: only {", ".join(sorted(SPREADSHEETS | {".csv"}))} files can be loaded')
    if not table:
        raise IngestError(f'{where} is empty')
    headers = _headers(table[0], where)
    for raw in table[1:]:
        values = [cell_text(v) for v in raw] + [None] * (len(headers) - len(raw))
        if any(v is not None for v in values):
            yield dict(zip(headers, values, strict=False))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def store_file(path: Path, files_url: str, dataset: str, sha256: str, storage_options: dict[str, Any] | None = None) -> str:
    """Keeps the file unchanged at <files_url>/<dataset>/<sha256><suffix> (written once; the same content is the same object)."""
    target = f'{files_url.rstrip("/")}/{dataset}/{sha256}{path.suffix.lower()}'
    fs, fs_path = fsspec.core.url_to_fs(target, **(storage_options or {}))
    if not fs.exists(fs_path):
        folder = fs_path.rsplit('/', 1)[0]
        fs.makedirs(folder, exist_ok=True)
        fs.put_file(str(path), fs_path)
        if 'file' in fs.protocol:  # on a disk: the BI's alone and read-only: the stored file never changes (a bucket has its own policy)
            os.chmod(folder, 0o700)
            os.chmod(fs_path, 0o400)
    return target


def _already_loaded(database_url: str, dataset: str, sha256: str) -> bool:
    with psycopg.connect(database_url) as conn:
        exists = conn.execute('select to_regclass(%s) is not null', [f'{RAW_SCHEMA}.{dataset}']).fetchone()
        if not exists or not exists[0]:
            return False
        query = sql.SQL('select 1 from {}.{} where _bi_file_sha256 = %s limit 1').format(
            sql.Identifier(RAW_SCHEMA), sql.Identifier(dataset)
        )
        return conn.execute(query, [sha256]).fetchone() is not None


def load_file(
    path: Path,
    *,
    dataset: str,
    as_of: dt.date,
    database_url: str,
    files_url: str,
    sheet: str | None = None,
    storage_options: dict[str, Any] | None = None,
) -> Loaded:
    """Loads one file as a snapshot of `dataset`, true as of `as_of`. The same file (same content) for the same dataset loads once."""
    if not DATASET.match(dataset):
        raise IngestError(f'"{dataset}" is not a dataset name: lower-case letters, digits and _, starting with a letter')
    sha256 = _sha256(path)
    rows = list(read_rows(path, sheet))
    if not rows:
        raise IngestError(f'{path.name} has a header but no rows')
    stored_at = store_file(path, files_url, dataset, sha256, storage_options)
    if _already_loaded(database_url, dataset, sha256):
        return Loaded(dataset=dataset, sha256=sha256, stored_at=stored_at, rows=len(rows), repeat=True)
    loaded_at = dt.datetime.now(dt.UTC).isoformat()
    meta = {
        '_bi_file_sha256': sha256,
        '_bi_file_name': path.name,
        '_bi_sheet': sheet,
        '_bi_as_of': as_of.isoformat(),
        '_bi_loaded_at': loaded_at,
    }
    records = [{**row, **meta, '_bi_row': i + 2} for i, row in enumerate(rows)]  # spreadsheet row numbers: the header is row 1
    with tempfile.TemporaryDirectory() as state:
        pipeline = dlt.pipeline(
            pipeline_name=f'files_{dataset}',
            destination=dlt.destinations.postgres(credentials=database_url),
            dataset_name=RAW_SCHEMA,
            pipelines_dir=state,
        )
        # Every header is a text column, also one whose cells are all empty in this file (dlt would leave it out otherwise).
        text_columns: list[TColumnSchema] = [{'name': name, 'data_type': 'text', 'nullable': True} for name in [*rows[0], '_bi_sheet']]
        pipeline.run(records, table_name=dataset, write_disposition='append', columns=text_columns)
    return Loaded(dataset=dataset, sha256=sha256, stored_at=stored_at, rows=len(rows), repeat=False)
