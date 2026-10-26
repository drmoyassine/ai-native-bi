# Spec: the agent — runtime, loop and chat (ROADMAP-003)

Status: **proposed, 2026-10-26; revised for Pydantic AI and any model provider.** Decisions below become DEC records once approved (§ 12). Builds on ARCHITECTURE.md, DEC-004 (Cube is the
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
9. **Any model provider.** Claude (through Anthropic, Bedrock, Vertex or Foundry), OpenAI, OpenRouter, or a model the institution hosts
   (vLLM, Ollama) is a setting, not a rewrite; the best model per job is chosen by the eval set (§ 11).

## 3. Runtime: where the loop runs

### Options

| | Owns the loop | Models | Fit for the BI |
|---|---|---|---|
| **A. Pydantic AI, in our worker** (chosen) | Pydantic AI's `Agent`, driven step by step (`agent.iter`) in a Procrastinate job | Anthropic, Bedrock, Google, OpenAI, Azure, OpenRouter, Ollama, vLLM, LiteLLM, … through one interface | Our stack (Pydantic, typed tools, async); every tool is ours and gated by our code; tool approval and deferred tools built in; provider-specific settings where they exist |
| B. A provider's own SDK loop (the Anthropic SDK's tool runner) | The SDK | One provider | The fullest access to one provider's features; but tied to it |
| C. Our own loop over thin adapters | Our code | The providers we write adapters for | Full control; a few hundred lines to own and keep current |
| D. A hosted agent service (Claude Managed Agents) or a coding harness (Claude Agent SDK) | The service or harness | One provider | Strong for long unattended coding; tied to one provider, and our gated tools become round trips |

**Decision proposed: A** (chosen by the owner, 2026-10-26). Pydantic AI keeps the loop provider-neutral and in our process, where each
tool can be checked against the person's permissions, the privacy rules and the approval rules. What it does not abstract stays
available: each provider's own settings (§ 4) and, if ever needed, a provider's SDK directly behind a custom `Model`.

**Pin and verify.** Pydantic AI moves fast: pin its exact version, and keep a contract test per provider in use (§ 11) that runs a
multi-turn conversation with tool calls and checks the replayed history is accepted, notably Claude's thinking blocks, which Claude
Opus 5.5 checks against the exact history that produced them.

### Shape

```
browser ──POST /app/api/conversations/{id}/messages──▶ API: stores the message, queues an `agent_turn` job ──▶ 202
browser ◀──GET  /app/api/conversations/{id}/events (SSE, Last-Event-ID)── API: tails agent_event (LISTEN/NOTIFY)
                                                       worker: `agent_turn` job
                                                         Pydantic AI Agent.iter(...) ──▶ the model provider of the conversation
                                                           ├─ text / thinking updates / tool calls ──▶ agent_event (append) + NOTIFY
                                                           ├─ each model response and tool return ──▶ conversation_message (append)
                                                           └─ tools: Cube · catalog · drafts · sandbox (commands, files, run tests)
```

- **The loop runs in the worker**, one `agent_turn` job per user message (a new Procrastinate queue, `agent`), so a turn survives the
  browser closing, the API restarting, and scales apart from the API.
- **The API never calls a model.** It stores the message, queues the turn and streams events.
- **One turn at a time per conversation** (a Procrastinate lock on the conversation id); a message sent during a turn waits for it.
- **Interrupt:** `POST .../interrupt` sets a flag the job checks between steps; the turn ends with what it has, recorded as
  interrupted. Tools in flight finish or time out (§ 6 limits).

### Models and providers

A conversation is pinned at its start to one model, written as Pydantic AI writes it (`provider:model`), from settings per mode:

| Setting | Default | Examples |
|---|---|---|
| `AGENT_MODEL_ASK` | `anthropic:claude-opus-5-5` | `bedrock:…`, `openai:…`, `openrouter:…`, `ollama:…` |
| `AGENT_MODEL_BUILD` | `anthropic:claude-opus-5-5` | the strongest coding model the eval set finds |
| `AGENT_BASE_URL`, provider keys | none | a self-hosted OpenAI-compatible server (vLLM); keys from the environment, never in code |

Switching model applies to new conversations: tool-call formats and reasoning state differ between providers, and Claude's history must
stay exactly as produced. Where the data goes depends on this choice (§ 7):

| Route | Data path |
|---|---|
| Anthropic API | Anthropic, under its terms |
| Bedrock / Vertex / Foundry | The institution's cloud account, region and terms |
| OpenAI / Azure OpenAI | OpenAI or Microsoft, under their terms |
| OpenRouter | OpenRouter **and** the upstream provider it routes to; pin upstream providers in its settings |
| vLLM / Ollama on the institution's servers | Nowhere: the only route on which nothing leaves the institution |

## 4. The loop

Per `agent_turn` job:

