from __future__ import annotations

import base64
import json
import os
from typing import Any

import httpx
import pytest
from psycopg_pool import AsyncConnectionPool
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from bi import accounts
from bi.agent import catalog, providers
from bi.agent.secrets import DbSecretStore, SecretError, parse_key
from bi.agent.suppress import count_measures, suppress_rows

from .agent_fakes import MEMBERS
from .conftest import PoolFactory

KEY = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    return await make_pool('bi_agent_units_test')


# ---- the secret store --------------------------------------------------------------------------------------------------------


async def test_a_secret_is_encrypted_at_rest_and_opens_only_with_its_key(pool: AsyncConnectionPool) -> None:
    store = DbSecretStore(pool, KEY)
    assert await store.put('secret://anthropic-key', 'sk-ant-very-secret') == 'secret://anthropic-key'
    assert await store.get('secret://anthropic-key') == 'sk-ant-very-secret'
    async with pool.connection() as conn:
        row = await (
            await conn.execute("select nonce, ciphertext, last_used_at from secret where handle = 'secret://anthropic-key'")
        ).fetchone()
    assert row is not None and b'sk-ant-very-secret' not in bytes(row[1]) and row[2] is not None
    other = DbSecretStore(pool, base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('='))
    with pytest.raises(SecretError, match='cannot be opened'):
        await other.get('secret://anthropic-key')
    with pytest.raises(SecretError, match='no secret'):
        await store.get('secret://missing')
    await store.put('secret://anthropic-key', 'rotated')  # a new value replaces the old
    assert await store.get('secret://anthropic-key') == 'rotated'
    await store.delete('secret://anthropic-key')
    with pytest.raises(SecretError):
        await store.get('secret://anthropic-key')


async def test_a_ciphertext_cannot_be_moved_to_another_handle(pool: AsyncConnectionPool) -> None:
    store = DbSecretStore(pool, KEY)
    await store.put('secret://one', 'value-one')
    await store.put('secret://two', 'value-two')
    async with pool.connection() as conn:
        await conn.execute(
            """update secret set nonce = (select nonce from secret where handle = 'secret://one'),
                                 ciphertext = (select ciphertext from secret where handle = 'secret://one') where handle = 'secret://two'"""
        )
    with pytest.raises(SecretError, match='cannot be opened'):
        await store.get('secret://two')


def test_the_key_and_the_handle_are_checked() -> None:
    assert len(parse_key(KEY)) == 32
    for bad in ('short', 'x' * 50, '!' * 43):
        with pytest.raises(SecretError):
            parse_key(bad)


async def test_a_malformed_handle_is_refused(pool: AsyncConnectionPool) -> None:
    store = DbSecretStore(pool, KEY)
    for handle in ('anthropic', 'secret://', 'secret://A B', "secret://x'; drop table secret; --"):
        with pytest.raises(SecretError, match='not a secret handle'):
            await store.put(handle, 'v')


# ---- small cells -------------------------------------------------------------------------------------------------------------


def test_only_counts_under_the_threshold_are_hidden() -> None:
    counts = count_measures(MEMBERS)
    assert counts == {'enrollment.headcount'}
    rows, hidden = suppress_rows(
        [
            {'p': 'A', 'enrollment.headcount': '12', 'enrollment.avg_credits': '3'},
            {'p': 'B', 'enrollment.headcount': '4', 'enrollment.avg_credits': '2.5'},
            {'p': 'C', 'enrollment.headcount': '0', 'enrollment.avg_credits': None},
            {'p': 'D', 'enrollment.headcount': '5', 'enrollment.avg_credits': '1'},
        ],
        ['enrollment.headcount', 'enrollment.avg_credits'],
        counts,
        5,
    )
    assert hidden == 1
    assert [r['enrollment.headcount'] for r in rows] == [12, None, 0, 5]  # 4 hidden; 0 and 5 are not
    assert rows[1]['suppressed'] == ['enrollment.headcount'] and 'suppressed' not in rows[0]
    assert [r['enrollment.avg_credits'] for r in rows] == [3, 2.5, None, 1]  # an average is not a count: never hidden


