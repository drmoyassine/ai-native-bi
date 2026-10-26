from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from psycopg_pool import AsyncConnectionPool
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart

from bi import accounts
from bi.agent import store
from bi.agent.render import render_messages
from bi.agent.turn import process_turn

from .agent_fakes import FakeCube, conversation, provider, queue_turn, scripted, turn_deps
from .conftest import PoolFactory

PASSWORD = 'a-long-password-0123'


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    return await make_pool('bi_agent_turn_test')


@pytest.fixture(scope='module')
async def user_id(pool: AsyncConnectionPool) -> str:
    return (await accounts.create_user(pool, 'turn@example.edu', 'Turn Tester', PASSWORD)).id


@pytest.fixture
async def conv(pool: AsyncConnectionPool, user_id: str) -> str:
    return await conversation(pool, user_id, await provider(pool, name=f'p{uuid.uuid4().hex[:8]}'))


async def events(pool: AsyncConnectionPool, conv: str) -> list[tuple[str, dict[str, Any]]]:
    return [(e['type'], e['payload']) for e in await store.events_after(pool, conv, 0)]


async def run_row(pool: AsyncConnectionPool, run_id: str) -> dict[str, Any]:
    async with pool.connection() as conn:
        r = await (
            await conn.execute(
                'select status, stop_reason, error, requests, input_tokens, output_tokens, finished_at from agent_run where id = %s',
                [run_id],
            )
        ).fetchone()
    assert r is not None
    return dict(zip(('status', 'stop_reason', 'error', 'requests', 'input', 'output', 'finished'), r, strict=True))


def valid_history(messages: list[Any]) -> bool:
    """Every tool call has a result, in the message right after it: what a provider requires."""
    for i, m in enumerate(messages):
        if isinstance(m, ModelResponse):
            calls = {p.tool_call_id for p in m.parts if isinstance(p, ToolCallPart)}
            if calls:
                nxt = messages[i + 1] if i + 1 < len(messages) else None
                returned = {p.tool_call_id for p in nxt.parts if isinstance(p, ToolReturnPart)} if isinstance(nxt, ModelRequest) else set()
                if not calls <= returned:
                    return False
    return True


async def test_answers_a_question_from_governed_metrics(pool: AsyncConnectionPool, conv: str) -> None:
    cube = FakeCube()
    model = scripted(
        [
            [('list_metrics', {})],
            [('query_metric', {'query': {'measures': ['enrollment.headcount'], 'dimensions': ['enrollment.program']}})],
            'BSME has 120 and BSCE 87 students, as of 2026-10-20.',
        ]
    )
    run_id = await queue_turn(pool, conv, 'How many students per program?')
    assert await process_turn(turn_deps(pool, model, cube), run_id) == 'done'

    kinds = [t for t, _ in await events(pool, conv)]
    assert kinds[0] == 'turn.started' and kinds[-1] == 'turn.finished'
    assert kinds.count('tool.started') == 2 and kinds.count('tool.finished') == 2 and 'text.delta' in kinds
    text = ''.join(p['text'] for t, p in await events(pool, conv) if t == 'text.delta')
    assert text == 'BSME has 120 and BSCE 87 students, as of 2026-10-20.'
    table = next(p for t, p in await events(pool, conv) if t == 'result.table')
    assert table['rows'] == [
        {'enrollment.program': 'BSME', 'enrollment.headcount': 120},
        {'enrollment.program': 'BSCE', 'enrollment.headcount': 87},
    ]
    assert table['as_of'] == '2026-10-20' and 'enrollment.as_of' not in json.dumps(table['rows'])
    assert cube.queries[-1]['measures'] == ['enrollment.headcount', 'enrollment.as_of']  # the as-of date rides along

    run = await run_row(pool, run_id)
    assert (run['status'], run['stop_reason'], run['requests']) == ('done', 'end_turn', 3) and run['finished'] is not None
    messages = await store.read_messages(pool, conv)
    assert valid_history(messages) and len(messages) == 6  # user, call, results, call, results, answer
    items = render_messages(messages)
    assert [i['kind'] for i in items] == ['user', 'tool', 'tool', 'table', 'assistant']
    assert items[1]['ok'] is True and items[2]['summary'] == '2 rows'


async def test_small_counts_never_reach_the_model(pool: AsyncConnectionPool, conv: str) -> None:
    cube = FakeCube(
        [
            {'enrollment.program': 'BSME', 'enrollment.headcount': '120', 'enrollment.as_of': '20261020'},
            {'enrollment.program': 'MSDS', 'enrollment.headcount': '3', 'enrollment.as_of': '20261020'},
        ]
    )
    model = scripted([[('query_metric', {'query': {'measures': ['enrollment.headcount'], 'dimensions': ['enrollment.program']}})], 'done'])
    run_id = await queue_turn(pool, conv, 'headcount by program')
    await process_turn(turn_deps(pool, model, cube, threshold=5), run_id)
    sent_second = json.dumps([str(m) for m in model.seen[1]])  # type: ignore[attr-defined]
    assert '120' in sent_second and "'enrollment.headcount': 3" not in sent_second and 'suppressed' in sent_second
    table = next(p for t, p in await events(pool, conv) if t == 'result.table')
    assert table['rows'][1] == {'enrollment.program': 'MSDS', 'enrollment.headcount': None, 'suppressed': ['enrollment.headcount']}
    assert table['suppressed_cells'] == 1


