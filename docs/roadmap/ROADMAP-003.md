---
id: ROADMAP-003
title: 'Phase 2: the agent builds integrations and KPIs'
description: >-
  The agent in the app's chat: answers and charts from governed KPIs, builds integrations and KPIs in a sandbox,
  proposes them for approval (spec: docs/agent-spec.md)
phase: '2'
status: In Progress
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
  - id: DEC-015
    name: The agent runs on Pydantic AI in a worker job; the API never calls a model
    url: /DECISIONS.md#DEC-015
  - id: DEC-016
    name: Five model providers, configured in the app, models fetched automatically
    url: /DECISIONS.md#DEC-016
  - id: DEC-017
    name: The model sees schemas, profiles and suppressed aggregates, never rows
    url: /DECISIONS.md#DEC-017
  - id: DEC-018
    name: Conversations are append-only; events go through PostgreSQL and SSE
    url: /DECISIONS.md#DEC-018
  - id: DEC-019
    name: Agent work is approved outside the chat, by the data's steward
    url: /DECISIONS.md#DEC-019
  - id: DEC-020
    name: Secrets in an encrypted table behind a small interface; budgets; language
    url: /DECISIONS.md#DEC-020
modified:
  by: agent/claude-code
  at: '2026-10-26T22:07:12.855Z'
related_tasks:
  - id: TASK-012
    name: 'Agent step 2a: ask questions, get charts'
    url: /TASKS.md#TASK-012
  - id: TASK-013
    name: 'Agent step 2b: build an integration from an uploaded file'
    url: /TASKS.md#TASK-013
  - id: TASK-014
    name: 'Agent step 2c: connect a source system (Banner)'
    url: /TASKS.md#TASK-014
  - id: TASK-015
    name: 'Agent step 2d: define a KPI'
    url: /TASKS.md#TASK-015
---
# ROADMAP-003 — Phase 2: the agent builds integrations and KPIs

Spec proposed 2026-10-26 in docs/agent-spec.md and revised the same day for any model provider: the runtime (Pydantic AI in a worker job, the model per mode a setting), the loop, the tools, the builder's sandbox, the data the model may see, conversations and the chat, caching and cost, and delivery in four steps (2a ask, 2b build from a file, 2c connect a system, 2d define a KPI). Decisions are recorded once it is approved.
