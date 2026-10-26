"""One turn of the agent (docs/agent-spec.md section 4): Pydantic AI driven node by node in a worker job.

The user's message is already stored (by the API). Each model response is stored *before* its tools run and each tool-result message
before the next model call, so the history is exactly what the provider saw (DEC-018). However a turn ends (done, interrupted, a limit,
an error) the history is left valid: a response whose tool calls never ran gets a closing message saying so."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic_ai import Agent
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from ..cube import CubeClient
from ..log import log
from . import providers, store
from .instructions import MODES
from .providers import usage_limits
from .secrets import SecretStore
from .tools import AgentDeps, ask_tools

FLUSH_CHARS = 120
FLUSH_SECONDS = 0.25
ModelFor = Callable[[dict[str, Any]], Awaitable[tuple[Model, dict[str, Any]]]]


@dataclass
class TurnDeps:
    pool: AsyncConnectionPool
    cube: CubeClient | None
    suppression_threshold: int
    model_for: ModelFor
    """(model, settings) for a conversation row: from the database in production, a fake in tests."""


def make_model_for(pool: AsyncConnectionPool, secrets: SecretStore | None, http_pool_timeout: float = 120) -> ModelFor:
    """The production `model_for`: the conversation's pinned provider and model, its key read from the secret store for this turn only."""

    async def model_for(conv: dict[str, Any]) -> tuple[Model, dict[str, Any]]:
        kind, base_url, key = await providers.provider_key(pool, secrets, conv['provider_id'])
        async with pool.connection() as conn:
            row = await (
                await conn.execute(
                    'select output_limit from provider_model where provider_id = %s and model_id = %s',
                    [conv['provider_id'], conv['model_id']],
                )
            ).fetchone()
        return providers.build_model(kind, conv['model_id'], base_url, key), providers.model_settings(
            kind, conv['mode'], row[0] if row else None
        )

    return model_for


def short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + '…'


def result_summary(name: str, content: Any) -> tuple[bool, str]:
    """(ok, one line) for a tool's return, for the chat's activity list."""
    if isinstance(content, dict) and 'error' in content:
        return False, short(content['error'])
    if isinstance(content, dict) and name == 'query_metric':
        return True, f'{content.get("row_count", 0)} rows' + (
            f', {content["suppressed_cells"]} cells hidden' if content.get('suppressed_cells') else ''
        )
    if isinstance(content, dict) and name == 'propose_chart':
        return True, 'chart saved as a draft'
    return True, short(content, 120)


async def _last_message(pool: AsyncConnectionPool, conversation_id: str) -> ModelMessage | None:
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                'select message from conversation_message where conversation_id = %s order by seq desc limit 1', [conversation_id]
            )
        ).fetchall()
    return store.load_messages(rows)[0] if rows else None


async def seal(pool: AsyncConnectionPool, conversation_id: str, reason: str) -> None:
    """If the history ends in a response whose tool calls never ran, answers them (as not run) so every call has a result."""
    last = await _last_message(pool, conversation_id)
    if isinstance(last, ModelResponse):
        calls = [p for p in last.parts if isinstance(p, ToolCallPart)]
        if calls:
            await store.append_message(
                pool,
                conversation_id,
                ModelRequest(
                    parts=[ToolReturnPart(tool_name=c.tool_name, content=f'not run: {reason}', tool_call_id=c.tool_call_id) for c in calls]
                ),
            )


async def _interrupt_requested(pool: AsyncConnectionPool, run_id: str) -> bool:
    async with pool.connection() as conn:
        row = await (await conn.execute('select interrupt_requested from agent_run where id = %s', [run_id])).fetchone()
    return bool(row and row[0])


async def _finish(
    pool: AsyncConnectionPool, conversation_id: str, run_id: str, status: str, stop_reason: str, usage: Any, error: str | None = None
) -> None:
    """Ends the run and writes its final event in one transaction: a chat that sees no active run is sure to see the final event too."""
    totals = {
        'requests': getattr(usage, 'requests', 0) or 0,
        'input_tokens': getattr(usage, 'input_tokens', 0) or 0,
        'output_tokens': getattr(usage, 'output_tokens', 0) or 0,
        'cache_read_tokens': getattr(usage, 'cache_read_tokens', 0) or 0,
        'cache_write_tokens': getattr(usage, 'cache_write_tokens', 0) or 0,
    }
    payload = {'stop_reason': stop_reason, 'usage': totals, **({'error': error} if error else {})}
    async with pool.connection() as conn, conn.transaction():
        await conn.execute(
            """update agent_run set status = %s, stop_reason = %s, error = %s, finished_at = now(), requests = %s, input_tokens = %s,
                                   output_tokens = %s, cache_read_tokens = %s, cache_write_tokens = %s where id = %s""",
            [status, stop_reason, error, *totals.values(), run_id],
        )
        await conn.execute(
            'insert into agent_event (conversation_id, run_id, type, payload) values (%s, %s, %s, %s)',
            [conversation_id, run_id, 'turn.failed' if status == 'failed' else 'turn.finished', Jsonb(payload)],
        )
        await conn.execute('select pg_notify(%s, %s)', [store.EVENT_CHANNEL, conversation_id])


