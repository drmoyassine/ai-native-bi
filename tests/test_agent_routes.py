from __future__ import annotations

import asyncio
import base64
import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic_ai.models import Model

from bi import accounts
from bi.agent.routes import AgentContext
from bi.agent.secrets import DbSecretStore
from bi.agent.turn import process_turn
from bi.api import AppDeps, create_app
from bi.app import AppContext
from bi.connect.files import Storage
from bi.cube import CubeClient

from .agent_fakes import FakeCube, scripted, turn_deps
from .conftest import AMS, PoolFactory

PASSWORD = 'a-long-password-0123'
APP = {'x-bi-app': '1'}
KEY = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
ANTHROPIC_KEY = 'sk-ant-api-THE-SECRET-VALUE-9f8e7d'


def listing_routes(request: httpx.Request) -> httpx.Response:
    host = request.url.netloc.decode()
    if host == 'api.anthropic.com':
        return httpx.Response(
            200,
            json={
                'data': [
                    {'id': 'claude-opus-5-5', 'display_name': 'Claude Opus 5.5', 'max_input_tokens': 1_000_000, 'max_tokens': 128_000},
                    {'id': 'claude-haiku-5-5', 'display_name': 'Claude Haiku 5.5'},
                ],
                'has_more': False,
            },
        )
    if host == 'api.openai.com':
        return httpx.Response(200, json={'data': [{'id': 'gpt-4.1'}, {'id': 'text-embedding-3-small'}]})
    if host == 'ollama.lan:11434':
        return httpx.Response(200, json={'models': []}) if request.url.path == '/api/tags' else httpx.Response(404)
    return httpx.Response(404, json={'error': 'unknown host'})


@dataclass
class Rig:
    api: httpx.AsyncClient  # the admin
    user: httpx.AsyncClient  # a person
    ctx: AgentContext
    queued: list[tuple[str, str]]
    pool: AsyncConnectionPool
    cube: FakeCube
    model_for_test: dict[str, Model]
    anonymous_transport: httpx.ASGITransport


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    p = await make_pool('bi_agent_routes_test')
    await accounts.create_user(p, 'admin@example.edu', 'Admin', PASSWORD, is_admin=True)
    await accounts.create_user(p, 'person@example.edu', 'Person', PASSWORD)
    await accounts.create_user(p, 'other@example.edu', 'Other', PASSWORD)
    return p


async def sign_in(app: Any, email: str) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://bi')
    res = await client.post('/app/api/session', json={'email': email, 'password': PASSWORD}, headers=APP)
    assert res.status_code == 200
    return client


@pytest.fixture
async def rig(pool: AsyncConnectionPool, tmp_path: Path) -> AsyncIterator[Rig]:
    queued: list[tuple[str, str]] = []
    cube = FakeCube()
    tests: dict[str, Model] = {}

    async def enqueue_turn(run_id: str, conversation_id: str) -> None:
        queued.append((run_id, conversation_id))

    async def noop(id: str) -> None:
        pass

    ctx = AgentContext(
        pool=pool,
        database_url=os.environ.get('TEST_DATABASE_ADMIN_URL', 'postgres://postgres:postgres@localhost:5432/postgres').rsplit('/', 1)[0]
        + '/bi_agent_routes_test',
        secrets=DbSecretStore(pool, KEY),
        http=httpx.AsyncClient(transport=httpx.MockTransport(listing_routes)),
        enqueue_turn=enqueue_turn,
        build_model=lambda kind, model_id, base_url, key: tests[kind],
    )
    app = create_app(
        AppDeps(
            pool=pool,
            api_key='k' * 16,
            ams_origin=AMS,
            enqueue=noop,
            app=AppContext(
                pool=pool,
                storage=Storage(f'file://{tmp_path}'),
                enqueue_load=noop,
                cube=cast(CubeClient, cube),  # a fake with the same two calls
                cookie_secure=False,
                agent=ctx,
            ),
        )
    )
    api, user = await sign_in(app, 'admin@example.edu'), await sign_in(app, 'person@example.edu')
    async with pool.connection() as conn:  # every test starts with no providers, conversations or secrets
        await conn.execute('delete from conversation; delete from model_provider; delete from secret; delete from draft')
    yield Rig(api, user, ctx, queued, pool, cube, tests, httpx.ASGITransport(app=app))
    await api.aclose()
    await user.aclose()


