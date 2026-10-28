"""The catalog: which datasets exist and what is in them, as the model may see it (DEC-017). A profile has column names and types, null
rates, distinct counts, numeric and date ranges, categories with counts at or above the suppression threshold, and the *shape* of
values as patterns ("999999999", "9999-99-99"). It never has a row, an identifier's value or free text."""

from __future__ import annotations

from typing import Any

from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from .. import mapping
from ..connect.profile import profile_table


def datasets() -> list[str]:
    """The datasets the metric layer is built on (bi.mapping): what a source can feed."""
    return mapping.datasets()


class CatalogError(ValueError):
    """The dataset is not one the BI knows."""


async def _table_exists(pool: AsyncConnectionPool, schema: str, table: str) -> bool:
    async with pool.connection() as conn:
        row = await (await conn.execute('select to_regclass(%s) is not null', [f'{schema}."{table}"'])).fetchone()
    return bool(row and row[0])


async def _rows(pool: AsyncConnectionPool, schema: str, table: str) -> int:
    async with pool.connection() as conn:
        row = await (await conn.execute(sql.SQL('select count(*) from {}').format(sql.Identifier(schema, table)))).fetchone()
    return int(row[0]) if row else 0


async def _streams(pool: AsyncConnectionPool) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            """select st.raw_table, st.dataset, s.name, s.type,
                      (select max(as_of) from sync y where y.stream_id = st.id and y.status = 'loaded') as as_of,
                      (select max(finished_at) from sync y where y.stream_id = st.id and y.status = 'loaded') as loaded_at,
                      (select count(*) from sync y where y.stream_id = st.id and y.status = 'loaded') as syncs
               from source_stream st join source s on s.id = st.source_id where s.state = 'live' order by s.name"""
        )
        names = [c.name for c in cur.description or []]
        return [dict(zip(names, r, strict=True)) for r in await cur.fetchall()]


async def list_datasets(pool: AsyncConnectionPool) -> list[dict[str, Any]]:
    """The datasets (built for the metric layer) and the sources' raw tables, with row counts and their last load."""
    streams = await _streams(pool)
    out: list[dict[str, Any]] = []
    for name in datasets():
        entry: dict[str, Any] = {'dataset': name, 'kind': 'dataset', 'tables': {},
                                 'sources': [s['name'] for s in streams if s['dataset'] == name]}  # fmt: skip
        if await _table_exists(pool, 'analytics', name):
            entry['tables']['analytics'] = {'rows': await _rows(pool, 'analytics', name)}
        out.append(entry)
    for s in streams:
        entry = {'dataset': s['raw_table'], 'kind': 'source', 'source': s['name'], 'type': s['type'], 'feeds': s['dataset'], 'tables': {}}
        if await _table_exists(pool, 'raw', s['raw_table']):
            entry['tables']['raw'] = {'rows': await _rows(pool, 'raw', s['raw_table'])}
        if s['syncs']:
            entry['last_load'] = {'as_of': s['as_of'].isoformat() if s['as_of'] else None,
                                  'loaded_at': s['loaded_at'].isoformat() if s['loaded_at'] else None, 'syncs': s['syncs']}  # fmt: skip
        out.append(entry)
    return out


async def describe_dataset(pool: AsyncConnectionPool, name: str, threshold: int) -> dict[str, Any]:
    """The profile of a dataset (its analytics table) or of a source's raw table. Never a row."""
    streams = {s['raw_table']: s for s in await _streams(pool)}
    if name in datasets():
        schema, extra = 'analytics', {'sources': [s['name'] for s in streams.values() if s['dataset'] == name]}
    elif name in streams:
        schema, extra = 'raw', {'source': streams[name]['name'], 'feeds': streams[name]['dataset']}
    else:
        known = [*datasets(), *streams]
        raise CatalogError(f'unknown dataset "{name}" (known: {", ".join(known)})')
    result: dict[str, Any] = {'dataset': name, **extra, 'tables': {}}
    if await _table_exists(pool, schema, name):
        result['tables'][schema] = await profile_table(pool, schema, name, threshold)
    else:
        result['note'] = 'nothing has been loaded for this dataset yet'
    return result
