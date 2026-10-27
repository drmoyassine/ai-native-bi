"""Runs the API: `python -m bi.main_api`. Creates the database when asked (co-deployment), migrates, then serves."""

from __future__ import annotations

import asyncio

import httpx
import uvicorn
from psycopg_pool import AsyncConnectionPool

from .accounts import AccountError, Throttle, ensure_admin
from .agent.routes import AgentContext
from .agent.secrets import DbSecretStore
from .api import AppDeps, create_app
from .app import AppContext
from .config import Env, admin_from_env, load_env, storage
from .cube import CubeClient
from .db import ensure_database, ensure_reader_role, grant_analytics, migrate
from .log import log
from .mcp.oidc import OidcIssuer
from .mcp.server import McpContext
from .queue import create_queue, enqueue_collect, enqueue_load, enqueue_rebuild, enqueue_turn


def oidc_issuers(env: Env, http: httpx.AsyncClient) -> list[OidcIssuer]:
    """The AMS as issuer when configured (contract 6.2); its tokens must name the MCP server (OAUTH_AUDIENCE, or PUBLIC_URL/mcp)."""
    if not env.AMS_OAUTH_ISSUER:
        return []
    audience = env.OAUTH_AUDIENCE or (f'{env.PUBLIC_URL}/mcp' if env.PUBLIC_URL else None)
    if audience is None:
        raise SystemExit('AMS_OAUTH_ISSUER needs OAUTH_AUDIENCE or PUBLIC_URL (the address tokens must be issued for)')
    return [OidcIssuer(issuer=env.AMS_OAUTH_ISSUER.rstrip('/'), audience=audience, http=http, name='ams')]


async def main() -> None:
    env = load_env()
    if env.BI_DATABASE_ADMIN_URL:
        await ensure_database(env.BI_DATABASE_ADMIN_URL, env.DATABASE_URL)
    async with AsyncConnectionPool(env.DATABASE_URL, open=False) as pool:
        applied = await migrate(pool)
        if applied:
            log('info', 'migrated', applied=applied)
        try:
            admin = admin_from_env(env)
            if admin and await ensure_admin(pool, *admin):
                log('info', 'administrator created', email=admin[0])  # never the password
        except (ValueError, AccountError) as e:
            raise SystemExit(f'ADMIN_EMAIL / ADMIN_PASSWORD: {e}') from e
        if env.CUBE_DB_PASSWORD:
            if env.BI_DATABASE_ADMIN_URL:
                await ensure_reader_role(env.BI_DATABASE_ADMIN_URL, env.CUBE_DB_USER, env.CUBE_DB_PASSWORD)
            await grant_analytics(pool, env.CUBE_DB_USER)
            log('info', 'cube may read analytics', role=env.CUBE_DB_USER)
        queue = create_queue(env.DATABASE_URL)
        async with queue.open_async(), httpx.AsyncClient() as http:
            cube = CubeClient(http, env.CUBE_API_URL, env.CUBE_API_SECRET) if env.CUBE_API_URL and env.CUBE_API_SECRET else None
            secrets = DbSecretStore(pool, env.BI_SECRETS_KEY) if env.BI_SECRETS_KEY else None
            context = AppContext(
                pool=pool,
                storage=storage(env),
                enqueue_load=lambda id: enqueue_load(queue, id),
                enqueue_rebuild=lambda dataset: enqueue_rebuild(queue, dataset),
                cube=cube,
                cookie_secure=env.APP_COOKIE_SECURE,
                public_url=env.PUBLIC_URL,
                throttle=Throttle(
                    window_minutes=env.SIGN_IN_WINDOW_MINUTES,
                    per_email=env.SIGN_IN_MAX_FAILURES_PER_EMAIL,
                    per_ip=env.SIGN_IN_MAX_FAILURES_PER_IP,
                ),
                proxy_hops=env.TRUSTED_PROXY_HOPS,
                agent=AgentContext(
                    pool=pool,
                    database_url=env.DATABASE_URL,
                    secrets=secrets,
                    http=http,
                    enqueue_turn=lambda run_id, conversation_id: enqueue_turn(queue, run_id, conversation_id),
                    institution_monthly_tokens=env.AGENT_INSTITUTION_MONTHLY_TOKENS,
                    person_monthly_tokens=env.AGENT_PERSON_MONTHLY_TOKENS,
                    suppression_threshold=env.SUPPRESSION_THRESHOLD,
                ),
            )
            deps = AppDeps(
                pool=pool,
                api_key=env.BI_API_KEY,
                ams_origin=env.AMS_CALLBACK_ORIGIN,
                enqueue=lambda id: enqueue_collect(queue, id),
                app=context,
                web_dir=env.WEB_DIR,
                mcp=McpContext(
                    pool=pool,
                    cube=cube,
                    suppression_threshold=env.SUPPRESSION_THRESHOLD,
                    public_url=env.PUBLIC_URL,
                    calls_per_minute=env.MCP_CALLS_PER_MINUTE,
                    calls_per_day=env.MCP_CALLS_PER_DAY,
                    issuers=oidc_issuers(env, http),
                ),
            )
            app = create_app(deps)
            log('info', 'bi api listening', port=env.PORT)
            config = uvicorn.Config(app, host='0.0.0.0', port=env.PORT, access_log=False, log_config=None)  # noqa: S104 (in a container)
            await uvicorn.Server(config).serve()


if __name__ == '__main__':
    asyncio.run(main())
