# CLAUDE.md

**AI-native BI** — the institution's BI product. It supplies evidence to the AMS (drmoyassine/ams) through a versioned contract.

## Rules

1. **The contract is owned by the AMS.** `docs/ams-bi-contract-v0.md` is a copy; `packages/contract` mirrors the AMS's
   `packages/shared/src/collection.ts`. Change the AMS first, then mirror it here. Never add a field the AMS does not know.
2. **Separate products, separate storage** (AMS DEC-017, DEC-034). The BI has its own database, even when it shares the AMS's
   PostgreSQL server in `compose.together.yaml`. Never read or write the AMS's database; talk to it only over the contract.
3. **No invented data.** A source answers only with data it has; no data means no supply. Every supply carries `asOf` and `lineage`.
4. **Call back only the AMS.** The callback address must be the run's own supply route on `AMS_CALLBACK_ORIGIN`; never follow a
   redirect; forget the token when the request ends.
5. Same stack and habits as the AMS: TypeScript strict, Hono, Zod at every boundary, pg-boss, forward-only SQL migrations in
   `packages/core/migrations`, Vitest, structured JSON logs.

## Checks

`pnpm build && pnpm typecheck && pnpm lint && pnpm test` (tests need PostgreSQL: `TEST_DATABASE_ADMIN_URL`, default
`postgres://postgres:postgres@localhost:5432/postgres`).
