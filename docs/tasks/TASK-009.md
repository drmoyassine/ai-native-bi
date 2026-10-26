---
id: TASK-009
title: Build the app shell
description: Accounts and sessions, uploads through the load job, the chart page; served by the API
status: completed
priority: P0
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
# TASK-009 — Build the app shell

Done 2026-10-26. Backend: accounts.py, app.py (/app/api), uploads.py (the load job), charts.py (chart definition v1), migration 0004, main_user.py. Frontend: web/ (Vite, React, TypeScript strict, ECharts): sign-in, uploads with live status, a chart page whose chart definition is shown. Tested: pytest (accounts, the header on writes, uploads refused and accepted, the load job loaded and failed, chart data with governed members only), vitest (the translator), and a browser walk-through against the app in Docker Compose.