async def process_turn(deps: TurnDeps, run_id: str) -> str:
    """Runs the turn queued as `run_id`; returns its outcome (done, interrupted, failed, skipped)."""
    pool = deps.pool
    async with pool.connection() as conn:
        claimed = await (
            await conn.execute(
                """update agent_run set status = 'running', started_at = now() where id = %s and status = 'queued'
                   returning conversation_id::text""",
                [run_id],
            )
        ).fetchone()
        if claimed is None:
            return 'skipped'
        conversation_id = claimed[0]
        crow = await (
            await conn.execute(
                'select mode, owner_id::text, provider_id::text, model_id from conversation where id = %s', [conversation_id]
            )
        ).fetchone()
    assert crow is not None
    conv = {'mode': crow[0], 'owner_id': crow[1], 'provider_id': crow[2], 'model_id': crow[3]}

    async def emit(type: str, payload: dict[str, Any] | None = None) -> None:
        await store.emit(pool, conversation_id, run_id, type, payload)

    await emit('turn.started', {'model': conv['model_id']})
    usage: Any = None
    stored = False  # whether the stored history's first request (the user's message) has been met yet
    status, stop_reason, error = 'done', 'end_turn', None
    try:
        model, settings = await deps.model_for(conv)
        agent: Agent[AgentDeps, str] = Agent(model, instructions=MODES[conv['mode']], toolsets=[ask_tools], deps_type=AgentDeps, retries=2)
        history = await store.read_messages(pool, conversation_id)
        tool_deps = AgentDeps(
            pool=pool,
            cube=deps.cube,
            user_id=conv['owner_id'],
            conversation_id=conversation_id,
            run_id=run_id,
            suppression_threshold=deps.suppression_threshold,
            emit=emit,
        )
        async with agent.iter(
            None,
            message_history=history,
            deps=tool_deps,
            model_settings=cast(ModelSettings, settings),
            usage_limits=usage_limits(conv['mode']),
        ) as run:
            try:
                async for node in run:
                    if Agent.is_model_request_node(node):
                        if not stored:
                            stored = True  # the first request is the user's message, already stored by the API
                        else:
                            await store.append_message(pool, conversation_id, node.request)  # the tool results, before the next model call
                        if await _interrupt_requested(pool, run_id):
                            status, stop_reason = 'interrupted', 'interrupted'
                            break
                        buffer, last_flush = '', time.monotonic()
                        async with node.stream(run.ctx) as model_stream:
                            async for event in model_stream:
                                chunk = ''
                                if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                                    chunk = event.part.content
                                elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                                    chunk = event.delta.content_delta
                                buffer += chunk
                                if buffer and (len(buffer) >= FLUSH_CHARS or time.monotonic() - last_flush >= FLUSH_SECONDS):
                                    await emit('text.delta', {'text': buffer})
                                    buffer, last_flush = '', time.monotonic()
                        if buffer:
                            await emit('text.delta', {'text': buffer})
                    elif Agent.is_call_tools_node(node):
                        response = node.model_response
                        await store.append_message(pool, conversation_id, response)  # before any tool runs
                        calls = [p for p in response.parts if isinstance(p, ToolCallPart)]
                        if calls and response.finish_reason in ('length', 'content_filter'):
                            status, stop_reason = 'done', 'length' if response.finish_reason == 'length' else 'refused'
                            await seal(
                                pool, conversation_id, 'the model response was cut off' if stop_reason == 'length' else 'the model declined'
                            )
                            break
                        if calls and await _interrupt_requested(pool, run_id):
                            status, stop_reason = 'interrupted', 'interrupted'
                            await seal(pool, conversation_id, 'interrupted by the person')
                            break
                        async with node.stream(run.ctx) as tool_stream:
                            async for tool_event in tool_stream:
                                if isinstance(tool_event, FunctionToolCallEvent):
                                    await emit('tool.started', {'name': tool_event.part.tool_name, 'summary': short(tool_event.part.args)})
                                elif isinstance(tool_event, FunctionToolResultEvent):
                                    ret = tool_event.part
                                    if ret.outcome == 'success':
                                        ok, text = result_summary(ret.tool_name, ret.content)
                                    else:  # a retry, a failure or a refusal of the call: its content is the error
                                        ok, text = False, short(ret.content)
                                    await emit('tool.finished', {'name': ret.tool_name, 'ok': ok, 'summary': text})
            finally:
                usage = run.usage
    except UsageLimitExceeded as e:
        status, stop_reason, error = 'failed', 'limit', f'the turn reached its usage limit: {e}'
    except Exception as e:  # provider down, a bad key, a tool bug: the turn ends with the reason; nothing is retried
        status, stop_reason, error = 'failed', 'error', f'{type(e).__name__}: {e}'
        log('error', 'agent turn failed', run_id=run_id, error=error)
    if status != 'done' or stop_reason != 'end_turn':
        await seal(pool, conversation_id, error or stop_reason)
    await _finish(pool, conversation_id, run_id, status, stop_reason, usage, error)
    return status
