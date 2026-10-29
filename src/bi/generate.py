"""The warehouse models, generated from the approved events (docs/data-model-spec.md section 7, M0b; DEC-036): never written by hand,
never naming a domain (DEC-037). Generation is a pure function of the definitions, so the same definitions always give the same SQL.

For each event: `staging/stg_<event>.sql` reads every approved input (macro `dataset_rows`), casts each part to its kind and, for a
state, keeps each period's latest load (`snapshot_by`); `analytics/<event>.sql` is what Cube reads; `generated.yml` holds the tests the
definition implies (needed parts present, the grain unique, an as-of on every row)."""

from __future__ import annotations

from typing import Any

import yaml

from .calendars import CalendarBody
from .definitions import ArithmeticRule, BucketRule, DatePartRule, Derived, EventBody, GroupRule, JoinRule, Part, PeriodRule

Calendars = dict[str, CalendarBody]


def _q(name: str) -> str:
    return f'"{name}"'


def _cast(part: Part, column: str) -> str:
    if part.expects == 'date':
        value = f'cast({column} as date)'
    elif part.expects == 'number':
        value = f'cast({column} as numeric)'
    else:
        value = column
    if part.normalize == 'lower':
        value = f'lower({value})'
    return value


def _lit(value: str) -> str:
    """A text literal for the generated SQL (values come from definitions a person approved; quotes are doubled, Jinja is closed)."""
    safe = value.replace("'", "''").replace('{{', '{ {').replace('{%', '{ %').replace('{#', '{ #')
    return f"'{safe}'"


def _num(value: float) -> str:
    return repr(float(value))


def _operand(value: str | float) -> str:
    return f'typed.{_q(value)}' if isinstance(value, str) else _num(value)


def period_sql(value: str, calendar: CalendarBody | None) -> str:
    """The code of the calendar's period a date falls in (bi.calendars; the same as CalendarBody.code_for)."""
    if calendar is None:
        return 'null::text'
    repeat = calendar.repeat
    if repeat is None:
        if not calendar.periods:
            return 'null::text'
        ordered = sorted(calendar.periods, key=lambda p: p.starts)
        whens = ' '.join(
            f"when {value} between date '{p.starts.isoformat()}' and date '{p.ends.isoformat()}' then {_lit(p.code)}" for p in ordered
        )
        return f'case {whens} else null end'
    # Shifting the date back to the start day makes the year (and its quarters) begin on 1 January (the day is at most 28).
    shifted = f"({value} - interval '{repeat.month - 1} months' - interval '{repeat.day - 1} days')"
    later = 1 if repeat.named_by == 'end' and (repeat.month, repeat.day) != (1, 1) else 0
    year = f'(cast(extract(year from {shifted}) as integer) + {later})::text'
    if repeat.every == 'year':
        return year
    return f"{year} || '-Q' || cast(extract(quarter from {shifted}) as integer)::text"


def derived_sql(d: Derived, calendars: Calendars | None = None) -> str:
    """The SQL of one derived part, over the typed parts (`typed`). Pure: the same rule (and calendars) give the same SQL."""
    r = d.rule
    if isinstance(r, GroupRule):
        whens = ' '.join(f'when {_lit(k)} then {_lit(v)}' for k, v in r.groups.items())
        otherwise = _lit(r.otherwise) if r.otherwise is not None else 'null'
        return f'case typed.{_q(r.part)}::text {whens} else {otherwise} end'
    if isinstance(r, JoinRule):
        return 'concat_ws(' + _lit(r.separator) + ', ' + ', '.join(f'typed.{_q(p)}::text' for p in r.parts) + ')'
    if isinstance(r, DatePartRule):
        unit = {'year': 'year', 'quarter': 'quarter', 'month': 'month', 'week': 'week', 'day_of_week': 'isodow'}[r.unit]
        return f'cast(extract({unit} from typed.{_q(r.part)}) as integer)'
    if isinstance(r, PeriodRule):
        return period_sql(f'typed.{_q(r.part)}', (calendars or {}).get(r.calendar))
    if isinstance(r, ArithmeticRule):
        right = _operand(r.right)
        if r.op == '/':
            right = f'nullif({right}, 0)'  # a division by zero is no value, not an error
        return f'({_operand(r.left)} {r.op} {right})'
    if isinstance(r, BucketRule):
        value = f'typed.{_q(r.part)}'
        whens = ' '.join(f'when {value} < {_num(edge)} then {_lit(label)}' for edge, label in zip(r.edges, r.labels, strict=False))
        return f'case when {value} is null then null {whens} else {_lit(r.labels[-1])} end'
    return 'coalesce(' + ', '.join(f'nullif(trim(typed.{_q(p)}::text), {_lit("")})' for p in r.parts) + ')'


