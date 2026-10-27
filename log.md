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
