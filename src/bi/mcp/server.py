"""The MCP server (docs/mcp-spec.md): the official MCP SDK's MCPServer, stateless streamable HTTP at /mcp, mounted in the API.

Every tool is a shared governed tool (src/bi/tools) called as the principal of the bearer token, within the person's rate limits,
and recorded in the access log. Nothing here decides what data may leave: that is the shared tools' job, the same as in the chat."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import AnyHttpUrl
from starlette.applications import Starlette

from .. import tools
from ..charts import ChartDefinition, ChartQuery
from ..cube import CubeClient, CubeError
from .oidc import OidcIssuer
from .principal import Principal, PrincipalVerifier

INSTRUCTIONS = """The institution's governed metrics (its business intelligence). Every number comes from a governed metric layer.
Call list_metrics first to learn the measures and dimensions and their exact names, then query_metric with those names.
Always tell the person the data's as-of date. Counts under the privacy threshold come back as null and are listed under
`suppressed`: say they are hidden for privacy; never guess them, and never combine overlapping queries to recover them.
There are no rows about individual people here, on purpose. save_chart keeps a chart as the person's private draft in the BI."""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


@dataclass
class McpContext:
    pool: AsyncConnectionPool
    cube: CubeClient | None
    suppression_threshold: int = 5
    public_url: str | None = None
    """The app's own address (PUBLIC_URL): the host MCP requests may name, and the base of the server's URL."""
    calls_per_minute: int = 60
    calls_per_day: int = 2000
    issuers: list[OidcIssuer] = field(default_factory=list)
    """OpenID Connect issuers whose access tokens act for a person (the AMS, contract 6.2); the first is advertised to MCP clients."""


class Limited(ToolError):
    pass


def transport_security(public_url: str | None) -> TransportSecuritySettings:
    """DNS-rebinding protection: requests must name the app's own host (or localhost, for a local run)."""
    hosts = ['127.0.0.1:*', 'localhost:*', '[::1]:*']
    origins = ['http://127.0.0.1:*', 'http://localhost:*', 'http://[::1]:*']
    if public_url:
        parts = urlsplit(public_url)
        hosts += [parts.netloc, f'{parts.hostname}:*']
        origins += [f'{parts.scheme}://{parts.netloc}']
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)


def auth_settings(ctx: McpContext) -> AuthSettings:
    """With an issuer configured, MCP clients are told where to sign in: the server publishes its protected-resource metadata
    (RFC 9728) naming the issuer as its authorization server, and a refusal points there. Without one, only personal access tokens
    work and nothing is advertised."""
    if ctx.issuers:
        # The verifier checks each token's audience itself (src/bi/mcp/oidc.py), for every configured issuer.
        return AuthSettings(
            issuer_url=AnyHttpUrl(ctx.issuers[0].issuer),
            resource_server_url=AnyHttpUrl(ctx.issuers[0].audience),
            validate_token_resource=False,
        )
    return AuthSettings(issuer_url=AnyHttpUrl(ctx.public_url or 'http://localhost'), resource_server_url=None)


