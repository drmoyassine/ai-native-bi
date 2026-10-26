"""The five model providers (DEC-016): fetching each one's model list, connecting Pydantic AI to a chosen model, and the test call that
settles whether a model can call tools when its provider's list does not say. Lists are fetched with plain HTTP (they are simple REST
calls); chat goes through Pydantic AI and each provider's own SDK."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from psycopg_pool import AsyncConnectionPool
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.usage import UsageLimits

from .secrets import SecretError, SecretStore

Kind = Literal['anthropic', 'openai', 'openai_compatible', 'openrouter', 'ollama']
KINDS: tuple[Kind, ...] = ('anthropic', 'openai', 'openai_compatible', 'openrouter', 'ollama')
ToolSupport = Literal['yes', 'no', 'unknown']
OPENAI_BASE = 'https://api.openai.com/v1'
ANTHROPIC_BASE = 'https://api.anthropic.com'
OPENROUTER_BASE = 'https://openrouter.ai/api/v1'
NEEDS_BASE_URL = {'openai_compatible', 'ollama'}


class ProviderError(RuntimeError):
    """A provider could not be reached or refused the request; the message is shown to the admin."""


@dataclass(frozen=True)
class ListedModel:
    model_id: str
    name: str | None = None
    context_window: int | None = None
    output_limit: int | None = None
    price_in: float | None = None  # USD per million tokens
    price_out: float | None = None
    tool_support: ToolSupport = 'unknown'


def clean_base_url(kind: str, base_url: str | None) -> str | None:
    """The address as stored: http(s), no trailing slash; required where the provider has no fixed address."""
    if not base_url or not base_url.strip():
        if kind in NEEDS_BASE_URL:
            raise ProviderError(f'a {kind.replace("_", "-")} provider needs an address (base URL)')
        return None
    url = base_url.strip().rstrip('/')
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise ProviderError('the address must be an http(s) URL')
    return url


def data_path(kind: str, base_url: str | None) -> str:
    """Where a conversation's data goes on this route, shown beside each model (docs/agent-spec.md section 3)."""
    return {
        'anthropic': 'Anthropic, under its terms',
        'openai': 'OpenAI, under its terms',
        'openai_compatible': f"The server at {base_url}: the institution's own servers if it runs there, otherwise a third party",
        'openrouter': 'OpenRouter and the upstream provider it routes to',
        'ollama': f"The Ollama server at {base_url}, normally the institution's own: nothing leaves",
    }[kind]


# ---- Fetching each provider's model list -------------------------------------------------------------------------------------


