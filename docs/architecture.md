# Architecture

The BI is the institution's **AI-native business intelligence platform**: one institution, one deployment. It takes data from the
institution's source systems, keeps it in its own warehouse, defines every KPI once in a governed metric layer, and serves those
KPIs to every consumer. An **agent** builds most of it: the integrations, the KPIs and the dashboards, each approved by a person
before it goes live.

It works **on its own** and **with the AMS** (drmoyassine/ams), the accreditation and quality management system. With the AMS,
the AMS is one consumer among others: it asks, the BI answers (see "The AMS" below).

![Institutional effectiveness data architecture](architecture.png)

*Institutional Effectiveness Data Architecture, Mohamad Yassine, Manager of Institutional Effectiveness, 23 September 2026.*

## Layers

| Layer | What | Built with |
|---|---|---|
| Sources | Students (Banner SIS, DegreeWorks), faculty and staff (FAS/SAS), learning outcomes (Canvas, DegreeWorks, X-Matrix, Explorance), feedback and research (Explorance Blue, DSpace), strategic planning (X-Matrix, FAS/SAS), finance (Oracle Fusion), documents (SharePoint, policies, criteria, AMS evidence files), and manual entry, sheets and forms | Read-only access; each source is one integration |
| Extract and load | Each integration copies a source as it is into **raw** storage: files in S3, immutable, loaded into the `raw` schema | dlt pipelines, one standard pattern the agent fills in |
| Transform | `raw` into **analytical** data in the `analytics` schema: conformed across sources, at student grain | SQL models (dbt or SQLMesh, to decide in phase 1) |
| Governed layer | Each KPI defined **once** in the metric registry, with its steward, version and lineage; row-level security; certified snapshots (a report or dataset saved as it was at a point in time) | Cube (Cube Core, open source) |
| Serving | One general-purpose API and an MCP server on top of Cube | FastAPI; MCP |
| Consumers | The BI's own dashboards (the KPI canvas, generative UI), the AMS, Tableau and Power BI (Cube's SQL API), third-party apps and AI agents | |

The warehouse is PostgreSQL (schemas `raw` and `analytics`) plus S3 (raw files, documents). The BI has its own database, also when it
shares a PostgreSQL server with the AMS.

## Rules of the architecture

- **Every read of a KPI goes through Cube.** The canvas, the AMS adapter, the API, the MCP server and Tableau or Power BI read the
  governed layer, never the `raw` or `analytics` tables. Row-level security and lineage then live in one place.
- **Structured queries only.** Consumers, including AI agents and the AMS, ask in Cube's query terms (measures, dimensions, filters,
  time); nobody sends SQL.
- **Nothing student-level leaves the BI.** Student grain stays in `analytics`; consumers get aggregates, with small cells suppressed.
- **No invented data.** A KPI with no data has no answer. Every answer carries `asOf` and `lineage`.
- **A person approves what the agent builds.** An integration, a KPI or a dashboard goes live only after a person approves it,
  including a KPI the AMS asks for.

## The agent

The agent is how people use the BI. In a chat, a user asks it to:

- **Connect a source.** It asks what it needs (the system, credentials, which tables or exports), writes the integration from the
  standard pattern, tests it on real data, sets the privileges and runs the first load into the warehouse.
- **Define a KPI.** It writes the transform and the Cube definition, shows the result and its lineage, and waits for approval.
- **Build a dashboard.** Generative UI: it composes the dashboard from governed KPIs; the user then configures it.

Guardrails: the agent's code runs in a sandbox; credentials go to a secret store, never into code, the repository or logs; access
to sources is read-only; nothing it builds is live until approved.

## The AMS

The AMS **requests**; the BI **owns its KPIs end to end**. The AMS may ask for a reading of a KPI, a table, a dashboard, or a new KPI
(by a request schema), and the BI answers in the format asked. Manual entry, sheets and forms belong to the BI: the AMS asks for them
and the BI sends them back.

Today the contract (`docs/ams-bi-contract-v0.md`, owned by the AMS) covers one kind of request: collect one run (`POST /ams/collect`,
answered by the callback). The other kinds need the AMS to change the contract first: see `docs/ams-contract-proposals.md`.

## Deployment

- **The institution:** one deployment (Docker Compose), alone (`compose.yaml`) or beside the AMS (`compose.together.yaml`).
- **Free trial (later):** a self-serve trial for another institution, still one institution per deployment. It runs on a small
  PostgreSQL of its own (not PGlite: Cube needs a real PostgreSQL connection). At its end it becomes a paid hosted deployment, or is
  archived (a dump, the instance stopped).

## Phases

| Phase | What |
|---|---|
| 0 | Port the scaffold (TypeScript, Hono) to Python: FastAPI, Pydantic, Procrastinate, pytest; same behaviour, same tests |
| 1 | One slice by hand, from files: `.xlsb`, `.xlsx` and `.csv` exports → raw → analytics → Cube → `enrollment_headcount` → answered to the AMS. Proves every layer and becomes the pattern the agent copies |
| 2 | The agent: connects sources (Banner first, end to end, from the frontend) and defines KPIs from the pattern, with approval |
| 3 | The general-purpose API and MCP server on Cube; the KPI canvas with generative dashboards; document AI over SharePoint and AMS files |
| Later | Single sign-on with the institution (the BI's own accounts until then); AMS requests beyond `collect`; the free trial |

## Open questions

1. Privacy: which regulator and data protection law apply (PUC among the accreditors), the small-cell suppression threshold, and how a
   suppressed cell is marked in a supply. To settle before the first real student data.
2. dbt or SQLMesh for transforms (phase 1).
3. Which sign-on the institution uses (later).
