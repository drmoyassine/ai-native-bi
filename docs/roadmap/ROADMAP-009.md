---
id: ROADMAP-009
title: 'The app shell: sign-in, uploads, a first chart'
description: The BI's own accounts, file uploads through the load pipeline, and a governed chart from a chart definition
phase: '2'
status: In Progress
priority: P0
tags:
  - app
  - ui
last_updated: '2026-10-28'
generated:
  by: agent/claude-code
  at: '2026-10-26T21:39:41.703Z'
vision_theme:
  id: open-consumption
  name: Every consumer, one governed layer
  url: /VISION.md#open-consumption
related_decisions:
  - id: DEC-014
    name: 'The app: the BI''s own accounts, a cookie session, a React app served by the API'
    url: /DECISIONS.md#DEC-014
  - id: DEC-012
    name: One chart definition, rendered with ECharts
    url: /DECISIONS.md#DEC-012
  - id: DEC-011
    name: Phase 1 on test files; real data through the frontend
    url: /DECISIONS.md#DEC-011
  - id: DEC-027
    name: 'Connect data: every source behind one connector interface on dlt'
    url: /DECISIONS.md#DEC-027
  - id: DEC-028
    name: 'Discovery: metadata at the source, header rows found, profiles and classification inside the BI'
    url: /DECISIONS.md#DEC-028
  - id: DEC-029
    name: Mappings per layout; approved streams load under a frozen schema contract
    url: /DECISIONS.md#DEC-029
  - id: DEC-030
    name: Databases load incrementally with history (scd2); files stay snapshots
    url: /DECISIONS.md#DEC-030
  - id: DEC-031
    name: Raw keeps column names as written (duck_case)
    url: /DECISIONS.md#DEC-031
related_tasks:
  - id: TASK-009
    name: Build the app shell
    url: /TASKS.md#TASK-009
  - id: TASK-010
    name: Throttle sign-in attempts
    url: /TASKS.md#TASK-010
  - id: TASK-011
    name: Manage accounts in the app
    url: /TASKS.md#TASK-011
  - id: TASK-022
    name: 'Connect data C1: sources and files'
    url: /TASKS.md#TASK-022
modified:
  by: agent/claude-code
  at: '2026-10-28T09:17:34.526Z'
---
# ROADMAP-009 — The app shell: sign-in, uploads, a first chart

The home for real data (uploads), for the agent (its chat, step 2a of ROADMAP-003, is in the app) and for charts (the builder, ROADMAP-004).
