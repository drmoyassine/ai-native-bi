"""The app's API under /app/api (ROADMAP-009), for the web app in web/: signing in, uploads, the governed members and chart data.

Sessions: an HttpOnly, SameSite=Strict cookie. Every request that changes something must also carry `X-BI-App: 1`, which another
site cannot send without the BI's consent (no CORS is allowed), so a forged form or link does nothing.
"""

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from . import accounts, mapping, tools, uploads
from .accounts import User
from .agent.catalog import datasets
from .agent.routes import AgentContext, create_agent_router
from .agent.suppress import count_measures, suppress_rows
from .charts import ChartDefinition
from .cube import CubeClient, CubeError
from .ingest import DATASET
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
    storage: uploads.Storage
    enqueue_load: Callable[[str], Awaitable[None]]
    cube: CubeClient | None
    cookie_secure: bool = True
    agent: AgentContext | None = None
    """The agent's chat and admin routes (ROADMAP-003); None leaves them out."""
    public_url: str | None = None
    """The app's own address (PUBLIC_URL), shown with personal access tokens as the MCP server's base."""
    throttle: accounts.Throttle = field(default_factory=accounts.Throttle)
    """How many failed sign-ins refuse the next (TASK-010)."""
    enqueue_rebuild: Callable[[str], Awaitable[None]] | None = None
    """Rebuilds a dataset's analytics after its column mapping is approved."""
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


class MappingBody(BaseModel):
    mapping: dict[str, str | None]


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
        return {'user': user.__dict__, 'datasets': datasets()}

    @router.post('/uploads', status_code=202)
    async def upload(
        user: Signed,
        file: Annotated[UploadFile, File()],
        dataset: Annotated[str, Form()],
        as_of: Annotated[dt.date, Form(alias='asOf')],
        sheet: Annotated[str | None, Form()] = None,
    ) -> dict[str, str]:
        if not DATASET.match(dataset) or dataset not in datasets():
            raise HTTPException(422, f'unknown dataset "{dataset}" (known: {", ".join(datasets())})')
        if as_of > dt.date.today():
            raise HTTPException(422, 'the as-of date is in the future')
        try:
            id = await uploads.receive(
                ctx.pool,
                ctx.storage,
                user_id=user.id,
                dataset=dataset,
                as_of=as_of,
                sheet=(sheet or '').strip() or None,
                file_name=file.filename or '',
                source=file.file,
            )
        except uploads.UploadError as e:
            raise HTTPException(422, str(e)) from e
        await ctx.enqueue_load(id)
        log('info', 'upload received', id=id, dataset=dataset, user=user.id)
        return {'id': id}

    @router.get('/uploads')
    async def list_uploads(user: Signed) -> dict[str, Any]:
        return {'uploads': await uploads.recent(ctx.pool)}

    @router.get('/datasets/{dataset}/mapping')
    async def get_mapping(dataset: str, user: Signed) -> dict[str, Any]:
        if dataset not in datasets():
            raise HTTPException(404, f'unknown dataset "{dataset}"')
        columns = await mapping.raw_columns(ctx.pool, dataset)
        kept = await mapping.stored(ctx.pool, dataset)
        proposed, _ = mapping.propose(dataset, columns)
        return {
            'dataset': dataset,
            'parts': [{'name': f.name, 'required': f.required} for f in mapping.fields(dataset)],
            'columns': columns,
            'mapping': kept['mapping'] if kept else proposed,
            'status': kept['status'] if kept else None,
            'error': kept['error'] if kept else None,
        }

    @router.put('/datasets/{dataset}/mapping')
    async def put_mapping(dataset: str, body: MappingBody, user: Signed) -> dict[str, str]:
        if dataset not in datasets():
            raise HTTPException(404, f'unknown dataset "{dataset}"')
        try:
            mapping.check(dataset, body.mapping, await mapping.raw_columns(ctx.pool, dataset))
        except mapping.MappingError as e:
            raise HTTPException(422, str(e)) from e
        await mapping.save(ctx.pool, dataset, body.mapping, 'approved', f'approved by {user.email}', user.id)
        if ctx.enqueue_rebuild is not None:
            await ctx.enqueue_rebuild(dataset)
        log('info', 'mapping approved', dataset=dataset, user=user.id)
        return {'status': 'approved'}

    @router.get('/members')
    async def members(user: Signed, client: Annotated[CubeClient, Depends(cube)]) -> dict[str, Any]:
        try:
            return {'members': await client.meta()}
        except CubeError as e:
            raise HTTPException(CUBE_FAILED, str(e)) from e

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
    return router
