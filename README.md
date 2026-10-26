# AI-native BI

The institution's BI product: source systems, warehouse, governed metric layer and consumers. It supplies evidence to the AMS
(drmoyassine/ams) through the contract in `docs/ams-bi-contract-v0.md` (owned by the AMS; this is a copy) and `docs/endpoints.md`.

Stack: TypeScript, Hono on Node, PostgreSQL 16, pg-boss, Zod, Vitest, Docker Compose (the same as the AMS).

## Layout

| Path | What |
|---|---|
| `packages/contract` | The contract v0 as Zod schemas, mirroring the AMS's `packages/shared/src/collection.ts` |
| `packages/core` | Accepting a request, the source registry, the callback, migrations (`packages/core/migrations`, forward-only SQL) |
| `apps/api` | `GET /healthz`, `POST /ams/collect` and `POST /ams/collect/<endpoint>` |
| `apps/worker` | The `collect` queue: find a source, ask it, call the AMS back |

## How a request flows (async)

1. The AMS POSTs `/ams/collect` with `Authorization: Bearer BI_API_KEY`. The BI checks the key and the body, and checks that the
   callback address is the run's own supply route on `AMS_CALLBACK_ORIGIN`. It keeps the request and answers **202** at once.
2. The worker finds a source for it (by `query.metric` or `endpoint`). No source: the request ends `no_source` and the AMS is not
   called; a source never invents values.
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
