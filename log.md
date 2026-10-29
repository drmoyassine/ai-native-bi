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

## 2026-10-28 — Connect data: every source through dlt

Spec § 4: a source type dlt lacks (Excel files, SharePoint, an API without OpenAPI, a system with neither API nor database) is written
as a dlt source, resource or transformer, never a loader beside dlt, so each gets the same loading, contracts, lineage and incremental
state. Header detection, profiles and classification stay outside dlt, as do documents to parse and the AMS contract.

## 2026-10-28 — Connect data: questions answered

Spec § 13: order files, APIs, Oracle, PostgreSQL, the rest; a BI admin approves sources until there are stewards; databases load
incrementally with dlt's `scd2` merge and a slower full read for deletes; draft data in a `draft_<source>` schema; raw switches to
`duck_case` naming. Tried on PostgreSQL: with dlt's default `snake_case`, two Arabic headers both became `x` and one column's values
were lost without an error (today's upload path has this flaw; C1 fixes it). dlt 1.31.0 is the latest release and already in use.

## 2026-10-28 — Connect data C1: file sources

Uploads became Connect data (TASK-022, DEC-027 to DEC-031). A file source keeps each file, finds the table in its sheet (title rows,
two-row headers, total rows; a person can pick the row), profiles the columns in PostgreSQL (kinds, personal data never shown as values,
shapes and ranges), and matches them to the dataset's parts by name, label, alias and fit. A layout nobody approved waits in `draft`;
a BI admin approves it on the source's page and it loads into `raw.<source>`, named as written. dbt unions every approved input from
loaded syncs, so a file that fails the tests stays in raw but does not count. Migration 0010 turns uploads into syncs to load again.
Walked through in a browser with a made-up export shaped like the real one (title rows, other names, an email and an Arabic column).

## 2026-10-28 — Agentic BI benchmark

`docs/agentic-benchmark.md`: what Databricks, Microsoft Fabric and Power BI, Snowflake, Tableau Next, Looker, ThoughtSpot, Databox, dbt,
Hex and Monte Carlo ship as agents in 2026, where the BI stands, and a staged roadmap: context and trust (knowledge store, verified
questions, benchmarks, documentation, ontology), agents in Connect data, the analyst agent, the watcher, reach and act. Draft for
discussion.

## 2026-10-28 — Masked samples in setup (DEC-032)

The owner accepts sending a few rows to the model during discovery, configuration and drafting. DEC-032 amends DEC-017 for setup only:
up to 20 random rows per table, personal and free-text columns replaced by made-up values of the same shape, identifiers re-digited;
only an admin's setup work, only to providers an admin marks "may see sample rows" (off by default), logged and shown to the person.
Asking, charts, MCP and the watcher keep the no-rows rule. CLAUDE.md, the agent and Connect data specs updated.

## 2026-10-28 — Specs: context and trust, the setup agent

`docs/context-spec.md` (stage A): a knowledge store read by every agent (instructions and glossary in the prompt, descriptions and
synonyms in the tools, `search_knowledge`), verified questions marked Trusted, benchmarks scored from tool calls, documentation the
agent drafts, and an ontology file replacing `SHAPES`. `docs/setup-agent-spec.md` (stage B): masked samples under DEC-032 (masking by
profile kind, rare categories hidden, logged and shown) and mapping proposals with reasons, as one structured call in the worker.
Drafts for review.

## 2026-10-28 — K1 revised: knowledge is part of the metric definition, in Cube

The owner asked that K1 and metric definitions be the same thing, in Cube. Checked on a throwaway Cube 1.8: `/meta` returns nested `meta`
(lists, Arabic text) for measures, dimensions and views. So titles, descriptions, explanations and synonyms (English and Arabic) live on
each member, and the glossary and instructions in an `institution` view; no knowledge table or Knowledge page. The steward approves by
approving the pull request; CI checks completeness and personal-data-looking text; a read-only Metrics page shows definition and meaning
together. DEC-033, TASK-027 and `docs/context-spec.md` § 4 updated.

## 2026-10-29 — K1 built: metric knowledge in Cube, and the AMS reads the same catalogue

The Cube model now carries Arabic titles and descriptions on every member, and synonyms and an explanation on headcount. The
`institution` view holds the glossary and instructions (a view must be public to appear in `/meta`; the BI filters it from the metric
list). `list_metrics` returns the words, `search_knowledge` finds a metric or glossary term in either language (Arabic spelling variants
and typos forgiven), the chat prompt carries the instructions and glossary, and a read-only Metrics page shows them. The hard-coded
`METRICS` table is gone: a measure is answerable to the AMS when it declares `meta.metric`, with period, dimensions, as-of and lineage
read from Cube. CI checks completeness and personal-data-looking text. `docs/ams-contract-proposals.md` § 7 drafts a request for a
metrics catalogue route. TASK-027 completed; next in stage A: K2 verified questions (TASK-028).

## 2026-10-29 — Spec: the data model (subject areas, entities, events)

The owner asked how Banner through an API, the student life cycle (application to employment), staff, courses and events fit together.
`docs/data-model-spec.md` sets the hierarchy: a source per system connection and a stream per table or endpoint; an ontology of subject
areas (each with a steward), entities and events that streams map onto (proposed after the first read, not asked on the form); a
warehouse in four layers (raw, staging generated from mappings, core with shared dimensions and one fact per event, marts for life
cycles); Cube views per subject area and lens; rates on cohorts; people matched across systems inside the warehouse. DEC-036; K5 becomes
step M1 (TASK-031), M2 to M6 are TASK-034 to TASK-038. Draft for review, with six open questions (cohorts, census, applicant IDs,
employment survey, next subject, history).

## 2026-10-29 — The rule: agnostic and configuration-driven, no compromise

The owner rejected institution-specific choices in the data model spec (cohort rules, census, which subject next) and set a rule
without exception: the BI is agnostic of organisation and industry and driven by configuration throughout. `docs/data-model-spec.md`
rewritten: subjects, entities, events, cohorts (a cohort builder) and metrics (a metric builder) are defined in the app and approved by
the subject's steward; dbt and Cube models are generated from them; the organisation's languages, calendar and personal-data patterns
are settings; domain content (today's university enrollment, Arabic handling) moves into a template and a language pack, which are data.
A CI check will fail on domain words in code. DEC-037 (the rule, also CLAUDE.md rule 0), DEC-036 revised (supersedes DEC-034); M0 is
TASK-040 (P0), M1 to M7 are TASK-031 and TASK-034 to TASK-039.

## 2026-10-29 — The AMS's patterns and look adopted (DEC-038)

Cloned the AMS read-only and took its patterns: configuration is data, never code (its "frameworks are data" rule); one code path
tested on several templates, one right-to-left; versioned definitions; small JSON rules, no rule engine; a language registry with
English plus one secondary language; interface text through t() over an English catalogue; the organization's accent colour. Built
in the BI: organization settings (migration 0012: name in both languages, secondary and default language, accent colour; each
person's interface language), `/app/api/public/branding`, `/organization`, `/me/language`, `/languages`; the web app on Tailwind with
the AMS's oklch tokens, script font stacks, Button, Card and Input, its sidebar shell with a drawer on small screens, its sign-in
page, and a Settings → Organization page. Older pages keep their class names restyled on the tokens; the dark theme is gone (the AMS
has none). Checked in a browser: sign-in, settings, Connect data, Arabic right to left, the drawer at phone width.

## 2026-10-29 — M0a: the built-in domain moved out of the code

`src/bi/packs` holds everything about a language or a domain, as data: language packs (English and Arabic: words that suggest
personal, identifying or total rows; made-up names and letters for masking; folding for search), the language registry, and the
higher-education template (the enrollment dataset's parts, labels and aliases, formerly `SHAPES`). Code applies any pack and names
none. Organizations install templates in Settings (migration 0013); without one, nothing can be fed; the API installs at start any
template whose datasets streams already feed, so staging keeps working. Metric words are keyed by language code
(`meta.translations`, glossary `{term, meaning}` by language); the glossary view is found by its meta, not its name. "Institution"
became "organization" (`AGENT_ORGANIZATION_MONTHLY_TOKENS`, the old name read for one release). `tests/test_agnostic.py` fails on a
domain word or a language's letters outside packs; the files waiting for M0b (the template's dbt and Cube models) are listed and the
list can only shrink. TASK-040 completed; M0b is TASK-041.

## 2026-10-29 — Settings regrouped; M1 definitions and M0b generated models

Settings now holds Organization, Your account (password), Access tokens (MCP) and Models, with the AMS's side menu; the sidebar keeps
the work pages. M1: `definition` (migration 0014) stores subjects, entities and events as versioned JSON bodies checked by
`bi.definitions` (parts with kinds, words by language, grain, snapshot_by); a change is a draft until an admin or the subject's steward
approves it; `/app/api/model` lists, drafts and approves. Installing a template creates its definitions (never over the organization's
own) and writes its Cube files; uninstalling retires them. M0b: the hand-written enrollment dbt models are gone; `bi.generate` writes
staging, analytics and tests for every approved event into a copy of the dbt project at each build; the enrollment Cube files moved into
the template, and Cube reads them from `cube_model.file` through `cube/cube.js` (reloading when they change). The waiting list of
`tests/test_agnostic.py` is gone. Tests run a second, unrelated domain (a service desk's tickets) through definitions, loading,
generation and dbt. TASK-031 and TASK-041 completed.

## 2026-10-29 — C2a: REST API sources

An admin connects an API on Connect data: base URL, how it signs in (bearer token, API key in a header, username and password; the
credential goes to the secret store and is never shown again), the endpoints (each a stream, read with GET page by page through dlt's
`rest_api`; where the items are when they are not the whole response) and what each feeds, and a schedule (hourly, daily or on
request). A read flattens nested fields to `parent__child` and goes through the same draft, profile, mapping and review path as a file
(migration 0015: `api` sources, `sync.endpoint`). A periodic job queues due reads of live sources. Found by the test: re-queueing after
approval only accepted syncs with a stored file. Checked in a browser against a local paged API: connected, read, reviewed, approved,
built; a second read loaded on its own. Drafting configurations from OpenAPI, incremental reads and frozen contracts are C2b (TASK-042).

## 2026-10-29 — Merged and deployed; a slow Cube start; the plan from here

PR #26 (Settings, M1, M0b, C2a) merged and deployed. The first deploy failed: Cube came up a little after its healthcheck gave up
(20 checks every 5 s, no grace period), and the stack started on its own shortly after. Cube's healthcheck now has a 120 s grace period
(#27). The AMS's contract sync of 2026-10-27 (6.2 person identity, 6.3 co-deployment) had never been merged; `contract.py` already
matched it, so it merges as is (#28). Order from here (data model spec § 13): the Model page (M3), the organization calendar
(TASK-043), the metric builder (M5), the cohort builder (M6), then the rest of M2, M4, M7, C2b and database sources.

## 2026-10-29 — Column decisions at review (C1b) and derived parts (M3)

A real export on staging showed "Civil ID" classed as a plain identifier: the English pack had no word for it. The packs now also know
civil, citizen, identity, NIN, visa, residency, licence, IBAN, nationality's short "NAT.", religion, ethnicity, health and others (and
Arabic مدني). The owner asked what a person should decide before approving a stream. Specified (connect data spec § 6.7, TASK-044, P0):
personal (identifying, describing or not, with a reason), keep or leave out, kind with validation, labels and descriptions, row key with
checks, the as-of column; cadence on the source. Derived columns belong to definitions (derived parts of an event: group values, join,
a date's period, arithmetic, buckets, first non-empty; data model spec § 6) or to metrics, not to a source; they are part of M3.

## 2026-10-29 — C1b built: column decisions at review

Before approving a stream, an admin decides each column (migration 0016, `stream_column`; `PUT /app/api/syncs/{id}/columns`):
personal (identifies, describes, not personal; moving away from "identifies" needs a reason, kept with the name), keep or leave out
(a left-out column never reaches raw; identifying columns nothing uses are proposed for leaving out), the kind (checked against the
values: how many do not fit, by shape), a label, and the row key (checked for empty parts and repeats). The profile applies the
decisions, so masking and mapping follow them, and every later sync of the stream keeps them. Language packs now tell describing
words (gender, nationality, religion, age) from identifying ones, so Gender and NAT. are kept and counted instead of proposed for
leaving out. Checked in a browser on an export shaped like the real Banner file. Still to do: the as-of column and the expected cadence of
file sources.
