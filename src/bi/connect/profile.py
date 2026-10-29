"""What each column holds, without its rows (spec § 6.3, § 6.4; DEC-017, DEC-028). Computed in PostgreSQL on loaded data: the kind of a
column, how many values are empty or distinct, the shape of its values as patterns, ranges for numbers and dates, and the categories
with their counts at or above the suppression threshold. A column that names a person or identifies one is reported as a count and a
shape only, never with values. The person on the page and the model see the same profile."""

from __future__ import annotations

from typing import Any

from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from .. import packs

# Which column names suggest a person or a record's identifier comes from the language packs (bi.packs), never from code.
METADATA = {'_bi_file_name', '_bi_file_sha256', '_bi_sheet', '_bi_sync_id', '_bi_layout', '_bi_row', '_bi_as_of', '_bi_loaded_at'}
TEXT_TYPES = {'text', 'character varying', 'character', 'varchar'}
NUMBER_TYPES = {'integer', 'bigint', 'smallint', 'numeric', 'double precision', 'real'}
DATE_TYPES = {'date', 'timestamp without time zone', 'timestamp with time zone'}
MAX_CATEGORIES = 50
SHAPES_SHOWN = 5
PATTERN_SQL = "regexp_replace(regexp_replace(regexp_replace({col}, '[0-9]', '9', 'g'), '[A-Z]', 'A', 'g'), '[a-z]', 'a', 'g')"
_DATE_RE = r'^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?$'
_NUMBER_RE = r'^[-+]?\d+(\.\d+)?$'
_EMAIL_RE = r'^[^@\s]+@[^@\s]+\.[^@\s]+$'


def _short(pattern: str) -> str:
    return pattern if len(pattern) <= 40 else pattern[:39] + '…'


def _where(*conds: sql.Composable | None) -> sql.Composable:
    present = [c for c in conds if c is not None]
    return sql.SQL(' where ') + sql.SQL(' and ').join(sql.SQL('({})').format(c) for c in present) if present else sql.SQL('')


async def _columns(pool: AsyncConnectionPool, schema: str, table: str) -> list[tuple[str, str]]:
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """select column_name, data_type from information_schema.columns
                   where table_schema = %s and table_name = %s and column_name not like '\\_dlt\\_%%' order by ordinal_position""",
                [schema, table],
            )
        ).fetchall()
    return [(c, t) for c, t in rows]


async def profile_table(
    pool: AsyncConnectionPool, schema: str, table: str, threshold: int, where: sql.Composable | None = None
) -> dict[str, Any]:
    """The profile of every column of a table (or of the rows `where` selects): {'rows': n, 'columns': [...]}."""
    cols = await _columns(pool, schema, table)
    if not cols:
        return {'rows': 0, 'columns': []}
    tbl = sql.Identifier(schema, table)
    counts_sql = sql.SQL('select count(*), {} from {}{}').format(
        sql.SQL(', ').join(sql.SQL('count({c}), count(distinct {c})').format(c=sql.Identifier(c)) for c, _ in cols), tbl, _where(where)
    )
    async with pool.connection() as conn:
        counts = (await (await conn.execute(counts_sql)).fetchone()) or (0,)
    n_rows = counts[0]
    out = []
    for i, (column, dtype) in enumerate(cols):
        non_null, distinct = counts[1 + 2 * i], counts[2 + 2 * i]
        out.append(await _profile_column(pool, tbl, where, column, dtype, n_rows, non_null, distinct, threshold))
    return {'rows': n_rows, 'columns': out}


