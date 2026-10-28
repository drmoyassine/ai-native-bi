"""Runs the worker: `python -m bi.main_worker`. Works the collect queue (the API migrates the database first)."""

from __future__ import annotations

import asyncio

import httpx
from psycopg_pool import AsyncConnectionPool

from .agent.secrets import DbSecretStore
from .agent.turn import TurnDeps, make_model_for
from .config import load_env, storage
from .cube import CubeClient
from .log import log
from .metrics import CubeMetricSource
from .queue import AGENT_QUEUE, COLLECT_QUEUE, LOAD_QUEUE, AgentWorkerDeps, CollectDeps, LoadDeps, create_queue
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
        load = LoadDeps(pool=pool, storage=storage(env), database_url=env.DATABASE_URL, suppression_threshold=env.SUPPRESSION_THRESHOLD)
        secrets = DbSecretStore(pool, env.BI_SECRETS_KEY) if env.BI_SECRETS_KEY else None
        cube_client = CubeClient(client, env.CUBE_API_URL, env.CUBE_API_SECRET) if env.CUBE_API_URL and env.CUBE_API_SECRET else None
        turn = TurnDeps(
            pool=pool, cube=cube_client, suppression_threshold=env.SUPPRESSION_THRESHOLD, model_for=make_model_for(pool, secrets)
        )
        queue = create_queue(
            env.DATABASE_URL,
            deps,
            load=load,
            agent=AgentWorkerDeps(turn=turn, secrets=secrets, http=client, institution_monthly_tokens=env.AGENT_INSTITUTION_MONTHLY_TOKENS),
        )
        queues = [COLLECT_QUEUE, LOAD_QUEUE, AGENT_QUEUE]
        async with queue.open_async():
            log('info', 'bi worker started', queues=queues, agent=secrets is not None)
            await queue.run_worker_async(queues=queues, install_signal_handlers=True)


if __name__ == '__main__':
    asyncio.run(main())
