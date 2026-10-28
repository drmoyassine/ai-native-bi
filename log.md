---
okf_version: "0.2"
title: "AI-native BI Log"
generated:
  by: "process:vef-init"
  at: "2026-10-26T13:17:17.625Z"
---

# Log

Chronological log of decisions, discoveries, and session learnings. This is the **single-source memory** — durable context that survives across sessions. Newest entries first.

> **OKF reserved filename.** `log.md` follows the [Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) convention. It links to DECISIONS.md; decisions remain the canonical record.

---

## 2026-10-27 — Hardening: sign-in throttling, change password, no raw port

TASK-010 and part of TASK-011. Failed sign-ins are counted by the email typed and by client address; past 10 per email or 20 per
address in 15 minutes the next attempt is refused with 429 before any password work, and a success clears the email's count. The
client address behind a proxy is the entry the nearest trusted proxy appended to X-Forwarded-For (`TRUSTED_PROXY_HOPS`, Easypanel: 1);
trusting the first entry would let a blocked client dodge the limit by prefixing a made-up address, which a test now pins. People
change their own password on the Account page, which ends their other sessions. `compose.yaml` publishes port 4000 on the loopback
only: staging's API had also been reachable over plain HTTP on the server's address. For staging, set TRUSTED_PROXY_HOPS=1 on the
service, or the per-address limit would count everyone behind the router as one client.

## 2026-10-27 — "Error 502" on a fresh deployment was "no data yet"

On staging the Chart page showed a bare "error 502". Two causes together: nothing had been loaded, so the analytics table Cube reads
did not exist and Cube answered "relation does not exist"; and the app turned every Cube failure into HTTP 502, which Easypanel's
proxy replaces with its own "service is not reachable" page, so the reason never reached the page. Now the Cube client tells a
missing table (`CubeNoData`) from a failure: charts and the agent's tools answer it as no data, the AMS's collect answers it as no
supply (rule 3) instead of a failure to retry, and a real Cube failure is a 424 that carries its reason through any proxy.

## 2026-10-27 — The AMS signs people in to the MCP server

The AMS answered issue 10 with contract 6.2 (AMS DEC-035), and the BI built its side (TASK-018, DEC-025): the AMS's EdDSA access
tokens act for a person on `/mcp`, with `bi_role` and `bi_scope` read from each token; an AMS person gets a local record keyed by
(issuer, subject) and no password; MCP clients learn from the protected-resource metadata to sign in at the AMS. Learned on the way:
`mcp` 2.x warns unless `AuthSettings.validate_token_resource` is set, and it must be False when the verifier checks the audience
itself; PyJWT's `PyJWK` loads the AMS's OKP keys directly. The AMS also revised co-deployment (contract 6.3: one database, each
product in its own schemas), which the BI does not follow yet (TASK-021).

## 2026-10-27 — MCP step 3a: the governed tools for outside agents

TASK-016 (DEC-021 to DEC-024): the tools moved to `src/bi/tools` and are shared by the chat and the MCP server at `/mcp`; people make
personal access tokens on the Access tokens page; calls are rate-limited and logged. Learned on the way: in `mcp` 2.x tool annotations
are snake_case (`read_only_hint`), `AuthSettings` needs `issuer_url` even with only a token verifier (we give the BI's own address and
advertise no OAuth until the AMS issues tokens), the client takes an `httpx2` client so tests run it in-process with `httpx2`'s ASGI
transport, and the session manager must run in the host app's lifespan because a mounted app's own lifespan does not run (and only once
per instance). Verified with the SDK's real client, mutation checks, and a browser-made token over real HTTP against real Cube.

## 2026-10-27 — The MCP server, specified; person identity asked of the AMS

