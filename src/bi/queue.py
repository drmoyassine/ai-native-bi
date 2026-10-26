from __future__ import annotations

from dataclasses import dataclass

import httpx
import procrastinate
from procrastinate.jobs import Job
from procrastinate.retry import BaseRetryStrategy, RetryDecision
from psycopg_pool import AsyncConnectionPool

from .callback import Ended, Supplied, Unfit, post_supply
from .contract import CollectRequest
from .log import log
from .sources import SourceRegistry

COLLECT_QUEUE = 'collect'
COLLECT_TASK = 'collect'


@dataclass
class CollectDeps:
    pool: AsyncConnectionPool
    sources: SourceRegistry
    callback_timeout_ms: int
    client: httpx.AsyncClient


class CallbackError(Exception):
    """The AMS could not be reached (or answered something unexpected): the queue retries."""


async def process_collect(deps: CollectDeps, id: str) -> str:
    """Works one request: find a source, ask it, call the AMS back. Outcomes are kept on the row. A request no source can answer is
    `no_source` and the AMS is NOT called (its run stays requested and its owner sees it; the AMS's own retries ask again). A 401/409
    from the AMS ends the request (`refused`). A network error raises, so the queue retries it."""
    async with deps.pool.connection() as conn:
        row = await (
            await conn.execute(
                """update collect_request set status = 'running', attempts = attempts + 1
                   where id = %s and status in ('queued', 'running')
                   returning callback_token, callback_url, request""",
                [id],
            )
        ).fetchone()
    if row is None or row[0] is None:
        return 'skipped'
    token: str = row[0]
    callback_url: str = row[1]
    req = CollectRequest.model_validate({**row[2], 'callbackToken': token})

    async def end(status: str, error: str | None) -> None:
        async with deps.pool.connection() as conn:
            await conn.execute(
                'update collect_request set status = %s, last_error = %s, finished_at = now(), callback_token = null where id = %s',
                [status, error, id],
            )

    source = deps.sources.find(req)
    if source is None:
        metric = req.query.metric if req.query and req.query.metric else '(none)'
        await end('no_source', f'no source answers metric "{metric}"' + (f' at endpoint "{req.endpoint}"' if req.endpoint else ''))
        return 'no_source'
    supply = await source.answer(req)
    r = await post_supply(deps.client, callback_url, token, supply, deps.callback_timeout_ms)
    if isinstance(r, Supplied):
        await end('supplied', None)
        return 'supplied'
    if isinstance(r, Ended):
        await end('refused', f'the AMS answered {r.status}')
        return 'refused'
    if isinstance(r, Unfit):
        await end('failed', 'the AMS refused the supply: ' + '; '.join(f'{i.path}: {i.message}' for i in r.issues))
        return 'failed'
    async with deps.pool.connection() as conn:
        await conn.execute('update collect_request set last_error = %s where id = %s', [r.message, id])
    raise CallbackError(f'callback failed: {r.message}')


class CollectRetry(BaseRetryStrategy):
    """Five retries of a job that raised (the AMS unreachable, a source that failed): 1, 2, 4, 8 and 16 minutes after each failure."""

    def __init__(self, max_retries: int = 5, first_wait_seconds: int = 60) -> None:
        self.max_retries = max_retries
        self.first_wait_seconds = first_wait_seconds

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        if job.attempts >= self.max_retries:
            return None
        return RetryDecision(retry_in={'seconds': self.first_wait_seconds * 2**job.attempts})


async def give_up(pool: AsyncConnectionPool, id: str, attempts: int, error: BaseException) -> None:
    """Ends a request the queue will not try again: `failed`, with the reason, and the token forgotten (CLAUDE.md rule 4)."""
    message = f'gave up after {attempts} attempt{"s" if attempts != 1 else ""}: {error}'
    async with pool.connection() as conn:
        await conn.execute(
            """update collect_request set status = 'failed', last_error = %s, finished_at = now(), callback_token = null
               where id = %s and status = 'running'""",
            [message, id],
        )


def create_queue(conninfo: str, deps: CollectDeps | None = None, retry: CollectRetry | None = None) -> procrastinate.App:
    """The job queue on the BI's database (migration 0002). The API only defers jobs (`deps` None); the worker also runs them."""
    app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=conninfo))
    if deps is not None:
        strategy = retry or CollectRetry()

        async def collect(context: procrastinate.JobContext, id: str) -> None:
            try:
                outcome = await process_collect(deps, id)
            except Exception as e:
                if strategy.get_retry_decision(exception=e, job=context.job) is None:
                    await give_up(deps.pool, id, context.job.attempts + 1, e)
                    log('error', 'collect gave up', id=id, attempts=context.job.attempts + 1, error=str(e))
                raise
            log('info', 'collect', id=id, outcome=outcome)

        app.task(name=COLLECT_TASK, queue=COLLECT_QUEUE, retry=strategy, pass_context=True)(collect)
    return app


async def enqueue_collect(app: procrastinate.App, id: str) -> None:
    await app.configure_task(name=COLLECT_TASK, queue=COLLECT_QUEUE).defer_async(id=id)
