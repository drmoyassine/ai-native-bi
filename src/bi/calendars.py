"""The organization's calendars (docs/data-model-spec.md section 4; TASK-043): its own periods, whatever they are called (terms, fiscal
years, seasons, shifts). Nothing here names one: a calendar is configuration an admin makes in Settings. A calendar either lists its
periods with their dates (no two overlap; a date in none has no period) or repeats every year from a start day (a fiscal year, or its
quarters). An event's derived part `period` says which period of a calendar a date falls in (bi.generate); calendar years and months
need no calendar (the derived part `date_part`)."""

from __future__ import annotations

import datetime as dt
import itertools
import re
from typing import Annotated, Any, Literal

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field, StringConstraints, model_validator

from .definitions import Words, reasons

Code = Annotated[str, StringConstraints(min_length=1, max_length=60)]


class CalendarError(ValueError):
    """A calendar that cannot be saved or removed, with the reason."""


class _Body(BaseModel):
    model_config = {'extra': 'forbid'}


class Period(_Body):
    code: Code
    """What the period is called in the data and on charts (a value, the same in every language)."""
    label: Words = Field(default_factory=dict)
    starts: dt.date
    ends: dt.date
    """The last day of the period (inclusive)."""

    @model_validator(mode='after')
    def _order(self) -> Period:
        if self.ends < self.starts:
            raise ValueError(f'the period "{self.code}" ends before it starts')
        return self


class Repeat(_Body):
    """A period every year (or every quarter of it) from a start day: `starts` '07-01' is a year from 1 July."""

    every: Literal['year', 'quarter']
    starts: Annotated[str, StringConstraints(pattern=r'^(0[1-9]|1[0-2])-(0[1-9]|1[0-9]|2[0-8])$')]
    """MM-DD; the day is at most 28, so every year has it."""
    named_by: Literal['start', 'end'] = 'start'
    """A year from July 2025 to June 2026 is called 2025 (its start) or 2026 (its end)."""

    @property
    def month(self) -> int:
        return int(self.starts[:2])

    @property
    def day(self) -> int:
        return int(self.starts[3:])

    def code_for(self, date: dt.date) -> str:
        """The period a date falls in (the generated SQL does the same, tested against this)."""
        year = date.year if (date.month, date.day) >= (self.month, self.day) else date.year - 1
        if self.named_by == 'end' and (self.month, self.day) != (1, 1):
            name = year + 1
        else:
            name = year
        if self.every == 'year':
            return str(name)
        start = dt.date(year, self.month, self.day)
        months = (date.year - start.year) * 12 + date.month - start.month - (1 if date.day < self.day else 0)
        return f'{name}-Q{months // 3 + 1}'


class CalendarBody(_Body):
    label: Words
    description: Words = Field(default_factory=dict)
    repeat: Repeat | None = None
    periods: Annotated[list[Period], Field(max_length=2000)] = Field(default_factory=list)

    @model_validator(mode='after')
    def _periods(self) -> CalendarBody:
        if self.repeat is not None and self.periods:
            raise ValueError('a calendar either repeats or lists its periods, not both')
        codes = [p.code for p in self.periods]
        if len(codes) != len(set(codes)):
            raise ValueError('two periods have the same code')
        ordered = sorted(self.periods, key=lambda p: p.starts)
        for before, after in itertools.pairwise(ordered):
            if after.starts <= before.ends:
                raise ValueError(f'the periods "{before.code}" and "{after.code}" overlap')
        return self

    def code_for(self, date: dt.date) -> str | None:
        if self.repeat is not None:
            return self.repeat.code_for(date)
        return next((p.code for p in self.periods if p.starts <= date <= p.ends), None)


def parse(body: dict[str, Any]) -> CalendarBody:
    try:
        return CalendarBody.model_validate(body)
    except ValueError as e:
        raise CalendarError(f'the calendar is not valid: {reasons(e)}') from e


async def all_calendars(pool: AsyncConnectionPool) -> dict[str, CalendarBody]:
    async with pool.connection() as conn:
        rows = await (await conn.execute('select name, body from calendar order by name')).fetchall()
    return {name: CalendarBody.model_validate(body) for name, body in rows}


async def used_by(pool: AsyncConnectionPool, name: str) -> list[str]:
    """The events (current or draft) with a derived part that reads this calendar."""
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """select distinct d.name from definition d, jsonb_array_elements(coalesce(d.body->'derived', '[]')) part
                   where d.kind = 'event' and d.status in ('draft', 'approved') and part->'rule'->>'type' = 'period'
                     and part->'rule'->>'calendar' = %s order by d.name""",
                [name],
            )
        ).fetchall()
    return [r[0] for r in rows]


async def listing(pool: AsyncConnectionPool) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        rows = await (await conn.execute('select name, body, updated_at from calendar order by name')).fetchall()
    return [
        {'name': name, 'body': body, 'updated_at': updated.isoformat(), 'used_by': await used_by(pool, name)}
        for name, body, updated in rows
    ]


async def save(pool: AsyncConnectionPool, name: str, body: dict[str, Any], user_id: str | None) -> CalendarBody:
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', name):
        raise CalendarError('a calendar name is lower-case letters, digits and _, starting with a letter')
    parsed = parse(body)
    async with pool.connection() as conn:
        await conn.execute(
            """insert into calendar (name, body, updated_by) values (%s, %s, %s)
               on conflict (name) do update set body = excluded.body, updated_by = excluded.updated_by, updated_at = now()""",
            [name, Jsonb(parsed.model_dump(mode='json', exclude_defaults=True)), user_id],
        )
    return parsed


async def remove(pool: AsyncConnectionPool, name: str) -> None:
    users = await used_by(pool, name)
    if users:
        raise CalendarError(f'the calendar is used by {", ".join(users)}: change those first')
    async with pool.connection() as conn:
        deleted = await (await conn.execute('delete from calendar where name = %s returning name', [name])).fetchone()
    if deleted is None:
        raise CalendarError(f'no calendar named "{name}"')