`docs/mcp-spec.md` (proposed): the MCP server is the official MCP SDK's `MCPServer` mounted in the API at `/mcp`, sharing the chat
agent's governed read tools, with one principal behind several issuers and data scope enforced in Cube. Learned on the way: in `mcp`
2.x the class once called `FastMCP` is `MCPServer`, and importing `mcp.server.fastmcp` fails; DNS-rebinding protection allows only
localhost unless the public host is listed. Person identity, role and scope from the AMS is requested as issue 10 (`for-ams`) and
recorded as proposal 5 in `docs/ams-contract-proposals.md`.

## 2026-10-27 — The administrator from the environment

`ADMIN_EMAIL`, `ADMIN_PASSWORD` (and `ADMIN_NAME`) make the first administrator at API start when that email has no account yet; an
existing account is never touched, so a later change of the variables or of the person's own password changes nothing. Setting only
one of the pair stops the start, and the password is a secret value that never shows in a repr, an error or the logs. Learned while
deploying a staging stack on Easypanel: its log aggregation needs a licence with advanced monitoring, so the panel's own log viewer is
the way to read container logs there.

## 2026-10-26 — Agent step 2a: ask questions, get charts

TASK-012 (DEC-015 to DEC-020): the agent answers questions in a chat. Pydantic AI 2.61 runs the loop in a worker job; five provider
kinds (Anthropic, OpenAI, OpenAI-compatible, OpenRouter, Ollama) are configured on an admin page with their model lists fetched and
each model tested for tool calls; keys are AES-GCM encrypted in the BI's database (`BI_SECRETS_KEY`); the chat streams over SSE from
PostgreSQL; the model's tools return schemas, profiles and aggregates with small counts hidden, never rows. Learned on the way:
Pydantic AI's `FunctionModel` needs a stream function to exercise the streaming path, consecutive `ModelRequest`s are merged and a run
can start from a stored user message, so every turn's end must leave valid history (`seal()` answers unfinished tool calls); tool
results arrive on `FunctionToolResultEvent.part`; a run's final status and final event must be written in one transaction or the SSE
stream can end before its last event; FastAPI route modules cannot use `from __future__ import annotations` with these dependencies;
input tokens accumulate over a loop (each request resends the history), so a turn's output limit is the real bound. A chart the agent
proposes first drew small counts that its table had hidden, because it used the chart page's unsuppressed route: caught in the
browser walk-through, fixed with a draft data route that hides them, and tested. Not yet verified: any live provider (Anthropic cache
and thinking settings, OpenRouter, Ollama); only a fake OpenAI-protocol server over real HTTP and scripted models. Next: 2b (the build
sandbox and approvals page, TASK-013).

## 2026-10-26 — The app shell

