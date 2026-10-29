"""The app's API under /app/api (ROADMAP-009), for the web app in web/: signing in, Connect data (bi.connect.routes), the governed
members and chart data.

Sessions: an HttpOnly, SameSite=Strict cookie. Every request that changes something must also carry `X-BI-App: 1`, which another
site cannot send without the BI's consent (no CORS is allowed), so a forged form or link does nothing.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from . import accounts, definitions, knowledge, mapping, organization, tools
from .accounts import User
from .agent.routes import AgentContext, create_agent_router
from .agent.secrets import SecretStore
from .agent.suppress import count_measures, suppress_rows
from .charts import ChartDefinition
from .connect.files import Storage
from .connect.routes import create_connect_router
from .cube import CubeClient, CubeError
from .log import log
from .mcp.routes import create_tokens_router

COOKIE = 'bi_session'
# Cube failed (not a missing table: that is no data). 424 rather than 502: a proxy in front (Easypanel's) replaces a 502, 503 or 504
# with its own "service is not reachable" page, which hides the reason from the page and reads like an outage.
CUBE_FAILED = 424
CSRF_HEADER = 'x-bi-app'


@dataclass
class AppContext:
    pool: AsyncConnectionPool
    storage: Storage
    enqueue_load: Callable[[str], Awaitable[None]]
    cube: CubeClient | None
    cookie_secure: bool = True
    agent: AgentContext | None = None
    """The agent's chat and admin routes (ROADMAP-003); None leaves them out."""
    public_url: str | None = None
    """The app's own address (PUBLIC_URL), shown with personal access tokens as the MCP server's base."""
    throttle: accounts.Throttle = field(default_factory=accounts.Throttle)
    """How many failed sign-ins refuse the next (TASK-010)."""
    enqueue_setup: Callable[[str], Awaitable[None]] | None = None
    """Asks the setup agent about a sync waiting for review (docs/setup-agent-spec.md)."""
    secrets: SecretStore | None = None
    """The secret store (DEC-020): where an API source's credential is kept."""
    proxy_hops: int = 0
    """Proxies in front of the app that append the client's address to X-Forwarded-For (0: the connection's own address is the client)."""


def client_ip(request: Request, hops: int) -> str:
    """The client's address: the connection's own, or with `hops` trusted proxies in front, the address the first of them saw.
    X-Forwarded-For is only trusted for as many entries as the operator says proxies append (a client can add more to the front)."""
    if hops > 0:
        parts = [p.strip() for p in request.headers.get('x-forwarded-for', '').split(',') if p.strip()]
        if len(parts) >= hops:
            return parts[-hops][:64]
    return request.client.host if request.client else 'unknown'


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


class LanguageChoice(BaseModel):
    language: str | None


class SignIn(BaseModel):
    email: str
    password: str


