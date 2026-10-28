---
title: 'Connect data C3: Oracle (Banner)'
description: Oracle source on sql_database, incremental with history
status: pending
priority: P1
id: TASK-024
last_updated: '2026-10-28'
generated:
  by: agent/claude-code
  at: '2026-10-28T09:17:36.185Z'
roadmap_item:
  id: ROADMAP-003
  name: 'Phase 2: the agent builds integrations and KPIs'
  url: /ROADMAP.md#ROADMAP-003
related_decisions:
  - id: DEC-027
    name: 'Connect data: every source behind one connector interface on dlt'
    url: /DECISIONS.md#DEC-027
modified:
  by: agent/claude-code
  at: '2026-10-28T09:17:36.185Z'
---
# TASK-024 — Connect data C3: Oracle (Banner)

sql_database with oracledb: check (read-only), discover_schema(), choose tables and columns, incremental scd2 history (DEC-030), unmapped personal columns not read. Needs dlt 1.32. Done when a test Oracle (a container in CI) loads chosen tables incrementally.