async def add_anthropic(rig: Rig, name: str = 'Anthropic') -> dict[str, Any]:
    res = await rig.api.post('/app/api/admin/providers', json={'kind': 'anthropic', 'name': name, 'api_key': ANTHROPIC_KEY}, headers=APP)
    assert res.status_code == 201, res.text
    provider: dict[str, Any] = res.json()['provider']
    return provider


async def allow(rig: Rig, provider_id: str, model_id: str, **flags: bool) -> httpx.Response:
    body = {
        'provider_id': provider_id,
        'model_id': model_id,
        'allowed_ask': True,
        'allowed_build': False,
        'default_ask': False,
        'default_build': False,
        **flags,
    }
    return await rig.api.put('/app/api/admin/models', json=body, headers=APP)


async def start_conversation(rig: Rig, client: httpx.AsyncClient | None = None) -> str:
    p = await add_anthropic(rig)
    assert (await allow(rig, p['id'], 'claude-opus-5-5', default_ask=True)).status_code == 200
    res = await (client or rig.user).post(
        '/app/api/conversations', json={'mode': 'ask', 'provider_id': p['id'], 'model_id': 'claude-opus-5-5'}, headers=APP
    )
    assert res.status_code == 201, res.text
    return str(res.json()['id'])


# ---- admin: providers and models ---------------------------------------------------------------------------------------------


async def test_only_admins_manage_providers(rig: Rig) -> None:
    anonymous = httpx.AsyncClient(transport=rig.anonymous_transport, base_url='http://bi')
    assert (await anonymous.get('/app/api/admin/providers')).status_code == 401
    assert (await rig.user.get('/app/api/admin/providers')).status_code == 403
    assert (
        await rig.user.post('/app/api/admin/providers', json={'kind': 'ollama', 'name': 'x', 'base_url': 'http://x'}, headers=APP)
    ).status_code == 403
    assert (await rig.user.put('/app/api/admin/models', json={'provider_id': 'x', 'model_id': 'y'}, headers=APP)).status_code == 403


async def test_a_provider_is_added_with_its_key_encrypted_and_its_models_fetched(rig: Rig) -> None:
    res = await rig.api.post(
        '/app/api/admin/providers', json={'kind': 'anthropic', 'name': 'Anthropic', 'api_key': ANTHROPIC_KEY}, headers=APP
    )
    body = res.json()
    assert res.status_code == 201 and body['fetch_error'] is None
    provider = body['provider']
    assert (provider['kind'], provider['has_key'], provider['models'], provider['allowed']) == ('anthropic', True, 2, 0)
    assert 'Anthropic' in provider['data_path'] and ANTHROPIC_KEY not in res.text  # the key is never sent back
    async with rig.pool.connection() as conn:
        row = await (await conn.execute("select ciphertext from secret where handle like 'secret://provider-%'")).fetchone()
        stored = await (await conn.execute('select key_handle from model_provider')).fetchone()
    assert (
        row is not None
        and ANTHROPIC_KEY.encode() not in bytes(row[0])
        and stored is not None
        and stored[0].startswith('secret://provider-')
    )
    listed = await rig.api.get('/app/api/admin/providers')
    assert ANTHROPIC_KEY not in listed.text and listed.json()['providers'][0]['has_key'] is True
    models = (await rig.api.get(f'/app/api/admin/providers/{provider["id"]}/models')).json()['models']
    assert {m['model_id']: (m['tool_support'], m['tool_support_via'], m['allowed_ask']) for m in models} == {
        'claude-opus-5-5': ('yes', 'list', False),
        'claude-haiku-5-5': ('yes', 'list', False),
    }  # fetched, tool-capable, and nothing allowed until an admin says so


