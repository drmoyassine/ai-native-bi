"""What the organization reports on (docs/data-model-spec.md section 6, M1; DEC-036, DEC-037): subjects, entities and events, stored
as versioned definitions. Nothing here names a domain: every subject, entity and event is configuration, made by a person or installed
from a template, and checked by the bodies below. A change is a draft until it is approved; the current definition is the latest
approved version. The warehouse models are generated from the current events (bi.generate); a template's Cube files are written where
Cube reads them (cube_model.file, read through cube/cube.js)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field, StringConstraints, model_validator

from . import packs

Kind = Literal['subject', 'entity', 'event']
Name = Annotated[str, StringConstraints(pattern=r'^[a-z][a-z0-9_]{0,62}$')]
Words = dict[str, Annotated[str, StringConstraints(max_length=2000)]]
"""Text by language code: {'en': ..., '<secondary>': ...}."""

# Columns every generated model adds after the parts; a part may not take their names.
RESERVED = {'as_of', 'source_file_sha256', 'loaded_at'}


class DefinitionError(ValueError):
    """A definition that cannot be saved or approved, with the reason."""


class _Body(BaseModel):
    model_config = {'extra': 'forbid'}


class Part(_Body):
    """One thing a source supplies to an event (or an attribute of an entity)."""

    name: Name
    needed: bool = False
    expects: Literal['key', 'date', 'text', 'number'] = 'text'
    personal: bool = False
    """Identifies or describes a person: counted, never shown (DEC-017)."""
    label: Words = Field(default_factory=dict)
    description: Words = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    """Other names an export is likely to use (compared without case, spaces or punctuation)."""
    normalize: Literal['lower'] | None = None


def _check_parts(parts: list[Part], *named: tuple[str, list[str]]) -> None:
    names = [p.name for p in parts]
    if len(names) != len(set(names)):
        raise ValueError('two parts have the same name')
    if RESERVED & set(names):
        raise ValueError(f'a part may not be named {", ".join(sorted(RESERVED & set(names)))}')
    for what, chosen in named:
        unknown = [c for c in chosen if c not in names]
        if unknown:
            raise ValueError(f'{what} names no part: {", ".join(unknown)}')


class SubjectBody(_Body):
    label: Words
    description: Words = Field(default_factory=dict)
    steward: str | None = None
    """The email of the person who approves what is defined in this subject (an admin always may)."""


class EntityBody(_Body):
    subject: Name
    label: Words
    description: Words = Field(default_factory=dict)
    key: Name
    personal: bool = False
    attributes: list[Part] = Field(default_factory=list)

    @model_validator(mode='after')
    def _key_is_an_attribute(self) -> EntityBody:
        _check_parts(self.attributes, ('the key', [self.key]))
        return self


class EventBody(_Body):
    subject: Name
    label: Words
    description: Words = Field(default_factory=dict)
    parts: Annotated[list[Part], Field(min_length=1)]
    grain: list[Name] = Field(default_factory=list)
    """The parts that make a row unique (checked by the generated tests)."""
    snapshot_by: list[Name] = Field(default_factory=list)
    """For a state: the parts whose latest load replaces the earlier ones (each period's newest load counts)."""

    @model_validator(mode='after')
    def _names(self) -> EventBody:
        _check_parts(self.parts, ('the grain', self.grain), ('snapshot_by', self.snapshot_by))
        return self


BODIES: dict[str, type[_Body]] = {'subject': SubjectBody, 'entity': EntityBody, 'event': EventBody}


def parse(kind: str, body: dict[str, Any]) -> Any:
    try:
        return BODIES[kind].model_validate(body)
    except ValueError as e:
        raise DefinitionError(f'the {kind} is not valid: {e}') from e


async def current(pool: AsyncConnectionPool, kind: Kind) -> dict[str, Any]:
    """The current (latest approved) body of each definition of a kind, by name."""
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """select distinct on (name) name, body from definition where kind = %s and status = 'approved'
                   order by name, version desc""",
                [kind],
            )
        ).fetchall()
    return {name: parse(kind, body) for name, body in rows}


async def events(pool: AsyncConnectionPool) -> dict[str, EventBody]:
    found: dict[str, EventBody] = await current(pool, 'event')
    return found


