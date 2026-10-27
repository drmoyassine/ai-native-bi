"""The chat agent's tools (docs/agent-spec.md section 5): the shared governed tools of src/bi/tools, wrapped for Pydantic AI. The
wrappers only turn a run's dependencies into a ToolContext; the logic, the privacy rules and the docstrings the model reads live in
src/bi/tools, where the MCP server finds them too (docs/mcp-spec.md)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from psycopg_pool import AsyncConnectionPool
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from .. import tools
from ..charts import ChartDefinition, ChartQuery
from ..cube import CubeClient

MAX_ROWS_TO_MODEL = tools.MAX_ROWS_TO_MODEL


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


def context(deps: AgentDeps) -> tools.ToolContext:
    return tools.ToolContext(
        pool=deps.pool,
        cube=deps.cube,
        user_id=deps.user_id,
        suppression_threshold=deps.suppression_threshold,
        emit=deps.emit,
        conversation_id=deps.conversation_id,
    )


ask_tools: FunctionToolset[AgentDeps] = FunctionToolset()


async def list_metrics(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    return await tools.list_metrics(context(ctx.deps))


async def query_metric(ctx: RunContext[AgentDeps], query: ChartQuery) -> dict[str, Any]:
    return await tools.query_metric(context(ctx.deps), query)


async def propose_chart(ctx: RunContext[AgentDeps], chart: ChartDefinition) -> dict[str, Any]:
    result = await tools.save_chart(context(ctx.deps), chart)
    return {**result, 'note': 'saved as a private draft of the person; it is shown in the chat'} if 'draft_id' in result else result


async def list_datasets(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    return await tools.list_datasets(context(ctx.deps))


async def describe_dataset(ctx: RunContext[AgentDeps], dataset: str) -> dict[str, Any]:
    return await tools.describe_dataset(context(ctx.deps), dataset)


# The model reads the shared docstrings; set them before registering, which is when Pydantic AI reads them.
for wrapper, shared in (
    (list_metrics, tools.list_metrics),
    (query_metric, tools.query_metric),
    (propose_chart, tools.save_chart),
    (list_datasets, tools.list_datasets),
    (describe_dataset, tools.describe_dataset),
):
    wrapper.__doc__ = shared.__doc__
    ask_tools.tool(wrapper)
