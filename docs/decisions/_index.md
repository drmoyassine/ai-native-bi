# Decisions

Architectural, product, and technical decisions with context + rationale. Canonical decision items live in `docs/decisions/`; this generated ledger is the complete reading view. Decisions never live only in agent memory.

> All related references use the **`id + name + url`** pattern. Same-repo URLs are relative; cross-repo/external are absolute.

## Schema

```yaml
---
id: DEC-XXX
title: Short description
status: accepted | deprecated | superseded
context: What problem or situation led to this decision
decision: What we decided
rationale: Why this option over alternatives
consequences: What this means for the system (positive + negative)
superseded_by:               # singular, only when status = superseded
  id: DEC-002
  name: "Newer decision"
  url: /DECISIONS.md#DEC-002
related_vision: []           # array of vision refs (optional)
related_roadmap_items: []    # array of roadmap refs
related_tasks: []            # array of task refs
related_decisions: []        # array of decision refs
tags: []                     # OPTIONAL (OKF)
resource:                    # OPTIONAL (OKF)
log_ref:                     # OPTIONAL — ref to log.md section
  date: 2026-01-01
  section: "### ..."
generated:                   # OPTIONAL (OKF trust signal)
  by: "human:<id>"
  at: "2026-01-01T00:00:00Z"
modified:                    # transaction-managed actor/time provenance
  by: "agent/session"
  at: "2026-01-01T00:00:00Z"
verified:                    # OPTIONAL (OKF trust signal)
  - by: "human:<id>"
    at: "2026-01-01T00:00:00Z"
last_updated: 2026-01-01
---

Full prose expansion of the decision, discussion, alternatives considered.
```

**Field rules:** `superseded_by` is singular (omit unless `status: superseded`). `related_vision`, `related_roadmap_items`, `related_tasks`, `related_decisions` are arrays (empty = `[]`). Decisions link **bidirectionally** to/from vision/roadmap/tasks. `log_ref` points to log.md but log.md does NOT link back.

---

## Decisions

<!-- VEF:ITEMS -->
