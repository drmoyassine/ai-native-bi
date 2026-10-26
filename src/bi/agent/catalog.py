"""The catalog: which datasets exist and what is in them, as the model may see it (DEC-017). A profile has column names and types, null
rates, distinct counts, numeric and date ranges, categories with counts at or above the suppression threshold, and the *shape* of
values as patterns ("999999999", "9999-99-99"). It never has a row, an identifier's value or free text."""

from __future__ import annotations

import re
from importlib import resources
from typing import Any

import yaml
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

# A column that names a person or an identifier is never shown as values, whatever it contains.
ID_NAME = re.compile(r'(^|_)(id|ids|identifier|ssn|national|email|phone|mobile|name|dob|birth|birthdate|address|passport)($|_)', re.I)
TEXT_TYPES = {'text', 'character varying', 'character', 'varchar'}
NUMBER_TYPES = {'integer', 'bigint', 'smallint', 'numeric', 'double precision', 'real'}
DATE_TYPES = {'date', 'timestamp without time zone', 'timestamp with time zone'}
METADATA_ONLY = {'_bi_file_name', '_bi_file_sha256', '_bi_sheet'}
MAX_CATEGORIES = 50
PATTERN_SQL = "regexp_replace(regexp_replace(regexp_replace({col}, '[0-9]', '9', 'g'), '[A-Z]', 'A', 'g'), '[a-z]', 'a', 'g')"


def datasets() -> list[str]:
    """The datasets the transforms know (the raw sources of the dbt project): what an upload can be."""
    text = (resources.files('bi') / 'transform' / 'models' / 'sources.yml').read_text('utf-8')
    return sorted(t['name'] for s in yaml.safe_load(text)['sources'] if s['name'] == 'raw' for t in s['tables'])


class CatalogError(ValueError):
    """The dataset is not one the BI knows."""


async def _table_exists(pool: AsyncConnectionPool, schema: str, table: str) -> bool:
    async with pool.connection() as conn:
        row = await (await conn.execute('select to_regclass(%s) is not null', [f'{schema}.{table}'])).fetchone()
    return bool(row and row[0])