def create_router(ctx: AppContext) -> APIRouter:
    router = APIRouter(prefix='/app/api')

    async def current_user(request: Request) -> User:
        if request.method not in ('GET', 'HEAD') and request.headers.get(CSRF_HEADER) != '1':
            raise HTTPException(403, 'missing the X-BI-App header')
        user = await accounts.session_user(ctx.pool, request.cookies.get(COOKIE))
        if user is None:
            raise HTTPException(401, 'sign in')
        return user

    Signed = Annotated[User, Depends(current_user)]

    def cube() -> CubeClient:
        if ctx.cube is None:
            raise HTTPException(503, 'Cube is not configured (CUBE_API_URL, CUBE_API_SECRET)')
        return ctx.cube

    @router.post('/session')
    async def sign_in(body: SignIn, request: Request, response: Response) -> dict[str, Any]:
        if request.headers.get(CSRF_HEADER) != '1':
            raise HTTPException(403, 'missing the X-BI-App header')
        ip = client_ip(request, ctx.proxy_hops)
        wait = await accounts.blocked_for(ctx.pool, body.email, ip, ctx.throttle)
        if wait is not None:  # before any password work: refused attempts cost nothing and learn nothing
            log('warning', 'sign-in throttled', email=body.email[:200], ip=ip, retry_after=wait)
            raise HTTPException(
                429,
                f'Too many failed sign-in attempts. Try again in {max(1, round(wait / 60))} minutes.',
                headers={'Retry-After': str(wait)},
            )
        signed = await accounts.sign_in(ctx.pool, body.email, body.password)
        if signed is None:
            await accounts.record_failure(ctx.pool, body.email, ip)
            log('info', 'sign-in refused', email=body.email[:200], ip=ip)
            raise HTTPException(401, 'wrong email or password')
        await accounts.clear_failures(ctx.pool, body.email)
        user, token = signed
        response.set_cookie(
            COOKIE, token, max_age=accounts.SESSION_HOURS * 3600, httponly=True, secure=ctx.cookie_secure, samesite='strict', path='/'
        )
        return {'user': user.__dict__}

    @router.delete('/session', status_code=204)
    async def sign_out(request: Request, response: Response, user: Signed) -> None:
        await accounts.sign_out(ctx.pool, request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path='/', secure=ctx.cookie_secure, httponly=True, samesite='strict')

    @router.post('/password', status_code=204)
    async def change_password(body: ChangePassword, request: Request, user: Signed) -> None:
        if request.headers.get(CSRF_HEADER) != '1':
            raise HTTPException(403, 'missing the X-BI-App header')
        ip = client_ip(request, ctx.proxy_hops)
        wait = await accounts.blocked_for(ctx.pool, user.email, ip, ctx.throttle)  # a stolen session cannot guess the password either
        if wait is not None:
            raise HTTPException(429, 'Too many failed attempts. Try again later.', headers={'Retry-After': str(wait)})
        try:
            await accounts.change_password(ctx.pool, user.id, body.current_password, body.new_password, request.cookies.get(COOKIE))
        except accounts.AccountError as e:
            if 'current password is wrong' in str(e):
                await accounts.record_failure(ctx.pool, user.email, ip)
                raise HTTPException(403, str(e)) from e
            raise HTTPException(422, str(e)) from e
        await accounts.clear_failures(ctx.pool, user.email)
        log('info', 'password changed', user=user.id)

    @router.get('/me')
    async def me(user: Signed) -> dict[str, Any]:
        org = await organization.get(ctx.pool)
        return {
            'user': user.__dict__,
            'datasets': await mapping.installed_datasets(ctx.pool),
            'organization': org,
            'language': await organization.user_language(ctx.pool, user.id),
            'locale': await organization.locale_for(ctx.pool, user.id),
        }

    @router.get('/public/branding')
    async def branding() -> dict[str, Any]:
        """The only read without signing in (the sign-in page): the organization's name, accent colour and languages."""
        org = await organization.get(ctx.pool)
        return {k: org[k] for k in ('name', 'name_secondary', 'secondary_language', 'default_locale', 'accent_color')}

    @router.get('/languages')
    async def languages(user: Signed) -> dict[str, Any]:
        return {'languages': organization.languages_json()}

    @router.get('/templates')
    async def templates(user: Signed) -> dict[str, Any]:
        return {'templates': organization.templates_json()}

    @router.put('/organization')
    async def update_organization(body: organization.OrganizationPatch, user: Signed) -> dict[str, Any]:
        if not user.is_admin:
            raise HTTPException(403, 'only an admin changes the organization')
        try:
            org = await organization.update(ctx.pool, body, user.id)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        log('info', 'organization changed', user=user.id, fields=sorted(body.model_dump(exclude_unset=True)))
        return {'organization': org}

    @router.get('/model')
    async def model(user: Signed) -> dict[str, Any]:
        """What the organization reports on: every subject, entity and event, current version and draft (docs/data-model-spec.md)."""
        return {'definitions': await definitions.listing(ctx.pool)}

    @router.put('/model/{kind}/{name}')
    async def draft_definition(kind: definitions.Kind, name: str, body: dict[str, Any], user: Signed) -> dict[str, Any]:
        subject = name if kind == 'subject' else body.get('subject')
        if not user.is_admin and not await definitions.is_steward(ctx.pool, str(subject), user.email):
            raise HTTPException(403, "only an admin or the subject's steward changes what is defined in it")
        try:
            version = await definitions.save_draft(ctx.pool, kind, name, body, user.id)
        except definitions.DefinitionError as e:
            raise HTTPException(422, str(e)) from e
        log('info', 'definition drafted', kind=kind, name=name, version=version, user=user.id)
        return {'version': version, 'status': 'draft'}

    @router.get('/model/{kind}/{name}/changes')
    async def definition_changes(kind: definitions.Kind, name: str, user: Signed) -> dict[str, Any]:
        try:
            return await definitions.changes(ctx.pool, kind, name)
        except definitions.DefinitionError as e:
            raise HTTPException(404, str(e)) from e

    @router.get('/model/stewards')
    async def stewards(user: Signed) -> dict[str, Any]:
        """Who may be named a subject's steward: the BI's accounts (names and emails only)."""
        async with ctx.pool.connection() as conn:
            rows = await (await conn.execute('select name, email from app_user order by name')).fetchall()
        return {'people': [{'name': n, 'email': e} for n, e in rows]}

    @router.post('/model/{kind}/{name}/approve')
    async def approve_definition(kind: definitions.Kind, name: str, user: Signed) -> dict[str, Any]:
        if not await definitions.may_approve(ctx.pool, kind, name, user.email, user.is_admin):
            raise HTTPException(403, "only an admin or the subject's steward approves it")
        try:
            version = await definitions.approve(ctx.pool, kind, name, user.id)
        except definitions.DefinitionError as e:
            raise HTTPException(409, str(e)) from e
        log('info', 'definition approved', kind=kind, name=name, version=version, user=user.id)
        return {'version': version, 'status': 'approved'}

    @router.put('/me/language', status_code=204)
    async def my_language(body: LanguageChoice, user: Signed) -> None:
        try:
            await organization.set_user_language(ctx.pool, user.id, body.language)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @router.get('/members')
    async def members(user: Signed, client: Annotated[CubeClient, Depends(cube)]) -> dict[str, Any]:
        try:
            return {'members': await client.meta()}
        except CubeError as e:
            raise HTTPException(CUBE_FAILED, str(e)) from e

    @router.get('/knowledge')
    async def knowledge_page(user: Signed, client: Annotated[CubeClient, Depends(cube)], q: str = '') -> dict[str, Any]:
        """The Metrics page: every governed member with its words in each language; `q` searches them (docs/context-spec.md section 4)."""
        try:
            members, words = await client.meta(), await client.words()
        except CubeError as e:
            raise HTTPException(CUBE_FAILED, str(e)) from e
        if q.strip():
            return {**knowledge.search(members, words, q), 'instructions': words['instructions']}
        return {'members': [knowledge.brief(m) for m in members], 'glossary': words['glossary'], 'instructions': words['instructions']}

    async def chart_rows(chart: ChartDefinition, client: CubeClient) -> list[dict[str, Any]]:
        try:
            return await tools.chart_rows(client, chart)
        except tools.ToolError as e:
            raise HTTPException(422, str(e)) from e
        except CubeError as e:
            raise HTTPException(CUBE_FAILED, str(e)) from e

    @router.post('/charts/data')
    async def chart_data(chart: ChartDefinition, user: Signed, client: Annotated[CubeClient, Depends(cube)]) -> dict[str, Any]:
        return {'rows': await chart_rows(chart, client)}

    if ctx.agent is not None:
        threshold = ctx.agent.suppression_threshold

        @router.get('/drafts/{draft_id}/data')
        async def draft_data(draft_id: str, user: Signed, client: Annotated[CubeClient, Depends(cube)]) -> dict[str, Any]:
            """The rows of a draft chart the agent proposed, with small counts hidden as in the agent's own answers (DEC-017): the chat
            shows nothing the model was not allowed to see. Only its owner can read it."""
            async with ctx.pool.connection() as conn:
                row = await (
                    await conn.execute('select definition from draft where id::text = %s and owner_id = %s', [draft_id, user.id])
                ).fetchone()
            if row is None:
                raise HTTPException(404, 'no such draft')
            chart = ChartDefinition.model_validate(row[0])
            rows = await chart_rows(chart, client)
            try:
                counts = count_measures(await client.meta())
            except CubeError as e:
                raise HTTPException(CUBE_FAILED, str(e)) from e
            shown, hidden = suppress_rows(rows, chart.query.measures, counts, threshold)
            return {'rows': shown, 'suppressed_cells': hidden}

    if ctx.agent is not None:
        router.include_router(create_agent_router(ctx.agent, current_user))
    router.include_router(create_tokens_router(ctx.pool, current_user, ctx.public_url))
    profile_threshold = ctx.agent.suppression_threshold if ctx.agent is not None else 5
    router.include_router(
        create_connect_router(ctx.pool, ctx.storage, ctx.enqueue_load, ctx.enqueue_setup, current_user, ctx.secrets, profile_threshold)
    )
    return router
