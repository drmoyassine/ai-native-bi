---
okf_version: "0.2"
title: "AI-native BI Index"
generated:
  by: "process:vef-init"
  at: "2026-10-26T13:17:17.625Z"
---

# Index

Navigation hub for AI-native BI documentation.

> **OKF reserved filename.** `index.md` follows the [Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) convention.

## Core documents

| Document | Purpose |
|---|---|
| [VISION.md](VISION.md) | Why we exist, north-star direction |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the system works — data model, patterns |
| [ROADMAP.md](ROADMAP.md) | Directional roadmap — quarters, themes |
| [TASKS.md](TASKS.md) | Work breakdown — tasks with status, owners |
| [DECISIONS.md](DECISIONS.md) | Architectural/product/technical decisions |
| [log.md](log.md) | Chronological log + session learnings |
| [CLAUDE.md](CLAUDE.md) | Repo-level instructions for Claude Code |
| [AGENTS.md](AGENTS.md) | Working conventions for AI agents |
| [docs/ams-bi-contract-v0.md](docs/ams-bi-contract-v0.md) | The AMS–BI contract (a copy; the AMS owns it) |
| [docs/endpoints.md](docs/endpoints.md) | The contract's routes: who calls, who serves |
| [docs/ams-contract-proposals.md](docs/ams-contract-proposals.md) | Contract changes to raise in the AMS |

Structured items live canonically in `docs/vision/`, `docs/roadmap/`, `docs/tasks/`, and `docs/decisions/`. The linked root ledgers are generated, committed views; run `vef setup`, then `vef check`, after direct item changes.

## Query project state

Use `vef list`, `vef show`, `vef refs`, `vef why`, `vef graph`, and `vef search` for deterministic read-only retrieval. Add `--json` for the versioned automation contract.

## External

| Source | URL |
|---|---|
| GitHub Issues | https://github.com/drmoyassine/ai-native-bi/issues |
| Repository | https://github.com/drmoyassine/ai-native-bi |
