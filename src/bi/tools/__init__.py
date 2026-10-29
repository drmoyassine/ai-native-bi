"""The governed tools, defined once (docs/mcp-spec.md section 6): the chat agent (src/bi/agent/tools.py) and the MCP server
(src/bi/mcp/server.py) both call these. Each docstring is what a model reads to decide *when* to call the tool, so the front doors
reuse it. Every return is checked against DEC-017: aggregates with small counts hidden, profiles, never rows about a person."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from .. import knowledge
from ..agent import catalog
from ..agent.suppress import count_measures, suppress_rows
from ..charts import ChartDefinition, ChartQuery, cube_query, query_to_cube, unknown_members, unknown_query_members
from ..cube import CubeClient, CubeError, CubeNoData

MAX_ROWS_TO_MODEL = 200


async def _no_emit(type: str, payload: dict[str, Any]) -> None:
    pass


@dataclass
class ToolContext:
    """What a tool may use for one call: the person it acts for, the warehouse and Cube, and (in the chat) the way to tell the page."""

    pool: AsyncConnectionPool
    cube: CubeClient | None
    user_id: str
    suppression_threshold: int
    emit: Callable[[str, dict[str, Any]], Awaitable[None]] = field(default=_no_emit)
    conversation_id: str | None = None


class ToolError(Exception):
    """A refusal the caller can read (not governed, not found, Cube unavailable)."""


def _cube(ctx: ToolContext) -> CubeClient:
    if ctx.cube is None:
        raise CubeError('Cube is not configured, so governed metrics are not available')
    return ctx.cube


async def list_metrics(ctx: ToolContext) -> dict[str, Any]:
    """List the governed measures and dimensions the organization defines (name, title, type, description).
    Call this first for any question about numbers, and before querying or charting, to learn what exists and what each is called."""
    try:
        members = await _cube(ctx).meta()
    except CubeError as e:
        return {'error': str(e)}
    return {'members': [knowledge.brief(m) for m in members]}


async def search_knowledge(ctx: ToolContext, query: str) -> dict[str, Any]:
    """Find governed metrics and glossary terms by the organization's own words, in any of its languages: names, synonyms, descriptions
    and explanations of what a metric counts. Call this when a question uses a word you do not see
    in list_metrics, or to explain a metric."""
    cube = _cube(ctx)
    try:
        return knowledge.search(await cube.meta(), await cube.words(), query)
    except CubeError as e:
        return {'error': str(e)}


async def query_metric(ctx: ToolContext, query: ChartQuery) -> dict[str, Any]:
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
    cube_q = query_to_cube(query.model_copy(update={'measures': [*query.measures, as_of_member]}) if wants_as_of else query)
    try:
        raw = await cube.load(cube_q)
    except CubeNoData:
        raw = []  # nothing loaded yet: answered below as no data, never as made-up numbers
    except CubeError as e:
        return {'error': str(e)}
    as_of: str | None = None
    if wants_as_of:
        dates = sorted(str(r[as_of_member]) for r in raw if r.get(as_of_member) not in (None, ''))
        if dates and len(dates[0]) == 8:
            as_of = f'{dates[0][:4]}-{dates[0][4:6]}-{dates[0][6:]}'
        for r in raw:
            r.pop(as_of_member, None)
    rows, hidden = suppress_rows(raw, query.measures, count_measures(members), ctx.suppression_threshold)
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
    await ctx.emit('result.table', {k: result[k] for k in ('rows', 'row_count', 'suppressed_cells', 'as_of', 'query')})
    return result


async def save_chart(ctx: ToolContext, chart: ChartDefinition) -> dict[str, Any]:
    """Save a chart for the person to see, as a private draft (a chart is a query over governed measures plus how to draw it).
    Call this when a picture would answer better than a table, or when asked for a chart. It does not publish anything."""
    members = await _cube(ctx).meta()
    unknown = unknown_query_members(chart.query, members)
    if unknown:
        return {'error': f'not governed measures/dimensions: {", ".join(unknown)}. Call list_metrics for the real names.'}
    definition = chart.model_dump(mode='json', by_alias=True, exclude_defaults=True)
    async with ctx.pool.connection() as conn:
        row = await (
            await conn.execute(
                """insert into draft (kind, owner_id, built_by, conversation_id, definition) values ('chart', %s, 'agent', %s, %s)
                   returning id::text""",
                [ctx.user_id, ctx.conversation_id, Jsonb(definition)],
            )
        ).fetchone()
    assert row is not None
    await ctx.emit('result.chart', {'draft_id': row[0], 'chart': definition})
    return {'draft_id': row[0], 'chart': definition}


async def chart_rows(cube: CubeClient, chart: ChartDefinition) -> list[dict[str, Any]]:
    """The rows of a chart definition, from Cube; time members come back under their own name (not name.granularity).
    Raises ToolError for members that are not governed and CubeError when Cube fails."""
    unknown = unknown_members(chart, await cube.meta())
    if unknown:
        raise ToolError(f'not governed members: {", ".join(unknown)}')
    try:
        rows = await cube.load(cube_query(chart))
    except CubeNoData:
        return []  # nothing loaded yet for this dataset: no data, not a failure
    time = chart.query.time
    if time and time.granularity:  # Cube names the bucket `<dimension>.<granularity>`: the chart knows it as the dimension
        key = f'{time.dimension}.{time.granularity}'
        for r in rows:
            if key in r:
                r[time.dimension] = r.pop(key)
    return rows


async def get_chart(ctx: ToolContext, chart_id: str) -> dict[str, Any]:
    """Get one chart: one of the person's own drafts, or a published chart, with its definition and its rows (small counts hidden).
    Call this to show or explain a chart the person saved or was given the id of."""
    async with ctx.pool.connection() as conn:
        row = await (
            await conn.execute(
                "select definition from draft where id::text = %s and (owner_id = %s or state = 'published')", [chart_id, ctx.user_id]
            )
        ).fetchone()
    if row is None:
        raise ToolError('no such chart')
    chart = ChartDefinition.model_validate(row[0])
    cube = _cube(ctx)
    rows = await chart_rows(cube, chart)
    shown, hidden = suppress_rows(rows, chart.query.measures, count_measures(await cube.meta()), ctx.suppression_threshold)
    return {'chart_id': chart_id, 'chart': row[0], 'rows': shown[:MAX_ROWS_TO_MODEL], 'row_count': len(shown), 'suppressed_cells': hidden}


async def list_datasets(ctx: ToolContext) -> dict[str, Any]:
    """List the datasets loaded into the warehouse: their tables, row counts and when they were last loaded (and as of when).
    Call this to learn what data exists, for example when asked what is available or when a metric is missing."""
    return {'datasets': await catalog.list_datasets(ctx.pool)}


async def describe_dataset(ctx: ToolContext, dataset: str) -> dict[str, Any]:
    """Describe one dataset: its columns and types, how many are empty, how many distinct values, numeric and date ranges, the common
    categories with their counts, and the shape of values as patterns (9 is a digit, A a capital letter, a a lower-case letter).
    Identifier columns show only a count and a shape. Call this to understand a dataset before explaining it. It never returns rows."""
    try:
        return await catalog.describe_dataset(ctx.pool, dataset, ctx.suppression_threshold)
    except catalog.CatalogError as e:
        return {'error': str(e)}
