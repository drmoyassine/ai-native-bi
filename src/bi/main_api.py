"""Runs the API: `python -m bi.main_api`. Creates the database when asked (co-deployment), migrates, then serves."""

from __future__ import annotations

import asyncio

import uvicorn
from psycopg_pool import AsyncConnectionPool

from .api import AppDeps, create_app
from .config import load_env
from .db import ensure_database, ensure_reader_role, grant_analytics, migrate
from .log import log
from .queue import create_queue, enqueue_collect


async def main() -> None:
    env = load_env()
    if env.BI_DATABASE_ADMIN_URL:
        await ensure_database(env.BI_DATABASE_ADMIN_URL, env.DATABASE_URL)
    async with AsyncConnectionPool(env.DATABASE_URL, open=False) as pool:
        applied = await migrate(pool)
        if applied:
            log('info', 'migrated', applied=applied)
        if env.CUBE_DB_PASSWORD:
            if env.BI_DATABASE_ADMIN_URL:
                await ensure_reader_role(env.BI_DATABASE_ADMIN_URL, env.CUBE_DB_USER, env.CUBE_DB_PASSWORD)
            await grant_analytics(pool, env.CUBE_DB_USER)
            log('info', 'cube may read analytics', role=env.CUBE_DB_USER)
        queue = create_queue(env.DATABASE_URL)
        async with queue.open_async():
            deps = AppDeps(
                pool=pool, api_key=env.BI_API_KEY, ams_origin=env.AMS_CALLBACK_ORIGIN, enqueue=lambda id: enqueue_collect(queue, id)
            )
            app = create_app(deps)
            log('info', 'bi api listening', port=env.PORT)
            config = uvicorn.Config(app, host='0.0.0.0', port=env.PORT, access_log=False, log_config=None)  # noqa: S104 (in a container)
            await uvicorn.Server(config).serve()


if __name__ == '__main__':
    asyncio.run(main())
