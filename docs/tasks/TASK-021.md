---
title: Co-deployment on one database, in the BI's own schemas
description: >-
  Contract 6.3 (AMS DEC-034 revised) - with the AMS, one PostgreSQL database; the BI's tables in bi, its queue in its
  own schema, public for analytic data
status: pending
priority: P1
id: TASK-021
last_updated: '2026-10-27'
generated:
  by: agent/claude-code
  at: '2026-10-27T11:29:31.698Z'
roadmap_item:
  id: ROADMAP-002
  name: 'Phase 1: the pipeline end to end, from files to the AMS'
  url: /ROADMAP.md#ROADMAP-002
related_decisions:
  - id: DEC-005
    name: 'Warehouse: raw and analytics on PostgreSQL, raw files on S3'
    url: /DECISIONS.md#DEC-005
modified:
  by: agent/claude-code
  at: '2026-10-27T11:29:31.698Z'
---
# TASK-021 — Co-deployment on one database, in the BI's own schemas

Contract 6.3: when both run together they share one PostgreSQL database. The AMS lives in ams (and pgboss) and leaves public empty
and closed until the BI grants its own role. The BI must keep its tables in a bi schema, its Procrastinate queue in a schema of its
own (never pgboss), and its analytic data in public, with no privilege on the AMS's schemas. Today the BI has its own database with
its tables in public. To do: the migrations' search_path and schema, Procrastinate's schema, dbt's target schemas, Cube's grants,
compose.together.yaml, and a test that the BI's role cannot read ams. Standalone deployments can keep a database of their own.
