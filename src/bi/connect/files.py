"""The file source (spec § 5, C1): an uploaded export is kept unchanged, its table found (§ 6.2), and its rows loaded through dlt. A layout
nobody has approved for the stream's dataset goes to the draft schema first, where it is profiled and its columns matched to the
dataset's parts; it reaches raw only once its mapping is approved, by a person or because every needed part has its own name. Raw is
appended, never changed; every row carries its sync, layout, file and as-of date."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import dlt
import fsspec
import psycopg
from dlt.common.schema.typing import TColumnSchema
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from .. import dbt, definitions, generate, mapping
from . import store
from .profile import profile_table, summary
from .sheets import FILE_SUFFIXES, SheetError, Table, read_table

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
RAW = 'raw'
DRAFT = 'draft'
_UNSAFE = re.compile(r'[^\w.() -]+')


class UploadError(ValueError):
    """The upload is refused as sent (its type, its size, its name)."""


@dataclass
class Storage:
    files_url: str
    options: dict[str, Any] | None = None


def safe_name(name: str) -> str:
    """The file's own name, without any path, and only plain characters."""
    base = _UNSAFE.sub('_', Path(name.replace('\\', '/')).name).strip(' .')
    if not base or Path(base).suffix.lower() not in FILE_SUFFIXES:
        raise UploadError(f'only {", ".join(sorted(FILE_SUFFIXES))} files can be uploaded')
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
    source_id: str,
    user_id: str | None,
    as_of: dt.date,
    sheet: str | None,
    file_name: str,
    data: BinaryIO,
) -> str:
    """Keeps an uploaded file under incoming/ and records its sync (`queued`); returns the sync's id, for the worker's `load` job."""
    name = safe_name(file_name)
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """select st.id::text from source s join source_stream st on st.source_id = s.id
                   where s.id::text = %s and s.type = 'file'""",
                [source_id],
            )
        ).fetchone()
        if row is None:
            raise UploadError('no such file source')
        made = await (
            await conn.execute(
                """insert into sync (source_id, stream_id, user_id, as_of, sheet, file_name) values (%s, %s, %s, %s, %s, %s)
                   returning id::text""",
                [source_id, row[0], user_id, as_of, sheet or None, name],
            )
        ).fetchone()
    assert made is not None
    sync_id = str(made[0])
    url = f'{storage.files_url.rstrip("/")}/incoming/{sync_id}/{name}'
    try:
        await asyncio.to_thread(_save, storage, url, data)
    except Exception:
        async with pool.connection() as conn:
            await conn.execute('delete from sync where id::text = %s', [sync_id])
        raise
    await store.update_sync(pool, sync_id, incoming_url=url)
    return sync_id


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def store_file(path: Path, files_url: str, folder: str, sha256: str, storage_options: dict[str, Any] | None = None) -> str:
    """Keeps the file unchanged at <files_url>/<folder>/<sha256><suffix> (written once; the same content is the same object)."""
    target = f'{files_url.rstrip("/")}/{folder}/{sha256}{path.suffix.lower()}'
    fs, fs_path = fsspec.core.url_to_fs(target, **(storage_options or {}))
    if not fs.exists(fs_path):
        parent = fs_path.rsplit('/', 1)[0]
        fs.makedirs(parent, exist_ok=True)
        fs.put_file(str(path), fs_path)
        if 'file' in fs.protocol:  # on a disk: the BI's alone and read-only (a bucket has its own policy)
            os.chmod(parent, 0o700)
            os.chmod(fs_path, 0o400)
    return target


def load_rows(database_url: str, schema: str, table: str, table_rows: Table, meta: dict[str, Any], replace: bool = False) -> int:
    """Loads a table's rows through dlt into <schema>.<table>, names kept as written (DEC-031), every cell as text, with the BI's
    metadata on every row. Returns the number of rows."""
    records = [{**row, **meta, '_bi_row': n} for row, n in zip(table_rows.rows, table_rows.row_numbers, strict=True)]
    hints: list[TColumnSchema] = [{'name': c, 'data_type': 'text', 'nullable': True} for c in table_rows.columns]
    typed: dict[str, Any] = {'_bi_as_of': 'date', '_bi_loaded_at': 'timestamp', '_bi_row': 'bigint'}
    for name in ('_bi_sync_id', '_bi_layout', '_bi_file_sha256', '_bi_file_name', '_bi_sheet', *typed):
        hints.append({'name': name, 'data_type': typed.get(name, 'text'), 'nullable': True})
    with tempfile.TemporaryDirectory() as state:
        pipeline = dlt.pipeline(
            pipeline_name=f'{schema}_{table}',
            destination=dlt.destinations.postgres(credentials=database_url, naming_convention='duck_case'),
            dataset_name=schema,
            pipelines_dir=state,
        )
        pipeline.run(records, table_name=table, write_disposition='replace' if replace else 'append', columns=hints)
    return len(records)


