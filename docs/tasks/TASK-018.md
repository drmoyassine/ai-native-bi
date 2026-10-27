---
title: 'MCP step 3c: the AMS as identity provider, OAuth for MCP clients'
description: >-
  Accept AMS-issued tokens (OIDC discovery, JWKS) and advertise the AMS as authorization server, once issue 10 is agreed
  and built
status: completed
priority: P1
id: TASK-018
last_updated: '2026-10-27'
generated:
  by: agent/claude-code
  at: '2026-10-27T06:57:36.211Z'
roadmap_item:
  id: ROADMAP-004
  name: 'Phase 3: API, MCP server, charts and dashboards, document AI'
  url: /ROADMAP.md#ROADMAP-004
related_decisions:
  - id: DEC-022
    name: One principal behind many issuers; personal access tokens first
    url: /DECISIONS.md#DEC-022
  - id: DEC-025
    name: The AMS's access tokens act for a person on the MCP server
    url: /DECISIONS.md#DEC-025
modified:
  by: agent/claude-code
  at: '2026-10-27T11:29:53.682Z'
---
# TASK-018 — MCP step 3c: the AMS as identity provider, OAuth for MCP clients

docs/mcp-spec.md section 10, step 3c (DEC-025; contract 6.2, AMS DEC-035). Done: src/bi/mcp/oidc.py checks the AMS's access tokens
(EdDSA, at+jwt, issuer, audience, expiry) against its published keys, cached and refetched at most once a minute for an unknown
key; the verifier dispatches a JWT to the issuer it names; migration 0007 (external_identity; app_user without a password); an AMS
person's local record keyed by (issuer, subject), linked to a BI account with the same email; bi_role and bi_scope read from each
token (institution = all, narrower refused); the protected-resource metadata names the AMS so MCP clients sign in there; settings
AMS_OAUTH_ISSUER and OAUTH_AUDIENCE. Verified with a fake AMS publishing Ed25519 keys and the SDK's real MCP client: valid tokens
work and are logged as ams:<client>; another audience, another issuer, expired, an unpublished key, an ID token, unsigned, no or
unknown role, no email all refused; key rotation fetched once; mutation checks (ID tokens accepted, audience unchecked) failed the tests.
Not yet on staging: the AMS's BI_OAUTH_AUDIENCE and OAUTH_CLIENTS (an AMS admin's settings) and the BI's AMS_OAUTH_ISSUER.
