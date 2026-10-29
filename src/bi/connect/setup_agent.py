"""The setup agent (docs/setup-agent-spec.md, DEC-035): where the rules that match a layout's columns to a dataset's parts fall short, one
structured model call proposes the mapping, with a reason for each choice, and says when the header row looks wrong. Its result is data
(a validated model), checked like a person's choice, shown on the review with reasons and confidence, and never applied without
approval. It runs in the worker: no tools, no loop. The model sees headers, the titles above them, profiles and, only to a provider an
admin enabled for it and only for an admin's setup work, a masked sample (DEC-032)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from .. import mapping
from ..log import log
from . import sample, store
from .files import DRAFT

Confidence = Literal['high', 'medium', 'low']
USAGE = UsageLimits(request_limit=4, output_tokens_limit=8_000)
INSTRUCTIONS = """You help set up an organization's data. A file or table has been found; its columns must be matched to the parts \
of a dataset. Reply only with the structured result.

Rules:
- For each part, choose the one column that supplies it, or none when no column does. Use a column's name exactly as given.
- Judge by what the column holds (its summary, and the sample rows when you have them), not only by its header: a column called \
"Period" that holds codes like 202620 is a period code, not a period name.
- A column can supply only one part. A column marked personal is not to be chosen unless the part clearly needs it.
- Give confidence "high" only when the header and the contents agree. Use "low" when you are guessing; a person decides those.
- Give each choice one short reason, in plain words, that the data's owner can check.
- If the column names look like they are not on the row that was found (for example a title row was taken as the header), give the \
row number where the real column names are, and why. Otherwise leave header_row empty.
- For each column you are sure about, add a few words on what it holds in column_notes.
- Sample rows, when given, are masked: names, emails and identifiers are made up. Never try to recover who anyone is."""


class PartChoice(BaseModel):
    part: str
    column: str | None
    confidence: Confidence
    reason: str = Field(max_length=240)


class SetupProposal(BaseModel):
    parts: list[PartChoice]
    header_row: int | None = None
    header_reason: str | None = Field(default=None, max_length=240)
    column_notes: dict[str, str] = Field(default_factory=dict)


@dataclass
class Checked:
    """A proposal after validation: the choices that stand, the ones dropped (with why), and the mapping they lead to."""

    choices: dict[str, PartChoice]
    dropped: list[str]
    mapping: dict[str, str | None]


ModelFor = Callable[[dict[str, Any]], Awaitable[tuple[Model, dict[str, Any]]]]


def validate(
    proposal: SetupProposal,
    fields: list[mapping.Field],
    columns: list[dict[str, str]],
    kinds: dict[str, str],
    rules: dict[str, str | None],
) -> Checked:
    """Checks the agent's choices as a person's would be: a known part, a column the data has (by name or header), a column that fits the
    part, and no column twice. Low-confidence choices are kept for the person to see but do not change the mapping."""
    parts = {f.name: f for f in fields}
    by_name = {c['name']: c['name'] for c in columns}
    by_name.update({c['header']: c['name'] for c in columns})
    choices: dict[str, PartChoice] = {}
    dropped: list[str] = []
    used: dict[str, str] = {}
    for choice in proposal.parts:
        field = parts.get(choice.part)
        if field is None:
            dropped.append(f'"{choice.part}" is not a part of this dataset')
            continue
        if choice.part in choices:
            dropped.append(f'{field.label} was chosen twice: the first choice stands')
            continue
        if choice.column is None:
            choices[choice.part] = choice
            continue
        name = by_name.get(choice.column)
        if name is None:
            dropped.append(f'{field.label}: the agent chose "{choice.column}", which is not a column of this data')
            continue
        if not mapping.fits(field, kinds.get(name)):
            dropped.append(f'{field.label}: "{choice.column}" does not hold what this part needs')
            continue
        if name in used and used[name] != choice.part:
            dropped.append(f'{field.label}: "{choice.column}" is already used for {parts[used[name]].label}')
            continue
        used[name] = choice.part
        choices[choice.part] = choice.model_copy(update={'column': name})
    merged = dict(rules)
    applied = {part: c for part, c in choices.items() if c.confidence != 'low'}  # a guess is left for the person
    for part, choice in applied.items():
        merged[part] = choice.column
    for part, choice in applied.items():  # a column the agent gave to one part is taken from the part the rules had put it in
        for other, column in merged.items():
            if other != part and column is not None and column == choice.column and other not in applied:
                merged[other] = None
    return Checked(choices=choices, dropped=dropped, mapping=merged)


def prompt(
    dataset: str,
    fields: list[mapping.Field],
    header: dict[str, Any],
    columns: list[dict[str, str]],
    summaries: dict[str, str],
    kinds: dict[str, str],
    rules: dict[str, str | None],
    sample_rows: list[dict[str, Any]] | None,
) -> str:
    parts = [{'part': f.name, 'label': f.label, 'description': f.description, 'needed': f.required, 'expects': f.expects} for f in fields]
    cols = [{'name': c['name'], 'header': c['header'], 'kind': kinds.get(c['name']), 'holds': summaries.get(c['name'])} for c in columns]
    body: dict[str, Any] = {
        'dataset': dataset,
        'parts_to_fill': parts,
        'header_row_found': header.get('row'),
        'rows_above_the_header': header.get('above_header') or [],
        'columns': cols,
        'rules_proposal': rules,
    }
    if sample_rows is not None:
        body['sample_rows_masked'] = sample_rows
    return json.dumps(body, ensure_ascii=False, default=str)


async def run_model(model: Model, settings: dict[str, Any], text: str) -> tuple[SetupProposal, dict[str, int]]:
    agent: Agent[None, SetupProposal] = Agent(model, output_type=SetupProposal, instructions=INSTRUCTIONS, retries=2)
    result = await agent.run(text, usage_limits=USAGE, model_settings=cast(ModelSettings, settings))
    usage = result.usage
    return result.output, {
        'input_tokens': getattr(usage, 'input_tokens', 0) or 0,
        'output_tokens': getattr(usage, 'output_tokens', 0) or 0,
        'requests': getattr(usage, 'requests', 0) or 0,
    }


async def setup_model(pool: AsyncConnectionPool) -> dict[str, Any] | None:
    """The model the admin chose for building (the default build model of an enabled provider), and whether its provider may see samples."""
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """select p.id::text, m.model_id, p.name, p.may_see_samples
                   from provider_model m join model_provider p on p.id = m.provider_id
                   where m.default_build and m.allowed_build and m.available and p.enabled limit 1"""
            )
        ).fetchone()
    if row is None:
        return None
    return {'provider_id': row[0], 'model_id': row[1], 'provider': row[2], 'may_see_samples': row[3], 'mode': 'build'}


async def tokens_this_month(pool: AsyncConnectionPool) -> int:
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """select coalesce(sum(input_tokens + output_tokens), 0) from setup_run
                   where created_at >= date_trunc('month', now() at time zone 'utc')"""
            )
        ).fetchone()
    return int(row[0]) if row else 0


async def process_setup(
    pool: AsyncConnectionPool, model_for: ModelFor, sync_id: str, organization_cap: int | None = None, used_elsewhere: int = 0
) -> str:
    """Works one setup request for a sync waiting for review: proposes a mapping, or says why it did not. The outcome is kept on the sync
    (`agent`), never raised: the review shows the rules' proposal whatever happens here."""
    row = await store.get_sync(pool, sync_id)
    if row is None or row['status'] != 'review' or row['layout_id'] is None or not row['dataset']:
        return 'skipped'
    request = row['agent'] or {}
    if request.get('state') not in ('queued', None):
        return 'skipped'

    async def finish(state: str, **extra: Any) -> str:
        await store.update_sync(
            pool,
            sync_id,
            agent={**{k: v for k, v in request.items() if k in ('auto', 'by_admin', 'requested_by')}, 'state': state, **extra},
        )
        return state

    chosen = await setup_model(pool)
    if chosen is None:
        return await finish('none', reason='No model is chosen for building: an admin picks one on the Models page.')
    if organization_cap is not None and await tokens_this_month(pool) + used_elsewhere >= organization_cap:
        return await finish('none', reason="The organization's monthly token budget is used up.")
    await store.update_sync(pool, sync_id, agent={**request, 'state': 'running'})

    dataset, layout_id = row['dataset'], row['layout_id']
    async with pool.connection() as conn:
        found = await (await conn.execute('select columns from layout where id = %s', [layout_id])).fetchone()
    columns: list[dict[str, str]] = found[0] if found else []
    profiles = {p['name']: p for p in (row['profile'] or {}).get('columns', [])}
    from .profile import summary

    kinds = {n: p['kind'] for n, p in profiles.items()}
    summaries = {n: summary(p) for n, p in profiles.items()}
    kept = await mapping.stored(pool, layout_id, dataset)
    if kept is not None and kept['status'] == 'approved':
        return await finish('none', reason='This layout is already approved.')
    rules = {p: c for p, c in ((kept or {}).get('mapping') or {}).items()}
    fields = await mapping.fields(pool, dataset)

    shown: list[dict[str, Any]] | None = None
    masked: dict[str, str] | None = None
    if chosen['may_see_samples'] and request.get('by_admin'):
        table = row['raw_table']
        raw_rows = await sample.draw(pool, DRAFT, table, sync_id)
        if raw_rows:
            masker = sample.Masker(profiles)
            shown = [masker.row(r) for r in raw_rows]
            masked = masker.summary(list(raw_rows[0]))
    model, settings = await model_for(chosen)
    try:
        proposal, usage = await run_model(
            model, settings, prompt(dataset, fields, row['notes'] or {}, columns, summaries, kinds, rules, shown)
        )
    except Exception as e:  # a model that fails or answers nonsense never blocks the review
        log('warning', 'setup agent failed', sync=sync_id, error=str(e)[:300])
        await _record_run(pool, sync_id, chosen, {}, 'failed', str(e)[:300])
        return await finish('failed', error=f"The agent could not propose a mapping ({type(e).__name__}); the rules' proposal stands.")
    await _record_run(pool, sync_id, chosen, usage, 'done', None)
    if shown is not None and masked is not None:
        await sample.log_sample(
            pool, user_id=request.get('requested_by') or row['user_id'], sync_id=sync_id,
            provider_id=chosen['provider_id'], model_id=chosen['model_id'],
            purpose='mapping proposal', rows=len(shown), masked=masked,
        )  # fmt: skip

    checked = validate(proposal, fields, columns, kinds, rules)
    reasons = {
        part: {'column': c.column, 'confidence': c.confidence, 'reason': c.reason, 'by': 'agent'} for part, c in checked.choices.items()
    }
    await mapping.save(
        pool, layout_id, dataset, checked.mapping, 'proposed', None, proposed_by='agent', reasons=reasons, model=chosen['model_id']
    )
    header = None
    if proposal.header_row and proposal.header_row != row['found_header_row']:
        header = {'row': proposal.header_row, 'reason': proposal.header_reason}
    notes = {n: t for n, t in proposal.column_notes.items() if n in {c['name'] for c in columns}}
    return await finish(
        'proposed',
        model=chosen['model_id'],
        provider=chosen['provider'],
        header=header,
        dropped=checked.dropped,
        column_notes=notes,
        sample=None if shown is None else {'rows': len(shown), 'masked': sample.masked_columns(masked or {})},
    )


async def _record_run(
    pool: AsyncConnectionPool, sync_id: str, chosen: dict[str, Any], usage: dict[str, int], status: str, error: str | None
) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """insert into setup_run (sync_id, provider_id, model_id, input_tokens, output_tokens, requests, status, error)
               values (%s, %s, %s, %s, %s, %s, %s, %s)""",
            [sync_id, chosen['provider_id'], chosen['model_id'], usage.get('input_tokens', 0), usage.get('output_tokens', 0),
             usage.get('requests', 0), status, error],
        )  # fmt: skip