def _already_loaded(database_url: str, table: str, sha256: str, layout_id: str) -> bool:
    with psycopg.connect(database_url) as conn:
        exists = conn.execute('select to_regclass(%s) is not null', [f'{RAW}."{table}"']).fetchone()
        if not exists or not exists[0]:
            return False
        query = sql.SQL('select 1 from {} where _bi_file_sha256 = %s and _bi_layout = %s limit 1').format(sql.Identifier(RAW, table))
        return conn.execute(query, [sha256, layout_id]).fetchone() is not None


def drop_draft(database_url: str, table: str) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(sql.SQL('drop table if exists {}').format(sql.Identifier(DRAFT, table)))


def _read(storage: Storage, row: dict[str, Any]) -> tuple[Table, str, str]:
    """Downloads the incoming file, keeps it under its SHA-256 and reads its table; returns the table, its hash and where it is kept."""
    with tempfile.TemporaryDirectory() as work:
        local = Path(work) / row['file_name']
        fs, path = fsspec.core.url_to_fs(row['incoming_url'], **(storage.options or {}))
        fs.get_file(path, str(local))
        table = read_table(local, row['sheet'], row['header_row'])
        if not table.rows:
            raise SheetError(f'{table.where} has a header on row {table.header_row} but no rows under it')
        sha256 = _sha256(local)
        stored_at = store_file(local, storage.files_url, row['raw_table'], sha256, storage.options)
    return table, sha256, stored_at


async def rebuild(pool: AsyncConnectionPool, database_url: str) -> dbt.Built:
    """Rebuilds staging and analytics from every approved input (dbt build, with its tests)."""
    generated = generate.dbt_files(await definitions.events(pool))
    return await asyncio.to_thread(dbt.build, database_url, None, await mapping.dbt_vars(pool), generated)


async def process_sync(pool: AsyncConnectionPool, storage: Storage, database_url: str, sync_id: str, threshold: int) -> str:
    """Works one sync of a file source; the outcome (`loaded`, `review` or `failed`, with the reason) is kept on the sync."""
    async with pool.connection() as conn:
        claimed = await (
            await conn.execute("update sync set status = 'running' where id::text = %s and status = 'queued' returning id", [sync_id])
        ).fetchone()
    if claimed is None:
        return 'skipped'
    row = await store.get_sync(pool, sync_id)
    assert row is not None
    try:
        return await _process(pool, storage, database_url, row, threshold)
    except Exception as e:  # any failure ends the sync, with its reason: nothing is retried, nothing stays `running`
        error = str(e) if isinstance(e, SheetError | dbt.TransformError) else f'the file could not be loaded: {e}'
        await store.update_sync(pool, sync_id, status='failed', error=error, finished_at=dt.datetime.now(dt.UTC))
        return 'failed'


