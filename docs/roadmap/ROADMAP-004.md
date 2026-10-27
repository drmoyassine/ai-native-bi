---
id: ROADMAP-004
title: 'Phase 3: API, MCP server, charts and dashboards, document AI'
description: >-
  The general-purpose API and MCP server on Cube; the chart definition (DEC-012) built by the agent, by API and by drag
  and drop; dashboards; charts served as data or images; document AI over SharePoint and AMS files
phase: '3'
status: In Progress
priority: P1
tags:
  - api
  - mcp
  - ui
last_updated: '2026-10-27'
generated:
  by: agent/claude-code
  at: '2026-10-26T13:23:31.090Z'
vision_theme:
  id: open-consumption
  name: Every consumer, one governed layer
  url: /VISION.md#open-consumption
related_decisions:
  - id: DEC-009
    name: One general-purpose API and MCP server on Cube
    url: /DECISIONS.md#DEC-009
  - id: DEC-012
    name: One chart definition, rendered with ECharts
    url: /DECISIONS.md#DEC-012
  - id: DEC-013
    name: 'Charts and dashboards: private drafts, approved to publish'
    url: /DECISIONS.md#DEC-013
  - id: DEC-021
    name: The MCP server is the official SDK's MCPServer, mounted in the API at /mcp
    url: /DECISIONS.md#DEC-021
  - id: DEC-022
    name: One principal behind many issuers; personal access tokens first
    url: /DECISIONS.md#DEC-022
  - id: DEC-023
    name: Data scope is enforced in Cube's security context, for every consumer
    url: /DECISIONS.md#DEC-023
  - id: DEC-024
    name: The chat agent and the MCP server share one tool implementation
    url: /DECISIONS.md#DEC-024
  - id: DEC-025
    name: The AMS's access tokens act for a person on the MCP server
    url: /DECISIONS.md#DEC-025
modified:
  by: agent/claude-code
  at: '2026-10-27T11:29:30.313Z'
related_tasks:
  - id: TASK-016
    name: 'MCP step 3a: shared tools, personal access tokens, /mcp'
    url: /TASKS.md#TASK-016
  - id: TASK-017
    name: 'MCP step 3b: connect staging to Claude Code'
    url: /TASKS.md#TASK-017
  - id: TASK-018
    name: 'MCP step 3c: the AMS as identity provider, OAuth for MCP clients'
    url: /TASKS.md#TASK-018
  - id: TASK-019
    name: 'MCP step 3d: data scope in Cube security context'
    url: /TASKS.md#TASK-019
---
# ROADMAP-004 — Phase 3: API, MCP server, charts and dashboards, document AI

The MCP server is specified in docs/mcp-spec.md (proposed 2026-10-27): the official MCP SDK's MCPServer mounted in the API at /mcp, the chat agent's governed read tools shared, one principal behind several issuers (BI personal access tokens first, then the AMS and the institution's SSO), and data scope enforced in Cube. Person identity from the AMS is requested in issue 10 (proposal 5 in docs/ams-contract-proposals.md). Decisions are recorded once the spec is approved.
