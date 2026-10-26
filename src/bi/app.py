"""The app's API under /app/api (ROADMAP-009), for the web app in web/: signing in, uploads, the governed members and chart data.

Sessions: an HttpOnly, SameSite=Strict cookie. Every request that changes something must also carry `X-BI-App: 1`, which another
site cannot send without the BI's consent (no CORS is allowed), so a forged form or link does nothing.
"""

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from . import accounts, uploads
from .accounts import User
from .agent.catalog import datasets
from .agent.routes import AgentContext, create_agent_router
from .agent.suppress import count_measures, suppress_rows
from .charts import ChartDefinition, cube_query, unknown_members
from .cube import CubeClient, CubeError
from .ingest import DATASET
from .log import log

COOKIE = 'bi_session'
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
        signed = await accounts.sign_in(ctx.pool, body.email, body.password)
        if signed is None:
            log('info', 'sign-in refused', email=body.email[:200])
            raise HTTPException(401, 'wrong email or password')
        user, token = signed
        response.set_cookie(
            COOKIE, token, max_age=accounts.SESSION_HOURS * 3600, httponly=True, secure=ctx.cookie_secure, samesite='strict', path='/'
        )
        return {'user': user.__dict__}

    @router.delete('/session', status_code=204)
    async def sign_out(request: Request, response: Response, user: Signed) -> None:
        await accounts.sign_out(ctx.pool, request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path='/', secure=ctx.cookie_secure, httponly=True, samesite='strict')

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

    @router.get('/members')
    async def members(user: Signed, client: Annotated[CubeClient, Depends(cube)]) -> dict[str, Any]:
        try:
            return {'members': await client.meta()}
        except CubeError as e:
            raise HTTPException(502, str(e)) from e

    async def chart_rows(chart: ChartDefinition, client: CubeClient) -> list[dict[str, Any]]:
        """The rows of a chart definition, from Cube; time members come back under their own name (not name.granularity)."""
        try:
            unknown = unknown_members(chart, await client.meta())
            if unknown:
                raise HTTPException(422, f'not governed members: {", ".join(unknown)}')
            rows = await client.load(cube_query(chart))
        except CubeError as e:
            raise HTTPException(502, str(e)) from e
        time = chart.query.time
        if time and time.granularity:  # Cube names the bucket `<dimension>.<granularity>`: the chart knows it as the dimension
            key = f'{time.dimension}.{time.granularity}'
            for r in rows:
                if key in r:
                    r[time.dimension] = r.pop(key)
        return rows

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
                raise HTTPException(502, str(e)) from e
            shown, hidden = suppress_rows(rows, chart.query.measures, counts, threshold)
            return {'rows': shown, 'suppressed_cells': hidden}

    if ctx.agent is not None:
        router.include_router(create_agent_router(ctx.agent, current_user))
    return router
