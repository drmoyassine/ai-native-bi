---
id: ROADMAP-002
title: 'Phase 1: the pipeline end to end, from files to the AMS'
description: .xlsb, .xlsx and .csv files to raw, dbt, Cube and enrollment_headcount, answered to the AMS; tested on made-up files
phase: '1'
status: Deferred
priority: P0
tags:
  - warehouse
  - cube
last_updated: '2026-10-26'
generated:
  by: agent/claude-code
  at: '2026-10-26T13:23:31.090Z'
vision_theme:
  id: governed-kpis
  name: One trusted definition of every KPI
  url: /VISION.md#governed-kpis
related_decisions:
  - id: DEC-004
    name: Cube is the governed layer and the only read path for KPIs
    url: /DECISIONS.md#DEC-004
  - id: DEC-005
    name: 'Warehouse: raw and analytics on PostgreSQL, raw files on S3'
    url: /DECISIONS.md#DEC-005
  - id: DEC-008
    name: First slice from real file exports; Banner through the agent
    url: /DECISIONS.md#DEC-008
  - id: DEC-010
    name: dbt for transforms
    url: /DECISIONS.md#DEC-010
  - id: DEC-011
    name: Phase 1 on test files; real data through the frontend
    url: /DECISIONS.md#DEC-011
related_tasks:
  - id: TASK-002
    name: Settle the privacy rules for student data
    url: /TASKS.md#TASK-002
  - id: TASK-003
    name: Choose dbt or SQLMesh for transforms
    url: /TASKS.md#TASK-003
  - id: TASK-004
    name: Load files into raw and analytics
    url: /TASKS.md#TASK-004
  - id: TASK-005
    name: Define enrollment_headcount in Cube and answer the AMS
    url: /TASKS.md#TASK-005
modified:
  by: agent/claude-code
  at: '2026-10-26T17:33:38.583Z'
---
# ROADMAP-002 — Phase 1: the pipeline end to end, from files to the AMS

Proves every layer on real data and becomes the pattern the agent copies in phase 2.
