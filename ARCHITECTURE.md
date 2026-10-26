---
okf_version: "0.2"
title: "AI-native BI Architecture"
generated:
  by: "process:vef-init"
  at: "2026-10-26T13:17:17.625Z"
---

# Architecture

How AI-native BI works — system structure, data model, key patterns, and the design decisions behind them. This is a living document: update it when the architecture changes, and link architectural decisions to [DECISIONS.md](DECISIONS.md) for their rationale.

> **OKF conformance.** This document follows the [Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) convention. Architectural decisions recorded here should link to their canonical record in DECISIONS.md.

---

## System overview

The BI is the institution's **AI-native business intelligence platform**: one institution, one deployment
([DEC-002](DECISIONS.md#DEC-002)). It takes data from the institution's source systems, keeps it in its own warehouse, defines every
KPI once in a governed metric layer, and serves those KPIs to every consumer. An **agent** builds most of it: the integrations, the
KPIs and the dashboards, each approved by a person before it goes live ([DEC-006](DECISIONS.md#DEC-006)).

It works **on its own** and **with the AMS** (drmoyassine/ams), the accreditation and quality management system, which is one
consumer among others (see "The AMS" below).

![Institutional effectiveness data architecture](docs/architecture.png)

*Institutional Effectiveness Data Architecture, Mohamad Yassine, Manager of Institutional Effectiveness, 23 September 2026.*

| Layer | What | Built with |
|---|---|---|
| Sources | Students (Banner SIS, DegreeWorks), faculty and staff (FAS/SAS), learning outcomes (Canvas, DegreeWorks, X-Matrix, Explorance), feedback and research (Explorance Blue, DSpace), strategic planning (X-Matrix, FAS/SAS), finance (Oracle Fusion), documents (SharePoint, policies, criteria, AMS evidence files), and manual entry, sheets and forms | Read-only access; each source is one integration |
| Extract and load | Each integration copies a source as it is into **raw** storage: files in S3, immutable, loaded into the `raw` schema | dlt pipelines, one standard pattern the agent fills in |
| Transform | `raw` into **analytical** data in the `analytics` schema: conformed across sources, at student grain | SQL models (dbt or SQLMesh, [TASK-003](TASKS.md#TASK-003)) |
| Governed layer | Each KPI defined **once** in the metric registry, with its steward, version and lineage; row-level security; certified snapshots (a report or dataset saved as it was at a point in time) | Cube (Cube Core, open source) |
| Serving | One general-purpose API and an MCP server on top of Cube ([DEC-009](DECISIONS.md#DEC-009)) | FastAPI; MCP |
| Consumers | The BI's own dashboards (the KPI canvas, generative UI), the AMS, Tableau and Power BI (Cube's SQL API), third-party apps and AI agents | |

The back end is Python ([DEC-003](DECISIONS.md#DEC-003)): FastAPI, Pydantic, Procrastinate, dlt, pytest. The UI is TypeScript/React;
Cube is its own Node service. Today's code is still the TypeScript scaffold of the AMS adapter until [ROADMAP-001](ROADMAP.md#ROADMAP-001)
ports it.

## Data model

- **Warehouse** ([DEC-005](DECISIONS.md#DEC-005)): PostgreSQL, the BI's own database also when it shares a server with the AMS
  (AMS DEC-017 and AMS DEC-034), with the schemas `raw` (sources as they are) and `analytics` (conformed, student grain), plus S3 for raw
  files and documents.
- **Metric registry**: the Cube model; one definition per KPI, with steward, version and lineage.
- **AMS requests**: `collect_request` (migration `0001`), one row per AMS run and attempt, holding the request and its outcome
  (`queued`, `running`, `supplied`, `no_source`, `refused`, `failed`). The callback token is cleared when the request ends.

## Key patterns

- **Every read of a KPI goes through Cube** ([DEC-004](DECISIONS.md#DEC-004)). The canvas, the AMS adapter, the API, the MCP server
  and Tableau or Power BI read the governed layer, never the `raw` or `analytics` tables.
- **Structured queries only.** Consumers, including AI agents and the AMS, ask in Cube's terms (measures, dimensions, filters,
  time); nobody sends SQL.
- **Extract and load, then transform.** Raw data is immutable and replayable; transforms can be rebuilt from it.
- **The agent fills in standard patterns.** Integrations follow one dlt pattern and KPIs one Cube pattern, proven by hand first
  ([ROADMAP-002](ROADMAP.md#ROADMAP-002)) and then copied by the agent ([ROADMAP-003](ROADMAP.md#ROADMAP-003)).
- **No invented data.** A KPI with no data has no answer. Every answer carries `asOf` and `lineage`.

### The agent

The agent is how people use the BI. In a chat, a user asks it to:

- **Connect a source.** It asks what it needs (the system, credentials, which tables or exports), writes the integration from the
  standard pattern, tests it on real data, sets the privileges and runs the first load into the warehouse.
- **Define a KPI.** It writes the transform and the Cube definition, shows the result and its lineage, and waits for approval.
- **Build a dashboard.** Generative UI: it composes the dashboard from governed KPIs; the user then configures it.

### The AMS

The AMS **requests**; the BI **owns its KPIs end to end** ([DEC-007](DECISIONS.md#DEC-007)). The AMS may ask for a reading of a
KPI, a table, a dashboard, or a new KPI (by a request schema), and the BI answers in the format asked. Manual entry, sheets and forms
belong to the BI.

Today the contract (`docs/ams-bi-contract-v0.md`, owned by the AMS; routes in `docs/endpoints.md`) covers one kind of request:
collect one run (`POST /ams/collect`, answered 202 and then by the callback). The other kinds need the AMS to change the contract
first: see `docs/ams-contract-proposals.md` ([TASK-006](TASKS.md#TASK-006)).

## Cross-cutting concerns

- **Approval** ([DEC-006](DECISIONS.md#DEC-006)): an integration, a KPI or a dashboard built by the agent is live only after a
  person approves it, including a KPI the AMS asks for.
- **Agent containment:** the agent's code runs in a sandbox; credentials go to a secret store, never into code, the repository or
  logs; access to sources is read-only.
- **Privacy:** nothing student-level leaves the BI; consumers get aggregates with small cells suppressed. The rules (regulator,
  threshold, how a suppressed cell is marked) are open: [TASK-002](TASKS.md#TASK-002), before the first real data. Real exports are
  never committed to the repository ([DEC-008](DECISIONS.md#DEC-008)).
- **Security:** row-level security in Cube. The AMS calls with `BI_API_KEY`; the BI calls back only the run's own supply route on
  `AMS_CALLBACK_ORIGIN`, never follows a redirect, and forgets the token when the request ends.
- **Authentication:** the BI's own accounts first, the institution's single sign-on later ([ROADMAP-005](ROADMAP.md#ROADMAP-005)).
- **Observability:** structured JSON logs.
- **Deployment:** Docker Compose, alone (`compose.yaml`) or beside the AMS (`compose.together.yaml`). A later self-serve free trial
  is its own small deployment on a real PostgreSQL ([ROADMAP-007](ROADMAP.md#ROADMAP-007)).

## Architectural decisions

- **One institution per deployment** — see [DEC-002](DECISIONS.md#DEC-002)
- **Python stack (FastAPI)** — see [DEC-003](DECISIONS.md#DEC-003)
- **Cube is the governed layer and the only read path for KPIs** — see [DEC-004](DECISIONS.md#DEC-004)
- **Warehouse: raw and analytics on PostgreSQL, raw files on S3** — see [DEC-005](DECISIONS.md#DEC-005)
- **A person approves what the agent builds** — see [DEC-006](DECISIONS.md#DEC-006)
- **The AMS requests; the BI owns its KPIs end to end** — see [DEC-007](DECISIONS.md#DEC-007)
- **First slice from real file exports; Banner through the agent** — see [DEC-008](DECISIONS.md#DEC-008)
- **One general-purpose API and MCP server on Cube** — see [DEC-009](DECISIONS.md#DEC-009)

The phases are roadmap items: [ROADMAP.md](ROADMAP.md).

## How to update this document

- When you add a new component or service, document it in **System overview**.
- When you make an architectural decision, record it in DECISIONS.md (`/decisions add`) and link it from the relevant section above.
- When you change the data model, update **Data model**.
- Run `vef setup` after direct canonical edits and `vef check` as the strict local/CI acceptance gate.
- Use `vef show`, `vef refs`, `vef why`, `vef graph`, and `vef search` to inspect canonical project state without an agent.
