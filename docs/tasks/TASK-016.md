---
title: 'MCP step 3a: shared tools, personal access tokens, /mcp'
description: >-
  Tools moved to src/bi/tools and shared by the chat and MCP; personal access tokens and their page; the MCP server at
  /mcp with the access log and rate limits
status: completed
priority: P1
id: TASK-016
last_updated: '2026-10-27'
generated:
  by: agent/claude-code
  at: '2026-10-27T06:57:34.731Z'
roadmap_item:
  id: ROADMAP-004
  name: 'Phase 3: API, MCP server, charts and dashboards, document AI'
  url: /ROADMAP.md#ROADMAP-004
related_decisions:
  - id: DEC-021
    name: The MCP server is the official SDK's MCPServer, mounted in the API at /mcp
    url: /DECISIONS.md#DEC-021
  - id: DEC-022
    name: One principal behind many issuers; personal access tokens first
    url: /DECISIONS.md#DEC-022
  - id: DEC-024
    name: The chat agent and the MCP server share one tool implementation
    url: /DECISIONS.md#DEC-024
modified:
  by: agent/claude-code
  at: '2026-10-27T06:57:34.731Z'
---
# TASK-016 — MCP step 3a: shared tools, personal access tokens, /mcp

docs/mcp-spec.md section 10, step 3a. Done: src/bi/tools (shared by the chat agent and the MCP server); migration 0006 (access_token,
access_log); src/bi/mcp (principal and token verifier, the MCPServer with six tools, rate limits, access log, token routes);
/mcp mounted in the API with its session manager in the lifespan; the Access tokens page; PUBLIC_URL and MCP limits settings.
Verified by: the SDK's real MCP client against the mounted app (tools, suppression, as-of date, drafts, another person's draft
refused, rate limit, access log); refusals of no token, a wrong one, a JWT from an unconfigured issuer, an expired or revoked
token, a disabled person and a foreign Host; mutation checks (revocation ignored, suppression off) made the tests fail; a
browser-made token used over real HTTP against real Cube.
