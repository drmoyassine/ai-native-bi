---
id: ROADMAP-002
title: 'Phase 1: first slice from file exports to the AMS'
description: Real .xlsb, .xlsx and .csv exports to raw, analytics, Cube and enrollment_headcount, answered to the AMS
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
related_tasks:
  - id: TASK-002
    name: Settle the privacy rules for student data
    url: /TASKS.md#TASK-002
  - id: TASK-003
    name: Choose dbt or SQLMesh for transforms
    url: /TASKS.md#TASK-003
  - id: TASK-004
    name: Load the file exports into raw and analytics
    url: /TASKS.md#TASK-004
  - id: TASK-005
    name: Define enrollment_headcount in Cube and answer the AMS
    url: /TASKS.md#TASK-005
modified:
  by: agent/claude-code
  at: '2026-10-26T13:23:31.090Z'
---
# ROADMAP-002 — Phase 1: first slice from file exports to the AMS

Proves every layer on real data and becomes the pattern the agent copies in phase 2.