# ---- the five providers' model lists -----------------------------------------------------------------------------------------


def mock_client(routes: dict[str, Any]) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        key = f'{req.method} {req.url.scheme}://{req.url.netloc.decode()}{req.url.path}'
        result = routes.get(key)
        if callable(result):
            result = result(req)
        if result is None:
            return httpx.Response(404, json={'error': f'no route {key}'})
        return result if isinstance(result, httpx.Response) else httpx.Response(200, json=result)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle)), seen


async def test_anthropic_lists_models_page_by_page() -> None:
    def page(req: httpx.Request) -> dict[str, Any]:
        if req.url.params.get('after_id') == 'claude-b':
            return {'data': [{'id': 'claude-c', 'display_name': 'Claude C'}], 'has_more': False, 'last_id': 'claude-c'}
        return {
            'data': [
                {'id': 'claude-a', 'display_name': 'Claude A', 'max_input_tokens': 1_000_000, 'max_tokens': 128_000},
                {'id': 'claude-b', 'display_name': 'Claude B'},
            ],
            'has_more': True,
            'last_id': 'claude-b',
        }

    client, seen = mock_client({'GET https://api.anthropic.com/v1/models': page})
    models = await providers.fetch_models(client, 'anthropic', None, 'sk-ant-1')
    assert [m.model_id for m in models] == ['claude-a', 'claude-b', 'claude-c']
    assert models[0].context_window == 1_000_000 and models[0].output_limit == 128_000 and all(m.tool_support == 'yes' for m in models)
    assert seen[0].headers['x-api-key'] == 'sk-ant-1' and seen[0].headers['anthropic-version']


async def test_openai_keeps_chat_models_and_leaves_tool_support_to_a_test() -> None:
    ids = [
        'gpt-4.1',
        'gpt-4o-mini',
        'o3',
        'text-embedding-3-large',
        'whisper-1',
        'dall-e-3',
        'gpt-4o-audio-preview',
        'omni-moderation-latest',
        'tts-1',
    ]
    client, seen = mock_client({'GET https://api.openai.com/v1/models': {'data': [{'id': i} for i in ids]}})
    models = await providers.fetch_models(client, 'openai', None, 'sk-1')
    assert [m.model_id for m in models] == ['gpt-4.1', 'gpt-4o-mini', 'o3'] and {m.tool_support for m in models} == {'unknown'}
    assert seen[0].headers['authorization'] == 'Bearer sk-1'


async def test_an_openai_compatible_server_lists_whatever_it_serves() -> None:
    client, seen = mock_client(
        {'GET http://vllm.lan:8000/v1/models': {'data': [{'id': 'Qwen/Qwen3-32B', 'max_model_len': 32768}, {'id': 'my-embedder'}]}}
    )
    models = await providers.fetch_models(client, 'openai_compatible', 'http://vllm.lan:8000/v1', None)
    assert [(m.model_id, m.context_window) for m in models] == [('Qwen/Qwen3-32B', 32768), ('my-embedder', None)]
    assert 'authorization' not in seen[0].headers  # a server without a key is sent none


async def test_openrouter_says_which_models_take_tools_and_what_they_cost() -> None:
    body = {
        'data': [
            {
                'id': 'anthropic/claude-opus-5-5',
                'name': 'Claude Opus 5.5',
                'context_length': 1_000_000,
                'pricing': {'prompt': '0.000004', 'completion': '0.00002'},
                'top_provider': {'max_completion_tokens': 128000},
                'supported_parameters': ['tools', 'temperature'],
            },
            {
                'id': 'some/chat-only',
                'name': 'Chat only',
                'context_length': 8192,
                'pricing': {'prompt': '0', 'completion': '0'},
                'supported_parameters': ['temperature'],
            },
            {'id': 'some/unsaid', 'name': 'Unsaid', 'pricing': {}},
        ]
    }
    client, _ = mock_client({'GET https://openrouter.ai/api/v1/models': body})
    a, b, c = await providers.fetch_models(client, 'openrouter', None, 'or-key')
    assert (a.tool_support, a.price_in, a.price_out, a.output_limit, a.context_window) == ('yes', 4.0, 20.0, 128000, 1_000_000)
    assert (b.tool_support, c.tool_support) == ('no', 'unknown')


