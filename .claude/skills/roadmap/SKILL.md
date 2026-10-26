# /roadmap

Manage canonical AI-native BI roadmap records in `docs/roadmap/`. `ROADMAP.md` is a generated, committed ledger for reading and stable public links.

## Commands

- `list` — Show all roadmap items, optionally filtered by quarter/status
- `add` — Add a new roadmap item (Q1/Q2/Q3/Q4, title, description)
- `graduate` — Graduate a roadmap item into one or more tasks
- `reconcile` — Validate canonical roadmap files and regenerate ROADMAP.md

## Required writer boundary

The skill interprets direction and authors semantic fields/body, but it never edits or serializes canonical Markdown.
For `add`, use `vef create roadmap --from <proposal>` for preview and rerun with `--write --actor <agent-id>` only
after acceptance. For scalar or relationship changes, use `vef update ROADMAP-XXX --from <proposal>`. Put scalar
changes under `set`, body prose under `body`, and link additions/removals under `relationships`. Graduation proposals
are submitted together through the transaction engine's batch proposal mode so the roadmap/task graph changes as
one candidate. The CLI owns lifecycle dates, `modified` provenance, inverse links, ledgers, validation, journaling,
and recovery; this adapter owns no frontmatter or Markdown renderer.

## Roadmap item schema

Every roadmap item in ROADMAP.md must follow this frontmatter schema. All related references use the **`id + name + url`** pattern — relative URLs for same-repo, absolute for cross-repo/external.

```yaml
---
id: ROADMAP-XXX
title: Short description
description: One-line summary
quarter: Q1 | Q2 | Q3 | Q4
status: Deferred | In Progress | Completed | Blocked
priority: P0 | P1 | P2 | P3
vision_theme:                 # SINGULAR object, OPTIONAL (until VISION.md themes exist)
  id: document-intelligence
  name: "Vision theme title"
  url: /VISION.md#document-intelligence
related_tasks:                # array of task refs (empty: [])
  - id: TASK-001
    name: "Task title"
    url: /TASKS.md#TASK-001
related_decisions:            # array of decision refs (empty: []) — link to DECISIONS, not log.md
  - id: DEC-001
    name: "Decision title"
    url: /DECISIONS.md#DEC-001
tags: []                      # OPTIONAL (OKF) — cross-cutting labels
resource:                     # OPTIONAL (OKF) — canonical URI to the artifact
log_ref:                      # OPTIONAL — ref to log.md section (narrative history)
  date: 2026-01-01
  section: "### Q2 planning"
generated:                    # OPTIONAL (OKF trust signal)
  by: "human:<id>"
  at: "2026-01-01T00:00:00Z"
modified:                     # transaction-managed provenance
  by: "agent/session"
  at: "2026-01-01T00:00:00Z"
verified:                     # OPTIONAL (OKF trust signal)
  - by: "human:<id>"
    at: "2026-01-01T00:00:00Z"
last_updated: 2026-01-01
---

Problem, solution, dependencies, open decisions.
```

**Field rules:**
- `vision_theme` is **singular** and **optional** (until VISION.md themes exist). Links to VISION.md when it exists.
- `related_tasks`, `related_decisions` are **arrays**. Empty array = `[]`.
- `related_decisions` links to DECISIONS.md (the canonical decision record), NOT to log.md.
- `log_ref` points to log.md (narrative history) but is optional.
- Same-repo URLs are **relative** (`/TASKS.md#TASK-001`); cross-repo/external are **absolute**.
- **OKF optional fields**: `tags`, `resource`, `log_ref`, `generated` {by, at}, transaction-managed `modified` {by, at}, `verified` [{by, at}]. Actor convention: `human:<id>` / `<producer>/<version>` / `process:<id>`.

## Cross-linking philosophy

Roadmap items link to **VISION** (via `vision_theme`) and **DECISIONS** (via `related_decisions`), NOT to log.md. Tasks link back via `roadmap_item`. Vision/roadmap/tasks all link bidirectionally to decisions.

## How to use

### List roadmap items
```
/roadmap list
/roadmap list quarter:Q1
/roadmap list status:Deferred
/roadmap list status:In Progress
```

### Add a roadmap item
```
/roadmap add
```
You'll be prompted for:
- id (auto-suggests next number, ROADMAP-XXX)
- title
- description (one-line summary)
- quarter (Q1/Q2/Q3/Q4)
- status (default: Deferred)
- priority (default: P2)
- problem / solution / dependencies (prose body)
- related_tasks (optional, array of TASK-XXX → `id + name + url`)
- related_decisions (optional, array of DEC-XXX → `id + name + url`)
- vision_theme (optional, omitted until VISION.md themes exist)

### Graduate roadmap item → tasks
```
/roadmap graduate ROADMAP-001
```
You'll be prompted for:
- How many tasks to create
- Task titles (break down the roadmap item into concrete tasks)
- Priority for each task
- Assignee (optional)

Submit the task creates and roadmap update as one `operations` proposal through `vef create batch --from <proposal>`;
the engine allocates/validates records and closes every inverse relationship in the same transaction.

### Reconcile
```
/roadmap reconcile
```
1. Runs `vef check` as the read-only reconciliation report.
2. Uses `vef show`, `vef refs`, and `vef graph` to explain inconsistencies.
3. Delegates accepted repairs to `vef update` or one batch proposal; a title/heading mismatch requires explicit human-selected `--authority frontmatter|heading`.
4. Reruns `vef check`; unresolved transaction journals require explicit recovery direction.

## Implementation notes

- Each roadmap item is stored canonically in `docs/roadmap/<ID>.md`; `docs/roadmap/_index.md` owns ledger-level prose.
- Automated agents never edit roadmap item files or generated blocks directly; the transaction commands are the only supported writer path.
- Direct human editing is an escape hatch: maintain inverse links, run `vef setup` to project, then require `vef check`.
- The `id` field is the unique identifier (ROADMAP-XXX format).
- Status is one of: Deferred, In Progress, Completed, Blocked.
- `related_tasks` ↔ TASK `roadmap_item` must be bidirectional.
