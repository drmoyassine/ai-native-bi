# CLAUDE.md

**AI-native BI** — the institution's AI-native business intelligence platform: sources, warehouse, a governed metric layer (Cube)
and consumers, built mostly by an agent. It works on its own and with the AMS (drmoyassine/ams), which requests through a versioned
contract. Read `ARCHITECTURE.md` first; vision, roadmap and decisions are in `VISION.md`, `ROADMAP.md` and `DECISIONS.md`.

## Rules

1. **The contract is owned by the AMS.** `docs/ams-bi-contract-v0.md` is a copy; `src/bi/contract.py` mirrors the AMS's
   `packages/shared/src/collection.ts`. Change the AMS first, then mirror it here. Never add a field the AMS does not know.
   The copy is not edited by hand: the AMS's `contract-sync` workflow opens a pull request (`ams-contract-sync`) with the new
   `docs/ams-bi-contract-v0.md` and `docs/ams-source/`; mirror the change into `src/bi/contract.py` on that pull request. Changes
   the BI needs are listed in `docs/ams-contract-proposals.md`.
2. **Separate products, separate storage** (AMS DEC-017 and AMS DEC-034). The BI has its own database, even when it shares the AMS's
   PostgreSQL server in `compose.together.yaml`. Never read or write the AMS's database; talk to it only over the contract.
3. **No invented data.** A source answers only with data it has; no data means no supply. Every supply carries `asOf` and `lineage`.
4. **Call back only the AMS.** The callback address must be the run's own supply route on `AMS_CALLBACK_ORIGIN`; never follow a
   redirect; forget the token when the request ends.
5. **Every read of a KPI goes through Cube.** Consumers (the canvas, the AMS adapter, the API, the MCP server, BI tools) never read
   the `raw` or `analytics` tables. Queries are structured, never SQL. Nothing student-level leaves the BI.
6. **A person approves what the agent builds.** An integration, a KPI or a dashboard is not live until approved. The agent's code
   runs in a sandbox, credentials live in the secret store (never in code, the repository or logs), and access to sources is read-only.
7. Stack (DEC-003): Python 3.12, FastAPI, Pydantic at every boundary, Procrastinate (queue on PostgreSQL), dlt for integrations,
   dbt for transforms, Cube for the metric layer, forward-only SQL migrations in `src/bi/migrations` (never edit an applied one),
   pytest, ruff, mypy strict, structured JSON logs. The web app (web/, DEC-014): React, TypeScript strict, Vite, ECharts, Vitest;
   charts are chart definitions (DEC-012), drawn only by `web/src/chart.ts`. Node builds the web app and runs VEF, nothing else.

## The agent (ROADMAP-003)

`src/bi/agent/` is the agent (spec: `docs/agent-spec.md`, decisions DEC-015 to DEC-020). The loop runs in the worker (`agent_turn` job),
never in the API; the model sees no rows (tools return schemas, profiles and aggregates with small counts hidden, `suppress.py`); a
chart it proposes is read through `/app/api/drafts/<id>/data`, which hides them too. Providers, keys and models are configured in the
app; keys live in the `secret` table, encrypted with `BI_SECRETS_KEY`. Tests need no model: they use scripted models and
`tests/fake_openai.py` (an OpenAI-protocol server over real HTTP). Do not add a tool that returns rows about people.

## The MCP server (ROADMAP-004)

`src/bi/mcp/` serves `src/bi/tools/` at `/mcp` (spec: `docs/mcp-spec.md`, DEC-021 to DEC-024). A tool is written once in `src/bi/tools/`
and reaches both the chat and MCP; never give MCP a tool the chat's privacy rules do not cover. Every call resolves to a principal from
a bearer token: a personal access token, or an AMS access token (contract 6.2, `src/bi/mcp/oidc.py`) whose role and scope are read
from the token, never stored; a scope other than `all` is refused until Cube enforces it. Tests use the SDK's real
client in-process (`tests/test_mcp.py`); the SDK's session manager runs in the app's lifespan, once per app.

## Project memory (VEF)

Vision, roadmap, tasks and decisions live in `docs/vision/`, `docs/roadmap/`, `docs/tasks/` and `docs/decisions/`, managed by
vibe-engineering-framework (see `AGENTS.md`). Change them with the `/tasks`, `/roadmap` and `/decisions` skills or `vef create` /
`vef update`; never edit the generated root ledgers (`VISION.md`, `ROADMAP.md`, `TASKS.md`, `DECISIONS.md`) by hand.

## Requests to and from the AMS

The two repositories talk through GitHub Issues, bridged by `.github/workflows/issue-bridge.yml`:
- **Need something from the AMS** (a contract change, a new field, a route, a bug)? `/request`, or open an issue here labelled `for-ams`. It is
  copied to the AMS (labelled `from-bi` there); when the AMS closes it, this issue gets the outcome and is closed.
- **At the start of a session, run `/inbox`** (open `from-ams` issues: requests the AMS made of the BI). Close one when it is done or declined,
  with a last comment saying what was done (commit or PR) or why not: that comment is what the AMS receives.
- Never edit the contract to get a change: ask with `for-ams`, then merge the `ams-contract-sync` pull request when it comes.

- **Moving code** between the repositories: `/request` with a `## Hand-over` (paths and commit SHA); the receiving side attaches
  the source read-only, ports it into its own layout and closes the request with the commit; only then does the source remove it.
  The skills `.claude/skills/request` and `.claude/skills/inbox` hold the steps (manual invoke only).

## Checks

```bash
uv sync && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest   # tests need PostgreSQL (TEST_DATABASE_ADMIN_URL)
pnpm install && pnpm exec vef check                                                              # project memory (VEF)
pnpm --filter bi-web typecheck && pnpm --filter bi-web test && pnpm --filter bi-web build      # the web app (web/)
```

Tests need PostgreSQL: `TEST_DATABASE_ADMIN_URL`, default `postgres://postgres:postgres@localhost:5432/postgres`. `tests/test_cube.py`
also needs Cube reading the database `bi_cube_test` (`CUBE_TEST_URL`, `CUBE_TEST_SECRET`; CI starts it, see `.github/workflows/ci.yml`).