async def test_ollama_reads_each_models_capabilities() -> None:
    def show(req: httpx.Request) -> dict[str, Any]:
        name = json.loads(req.content)['model']
        if name == 'llama3.3:70b':
            return {'capabilities': ['completion', 'tools'], 'model_info': {'llama.context_length': 131072}}
        if name == 'nomic-embed-text:latest':
            return {'capabilities': ['embedding'], 'model_info': {'nomic-bert.context_length': 2048}}
        return {}  # an older Ollama: no capabilities field

    client, _ = mock_client(
        {
            'GET http://ollama.lan:11434/api/tags': {
                'models': [{'name': 'llama3.3:70b'}, {'name': 'nomic-embed-text:latest'}, {'name': 'old:1b'}]
            },
            'POST http://ollama.lan:11434/api/show': show,
        }
    )
    models = {m.model_id: m for m in await providers.fetch_models(client, 'ollama', 'http://ollama.lan:11434', None)}
    assert models['llama3.3:70b'].tool_support == 'yes' and models['llama3.3:70b'].context_window == 131072
    assert models['nomic-embed-text:latest'].tool_support == 'no' and models['old:1b'].tool_support == 'unknown'


async def test_a_provider_that_refuses_or_is_down_says_so() -> None:
    client, _ = mock_client({'GET https://api.anthropic.com/v1/models': httpx.Response(401, json={'error': 'bad key'})})
    with pytest.raises(providers.ProviderError, match='refused the key'):
        await providers.fetch_models(client, 'anthropic', None, 'wrong')

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError('connection refused')

    with pytest.raises(providers.ProviderError, match='could not be reached'):
        await providers.fetch_models(httpx.AsyncClient(transport=httpx.MockTransport(down)), 'ollama', 'http://nowhere:11434', None)
    with pytest.raises(providers.ProviderError, match='needs an address'):
        providers.clean_base_url('ollama', '  ')
    with pytest.raises(providers.ProviderError, match='http\\(s\\)'):
        providers.clean_base_url('openai_compatible', 'ftp://x')
    assert providers.clean_base_url('ollama', 'http://h:11434/') == 'http://h:11434'


async def test_refreshing_keeps_decisions_marks_vanished_models_and_never_deletes(pool: AsyncConnectionPool) -> None:
    store = DbSecretStore(pool, KEY)
    await store.put('secret://refresh-test', 'key')
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                "insert into model_provider (kind, name, key_handle) values ('openai', 'refresh', 'secret://refresh-test') returning id::text"  # noqa: E501
            )
        ).fetchone()
    assert row is not None
    pid = row[0]
    first = {'data': [{'id': 'gpt-4.1'}, {'id': 'gpt-4o-mini'}]}
    client, _ = mock_client({'GET https://api.openai.com/v1/models': first})
    assert await providers.refresh_provider(pool, store, client, pid) == 2
    async with pool.connection() as conn:  # the admin allowed one and a test call settled it
        await conn.execute(
            "update provider_model set allowed_ask = true, tool_support = 'yes', tool_support_via = 'test' where provider_id::text = %s and model_id = 'gpt-4.1'",  # noqa: E501
            [pid],
        )
    client, _ = mock_client({'GET https://api.openai.com/v1/models': {'data': [{'id': 'gpt-4.1'}]}})  # gpt-4o-mini is gone
    await providers.refresh_provider(pool, store, client, pid)
    async with pool.connection() as conn:
        rows = {
            r[0]: r[1:]
            for r in await (
                await conn.execute(
                    'select model_id, available, allowed_ask, tool_support, tool_support_via from provider_model where provider_id::text = %s',  # noqa: E501
                    [pid],
                )
            ).fetchall()
        }
    assert rows['gpt-4.1'] == (True, True, 'yes', 'test') and rows['gpt-4o-mini'][0] is False

    client, _ = mock_client({'GET https://api.openai.com/v1/models': httpx.Response(500, text='boom')})
    with pytest.raises(providers.ProviderError):
        await providers.refresh_provider(pool, store, client, pid)
    async with pool.connection() as conn:
        err = await (
            await conn.execute('select fetch_error, fetched_at is not null from model_provider where id::text = %s', [pid])
        ).fetchone()
    assert err is not None and 'answered 500' in err[0] and err[1] is True  # the old list stays; the error is shown