async def _process(pool: AsyncConnectionPool, storage: Storage, database_url: str, row: dict[str, Any], threshold: int) -> str:
    sync_id, table_name, dataset = row['id'], row['raw_table'], row['dataset']
    table, sha256, _ = await asyncio.to_thread(_read, storage, row)
    layout_id, columns = store.layout_of(table.columns)
    await store.save_layout(pool, layout_id, columns)
    await store.update_sync(
        pool, sync_id, sha256=sha256, layout_id=layout_id, found_header_row=table.header_row, rows=len(table.rows),
        notes={'above_header': table.notes, 'guessed': table.guessed, 'dropped_columns': table.dropped_columns,
               'dropped_total_rows': table.dropped_total_rows, 'where': table.where},
    )  # fmt: skip
    meta = {
        '_bi_sync_id': sync_id,
        '_bi_layout': layout_id,
        '_bi_file_sha256': sha256,
        '_bi_file_name': row['file_name'],
        '_bi_sheet': row['sheet'],
        '_bi_as_of': row['as_of'].isoformat(),
        '_bi_loaded_at': dt.datetime.now(dt.UTC).isoformat(),
    }
    approved = await _approved(pool, row, layout_id)
    if not approved:
        await asyncio.to_thread(load_rows, database_url, DRAFT, table_name, table, meta, True)
        profile = await profile_table(pool, DRAFT, table_name, threshold, sql.SQL('_bi_sync_id = {}').format(sql.Literal(sync_id)))
        await store.update_sync(pool, sync_id, profile=profile)
        approved = await _propose(pool, row, layout_id, columns, profile)
        if not approved:
            await store.update_sync(pool, sync_id, status='review', note=_review_note(row), finished_at=dt.datetime.now(dt.UTC))
            return 'review'
    repeat = await asyncio.to_thread(_already_loaded, database_url, table_name, sha256, layout_id)
    if not repeat:
        await asyncio.to_thread(load_rows, database_url, RAW, table_name, table, meta)
    await asyncio.to_thread(drop_draft, database_url, table_name)
    await store.update_sync(pool, sync_id, status='loaded', repeat=repeat, note=None, finished_at=dt.datetime.now(dt.UTC))
    if dataset:
        try:
            built = await rebuild(pool, database_url)
        except dbt.TransformError as e:  # its rows stay in raw but no longer count (mapping.inputs reads loaded syncs only)
            await store.update_sync(pool, sync_id, status='failed', error=str(e))
            await rebuild(pool, database_url)
            return 'failed'
        await store.update_sync(pool, sync_id, tests=built.tests)
    return 'loaded'


async def _approved(pool: AsyncConnectionPool, row: dict[str, Any], layout_id: str) -> bool:
    if row['dataset'] is None:
        return bool(row['source_state'] == 'live')
    kept = await mapping.stored(pool, layout_id, row['dataset'])
    return kept is not None and kept['status'] == 'approved'


async def _propose(
    pool: AsyncConnectionPool, row: dict[str, Any], layout_id: str, columns: list[dict[str, str]], profile: dict[str, Any]
) -> bool:
    """Proposes a mapping for an unknown layout; approves it when every needed part has its own name and its column fits."""
    dataset = row['dataset']
    if dataset is None:
        return False
    names = [c['name'] for c in columns]
    kinds = {p['name']: p['kind'] for p in profile['columns']}
    proposal, exact = mapping.propose(await mapping.fields(pool, dataset), names, kinds)
    if exact:
        await mapping.save(pool, layout_id, dataset, proposal, 'approved', 'every needed part has a column of its own name')
        return True
    earlier = await mapping.latest_approved(pool, dataset, names)
    if earlier:  # a changed layout: start from what was approved before, and fill what it leaves out
        proposal = {p: earlier.get(p) or proposal.get(p) for p in proposal}
    stored = await mapping.stored(pool, layout_id, dataset)
    if stored is None:
        await mapping.save(pool, layout_id, dataset, proposal, 'proposed', None)
    elif stored['proposed_by'] == 'agent':  # the agent already looked at these columns: not asked twice unless a person asks
        await store.update_sync(pool, row['id'], agent={'state': 'proposed', 'earlier': True, 'model': stored['model']})
        return False
    # The rules fell short: ask the setup agent (a job; the review shows the rules' proposal meanwhile). Samples only for an admin's work.
    await store.update_sync(pool, row['id'], agent={'state': 'queued', 'auto': True, 'by_admin': bool(row.get('by_admin'))})
    return False


def _review_note(row: dict[str, Any]) -> str:
    if row['dataset'] is None:
        return 'Check the columns found, then approve the source to keep its data.'
    return f'Check which column is which, then approve to build the {row["dataset"]} analytics.'