async def test_providers_are_checked_when_added(rig: Rig) -> None:
    post = rig.api.post
    assert (await post('/app/api/admin/providers', json={'kind': 'anthropic', 'name': 'NoKey'}, headers=APP)).status_code == 422
    assert (await post('/app/api/admin/providers', json={'kind': 'ollama', 'name': 'NoAddress'}, headers=APP)).status_code == 422
    assert (
        await post('/app/api/admin/providers', json={'kind': 'ollama', 'name': 'Bad', 'base_url': 'ftp://x'}, headers=APP)
    ).status_code == 422
    assert (await post('/app/api/admin/providers', json={'kind': 'nonsense', 'name': 'Bad'}, headers=APP)).status_code == 422
    await add_anthropic(rig, 'Same')
    assert (
        await post('/app/api/admin/providers', json={'kind': 'anthropic', 'name': 'same', 'api_key': 'k'}, headers=APP)
    ).status_code == 409
    rig.ctx.secrets = None
    assert (
        await post('/app/api/admin/providers', json={'kind': 'anthropic', 'name': 'Other', 'api_key': 'k'}, headers=APP)
    ).status_code == 503


async def test_a_provider_that_cannot_list_is_kept_with_its_error(rig: Rig) -> None:
    res = await rig.api.post(
        '/app/api/admin/providers', json={'kind': 'ollama', 'name': 'Lan', 'base_url': 'http://nowhere.lan:11434'}, headers=APP
    )
    body = res.json()
    assert res.status_code == 201
    assert 'nowhere.lan:11434' in body['fetch_error'] and 'answered 404' in body['fetch_error']  # the admin sees what went wrong
    assert body['provider']['fetch_error'] == body['fetch_error'] and body['provider']['models'] == 0
    refreshed = await rig.api.post(f'/app/api/admin/providers/{body["provider"]["id"]}/refresh', headers=APP)
    assert refreshed.status_code == 200 and refreshed.json()['fetch_error']  # a refresh tries again and reports again


async def test_allowing_models_defaults_and_the_selector(rig: Rig) -> None:
    p = await add_anthropic(rig)
    assert (await rig.user.get('/app/api/models?mode=ask')).json()['providers'] == []  # nothing allowed yet
    assert (await allow(rig, p['id'], 'claude-opus-5-5', default_ask=True, allowed_build=True, default_build=True)).status_code == 200
    assert (await allow(rig, p['id'], 'claude-haiku-5-5')).status_code == 200
    ask = (await rig.user.get('/app/api/models?mode=ask')).json()['providers']
    assert len(ask) == 1 and ask[0]['kind'] == 'anthropic' and 'Anthropic' in ask[0]['data_path']
    assert [(m['model_id'], m['default']) for m in ask[0]['models']] == [('claude-haiku-5-5', False), ('claude-opus-5-5', True)]
    build = (await rig.user.get('/app/api/models?mode=build')).json()['providers']
    assert [m['model_id'] for m in build[0]['models']] == ['claude-opus-5-5']

    assert (await allow(rig, p['id'], 'claude-haiku-5-5', default_ask=True)).status_code == 200  # a new default replaces the old one
    ask = (await rig.user.get('/app/api/models?mode=ask')).json()['providers'][0]['models']
    assert [(m['model_id'], m['default']) for m in ask] == [('claude-haiku-5-5', True), ('claude-opus-5-5', False)]
    assert (
        await allow(rig, p['id'], 'claude-opus-5-5', allowed_ask=False, default_ask=True)
    ).status_code == 422  # a default must be allowed
    assert (await allow(rig, p['id'], 'no-such-model')).status_code == 404
    assert (await allow(rig, p['id'], 'claude-haiku-5-5', allowed_ask=False)).status_code == 200  # and a model can be taken away again
    assert [m['model_id'] for m in (await rig.user.get('/app/api/models?mode=ask')).json()['providers'][0]['models']] == ['claude-opus-5-5']


async def test_a_model_whose_tool_support_is_unknown_is_tested_before_it_is_allowed(rig: Rig) -> None:
    res = await rig.api.post('/app/api/admin/providers', json={'kind': 'openai', 'name': 'OpenAI', 'api_key': 'sk-openai'}, headers=APP)
    pid = res.json()['provider']['id']
    assert res.json()['provider']['models'] == 1  # the embedding model is not offered at all
    rig.model_for_test['openai'] = scripted([[('ping', {})], 'done'])  # a model that calls tools
    ok = await allow(rig, pid, 'gpt-4.1')
    assert (
        ok.status_code == 200 and ok.json()['models'][0]['tool_support'] == 'yes' and ok.json()['models'][0]['tool_support_via'] == 'test'
    )

    async with rig.pool.connection() as conn:
        await conn.execute(
            "update provider_model set tool_support = 'unknown', tool_support_via = null, allowed_ask = false where model_id = 'gpt-4.1'"
        )
    rig.model_for_test['openai'] = scripted(['I will not call tools.'])  # one that does not
    no = await allow(rig, pid, 'gpt-4.1')
    assert no.status_code == 422 and 'cannot call tools' in no.json()['detail']
    shown = (await rig.api.get(f'/app/api/admin/providers/{pid}/models')).json()['models'][0]
    assert (shown['tool_support'], shown['allowed_ask']) == ('no', False)


