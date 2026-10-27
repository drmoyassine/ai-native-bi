# Spec: the MCP server — governed metrics for outside agents (ROADMAP-004)

Status: **approved 2026-10-27; step 3a built (TASK-016).** The decisions of § 11 are DEC-021 to DEC-024; steps 3b to 3e are TASK-017 to TASK-020. Builds on DEC-004 (Cube is the only read
path), DEC-009 (one general-purpose API and MCP server on Cube), DEC-012 (one chart definition), DEC-013 (drafts and publishing),
DEC-017 (the model sees schemas, profiles and suppressed aggregates, never rows) and `docs/agent-spec.md` (the same tools, defined once).
Identity depends on the contract request [#10](https://github.com/drmoyassine/ai-native-bi/issues/10) (proposal 5 in
`docs/ams-contract-proposals.md`).

## 1. What it is for

An MCP server lets an agent outside the BI (Claude, Claude Code, another assistant, an automation) use the institution's governed
metrics the way the BI's own chat agent does: find a metric, query it, get a chart. The outside agent's model runs on the client's side,
so the BI serves **tools and data, not a model**.

| Who | Example | What they get |
|---|---|---|
| A dean in Claude | "Compare enrollment by program this fall with last fall" | Suppressed aggregates with their as-of date; a chart draft in the BI |
| An analyst in Claude Code | "What datasets do we have, and what does enrollment contain?" | The catalog and column profiles, never rows |
| An automation | A weekly summary of headcount | The same reads, under a person's or a service's identity |

## 2. Requirements

1. **Governed reads only** (rule 5). Every number comes through Cube; structured queries, never SQL; nothing student-level.
2. **The same tools as the chat agent**, defined once (agent spec, requirement 8): one implementation, two front doors.
3. **The same privacy as the chat** (DEC-017). What an MCP client reads goes to the client's own model provider, outside the BI; it
   gets exactly what the BI's model would: schemas, profiles, aggregates with small counts hidden.
4. **Acts as a person**, with that person's role and data scope, never more. Every call is recorded: who, which tool, what was asked,
   how many rows came back.
5. **A range of identities** (§ 5): the BI's own accounts, the AMS as identity provider, the institution's single sign-on, and service
   identities, behind one interface, so the tools never know which issuer signed a person in.
6. **Read-only and drafts only.** No tool publishes, approves, builds or changes anything shared.
7. **Bounded.** Rate limits per person; row caps per answer; timeouts.

## 3. Library

**The official MCP Python SDK, `mcp` 2.x, its `MCPServer` class.** Verified against `mcp` 2.3.0 on 2026-10-27:

- In 2.x the high-level server once called `FastMCP` is **`MCPServer`** (`from mcp.server.mcpserver import MCPServer`); importing
  `mcp.server.fastmcp` fails with a pointer to the migration guide. Tools are decorated functions with schemas from type hints.
- `MCPServer.streamable_http_app(streamable_http_path='/mcp', stateless_http=..., json_response=..., transport_security=..., host=...)`
  returns a Starlette app, which we mount in the API (§ 4).
- Authentication is built in for a **resource server**: `MCPServer(token_verifier=..., auth=AuthSettings(...))`. `TokenVerifier`
  is a protocol with one method, `verify_token(token) -> AccessToken | None`; `AccessToken` carries `subject`, `scopes`, `claims`,
  `expires_at`, `resource`. `AuthSettings` names the authorization server (`issuer_url`) and this server's address
  (`resource_server_url`, with `validate_token_resource`), which is what MCP clients use to discover where to sign in.
- DNS-rebinding protection is on by default with `allowed_hosts` limited to `127.0.0.1`/`localhost`; behind our domain it must list
  the public host (`TransportSecuritySettings`).
- `mcp` 2.3.0 depends on `httpx2` (not `httpx`), `pyjwt[crypto]` and `starlette`; the build checks it installs cleanly beside
  Pydantic AI and our `httpx`, and pins the version.

**Not the standalone `fastmcp` package** (a separate project with more batteries: auth integrations, composition, generating tools
from an OpenAPI or FastAPI app). We need none of it now, and generating MCP tools from our REST routes is exactly what we must not do:
tools are designed, documented for a model and privacy-filtered. Revisit only if its auth integrations save real work in § 5.

## 4. Shape