def staging_sql(name: str, event: EventBody, calendars: Calendars | None = None) -> str:
    names = ', '.join(repr(p.name) for p in event.parts)
    lines = [
        f'-- Generated from the approved event "{name}" (bi.generate): every approved input, typed. Do not edit.',
        'with raw as (',
        f"    {{{{ dataset_rows('{name}', [{names}]) }}}}",
        ')',
    ]
    if event.snapshot_by:
        keys = ', '.join(_q(k) for k in event.snapshot_by)
        lines += [
            '',
            ', latest as (',
            f'    select {keys}, max(_bi_loaded_at) as loaded_at',
            '    from raw',
            f'    group by {keys}',
            ')',
        ]
    columns = [f'        {_cast(p, "raw." + _q(p.name))} as {_q(p.name)}' for p in event.parts]
    columns += [
        '        cast(raw._bi_as_of as date) as as_of',
        '        raw._bi_file_sha256 as source_file_sha256',
        '        raw._bi_loaded_at as loaded_at',
    ]
    lines += ['', ', typed as (', '    select', ',\n'.join(columns), '    from raw']
    if event.snapshot_by:
        on = ' and '.join(f'raw.{_q(k)} = latest.{_q(k)}' for k in event.snapshot_by)
        lines += ['    inner join latest', f'        on {on} and raw._bi_loaded_at = latest.loaded_at']
    derived = ''.join(f',\n    {derived_sql(d, calendars)} as {_q(d.name)}' for d in event.derived)
    lines += [')', '', 'select', '    typed.*' + derived, 'from typed']
    return '\n'.join(lines) + '\n'


def analytics_sql(name: str, event: EventBody) -> str:
    columns = [_q(p.name) for p in event.parts] + [_q(d.name) for d in event.derived] + ['as_of', 'source_file_sha256', 'loaded_at']
    return (
        f'-- Generated from the approved event "{name}" (bi.generate): what Cube reads (CLAUDE.md rule 5). Do not edit.\n'
        'select\n    ' + ',\n    '.join(columns) + f"\nfrom {{{{ ref('stg_{name}') }}}}\n"
    )


def tests_yml(events: dict[str, EventBody]) -> str:
    models: list[dict[str, Any]] = []
    for name, event in sorted(events.items()):
        needed = [{'name': p.name, 'data_tests': ['not_null']} for p in event.parts if p.needed]
        models.append({'name': f'stg_{name}', 'columns': needed})
        analytics: dict[str, Any] = {
            'name': name,
            'columns': [*({'name': g, 'data_tests': ['not_null']} for g in event.grain), {'name': 'as_of', 'data_tests': ['not_null']}],
        }
        if event.grain:
            key = " || '|' || ".join(_q(g) for g in event.grain)
            analytics['data_tests'] = [{'unique': {'column_name': key}}]
        models.append(analytics)
    return '# Generated from the approved events (bi.generate). Do not edit.\n' + yaml.safe_dump(
        {'version': 2, 'models': models}, sort_keys=False, allow_unicode=True
    )


def dbt_files(events: dict[str, EventBody], calendars: Calendars | None = None) -> dict[str, str]:
    """The generated models, by path inside the dbt project (a calendar's periods are written into the events that read it)."""
    files: dict[str, str] = {}
    for name, event in sorted(events.items()):
        files[f'models/staging/stg_{name}.sql'] = staging_sql(name, event, calendars)
        files[f'models/analytics/{name}.sql'] = analytics_sql(name, event)
    if events:
        files['models/generated.yml'] = tests_yml(events)
    return files
