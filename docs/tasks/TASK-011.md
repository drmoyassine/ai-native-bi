---
id: TASK-011
title: Manage accounts in the app
description: An admin invites, disables and resets accounts from the app instead of the command line
status: in-progress
priority: P2
last_updated: '2026-10-27'
generated:
  by: agent/claude-code
  at: '2026-10-26T21:39:41.703Z'
roadmap_item:
  id: ROADMAP-009
  name: 'The app shell: sign-in, uploads, a first chart'
  url: /ROADMAP.md#ROADMAP-009
related_decisions:
  - id: DEC-014
    name: 'The app: the BI''s own accounts, a cookie session, a React app served by the API'
    url: /DECISIONS.md#DEC-014
modified:
  by: agent/claude-code
  at: '2026-10-27T12:17:26.912Z'
---
# TASK-011 — Manage accounts in the app

Done so far: a person changes their own password on the Account page (the current password, at least 12 characters, different from
the current one; their sessions on other devices end; same throttle as sign-in), reached from their name in the header; a person
signed in through the AMS has no password here and is told so. Still to do: an administrator creating, disabling and resetting
people's accounts in the app instead of by command line (python -m bi.main_user).
