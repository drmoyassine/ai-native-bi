---
id: agent-built-bi
title: An agent builds the BI
status: active
description: >-
  People ask in a conversation; an agent connects sources, defines KPIs and builds dashboards, and a person approves
  each before it goes live
tags:
  - agent
  - ai
generated:
  by: agent/claude-code
  at: '2026-10-26T13:23:31.090Z'
related_decisions:
  - id: DEC-006
    name: A person approves what the agent builds
    url: /DECISIONS.md#DEC-006
  - id: DEC-012
    name: One chart definition, rendered with ECharts
    url: /DECISIONS.md#DEC-012
  - id: DEC-013
    name: 'Charts and dashboards: private drafts, approved to publish'
    url: /DECISIONS.md#DEC-013
related_roadmap_items:
  - id: ROADMAP-003
    name: 'Phase 2: the agent builds integrations and KPIs'
    url: /ROADMAP.md#ROADMAP-003
modified:
  by: agent/claude-code
  at: '2026-10-26T17:54:58.321Z'
---
# agent-built-bi — An agent builds the BI

A BI team is usually the bottleneck between a question and an answer. Here the agent is how people use the BI: it asks
for what it needs, writes and tests the integration, loads the warehouse, writes the KPI definition and composes the
dashboard (generative UI). People keep the judgement: nothing the agent builds is live until a person approves it.
