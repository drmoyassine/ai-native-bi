---
id: TASK-007
title: A read-only database role for Cube
description: Cube connects as the BI's owner role today; give it a role that can only read analytics
status: completed
priority: P1
last_updated: '2026-10-26'
generated:
  by: agent/claude-code
  at: '2026-10-26T18:14:30.345Z'
roadmap_item:
  id: ROADMAP-002
  name: 'Phase 1: the pipeline end to end, from files to the AMS'
  url: /ROADMAP.md#ROADMAP-002
related_decisions:
  - id: DEC-004
    name: Cube is the governed layer and the only read path for KPIs
    url: /DECISIONS.md#DEC-004
modified:
  by: agent/claude-code
  at: '2026-10-26T21:22:32.764Z'
---
# TASK-007 — A read-only database role for Cube

Cube's model only reads analytics, but its database role can read raw too. A role with SELECT on analytics only makes rule 5 hold in the database, not only in the model. Roles are server-level: created with the database (ensure_database) or by the deployment.

Done 2026-10-26. Cube connects as `CUBE_DB_USER` (default `bi_cube`). At start the API creates it with `BI_DATABASE_ADMIN_URL` (or resets its password) and, as the BI's own role, grants it the analytics schema: usage, select on its tables, and default privileges so the tables dbt rebuilds stay readable. raw, staging and the BI's own tables are never granted (tests/test_reader.py; checked in Docker Compose: `permission denied for schema raw`).
