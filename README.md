# AI-native BI

The institution's AI-native business intelligence platform. It takes data from the institution's source systems into its own
warehouse, defines every KPI once in a governed metric layer (Cube), and serves those KPIs to every consumer: its own dashboards, the
AMS, BI tools such as Tableau and Power BI, third-party apps and AI agents. An agent builds the integrations, the KPIs and the
dashboards, each approved by a person before it goes live.

It works on its own, or with the AMS (drmoyassine/ams), the accreditation and quality management system, which requests readings
through the contract in `docs/ams-bi-contract-v0.md` (owned by the AMS; this is a copy) and `docs/endpoints.md`.

**Read `ARCHITECTURE.md`** for the layers, the agent and the boundary with the AMS; `VISION.md`, `ROADMAP.md` (the phases), `TASKS.md` and `DECISIONS.md` hold the rest (managed with vibe-engineering-framework).

## Status

Before phase 0 (`ROADMAP.md`, ROADMAP-001): the code is a TypeScript scaffold of the AMS adapter only, to be ported to Python (FastAPI). No
source, warehouse or metric layer exists yet.

Stack (target): Python, FastAPI, Pydantic, Procrastinate, dlt, SQL transforms, Cube, PostgreSQL 16 + S3, pytest, Docker Compose.
Stack (today's scaffold): TypeScript, Hono on Node, PostgreSQL 16, pg-boss, Zod, Vitest, Docker Compose.

## Layout (today's scaffold)

| Path | What |
|---|---|
| `packages/contract` | The contract v0 as Zod schemas, mirroring the AMS's `packages/shared/src/collection.ts` |
| `packages/core` | Accepting a request, the source registry, the callback, migrations (`packages/core/migrations`, forward-only SQL) |
| `apps/api` | `GET /healthz`, `POST /ams/collect` and `POST /ams/collect/<endpoint>` |
| `apps/worker` | The `collect` queue: find a source, ask it, call the AMS back |

## How an AMS request flows (async)

1. The AMS POSTs `/ams/collect` with `Authorization: Bearer BI_API_KEY`. The BI checks the key and the body, and checks that the
   callback address is the run's own supply route on `AMS_CALLBACK_ORIGIN`. It keeps the request and answers **202** at once.
2. The worker finds a source for it (by `query.metric` or `endpoint`). No source: the request ends `no_source` and the AMS is not
   called; a source never invents values. No source is registered yet.
3. The worker POSTs the supply to the callback with the run's one-time token: 200 supplied, 401/409 ended, 422 refused (with the
   issues), a network error is retried by the queue (5 tries, backoff).

The contract also allows a sync **200** answer with the supply in the body; the BI does not use it yet.

## Run

```bash
cp .env.example .env    # set BI_API_KEY, AMS_CALLBACK_ORIGIN, POSTGRES_PASSWORD
docker compose up --build                            # the BI alone, API on :4000
docker compose -f compose.together.yaml up --build   # with the AMS (AMS_DIR, default ../ams), see the file's header
```

## Check

```bash
pnpm install && pnpm build && pnpm typecheck && pnpm lint && pnpm test   # tests need PostgreSQL (TEST_DATABASE_ADMIN_URL)
```
