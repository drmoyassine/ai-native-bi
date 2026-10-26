---
okf_version: "0.2"
title: "AI-native BI Log"
generated:
  by: "process:vef-init"
  at: "2026-10-26T13:17:17.625Z"
---

# Log

Chronological log of decisions, discoveries, and session learnings. This is the **single-source memory** — durable context that survives across sessions. Newest entries first.

> **OKF reserved filename.** `log.md` follows the [Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) convention. It links to DECISIONS.md; decisions remain the canonical record.

---

## 2026-10-26 — Phase 1 closed

Pull request #4 merged (phases 0 and 1). Cube now connects as its own role, which reads `analytics` only (TASK-007): rule 5 holds
in the database, not only in Cube's model. Learned: in compose, Cube must wait for the API (which creates and grants its role) and the
worker for Cube's readiness (`/readyz`), or the first queries fail while Cube starts. The privacy rules and small-cell suppression
(TASK-002, TASK-008) now sit under ROADMAP-008 "First real data": they gate real data, not the pipeline.

## 2026-10-26 — Phase 1: the pipeline end to end, on made-up files

A file now goes all the way: raw (dlt, cells as text, the file kept unchanged), dbt (staging, analytics, data tests), Cube
(`enrollment_headcount`), and the worker answers the AMS from Cube (TASK-004, TASK-005; DEC-010, DEC-011). Learned on the way:
Cube in production mode needs Cube Store unless its cache and queue run in memory (one instance: memory); Cube 1.8 refuses
`renewQuery` and takes `cache: "must-revalidate"` in the request body instead; an all-empty column would vanish from raw unless every
header is declared as a text column; Cube answers numbers as text. Follow-ups: a read-only role for Cube (TASK-007), small-cell
suppression once the privacy rules are set (TASK-008, TASK-002).

## 2026-10-26 — Phase 0: the scaffold runs on Python

ROADMAP-001 done (TASK-001, DEC-003). The AMS adapter is now `src/bi`: FastAPI, Pydantic, Procrastinate, httpx, psycopg, with the
same behaviour as the TypeScript scaffold, which was removed. Learned on the way: a supply must leave out absent fields rather than send
`null` (the AMS's schema refuses null for optional fields), so `SupplyBody.wire()` drops top-level None and keeps null cells. Node
stays only for VEF.

## 2026-10-26 — Product direction recorded

Recorded the product as an AI-native BI platform that works on its own and with the AMS, from the Institutional Effectiveness Data
Architecture diagram (`docs/architecture.png`). Vision themes `governed-kpis`, `agent-built-bi`, `open-consumption`; decisions
DEC-002 to DEC-009 (one institution, Python, Cube as the only read path, warehouse layout, approval of agent work, the AMS requests,
first slice from real file exports, one API and MCP server); phases as ROADMAP-001 to ROADMAP-007; tasks TASK-001 to TASK-006.
`docs/architecture.md` was merged into `ARCHITECTURE.md`. Contract changes for the AMS are in `docs/ams-contract-proposals.md`.

## 2026-10-26 — Framework adopted

Adopted `vibe-engineering-framework` through `vef setup`; `vef check` confirmed deterministic core enforcement. Framework docs (VISION, ROADMAP, TASKS, DECISIONS) are the public reading surfaces over canonical records. Claude Code skills (`/tasks`, `/roadmap`, `/decisions`, `/bugs`, `/apply`) were installed in `.claude/skills/`.