async def _get_json(client: httpx.AsyncClient, url: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> Any:
    try:
        res = await client.get(url, headers=headers, params=params, timeout=30)
    except httpx.HTTPError as e:
        raise ProviderError(f'{url} could not be reached: {e}') from e
    if res.status_code in (401, 403):
        raise ProviderError(f'{urlsplit(url).netloc} refused the key ({res.status_code})')
    if res.status_code != 200:
        raise ProviderError(f'{urlsplit(url).netloc} answered {res.status_code}: {res.text[:200]}')
    try:
        return res.json()
    except ValueError as e:
        raise ProviderError(f'{urlsplit(url).netloc} did not answer JSON') from e


async def fetch_anthropic(client: httpx.AsyncClient, base_url: str | None, key: str) -> list[ListedModel]:
    base = (base_url or ANTHROPIC_BASE).rstrip('/')
    headers = {'x-api-key': key, 'anthropic-version': '2023-06-01'}
    models: list[ListedModel] = []
    after: str | None = None
    for _ in range(20):  # pages
        body = await _get_json(client, f'{base}/v1/models', headers, {'limit': 1000, **({'after_id': after} if after else {})})
        for m in body.get('data', []):
            models.append(
                ListedModel(
                    model_id=m['id'],
                    name=m.get('display_name'),
                    context_window=m.get('max_input_tokens'),
                    output_limit=m.get('max_tokens'),
                    tool_support='yes',  # every Claude model calls tools
                )
            )
        if not body.get('has_more') or not body.get('last_id'):
            break
        after = body['last_id']
    return models


_NOT_CHAT = re.compile(
    r'embed|whisper|tts|dall-e|image|audio|transcribe|moderation|realtime|davinci|babbage|search|sora|computer-use', re.I
)
_CHAT = re.compile(r'^(gpt-|o\d|chatgpt)', re.I)


async def fetch_openai(client: httpx.AsyncClient, base_url: str | None, key: str | None, *, compatible: bool = False) -> list[ListedModel]:
    """OpenAI's list has ids only: chat models are kept by name (OpenAI only), and tool support is settled by a test call."""
    base = (base_url or OPENAI_BASE).rstrip('/')
    headers = {'authorization': f'Bearer {key}'} if key else {}
    body = await _get_json(client, f'{base}/models', headers)
    out: list[ListedModel] = []
    for m in body.get('data', []):
        mid = m['id']
        if not compatible and (_NOT_CHAT.search(mid) or not _CHAT.match(mid)):
            continue
        out.append(ListedModel(model_id=mid, name=mid, context_window=m.get('context_window') or m.get('max_model_len')))
    return out


async def fetch_openrouter(client: httpx.AsyncClient, base_url: str | None, key: str | None) -> list[ListedModel]:
    base = (base_url or OPENROUTER_BASE).rstrip('/')
    body = await _get_json(client, f'{base}/models', {'authorization': f'Bearer {key}'} if key else {})
    out: list[ListedModel] = []
    for m in body.get('data', []):
        pricing = m.get('pricing') or {}

        def per_million(v: Any) -> float | None:
            try:
                return round(float(v) * 1_000_000, 6) if v not in (None, '') else None
            except (TypeError, ValueError):
                return None

        params = m.get('supported_parameters')
        out.append(
            ListedModel(
                model_id=m['id'],
                name=m.get('name'),
                context_window=m.get('context_length'),
                output_limit=(m.get('top_provider') or {}).get('max_completion_tokens'),
                price_in=per_million(pricing.get('prompt')),
                price_out=per_million(pricing.get('completion')),
                tool_support=('unknown' if params is None else 'yes' if 'tools' in params else 'no'),
            )
        )
    return out


async def fetch_ollama(client: httpx.AsyncClient, base_url: str, key: str | None) -> list[ListedModel]:
    base = base_url.rstrip('/')
    headers = {'authorization': f'Bearer {key}'} if key else {}
    tags = await _get_json(client, f'{base}/api/tags', headers)
    names = [m.get('model') or m.get('name') for m in tags.get('models', [])]
    gate = asyncio.Semaphore(8)

    async def show(name: str) -> ListedModel:
        async with gate:
            try:
                res = await client.post(f'{base}/api/show', json={'model': name}, headers=headers, timeout=30)
                info = res.json() if res.status_code == 200 else {}
            except (httpx.HTTPError, ValueError):
                info = {}
        caps = info.get('capabilities')
        ctx = next((v for k, v in (info.get('model_info') or {}).items() if k.endswith('.context_length')), None)
        return ListedModel(
            model_id=name, name=name, context_window=ctx, tool_support='unknown' if caps is None else 'yes' if 'tools' in caps else 'no'
        )

    return list(await asyncio.gather(*(show(n) for n in names if n)))


async def fetch_models(client: httpx.AsyncClient, kind: str, base_url: str | None, key: str | None) -> list[ListedModel]:
    if kind == 'anthropic':
        if not key:
            raise ProviderError('an Anthropic provider needs an API key')
        return await fetch_anthropic(client, base_url, key)
    if kind == 'openai':
        if not key:
            raise ProviderError('an OpenAI provider needs an API key')
        return await fetch_openai(client, base_url, key)
    if kind == 'openai_compatible':
        return await fetch_openai(client, base_url, key, compatible=True)
    if kind == 'openrouter':
        return await fetch_openrouter(client, base_url, key)
    if kind == 'ollama':
        return await fetch_ollama(client, base_url or '', key)
    raise ProviderError(f'unknown provider kind {kind}')


# ---- Connecting Pydantic AI --------------------------------------------------------------------------------------------------


def build_model(kind: str, model_id: str, base_url: str | None, key: str | None) -> Model:
    """The Pydantic AI model for a provider and a model id. Ollama and OpenAI-compatible servers need no key (a placeholder is sent)."""
    if kind == 'anthropic':
        return AnthropicModel(model_id, provider=AnthropicProvider(api_key=key, base_url=base_url))
    if kind == 'openai':
        return OpenAIChatModel(model_id, provider=OpenAIProvider(api_key=key, base_url=base_url))
    if kind == 'openai_compatible':
        return OpenAIChatModel(model_id, provider=OpenAIProvider(api_key=key or 'none', base_url=base_url))
    if kind == 'openrouter':
        return OpenRouterModel(model_id, provider=OpenRouterProvider(api_key=key))
    if kind == 'ollama':
        return OpenAIChatModel(model_id, provider=OllamaProvider(base_url=f'{(base_url or "").rstrip("/")}/v1', api_key=key or 'none'))
    raise ProviderError(f'unknown provider kind {kind}')


def model_settings(kind: str, mode: str, output_limit: int | None) -> dict[str, Any]:
    """Settings for a turn. `thinking` is Pydantic AI's provider-neutral reasoning level: it maps it per model and drops what a model
    does not support. Claude also gets prompt caching of the tools, the instructions and the growing conversation (DEC-015)."""
    settings: dict[str, Any] = {'thinking': 'high' if mode == 'build' else 'medium', 'parallel_tool_calls': True}
    if kind == 'anthropic':
        settings.update(
            max_tokens=min(64000, output_limit) if output_limit else 16000,
            anthropic_cache_tool_definitions=True,
            anthropic_cache_instructions=True,
            anthropic_cache_messages=True,
        )
    return settings


def usage_limits(mode: str) -> UsageLimits:
    """Per-turn limits. Input tokens add up across every request of a turn (each re-reads the history), so the bound that means
    something is output; the total only catches runaway loops."""
    if mode == 'build':
        return UsageLimits(request_limit=150, output_tokens_limit=128_000, total_tokens_limit=8_000_000)
    return UsageLimits(request_limit=30, output_tokens_limit=32_000, total_tokens_limit=2_000_000)


async def test_tool_support(model: Model) -> bool:
    """One short request with one tool: does the model call it? Settles tool support where a provider's list does not say."""
    called: list[bool] = []
    agent: Agent[None, str] = Agent(model, instructions='You must call the ping tool, then reply done.', retries=1)

    @agent.tool_plain
    def ping() -> str:
        """Call this once to check that tool calls work."""
        called.append(True)
        return 'pong'

    try:
        # Streamed, like every turn of the agent: the test exercises the path the agent will use.
        async with agent.iter('Call the ping tool.', usage_limits=UsageLimits(request_limit=3, output_tokens_limit=2000)) as run:
            async for node in run:
                if Agent.is_model_request_node(node):
                    async with node.stream(run.ctx) as stream:
                        async for _ in stream:
                            pass
    except Exception as e:  # the provider said no, or cannot do tools: both mean "not usable by the agent"
        raise ProviderError(f'the test call failed: {e}') from e
    return bool(called)


# ---- Keeping the model lists --------------------------------------------------------------------------------------------------


async def provider_key(pool: AsyncConnectionPool, secrets: SecretStore | None, provider_id: str) -> tuple[str, str | None, str | None]:
    """(kind, base_url, key) of a provider; the key is read from the secret store and never kept."""
    async with pool.connection() as conn:
        row = await (await conn.execute('select kind, base_url, key_handle from model_provider where id = %s', [provider_id])).fetchone()
    if row is None:
        raise ProviderError('no such provider')
    key: str | None = None
    if row[2]:
        if secrets is None:
            raise ProviderError('the secret store is not configured (BI_SECRETS_KEY)')
        try:
            key = await secrets.get(row[2])
        except SecretError as e:
            raise ProviderError(str(e)) from e
    return row[0], row[1], key


async def refresh_provider(pool: AsyncConnectionPool, secrets: SecretStore | None, client: httpx.AsyncClient, provider_id: str) -> int:
    """Fetches the provider's model list and keeps it: new models arrive disallowed, models gone from the list are marked unavailable
    (never deleted or replaced), what an admin or a test call decided is kept. Returns the number of models listed."""
    kind, base_url, key = await provider_key(pool, secrets, provider_id)
    try:
        listed = await fetch_models(client, kind, base_url, key)
    except ProviderError as e:
        async with pool.connection() as conn:
            await conn.execute('update model_provider set fetch_error = %s where id = %s', [str(e), provider_id])
        raise
    async with pool.connection() as conn:
        async with conn.transaction():
            for m in listed:
                await conn.execute(
                    """insert into provider_model (provider_id, model_id, name, context_window, output_limit, price_in, price_out,
                                                   tool_support, tool_support_via, fetched_at)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                       on conflict (provider_id, model_id) do update set
                         name = excluded.name, context_window = excluded.context_window, output_limit = excluded.output_limit,
                         price_in = excluded.price_in, price_out = excluded.price_out, available = true, fetched_at = now(),
                         tool_support = case when excluded.tool_support <> 'unknown' then excluded.tool_support
                                             else provider_model.tool_support end,
                         tool_support_via = case when excluded.tool_support <> 'unknown' then 'list'
                                                 else provider_model.tool_support_via end""",
                    [
                        provider_id,
                        m.model_id,
                        m.name,
                        m.context_window,
                        m.output_limit,
                        m.price_in,
                        m.price_out,
                        m.tool_support,
                        'list' if m.tool_support != 'unknown' else None,
                    ],
                )
            await conn.execute(
                'update provider_model set available = false where provider_id = %s and not (model_id = any(%s))',
                [provider_id, [m.model_id for m in listed]],
            )
            await conn.execute('update model_provider set fetched_at = now(), fetch_error = null where id = %s', [provider_id])
    return len(listed)


async def refresh_all(pool: AsyncConnectionPool, secrets: SecretStore | None, client: httpx.AsyncClient) -> dict[str, str]:
    """Every enabled provider (the worker does this every 6 hours); one provider failing does not stop the others."""
    async with pool.connection() as conn:
        ids = [r[0] for r in await (await conn.execute('select id::text from model_provider where enabled')).fetchall()]
    outcome: dict[str, str] = {}
    for pid in ids:
        try:
            outcome[pid] = f'{await refresh_provider(pool, secrets, client, pid)} models'
        except ProviderError as e:
            outcome[pid] = f'failed: {e}'
    return outcome
