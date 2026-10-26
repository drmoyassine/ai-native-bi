# AGENTS.md

Detailed working conventions for AI agents in this repo. Companion to `CLAUDE.md` (which covers identity + doc framework). This file covers *how to work*.

## Doc framework

This repo uses the [vibe-engineering-framework](https://github.com/drmoyassine/vibe-engineering-framework) documentation system. See `CLAUDE.md` for the skills table and doc-framework overview.

## Deterministic queries

Use `vef list`, `show`, `refs`, `why`, `graph`, and `search` for read-only project retrieval. Every query supports versioned JSON through `--json`; none modifies files or invokes an agent.

## Canonical record storage

Structured records live in `docs/vision/`, `docs/roadmap/`, `docs/tasks/`, and `docs/decisions/`; each collection's `_index.md` owns ledger-level prose. The root `VISION.md`, `ROADMAP.md`, `TASKS.md`, and `DECISIONS.md` files are generated committed ledgers. Never edit their generated item blocks directly.

Automated agents must author semantic proposal data and use `vef create`/`vef update`; they must not serialize
canonical item Markdown, inverse links, or ledgers. Preview is the default and writes require `--write --actor <id>`.
VEF owns IDs when omitted, dates, `modified` provenance, relationship closure, journaling, and validation. If a write
is interrupted, stop for an explicit `vef recover <id> --forward|--rollback` direction. If doctor reports malformed
writer leases, confirm no writer is active and run `vef recover leases`; never delete lease files as a recovery policy.
Direct human item editing is an escape hatch; after it, run:

```bash
vef setup
vef check
```

## Editing workflow

1. **Read before you write** — never patch a file you haven't seen this session.
2. **Batch independent edits** into one response.
3. **Run the build + tests** after non-trivial changes; read the whole output.
4. **Migrations are forward-only.** Destructive changes (drops, mass updates) need explicit owner approval.

<!-- PROJECT: Add your build/test commands here, e.g.: -->
<!--
```bash
npm run type-check
npm test
```
-->

## Decision discipline

- Before making or reversing an architectural/product decision, check `DECISIONS.md` (`/decisions list`).
- Don't re-litigate settled decisions; record new or reversed ones via `/decisions add` / `supersede`.
- All decisions — including those made by AI agents — go in DECISIONS.md, never in memory files.

## Doc maintenance

- After completing direction-changing work, run the relevant skill:
  - `/tasks reconcile` — validate task schemas, detect orphans
  - `/roadmap reconcile` — validate roadmap schemas
  - `/decisions reconcile` — validate decision schemas + cross-links
- Run `/apply` to migrate scattered content into the canonical schema.
- `vef setup` is the adoption/upgrade lifecycle write; `vef create` and `vef update` are the day-to-day record writers. `vef check` is the strict read-only local/CI gate; `vef doctor` explains blockers. Review and commit `.vef/`, `docs/`, regenerated ledgers, adapters, and the managed enforcement workflow together. Existing adapter files are never overwritten.

<!-- PROJECT: Add your project-specific conventions here. -->