async def list_datasets(pool: AsyncConnectionPool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in datasets():
        entry: dict[str, Any] = {'dataset': name, 'tables': {}}
        for schema in ('raw', 'analytics'):
            if await _table_exists(pool, schema, name):
                async with pool.connection() as conn:
                    n = await (
                        await conn.execute(sql.SQL('select count(*) from {}.{}').format(sql.Identifier(schema), sql.Identifier(name)))
                    ).fetchone()
                entry['tables'][schema] = {'rows': n[0] if n else 0}
        if 'raw' in entry['tables']:
            async with pool.connection() as conn:
                row = await (
                    await conn.execute(
                        sql.SQL('select max(_bi_as_of), max(_bi_loaded_at), count(distinct _bi_file_sha256) from raw.{}').format(
                            sql.Identifier(name)
                        )
                    )
                ).fetchone()
            if row:
                entry['last_load'] = {'as_of': row[0], 'loaded_at': row[1].isoformat() if row[1] else None, 'files': row[2]}
        out.append(entry)
    return out


def _short(pattern: str) -> str:
    return pattern if len(pattern) <= 40 else pattern[:39] + '…'


async def _profile_column(
    pool: AsyncConnectionPool, schema: str, table: str, column: str, dtype: str, n_rows: int, non_null: int, distinct: int, threshold: int
) -> dict[str, Any]:
    out: dict[str, Any] = {
        'name': column,
        'type': dtype,
        'null_rate': round(1 - non_null / n_rows, 4) if n_rows else None,
        'distinct': distinct,
    }
    if column in METADATA_ONLY:
        out['kind'] = 'metadata'
        return out
    identifier = bool(ID_NAME.search(column)) or (non_null >= 20 and distinct >= 0.9 * non_null)
    tbl, col = sql.Identifier(schema, table), sql.Identifier(column)

    async def rows(query: sql.Composed) -> list[tuple[Any, ...]]:
        async with pool.connection() as conn:
            return await (await conn.execute(query)).fetchall()

    async def patterns() -> list[dict[str, Any]]:
        pat = sql.SQL(PATTERN_SQL).format(col=sql.SQL('{}::text').format(col))
        found = await rows(
            sql.SQL('select {p} as p, count(*) from {t} where {c} is not null group by p order by count(*) desc limit 5').format(
                p=pat, t=tbl, c=col
            )
        )
        return [{'pattern': _short(p), 'rows': n} for p, n in found if n >= threshold]

    if identifier:
        out['kind'] = 'identifier'  # reported as a count and a shape; its values are never shown
        if dtype in TEXT_TYPES or dtype in NUMBER_TYPES:
            out['patterns'] = await patterns()
    elif dtype in TEXT_TYPES:
        if distinct <= MAX_CATEGORIES:
            out['kind'] = 'category'
            found = await rows(
                sql.SQL('select {c}, count(*) from {t} where {c} is not null group by {c} order by count(*) desc').format(c=col, t=tbl)
            )
            shown = [(v, n) for v, n in found if n >= threshold and len(str(v)) <= 60]
            out['values'] = [{'value': v, 'rows': n} for v, n in shown]
            hidden = sum(n for v, n in found) - sum(n for v, n in shown)
            if hidden:
                out['other_rows'] = hidden  # rows whose value is rare (or long) and so not named
        else:
            out['kind'] = 'text'
            out['patterns'] = await patterns()
    elif dtype in NUMBER_TYPES or dtype in DATE_TYPES:
        out['kind'] = 'number' if dtype in NUMBER_TYPES else 'date'
        lo = await rows(sql.SQL('select min({c}), max({c}) from {t}').format(c=col, t=tbl))
        if lo and lo[0][0] is not None:
            out['min'], out['max'] = (v.isoformat() if hasattr(v, 'isoformat') else float(v) for v in lo[0])
    elif dtype == 'boolean':
        out['kind'] = 'boolean'
        found = await rows(sql.SQL('select {c}, count(*) from {t} where {c} is not null group by {c}').format(c=col, t=tbl))
        out['values'] = [{'value': v, 'rows': n} for v, n in found if n >= threshold]
    else:
        out['kind'] = 'other'
    return out


async def describe_dataset(pool: AsyncConnectionPool, name: str, threshold: int) -> dict[str, Any]:
    if name not in datasets():
        raise CatalogError(f'unknown dataset "{name}" (known: {", ".join(datasets())})')
    result: dict[str, Any] = {'dataset': name, 'tables': {}}
    for schema in ('raw', 'analytics'):
        if not await _table_exists(pool, schema, name):
            continue
        async with pool.connection() as conn:
            cols = await (
                await conn.execute(
                    """select column_name, data_type from information_schema.columns
                       where table_schema = %s and table_name = %s and column_name not like '\\_dlt\\_%%' order by ordinal_position""",
                    [schema, name],
                )
            ).fetchall()
            counts_sql = sql.SQL('select count(*), {} from {}').format(
                sql.SQL(', ').join(sql.SQL('count({c}), count(distinct {c})').format(c=sql.Identifier(c)) for c, _ in cols),
                sql.Identifier(schema, name),
            )
            counts = (await (await conn.execute(counts_sql)).fetchone()) or (0,)
        n_rows = counts[0]
        profiles = [
            await _profile_column(pool, schema, name, c, t, n_rows, counts[1 + 2 * i], counts[2 + 2 * i], threshold)
            for i, (c, t) in enumerate(cols)
        ]
        result['tables'][schema] = {'rows': n_rows, 'columns': profiles}
    if not result['tables']:
        result['note'] = 'nothing has been loaded for this dataset yet'
    return result
