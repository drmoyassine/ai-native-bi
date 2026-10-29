"""The warehouse models, generated from the approved events (docs/data-model-spec.md section 7, M0b; DEC-036): never written by hand,
never naming a domain (DEC-037). Generation is a pure function of the definitions, so the same definitions always give the same SQL.

For each event: `staging/stg_<event>.sql` reads every approved input (macro `dataset_rows`), casts each part to its kind and, for a
state, keeps each period's latest load (`snapshot_by`); `analytics/<event>.sql` is what Cube reads; `generated.yml` holds the tests the
definition implies (needed parts present, the grain unique, an as-of on every row)."""

from __future__ import annotations

from typing import Any

import yaml

from .definitions import EventBody, Part


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


def staging_sql(name: str, event: EventBody) -> str:
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
    columns = [f'    {_cast(p, "raw." + _q(p.name))} as {_q(p.name)}' for p in event.parts]
    columns += [
        '    cast(raw._bi_as_of as date) as as_of',
        '    raw._bi_file_sha256 as source_file_sha256',
        '    raw._bi_loaded_at as loaded_at',
    ]
    lines += ['', 'select', ',\n'.join(columns), 'from raw']
    if event.snapshot_by:
        on = ' and '.join(f'raw.{_q(k)} = latest.{_q(k)}' for k in event.snapshot_by)
        lines += ['inner join latest', f'    on {on} and raw._bi_loaded_at = latest.loaded_at']
    return '\n'.join(lines) + '\n'


def analytics_sql(name: str, event: EventBody) -> str:
    columns = [_q(p.name) for p in event.parts] + ['as_of', 'source_file_sha256', 'loaded_at']
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


def dbt_files(events: dict[str, EventBody]) -> dict[str, str]:
    """The generated models, by path inside the dbt project."""
    files: dict[str, str] = {}
    for name, event in sorted(events.items()):
        files[f'models/staging/stg_{name}.sql'] = staging_sql(name, event)
        files[f'models/analytics/{name}.sql'] = analytics_sql(name, event)
    if events:
        files['models/generated.yml'] = tests_yml(events)
    return files
