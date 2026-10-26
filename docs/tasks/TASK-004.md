---
id: TASK-004
title: Load files into raw and analytics
description: dlt pipeline for .xlsb, .xlsx and .csv into S3 and the raw schema; dbt models into analytics; tested on made-up files
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
  - id: TASK-001
    name: Port the scaffold to Python
    url: /TASKS.md#TASK-001
  - id: TASK-003
    name: Choose dbt or SQLMesh for transforms
    url: /TASKS.md#TASK-003
related_decisions:
  - id: DEC-005
    name: 'Warehouse: raw and analytics on PostgreSQL, raw files on S3'
    url: /DECISIONS.md#DEC-005
  - id: DEC-008
    name: First slice from real file exports; Banner through the agent
    url: /DECISIONS.md#DEC-008
  - id: DEC-011
    name: Phase 1 on test files; real data through the frontend
    url: /DECISIONS.md#DEC-011
modified:
  by: agent/claude-code
  at: '2026-10-26T18:14:30.345Z'
---
# TASK-004 — Load files into raw and analytics

Built and tested on made-up test files (DEC-011). Real exports arrive later through the frontend; they are never committed to the repository.

Done 2026-10-26. `src/bi/ingest.py` keeps each file unchanged (read-only, under its SHA-256) and appends its rows to `raw.<dataset>` as text with their file, row, as-of date and load time; the same file loads once. `src/bi/transform` (dbt) builds `staging.stg_enrollment` (typed; per term, the latest upload replaces the earlier) and `analytics.enrollment` (one row per student and term) with data tests. `python -m bi.main_load` loads and rebuilds. Tested on .xlsx and .csv; .xlsb and .xls are read by the same library (calamine) but not yet tested on a real file.