1. Load the conversation's messages **exactly as stored** (Pydantic AI's `ModelMessage` list, § 8; append-only).
2. Drive `agent.iter(user_message, message_history=..., usage_limits=..., model_settings=...)` node by node, with the mode's toolset
   (§ 5), the frozen instructions, and:
   - **usage limits** per turn (`UsageLimits`): requests (30 to answer, 150 to build) and total tokens (64K to answer, 400K to build);
   - **common settings:** `max_tokens` 64000, `parallel_tool_calls` on, streaming always;
   - **Claude settings** when the model is Claude: thinking adaptive with `display: "updates"` (progress notes, never the reasoning),
     `anthropic_effort` set explicitly (`medium` to answer, `high` to build; Opus 5.5 defaults to `medium`), `anthropic_task_budget` as
     the token limit above, the three `anthropic_cache_*` settings (§ 10), `anthropic_context_management` (compaction and clearing old
     tool results, § below), `anthropic_eager_input_streaming` for large tool inputs, and refusal fallbacks (`fallbacks: "default"`
     with beta `server-side-fallback-2026-07-01`, through `extra_body` and `anthropic_betas`) where the route supports them;
   - **OpenAI-compatible settings** when the model is: `openai_reasoning_effort` per mode, `openai_prompt_cache_key` per conversation;
   - **tool choice** automatic (some models, Claude Opus 5.5 among them, refuse forced tool use); tool inputs are validated against their
     schemas by Pydantic before any tool runs.
3. At each node: stream text, thinking updates and tool calls to `agent_event`; when the model's response is complete, append it to
   `conversation_message` **before** its tools run; when the tools return, append their results. A response cut off at its token limit
   or refused runs no tools.
4. Stop when the model ends its turn, at a usage limit, an interrupt, a deferred tool (§ 5: waiting for the person) or an error; record
   usage (input, cache read and write, output) on the `agent_run`.
5. On an error (provider down, worker killed): the run ends `failed` with the reason; the conversation keeps every message appended so
   far, and the next user message continues from there. No automatic retry of a half-done turn (tools may have had effects in the
   sandbox).

**Long conversations:** on Claude, compaction and clearing old tool results (profiles and sandbox outputs are bulky and soon stale); on
other providers, a Pydantic AI history processor that drops old tool returns past a size. Neither edits stored messages.

## 5. Tools

Defined once in `src/bi/agent/tools.py` as typed async functions in a Pydantic AI `FunctionToolset` (Pydantic validates every input),
each with a docstring that says *when* to call it. The same functions back the MCP server later (DEC-009), served with the MCP SDK.
Every tool checks the person's permissions (from the run's dependencies) and writes an audit event.

| Tool | Mode | Does | Returns to the model |
|---|---|---|---|
| `list_metrics` | all | Cube's governed measures and dimensions (`/meta`) | Names, titles, descriptions, types |
| `query_metric` | all | A structured Cube query (the `query` part of a chart definition) | Aggregated rows with small cells suppressed (TASK-008), as-of date, lineage |
| `propose_chart` | all | Saves a chart definition as the person's private draft | The draft's id; the chat renders it |
| `list_datasets` / `describe_dataset` | all | The catalog: datasets, their raw and analytics tables, last loads | Columns, types, null rates, distinct counts, ranges, top values with counts at or above the threshold; never rows (§ 7) |
| `list_uploads` | build | Files the person uploaded (DEC-011) | Name, sheet names, headers, row count, profile |
| `run_command` · `read_file` · `write_file` · `edit_file` | build | Our own tools (the same on every provider), executed **in the sandbox only** (§ 6) | Output, scrubbed of credentials and capped in size |
| `run_integration_test` | build | Runs the draft's dlt pipeline into the sandbox's scratch schema, then `dbt build` there | Row counts, dbt test results, profiles of the result; never rows |
| `request_credentials` | build | A **deferred** tool: the turn ends and the chat shows a secret form; the next turn resumes with the answer | A handle (`secret://banner-prod`), never the value |
| `propose_integration` / `propose_kpi` | build | Freezes the draft (files, test report) and opens an approval request | The request's id and link |

Not tools, on purpose: running SQL; reading raw or analytics tables; publishing, deploying or approving; anything outside the
sandbox's file system; the web (no `web_search`/`web_fetch` in v1: the model works from the institution's data and its own knowledge).

**Modes.** A conversation is *ask* (answer, chart) or *build* (everything). The tool set is fixed per mode for the whole conversation
(changing tools mid-conversation breaks the prompt cache); switching mode starts a new conversation that links back.

## 6. The builder's sandbox

Code the agent writes (dlt sources, dbt models, Cube definitions) runs only here.

- **One container per build conversation**, from a BI-built image: Python 3.12, dlt, dbt-core and dbt-postgres, the BI's ingest helpers,
  no compilers beyond those, no package installs at run time (an allow-listed internal mirror later, if needed).
- **Files:** a work directory per draft (`/work/<draft>`) on a volume; the file and command tools are confined to it (paths resolved and
  checked against the root, rejected otherwise).
- **Database:** a scratch database per conversation with its own role; raw, staging and analytics live there for the tests. It cannot
  reach the BI's database.