async def test_changing_a_providers_key_replaces_the_secret(rig: Rig) -> None:
    p = await add_anthropic(rig)
    res = await rig.api.put(
        f'/app/api/admin/providers/{p["id"]}', json={'api_key': 'sk-ant-rotated-key-0001', 'name': 'Anthropic prod'}, headers=APP
    )
    assert res.status_code == 200 and res.json()['provider']['name'] == 'Anthropic prod' and 'rotated' not in res.text
    assert await rig.ctx.secrets.get(f'secret://provider-{p["id"]}') == 'sk-ant-rotated-key-0001'  # type: ignore[union-attr]
    off = await rig.api.put(f'/app/api/admin/providers/{p["id"]}', json={'enabled': False}, headers=APP)
    assert off.json()['provider']['enabled'] is False
    await allow(rig, p['id'], 'claude-opus-5-5')
    assert (await rig.user.get('/app/api/models?mode=ask')).json()['providers'] == []  # a disabled provider offers nothing


# ---- conversations -----------------------------------------------------------------------------------------------------------


async def test_a_conversation_needs_an_allowed_model_and_belongs_to_its_owner(rig: Rig) -> None:
    p = await add_anthropic(rig)
    body = {'mode': 'ask', 'provider_id': p['id'], 'model_id': 'claude-opus-5-5'}
    assert (await rig.user.post('/app/api/conversations', json=body, headers=APP)).status_code == 422  # not allowed yet
    await allow(rig, p['id'], 'claude-opus-5-5')
    made = await rig.user.post('/app/api/conversations', json=body, headers=APP)
    assert made.status_code == 201
    assert (
        await rig.user.post('/app/api/conversations', json={**body, 'mode': 'build'}, headers=APP)
    ).status_code == 403  # building: admins, for now
    assert (
        await rig.user.post('/app/api/conversations', json={**body, 'mode': 'ask', 'model_id': 'claude-haiku-5-5'}, headers=APP)
    ).status_code == 422
    cid = made.json()['id']
    assert [c['id'] for c in (await rig.user.get('/app/api/conversations')).json()['conversations']] == [cid]
    assert (await rig.api.get('/app/api/conversations')).json()['conversations'] == []  # the admin does not see the person's chats
    assert (await rig.api.get(f'/app/api/conversations/{cid}')).status_code == 404
    assert (await rig.api.post(f'/app/api/conversations/{cid}/messages', json={'text': 'hi'}, headers=APP)).status_code == 404


async def test_a_message_is_stored_queued_and_one_turn_runs_at_a_time(rig: Rig) -> None:
    cid = await start_conversation(rig)
    empty = await rig.user.post(f'/app/api/conversations/{cid}/messages', json={'text': '   '}, headers=APP)
    assert empty.status_code == 422
    sent = await rig.user.post(
        f'/app/api/conversations/{cid}/messages', json={'text': 'How many students are enrolled in each program this term?'}, headers=APP
    )
    assert sent.status_code == 202 and rig.queued == [(sent.json()['run_id'], cid)]
    again = await rig.user.post(f'/app/api/conversations/{cid}/messages', json={'text': 'and last term?'}, headers=APP)
    assert again.status_code == 409 and 'still answering' in again.json()['detail']
    shown = (await rig.user.get(f'/app/api/conversations/{cid}')).json()
    assert shown['active_run'] == sent.json()['run_id'] and shown['items'] == [
        {'kind': 'user', 'text': 'How many students are enrolled in each program this term?'}
    ]
    assert (
        shown['conversation']['title'].startswith('How many students are enrolled')
        and shown['conversation']['model_id'] == 'claude-opus-5-5'
    )

    assert await process_turn(turn_deps(rig.pool, scripted(['Fine.']), rig.cube), sent.json()['run_id']) == 'done'
    after = (await rig.user.get(f'/app/api/conversations/{cid}')).json()
    assert after['active_run'] is None and [i['kind'] for i in after['items']] == ['user', 'assistant']
    assert (await rig.user.post(f'/app/api/conversations/{cid}/messages', json={'text': 'and last term?'}, headers=APP)).status_code == 202