async def test_the_tool_test_call() -> None:
    async def calls(messages: list[Any], info: AgentInfo) -> Any:
        if len(messages) == 1:
            yield {0: DeltaToolCall(name='ping', json_args='{}')}
        else:
            yield 'done'

    async def chats(messages: list[Any], info: AgentInfo) -> Any:
        yield 'I cannot call tools.'

    async def breaks(messages: list[Any], info: AgentInfo) -> Any:
        raise RuntimeError('400 this model does not support tools')
        yield ''  # pragma: no cover

    assert await providers.test_tool_support(FunctionModel(stream_function=calls)) is True
    assert await providers.test_tool_support(FunctionModel(stream_function=chats)) is False
    with pytest.raises(providers.ProviderError, match='does not support tools'):
        await providers.test_tool_support(FunctionModel(stream_function=breaks))


# ---- the catalog: what the model may learn about a dataset -------------------------------------------------------------------


@pytest.fixture(scope='module')
async def loaded(pool: AsyncConnectionPool) -> list[tuple[str, str, str, str, str, str]]:
    """A made-up enrollment dataset (120 rows) in raw and analytics, with identifiers, emails and free text that must never be shown."""
    people = []
    for i in range(120):
        program = (
            'BSME'
            if i < 48
            else 'BSCE'
            if i < 88
            else 'MSDS'
            if i < 91
            else 'PHD1'
            if i < 93
            else 'SECRET-PROGRAM-FOR-ONE'
            if i < 94
            else 'BSEE'
        )
        people.append(
            (
                f'{100000000 + i * 7919}',
                f'student{i}@example.edu',
                program,
                f'Left a long personal note number {i} for the advisor',
                f'remark {i % 60}',
                '2026-08-24',
            )
        )
    async with pool.connection() as conn:
        await conn.execute('create schema if not exists raw; create schema if not exists analytics')
        await conn.execute('drop table if exists raw.registrar; drop table if exists analytics.enrollment')
        await conn.execute(
            """create table raw.registrar (student_id text, email text, program text, advisor_note text, remark text, term_start text,
                 _bi_file_sha256 text, _bi_file_name text, _bi_sheet text, _bi_as_of date, _bi_loaded_at timestamptz, _bi_row bigint,
                 _bi_sync_id text, _bi_layout text, _dlt_id text)"""
        )
        await conn.execute(
            'create table analytics.enrollment (student_id text, program text, term_start date, credits integer, as_of date)'
        )
        for i, (sid, email, program, note, remark, start) in enumerate(people):
            await conn.execute(
                """insert into raw.registrar values (%s, %s, %s, %s, %s, %s, 'abc123', 'jdoe-private.xlsx', null, '2026-10-20', now(), %s,
                   's', 'l', 'd')""",
                [sid, email, program, note, remark, start, i + 2],
            )
            await conn.execute(
                'insert into analytics.enrollment values (%s, %s, %s, %s, %s)', [sid, program, start, 12 + i % 7, '2026-10-20']
            )
        await conn.execute("delete from source where name = 'Registrar'")
        source = await (
            await conn.execute(
                "insert into source (name, slug, type, state) values ('Registrar', 'registrar', 'file', 'live') returning id"
            )
        ).fetchone()
        assert source is not None
        stream = await (
            await conn.execute(
                """insert into source_stream (source_id, name, raw_table, dataset) values (%s, 'files', 'registrar', 'enrollment')
                   returning id""",
                [source[0]],
            )
        ).fetchone()
        assert stream is not None
        await conn.execute(
            """insert into sync (source_id, stream_id, as_of, status, finished_at) values (%s, %s, '2026-10-20', 'loaded', now())""",
            [source[0], stream[0]],
        )
    return people


