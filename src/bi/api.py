"""The BI's HTTP surface.

Today: the AMS's request for one collection run (contract 3.6). It is always answered asynchronously: 202 at once, then the worker
calls the AMS back (4.2). The default path is /ams/collect; the AMS's BI_ENDPOINTS may name more paths under it (/ams/collect/<name>),
which land here too and carry the name in the body's `endpoint`.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from fastapi import FastAPI, Path, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import AsyncConnectionPool
from starlette.routing import Route

from .app import AppContext, create_router
from .collect import Refused, accept_collect, key_matches
from .mcp.server import McpContext, build_server


@dataclass
class AppDeps:
    pool: AsyncConnectionPool
    api_key: str
    ams_origin: str
    enqueue: Callable[[str], Awaitable[None]]
    """Queues the work of one accepted request (Procrastinate in production)."""
    app: AppContext | None = None
    """The app's API (/app/api); None serves the AMS's route only."""
    web_dir: str | None = None
    """The built web app (web/dist), served at /."""
    mcp: McpContext | None = None
    """The MCP server (docs/mcp-spec.md), at /mcp; None leaves it out."""


def create_app(deps: AppDeps) -> FastAPI:
    mcp = build_server(deps.mcp) if deps.mcp else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if mcp is None:
            yield
            return
        async with mcp[0].session_manager.run():  # mounted inside this app, so its own lifespan does not run
            yield

    app = FastAPI(title='AI-native BI', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    if mcp is not None:
        # An exact route, ahead of every other: the MCP app keeps its own middleware (bearer authentication) and its own route.
        app.router.routes.insert(0, Route('/mcp', endpoint=mcp[1]))

    @app.get('/healthz')
    async def healthz() -> dict[str, bool]:
        return {'ok': True}

    async def collect(request: Request) -> Response:
        if not key_matches(request.headers.get('authorization'), deps.api_key):
            return JSONResponse({'error': 'unauthorized'}, status_code=401)
        try:
            body = json.loads(await request.body())
        except ValueError:
            return JSONResponse({'error': 'bad_request', 'message': 'the body must be JSON'}, status_code=400)
        r = await accept_collect(deps.pool, body, deps.ams_origin)
        if isinstance(r, Refused):
            return JSONResponse(
                {'error': 'invalid', 'message': 'the request does not fit the contract', 'issues': [i.model_dump() for i in r.issues]},
                status_code=r.status,
            )
        if not r.repeat:
            await deps.enqueue(r.id)
        return Response(status_code=202)

    @app.post('/ams/collect')
    async def collect_default(request: Request) -> Response:
        return await collect(request)

    @app.post('/ams/collect/{endpoint}')
    async def collect_named(request: Request, endpoint: Annotated[str, Path(pattern=r'^[A-Za-z0-9_.-]+$')]) -> Response:
        return await collect(request)

    if deps.app is not None:
        app.include_router(create_router(deps.app))
    if deps.web_dir and os.path.isdir(deps.web_dir):
        app.mount('/', StaticFiles(directory=deps.web_dir, html=True), name='web')  # after every route: they match first
    return app
