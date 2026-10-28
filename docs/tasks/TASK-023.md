---
title: 'Connect data C2: APIs and schedules'
description: rest_api sources, scheduled incremental syncs
status: pending
priority: P1
id: TASK-023
last_updated: '2026-10-28'
generated:
  by: agent/claude-code
  at: '2026-10-28T09:17:35.457Z'
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
  at: '2026-10-28T09:17:35.457Z'
---
# TASK-023 — Connect data C2: APIs and schedules

rest_api configurations, drafted from an OpenAPI document; syncs on a schedule, incremental with state; frozen contracts on approved streams. Done when one endpoint syncs on a schedule and a changed field pauses the stream with a review.
