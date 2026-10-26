# AI-native BI

The institution's AI-native business intelligence platform. It takes data from the institution's source systems into its own
warehouse, defines every KPI once in a governed metric layer (Cube), and serves those KPIs to every consumer: its own dashboards, the
AMS, BI tools such as Tableau and Power BI, third-party apps and AI agents. An agent builds the integrations, the KPIs and the
dashboards, each approved by a person before it goes live.

It works on its own, or with the AMS (drmoyassine/ams), the accreditation and quality management system, which requests readings
through the contract in `docs/ams-bi-contract-v0.md` (owned by the AMS; this is a copy) and `docs/endpoints.md`.

**Read `ARCHITECTURE.md`** for the layers, the agent and the boundary with the AMS; `VISION.md`, `ROADMAP.md` (the phases), `TASKS.md` and `DECISIONS.md` hold the rest (managed with vibe-engineering-framework).

## Status

Phase 0 is done (ROADMAP-001): the AMS adapter runs on Python. Next is phase 1 (ROADMAP-002). No source, warehouse or metric layer
exists yet.

Stack: Python 3.12, FastAPI, Pydantic, Procrastinate, httpx, psycopg, PostgreSQL 16, pytest, ruff, mypy, uv, Docker Compose. Coming:
dlt, SQL transforms, Cube, S3. Node is used only for the project-memory tool (VEF).

## Layout

| Path | What |
|---|---|
| `src/bi/contract.py` | The contract v0 as Pydantic models, mirroring the AMS's `packages/shared/src/collection.ts` |
| `src/bi/collect.py` | Accepting a request: the key, the body, the callback address; kept once per attempt |
| `src/bi/queue.py`, `callback.py`, `sources.py` | The `collect` job: find a source, ask it, call the AMS back; retries |
| `src/bi/api.py`, `main_api.py` | `GET /healthz`, `POST /ams/collect` and `POST /ams/collect/<endpoint>`; `python -m bi.main_api` |
| `src/bi/main_worker.py` | The worker; `python -m bi.main_worker` |
| `src/bi/migrations` | Forward-only SQL, applied by the API at start: `0001` the requests, `0002` Procrastinate's queue |
| `tests/` | pytest, against a real PostgreSQL |

## How an AMS request flows (async)

1. The AMS POSTs `/ams/collect` with `Authorization: Bearer BI_API_KEY`. The BI checks the key and the body, and checks that the
   callback address is the run's own supply route on `AMS_CALLBACK_ORIGIN`. It keeps the request and answers **202** at once.
2. The worker finds a source for it (by `query.metric` or `endpoint`). No source: the request ends `no_source` and the AMS is not
   called; a source never invents values. No source is registered yet.
3. The worker POSTs the supply to the callback with the run's one-time token: 200 supplied, 401/409 ended, 422 refused (with the
   issues), a network error or a failing source is retried by the queue (5 retries, after 1, 2, 4, 8 and 16 minutes).

The contract also allows a sync **200** answer with the supply in the body; the BI does not use it yet.

## Run

```bash
cp .env.example .env    # set BI_API_KEY, AMS_CALLBACK_ORIGIN, POSTGRES_PASSWORD
docker compose up --build                            # the BI alone, API on :4000
docker compose -f compose.together.yaml up --build   # with the AMS (AMS_DIR, default ../ams), see the file's header
```

## Check

```bash
uv sync && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest   # tests need PostgreSQL (TEST_DATABASE_ADMIN_URL)
pnpm install && pnpm exec vef check                                                              # project memory (Node, VEF only)
```