- **Network:** deny by default; the hosts of the sources being connected are opened per draft (e.g. Banner's API host) when the person
  confirms them. The model provider is never reachable from the sandbox.
- **Credentials:** a credential handle in the draft's config is turned into an environment variable by the sandbox runner when it
  starts a test; the value is never written to files the agent can read, and every tool output is scrubbed of it before it returns.
- **Limits:** per command 120 s, per test run 15 min, 2 CPU, 4 GB memory, 10 GB disk; commands logged; the container is stopped
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
| `conversation` | id, owner, mode (ask, build), title, model (`provider:model`, pinned), created_at, archived_at |
| `conversation_message` | conversation, seq, kind (request, response), **message (jsonb: Pydantic AI's `ModelMessage`, with the provider's own details such as thinking signatures)**, created_at. Append-only |
| `agent_run` | one per turn: status (queued, running, done, failed, interrupted), stop reason, iterations, usage, error, timings |
| `agent_event` | bigserial id, run, conversation, type, payload: what the chat streams (§ 9); kept 30 days |
| `draft` | kind (integration, kpi, chart, dashboard), owner, built_by (person or agent), files or definition, test report, state |
| `approval` | draft, requested_by, status (pending, approved, rejected), decided_by, decided_at, note |
| `secret` | handle, encrypted value (AES-GCM, key `BI_SECRETS_KEY` from `make_env.py`), created_by, last_used_at |

**Append-only history is required, not a preference:** some models (Claude Opus 5.5) tie their reasoning to the exact conversation that
produced it, so an edited earlier turn invalidates it. Messages are never edited or deleted; "forget this" archives the conversation.

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

- **Frozen prefix:** the tool list (sorted, fixed per mode) and the instructions (role, rules of § 2 and § 7, the BI's conventions)
  never change within a conversation; nothing per-request (dates, names, catalog) goes in them.
- **Per provider:** on Claude, `anthropic_cache_tool_definitions`, `anthropic_cache_instructions` and `anthropic_cache_messages` mark the
  tools, the instructions and the growing conversation; on OpenAI-compatible routes caching is automatic, keyed per conversation with
  `openai_prompt_cache_key`.
- **Volatile context** (today's date, the person's name and permissions) goes in the first user turn.
- **The catalog is a tool** (`list_metrics`, `list_datasets`), not prompt text, so it can change without breaking the cache.
- **Check:** cached input tokens are recorded per turn; a turn after the first with no cache reads is logged as a warning.
- **Budgets:** per turn (usage limits), per person per month (`AGENT_MONTHLY_TOKENS`, a refusal message when spent).

## 11. Delivery

| Step | Contents | Done when |
|---|---|---|
| **2a. Ask** | Pydantic AI (pinned), the model settings, tables, the loop in the worker, events and SSE, the chat screen, `list_metrics`, `query_metric`, `propose_chart`, `list_datasets`, `describe_dataset`; the scrubber; usage | A person asks a KPI question and gets a governed answer and a chart; no row ever reaches the model (tested) |
| **2b. Build from a file** | The sandbox runner and image, build mode, `run_command` and the file tools, `list_uploads`, `run_integration_test`, `propose_integration`, approvals page | From an uploaded export, the agent drafts dlt and dbt code, tests it, proposes it; a person approves it; it runs in production |
| **2c. Connect a system** | `request_credentials`, the secret store, per-draft egress; Banner first (DEC-008/011) | Banner connected end to end from the chat |
| **2d. Define a KPI** | `propose_kpi`: dbt model and Cube definition, steward approval | A new KPI approved and queryable through Cube and the AMS |

Each step ships behind its own pull request, with an eval set of real requests run against each candidate model: it catches
regressions in tool choice and answers, and decides which model serves each mode. A contract test per provider in use runs a
multi-turn conversation with tools and checks the replayed history is accepted (§ 3).

## 12. Decisions to record once approved

1. Runtime A: Pydantic AI in a worker job, provider-neutral; the API never calls a model (§ 3).
2. A conversation is pinned to one model; models per mode are settings, chosen by the eval set (§ 3, § 11).
3. The model sees schemas, profiles and suppressed aggregates only, whatever the provider (§ 7).
4. Our own sandbox and our own file and command tools for code the agent writes; deny-by-default network; credentials by handle (§ 6).
5. Conversations append-only, events through PostgreSQL and SSE (§ 8, § 9).
6. Approvals outside the chat (§ 9).

## 13. Questions for you

1. **Data with the model provider:** is the default of § 7 right (no rows at all), or may the agent see masked samples while building?
   Which route (§ 3) does the institution allow: a provider's API, its own cloud account (Bedrock, Vertex, Foundry), or only a model
   on its own servers? Is there a data processing agreement, or a residency requirement?
2. **Who approves:** any admin, or a steward per dataset (the registrar for enrollment)?
3. **Where approved integrations live:** as versioned bundles in the BI's database, materialized at deploy (proposed), or in a git
   repository the BI commits to?
4. **Secrets:** an encrypted table in the BI's database for now (proposed), or the institution's vault from the start?
5. **Budget:** a monthly token budget per person, or one for the institution?
6. **Language:** should the chat answer in Arabic as well as English (the calendar already has Arabic names), and the app read
   right to left?