def build_server(ctx: McpContext) -> tuple[MCPServer, Starlette]:
    """The server and its ASGI app (/mcp, and the protected-resource metadata when an issuer is configured). The caller routes every
    path of the app's routes to it and runs `server.session_manager.run()` for the app's lifetime."""
    server = MCPServer(
        name='ai-native-bi',
        title='AI-native BI: governed metrics',
        instructions=INSTRUCTIONS,
        token_verifier=PrincipalVerifier(ctx.pool, ctx.issuers),
        auth=auth_settings(ctx),
    )

    async def call(tool: str, arguments: dict[str, Any], run: Callable[[tools.ToolContext], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        access = get_access_token()
        if access is None or not access.claims:  # the SDK's middleware refuses unauthenticated requests before this
            raise ToolError('not signed in')
        principal = Principal.from_claims(access.claims)
        if principal.scope != 'all':
            raise ToolError(
                'your access is limited to some units or programs, which the BI cannot enforce yet, so nothing is answered rather than '
                'too much; ask for institution-wide access or wait for scoped access'
            )
        await _check_limits(ctx, principal, tool, arguments)
        tc = tools.ToolContext(pool=ctx.pool, cube=ctx.cube, user_id=principal.subject, suppression_threshold=ctx.suppression_threshold)
        try:
            result = await run(tc)
        except (tools.ToolError, CubeError) as e:
            await _log(ctx, principal, tool, arguments, None, 'error', str(e))
            raise ToolError(str(e)) from e
        error = result.get('error')
        await _log(ctx, principal, tool, arguments, result, 'error' if error else 'ok', error)
        return result

    @server.tool(name='list_metrics', description=tools.list_metrics.__doc__, annotations=READ_ONLY)
    async def list_metrics() -> dict[str, Any]:
        return await call('list_metrics', {}, tools.list_metrics)

    @server.tool(name='query_metric', description=tools.query_metric.__doc__, annotations=READ_ONLY)
    async def query_metric(query: ChartQuery) -> dict[str, Any]:
        return await call('query_metric', {'query': query.model_dump(mode='json', by_alias=True, exclude_defaults=True)},
                          lambda tc: tools.query_metric(tc, query))  # fmt: skip

    @server.tool(
        name='save_chart',
        description=tools.save_chart.__doc__,
        annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False),
    )
    async def save_chart(chart: ChartDefinition) -> dict[str, Any]:
        result = await call('save_chart', {'chart': chart.model_dump(mode='json', by_alias=True, exclude_defaults=True)},
                            lambda tc: tools.save_chart(tc, chart))  # fmt: skip
        if 'draft_id' in result and ctx.public_url:
            result['note'] = 'saved as a private draft; the person sees it in the BI app'
        return result

    @server.tool(name='get_chart', description=tools.get_chart.__doc__, annotations=READ_ONLY)
    async def get_chart(chart_id: str) -> dict[str, Any]:
        return await call('get_chart', {'chart_id': chart_id}, lambda tc: tools.get_chart(tc, chart_id))

    @server.tool(name='list_datasets', description=tools.list_datasets.__doc__, annotations=READ_ONLY)
    async def list_datasets() -> dict[str, Any]:
        return await call('list_datasets', {}, tools.list_datasets)

    @server.tool(name='describe_dataset', description=tools.describe_dataset.__doc__, annotations=READ_ONLY)
    async def describe_dataset(dataset: str) -> dict[str, Any]:
        return await call('describe_dataset', {'dataset': dataset}, lambda tc: tools.describe_dataset(tc, dataset))

    app = server.streamable_http_app(
        streamable_http_path='/mcp', stateless_http=True, json_response=True, transport_security=transport_security(ctx.public_url)
    )
    return server, app


async def _check_limits(ctx: McpContext, principal: Principal, tool: str, arguments: dict[str, Any]) -> None:
    async with ctx.pool.connection() as conn:
        row = await (
            await conn.execute(
                """select count(*) filter (where at > now() - interval '1 minute'), count(*) from access_log
                   where user_id = %s and outcome <> 'limited' and at > now() - interval '1 day'""",
                [principal.subject],
            )
        ).fetchone()
    minute, day = row if row else (0, 0)
    if minute >= ctx.calls_per_minute or day >= ctx.calls_per_day:
        message = (
            f'the limit of {ctx.calls_per_minute} calls a minute is reached; try again in a minute'
            if minute >= ctx.calls_per_minute
            else f'the limit of {ctx.calls_per_day} calls a day is reached; try again tomorrow'
        )
        await _log(ctx, principal, tool, arguments, None, 'limited', message)
        raise Limited(message)


async def _log(
    ctx: McpContext,
    principal: Principal,
    tool: str,
    arguments: dict[str, Any],
    result: dict[str, Any] | None,
    outcome: str,
    error: str | None,
) -> None:
    result = result or {}
    rows = result.get('row_count', len(result['rows']) if isinstance(result.get('rows'), list) else None)
    async with ctx.pool.connection() as conn:
        await conn.execute(
            """insert into access_log (user_id, issuer, client_id, tool, arguments, rows, suppressed_cells, outcome, error)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [principal.subject, principal.issuer, principal.client_id, tool, Jsonb(arguments), rows,
             result.get('suppressed_cells'), outcome, error],
        )  # fmt: skip
