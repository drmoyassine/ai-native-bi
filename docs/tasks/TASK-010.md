---
id: TASK-010
title: Throttle sign-in attempts
description: Slow down or lock repeated failed sign-ins per email and per address
status: pending
priority: P1
last_updated: '2026-10-26'
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
  at: '2026-10-26T21:39:41.703Z'
---
# TASK-010 — Throttle sign-in attempts

Argon2id makes each guess slow, but nothing limits how many are tried. Needed before the app is reachable from outside the institution.
