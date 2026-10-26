"""The agent's tools (docs/agent-spec.md section 5), step 2a: read governed KPIs, look at the catalog, draft charts. Each is a typed async
function in a Pydantic AI toolset (Pydantic validates every input) whose docstring tells the model *when* to call it. What a tool
returns is what the model sees, so every return is checked against DEC-017: aggregates with small counts hidden, profiles, never rows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from ..charts import ChartDefinition, ChartQuery, query_to_cube, unknown_query_members
from ..cube import CubeClient, CubeError
from . import catalog
from .suppress import count_measures, suppress_rows

MAX_ROWS_TO_MODEL = 200


@dataclass
class AgentDeps:
    """What a tool may use during one turn: the person it acts for, the warehouse and Cube, and the way to tell the chat."""

    pool: AsyncConnectionPool
    cube: CubeClient | None
    user_id: str
    conversation_id: str
    run_id: str
    suppression_threshold: int
    emit: Callable[[str, dict[str, Any]], Awaitable[None]]


ask_tools: FunctionToolset[AgentDeps] = FunctionToolset()


def _cube(ctx: RunContext[AgentDeps]) -> CubeClient:
    if ctx.deps.cube is None:
        raise CubeError('Cube is not configured, so governed metrics are not available')
    return ctx.deps.cube


@ask_tools.tool
async def list_metrics(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    """List the governed measures and dimensions the institution defines (name, title, type, description).
    Call this first for any question about numbers, and before querying or charting, to learn what exists and what each is called."""
    try:
        members = await _cube(ctx).meta()
    except CubeError as e:
        return {'error': str(e)}
    return {'members': [{k: m[k] for k in ('name', 'title', 'kind', 'description', 'cube') if m.get(k) is not None} for m in members]}


@ask_tools.tool
async def query_metric(ctx: RunContext[AgentDeps], query: ChartQuery) -> dict[str, Any]:
    """Run a structured query over governed measures and dimensions and get aggregated rows (never SQL, never rows about a person).
    Call this to answer any question about a number. Use only names returned by list_metrics. Counts under the privacy threshold come
    back as null and are listed under `suppressed`: say so rather than guess them, and do not try to recover them by querying
    overlapping groups. The answer includes the data's as-of date: always tell the person."""
    cube = _cube(ctx)
    try:
        members = await cube.meta()
    except CubeError as e:
        return {'error': str(e)}
    unknown = unknown_query_members(query, members)
    if unknown:
        return {'error': f'not governed measures/dimensions: {", ".join(unknown)}. Call list_metrics for the real names.'}
    # The data's as-of date comes from the same cube as the first measure, where it has one (the `as_of` measure).
    as_of_member = f'{query.measures[0].split(".")[0]}.as_of'
    wants_as_of = any(m['name'] == as_of_member and m['kind'] == 'measure' for m in members) and as_of_member not in query.measures
    cube_query = query_to_cube(query.model_copy(update={'measures': [*query.measures, as_of_member]}) if wants_as_of else query)
    try:
        raw = await cube.load(cube_query)
    except CubeError as e:
        return {'error': str(e)}
    as_of: str | None = None
    if wants_as_of:
        dates = sorted(str(r[as_of_member]) for r in raw if r.get(as_of_member) not in (None, ''))
        if dates and len(dates[0]) == 8:
            as_of = f'{dates[0][:4]}-{dates[0][4:6]}-{dates[0][6:]}'
        for r in raw:
            r.pop(as_of_member, None)
    rows, hidden = suppress_rows(raw, query.measures, count_measures(members), ctx.deps.suppression_threshold)
    shown, truncated = rows[:MAX_ROWS_TO_MODEL], len(rows) > MAX_ROWS_TO_MODEL
    result: dict[str, Any] = {
        'rows': shown,
        'row_count': len(rows),
        'suppressed_cells': hidden,
        'as_of': as_of,
        'source': 'cube',
        'query': query.model_dump(mode='json', by_alias=True, exclude_defaults=True),
    }
    if truncated:
        result['note'] = f'only the first {MAX_ROWS_TO_MODEL} of {len(rows)} rows are shown'
    if not rows:
        result['note'] = 'no data: nothing matches (or nothing has been loaded yet); do not make up numbers'
    await ctx.deps.emit('result.table', {k: result[k] for k in ('rows', 'row_count', 'suppressed_cells', 'as_of', 'query')})
    return result


@ask_tools.tool
async def propose_chart(ctx: RunContext[AgentDeps], chart: ChartDefinition) -> dict[str, Any]:
    """Save a chart for the person to see, as a private draft (a chart is a query over governed measures plus how to draw it).
    Call this when a picture would answer better than a table, or when asked for a chart. It does not publish anything."""
    members = await _cube(ctx).meta()
    unknown = unknown_query_members(chart.query, members)
    if unknown:
        return {'error': f'not governed measures/dimensions: {", ".join(unknown)}. Call list_metrics for the real names.'}
    definition = chart.model_dump(mode='json', by_alias=True, exclude_defaults=True)
    async with ctx.deps.pool.connection() as conn:
        row = await (
            await conn.execute(
                """insert into draft (kind, owner_id, built_by, conversation_id, definition) values ('chart', %s, 'agent', %s, %s)
                   returning id::text""",
                [ctx.deps.user_id, ctx.deps.conversation_id, Jsonb(definition)],
            )
        ).fetchone()
    assert row is not None
    await ctx.deps.emit('result.chart', {'draft_id': row[0], 'chart': definition})
    return {'draft_id': row[0], 'chart': definition, 'note': 'saved as a private draft of the person; it is shown in the chat'}


@ask_tools.tool
async def list_datasets(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    """List the datasets loaded into the warehouse: their tables, row counts and when they were last loaded (and as of when).
    Call this to learn what data exists, for example when asked what is available or when a metric is missing."""
    return {'datasets': await catalog.list_datasets(ctx.deps.pool)}


@ask_tools.tool
async def describe_dataset(ctx: RunContext[AgentDeps], dataset: str) -> dict[str, Any]:
    """Describe one dataset: its columns and types, how many are empty, how many distinct values, numeric and date ranges, the common
    categories with their counts, and the shape of values as patterns (9 is a digit, A a capital letter, a a lower-case letter).
    Identifier columns show only a count and a shape. Call this to understand a dataset before explaining it. It never returns rows."""
    try:
        return await catalog.describe_dataset(ctx.deps.pool, dataset, ctx.deps.suppression_threshold)
    except catalog.CatalogError as e:
        return {'error': str(e)}
