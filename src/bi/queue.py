from __future__ import annotations

from dataclasses import dataclass

import httpx
import procrastinate
from procrastinate.jobs import Job
from procrastinate.retry import BaseRetryStrategy, RetryDecision
from psycopg_pool import AsyncConnectionPool

from .agent import providers as agent_providers
from .agent import store as agent_store
from .agent.secrets import SecretStore
from .agent.turn import TurnDeps, process_turn
from .callback import Ended, Supplied, Unfit, post_supply
from .connect.files import Storage, process_sync
from .contract import CollectRequest
from .log import log
from .sources import CannotAnswer, SourceRegistry

COLLECT_QUEUE = 'collect'
COLLECT_TASK = 'collect'
LOAD_QUEUE = 'load'
LOAD_TASK = 'load'
AGENT_QUEUE = 'agent'
TURN_TASK = 'agent_turn'
REFRESH_TASK = 'refresh_models'


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
    `no_source`, and one its source has no data for is `no_data`: the AMS is NOT called (its run stays requested and its owner sees
    it; the AMS's own retries ask again). A 401/409 from the AMS ends the request (`refused`). A network error raises, so the queue
    retries it."""
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
    try:
        supply = await source.answer(req)
    except CannotAnswer as e:
        await end('no_source', f'{source.name}: {e}')
        return 'no_source'
    if supply is None:
        await end('no_data', f'{source.name} has no data for {req.period.label}')
        return 'no_data'
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


@dataclass
class LoadDeps:
    pool: AsyncConnectionPool
    storage: Storage
    database_url: str
    suppression_threshold: int = 5
    """Small counts hidden in the profiles a person checks before approving (DEC-017)."""


@dataclass
class AgentWorkerDeps:
    turn: TurnDeps
    secrets: SecretStore | None
    http: httpx.AsyncClient


def create_queue(
    conninfo: str,
    deps: CollectDeps | None = None,
    retry: CollectRetry | None = None,
    load: LoadDeps | None = None,
    agent: AgentWorkerDeps | None = None,
) -> procrastinate.App:
    """The job queue on the BI's database (migration 0002). The API only defers jobs (no deps); the worker also runs them: `collect`
    (an AMS run) and `load` (a sync of a source, never retried: process_sync records why it failed)."""
    app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=conninfo))
    if agent is not None:

        async def agent_turn(run_id: str) -> None:
            # Never retried: a half-done turn may have had effects; process_turn records how it ended.
            outcome = await process_turn(agent.turn, run_id)
            log('info', 'agent turn', run_id=run_id, outcome=outcome)

        app.task(name=TURN_TASK, queue=AGENT_QUEUE)(agent_turn)

        async def refresh_models(timestamp: int) -> None:
            outcome = await agent_providers.refresh_all(agent.turn.pool, agent.secrets, agent.http)
            pruned = await agent_store.prune_events(agent.turn.pool)
            log('info', 'model lists refreshed', providers=outcome, events_pruned=pruned)

        app.periodic(cron='0 */6 * * *')(app.task(name=REFRESH_TASK, queue=AGENT_QUEUE)(refresh_models))
    if load is not None:

        async def load_sync(id: str) -> None:
            outcome = await process_sync(load.pool, load.storage, load.database_url, id, load.suppression_threshold)
            log('info', 'sync', id=id, outcome=outcome)

        app.task(name=LOAD_TASK, queue=LOAD_QUEUE)(load_sync)
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


async def enqueue_load(app: procrastinate.App, id: str) -> None:
    await app.configure_task(name=LOAD_TASK, queue=LOAD_QUEUE).defer_async(id=id)


async def enqueue_turn(app: procrastinate.App, run_id: str, conversation_id: str) -> None:
    """Queues a turn; the lock makes the turns of one conversation run one at a time."""
    await app.configure_task(name=TURN_TASK, queue=AGENT_QUEUE, lock=conversation_id).defer_async(run_id=run_id)
