# CLAUDE.md

**AI-native BI** — the institution's AI-native business intelligence platform: sources, warehouse, a governed metric layer (Cube)
and consumers, built mostly by an agent. It works on its own and with the AMS (drmoyassine/ams), which requests through a versioned
contract. Read `docs/architecture.md` first.

## Rules

1. **The contract is owned by the AMS.** `docs/ams-bi-contract-v0.md` is a copy; `packages/contract` mirrors the AMS's
   `packages/shared/src/collection.ts`. Change the AMS first, then mirror it here. Never add a field the AMS does not know. Changes
   the BI needs are listed in `docs/ams-contract-proposals.md`.
2. **Separate products, separate storage** (AMS DEC-017, DEC-034). The BI has its own database, even when it shares the AMS's
   PostgreSQL server in `compose.together.yaml`. Never read or write the AMS's database; talk to it only over the contract.
3. **No invented data.** A source answers only with data it has; no data means no supply. Every supply carries `asOf` and `lineage`.
4. **Call back only the AMS.** The callback address must be the run's own supply route on `AMS_CALLBACK_ORIGIN`; never follow a
   redirect; forget the token when the request ends.
5. **Every read of a KPI goes through Cube.** Consumers (the canvas, the AMS adapter, the API, the MCP server, BI tools) never read
   the `raw` or `analytics` tables. Queries are structured, never SQL. Nothing student-level leaves the BI.
6. **A person approves what the agent builds.** An integration, a KPI or a dashboard is not live until approved. The agent's code
   runs in a sandbox, credentials live in the secret store (never in code, the repository or logs), and access to sources is read-only.
7. Stack: Python (target, from phase 0): FastAPI, Pydantic at every boundary, Procrastinate (queue on PostgreSQL), dlt for
   integrations, SQL transforms, Cube for the metric layer, forward-only SQL migrations, pytest, structured JSON logs. The current
   scaffold is still TypeScript (Hono, Zod, pg-boss, Vitest) until phase 0 ports it.

## Checks

Until the port: `pnpm build && pnpm typecheck && pnpm lint && pnpm test` (tests need PostgreSQL: `TEST_DATABASE_ADMIN_URL`, default
`postgres://postgres:postgres@localhost:5432/postgres`).
