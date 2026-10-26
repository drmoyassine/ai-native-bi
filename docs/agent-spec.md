# Spec: the agent — runtime, loop and chat (ROADMAP-003)

Status: **proposed, 2026-10-26.** Decisions below become DEC records once approved (§ 12). Builds on ARCHITECTURE.md, DEC-004 (Cube is the
only read path), DEC-006 (a person approves what the agent builds), DEC-012 (one chart definition), DEC-013 (drafts and publishing),
DEC-014 (the app).

## 1. What the agent is for

The agent is how people use the BI (vision theme `agent-built-bi`). In the app's chat, a signed-in person asks it to:

| Job | Example | What the agent produces |
|---|---|---|
| **Answer** | "How many bachelor students did we enroll per program in Fall 2026?" | An answer from governed KPIs, with the numbers' as-of date and lineage, and a chart |
| **Chart** | "Chart headcount by level over the last six terms" | A chart definition (DEC-012), a private draft (DEC-013) |
| **Connect a source** | "Load the registrar's enrollment export" / "Connect Banner" | An integration draft: dlt source, dbt models, tests, run and checked in the sandbox, then proposed |
| **Define a KPI** | "Define retention the way the self-study does" | A KPI draft: dbt model and Cube definition, with its test results, then proposed |

It never publishes, deploys or approves anything. What it builds is a draft until a person approves it (DEC-006, DEC-013).

## 2. Requirements

1. **Governed reads only.** Every number comes through Cube (rule 5); structured queries, never SQL against warehouse tables.
2. **Nothing student-level reaches the model.** The model provider is outside the BI, so rule 5's "nothing student-level leaves the BI"
   covers it: tools return schemas, profiles and suppressed aggregates, never rows about a person (§ 7).
3. **Drafts, then approval.** Building happens in a sandbox; anything live (an integration, a KPI, a published chart) needs a person's
   approval through the app, not through the chat.
4. **Acts as the person.** The agent has the signed-in person's permissions, never more; every tool call is recorded as "the agent,
   on behalf of <person>".
5. **Credentials never enter the model's context**, the code it writes, the repository or logs (rule 6).
6. **Streams.** The chat shows text as it is written, what the agent is doing (tool activity, progress notes), and its results
   (tables, charts, proposals) as they arrive; a turn survives a closed tab and resumes on reconnect.
7. **Bounded.** Each turn has an iteration cap and a token budget; each person a monthly budget; usage is recorded per turn.
8. **Same tools outside the app.** The tools the chat agent uses are the ones the MCP server offers to outside agents later (DEC-009),
   defined once.

## 3. Runtime: where the loop runs

### Options

| | Owns the loop | Tool execution | Fit for the BI |
|---|---|---|---|
| **A. Claude API + SDK tool runner, in our worker** (recommended) | The Anthropic Python SDK's tool runner (`client.beta.messages.tool_runner`), in a Procrastinate job | Our tools in our process; code in **our** sandbox container | Every tool is ours and gated by our code; chat events go through our database; nothing new to operate |
| B. Claude API, manual loop | Our own `while stop_reason == "tool_use"` | Same as A | Same as A, more code; only if the runner's hooks stop fitting |
| C. Managed Agents, self-hosted sandbox | Anthropic's orchestration layer | Bash and files in our container, via an outbound-polling worker; our custom tools round-trip through its event stream | Versioned agent configs, sessions and reconnectable streams for free; but most of our tools are custom and gated, each a round trip; beta |
| D. Claude Agent SDK (Claude Code as a library) | The Claude Code harness | Built-in Read/Write/Bash in the host it runs on | Excellent at writing code; to keep it from the credentials and the network it would itself have to run inside the sandbox, with the API key there too |

**Decision proposed: A.** The BI's agent is mostly *our* tools (Cube queries, profiles, drafts, proposals), each of which must be checked
against the person's permissions, the privacy rules and the approval rules. That is natural when our code runs the loop. The runner
yields every assistant message before its tools run, which is where we persist it, check `stop_reason` and gate tools; it supports
streaming. Option C stays the candidate for long, unattended builds (§ 11, 2c) if the sandbox protocol and versioned configs start to
pay for themselves. D is revisited only for the builder (§ 6) if code quality there falls short.

### Shape

