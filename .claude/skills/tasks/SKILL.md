# /tasks

Manage canonical AI-native BI task records in `docs/tasks/`. `TASKS.md` is a generated, committed ledger for reading and stable public links.

## Commands

- `list` — Show all tasks, optionally filtered by status/priority/assignee/roadmap_item
- `add` — Add a new task (prompts for required fields)
- `update` — Update an existing task (change status, assignee, priority)
- `complete` — Mark a task as completed
- `reconcile` — Validate canonical task files and regenerate TASKS.md

## Required writer boundary

The skill interprets intent and authors semantic fields/body, but it never edits or serializes canonical Markdown.
For `add`, write a temporary YAML/JSON proposal and run `vef create task --from <proposal>` to preview, then rerun
with `--write --actor <agent-id>` only after the preview is accepted. For `update` and `complete`, use
`vef update TASK-XXX --from <proposal>` and the same explicit `--write` gate. Put scalar changes under `set`, body
prose under `body`, and relationship changes under `relationships`; the CLI owns IDs when omitted, `last_updated`,
`modified` provenance, inverse links, ledgers, validation, journaling, and recovery. Never maintain a second YAML
frontmatter or Markdown renderer in this adapter.

## Task schema

Every task in TASKS.md must follow this frontmatter schema. All related references use the **`id + name + url`** pattern — relative URLs for same-repo, absolute for cross-repo/external.

```yaml
---
id: TASK-XXX
title: Short description
description: One-line summary
status: pending | in-progress | completed | cancelled
priority: P0 | P1 | P2 | P3
roadmap_item:                 # SINGULAR object — a task belongs to one roadmap item
  id: ROADMAP-001
  name: "Roadmap item title"
  url: /ROADMAP.md#ROADMAP-001
assignee:                     # name, or empty
depends_on:                   # array of task refs (empty: [])
  - id: TASK-001
    name: "Prerequisite task"
    url: /TASKS.md#TASK-001
related_bugs:                 # array of GitHub Issue refs (id = issue number, int)
  - id: 42
    name: "Bug title"
    url: https://github.com/drmoyassine/ai-native-bi/issues/42
related_decisions:            # array of decision refs (empty: []) — link to DECISIONS, not log.md
  - id: DEC-001
    name: "Decision title"
    url: /DECISIONS.md#DEC-001
tags: []                      # OPTIONAL (OKF) — cross-cutting labels
resource:                     # OPTIONAL (OKF) — canonical URI to the artifact
log_ref:                      # OPTIONAL — ref to log.md section (narrative history)
  date: 2026-01-01
  section: "### ..."
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

Full description, acceptance criteria, implementation notes.
```

**Field rules:**
- `roadmap_item` is **singular** (one origin item). Use `roadmap_item:` with no value if unlinked.
- `depends_on`, `related_bugs`, `related_decisions` are **arrays**. Empty array = `[]`.
- `related_bugs.id` is the GitHub Issue **number** (integer, unquoted).
- `related_decisions` links to DECISIONS.md (the canonical decision record), NOT to log.md.
- `log_ref` points to log.md (narrative history) but is optional.
- Same-repo URLs are **relative** (`/ROADMAP.md#ROADMAP-001`); cross-repo/external are **absolute**.
- **OKF optional fields**: `tags`, `resource`, `log_ref`, `generated` {by, at}, transaction-managed `modified` {by, at}, `verified` [{by, at}]. Actor convention: `human:<id>` / `<producer>/<version>` / `process:<id>`.

## Cross-linking philosophy

Tasks link to **ROADMAP** (via `roadmap_item`) and **DECISIONS** (via `related_decisions`), NOT to log.md. The decision is the canonical record for "what we decided"; log.md is the narrative history of "how we got there."

## How to use

### List tasks
```
/tasks list
/tasks list status:pending
/tasks list priority:P1
/tasks list assignee:drmoy
/tasks list roadmap_item:ROADMAP-003
```

### Add a task
```
/tasks add
```
You'll be prompted for:
- id (auto-suggests next number)
- title
- description (one-line summary)
- status (default: pending)
- priority (default: P2)
- roadmap_item (choose a ROADMAP-XXX from ROADMAP.md; recorded as `id + name + url`)
- assignee (optional)
- depends_on (optional, array of TASK-XXX → `id + name + url`)
- related_bugs (optional, array of issue numbers → `id + name + url`)
- related_decisions (optional, array of DEC-XXX → `id + name + url`)

### Update a task
```
/tasks update TASK-001
```
You'll be prompted for fields to update.

### Complete a task
```
/tasks complete TASK-001
```
Submit `set: { status: completed }` through `vef update`; the transaction engine stamps dates and provenance.

### Reconcile
```
/tasks reconcile
```
1. Runs `vef check` as the read-only reconciliation report.
2. Uses `vef show`, `vef refs`, and `vef graph` to explain any inconsistency.
3. For an accepted repair, authors an update proposal and delegates the complete write to `vef update`; a title/heading mismatch requires explicit human-selected `--authority frontmatter|heading`.
4. Reruns `vef check`; unresolved transaction journals require explicit `vef recover` direction.

## Implementation notes

- Each task is stored canonically in `docs/tasks/<ID>.md`; `docs/tasks/_index.md` owns ledger-level prose.
- Automated agents never edit task item files or generated blocks directly; `vef create`/`vef update` are the only supported writer path.
- Direct human editing is an escape hatch: maintain all inverse links, run `vef setup` to project, then require `vef check` before acceptance.
- The `id` field is the unique identifier (TASK-XXX format).
- Generated ledgers use deterministic record-ID order; status filtering belongs in `vef list tasks --status ...` or a derived review view.
- `roadmap_item` ↔ ROADMAP `related_tasks` must be bidirectional.
