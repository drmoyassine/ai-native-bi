# CLAUDE.md

**AI-native BI** — the institution's BI product. It supplies evidence to the AMS (drmoyassine/ams) through a versioned contract.

## Rules

1. **The contract is owned by the AMS.** `docs/ams-bi-contract-v0.md` is a copy; `packages/contract` mirrors the AMS's
   `packages/shared/src/collection.ts`. Change the AMS first, then mirror it here. Never add a field the AMS does not know.
   The copy is not edited by hand: the AMS's `contract-sync` workflow opens a pull request (`ams-contract-sync`) with the new
   `docs/ams-bi-contract-v0.md` and `docs/ams-source/`; mirror the change into `packages/contract` on that pull request.
2. **Separate products, separate storage** (AMS DEC-017, DEC-034). The BI has its own database, even when it shares the AMS's
   PostgreSQL server in `compose.together.yaml`. Never read or write the AMS's database; talk to it only over the contract.
3. **No invented data.** A source answers only with data it has; no data means no supply. Every supply carries `asOf` and `lineage`.
4. **Call back only the AMS.** The callback address must be the run's own supply route on `AMS_CALLBACK_ORIGIN`; never follow a
   redirect; forget the token when the request ends.
5. Same stack and habits as the AMS: TypeScript strict, Hono, Zod at every boundary, pg-boss, forward-only SQL migrations in
   `packages/core/migrations`, Vitest, structured JSON logs.

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

`pnpm build && pnpm typecheck && pnpm lint && pnpm test` (tests need PostgreSQL: `TEST_DATABASE_ADMIN_URL`, default
`postgres://postgres:postgres@localhost:5432/postgres`).
