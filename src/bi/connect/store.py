"""Sources, their streams, the layouts their data comes in, and syncs, in the BI's database (migration 0010)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from dlt.common.normalizers.naming.duck_case import NamingConvention
from psycopg import sql
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

TYPES = {'file'}
"""The source types built so far (spec § 11: files first)."""
NAMING = NamingConvention()
"""Raw keeps column names as written (DEC-031): Unicode and case kept, so two Arabic headers stay two columns."""
SYNC_STATES = ('queued', 'running', 'review', 'loaded', 'failed', 'stale')


class SourceError(ValueError):
    """A source cannot be made or changed as asked."""


def slug(name: str) -> str:
    """The source's name as a raw table name: lower-case ASCII letters, digits and _, starting with a letter."""
    base = re.sub(r'[^a-z0-9]+', '_', name.casefold()).strip('_')[:36] or 'source'
    return base if base[0].isalpha() else f's_{base}'[:36]


def column_name(header: str) -> str:
    return NAMING.normalize_identifier(header)


def layout_of(headers: list[str]) -> tuple[str, list[dict[str, str]]]:
    """The layout of a header: its fingerprint (the normalised names, in order) and its columns, as named in raw and as written."""
    columns = [{'name': column_name(h), 'header': h} for h in headers]
    digest = hashlib.sha256('\x1f'.join(c['name'] for c in columns).encode()).hexdigest()[:20]
    return digest, columns


async def save_layout(pool: AsyncConnectionPool, layout_id: str, columns: list[dict[str, str]]) -> None:
    async with pool.connection() as conn:
        await conn.execute('insert into layout (id, columns) values (%s, %s) on conflict (id) do nothing', [layout_id, Jsonb(columns)])


async def create_source(pool: AsyncConnectionPool, *, name: str, type: str, dataset: str | None, owner: str | None) -> str:
    """A new source (in draft) with its one stream for now (a file source's files); returns its id."""
    name = ' '.join(name.split())
    if not name or len(name) > 80:
        raise SourceError('a source needs a name of up to 80 characters')
    if type not in TYPES:
        raise SourceError(f'"{type}" sources are not available yet (available: {", ".join(sorted(TYPES))})')
    base = slug(name)
    async with pool.connection() as conn, conn.transaction():
        if await (await conn.execute('select 1 from source where lower(name) = lower(%s)', [name])).fetchone():
            raise SourceError(f'there is already a source named "{name}"')
        taken = {r[0] for r in await (await conn.execute('select raw_table from source_stream')).fetchall()}
        table, n = base, 2
        while table in taken:
            table, n = f'{base}_{n}', n + 1
        row = await (
            await conn.execute(
                'insert into source (name, slug, type, owner) values (%s, %s, %s, %s) returning id::text', [name, table, type, owner]
            )
        ).fetchone()
        assert row is not None
        await conn.execute(
            'insert into source_stream (source_id, name, raw_table, dataset) values (%s, %s, %s, %s)', [row[0], 'files', table, dataset]
        )
    return str(row[0])


async def find_source(pool: AsyncConnectionPool, name: str) -> str | None:
    async with pool.connection() as conn:
        row = await (await conn.execute('select id::text from source where lower(name) = lower(%s)', [name])).fetchone()
    return None if row is None else str(row[0])


async def list_sources(pool: AsyncConnectionPool) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            """select s.id::text, s.name, s.type, s.state, st.dataset, st.raw_table, s.created_at,
                      (select max(created_at) from sync where source_id = s.id) as last_sync,
                      (select count(*) from sync where source_id = s.id and status = 'review') as waiting,
                      (select status from sync where source_id = s.id order by created_at desc limit 1) as last_status
               from source s join source_stream st on st.source_id = s.id
               order by s.name"""
        )
        names = [c.name for c in cur.description or []]
        return [dict(zip(names, r, strict=True)) for r in await cur.fetchall()]


SYNC_COLUMNS = sql.SQL("""y.id::text, y.source_id::text, y.stream_id::text, y.user_id::text, y.as_of, y.sheet, y.header_row, y.file_name,
    y.incoming_url, y.status, y.sha256, y.layout_id, y.found_header_row, y.notes, y.profile, y.rows, y.repeat, y.tests, y.note, y.error,
    y.created_at, y.finished_at, y.agent, a.name as by_name, a.is_admin as by_admin""")


async def get_source(pool: AsyncConnectionPool, source_id: str) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        cur = await conn.execute(
            """select s.id::text, s.name, s.type, s.state, s.slug, s.created_at, s.approved_at, st.id::text as stream_id, st.dataset,
                      st.raw_table, a.name as approved_by
               from source s join source_stream st on st.source_id = s.id left join app_user a on a.id = s.approved_by
               where s.id::text = %s""",
            [source_id],
        )
        row = await cur.fetchone()
        if row is None:
            return None
        source = dict(zip([c.name for c in cur.description or []], row, strict=True))
        cur = await conn.execute(
            sql.SQL("""select {} from sync y left join app_user a on a.id = y.user_id
                where y.source_id::text = %s order by y.created_at desc limit 50""").format(SYNC_COLUMNS),
            [source_id],
        )
        names = [c.name for c in cur.description or []]
        source['syncs'] = [{k: v for k, v in zip(names, r, strict=True) if k not in ('profile', 'agent')} for r in await cur.fetchall()]
    return source


async def get_sync(pool: AsyncConnectionPool, sync_id: str) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        cur = await conn.execute(
            sql.SQL("""select {}, st.dataset, st.raw_table, s.name as source_name, s.state as source_state, s.slug
                from sync y join source_stream st on st.id = y.stream_id join source s on s.id = y.source_id
                left join app_user a on a.id = y.user_id
                where y.id::text = %s""").format(SYNC_COLUMNS),
            [sync_id],
        )
        row = await cur.fetchone()
        return None if row is None else dict(zip([c.name for c in cur.description or []], row, strict=True))


async def update_sync(pool: AsyncConnectionPool, sync_id: str, **values: Any) -> None:
    sets = sql.SQL(', ').join(sql.SQL('{} = %s').format(sql.Identifier(k)) for k in values)
    params = [Jsonb(v) if k in ('notes', 'profile', 'agent') and v is not None else v for k, v in values.items()]
    async with pool.connection() as conn:
        await conn.execute(sql.SQL('update sync set {} where id::text = %s').format(sets), [*params, sync_id])


async def requeue(pool: AsyncConnectionPool, sync_id: str, header_row: int | None = None, keep_header: bool = True) -> bool:
    """Puts a finished sync back in the queue (after an approval, a chosen header row, or to load it again)."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            """update sync set status = 'queued', error = null, note = null, finished_at = null,
                      header_row = case when %s then header_row else %s end
               where id::text = %s and status in ('review', 'loaded', 'failed', 'stale') and incoming_url is not null""",
            [keep_header, header_row, sync_id],
        )
        return cur.rowcount == 1


async def approve_source(pool: AsyncConnectionPool, source_id: str, user_id: str) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """update source set state = 'live', approved_by = %s, approved_at = now() where id::text = %s and state = 'draft'""",
            [user_id, source_id],
        )
