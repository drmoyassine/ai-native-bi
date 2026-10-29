"""What a dataset needs, and which column of a layout supplies it (DEC-026, DEC-029). Data is not made to fit: the columns a stream has are
discovered, matched to the parts the dataset needs by name and by what the columns hold, and a person approves any match that is not
exact. Mappings are kept per layout, so files of several layouts can feed one dataset. The transforms read the approved mappings as
the dbt variable `<dataset>_inputs`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from . import packs
from .languages import PRIMARY_LANGUAGE

Expects = Literal['key', 'date', 'text']


@dataclass(frozen=True)
class Field:
    name: str
    required: bool
    label: str
    description: str
    expects: Expects = 'text'
    """What the column must hold: a key (an identifier or a code), a date, or any text that is not personal."""
    aliases: tuple[str, ...] = ()
    """Other names an export is likely to use (compared without case, spaces or punctuation)."""


def _field(part: dict[str, Any]) -> Field:
    return Field(
        name=part['name'],
        required=bool(part.get('needed', False)),
        label=part.get('label', {}).get(PRIMARY_LANGUAGE, part['name']),
        description=part.get('description', {}).get(PRIMARY_LANGUAGE, ''),
        expects=part.get('expects', 'text'),
        aliases=tuple(norm(a) for a in part.get('aliases', [])),
    )


def shapes() -> dict[str, list[Field]]:
    """What each dataset needs, from the templates shipped (bi.packs, DEC-037): the BI itself defines none. A stream that feeds no dataset
    is kept in raw and nothing more."""
    out: dict[str, list[Field]] = {}
    for template in packs.templates().values():
        for name, dataset in (template.get('datasets') or {}).items():
            out[name] = [_field(p) for p in dataset.get('parts', [])]
    return out


def dataset_label(name: str) -> str:
    for template in packs.templates().values():
        dataset = (template.get('datasets') or {}).get(name)
        if dataset:
            return str(dataset.get('label', {}).get(PRIMARY_LANGUAGE, name))
    return name


class MappingError(ValueError):
    """A mapping that cannot be used (a part left out, a column the data does not have)."""


def norm(name: str) -> str:
    """A name compared without case, spaces or punctuation, in any script."""
    return re.sub(r'[\W_]+', '', name.casefold())


def fields(dataset: str) -> list[Field]:
    return shapes().get(dataset, [])


def datasets(installed: list[str]) -> list[str]:
    """The datasets of the templates the organization installed: what a source can feed."""
    templates = packs.templates()
    return sorted(d for t in installed if t in templates for d in (templates[t].get('datasets') or {}))


async def installed_datasets(pool: AsyncConnectionPool) -> list[str]:
    async with pool.connection() as conn:
        row = await (await conn.execute('select installed_templates from organization')).fetchone()
    return datasets(list(row[0]) if row else [])


def fits(field: Field, kind: str | None) -> bool:
    """Whether a column of this kind (from its profile) can supply the part. Personal columns supply nothing unless a person says so."""
    if kind is None:
        return True
    if kind == 'personal':
        return False
    if field.expects == 'date':
        return kind == 'date'
    return kind != 'date'


def propose(dataset: str, columns: list[str], kinds: dict[str, str] | None = None) -> tuple[dict[str, str | None], bool]:
    """Matches the dataset's parts to the columns found: by the part's own name or label first (exact), then by the names exports use (a
    guess), never to a column whose profile does not fit the part. Returns the mapping (None where nothing matched) and whether every
    needed part matched by its own name."""
    kinds = kinds or {}
    by_norm: dict[str, str] = {}
    for c in columns:
        by_norm.setdefault(norm(c), c)
    mapping: dict[str, str | None] = {}
    taken: set[str] = set()
    exact = True
    for f in fields(dataset):  # first pass: own names, so a loose alias never takes a column another part names exactly
        own = by_norm.get(norm(f.name)) or by_norm.get(norm(f.label))
        if own and fits(f, kinds.get(own)):
            mapping[f.name] = own
            taken.add(own)
    for f in fields(dataset):
        if f.name in mapping:
            continue
        found = next((by_norm[a] for a in f.aliases if a in by_norm and by_norm[a] not in taken and fits(f, kinds.get(by_norm[a]))), None)
        mapping[f.name] = found
        if found:
            taken.add(found)
        if f.required:
            exact = False
    return mapping, exact


def check(dataset: str, mapping: dict[str, str | None], columns: list[str]) -> None:
    """Raises MappingError unless the mapping names every needed part, and only columns the data has, each at most once."""
    known = {f.name: f for f in fields(dataset)}
    for part, column in mapping.items():
        if part not in known:
            raise MappingError(f'"{part}" is not a part of the {dataset} dataset')
        if column is not None and column not in columns:
            raise MappingError(f'the data has no column "{column}"')
    chosen = [c for c in mapping.values() if c]
    if len(chosen) != len(set(chosen)):
        raise MappingError('a column can supply only one part')
    missing = [known[p].label for p in known if known[p].required and not mapping.get(p)]
    if missing:
        raise MappingError(f'no column is chosen for: {", ".join(missing)}')


async def stored(pool: AsyncConnectionPool, layout_id: str, dataset: str) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """select mapping, status, approved_how, proposed_by, reasons, model from layout_mapping
                   where layout_id = %s and dataset = %s""",
                [layout_id, dataset],
            )
        ).fetchone()
    if row is None:
        return None
    return {'mapping': row[0], 'status': row[1], 'approved_how': row[2], 'proposed_by': row[3], 'reasons': row[4], 'model': row[5]}


async def save(
    pool: AsyncConnectionPool,
    layout_id: str,
    dataset: str,
    mapping: dict[str, str | None],
    status: str,
    how: str | None,
    user_id: str | None = None,
    proposed_by: str = 'rules',
    reasons: dict[str, Any] | None = None,
    model: str | None = None,
) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """insert into layout_mapping (layout_id, dataset, mapping, status, approved_by, approved_how, proposed_by, reasons, model)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (layout_id, dataset) do update set mapping = excluded.mapping, status = excluded.status,
                 approved_by = excluded.approved_by, approved_how = excluded.approved_how, proposed_by = excluded.proposed_by,
                 reasons = excluded.reasons, model = excluded.model, updated_at = now()""",
            [layout_id, dataset, Jsonb(mapping), status, user_id, how, proposed_by, Jsonb(reasons) if reasons is not None else None, model],
        )


async def latest_approved(pool: AsyncConnectionPool, dataset: str, columns: list[str]) -> dict[str, str | None] | None:
    """The most recently approved mapping of this dataset that the columns can satisfy: the starting proposal for a changed layout."""
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                "select mapping from layout_mapping where dataset = %s and status = 'approved' order by updated_at desc", [dataset]
            )
        ).fetchall()
    for (mapping,) in rows:
        kept = {p: c if c in columns else None for p, c in mapping.items()}
        if any(kept.values()):
            return kept
    return None


async def inputs(pool: AsyncConnectionPool, dataset: str) -> list[dict[str, Any]]:
    """What the transforms read for a dataset: each raw table and layout with an approved mapping, the columns it reads, and the loaded
    syncs whose rows count (a sync that failed its tests is left out, though its rows stay in raw)."""
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """select st.raw_table, m.layout_id, m.mapping, array_agg(s.id::text order by s.created_at)
                   from layout_mapping m
                   join sync s on s.layout_id = m.layout_id and s.status = 'loaded'
                   join source_stream st on st.id = s.stream_id and st.dataset = m.dataset
                   where m.dataset = %s and m.status = 'approved'
                   group by st.raw_table, m.layout_id, m.mapping
                   order by st.raw_table, m.layout_id""",
                [dataset],
            )
        ).fetchall()
    return [{'table': table, 'layout': layout, 'columns': mapping, 'syncs': syncs} for table, layout, mapping, syncs in rows]


async def dbt_vars(pool: AsyncConnectionPool) -> dict[str, Any]:
    return {f'{d}_inputs': await inputs(pool, d) for d in shapes()}