async def test_the_monthly_budgets_stop_a_message(rig: Rig) -> None:
    cid = await start_conversation(rig)
    first = await rig.user.post(f'/app/api/conversations/{cid}/messages', json={'text': 'hello'}, headers=APP)
    await process_turn(turn_deps(rig.pool, scripted(['hi']), rig.cube), first.json()['run_id'])
    usage = (await rig.user.get('/app/api/agent/usage')).json()
    assert usage['person']['used'] > 0 and usage['person']['cap'] == rig.ctx.person_monthly_tokens
    rig.ctx.person_monthly_tokens = 1
    refused = await rig.user.post(f'/app/api/conversations/{cid}/messages', json={'text': 'again'}, headers=APP)
    assert refused.status_code == 429 and 'budget of you' in refused.json()['detail']
    rig.ctx.person_monthly_tokens, rig.ctx.organization_monthly_tokens = 10_000_000, 1
    assert (
        'budget of the organization'
        in (await rig.user.post(f'/app/api/conversations/{cid}/messages', json={'text': 'again'}, headers=APP)).json()['detail']
    )


async def test_interrupting_asks_the_running_turn_to_stop(rig: Rig) -> None:
    cid = await start_conversation(rig)
    assert (await rig.user.post(f'/app/api/conversations/{cid}/interrupt', headers=APP)).json() == {'requested': False}  # nothing running
    sent = await rig.user.post(f'/app/api/conversations/{cid}/messages', json={'text': 'hello'}, headers=APP)
    assert (await rig.user.post(f'/app/api/conversations/{cid}/interrupt', headers=APP)).json() == {'requested': True}
    assert (
        await process_turn(turn_deps(rig.pool, scripted([[('list_metrics', {})], 'unreached']), rig.cube), sent.json()['run_id'])
        == 'interrupted'
    )


# ---- the event stream --------------------------------------------------------------------------------------------------------


def parse_sse(body: str) -> list[dict[str, Any]]:
    out = []
    for block in body.split('\n\n'):
        fields = dict(line.split(': ', 1) for line in block.splitlines() if ': ' in line and not line.startswith(':'))
        if fields:
            out.append(fields)
    return out


async def test_the_stream_replays_what_happened_and_resumes_after_an_event(rig: Rig) -> None:
    cid = await start_conversation(rig)
    sent = await rig.user.post(f'/app/api/conversations/{cid}/messages', json={'text': 'hello'}, headers=APP)
    await process_turn(turn_deps(rig.pool, scripted([[('list_metrics', {})], 'All done.']), rig.cube), sent.json()['run_id'])
    body = (await rig.user.get(f'/app/api/conversations/{cid}/events?after={sent.json()["after"]}')).text
    events = parse_sse(body)
    names = [e['event'] for e in events]
    assert (
        names[0] == 'turn.started'
        and names[-2] == 'turn.finished'
        and names[-1] == 'end'
        and 'tool.started' in names
        and 'text.delta' in names
    )
    ids = [int(e['id']) for e in events if 'id' in e]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    resumed = parse_sse((await rig.user.get(f'/app/api/conversations/{cid}/events', headers={'Last-Event-ID': str(ids[2])})).text)
    assert [int(e['id']) for e in resumed if 'id' in e] == ids[3:] and resumed[-1]['event'] == 'end'  # nothing missed, nothing repeated
    assert (await rig.api.get(f'/app/api/conversations/{cid}/events')).status_code == 404  # another person's chat


