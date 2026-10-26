---
id: TASK-001
title: Port the scaffold to Python
description: >-
  Contract mirror in Pydantic, POST /ams/collect on FastAPI, the collect queue on Procrastinate, the callback, tests in
  pytest
status: completed
priority: P0
last_updated: '2026-10-26'
generated:
  by: agent/claude-code
  at: '2026-10-26T13:23:31.090Z'
roadmap_item:
  id: ROADMAP-001
  name: 'Phase 0: port the scaffold to Python'
  url: /ROADMAP.md#ROADMAP-001
related_decisions:
  - id: DEC-003
    name: Python stack (FastAPI)
    url: /DECISIONS.md#DEC-003
modified:
  by: agent/claude-code
  at: '2026-10-26T13:36:30.998Z'
---
# TASK-001 — Port the scaffold to Python

Acceptance: the existing Vitest cases pass as pytest cases against PostgreSQL; the TypeScript packages are removed; CLAUDE.md Checks updated.

Done 2026-10-26. `src/bi` (FastAPI, Pydantic, Procrastinate, httpx, psycopg); every Vitest case ported to pytest, plus tests for
redirects, retries, configuration and the real queue (22 tests). Migrations moved to `src/bi/migrations` with the same names and
`schema_migration` table, so an existing database carries over; Procrastinate's schema is migration 0002. Images built and run end
to end against PostgreSQL. CI runs ruff, mypy and pytest.
