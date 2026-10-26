---
id: TASK-004
title: Load the file exports into raw and analytics
description: dlt pipeline for .xlsb, .xlsx and .csv into S3 and the raw schema; transforms into analytics
status: pending
priority: P0
last_updated: '2026-10-26'
generated:
  by: agent/claude-code
  at: '2026-10-26T13:23:31.090Z'
roadmap_item:
  id: ROADMAP-002
  name: 'Phase 1: first slice from file exports to the AMS'
  url: /ROADMAP.md#ROADMAP-002
depends_on:
  - id: TASK-001
    name: Port the scaffold to Python
    url: /TASKS.md#TASK-001
  - id: TASK-002
    name: Settle the privacy rules for student data
    url: /TASKS.md#TASK-002
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
modified:
  by: agent/claude-code
  at: '2026-10-26T13:23:31.090Z'
---
# TASK-004 — Load the file exports into raw and analytics

The exports are never committed to the repository.
