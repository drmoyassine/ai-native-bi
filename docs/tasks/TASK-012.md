---
id: TASK-012
title: 'Agent step 2a: ask questions, get charts'
description: >-
  Pydantic AI loop in the worker, five providers with fetched model lists and the selector, secret store, chat with SSE,
  governed read tools, scrubber, usage
status: completed
priority: P0
last_updated: '2026-10-26'
generated:
  by: agent/claude-code
  at: '2026-10-26T22:07:12.855Z'
roadmap_item:
  id: ROADMAP-003
  name: 'Phase 2: the agent builds integrations and KPIs'
  url: /ROADMAP.md#ROADMAP-003
related_decisions:
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
  - id: DEC-020
    name: Secrets in an encrypted table behind a small interface; budgets; language
    url: /DECISIONS.md#DEC-020
modified:
  by: process:vef-cli
  at: '2026-10-26T22:39:08.759Z'
---
# TASK-012 — Agent step 2a: ask questions, get charts

docs/agent-spec.md section 11, step 2a. Done: Pydantic AI loop in a worker job (never retried, one turn per conversation at a time);
five providers with fetched model lists, a tool-call test before a model is allowed, and the selector; encrypted secret store;
chat over SSE with stop and usage; governed read tools (list_metrics, query_metric, propose_chart, list_datasets, describe_dataset);
small-count hiding in the tools and in the draft chart's data route; monthly budgets; admin Models page; chat page.
Verified by: scripted-model turn tests (including a mutation check that the suppression test fails when suppression is broken),
route tests, a fake OpenAI-protocol server over real HTTP (provider, key from the secret store, streaming tool calls, replayed history),
the tools against a real Cube, and a headless browser walk-through of the whole flow.
Not verified: any live provider (Anthropic cache and thinking settings, OpenRouter, Ollama); the finish reasons "length" and
"content_filter" are handled but not unit-tested. Left for later: complementary suppression (TASK-008), build mode (TASK-013).