async def _profile_column(
    pool: AsyncConnectionPool,
    tbl: sql.Identifier,
    rows_of: sql.Composable | None,
    column: str,
    dtype: str,
    n_rows: int,
    non_null: int,
    distinct: int,
    threshold: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        'name': column,
        'type': dtype,
        'null_rate': round(1 - non_null / n_rows, 4) if n_rows else None,
        'distinct': distinct,
    }
    if column in METADATA:
        out['kind'] = 'metadata'
        return out
    col = sql.Identifier(column)
    text = sql.SQL('{}::text').format(col)

    async def rows(query: sql.Composed) -> list[tuple[Any, ...]]:
        async with pool.connection() as conn:
            return await (await conn.execute(query)).fetchall()

    async def share(regex: str) -> float:
        if not non_null:
            return 0.0
        cond = sql.SQL('{} ~ {}').format(text, sql.Literal(regex))
        found = await rows(sql.SQL('select count(*) from {t}{w}').format(t=tbl, w=_where(rows_of, cond)))
        return float(found[0][0]) / non_null

    async def patterns() -> list[dict[str, Any]]:
        pat = sql.SQL(PATTERN_SQL).format(col=text)
        found = await rows(
            sql.SQL('select {p} as p, count(*) from {t}{w} group by p order by count(*) desc limit {k}').format(
                p=pat, t=tbl, w=_where(rows_of, sql.SQL('{} is not null').format(col)), k=sql.Literal(SHAPES_SHOWN)
            )
        )
        return [{'pattern': _short(p), 'rows': n} for p, n in found if n >= threshold]

    async def span(cast: str) -> None:
        typed = sql.SQL('{}::{}').format(text, sql.SQL(cast)) if dtype in TEXT_TYPES else col
        regex = _DATE_RE if cast == 'date' else _NUMBER_RE
        cond = sql.SQL('{} ~ {}').format(text, sql.Literal(regex)) if dtype in TEXT_TYPES else None
        lo = await rows(sql.SQL('select min({v}), max({v}) from {t}{w}').format(v=typed, t=tbl, w=_where(rows_of, cond)))
        if lo and lo[0][0] is not None:
            out['min'], out['max'] = (v.isoformat() if hasattr(v, 'isoformat') else float(v) for v in lo[0])

    personal = packs.looks_personal(column) or (dtype in TEXT_TYPES and await share(_EMAIL_RE) >= 0.5)
    unique = non_null >= 20 and distinct >= 0.9 * non_null
    if personal:
        out['kind'] = 'personal'  # a count and a shape; never values, never mapped unless a person chooses it
        out['patterns'] = await patterns()
    elif dtype in DATE_TYPES or (dtype in TEXT_TYPES and non_null and await share(_DATE_RE) >= 0.9):
        out['kind'] = 'date'
        await span('date')
    elif packs.looks_identifying(column) or unique:
        out['kind'] = 'identifier'  # a count and a shape; its values are never shown
        out['patterns'] = await patterns()
    elif dtype in NUMBER_TYPES or (dtype in TEXT_TYPES and non_null and distinct > MAX_CATEGORIES and await share(_NUMBER_RE) >= 0.9):
        out['kind'] = 'number'
        await span('numeric')
    elif dtype in TEXT_TYPES or dtype == 'boolean':
        if distinct <= MAX_CATEGORIES:
            out['kind'] = 'category' if dtype != 'boolean' else 'boolean'
            found = await rows(
                sql.SQL('select {c}, count(*) from {t}{w} group by {c} order by count(*) desc').format(
                    c=col, t=tbl, w=_where(rows_of, sql.SQL('{} is not null').format(col))
                )
            )
            shown = [(v, n) for v, n in found if n >= threshold and len(str(v)) <= 60]
            out['values'] = [{'value': v, 'rows': n} for v, n in shown]
            hidden = sum(n for _, n in found) - sum(n for _, n in shown)
            if hidden:
                out['other_rows'] = hidden  # rows whose value is rare (or long) and so not named
        else:
            out['kind'] = 'text'
            out['patterns'] = await patterns()
    else:
        out['kind'] = 'other'
    return out


def summary(profile: dict[str, Any]) -> str:
    """One line a person can read about a column: what it holds, never its values when it is personal or an identifier."""
    kind = profile.get('kind')
    distinct = profile.get('distinct', 0)
    empty = profile.get('null_rate') or 0
    tail = f', {round(empty * 100)}% empty' if empty >= 0.01 else ''
    if kind in ('personal', 'identifier'):
        shape = profile.get('patterns') or []
        shape_text = f' like {shape[0]["pattern"]}' if shape else ''
        what = 'personal data' if kind == 'personal' else 'an identifier'
        return f'{what}{shape_text}, {distinct} different values{tail}'
    if kind in ('date', 'number') and 'min' in profile:
        return f'{"dates" if kind == "date" else "numbers"} from {profile["min"]} to {profile["max"]}{tail}'
    if kind in ('category', 'boolean'):
        values = [v['value'] for v in profile.get('values', [])][:4]
        more = ', …' if distinct > len(values) else ''
        noun = 'value' if distinct == 1 else 'values'
        return f'{distinct} {noun}: {", ".join(str(v) for v in values)}{more}{tail}' if values else f'{distinct} {noun}{tail}'
    if kind == 'text':
        return f'free text, {distinct} different values{tail}'
    return f'{distinct} different values{tail}'
