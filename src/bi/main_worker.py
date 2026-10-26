"""Runs the worker: `python -m bi.main_worker`. Works the collect queue (the API migrates the database first)."""

from __future__ import annotations

import asyncio

import httpx
from psycopg_pool import AsyncConnectionPool

from .config import load_env
from .cube import CubeClient
from .log import log
from .metrics import CubeMetricSource
from .queue import COLLECT_QUEUE, CollectDeps, create_queue
from .sources import Source, SourceRegistry


async def main() -> None:
    env = load_env()
    async with AsyncConnectionPool(env.DATABASE_URL, open=False) as pool, httpx.AsyncClient() as client:
        sources: list[Source] = []
        if env.CUBE_API_URL and env.CUBE_API_SECRET:
            sources.append(CubeMetricSource(CubeClient(client, env.CUBE_API_URL, env.CUBE_API_SECRET)))
        else:
            log('info', 'no cube configured: every request ends no_source')
        deps = CollectDeps(pool=pool, sources=SourceRegistry(sources), callback_timeout_ms=env.CALLBACK_TIMEOUT_MS, client=client)
        queue = create_queue(env.DATABASE_URL, deps)
        async with queue.open_async():
            log('info', 'bi worker started', queues=[COLLECT_QUEUE])
            await queue.run_worker_async(queues=[COLLECT_QUEUE], install_signal_handlers=True)


if __name__ == '__main__':
    asyncio.run(main())
