---
id: ROADMAP-004
title: 'Phase 3: API, MCP server, charts and dashboards, document AI'
description: >-
  The general-purpose API and MCP server on Cube; the chart definition (DEC-012) built by the agent, by API and by drag
  and drop; dashboards; charts served as data or images; document AI over SharePoint and AMS files
phase: '3'
status: Deferred
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
modified:
  by: process:vef-cli
  at: '2026-10-27T06:37:40.690Z'
---
# ROADMAP-004 — Phase 3: API, MCP server, charts and dashboards, document AI

The MCP server is specified in docs/mcp-spec.md (proposed 2026-10-27): the official MCP SDK's MCPServer mounted in the API at /mcp, the chat agent's governed read tools shared, one principal behind several issuers (BI personal access tokens first, then the AMS and the institution's SSO), and data scope enforced in Cube. Person identity from the AMS is requested in issue 10 (proposal 5 in docs/ams-contract-proposals.md). Decisions are recorded once the spec is approved.