```
MCP client ──HTTPS──▶  bi-api  /mcp  (MCPServer, streamable HTTP, stateless)
                          │  bearer token ─▶ TokenVerifier ─▶ Principal (who, role, scope)
                          ▼
                   shared tools (src/bi/tools/)  ──▶  Cube (security context = scope)  ──▶  analytics
                          │
                          └─▶ access log, drafts (BI database)
```

- **Mounted in the API** at `/mcp` (one deployment, one domain, one TLS certificate), not a new service. The SDK's session manager runs
  in the API's lifespan.
- **Stateless HTTP with JSON responses**: every call stands alone, so any API replica can answer it and nothing is kept between calls.
  Our tools are request/response; nothing needs server-sent streaming in v1.
- **Allowed hosts** come from a new setting, `PUBLIC_URL` (the app's own address), also used for `resource_server_url`.
- **Tools move to `src/bi/tools/`** as plain async functions taking a `ToolContext` (the principal, the pool, Cube, the suppression
  threshold, an `emit` that is a no-op outside the chat). The chat agent's `FunctionToolset` and the MCP server both wrap them; the
  chat-only parts (events to the chat) stay in `src/bi/agent/`.

## 5. Identity and access

### The principal

Every request resolves to one **principal**: `issuer`, `subject`, `email`, `name`, `role` (`viewer`, `steward`, `admin`) and `scope`
(the org units or programs whose figures the person may see, or `all`). Tools see only the principal, never the token or the issuer.
A person seen for the first time gets a minimal record keyed by (issuer, subject), so their drafts and access log have an owner; no
password, no copy of their roles (roles are read from each token).

### Issuers, one interface

A `TokenVerifier` that dispatches by token shape to the configured issuers (`AUTH_ISSUERS`):

| Setup | Token | Verified by | When |
|---|---|---|---|
| **BI accounts** (standalone) | A personal access token, `bi_pat_...` | Its SHA-256 hash in the BI's database; expiry; not revoked | Phase 1 |
| **AMS as identity provider** | A JWT the AMS issues for the BI (audience = the BI) | The AMS's published keys (OIDC discovery, JWKS); `iss`, `aud`, `exp` | When #10 is agreed and built |
| **Institution SSO, direct** | A JWT from the institution's OIDC provider | Its published keys; claims mapped to role and scope by a configured mapping | ROADMAP-005, if the AMS does not federate it |
| **Service identity** | The existing service key (AMS → BI) | Constant-time compare, as today | Unchanged; not for MCP clients in v1 |

Claims follow one vocabulary whichever issuer signed them (subject, email, name, BI role, data scope: proposal 5). A disabled person
is refused at the next token: the AMS stops issuing, the BI rejects revoked PATs, and JWTs are short-lived.

### Signing in from an MCP client

- **Phase 1, personal access tokens.** A signed-in person creates a token in the app ("Access tokens": name, expiry, shown once,
  revocable); the client sends it as `Authorization: Bearer bi_pat_...`. Works with clients that take a header (Claude Code's `.mcp.json`,
  most SDK clients). Admins see and revoke everyone's tokens.
- **Phase 2, OAuth through the AMS.** `AuthSettings(issuer_url=<AMS>, resource_server_url=<PUBLIC_URL>/mcp)`: the BI advertises the
  AMS as its authorization server; an MCP client (including claude.ai connectors, which sign in with OAuth) sends the person through the
  AMS's sign-in (authorization code with PKCE) and comes back with an AMS token for the BI. Client registration (dynamic or
  pre-registered) is the AMS's answer to #10, question 3.

### Data scope in Cube

Scope is enforced **in Cube**, not in each tool: the principal's scope goes into Cube's security context for the request (the JWT the
BI signs for Cube), and the Cube model's query rewrite adds the org-unit or program filter to every query. Every consumer (MCP, chat,
charts, AMS answers) then gets the same filtering, and a tool cannot forget it. Needs the scope ids in the warehouse (the org-unit or
program dimension, contract open question 6). Until then every principal's scope is `all`, as in the app today, and the spec's tests
pin that a non-`all` scope is refused rather than ignored.

## 6. Tools