async def test_a_chart_is_a_private_draft_of_the_person(pool: AsyncConnectionPool, conv: str, user_id: str) -> None:
    chart = {
        'title': 'Headcount by program',
        'query': {'measures': ['enrollment.headcount'], 'dimensions': ['enrollment.program']},
        'visual': {'type': 'bar', 'x': 'enrollment.program'},
    }
    ungoverned = {**chart, 'query': {'measures': ['enrollment.student_id'], 'dimensions': ['enrollment.program']}}
    model = scripted([[('propose_chart', {'chart': chart})], [('propose_chart', {'chart': ungoverned})], 'Here is the chart.'])
    run_id = await queue_turn(pool, conv, 'chart it')
    assert await process_turn(turn_deps(pool, model, FakeCube()), run_id) == 'done'
    async with pool.connection() as conn:
        drafts = await (
            await conn.execute('select owner_id::text, built_by, state, definition from draft where conversation_id = %s', [conv])
        ).fetchall()
    assert len(drafts) == 1 and drafts[0][:3] == (user_id, 'agent', 'draft') and drafts[0][3]['visual']['type'] == 'bar'
    emitted = [p for t, p in await events(pool, conv) if t == 'result.chart']
    assert len(emitted) == 1 and emitted[0]['chart']['title'] == 'Headcount by program'
    finished = [p for t, p in await events(pool, conv) if t == 'tool.finished']
    assert [f['ok'] for f in finished] == [True, False] and 'not governed' in finished[1]['summary']
    assert [i['kind'] for i in render_messages(await store.read_messages(pool, conv))] == ['user', 'tool', 'chart', 'tool', 'assistant']


async def test_an_interrupt_ends_the_turn_and_leaves_a_valid_history(pool: AsyncConnectionPool, conv: str) -> None:
    model = scripted([[('list_metrics', {})], 'never reached'])
    run_id = await queue_turn(pool, conv, 'hello')
    async with pool.connection() as c:
        await c.execute('update agent_run set interrupt_requested = true where id = %s', [run_id])
    assert await process_turn(turn_deps(pool, model, FakeCube()), run_id) == 'interrupted'
    assert (await run_row(pool, run_id))['stop_reason'] == 'interrupted'
    assert valid_history(await store.read_messages(pool, conv)) and (await events(pool, conv))[-1][0] == 'turn.finished'


async def test_a_failure_ends_the_turn_with_its_reason_and_the_next_message_continues(pool: AsyncConnectionPool, conv: str) -> None:
    cube = FakeCube()
    cube.fail = RuntimeError('database is on fire')  # not a CubeError: nothing handles it, the turn must still end cleanly
    model = scripted([[('query_metric', {'query': {'measures': ['enrollment.headcount']}})], 'recovered'])
    run_id = await queue_turn(pool, conv, 'first try')
    assert await process_turn(turn_deps(pool, model, cube), run_id) == 'failed'
    run = await run_row(pool, run_id)
    assert run['status'] == 'failed' and 'database is on fire' in run['error'] and run['finished'] is not None
    last_event = (await events(pool, conv))[-1]
    assert last_event[0] == 'turn.failed' and 'database is on fire' in last_event[1]['error']
    messages = await store.read_messages(pool, conv)
    assert valid_history(messages)  # the call that never ran was answered ("not run: ...")

    cube.fail = None
    second = await queue_turn(pool, conv, 'try again')
    model2 = scripted(['It works now.'])
    assert await process_turn(turn_deps(pool, model2, cube), second) == 'done'
    assert render_messages(await store.read_messages(pool, conv))[-1] == {'kind': 'assistant', 'text': 'It works now.'}


async def test_a_runaway_loop_stops_at_the_request_limit(pool: AsyncConnectionPool, conv: str) -> None:
    model = scripted([[('list_datasets', {})]])  # the same call, forever
    run_id = await queue_turn(pool, conv, 'loop')
    assert await process_turn(turn_deps(pool, model, FakeCube()), run_id) == 'failed'
    run = await run_row(pool, run_id)
    assert run['stop_reason'] == 'limit' and 'usage limit' in run['error'] and valid_history(await store.read_messages(pool, conv))


async def test_a_turn_is_claimed_once(pool: AsyncConnectionPool, conv: str) -> None:
    run_id = await queue_turn(pool, conv, 'hi')
    deps = turn_deps(pool, scripted(['hello']), FakeCube())
    assert await process_turn(deps, run_id) == 'done'
    assert await process_turn(deps, run_id) == 'skipped'