async def review(pool: AsyncConnectionPool, sync_id: str) -> dict[str, Any] | None:
    """What a person checks before approving a sync's layout: the header found, each column (as written, with what it holds), the
    dataset's parts with plain names, and the proposed or approved mapping."""
    row = await store.get_sync(pool, sync_id)
    if row is None:
        return None
    out: dict[str, Any] = {
        'sync': {k: row[k] for k in ('id', 'source_id', 'status', 'file_name', 'as_of', 'sheet', 'rows', 'note', 'error')},
        'source': {'id': row['source_id'], 'name': row['source_name'], 'state': row['source_state']},
        'dataset': row['dataset'],
        'header': {'row': row['found_header_row'], **(row['notes'] or {})},
        'columns': [],
        'parts': [],
        'mapping': None,
        'mapping_status': None,
        'proposed_by': None,
        'reasons': None,
        'agent': row['agent'],
    }
    if row['layout_id'] is None:
        return out
    async with pool.connection() as conn:
        found = await (await conn.execute('select columns from layout where id = %s', [row['layout_id']])).fetchone()
    profiles = {p['name']: p for p in (row['profile'] or {}).get('columns', [])}
    out['columns'] = [
        {'name': c['name'], 'header': c['header'], 'kind': profiles.get(c['name'], {}).get('kind'),
         'summary': summary(profiles[c['name']]) if c['name'] in profiles else None}
        for c in (found[0] if found else [])
    ]  # fmt: skip
    if row['dataset']:
        out['parts'] = [
            {'name': f.name, 'label': f.label, 'description': f.description, 'required': f.required, 'expects': f.expects}
            for f in await mapping.fields(pool, row['dataset'])
        ]
        kept = await mapping.stored(pool, row['layout_id'], row['dataset'])
        if kept:
            out['mapping'], out['mapping_status'] = kept['mapping'], kept['status']
            out['proposed_by'], out['reasons'] = kept['proposed_by'], kept['reasons']
            out['model'] = kept['model']
    return out


async def approve(pool: AsyncConnectionPool, sync_id: str, chosen: dict[str, str | None] | None, user_id: str, email: str) -> None:
    """A person approves a sync's layout (and its source): the mapping is checked and saved, and the sync is queued again to load."""
    row = await store.get_sync(pool, sync_id)
    if row is None or row['layout_id'] is None:
        raise mapping.MappingError('this sync has no columns to approve yet')
    if row['dataset']:
        async with pool.connection() as conn:
            found = await (await conn.execute('select columns from layout where id = %s', [row['layout_id']])).fetchone()
        names = [c['name'] for c in (found[0] if found else [])]
        mapping.check(row['dataset'], await mapping.fields(pool, row['dataset']), chosen or {}, names)
        kept = await mapping.stored(pool, row['layout_id'], row['dataset'])
        changed = kept is None or {p: c for p, c in (chosen or {}).items() if c} != {p: c for p, c in kept['mapping'].items() if c}
        await mapping.save(
            pool, row['layout_id'], row['dataset'], chosen or {}, 'approved', f'approved by {email}', user_id,
            proposed_by='person' if changed else (kept or {}).get('proposed_by', 'rules'), reasons=(kept or {}).get('reasons'),
            model=(kept or {}).get('model'),
        )  # fmt: skip
    await store.approve_source(pool, row['source_id'], user_id)
    await store.requeue(pool, sync_id)


async def load_now(
    pool: AsyncConnectionPool,
    storage: Storage,
    database_url: str,
    path: Path,
    *,
    source_name: str,
    dataset: str | None,
    as_of: dt.date,
    sheet: str | None = None,
    threshold: int = 5,
) -> dict[str, Any]:
    """Loads one file now, as an operator (python -m bi.main_load) or a test does: into the named file source (made, and approved, if
    it does not exist), through the same steps as an upload. Returns the sync as it ended."""
    source_id = await store.find_source(pool, source_name)
    if source_id is None:
        source_id = await store.create_source(pool, name=source_name, type='file', dataset=dataset, owner=None)
        async with pool.connection() as conn:
            await conn.execute("update source set state = 'live', approved_at = now() where id::text = %s", [source_id])
    with path.open('rb') as data:
        sync_id = await receive(pool, storage, source_id=source_id, user_id=None, as_of=as_of, sheet=sheet, file_name=path.name, data=data)
    await process_sync(pool, storage, database_url, sync_id, threshold)
    ended = await store.get_sync(pool, sync_id)
    assert ended is not None
    return ended