| Tool | Does | Returns | Annotations |
|---|---|---|---|
| `list_metrics` | Cube's governed measures and dimensions | Names, titles, descriptions, types | read-only |
| `query_metric` | A structured Cube query | Aggregated rows (at most 200) with small counts hidden, `as_of`, the query | read-only |
| `list_datasets` / `describe_dataset` | The catalog | Tables, columns, types, profiles; never rows | read-only |
| `save_chart` | Saves a chart definition as the person's private draft (the chat's `propose_chart`) | The draft's id and its link in the app | not read-only, idempotent per definition |
| `get_chart` | One of the person's drafts or a published chart | Its definition and its rows, small counts hidden | read-only |

Every tool writes the access log (§ 7). Not offered, on purpose: the build tools (sandbox, files, credentials, proposals), uploads,
anything admin, SQL. Instructions sent with the server tell the client's model the same rules the chat agent's prompt does: say the
as-of date, never guess a hidden count, never combine overlapping queries to recover one.

## 7. Privacy, audit and limits

- **Privacy** is the chat's (DEC-017), unchanged: the same functions, the same suppression, the same row cap. Complementary
  suppression across many calls is still TASK-008; outside agents make that more pressing, so the access log keeps enough to detect
  differencing later. The privacy rules (TASK-002) must be set before real data is reachable through MCP.
- **Access log** (new table): time, principal, issuer, client, tool, arguments (structured query, never secrets), rows returned, cells
  hidden, outcome. Kept a year by default; readable by admins in the app.
- **Limits**: per principal, 60 calls a minute and 2,000 a day by default (settings); a refused call says why and when to retry. Each
  call has Cube's timeout. No token budget: the model is the client's.

## 8. Connecting

- **Claude Code** (this project's sessions included): `.mcp.json` with an `http` server at `<PUBLIC_URL>/mcp` and the token from an
  environment variable, never committed. A cloud session also needs the BI's host in its environment's allowed network domains.
- **claude.ai and other OAuth-only clients**: after phase 2, as a custom connector pointing at `<PUBLIC_URL>/mcp`.
- **Staging first**: `https://bi-staging.4ky7uo.easypanel.host/mcp`, with a token for a staging person.

## 9. Testing

- The tools' existing tests move with them; the chat and MCP wrappers each get thin tests.
- **A real MCP client** (the SDK's) against the mounted app over HTTP: list tools, call each, check suppression and the as-of date
  match the chat's answers for the same query.
- **Auth**: no token, a wrong token, a revoked or expired PAT, a JWT from an unknown issuer, the wrong audience, an expired JWT: all
  refused; a viewer cannot reach admin data; a non-`all` scope is refused until Cube enforces it.
- **Limits and the access log**: the 61st call in a minute is refused; every call leaves one log row.

## 10. Delivery

| Step | What | Done when |
|---|---|---|
| **3a** | Tools moved to `src/bi/tools/`; principal and `TokenVerifier`; personal access tokens and their page; `/mcp` mounted; access log; limits | A real MCP client lists and calls the tools with a PAT; refusals tested |
| **3b** | Staging: `PUBLIC_URL`, a token, `.mcp.json`, the network allowance | This project's Claude Code session queries staging through MCP |
| **3c** | AMS issuer and OAuth (after #10) | A person signs in through the AMS from an MCP client and gets their role |
| **3d** | Scope in Cube's security context (after the org dimension) | A scoped person sees only their units' figures, in MCP and in the app |
| **3e** | Institution SSO, direct, if the AMS does not federate it | An institution token is accepted with mapped role and scope |

## 11. Decisions to record once approved

1. **The MCP server is the official SDK's `MCPServer`, mounted in the API at `/mcp`, stateless streamable HTTP**; not the standalone
   `fastmcp` package; no tools generated from REST routes.
2. **One principal, many issuers**: BI personal access tokens, the AMS (OIDC), the institution's SSO and service identities behind one
   verifier; roles and scope read from each token, not copied.
3. **Data scope is enforced in Cube's security context**, for every consumer.
4. **The chat agent and the MCP server share one tool implementation**, with the same privacy rules.

## 12. Open questions

1. Answers to #10: the role mapping, whether the AMS federates SSO, client registration, token lifetimes.
2. Does a person's scope limit the figures they see now, or is `all` right until the org dimension exists?
3. Should service identities (automations) be allowed on MCP in v1, or only people?
4. The default limits and the access log's retention.
