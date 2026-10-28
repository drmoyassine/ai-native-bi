"""The production path end to end against a server that speaks the OpenAI protocol over real HTTP: the provider and its key from the
database, the real OpenAI client inside Pydantic AI, tool-call streaming, the model test call, and a whole conversation."""

from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from psycopg_pool import AsyncConnectionPool

from bi import accounts
from bi.agent import store
from bi.agent.routes import AgentContext
from bi.agent.secrets import DbSecretStore
from bi.agent.turn import TurnDeps, make_model_for, process_turn
from bi.api import AppDeps, create_app
from bi.app import AppContext
from bi.connect.files import Storage

from .conftest import AMS, PoolFactory, database_url
from .fake_openai import ServerThread

PASSWORD = 'a-long-password-0123'
APP = {'x-bi-app': '1'}
KEY = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')


@pytest.fixture(scope='module')
def server() -> Iterator[tuple[ServerThread, str]]:
    s = ServerThread()
    yield s, s.start()
    s.stop()


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    p = await make_pool('bi_agent_provider_test')
    await accounts.create_user(p, 'admin@example.edu', 'Admin', PASSWORD, is_admin=True)
    return p


@pytest.fixture
async def api(pool: AsyncConnectionPool, tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, AgentContext]]:
    async def enqueue(run_id: str, conversation_id: str) -> None:
        pass

    async def noop(id: str) -> None:
        pass

    async with httpx.AsyncClient() as http:
        ctx = AgentContext(
            pool=pool,
            database_url=database_url('bi_agent_provider_test'),
            secrets=DbSecretStore(pool, KEY),
            http=http,
            enqueue_turn=enqueue,
        )
        app = create_app(
            AppDeps(
                pool=pool,
                api_key='k' * 16,
                ams_origin=AMS,
                enqueue=noop,
                app=AppContext(
                    pool=pool, storage=Storage(f'file://{tmp_path}'), enqueue_load=noop, cube=None, cookie_secure=False, agent=ctx
                ),
            )
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://bi') as client:
            assert (
                await client.post('/app/api/session', json={'email': 'admin@example.edu', 'password': PASSWORD}, headers=APP)
            ).status_code == 200
            yield client, ctx


async def test_a_whole_conversation_through_a_real_provider_client(
    api: tuple[httpx.AsyncClient, AgentContext], server: tuple[ServerThread, str], pool: AsyncConnectionPool
) -> None:
    client, ctx = api
    fake, base_url = server
    async with pool.connection() as conn:
        await conn.execute('delete from conversation; delete from model_provider; delete from secret')

    # 1. an admin adds the server as an OpenAI-compatible provider: its models are fetched over HTTP
    added = await client.post(
        '/app/api/admin/providers',
        json={'kind': 'openai_compatible', 'name': 'Fake', 'base_url': base_url, 'api_key': 'sk-fake-key'},
        headers=APP,
    )
    assert added.status_code == 201 and added.json()['fetch_error'] is None and added.json()['provider']['models'] == 2
    pid = added.json()['provider']['id']

    # 2. its tool support is unknown, so allowing a model runs the real test call: one that calls tools passes, one that cannot is refused
    body = {'provider_id': pid, 'allowed_ask': True, 'allowed_build': False, 'default_ask': True, 'default_build': False}
    ok = await client.put('/app/api/admin/models', json={**body, 'model_id': 'fake-chat'}, headers=APP)
    assert ok.status_code == 200
    no = await client.put('/app/api/admin/models', json={**body, 'model_id': 'fake-no-tools', 'default_ask': False}, headers=APP)
    assert no.status_code == 422 and 'test call failed' in no.json()['detail']
    states = {
        m['model_id']: (m['tool_support'], m['tool_support_via'], m['allowed_ask'])
        for m in (await client.get(f'/app/api/admin/providers/{pid}/models')).json()['models']
    }
    assert states == {
        'fake-chat': ('yes', 'test', True),
        'fake-no-tools': ('unknown', None, False),
    }  # an error is not proof: only a clean answer is recorded
    assert all(r['auth'] == 'Bearer sk-fake-key' for r in fake.requests)  # the key came out of the secret store

    # 3. a person's conversation: the worker's production model_for reads the pinned provider and model from the database
    selector = (await client.get('/app/api/models?mode=ask')).json()['providers']
    assert [m['model_id'] for m in selector[0]['models']] == ['fake-chat'] and selector[0]['models'][0]['default'] is True
    cid = (
        await client.post('/app/api/conversations', json={'mode': 'ask', 'provider_id': pid, 'model_id': 'fake-chat'}, headers=APP)
    ).json()['id']
    sent = await client.post(f'/app/api/conversations/{cid}/messages', json={'text': 'What data do we have?'}, headers=APP)
    assert sent.status_code == 202
    fake.requests.clear()
    deps = TurnDeps(pool=pool, cube=None, suppression_threshold=5, model_for=make_model_for(pool, ctx.secrets))
    assert await process_turn(deps, sent.json()['run_id']) == 'done'

    shown = (await client.get(f'/app/api/conversations/{cid}')).json()
    assert [i['kind'] for i in shown['items']] == ['user', 'tool', 'assistant']
    assert shown['items'][1]['name'] == 'list_datasets' and shown['items'][1]['ok'] is True
    assert shown['items'][2]['text'] == 'The warehouse has enrollment data.'
    sent_to_provider = fake.requests[0]['body']
    assert sent_to_provider['model'] == 'fake-chat' and {t['function']['name'] for t in sent_to_provider['tools']} >= {
        'list_metrics',
        'query_metric',
        'propose_chart',
    }
    assert sent_to_provider['messages'][0]['role'] == 'system' and 'analytics assistant' in sent_to_provider['messages'][0]['content']
    assert len(fake.requests) == 2 and any(m['role'] == 'tool' for m in fake.requests[1]['body']['messages'])  # the tool's result went back

    async with pool.connection() as conn:
        run = await (
            await conn.execute(
                'select status, requests, input_tokens, output_tokens from agent_run where id::text = %s', [sent.json()['run_id']]
            )
        ).fetchone()
    assert run is not None and run[0] == 'done' and run[1] == 2 and run[2] > 0 and run[3] > 0  # usage from the provider is kept
    assert [e['type'] for e in await store.events_after(pool, cid, 0)][-1] == 'turn.finished'

    # 4. the next message continues the same conversation: the stored history replays to the provider
    fake.requests.clear()
    second = await client.post(f'/app/api/conversations/{cid}/messages', json={'text': 'Thanks!'}, headers=APP)
    assert await process_turn(deps, second.json()['run_id']) == 'done'
    replay = fake.requests[0]['body']['messages']
    assert [m['role'] for m in replay] == ['system', 'user', 'assistant', 'tool', 'assistant', 'user']


async def test_a_bad_key_ends_the_turn_with_a_readable_failure(
    api: tuple[httpx.AsyncClient, AgentContext], server: tuple[ServerThread, str], pool: AsyncConnectionPool
) -> None:
    client, ctx = api
    _, base_url = server
    async with pool.connection() as conn:
        await conn.execute('delete from conversation; delete from model_provider; delete from secret')
    added = await client.post(
        '/app/api/admin/providers', json={'kind': 'openai_compatible', 'name': 'Down', 'base_url': base_url, 'api_key': 'sk-1'}, headers=APP
    )
    pid = added.json()['provider']['id']
    await client.put('/app/api/admin/models', json={'provider_id': pid, 'model_id': 'fake-chat', 'allowed_ask': True}, headers=APP)
    cid = (
        await client.post('/app/api/conversations', json={'mode': 'ask', 'provider_id': pid, 'model_id': 'fake-chat'}, headers=APP)
    ).json()['id']
    async with pool.connection() as conn:  # the provider disappears: its address now points nowhere
        await conn.execute("update model_provider set base_url = 'http://127.0.0.1:9/v1' where id::text = %s", [pid])
    sent = await client.post(f'/app/api/conversations/{cid}/messages', json={'text': 'hello'}, headers=APP)
    deps = TurnDeps(pool=pool, cube=None, suppression_threshold=5, model_for=make_model_for(pool, ctx.secrets))
    assert await process_turn(deps, sent.json()['run_id']) == 'failed'
    last = (await store.events_after(pool, cid, 0))[-1]
    assert last['type'] == 'turn.failed' and last['payload']['error']  # the chat shows why, and the conversation is intact
    assert (await client.get(f'/app/api/conversations/{cid}')).json()['active_run'] is None
