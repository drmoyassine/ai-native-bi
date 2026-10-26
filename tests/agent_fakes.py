"""Fakes for the agent's tests: a Cube that knows count measures, a scripted model, and a conversation with a queued turn."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from psycopg_pool import AsyncConnectionPool
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from bi.agent import store
from bi.agent.turn import TurnDeps

MEMBERS: list[dict[str, Any]] = [
    {
        'name': 'enrollment.headcount',
        'title': 'Headcount',
        'kind': 'measure',
        'type': 'number',
        'agg_type': 'countDistinct',
        'cube': 'Enrollment',
        'description': 'Distinct students on the roster',
    },
    {
        'name': 'enrollment.as_of',
        'title': 'Data as of',
        'kind': 'measure',
        'type': 'number',
        'agg_type': 'max',
        'cube': 'Enrollment',
        'description': None,
    },
    {
        'name': 'enrollment.avg_credits',
        'title': 'Average credits',
        'kind': 'measure',
        'type': 'number',
        'agg_type': 'avg',
        'cube': 'Enrollment',
        'description': None,
    },
    {
        'name': 'enrollment.program',
        'title': 'Program',
        'kind': 'dimension',
        'type': 'string',
        'agg_type': None,
        'cube': 'Enrollment',
        'description': None,
    },
    {
        'name': 'enrollment.level',
        'title': 'Level',
        'kind': 'dimension',
        'type': 'string',
        'agg_type': None,
        'cube': 'Enrollment',
        'description': None,
    },
    {
        'name': 'enrollment.term_start',
        'title': 'Term start',
        'kind': 'dimension',
        'type': 'time',
        'agg_type': None,
        'cube': 'Enrollment',
        'description': None,
    },
]


class FakeCube:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = (
            rows
            if rows is not None
            else [
                {'enrollment.program': 'BSME', 'enrollment.headcount': '120', 'enrollment.as_of': '20261020'},
                {'enrollment.program': 'BSCE', 'enrollment.headcount': '87', 'enrollment.as_of': '20261020'},
            ]
        )
        self.queries: list[dict[str, Any]] = []
        self.fail: Exception | None = None

    async def meta(self) -> list[dict[str, Any]]:
        return MEMBERS

    async def load(self, query: dict[str, Any], fresh: bool = False) -> list[dict[str, Any]]:
        if self.fail:
            raise self.fail
        self.queries.append(query)
        return [dict(r) for r in self.rows]


Step = str | Sequence[tuple[str, dict[str, Any]]]


def scripted(steps: Sequence[Step]) -> FunctionModel:
    """A model that does what `steps` say, one step per request: a string is text, a list of (tool, arguments) is tool calls. The last step
    repeats if the loop goes on. `seen` keeps what the model was sent each time, for checking what reaches a model."""
    state = {'n': 0}
    seen: list[list[Any]] = []

    async def stream(messages: list[Any], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        seen.append(list(messages))
        step = steps[min(state['n'], len(steps) - 1)]
        state['n'] += 1
        if isinstance(step, str):
            for i in range(0, len(step), 40):
                yield step[i : i + 40]
        else:
            for i, (name, args) in enumerate(step):
                yield {i: DeltaToolCall(name=name, json_args=json.dumps(args))}

    model = FunctionModel(stream_function=stream)
    model.seen = seen  # type: ignore[attr-defined]
    return model


def turn_deps(pool: AsyncConnectionPool, model: FunctionModel, cube: FakeCube | None, threshold: int = 5) -> TurnDeps:
    async def model_for(conv: dict[str, Any]) -> tuple[FunctionModel, dict[str, Any]]:
        return model, {}

    return TurnDeps(pool=pool, cube=cube, suppression_threshold=threshold, model_for=model_for)  # type: ignore[arg-type]


async def provider(pool: AsyncConnectionPool, kind: str = 'openai_compatible', name: str = 'test') -> str:
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                "insert into model_provider (kind, name, base_url) values (%s, %s, 'http://x/v1') returning id::text", [kind, name]
            )
        ).fetchone()
    assert row is not None
    return str(row[0])


async def conversation(pool: AsyncConnectionPool, owner_id: str, provider_id: str, mode: str = 'ask') -> str:
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                'insert into conversation (owner_id, mode, provider_id, model_id) values (%s, %s, %s, %s) returning id::text',
                [owner_id, mode, provider_id, 'fake-model'],
            )
        ).fetchone()
    assert row is not None
    return str(row[0])


async def queue_turn(pool: AsyncConnectionPool, conversation_id: str, text: str) -> str:
    """What the API does for a message: store it, queue a run. Returns the run id."""
    await store.append_message(pool, conversation_id, ModelRequest(parts=[UserPromptPart(content=text)]))
    async with pool.connection() as conn:
        row = await (
            await conn.execute('insert into agent_run (conversation_id) values (%s) returning id::text', [conversation_id])
        ).fetchone()
    assert row is not None
    return str(row[0])
