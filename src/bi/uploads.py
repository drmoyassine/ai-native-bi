"""Files uploaded through the app (ROADMAP-009): kept under <RAW_FILES_URL>/incoming/<upload id>/ by the API, then loaded into raw
(bi.ingest) and analytics rebuilt (dbt) by the worker. An upload that fails is not retried: a bad file stays bad; its error is shown.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import fsspec
from psycopg_pool import AsyncConnectionPool

from . import dbt
from .ingest import SPREADSHEETS, IngestError, load_file

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
SUFFIXES = SPREADSHEETS | {'.csv'}
_UNSAFE = re.compile(r'[^A-Za-z0-9._ -]+')


class UploadError(ValueError):
    """The upload is refused as sent (its type, its size, its name)."""


@dataclass
class Storage:
    files_url: str
    options: dict[str, Any] | None = None


def safe_name(name: str) -> str:
    """The file's own name, without any path, and only plain characters."""
    base = _UNSAFE.sub('_', Path(name.replace('\\', '/')).name).strip(' .')
    if not base or Path(base).suffix.lower() not in SUFFIXES:
        raise UploadError(f'only {", ".join(sorted(SUFFIXES))} files can be uploaded')
    return base[-150:]


def _save(storage: Storage, url: str, source: BinaryIO) -> int:
    size = 0
    fs, path = fsspec.core.url_to_fs(url, **(storage.options or {}))
    fs.makedirs(path.rsplit('/', 1)[0], exist_ok=True)
    with fs.open(path, 'wb') as out:
        while chunk := source.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                break
            out.write(chunk)
    if size > MAX_UPLOAD_BYTES:
        fs.rm(path)
        raise UploadError(f'the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB')
    if size == 0:
        fs.rm(path)
        raise UploadError('the file is empty')
    return size


async def receive(
    pool: AsyncConnectionPool,
    storage: Storage,
    *,
    user_id: str,
    dataset: str,
    as_of: dt.date,
    sheet: str | None,
    file_name: str,
    source: BinaryIO,
) -> str:
    """Keeps an uploaded file under incoming/ and records the upload (`queued`); returns its id, for the worker's `load` job."""
    name = safe_name(file_name)
    id = str(uuid.uuid4())
    url = f'{storage.files_url.rstrip("/")}/incoming/{id}/{name}'
    await asyncio.to_thread(_save, storage, url, source)
    async with pool.connection() as conn:
        await conn.execute(
            """insert into upload (id, user_id, dataset, as_of, sheet, file_name, incoming_url) values (%s, %s, %s, %s, %s, %s, %s)""",
            [id, user_id, dataset, as_of, sheet or None, name, url],
        )
    return id


def _load(storage: Storage, database_url: str, row: dict[str, Any]) -> tuple[Any, dbt.Built]:
    with tempfile.TemporaryDirectory() as work:
        local = Path(work) / row['file_name']
        fs, path = fsspec.core.url_to_fs(row['incoming_url'], **(storage.options or {}))
        fs.get_file(path, str(local))
        loaded = load_file(
            local,
            dataset=row['dataset'],
            as_of=row['as_of'],
            database_url=database_url,
            files_url=storage.files_url,
            sheet=row['sheet'],
            storage_options=storage.options,
        )
    return loaded, dbt.build(database_url)


async def process_upload(pool: AsyncConnectionPool, storage: Storage, database_url: str, id: str) -> str:
    """Loads one upload and rebuilds analytics; the outcome (`loaded` or `failed`, with the reason) is kept on the upload."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            """update upload set status = 'running' where id = %s and status = 'queued'
               returning dataset, as_of, sheet, file_name, incoming_url""",
            [id],
        )
        found = await cur.fetchone()
    if found is None:
        return 'skipped'
    row = dict(zip(('dataset', 'as_of', 'sheet', 'file_name', 'incoming_url'), found, strict=True))
    try:
        loaded, built = await asyncio.to_thread(_load, storage, database_url, row)
    except Exception as e:  # any failure ends the upload, with its reason: nothing is retried, nothing stays `running`
        error = str(e) if isinstance(e, IngestError | dbt.TransformError) else f'the file could not be loaded: {e}'
        async with pool.connection() as conn:
            await conn.execute("update upload set status = 'failed', error = %s, finished_at = now() where id = %s", [error, id])
        return 'failed'
    async with pool.connection() as conn:
        await conn.execute(
            """update upload set status = 'loaded', sha256 = %s, rows = %s, repeat = %s, tests = %s, finished_at = now()
               where id = %s""",
            [loaded.sha256, loaded.rows, loaded.repeat, built.tests, id],
        )
    return 'loaded'


async def recent(pool: AsyncConnectionPool, limit: int = 50) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            """select u.id::text, u.dataset, u.as_of, u.sheet, u.file_name, u.status, u.rows, u.repeat, u.tests, u.error,
                      u.created_at, u.finished_at, a.name
               from upload u join app_user a on a.id = u.user_id order by u.created_at desc limit %s""",
            [limit],
        )
        names = [c.name for c in cur.description or []]
        return [dict(zip(names, r, strict=True)) for r in await cur.fetchall()]
