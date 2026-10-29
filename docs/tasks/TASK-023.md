---
title: 'Connect data C2a: REST API sources'
description: >-
  One source per API, one stream per endpoint, read with GET through dlt rest_api (pagination found by dlt), bearer, API
  key or basic credentials in the secret store, the same draft, profile, mapping and review path as files, Read it now
  and an hourly or daily schedule
status: completed
priority: P1
id: TASK-023
last_updated: '2026-10-29'
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
  by: process:vef-cli
  at: '2026-10-29T07:55:50.255Z'
---
# TASK-023 — Connect data C2a: REST API sources

rest_api configurations, drafted from an OpenAPI document; syncs on a schedule, incremental with state; frozen contracts on approved streams. Done when one endpoint syncs on a schedule and a changed field pauses the stream with a review.
