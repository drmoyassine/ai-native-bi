---
id: TASK-010
title: Throttle sign-in attempts
description: Slow down or lock repeated failed sign-ins per email and per address
status: completed
priority: P1
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
  at: '2026-10-27T12:17:26.214Z'
---
# TASK-010 — Throttle sign-in attempts

Argon2id makes each guess slow, but nothing limited how many were tried. Done: failed sign-ins are recorded (migration 0008), by the
email typed whether or not it exists and by client address; 10 failures for one email or 20 from one address in 15 minutes refuse
the next attempt with 429 and Retry-After, before any password work; a successful sign-in clears that email's failures. Settings
SIGN_IN_WINDOW_MINUTES, SIGN_IN_MAX_FAILURES_PER_EMAIL, SIGN_IN_MAX_FAILURES_PER_IP and TRUSTED_PROXY_HOPS: the client address is
read from X-Forwarded-For only as far as the operator says proxies append (behind Easypanel's router: 1), the entry the nearest
proxy appended, never a client-supplied one. Changing a password is held to the same limits. Verified through the real app over
HTTP (lockout, window, per-address limit, trusted and spoofed forwarded addresses) with mutation checks, and in a browser.
Trade-off: someone who knows an email can lock that account for the window by failing on purpose; the window is short and the
per-address limit keeps one address from doing it to many.