```
browser ──POST /app/api/conversations/{id}/messages──▶ API: stores the message, queues an `agent_turn` job ──▶ 202
browser ◀──GET  /app/api/conversations/{id}/events (SSE, Last-Event-ID)── API: tails agent_event (LISTEN/NOTIFY)
                                                       worker: `agent_turn` job
                                                         tool runner (stream) ──▶ Claude API
                                                           ├─ text / progress / tool activity ──▶ agent_event (append) + NOTIFY
                                                           ├─ each assistant message + tool results ──▶ conversation_message (append)
                                                           └─ tools: Cube · catalog · drafts · sandbox (bash, editor, run tests)
```

- **The loop runs in the worker**, one `agent_turn` job per user message (a new Procrastinate queue, `agent`), so a turn survives the
  browser closing, the API restarting, and scales apart from the API.
- **The API never calls the model.** It stores the message, queues the turn and streams events.
- **One turn at a time per conversation** (a Procrastinate lock on the conversation id); a message sent during a turn waits for it.
- **Interrupt:** `POST .../interrupt` sets a flag the job checks between iterations; the turn ends with what it has, recorded as
  interrupted. Tools in flight finish or time out (§ 6 limits).

## 4. The loop

Per `agent_turn` job:

1. Load the conversation's messages **exactly as stored** (append-only: § 8).
2. Run the tool runner with `stream=True` over the tool set of the conversation's mode (§ 5), the frozen system prompt, and:
   - **model** `claude-opus-5-5` (configurable: `AGENT_MODEL`);
   - **thinking** adaptive (the model's default), `display: "updates"` (beta `thinking-display-updates-2026-08-18`) so the chat shows
     short progress notes between tool calls, never the reasoning itself;
   - **effort** set explicitly per mode (Opus 5.5 defaults to `medium`): `medium` for answering and charting, `high` for building;
   - **max_tokens** 64000 (streamed);
   - **task budget** (beta `task-budgets-2026-03-13`) per turn: 64K tokens for answers, 400K for builds;
   - **refusal fallbacks** on by default: `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`); a final `refusal` ends the
     turn with a plain message, never tool calls from that turn;
   - **tool_choice** `auto` (Opus 5.5 refuses forced tool use); tools `strict: true`; tools whose input is large (file contents) carry
     `eager_input_streaming: true`, and every input is validated against its schema before it runs.
3. For each streamed turn: forward text deltas, progress notes and tool-call starts to `agent_event`; on the final message, append it
   to `conversation_message` **before** any tool runs; stop without running tools on `max_tokens` with a pending `tool_use` or on
   `refusal`; otherwise let the runner run the tools and append the tool-result message.
4. Stop at `end_turn`, the iteration cap (30 for answers, 150 for builds), the task budget, an interrupt or an error. Record usage
   (input, cache read/write, output) on the `agent_run`.
5. On an error (API down, worker killed): the run ends `failed` with the reason; the conversation keeps every message appended so far,
   and the next user message continues from there. No automatic retry of a half-done turn (tools may have had effects in the sandbox).

**Context:** compaction (beta `compact-2026-01-12`) when a conversation grows past 150K tokens, and clearing old tool results
(`clear_tool_uses_20250919`): profiles and sandbox outputs are bulky and soon stale. Both keep the history append-only.

## 5. Tools

Defined once in `src/bi/agent/tools.py` as typed functions (the runner's `@beta_async_tool`), each with a description that says *when*
to call it. The same registry backs the MCP server later (DEC-009). Every tool checks the person's permissions and writes an audit
event.

| Tool | Mode | Does | Returns to the model |
|---|---|---|---|
| `list_metrics` | all | Cube's governed measures and dimensions (`/meta`) | Names, titles, descriptions, types |
| `query_metric` | all | A structured Cube query (the `query` part of a chart definition) | Aggregated rows with small cells suppressed (TASK-008), as-of date, lineage |
| `propose_chart` | all | Saves a chart definition as the person's private draft | The draft's id; the chat renders it |
| `list_datasets` / `describe_dataset` | all | The catalog: datasets, their raw and analytics tables, last loads | Columns, types, null rates, distinct counts, ranges, top values with counts at or above the threshold; never rows (§ 7) |
| `list_uploads` | build | Files the person uploaded (DEC-011) | Name, sheet names, headers, row count, profile |
| `bash` · `str_replace_based_edit_tool` | build | Anthropic-defined client tools, executed **in the sandbox only** (§ 6) | Output, scrubbed of credentials and capped in size |
| `run_integration_test` | build | Runs the draft's dlt pipeline into the sandbox's scratch schema, then `dbt build` there | Row counts, dbt test results, profiles of the result; never rows |
| `request_credentials` | build | Asks the person to enter a secret in a form in the chat | A handle (`secret://banner-prod`), never the value |
| `propose_integration` / `propose_kpi` | build | Freezes the draft (files, test report) and opens an approval request | The request's id and link |

Not tools, on purpose: running SQL; reading raw or analytics tables; publishing, deploying or approving; anything outside the
sandbox's file system; the web (no `web_search`/`web_fetch` in v1: the model works from the institution's data and its own knowledge).