async def listing(pool: AsyncConnectionPool) -> list[dict[str, Any]]:
    """Every definition's current version and its draft, if any (for the Model page and the API)."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            """select kind, name, version, status, body, template, created_at, approved_at from definition
               where status <> 'retired' order by kind, name, version"""
        )
        names = [c.name for c in cur.description or []]
        rows = [dict(zip(names, r, strict=True)) for r in await cur.fetchall()]
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        entry = out.setdefault((r['kind'], r['name']), {'kind': r['kind'], 'name': r['name'], 'current': None, 'draft': None})
        view = {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in r.items() if k not in ('kind', 'name')}
        entry['draft' if r['status'] == 'draft' else 'current'] = view
    return list(out.values())


async def save_draft(pool: AsyncConnectionPool, kind: Kind, name: str, body: dict[str, Any], user_id: str | None) -> int:
    """Saves a draft (replacing an earlier draft of the same definition); returns its version."""
    parsed = parse(kind, body)
    subject = getattr(parsed, 'subject', None)
    if subject is not None and subject not in await current(pool, 'subject'):
        raise DefinitionError(f'no approved subject named "{subject}"')
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("delete from definition where kind = %s and name = %s and status = 'draft'", [kind, name])
        row = await (
            await conn.execute('select coalesce(max(version), 0) + 1 from definition where kind = %s and name = %s', [kind, name])
        ).fetchone()
        version = int(row[0]) if row else 1
        await conn.execute(
            'insert into definition (kind, name, version, status, body, created_by) values (%s, %s, %s, %s, %s, %s)',
            [kind, name, version, 'draft', Jsonb(parsed.model_dump(exclude_defaults=True)), user_id],
        )
    return version


async def is_steward(pool: AsyncConnectionPool, subject_name: str, email: str) -> bool:
    subject = (await current(pool, 'subject')).get(subject_name)
    return bool(subject and subject.steward and subject.steward.lower() == email.lower())


async def may_approve(pool: AsyncConnectionPool, kind: Kind, name: str, email: str, is_admin: bool) -> bool:
    """An admin, or the steward of the subject the definition belongs to (DEC-006)."""
    if is_admin:
        return True
    async with pool.connection() as conn:
        row = await (
            await conn.execute("select body from definition where kind = %s and name = %s and status = 'draft'", [kind, name])
        ).fetchone()
    if row is None:
        return False
    return await is_steward(pool, name if kind == 'subject' else str(row[0].get('subject')), email)


async def approve(pool: AsyncConnectionPool, kind: Kind, name: str, user_id: str | None) -> int:
    """Approves the draft: it becomes the current definition. Returns its version."""
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """update definition set status = 'approved', approved_by = %s, approved_at = now()
                   where kind = %s and name = %s and status = 'draft' returning version""",
                [user_id, kind, name],
            )
        ).fetchone()
    if row is None:
        raise DefinitionError(f'no draft of the {kind} "{name}" to approve')
    return int(row[0])


# Templates (DEC-037): installing one creates its definitions, approved, unless the organization already has a definition of that name
# (its own wins), and writes its Cube files. Uninstalling retires what it made and removes its files; what people changed stays.

TEMPLATE_KINDS: tuple[tuple[str, Kind], ...] = (('subjects', 'subject'), ('entities', 'entity'), ('events', 'event'))


async def install_template(pool: AsyncConnectionPool, name: str, user_id: str | None = None) -> list[str]:
    """Creates the template's definitions and Cube files; returns the definitions it made (kind:name)."""
    template = packs.templates().get(name)
    if template is None:
        raise DefinitionError(f'no template named "{name}"')
    made: list[str] = []
    async with pool.connection() as conn, conn.transaction():
        for key, kind in TEMPLATE_KINDS:
            for item, body in (template.get(key) or {}).items():
                parsed = parse(kind, body)
                exists = await (
                    await conn.execute("select 1 from definition where kind = %s and name = %s and status <> 'retired'", [kind, item])
                ).fetchone()
                if exists:
                    continue
                row = await (
                    await conn.execute('select coalesce(max(version), 0) + 1 from definition where kind = %s and name = %s', [kind, item])
                ).fetchone()
                await conn.execute(
                    """insert into definition (kind, name, version, status, body, template, created_by, approved_by, approved_at)
                       values (%s, %s, %s, 'approved', %s, %s, %s, %s, now())""",
                    [kind, item, int(row[0]) if row else 1, Jsonb(parsed.model_dump(exclude_defaults=True)), name, user_id, user_id],
                )
                made.append(f'{kind}:{item}')
        for path in template.get('cube_files') or []:
            content = (packs.ROOT / 'templates' / name / path).read_text(encoding='utf-8')
            file_name = f'{name}/{path.rsplit("/", 1)[-1]}'
            await conn.execute(
                """insert into cube_model.file (name, content, source) values (%s, %s, %s)
                   on conflict (name) do update set content = excluded.content, source = excluded.source, updated_at = now()""",
                [file_name, content, f'template:{name}'],
            )
        await conn.execute(
            """update organization
               set installed_templates = (select array(select distinct unnest(installed_templates || %s::text[]) order by 1))""",
            [[name]],
        )
    return made


async def uninstall_template(pool: AsyncConnectionPool, name: str) -> None:
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("update definition set status = 'retired' where template = %s and status = 'approved'", [name])
        await conn.execute('delete from cube_model.file where source = %s', [f'template:{name}'])
        await conn.execute('update organization set installed_templates = array_remove(installed_templates, %s)', [name])
