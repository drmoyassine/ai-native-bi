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
last_updated: '2026-10-29'
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
  - id: DEC-024
    name: The chat agent and the MCP server share one tool implementation
    url: /DECISIONS.md#DEC-024
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
  - id: DEC-033
    name: >-
      Knowledge is part of the metric definition in Cube; verified questions marked Trusted; benchmarks scored from tool
      calls
    url: /DECISIONS.md#DEC-033
  - id: DEC-034
    name: The ontology is a reviewed file that replaces SHAPES
    url: /DECISIONS.md#DEC-034
  - id: DEC-035
    name: The setup agent proposes mappings where the rules fall short; masking is by profile kind, in code
    url: /DECISIONS.md#DEC-035
  - id: DEC-036
    name: >-
      What the institution reports on is configuration: subjects, entities, events, cohorts and metrics defined in the
      app; models generated
    url: /DECISIONS.md#DEC-036
  - id: DEC-037
    name: The BI knows no organisation, industry or language; all domain meaning is configuration or a template
    url: /DECISIONS.md#DEC-037
  - id: DEC-038
    name: Adopt the AMS's patterns for configuration, languages and the interface
    url: /DECISIONS.md#DEC-038
modified:
  by: process:vef-cli
  at: '2026-10-29T07:55:51.059Z'
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
  - id: TASK-023
    name: 'Connect data C2a: REST API sources'
    url: /TASKS.md#TASK-023
  - id: TASK-024
    name: 'Connect data C3: Oracle (Banner)'
    url: /TASKS.md#TASK-024
  - id: TASK-025
    name: 'Connect data C4: PostgreSQL'
    url: /TASKS.md#TASK-025
  - id: TASK-026
    name: 'Connect data C5: the remaining sources'
    url: /TASKS.md#TASK-026
  - id: TASK-027
    name: 'Context K1: metric knowledge in Cube'
    url: /TASKS.md#TASK-027
  - id: TASK-028
    name: 'Context K2: verified questions'
    url: /TASKS.md#TASK-028
  - id: TASK-029
    name: 'Context K3: benchmarks'
    url: /TASKS.md#TASK-029
  - id: TASK-030
    name: 'Context K4: drafted documentation'
    url: /TASKS.md#TASK-030
  - id: TASK-031
    name: 'Data model M1: definitions'
    url: /TASKS.md#TASK-031
  - id: TASK-032
    name: 'Setup agent S1: masked samples'
    url: /TASKS.md#TASK-032
  - id: TASK-033
    name: 'Setup agent S2: mapping proposals'
    url: /TASKS.md#TASK-033
  - id: TASK-034
    name: 'Data model M2: generated warehouse'
    url: /TASKS.md#TASK-034
  - id: TASK-035
    name: 'Data model M3: the Model page'
    url: /TASKS.md#TASK-035
  - id: TASK-036
    name: 'Data model M4: targets proposed per stream'
    url: /TASKS.md#TASK-036
  - id: TASK-037
    name: 'Data model M5: metric builder'
    url: /TASKS.md#TASK-037
  - id: TASK-038
    name: 'Data model M6: cohort builder'
    url: /TASKS.md#TASK-038
  - id: TASK-039
    name: 'Data model M7: identity across sources'
    url: /TASKS.md#TASK-039
  - id: TASK-040
    name: 'Data model M0a: out with the built-in domain (code)'
    url: /TASKS.md#TASK-040
  - id: TASK-041
    name: 'Data model M0b: template models installed by generation'
    url: /TASKS.md#TASK-041
  - id: TASK-042
    name: 'Connect data C2b: API configurations drafted, incremental reads, frozen contracts'
    url: /TASKS.md#TASK-042
---
# ROADMAP-003 — Phase 2: the agent builds integrations and KPIs

Spec in docs/agent-spec.md and decisions DEC-015 to DEC-020: the runtime (Pydantic AI in a worker job, the model per mode a setting), the loop, the tools, the builder's sandbox, the data the model may see, conversations and the chat, caching and cost. Delivery is in four steps.

- 2a, ask questions and get charts (TASK-012): done and merged (PR 8). Chat over SSE, five providers with fetched model lists and a tool-call test, encrypted secret store, governed read tools with small counts hidden, budgets, the Models page. No live provider has been called yet; that is the first thing to verify with real keys.
- 2b, build an integration from an uploaded file, with the sandbox and the approvals page (TASK-013): next.
- 2c, connect a source system (TASK-014), and 2d, define a KPI (TASK-015): after 2b.