async def test_a_stream_open_during_a_turn_wakes_up_for_each_event_and_ends_with_the_turn(rig: Rig) -> None:
    cid = await start_conversation(rig)
    sent = await rig.user.post(f'/app/api/conversations/{cid}/messages', json={'text': 'hello'}, headers=APP)
    stream = asyncio.create_task(rig.user.get(f'/app/api/conversations/{cid}/events?after={sent.json()["after"]}'))
    await asyncio.sleep(0.5)  # the stream is open and waiting: the turn is queued, nothing has happened
    assert not stream.done()
    await process_turn(turn_deps(rig.pool, scripted(['Live answer.']), rig.cube), sent.json()['run_id'])
    body = (await asyncio.wait_for(stream, timeout=20)).text
    names = [e['event'] for e in parse_sse(body)]
    assert names[0] == 'turn.started' and 'turn.finished' in names and names[-1] == 'end'
    assert re.search(r'Live answer\.', body)


async def test_the_agent_routes_need_a_signed_in_person(rig: Rig) -> None:
    cid = await start_conversation(rig)
    anonymous = httpx.AsyncClient(transport=rig.anonymous_transport, base_url='http://bi')
    for method, path in (
        ('GET', '/app/api/models'),
        ('GET', '/app/api/conversations'),
        ('GET', f'/app/api/conversations/{cid}'),
        ('GET', f'/app/api/conversations/{cid}/events'),
        ('GET', '/app/api/agent/usage'),
    ):
        assert (await anonymous.request(method, path)).status_code == 401, path
    for path in ('/app/api/conversations', f'/app/api/conversations/{cid}/messages', f'/app/api/conversations/{cid}/interrupt'):
        assert (await rig.user.post(path, json={})).status_code == 403, path  # signed in, but without the X-BI-App header: refused


async def test_a_person_without_a_session_header_cannot_change_anything(rig: Rig) -> None:
    p = await add_anthropic(rig)
    res = await rig.api.put('/app/api/admin/models', json={'provider_id': p['id'], 'model_id': 'claude-opus-5-5', 'allowed_ask': True})
    assert res.status_code == 403


async def test_a_proposed_charts_data_hides_small_counts_and_is_private_to_its_owner(rig: Rig) -> None:
    definition = {
        'version': 1,
        'title': 'Headcount by program',
        'query': {'measures': ['enrollment.headcount'], 'dimensions': ['enrollment.program']},
        'visual': {'type': 'bar', 'x': 'enrollment.program'},
    }
    rig.cube.rows = [
        {'enrollment.program': 'BSME', 'enrollment.headcount': '120'},
        {'enrollment.program': 'MSDS', 'enrollment.headcount': '2'},
    ]
    async with rig.pool.connection() as conn:
        row = await (
            await conn.execute(
                """insert into draft (kind, owner_id, built_by, definition)
                   select 'chart', id, 'agent', %s from app_user where email = 'person@example.edu' returning id::text""",
                [Jsonb(definition)],
            )
        ).fetchone()
    assert row is not None
    mine = await rig.user.get(f'/app/api/drafts/{row[0]}/data')
    assert mine.status_code == 200
    by_program = {r['enrollment.program']: r['enrollment.headcount'] for r in mine.json()['rows']}
    assert by_program == {'BSME': 120, 'MSDS': None} and mine.json()['suppressed_cells'] == 1  # the 2 never reaches the page
    assert '"2"' not in mine.text and ': 2' not in mine.text
    assert (await rig.api.get(f'/app/api/drafts/{row[0]}/data')).status_code == 404  # another person's draft: not even an admin's


async def test_a_provider_may_see_sample_rows_only_when_an_admin_says_so(rig: Rig) -> None:
    provider = await add_anthropic(rig)
    assert provider['may_see_samples'] is False  # off by default (DEC-032)
    url = f'/app/api/admin/providers/{provider["id"]}'
    assert (await rig.user.put(url, json={'may_see_samples': True}, headers=APP)).status_code == 403  # an admin only
    on = await rig.api.put(url, json={'may_see_samples': True}, headers=APP)
    assert on.status_code == 200 and on.json()['provider']['may_see_samples'] is True
    assert (await rig.api.put(url, json={'name': 'Renamed'}, headers=APP)).json()['provider'][
        'may_see_samples'
    ] is True  # a rename keeps it
    off = await rig.api.put(url, json={'may_see_samples': False}, headers=APP)
    assert off.json()['provider']['may_see_samples'] is False