Phase 1 merged (#5). `scripts/make_env.py` makes `.env` with every secret generated. The app shell (ROADMAP-009, DEC-014): the
BI's own accounts and cookie sessions, uploads through a new `load` job, and a chart page that builds a chart definition (DEC-012)
from Cube's governed members. Learned: FastAPI cannot see a route's `Annotated` dependency defined inside a function when the module
uses `from __future__ import annotations` (it read the signed-in user as a query parameter); Cube's metadata has `shortTitle`
("Headcount") beside `title` ("Enrollment Headcount"). Still to do: sign-in throttling (TASK-010), accounts in the app (TASK-011).

## 2026-10-26 — Phase 1 closed

Pull request #4 merged (phases 0 and 1). Cube now connects as its own role, which reads `analytics` only (TASK-007): rule 5 holds
in the database, not only in Cube's model. Learned: in compose, Cube must wait for the API (which creates and grants its role) and the
worker for Cube's readiness (`/readyz`), or the first queries fail while Cube starts. The privacy rules and small-cell suppression
(TASK-002, TASK-008) now sit under ROADMAP-008 "First real data": they gate real data, not the pipeline.

## 2026-10-26 — Phase 1: the pipeline end to end, on made-up files

A file now goes all the way: raw (dlt, cells as text, the file kept unchanged), dbt (staging, analytics, data tests), Cube
(`enrollment_headcount`), and the worker answers the AMS from Cube (TASK-004, TASK-005; DEC-010, DEC-011). Learned on the way:
Cube in production mode needs Cube Store unless its cache and queue run in memory (one instance: memory); Cube 1.8 refuses
`renewQuery` and takes `cache: "must-revalidate"` in the request body instead; an all-empty column would vanish from raw unless every
header is declared as a text column; Cube answers numbers as text. Follow-ups: a read-only role for Cube (TASK-007), small-cell
suppression once the privacy rules are set (TASK-008, TASK-002).

## 2026-10-26 — Phase 0: the scaffold runs on Python

ROADMAP-001 done (TASK-001, DEC-003). The AMS adapter is now `src/bi`: FastAPI, Pydantic, Procrastinate, httpx, psycopg, with the
same behaviour as the TypeScript scaffold, which was removed. Learned on the way: a supply must leave out absent fields rather than send
`null` (the AMS's schema refuses null for optional fields), so `SupplyBody.wire()` drops top-level None and keeps null cells. Node
stays only for VEF.

## 2026-10-26 — Product direction recorded

Recorded the product as an AI-native BI platform that works on its own and with the AMS, from the Institutional Effectiveness Data
Architecture diagram (`docs/architecture.png`). Vision themes `governed-kpis`, `agent-built-bi`, `open-consumption`; decisions
DEC-002 to DEC-009 (one institution, Python, Cube as the only read path, warehouse layout, approval of agent work, the AMS requests,
first slice from real file exports, one API and MCP server); phases as ROADMAP-001 to ROADMAP-007; tasks TASK-001 to TASK-006.
`docs/architecture.md` was merged into `ARCHITECTURE.md`. Contract changes for the AMS are in `docs/ams-contract-proposals.md`.

## 2026-10-26 — Framework adopted

Adopted `vibe-engineering-framework` through `vef setup`; `vef check` confirmed deterministic core enforcement. Framework docs (VISION, ROADMAP, TASKS, DECISIONS) are the public reading surfaces over canonical records. Claude Code skills (`/tasks`, `/roadmap`, `/decisions`, `/bugs`, `/apply`) were installed in `.claude/skills/`.

## 2026-10-27 — Columns are discovered, not fixed

A real .xlsb export failed in dbt (`term_code` does not exist): the staging model was written for the made-up test shape. Now raw keeps the
file's own columns, `bi.mapping` matches them to the parts a dataset needs (own name, then the names exports use), a person approves a match
that is not exact (Uploads page), and dbt reads the approved mapping (DEC-026). A file whose layout cannot be read says which, instead of
a dbt error. Discovering the dataset itself and building new ones stays with agent step 2b (TASK-013).

## 2026-10-28 — Connect data: spec

Uploads become one type of source. `docs/connect-data-spec.md` proposes sources with a connector interface (`spec`, `check`, `discover`,
`read`, the Airbyte protocol's shape, built on dlt), discovery in layers (metadata at the source; header rows found in spreadsheets;
profiles, sensitive columns and keys computed inside the BI; mapping by names, profiles and the agent), mappings per layout, and
delivery in steps C1 to C5. Draft for review; decisions to be recorded once approved.

## 2026-10-28 — Connect data: what dlt gives us

Read the dlt documentation in full (1.31; sources, schema, naming, contracts, incremental, data quality, dataset access, dltHub, release
notes) and revised the spec (§ 4). dlt covers connecting and structural discovery: `sql_database` with `discover_schema()` (reflection,
no rows), `filesystem` (Drive, S3, Azure, SFTP, paths; no Excel reader, no SharePoint), Google Sheets (header must be the first row of a
range), `rest_api` with `dlt-init-openapi`, `inbox`. Frozen schema contracts catch layout changes; unmapped personal columns can be left
out of database reads. Header detection, profiles and sensitive-column classification stay ours. dltHub (paid) data quality and MS SQL
change tracking are licensed for its platform only and are not used.
