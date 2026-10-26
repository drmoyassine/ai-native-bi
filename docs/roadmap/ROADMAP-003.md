---
id: ROADMAP-003
title: 'Phase 2: the agent builds integrations and KPIs'
description: >-
  The agent in the app's chat: answers and charts from governed KPIs, builds integrations and KPIs in a sandbox,
  proposes them for approval (spec: docs/agent-spec.md)
phase: '2'
status: Deferred
priority: P1
tags:
  - agent
last_updated: '2026-10-26'
generated:
  by: agent/claude-code
  at: '2026-10-26T13:23:31.090Z'
vision_theme:
  id: agent-built-bi
  name: An agent builds the BI
  url: /VISION.md#agent-built-bi
related_decisions:
  - id: DEC-006
    name: A person approves what the agent builds
    url: /DECISIONS.md#DEC-006
modified:
  by: agent/claude-code
  at: '2026-10-26T21:46:56.262Z'
---
# ROADMAP-003 — Phase 2: the agent builds integrations and KPIs

Spec proposed 2026-10-26 in docs/agent-spec.md: the runtime (the Claude API SDK tool runner in a worker job), the loop, the tools, the builder's sandbox, the data the model may see, conversations and the chat, caching and cost, and delivery in four steps (2a ask, 2b build from a file, 2c connect a system, 2d define a KPI). Decisions are recorded once it is approved.
