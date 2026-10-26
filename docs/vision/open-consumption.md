---
id: open-consumption
title: Every consumer, one governed layer
status: active
description: The BI's own dashboards, the AMS, BI tools, third-party apps and AI agents all read the same governed KPIs
tags:
  - api
  - mcp
  - ams
generated:
  by: agent/claude-code
  at: '2026-10-26T13:23:31.090Z'
related_decisions:
  - id: DEC-004
    name: Cube is the governed layer and the only read path for KPIs
    url: /DECISIONS.md#DEC-004
  - id: DEC-007
    name: The AMS requests; the BI owns its KPIs end to end
    url: /DECISIONS.md#DEC-007
  - id: DEC-009
    name: One general-purpose API and MCP server on Cube
    url: /DECISIONS.md#DEC-009
related_roadmap_items:
  - id: ROADMAP-004
    name: 'Phase 3: API, MCP server, KPI canvas and document AI'
    url: /ROADMAP.md#ROADMAP-004
  - id: ROADMAP-006
    name: AMS requests beyond collect
    url: /ROADMAP.md#ROADMAP-006
modified:
  by: agent/claude-code
  at: '2026-10-26T13:23:31.090Z'
---
# open-consumption — Every consumer, one governed layer

The BI works on its own and with the AMS (drmoyassine/ams), which is one consumer among others. Every consumer reads the
governed layer through one general-purpose API and an MCP server, with structured queries only; Tableau and Power BI
connect through Cube's SQL API. Nothing student-level leaves the BI.