async def test_a_profile_has_shapes_and_counts_but_no_row_and_no_identifier(
    pool: AsyncConnectionPool, loaded: list[tuple[str, ...]]
) -> None:
    profile = await catalog.describe_dataset(pool, 'registrar', threshold=5)  # a source's raw table
    typed_profile = await catalog.describe_dataset(pool, 'enrollment', threshold=5)  # the dataset built from it
    text = json.dumps([profile, typed_profile], default=str)
    for sid, email, _program, note, remark, _ in loaded:
        assert sid not in text and email not in text and note not in text and remark not in text  # no identifier, email or free text
    assert (
        'jdoe-private' not in text and 'SECRET-PROGRAM-FOR-ONE' not in text and 'PHD1' not in text and 'MSDS' not in text
    )  # rare values: not named
    assert profile['source'] == 'Registrar' and profile['feeds'] == 'enrollment' and typed_profile['sources'] == ['Registrar']

    raw = {c['name']: c for c in profile['tables']['raw']['columns']}
    assert profile['tables']['raw']['rows'] == 120 and '_dlt_id' not in raw
    assert raw['student_id']['kind'] == 'identifier' and raw['student_id']['distinct'] == 120
    assert raw['student_id']['patterns'] == [{'pattern': '999999999', 'rows': 120}]  # the shape of the ids, not an id
    assert raw['email']['kind'] == 'personal' and 'values' not in raw['email']
    assert (
        raw['advisor_note']['kind'] == 'identifier' and 'values' not in raw['advisor_note']
    )  # unique on every row: treated as an identifier
    assert (
        raw['remark']['kind'] == 'text' and raw['remark']['distinct'] == 60 and 'values' not in raw['remark']
    )  # many distinct values: a shape only
    assert raw['_bi_file_name']['kind'] == 'metadata' and 'values' not in raw['_bi_file_name']
    assert raw['program']['kind'] == 'category'
    assert raw['program']['values'] == [{'value': 'BSME', 'rows': 48}, {'value': 'BSCE', 'rows': 40}, {'value': 'BSEE', 'rows': 26}]
    assert raw['program']['other_rows'] == 6  # MSDS 3, PHD1 2, one more: counted, never named
    assert raw['term_start']['kind'] == 'date' and raw['term_start']['min'] == '2026-08-24'  # dates written as text are dates

    typed = {c['name']: c for c in typed_profile['tables']['analytics']['columns']}
    assert typed['term_start']['kind'] == 'date' and typed['term_start']['min'] == typed['term_start']['max'] == '2026-08-24'
    assert typed['credits']['kind'] == 'number' and (typed['credits']['min'], typed['credits']['max']) == (12.0, 18.0)
    assert 'min' not in typed['student_id']  # an identifier has no range: a minimum is a real value


async def test_listing_datasets_and_asking_about_an_unknown_one(pool: AsyncConnectionPool, loaded: list[tuple[str, ...]]) -> None:
    listing = {d['dataset']: d for d in await catalog.list_datasets(pool)}
    assert listing['enrollment']['tables'] == {'analytics': {'rows': 120}} and listing['enrollment']['sources'] == ['Registrar']
    assert listing['registrar']['kind'] == 'source' and listing['registrar']['tables'] == {'raw': {'rows': 120}}
    assert listing['registrar']['last_load']['as_of'] == '2026-10-20' and listing['registrar']['last_load']['syncs'] == 1
    with pytest.raises(catalog.CatalogError, match='unknown dataset'):
        await catalog.describe_dataset(pool, 'payroll; drop table raw.registrar', 5)
    assert 'student_id' not in json.dumps(listing, default=str)  # a listing has no columns at all


async def test_a_dataset_nothing_is_loaded_for_says_so(pool: AsyncConnectionPool, loaded: list[tuple[str, ...]]) -> None:
    async with pool.connection() as conn:
        await conn.execute('drop table raw.registrar; drop table analytics.enrollment')
    assert (await catalog.describe_dataset(pool, 'enrollment', 5))['note'] == 'nothing has been loaded for this dataset yet'


async def test_unused_import_guard() -> None:
    assert accounts  # the users are made in the routes tests
