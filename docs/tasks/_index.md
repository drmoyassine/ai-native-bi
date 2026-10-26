# Tasks

Work breakdown — tasks with status, owners, dependencies. Canonical task items live in `docs/tasks/`; this generated ledger is the complete reading view.

> All related references use the **`id + name + url`** pattern. Same-repo URLs are relative (`/ROADMAP.md#ROADMAP-001`); cross-repo/external are absolute.

## Schema

```yaml
---
id: TASK-XXX
title: Short description
description: One-line summary
status: pending | in-progress | completed | cancelled
priority: P0 | P1 | P2 | P3
roadmap_item:               # singular — links to one roadmap item
  id: ROADMAP-001
  name: "Roadmap item title"
  url: /ROADMAP.md#ROADMAP-001
assignee:                   # name, or empty
depends_on: []              # array of task refs (empty: [])
related_bugs: []            # array of GitHub Issue refs (id = issue number, int)
related_decisions: []       # array of decision refs — link to DECISIONS, not log.md
tags: []                    # OPTIONAL (OKF)
resource:                   # OPTIONAL (OKF) — canonical URI to the artifact
log_ref:                    # OPTIONAL — ref to log.md section
  date: 2026-01-01
  section: "### ..."
generated:                  # OPTIONAL (OKF trust signal)
  by: "human:<id>"
  at: "2026-01-01T00:00:00Z"
modified:                   # transaction-managed actor/time provenance
  by: "agent/session"
  at: "2026-01-01T00:00:00Z"
verified:                   # OPTIONAL (OKF trust signal)
  - by: "human:<id>"
    at: "2026-01-01T00:00:00Z"
last_updated: 2026-01-01
---

Full description, acceptance criteria, implementation notes.
```

**Field rules:** `roadmap_item` is singular. `depends_on`, `related_bugs`, `related_decisions` are arrays (empty = `[]`). `related_decisions` links to DECISIONS.md, NOT to log.md. `log_ref` points to log.md (narrative history) but is optional.

---

## Task records

<!--
## TASK-001 — Example task

---
id: TASK-001
title: Example task
description: Replace this with a real task
status: pending
priority: P2
roadmap_item:
assignee:
depends_on: []
related_bugs: []
related_decisions: []
last_updated: 2026-01-01
---

Describe the task, acceptance criteria, and implementation notes here.
-->

<!-- VEF:ITEMS -->
