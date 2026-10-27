# AI-native BI

The institution's AI-native business intelligence platform. It takes data from the institution's source systems into its own
warehouse, defines every KPI once in a governed metric layer (Cube), and serves those KPIs to every consumer: its own dashboards, the
AMS, BI tools such as Tableau and Power BI, third-party apps and AI agents. An agent builds the integrations, the KPIs and the
dashboards, each approved by a person before it goes live.

It works on its own, or with the AMS (drmoyassine/ams), the accreditation and quality management system, which requests readings
through the contract in `docs/ams-bi-contract-v0.md` (owned by the AMS; this is a copy) and `docs/endpoints.md`.

**Read `ARCHITECTURE.md`** for the layers, the agent and the boundary with the AMS; `VISION.md`, `ROADMAP.md` (the phases), `TASKS.md` and `DECISIONS.md` hold the rest (managed with vibe-engineering-framework).

## Status

Phase 1 (ROADMAP-002): the pipeline runs end to end, tested on made-up files: a file is loaded into `raw`, dbt builds `analytics`,
Cube serves `enrollment_headcount`, and the worker answers the AMS from Cube. Real data comes through the frontend later (DEC-011).

The app shell (ROADMAP-009): sign in with the BI's own accounts, upload a file (loaded and analytics rebuilt by the worker, with
the status of each upload), and chart a governed measure from Cube.

The agent, step 2a (ROADMAP-003, TASK-012): ask questions in a chat and get answers with governed tables and proposed charts. An
admin adds model providers (Anthropic, OpenAI, OpenAI-compatible, OpenRouter, Ollama) on the Models page; their model lists are
fetched and each model is tested for tool calls before people can use it. Needs `BI_SECRETS_KEY` (`python3 scripts/make_env.py`).
Verified against a server that speaks the OpenAI protocol and with scripted models; no live provider has been called yet.

Stack: Python 3.12, FastAPI, Pydantic, Procrastinate, dlt, dbt, Cube, httpx, psycopg, PostgreSQL 16, pytest, ruff, mypy, uv, Docker
Compose; the web app in React, TypeScript, Vite and ECharts. Node builds the web app and runs the project-memory tool (VEF).

## Layout

| Path | What |
|---|---|
| `src/bi/contract.py` | The contract v0 as Pydantic models, mirroring the AMS's `packages/shared/src/collection.ts` |
| `src/bi/collect.py` | Accepting a request: the key, the body, the callback address; kept once per attempt |
| `src/bi/queue.py`, `callback.py`, `sources.py` | The `collect` job: find a source, ask it, call the AMS back; retries |
| `src/bi/api.py`, `main_api.py` | `GET /healthz`, `POST /ams/collect` and `POST /ams/collect/<endpoint>`; `python -m bi.main_api` |
| `src/bi/main_worker.py` | The worker; `python -m bi.main_worker` |
| `src/bi/ingest.py`, `main_load.py` | Loading a file (.xlsx, .xlsb, .xls, .ods, .csv) into `raw`; `python -m bi.main_load` |
| `src/bi/transform/`, `dbt.py` | The dbt project: `raw` -> `staging` -> `analytics`, with its tests |
| `cube/model/` | The governed metrics (Cube) |
| `src/bi/metrics.py`, `cube.py` | The first source: the AMS's metric names onto Cube, and the Cube client |
| `src/bi/app.py`, `accounts.py`, `uploads.py`, `charts.py` | The app's API (`/app/api`): sessions, uploads, governed members, chart data |
| `src/bi/agent/` | The agent: providers and model lists, secret store, the turn loop (Pydantic AI), governed read tools, small-count hiding, the chat's routes |
| `web/` | The web app (Vite, React, ECharts), built into the API image and served at `/`; `web/src/chart.ts` draws every chart |
| `scripts/make_env.py` | `.env` from `.env.example` with every secret generated |
| `src/bi/migrations` | Forward-only SQL, applied by the API at start: `0001` the requests, `0002` Procrastinate's queue, `0003` `no_data`, `0004` the app, `0005` the agent |
| `tests/` | pytest, against a real PostgreSQL |

## How an AMS request flows (async)

1. The AMS POSTs `/ams/collect` with `Authorization: Bearer BI_API_KEY`. The BI checks the key and the body, and checks that the
   callback address is the run's own supply route on `AMS_CALLBACK_ORIGIN`. It keeps the request and answers **202** at once.
2. The worker finds a source for it (by `query.metric`): today the Cube source, for the metrics in `src/bi/metrics.py`. It reads
   Cube for the run's period, dimensions and filters. No source, or a shape the metric does not have: `no_source`; no data for the
   period: `no_data`. Either way the AMS is not called; a source never invents values.
3. The worker POSTs the supply to the callback with the run's one-time token: 200 supplied, 401/409 ended, 422 refused (with the
   issues), a network error or a failing source is retried by the queue (5 retries, after 1, 2, 4, 8 and 16 minutes); after the
   last one the request ends `failed` with the reason, and the token is forgotten.

The contract also allows a sync **200** answer with the supply in the body; the BI does not use it yet.

## Run

```bash
python3 scripts/make_env.py   # .env with every secret generated (keeps values already set); then check AMS_CALLBACK_ORIGIN
docker compose up --build                            # the BI alone, API on :4000
docker compose -f compose.together.yaml up --build   # with the AMS (AMS_DIR, default ../ams), see the file's header

# The first account of the app, then open http://localhost:4000. Either set ADMIN_EMAIL and ADMIN_PASSWORD (at least 12 characters) in
# .env: the API makes that administrator at start if the email has no account yet, and never changes an existing account. Or ask for
# one by hand (it asks for the password):
docker compose exec bi-api python -m bi.main_user you@example.edu --name "Your Name" --admin

# Or load a file from the command line (the folder of exports mounted read-only), then dbt rebuilds analytics:
docker compose run --rm -v /path/to/exports:/imports:ro bi-worker \
  python -m bi.main_load /imports/fall-2026.xlsx --dataset enrollment --as-of 2026-10-20
```

## Check

```bash
uv sync && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest   # tests need PostgreSQL (TEST_DATABASE_ADMIN_URL)
# tests/test_cube.py needs Cube on the database bi_cube_test: CUBE_TEST_URL and CUBE_TEST_SECRET (see .github/workflows/ci.yml)
pnpm install && pnpm --filter bi-web typecheck && pnpm --filter bi-web test && pnpm --filter bi-web build
pnpm --filter bi-web dev     # the web app on :5173, its API proxied to a local python -m bi.main_api on :4000
pnpm install && pnpm exec vef check                                                              # project memory (Node, VEF only)
```
