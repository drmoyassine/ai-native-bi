"""The chat's and the admin's routes under /app/api (docs/agent-spec.md section 9). Same session cookie and X-BI-App rule as the rest of
the app (DEC-014); the admin routes need an admin account.

No `from __future__ import annotations` here: FastAPI has to evaluate the routes' annotations where `Signed` is defined."""

import datetime as dt
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

import httpx
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, StringConstraints
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import Model

from ..accounts import User
from ..log import log
from . import providers, store
from .providers import KINDS, ProviderError
from .render import render_messages
from .secrets import SecretStore

KEEPALIVE_SECONDS = 15
MAX_MESSAGE = 20_000


@dataclass
class AgentContext:
    pool: AsyncConnectionPool
    database_url: str
    secrets: SecretStore | None
    http: httpx.AsyncClient
    enqueue_turn: Callable[[str, str], Awaitable[None]]
    """(run_id, conversation_id): queues the turn; one at a time per conversation."""
    organization_monthly_tokens: int = 100_000_000
    person_monthly_tokens: int = 10_000_000
    suppression_threshold: int = 5
    build_model: Callable[[str, str, str | None, str | None], Model] = field(default=providers.build_model)


class NewConversation(BaseModel):
    mode: Literal['ask', 'build'] = 'ask'
    provider_id: str
    model_id: str


class NewMessage(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE)]


class ProviderIn(BaseModel):
    kind: Literal['anthropic', 'openai', 'openai_compatible', 'openrouter', 'ollama']
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    base_url: str | None = None
    api_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None


class ProviderPatch(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None
    base_url: str | None = None
    api_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None
    enabled: bool | None = None
    may_see_samples: bool | None = None


class ModelAllow(BaseModel):
    provider_id: str
    model_id: str
    allowed_ask: bool = False
    allowed_build: bool = False
    default_ask: bool = False
    default_build: bool = False


def sse(event: dict[str, Any]) -> str:
    return f'id: {event["id"]}\nevent: {event["type"]}\ndata: {json.dumps(event["payload"], default=str)}\n\n'


def month_start() -> dt.datetime:
    now = dt.datetime.now(dt.UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def tokens_used(pool: AsyncConnectionPool, owner_id: str | None = None) -> int:
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """select coalesce(sum(r.input_tokens + r.output_tokens), 0)
                   from agent_run r join conversation c on c.id = r.conversation_id
                   where r.created_at >= %s and (%s::uuid is null or c.owner_id = %s::uuid)""",
                [month_start(), owner_id, owner_id],
            )
        ).fetchone()
        setup = 0
        if owner_id is None:  # the setup agent's calls (Connect data) belong to the organization, not to a person
            found = await (
                await conn.execute(
                    'select coalesce(sum(input_tokens + output_tokens), 0) from setup_run where created_at >= %s', [month_start()]
                )
            ).fetchone()
            setup = int(found[0]) if found else 0
    return (int(row[0]) if row else 0) + setup


