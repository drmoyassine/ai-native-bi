"""Conversations, their messages and their events in PostgreSQL (DEC-018). Messages are Pydantic AI messages exactly as sent and received:
appended, never edited or deleted. Events are what the chat streams; a NOTIFY wakes the listeners."""

from __future__ import annotations

import json
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

EVENT_CHANNEL = 'agent_event'
EVENT_DAYS = 30


def dump_message(message: ModelMessage) -> tuple[str, Any]:
    """(kind, JSON) of one message, in Pydantic AI's own serialization (it keeps provider details such as thinking signatures)."""
    return message.kind, json.loads(ModelMessagesTypeAdapter.dump_json([message]))[0]


def load_messages(rows: list[tuple[Any, ...]]) -> list[ModelMessage]:
    return ModelMessagesTypeAdapter.validate_python([r[0] for r in rows])


async def append_message(pool: AsyncConnectionPool, conversation_id: str, message: ModelMessage) -> int:
    """Stores one message at the end of the conversation; the conversation row is locked so concurrent writers get distinct numbers."""
    kind, payload = dump_message(message)
    async with pool.connection() as conn, conn.transaction():
        await conn.execute('select 1 from conversation where id = %s for update', [conversation_id])
        row = await (
            await conn.execute('select coalesce(max(seq), 0) + 1 from conversation_message where conversation_id = %s', [conversation_id])
        ).fetchone()
        assert row is not None
        await conn.execute(
            'insert into conversation_message (conversation_id, seq, kind, message) values (%s, %s, %s, %s)',
            [conversation_id, row[0], kind, Jsonb(payload)],
        )
    return int(row[0])


async def read_messages(pool: AsyncConnectionPool, conversation_id: str) -> list[ModelMessage]:
    async with pool.connection() as conn:
        rows = await (
            await conn.execute('select message from conversation_message where conversation_id = %s order by seq', [conversation_id])
        ).fetchall()
    return load_messages(rows)


async def emit(
    pool: AsyncConnectionPool, conversation_id: str, run_id: str | None, type: str, payload: dict[str, Any] | None = None
) -> int:
    """Appends an event and wakes the chat's listeners; returns its id (the SSE cursor)."""
    async with pool.connection() as conn, conn.transaction():
        row = await (
            await conn.execute(
                'insert into agent_event (conversation_id, run_id, type, payload) values (%s, %s, %s, %s) returning id',
                [conversation_id, run_id, type, Jsonb(payload or {})],
            )
        ).fetchone()
        await conn.execute('select pg_notify(%s, %s)', [EVENT_CHANNEL, conversation_id])
    assert row is not None
    return int(row[0])


async def events_after(pool: AsyncConnectionPool, conversation_id: str, after: int) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                'select id, type, payload, run_id::text from agent_event where conversation_id = %s and id > %s order by id',
                [conversation_id, after],
            )
        ).fetchall()
    return [{'id': r[0], 'type': r[1], 'payload': r[2], 'run_id': r[3]} for r in rows]


async def active_run(pool: AsyncConnectionPool, conversation_id: str) -> str | None:
    """The queued or running turn of a conversation, if any."""
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                "select id::text from agent_run where conversation_id = %s and status in ('queued', 'running') order by created_at limit 1",
                [conversation_id],
            )
        ).fetchone()
    return row[0] if row else None


async def prune_events(pool: AsyncConnectionPool) -> int:
    async with pool.connection() as conn:
        cur = await conn.execute("delete from agent_event where created_at < now() - (%s || ' days')::interval", [str(EVENT_DAYS)])
        return cur.rowcount
