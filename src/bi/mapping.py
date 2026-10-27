"""What a dataset needs from its files, and which of a file's columns supplies it. Files are not made to fit: the columns a file has are
discovered when it is loaded (raw keeps them as written), matched to the parts the dataset needs by name, and a person approves any
match that is not exact. The transform (transform/models/staging) reads the approved mapping as a dbt variable."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


@dataclass(frozen=True)
class Field:
    name: str
    required: bool
    aliases: tuple[str, ...] = ()
    """Other names an export is likely to use (compared without case, spaces or punctuation)."""


# The governed shape of each dataset the metric layer is built on. A dataset with no entry here is loaded to raw and nothing more.
SHAPES: dict[str, list[Field]] = {
    'enrollment': [
        Field('student_id', True, ('studentid', 'studentnumber', 'studentno', 'sid', 'idbanner', 'id')),
        Field('term_code', True, ('termcode', 'termid', 'semestercode', 'periodcode', 'term', 'semester')),
        Field('term', False, ('termname', 'termlabel', 'termdescription', 'semestername')),
        Field('term_start', True, ('termstart', 'termstartdate', 'startdate', 'semesterstart', 'begindate')),
        Field('term_end', False, ('termend', 'termenddate', 'enddate', 'semesterend')),
        Field('program', False, ('programme', 'major', 'programcode', 'programname', 'degreeprogram')),
        Field('level', False, ('studentlevel', 'degreelevel', 'levelcode', 'academiclevel', 'classlevel')),
        Field('status', False, ('enrollmentstatus', 'enrolmentstatus', 'registrationstatus', 'studentstatus')),
    ]
}


class MappingError(ValueError):
    """A mapping that cannot be used (a part left out, a column the data does not have)."""


def norm(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', name.lower())


def fields(dataset: str) -> list[Field]:
    return SHAPES.get(dataset, [])


def propose(dataset: str, columns: list[str]) -> tuple[dict[str, str | None], bool]:
    """Matches the dataset's parts to the columns found: by the part's own name first (exact), then by the names exports use (a guess).
    Returns the mapping (None where nothing matched) and whether every part that is needed matched by its own name."""
    by_norm: dict[str, str] = {}
    for c in columns:
        by_norm.setdefault(norm(c), c)
    mapping: dict[str, str | None] = {}
    exact = True
    taken: set[str] = set()
    for f in fields(dataset):  # first pass: own names, so a loose alias never takes a column another part names exactly
        own = by_norm.get(norm(f.name))
        if own:
            mapping[f.name] = own
            taken.add(own)
    for f in fields(dataset):
        if f.name in mapping:
            continue
        found = next((by_norm[a] for a in f.aliases if a in by_norm and by_norm[a] not in taken), None)
        mapping[f.name] = found
        if found:
            taken.add(found)
        if f.required:
            exact = False
    return mapping, exact


def check(dataset: str, mapping: dict[str, str | None], columns: list[str]) -> None:
    """Raises MappingError unless the mapping names every needed part, and only columns the data has."""
    known = {f.name: f for f in fields(dataset)}
    for part, column in mapping.items():
        if part not in known:
            raise MappingError(f'"{part}" is not a part of the {dataset} dataset')
        if column is not None and column not in columns:
            raise MappingError(f'the data has no column "{column}"')
    missing = [f.name for f in known.values() if f.required and not mapping.get(f.name)]
    if missing:
        raise MappingError(f'no column is chosen for: {", ".join(missing)}')


async def raw_columns(pool: AsyncConnectionPool, dataset: str) -> list[str]:
    """The columns the latest file of this dataset has, as raw keeps them (the BI's own bookkeeping columns left out)."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            """select column_name from information_schema.columns
               where table_schema = 'raw' and table_name = %s and column_name not like '\\_bi\\_%%' and column_name not like '\\_dlt\\_%%'
               order by ordinal_position""",
            [dataset],
        )
        every = [r[0] for r in await cur.fetchall()]
        if not every:
            return []
        table = sql.Identifier('raw', dataset)
        counts = sql.SQL(', ').join(sql.SQL('count({}) filter (where _bi_loaded_at = latest.at)').format(sql.Identifier(c)) for c in every)
        query = sql.SQL('select {counts} from {table}, (select max(_bi_loaded_at) as at from {table}) latest').format(
            counts=counts, table=table
        )
        row = await (await conn.execute(query)).fetchone()
    return [c for c, n in zip(every, row or [], strict=False) if n]


async def unreadable(pool: AsyncConnectionPool, dataset: str, mapping: dict[str, str | None]) -> list[str]:
    """The files in raw that do not have a column the mapping reads for a part that is needed (an export with another layout)."""
    needed = [mapping[f.name] for f in fields(dataset) if f.required and mapping.get(f.name)]
    if not needed:
        return []
    blank = sql.SQL(' or ').join(sql.SQL('{} is null').format(sql.Identifier(c)) for c in needed if c)
    query = sql.SQL('select distinct _bi_file_name from raw.{} where {} order by 1').format(sql.Identifier(dataset), blank)
    async with pool.connection() as conn:
        return [r[0] for r in await (await conn.execute(query)).fetchall()]


async def stored(pool: AsyncConnectionPool, dataset: str) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        row = await (
            await conn.execute('select mapping, status, approved_how, error, built_at from column_mapping where dataset = %s', [dataset])
        ).fetchone()
    if row is None:
        return None
    return {'mapping': row[0], 'status': row[1], 'approved_how': row[2], 'error': row[3], 'built_at': row[4]}


async def save(
    pool: AsyncConnectionPool, dataset: str, mapping: dict[str, str | None], status: str, how: str | None, user_id: str | None = None
) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """insert into column_mapping (dataset, mapping, status, approved_by, approved_how, error)
               values (%s, %s, %s, %s, %s, null)
               on conflict (dataset) do update set mapping = excluded.mapping, status = excluded.status,
                 approved_by = excluded.approved_by, approved_how = excluded.approved_how, error = null, updated_at = now()""",
            [dataset, Jsonb(mapping), status, user_id, how],
        )


async def record_build(pool: AsyncConnectionPool, dataset: str, error: str | None) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            'update column_mapping set error = %s, built_at = case when %s::text is null then now() else built_at end where dataset = %s',
            [error, error, dataset],
        )


def dbt_vars(dataset: str, mapping: dict[str, str | None]) -> dict[str, Any]:
    return {f'{dataset}_columns': mapping}