def create_agent_router(ctx: AgentContext, current_user: Callable[..., Awaitable[User]]) -> APIRouter:
    router = APIRouter()
    Signed = Annotated[User, Depends(current_user)]

    async def admin_user(user: Signed) -> User:
        if not user.is_admin:
            raise HTTPException(403, 'admins only')
        return user

    Admin = Annotated[User, Depends(admin_user)]

    async def owned(conversation_id: str, user: User) -> dict[str, Any]:
        async with ctx.pool.connection() as conn:
            row = await (
                await conn.execute(
                    """select c.id::text, c.mode, c.title, c.provider_id::text, c.model_id, c.created_at, p.name
                       from conversation c join model_provider p on p.id = c.provider_id
                       where c.id::text = %s and c.owner_id = %s and c.archived_at is null""",
                    [conversation_id, user.id],
                )
            ).fetchone()
        if row is None:
            raise HTTPException(404, 'no such conversation')
        return {
            'id': row[0],
            'mode': row[1],
            'title': row[2],
            'provider_id': row[3],
            'model_id': row[4],
            'created_at': row[5],
            'provider': row[6],
        }

    # ---- models and conversations ---------------------------------------------------------------------------------------------

    @router.get('/models')
    async def models(user: Signed, mode: Literal['ask', 'build'] = 'ask') -> dict[str, Any]:
        """The models the admin allows for this mode, grouped by provider, with each one's data path; the default is marked."""
        column = 'allowed_ask' if mode == 'ask' else 'allowed_build'
        default = 'default_ask' if mode == 'ask' else 'default_build'
        async with ctx.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    f"""select p.id::text, p.kind, p.name, p.base_url, m.model_id, m.name, m.context_window,
                               m.price_in, m.price_out, m.{default}
                        from provider_model m join model_provider p on p.id = m.provider_id
                        where m.{column} and m.available and p.enabled and m.tool_support = 'yes'
                        order by p.name, m.name nulls last, m.model_id"""  # noqa: S608
                )
            ).fetchall()
        groups: dict[str, dict[str, Any]] = {}
        for r in rows:
            g = groups.setdefault(
                r[0], {'provider_id': r[0], 'kind': r[1], 'provider': r[2], 'data_path': providers.data_path(r[1], r[3]), 'models': []}
            )
            g['models'].append(
                {'model_id': r[4], 'name': r[5] or r[4], 'context_window': r[6], 'price_in': r[7], 'price_out': r[8], 'default': bool(r[9])}
            )
        return {'mode': mode, 'providers': list(groups.values())}

    @router.get('/conversations')
    async def list_conversations(user: Signed) -> dict[str, Any]:
        async with ctx.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    """select c.id::text, c.title, c.mode, c.model_id, p.name, c.created_at from conversation c
                       join model_provider p on p.id = c.provider_id where c.owner_id = %s and c.archived_at is null
                       order by c.created_at desc limit 100""",
                    [user.id],
                )
            ).fetchall()
        return {
            'conversations': [
                {'id': r[0], 'title': r[1], 'mode': r[2], 'model_id': r[3], 'provider': r[4], 'created_at': r[5]} for r in rows
            ]
        }

    @router.post('/conversations', status_code=201)
    async def new_conversation(body: NewConversation, user: Signed) -> dict[str, Any]:
        if body.mode == 'build' and not user.is_admin:
            raise HTTPException(403, 'building is for admins for now')
        column = 'allowed_ask' if body.mode == 'ask' else 'allowed_build'
        async with ctx.pool.connection() as conn:
            ok = await (
                await conn.execute(
                    f"""select 1 from provider_model m join model_provider p on p.id = m.provider_id
                        where m.provider_id::text = %s and m.model_id = %s and m.{column} and m.available and p.enabled
                          and m.tool_support = 'yes'""",  # noqa: S608
                    [body.provider_id, body.model_id],
                )
            ).fetchone()
            if not ok:
                raise HTTPException(422, 'that model is not allowed for this mode')
            row = await (
                await conn.execute(
                    'insert into conversation (owner_id, mode, provider_id, model_id) values (%s, %s, %s, %s) returning id::text',
                    [user.id, body.mode, body.provider_id, body.model_id],
                )
            ).fetchone()
        assert row is not None
        return {'id': row[0]}

    @router.get('/conversations/{conversation_id}')
    async def get_conversation(conversation_id: str, user: Signed) -> dict[str, Any]:
        conv = await owned(conversation_id, user)
        messages = await store.read_messages(ctx.pool, conversation_id)
        async with ctx.pool.connection() as conn:
            last = await (
                await conn.execute('select coalesce(max(id), 0) from agent_event where conversation_id = %s', [conversation_id])
            ).fetchone()
        return {
            'conversation': conv,
            'items': render_messages(messages),
            'active_run': await store.active_run(ctx.pool, conversation_id),
            'last_event_id': last[0] if last else 0,
        }

    @router.post('/conversations/{conversation_id}/messages', status_code=202)
    async def post_message(conversation_id: str, body: NewMessage, user: Signed) -> dict[str, Any]:
        conv = await owned(conversation_id, user)
        if await store.active_run(ctx.pool, conversation_id):
            raise HTTPException(409, 'the assistant is still answering: wait for it, or stop it')
        for who, used, cap in (
            ('you', await tokens_used(ctx.pool, user.id), ctx.person_monthly_tokens),
            ('the organization', await tokens_used(ctx.pool), ctx.organization_monthly_tokens),
        ):
            if used >= cap:
                raise HTTPException(429, f'the monthly token budget of {who} is used up ({used:,} of {cap:,}); an admin can raise it')
        await store.append_message(ctx.pool, conversation_id, ModelRequest(parts=[UserPromptPart(content=body.text)]))
        async with ctx.pool.connection() as conn:
            run = await (
                await conn.execute('insert into agent_run (conversation_id) values (%s) returning id::text', [conversation_id])
            ).fetchone()
            if conv['title'] == 'New conversation':
                title = ' '.join(body.text.split())
                await conn.execute(
                    'update conversation set title = %s where id = %s', [title[:60] + ('…' if len(title) > 60 else ''), conversation_id]
                )
        assert run is not None
        async with ctx.pool.connection() as conn:  # the chat follows the turn from the last event so far
            last = await (
                await conn.execute('select coalesce(max(id), 0) from agent_event where conversation_id = %s', [conversation_id])
            ).fetchone()
        await ctx.enqueue_turn(run[0], conversation_id)
        return {'run_id': run[0], 'after': last[0] if last else 0}

    @router.get('/conversations/{conversation_id}/events')
    async def events(conversation_id: str, request: Request, user: Signed, after: int = 0) -> StreamingResponse:
        """Server-sent events of the conversation after an event id (also `Last-Event-ID`); ends when nothing is running and all is sent."""
        await owned(conversation_id, user)
        cursor = max(after, int(request.headers.get('last-event-id') or 0))

        async def stream() -> AsyncIterator[str]:
            nonlocal cursor
            async with await psycopg.AsyncConnection.connect(ctx.database_url, autocommit=True) as listener:
                await listener.execute(f'listen {store.EVENT_CHANNEL}')
                while True:
                    batch = await store.events_after(ctx.pool, conversation_id, cursor)
                    if not batch:
                        if await store.active_run(ctx.pool, conversation_id) is None:
                            batch = await store.events_after(ctx.pool, conversation_id, cursor)  # the last event may have just landed
                            if not batch:
                                break
                    for e in batch:
                        cursor = e['id']
                        yield sse(e)
                    if batch:
                        continue
                    woken = False
                    async for _ in listener.notifies(timeout=KEEPALIVE_SECONDS, stop_after=1):
                        woken = True
                    if not woken:
                        if await request.is_disconnected():
                            return
                        yield ': keepalive\n\n'
            yield 'event: end\ndata: {}\n\n'

        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    @router.post('/conversations/{conversation_id}/interrupt', status_code=202)
    async def interrupt(conversation_id: str, user: Signed) -> dict[str, bool]:
        await owned(conversation_id, user)
        async with ctx.pool.connection() as conn:
            cur = await conn.execute(
                "update agent_run set interrupt_requested = true where conversation_id = %s and status in ('queued', 'running')",
                [conversation_id],
            )
        return {'requested': cur.rowcount > 0}

    @router.get('/agent/usage')
    async def usage(user: Signed) -> dict[str, Any]:
        return {
            'person': {'used': await tokens_used(ctx.pool, user.id), 'cap': ctx.person_monthly_tokens},
            'organization': {'used': await tokens_used(ctx.pool), 'cap': ctx.organization_monthly_tokens},
            'month_start': month_start().date().isoformat(),
        }

    # ---- providers and models (admin) -----------------------------------------------------------------------------------------

    def need_secrets() -> SecretStore:
        if ctx.secrets is None:
            raise HTTPException(503, 'the secret store is not configured: set BI_SECRETS_KEY (python3 scripts/make_env.py)')
        return ctx.secrets

    def provider_json(r: tuple[Any, ...]) -> dict[str, Any]:
        return {
            'id': r[0], 'kind': r[1], 'name': r[2], 'base_url': r[3], 'has_key': r[4] is not None, 'enabled': r[5], 'fetched_at': r[6],
            'fetch_error': r[7], 'models': r[8], 'allowed': r[9], 'data_path': providers.data_path(r[1], r[3]), 'may_see_samples': r[10],
        }  # fmt: skip

    async def one_provider(provider_id: str) -> dict[str, Any]:
        async with ctx.pool.connection() as conn:
            r = await (
                await conn.execute(
                    """select p.id::text, p.kind, p.name, p.base_url, p.key_handle, p.enabled, p.fetched_at, p.fetch_error,
                              count(m.model_id) filter (where m.available),
                              count(m.model_id) filter (where m.allowed_ask or m.allowed_build), p.may_see_samples
                       from model_provider p left join provider_model m on m.provider_id = p.id where p.id::text = %s group by p.id""",
                    [provider_id],
                )
            ).fetchone()
        if r is None:
            raise HTTPException(404, 'no such provider')
        return provider_json(r)

    @router.get('/admin/providers')
    async def list_providers(admin: Admin) -> dict[str, Any]:
        async with ctx.pool.connection() as conn:
            ids = [r[0] for r in await (await conn.execute('select id::text from model_provider order by lower(name)')).fetchall()]
        return {'providers': [await one_provider(i) for i in ids], 'kinds': list(KINDS), 'secrets_configured': ctx.secrets is not None}

    async def refresh(provider_id: str) -> str | None:
        try:
            await providers.refresh_provider(ctx.pool, ctx.secrets, ctx.http, provider_id)
        except ProviderError as e:
            return str(e)
        return None

    @router.post('/admin/providers', status_code=201)
    async def add_provider(body: ProviderIn, admin: Admin) -> dict[str, Any]:
        try:
            base_url = providers.clean_base_url(body.kind, body.base_url)
        except ProviderError as e:
            raise HTTPException(422, str(e)) from e
        if body.api_key:
            need_secrets()
        if body.kind in ('anthropic', 'openai', 'openrouter') and not body.api_key:
            raise HTTPException(422, f'a {body.kind} provider needs an API key')
        async with ctx.pool.connection() as conn:
            if await (await conn.execute('select 1 from model_provider where lower(name) = lower(%s)', [body.name])).fetchone():
                raise HTTPException(409, f'there is already a provider called {body.name}')
            row = await (
                await conn.execute(
                    'insert into model_provider (kind, name, base_url) values (%s, %s, %s) returning id::text',
                    [body.kind, body.name, base_url],
                )
            ).fetchone()
            assert row is not None
            if body.api_key:
                handle = await need_secrets().put(f'secret://provider-{row[0]}', body.api_key, admin.id)
                await conn.execute('update model_provider set key_handle = %s where id = %s', [handle, row[0]])
        error = await refresh(row[0])
        return {'provider': await one_provider(row[0]), 'fetch_error': error}

    @router.put('/admin/providers/{provider_id}')
    async def change_provider(provider_id: str, body: ProviderPatch, admin: Admin) -> dict[str, Any]:
        current = await one_provider(provider_id)
        try:
            base_url = providers.clean_base_url(current['kind'], body.base_url) if body.base_url is not None else None
        except ProviderError as e:
            raise HTTPException(422, str(e)) from e
        if body.api_key:
            handle = await need_secrets().put(f'secret://provider-{provider_id}', body.api_key, admin.id)
            async with ctx.pool.connection() as conn:
                await conn.execute('update model_provider set key_handle = %s where id::text = %s', [handle, provider_id])
        async with ctx.pool.connection() as conn:
            await conn.execute(
                """update model_provider set name = coalesce(%s, name), base_url = coalesce(%s, base_url),
                                              enabled = coalesce(%s, enabled), may_see_samples = coalesce(%s, may_see_samples)
                   where id::text = %s""",
                [body.name, base_url, body.enabled, body.may_see_samples, provider_id],
            )
        if body.may_see_samples is not None and body.may_see_samples != current['may_see_samples']:
            log('info', 'provider sample rows switch', provider=provider_id, allowed=body.may_see_samples, admin=admin.id)
        error = await refresh(provider_id) if (body.api_key or body.base_url is not None) else None
        return {'provider': await one_provider(provider_id), 'fetch_error': error}

    @router.post('/admin/providers/{provider_id}/refresh')
    async def refresh_provider(provider_id: str, admin: Admin) -> dict[str, Any]:
        await one_provider(provider_id)
        error = await refresh(provider_id)
        return {'provider': await one_provider(provider_id), 'fetch_error': error}

    @router.get('/admin/providers/{provider_id}/models')
    async def provider_models(provider_id: str, admin: Admin) -> dict[str, Any]:
        await one_provider(provider_id)
        async with ctx.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    """select model_id, name, context_window, output_limit, price_in, price_out, tool_support, tool_support_via, available,
                              allowed_ask, allowed_build, default_ask, default_build
                       from provider_model where provider_id::text = %s order by available desc, coalesce(name, model_id)""",
                    [provider_id],
                )
            ).fetchall()
        keys = (
            *('model_id', 'name', 'context_window', 'output_limit', 'price_in', 'price_out', 'tool_support', 'tool_support_via'),
            *('available', 'allowed_ask', 'allowed_build', 'default_ask', 'default_build'),
        )
        return {'models': [dict(zip(keys, r, strict=True)) for r in rows]}

    @router.put('/admin/models')
    async def allow_model(body: ModelAllow, admin: Admin) -> dict[str, Any]:
        """Allows a model per mode and sets defaults. A model whose tool support is unknown is tested first (one short call)."""
        if (body.default_ask and not body.allowed_ask) or (body.default_build and not body.allowed_build):
            raise HTTPException(422, 'a default model must be allowed for that mode')
        async with ctx.pool.connection() as conn:
            row = await (
                await conn.execute(
                    'select tool_support, available from provider_model where provider_id::text = %s and model_id = %s',
                    [body.provider_id, body.model_id],
                )
            ).fetchone()
        if row is None:
            raise HTTPException(404, 'no such model')
        wants = body.allowed_ask or body.allowed_build
        if wants and not row[1]:
            raise HTTPException(422, 'that model is no longer listed by its provider')
        if wants and row[0] == 'unknown':
            kind, base_url, key = await providers.provider_key(ctx.pool, ctx.secrets, body.provider_id)
            try:
                supported = await providers.test_tool_support(ctx.build_model(kind, body.model_id, base_url, key))
            except ProviderError as e:
                raise HTTPException(422, str(e)) from e
            async with ctx.pool.connection() as conn:
                await conn.execute(
                    "update provider_model set tool_support = %s, tool_support_via = 'test' where provider_id::text = %s and model_id = %s",
                    ['yes' if supported else 'no', body.provider_id, body.model_id],
                )
            row = ('yes' if supported else 'no', True)
        if wants and row[0] != 'yes':
            raise HTTPException(422, 'that model cannot call tools, which the agent needs')
        async with ctx.pool.connection() as conn, conn.transaction():
            if body.default_ask:
                await conn.execute('update provider_model set default_ask = false where default_ask')
            if body.default_build:
                await conn.execute('update provider_model set default_build = false where default_build')
            await conn.execute(
                """update provider_model set allowed_ask = %s, allowed_build = %s,
                       default_ask = case when %s then true when not %s then false else default_ask end,
                       default_build = case when %s then true when not %s then false else default_build end
                   where provider_id::text = %s and model_id = %s""",
                [
                    body.allowed_ask,
                    body.allowed_build,
                    body.default_ask,
                    body.allowed_ask,
                    body.default_build,
                    body.allowed_build,
                    body.provider_id,
                    body.model_id,
                ],
            )
        return await provider_models(body.provider_id, admin)

    return router
