"""The BI's HTTP surface.

Today: the AMS's request for one collection run (contract 3.6). It is always answered asynchronously: 202 at once, then the worker
calls the AMS back (4.2). The default path is /ams/collect; the AMS's BI_ENDPOINTS may name more paths under it (/ams/collect/<name>),
which land here too and carry the name in the body's `endpoint`.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import FastAPI, Path, Request, Response
from fastapi.responses import JSONResponse
from psycopg_pool import AsyncConnectionPool

from .collect import Refused, accept_collect, key_matches


@dataclass
class AppDeps:
    pool: AsyncConnectionPool
    api_key: str
    ams_origin: str
    enqueue: Callable[[str], Awaitable[None]]
    """Queues the work of one accepted request (Procrastinate in production)."""


def create_app(deps: AppDeps) -> FastAPI:
    app = FastAPI(title='AI-native BI', docs_url=None, redoc_url=None, openapi_url=None)

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

    return app
