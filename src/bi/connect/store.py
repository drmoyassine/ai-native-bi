"""Sources, their streams, the layouts their data comes in, and syncs, in the BI's database (migration 0010)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from dlt.common.normalizers.naming.duck_case import NamingConvention
from psycopg import sql
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

TYPES = {'file', 'api'}
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


async def create_source(
    pool: AsyncConnectionPool,
    *,
    name: str,
    type: str,
    dataset: str | None,
    owner: str | None,
    settings: dict[str, Any] | None = None,
    streams: dict[str, str | None] | None = None,
) -> str:
    """A new source (in draft) and its streams: a file source's files, or one per endpoint of an API (`streams`: name -> dataset);
    returns its id."""
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
        taken |= {r[0] for r in await (await conn.execute('select slug from source')).fetchall()}

        def free(wanted: str) -> str:
            chosen, n = wanted, 2
            while chosen in taken:
                chosen, n = f'{wanted}_{n}', n + 1
            taken.add(chosen)
            return chosen

        source_slug = free(base)
        row = await (
            await conn.execute(
                'insert into source (name, slug, type, owner, settings) values (%s, %s, %s, %s, %s) returning id::text',
                [name, source_slug, type, owner, Jsonb(settings or {})],
            )
        ).fetchone()
        assert row is not None
        for stream, feeds in (streams or {'files': dataset}).items():
            table = source_slug if streams is None else free(f'{source_slug}_{stream}')[:63]
            await conn.execute(
                'insert into source_stream (source_id, name, raw_table, dataset) values (%s, %s, %s, %s)', [row[0], stream, table, feeds]
            )
    return str(row[0])


async def find_source(pool: AsyncConnectionPool, name: str) -> str | None:
    async with pool.connection() as conn:
        row = await (await conn.execute('select id::text from source where lower(name) = lower(%s)', [name])).fetchone()
    return None if row is None else str(row[0])


async def list_sources(pool: AsyncConnectionPool) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            """select s.id::text, s.name, s.type, s.state,
                      (select string_agg(distinct st.dataset, ', ') from source_stream st where st.source_id = s.id) as dataset,
                      (select min(st.raw_table) from source_stream st where st.source_id = s.id) as raw_table, s.created_at,
                      (select max(created_at) from sync where source_id = s.id) as last_sync,
                      (select count(*) from sync where source_id = s.id and status = 'review') as waiting,
                      (select status from sync where source_id = s.id order by created_at desc limit 1) as last_status
               from source s
               order by s.name"""
        )
        names = [c.name for c in cur.description or []]
        return [dict(zip(names, r, strict=True)) for r in await cur.fetchall()]


SYNC_COLUMNS = sql.SQL("""y.id::text, y.source_id::text, y.stream_id::text, y.user_id::text, y.as_of, y.sheet, y.header_row, y.file_name,
    y.incoming_url, y.status, y.sha256, y.layout_id, y.found_header_row, y.notes, y.profile, y.rows, y.repeat, y.tests, y.note, y.error,
    y.created_at, y.finished_at, y.agent, y.endpoint, a.name as by_name, a.is_admin as by_admin""")


async def get_source(pool: AsyncConnectionPool, source_id: str) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        cur = await conn.execute(
            """select s.id::text, s.name, s.type, s.state, s.slug, s.settings, s.created_at, s.approved_at, st.id::text as stream_id,
                      st.dataset, st.raw_table, a.name as approved_by
               from source s join source_stream st on st.source_id = s.id left join app_user a on a.id = s.approved_by
               where s.id::text = %s order by st.name""",
            [source_id],
        )
        row = await cur.fetchone()
        if row is None:
            return None
        source = dict(zip([c.name for c in cur.description or []], row, strict=True))
        streams = await (
            await conn.execute(
                """select st.id::text, st.name, st.dataset, st.raw_table,
                          (select status from sync where stream_id = st.id order by created_at desc limit 1) as last_status
                   from source_stream st where st.source_id::text = %s order by st.name""",
                [source_id],
            )
        ).fetchall()
        source['streams'] = [dict(zip(('id', 'name', 'dataset', 'raw_table', 'last_status'), r, strict=True)) for r in streams]
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
            sql.SQL("""select {}, st.dataset, st.raw_table, st.name as stream_name, st.row_key, s.name as source_name,
                s.state as source_state,
                s.slug, s.type as source_type, s.settings as source_settings
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
               where id::text = %s and status in ('review', 'loaded', 'failed', 'stale')
                 and (incoming_url is not null or endpoint is not null)""",
            [keep_header, header_row, sync_id],
        )
        return cur.rowcount == 1


async def approve_source(pool: AsyncConnectionPool, source_id: str, user_id: str) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """update source set state = 'live', approved_by = %s, approved_at = now() where id::text = %s and state = 'draft'""",
            [user_id, source_id],
        )


async def queue_endpoint_syncs(pool: AsyncConnectionPool, source_id: str, user_id: str | None, as_of: Any) -> list[str]:
    """One queued sync per stream of an API source (each reads its endpoint); returns their ids. A stream with a sync still queued or
    running is left alone."""
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """insert into sync (source_id, stream_id, user_id, as_of, endpoint)
                   select st.source_id, st.id, %s, %s, st.name from source_stream st
                   where st.source_id::text = %s
                     and not exists (select 1 from sync y where y.stream_id = st.id and y.status in ('queued', 'running'))
                   returning id::text""",
                [user_id, as_of, source_id],
            )
        ).fetchall()
    return [str(r[0]) for r in rows]


async def due_api_sources(pool: AsyncConnectionPool) -> list[str]:
    """Live API sources whose schedule says a sync is due: hourly or daily, counted from their last sync."""
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """select s.id::text from source s
                   where s.type = 'api' and s.state = 'live' and s.settings->>'schedule' in ('hourly', 'daily')
                     and coalesce((select max(created_at) from sync y where y.source_id = s.id), '-infinity')
                         < now() - case s.settings->>'schedule' when 'hourly' then interval '1 hour' else interval '1 day' end"""
            )
        ).fetchall()
    return [str(r[0]) for r in rows]


# Column decisions at review (C1b, docs/connect-data-spec.md § 6.7).

DECISION_FIELDS = ('personal', 'reason', 'keep', 'kind', 'label', 'description')


async def column_decisions(pool: AsyncConnectionPool, stream_id: str) -> dict[str, dict[str, Any]]:
    """What a person decided about each column of a stream, by column name."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            """select c.name, c.personal, c.reason, c.keep, c.kind, c.label, c.description, a.name as decided_by, c.decided_at
               from stream_column c left join app_user a on a.id = c.decided_by where c.stream_id::text = %s""",
            [stream_id],
        )
        names = [d.name for d in cur.description or []]
        rows = [dict(zip(names, r, strict=True)) for r in await cur.fetchall()]
    return {r.pop('name'): r for r in rows}


async def save_column_decisions(
    pool: AsyncConnectionPool, stream_id: str, decisions: dict[str, dict[str, Any]], user_id: str | None
) -> None:
    """Saves the decisions given (a column's decision replaces its earlier one as a whole)."""
    async with pool.connection() as conn, conn.transaction():
        for name, d in decisions.items():
            await conn.execute(
                """insert into stream_column (stream_id, name, personal, reason, keep, kind, label, description, decided_by)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   on conflict (stream_id, name) do update set personal = excluded.personal, reason = excluded.reason,
                     keep = excluded.keep, kind = excluded.kind, label = excluded.label, description = excluded.description,
                     decided_by = excluded.decided_by, decided_at = now()""",
                [stream_id, name, d.get('personal'), d.get('reason'), d.get('keep', True), d.get('kind'),
                 Jsonb(d.get('label') or {}), Jsonb(d.get('description') or {}), user_id],
            )  # fmt: skip


async def set_row_key(pool: AsyncConnectionPool, stream_id: str, columns: list[str] | None) -> None:
    async with pool.connection() as conn:
        await conn.execute('update source_stream set row_key = %s where id::text = %s', [columns or None, stream_id])


async def row_key_check(pool: AsyncConnectionPool, schema: str, table: str, sync_id: str, columns: list[str]) -> dict[str, int]:
    """For the rows a sync loaded: how many have an empty key part, and how many keys are repeated (a key is a row key only when both
    are 0)."""
    key = sql.SQL(', ').join(sql.Identifier(c) for c in columns)
    empty = sql.SQL(' or ').join(sql.SQL('nullif(trim({}::text), {}) is null').format(sql.Identifier(c), sql.Literal('')) for c in columns)
    tbl = sql.Identifier(schema, table)
    async with pool.connection() as conn:
        e = await (
            await conn.execute(sql.SQL('select count(*) from {} where _bi_sync_id = %s and ({})').format(tbl, empty), [sync_id])
        ).fetchone()
        d = await (
            await conn.execute(
                sql.SQL(
                    'select coalesce(sum(n - 1), 0) from (select count(*) as n from {} where _bi_sync_id = %s group by {}) g where n > 1'
                ).format(tbl, key),
                [sync_id],
            )
        ).fetchone()
    return {'empty': int(e[0]) if e else 0, 'repeated': int(d[0]) if d else 0}
