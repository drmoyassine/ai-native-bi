---
id: TASK-005
title: Define enrollment_headcount in Cube and answer the AMS
description: The Cube model, and a source in the collect worker that queries Cube and supplies rows, asOf and lineage
status: completed
priority: P0
last_updated: '2026-10-26'
generated:
  by: agent/claude-code
  at: '2026-10-26T13:23:31.090Z'
roadmap_item:
  id: ROADMAP-002
  name: 'Phase 1: the pipeline end to end, from files to the AMS'
  url: /ROADMAP.md#ROADMAP-002
depends_on:
  - id: TASK-004
    name: Load files into raw and analytics
    url: /TASKS.md#TASK-004
related_decisions:
  - id: DEC-004
    name: Cube is the governed layer and the only read path for KPIs
    url: /DECISIONS.md#DEC-004
modified:
  by: agent/claude-code
  at: '2026-10-26T18:14:30.345Z'
---
# TASK-005 — Define enrollment_headcount in Cube and answer the AMS

Done 2026-10-26. `cube/model/cubes/enrollment.yml` (headcount, as-of date, dimensions program, level, status, term); `src/bi/metrics.py` maps `enrollment_headcount` onto it, turns the run's period, dimensions and filters into a Cube query, and answers rows in the item's columns with asOf and lineage. A shape the metric does not have is `no_source` with the reason; no data for the period is `no_data` (migration 0003); neither calls the AMS. Tested end to end against a real Cube (tests/test_cube.py) and in Docker Compose.