**Modes.** A conversation is *ask* (answer, chart) or *build* (everything). The tool set is fixed per mode for the whole conversation
(changing tools mid-conversation breaks the prompt cache); switching mode starts a new conversation that links back.

## 6. The builder's sandbox

Code the agent writes (dlt sources, dbt models, Cube definitions) runs only here.

- **One container per build conversation**, from a BI-built image: Python 3.12, dlt, dbt-core and dbt-postgres, the BI's ingest helpers,
  no compilers beyond those, no package installs at run time (an allow-listed internal mirror later, if needed).
- **Files:** a work directory per draft (`/work/<draft>`) on a volume; the editor tool and bash are confined to it (paths resolved and
  checked against the root, rejected otherwise).
- **Database:** a scratch database per conversation with its own role; raw, staging and analytics live there for the tests. It cannot
  reach the BI's database.
- **Network:** deny by default; the hosts of the sources being connected are opened per draft (e.g. Banner's API host) when the person
  confirms them. The model provider is never reachable from the sandbox.
- **Credentials:** a credential handle in the draft's config is turned into an environment variable by the sandbox runner when it
  starts a test; the value is never written to files the agent can read, and every tool output is scrubbed of it before it returns.
- **Limits:** per command 120 s, per test run 15 min, 2 CPU, 4 GB memory, 10 GB disk; bash commands logged; the container is stopped
  when the conversation idles for 30 minutes and removed after 14 days.
- **Runner:** a small service on the host (`bi-sandbox`) that the worker calls to create, exec in, copy from and stop containers; the
  worker itself has no access to the Docker socket.

## 7. Data the model may see

The model provider is outside the BI. What crosses to it is decided by the tools, not by the prompt:

| Allowed | Never |
|---|---|
| Column names, types, null rates, distinct counts, numeric ranges | A row about a person, from raw, staging, analytics or an upload |
| Categories and their counts at or above the suppression threshold (TASK-002) | Identifiers (IDs, names, emails, birth dates) or their values in any form |
| Aggregates from Cube, suppressed | Credentials |
| dbt test results and counts; errors (scrubbed) | Free text from records (comments, notes) |

Identifier columns are detected by name and by profile (unique per row) and reported only as "identifier, n distinct". Test failures
report counts and column names, not the failing rows. Sandbox command output passes the same scrubber.

**Before real data (ROADMAP-008)** the institution decides: the provider's data processing terms and retention, whether to pin
inference geography (`inference_geo`), and the suppression threshold the tools use.

## 8. Conversations and storage

Migration `0005_agent.sql`:

| Table | Holds |
|---|---|
| `conversation` | id, owner, mode (ask, build), title, model, created_at, archived_at |
| `conversation_message` | conversation, seq, role, **content (jsonb, exactly as sent or received)**, created_at. Append-only |
| `agent_run` | one per turn: status (queued, running, done, failed, interrupted), stop reason, iterations, usage, error, timings |
| `agent_event` | bigserial id, run, conversation, type, payload: what the chat streams (§ 9); kept 30 days |
| `draft` | kind (integration, kpi, chart, dashboard), owner, built_by (person or agent), files or definition, test report, state |
| `approval` | draft, requested_by, status (pending, approved, rejected), decided_by, decided_at, note |
| `secret` | handle, encrypted value (AES-GCM, key `BI_SECRETS_KEY` from `make_env.py`), created_by, last_used_at |

**Append-only history is required, not a preference:** Opus 5.5 ties thinking blocks to the exact conversation that produced them, so
an edited earlier turn invalidates them. Messages are never edited or deleted; "forget this" archives the conversation.

## 9. The chat

**API** (`/app/api`, same session and `X-BI-App` rules as DEC-014):

| Route | Does |
|---|---|
| `GET /conversations`, `POST /conversations` (mode) | List, start |
| `GET /conversations/{id}` | Messages rendered for display (not the raw API content) |
| `POST /conversations/{id}/messages` | Store the person's message, queue the turn; 202 |
| `GET /conversations/{id}/events?after=` | Server-sent events; resumes from `Last-Event-ID` |
| `POST /conversations/{id}/interrupt` | Stop the running turn |
| `POST /conversations/{id}/credentials` | The secret form's answer: stored, the handle returned to the turn |

**Events:** `turn.started`, `text.delta`, `progress` (the model's progress notes), `tool.started` (name, short summary of the input),
`tool.finished` (ok or error, short summary), `result.table`, `result.chart` (a chart definition, drawn by `web/src/chart.ts`),
`result.proposal` (a link to the approval), `credentials.requested`, `turn.finished` (stop reason, usage), `turn.failed`.

**Screen:** a conversation list; the thread with streamed text, progress lines, collapsible tool activity, inline tables and charts and
proposal cards; a stop button; the secret form when asked; a budget line. Approvals get their own page (approve, reject, note), outside
the chat, so no chat message can approve anything.

## 10. Prompt caching and cost

- **Frozen prefix:** the tool list (sorted, fixed per mode) and the system prompt (role, rules of § 2 and § 7, the BI's conventions)
  never change within a conversation; nothing per-request (dates, names, catalog) goes in them. One `cache_control` breakpoint on the
  system prompt, and top-level automatic caching for the growing conversation.
- **Volatile context** (today's date, the person's name and permissions) goes in the first user turn; changes during a conversation
  are mid-conversation system messages, which keep the cache.
- **The catalog is a tool** (`list_metrics`, `list_datasets`), not prompt text, so it can change without breaking the cache.
- **Check:** `cache_read_input_tokens` is recorded per turn; a turn after the first with zero cache reads is logged as a warning.
- **Budgets:** per turn (task budget, iteration cap), per person per month (`AGENT_MONTHLY_TOKENS`, a refusal message when spent).

## 11. Delivery

| Step | Contents | Done when |
|---|---|---|
| **2a. Ask** | Tables, the loop in the worker, events and SSE, the chat screen, `list_metrics`, `query_metric`, `propose_chart`, `list_datasets`, `describe_dataset`; the scrubber; usage | A person asks a KPI question and gets a governed answer and a chart; no row ever reaches the model (tested) |
| **2b. Build from a file** | The sandbox runner and image, build mode, `bash`, editor, `list_uploads`, `run_integration_test`, `propose_integration`, approvals page | From an uploaded export, the agent drafts dlt and dbt code, tests it, proposes it; a person approves it; it runs in production |
| **2c. Connect a system** | `request_credentials`, the secret store, per-draft egress; Banner first (DEC-008/011) | Banner connected end to end from the chat |
| **2d. Define a KPI** | `propose_kpi`: dbt model and Cube definition, steward approval | A new KPI approved and queryable through Cube and the AMS |

Each step ships behind its own pull request, with an eval set of real requests (built with the Claude API skill's `build-eval` flow) to
catch regressions in tool choice and answers.

## 12. Decisions to record once approved

1. Runtime A: the SDK tool runner in a worker job; the API never calls the model (§ 3).
2. The model sees schemas, profiles and suppressed aggregates only (§ 7).
3. Our own sandbox for code the agent writes, deny-by-default network, credentials by handle (§ 6).
4. Conversations append-only, events through PostgreSQL and SSE (§ 8, § 9).
5. Approvals outside the chat (§ 9).

## 13. Questions for you

1. **Data with the model provider:** is the default of § 7 right (no rows at all), or may the agent see masked samples while building?
   And is there a data processing agreement, or a residency requirement (`inference_geo`)?
2. **Who approves:** any admin, or a steward per dataset (the registrar for enrollment)?
3. **Where approved integrations live:** as versioned bundles in the BI's database, materialized at deploy (proposed), or in a git
   repository the BI commits to?
4. **Secrets:** an encrypted table in the BI's database for now (proposed), or the institution's vault from the start?
5. **Budget:** a monthly token budget per person, or one for the institution?
6. **Language:** should the chat answer in Arabic as well as English (the calendar already has Arabic names), and the app read
   right to left?
