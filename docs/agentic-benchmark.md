# Agentic BI: what the leading platforms ship, where we stand, and what to build

Status: **draft for discussion, 2026-10-28.** Researched from vendor documentation, release notes and recaps of 2026 events (sources at
the end). Feature status (preview or generally available) moves fast and the recaps sometimes disagree; where it matters, the official
release notes decide.

## 1. The question

"Become a Databricks here" does not mean rebuilding a lakehouse, Spark or a model platform: the BI serves one institution, and those
parts are what Databricks sells to thousands. It means the **agentic layer** the leaders now put on top of governed data:

1. agents that **ask and answer** over governed metrics, with context a data team curates and benchmarks that prove accuracy;
2. agents that **build**: pipelines, semantic models, metrics and dashboards from a description or a file;
3. agents that **watch**: monitor metrics and data, explain changes, and report on a schedule;
4. agents that **act** and **reach people where they work**: other copilots, chat, email, the AMS;
5. all of it **governed**: catalog, classification, approval, audit, spend limits, sandboxes.

## 2. What each platform ships (2026)

| Platform | Ask | Build | Watch | Context and trust | Open access |
|---|---|---|---|---|---|
| **Databricks** | Genie Agents (formerly Genie Spaces; agent mode GA), Genie One "coworker" (documents, scheduled tasks, MCP tools) | Genie Code (pipelines, ML, dashboards; can turn Tableau or Power BI files into AI/BI dashboards), Lakeflow Designer (visual, AI-assisted pipelines), Agent Bricks (build and evaluate agents) | Genie ZeroOps (background monitoring, preview) | Unity Catalog; Genie knowledge store (descriptions, synonyms, joins, SQL expressions); trusted assets; **benchmarks** (test questions, evaluation only); Genie Ontology; data classification (an agent tags PII); AI-generated comments (reviewed) | MCP tools; Unity AI Gateway (spend caps); Databricks Sandbox |
| **Microsoft Fabric / Power BI** | Fabric data agents (GA in Copilot Studio and M365 Copilot; charts in answers); standalone Copilot over every report and model a person can see | Copilot creates and edits report pages from prompts; Creator Agent (preview) | Operations agent (watches live data bound in the ontology, detects rule breaks, triggers actions) | Fabric IQ and its ontology (entities, relationships, rules, actions); "Prep data for AI": AI instructions, verified answers, AI data schema, "Approved for Copilot"; Topics (SQL guidance); Purview audit | M365 Copilot, Copilot Studio, GitHub Copilot CLI, MCP |
| **Snowflake** | Snowflake Intelligence on Cortex Agents (Snowflake now recommends Agents over Cortex Analyst) | Semantic views drafted by "Autopilot" | — | Semantic views with verified queries | Agents API |
| **Tableau Next** | Concierge (questions, root causes, next best actions; GA 2026.1) | Data Pro (prepare and model data) | Inspector (watches data, surfaces anomalies) | Salesforce Data 360 semantic layer | Embedded agents for vendors |
| **Looker** | Conversational Analytics and shareable data agents (up to five Explores, author instructions) | — | — | LookML semantic model | Code Interpreter: Python for forecasting and deeper analysis (preview) |
| **ThoughtSpot** | Spotter 3 | SpotterViz (dashboards from prompts), SpotterModel (semantic models without code), SpotterCode | — | Semantic model | Embedded |
| **Databox** | AI Analyst, Genie (questions; creates dashboards, metrics, goals from prompts) | Artifacts (an answer becomes a shareable report), Skills marketplace | Routines (recurring workflows) | Governed semantic layer | MCP: chat with business data in Claude or ChatGPT |
| **dbt Labs** | Analyst agent (in dbt Insights) | Developer agent (writes, refactors, validates models) | Observability agent (job failures, root causes, fixes) | Discovery agent; semantic layer; benchmark of semantic layer vs text-to-SQL | Remote MCP server (metadata, not rows) |
| **Hex / Omni** | Hex Threads; Omni AI through its semantic layer | Hex Notebook Agent (fixes cells across the project), Modeling Agent (code to semantic models) | — | Hex Context Studio (curated context); a 90-day simulation benchmark | — |
| **Monte Carlo** | — | Monitoring agent proposes data-quality rules and thresholds | Troubleshooting agent: parallel hypotheses to a root cause | — | — |

Five patterns repeat across all of them:

1. **Context beats the model.** Every leader added a curated layer the agent reads first: Genie's knowledge store and ontology, Fabric
   IQ, Power BI's AI instructions and verified answers, Snowflake's verified queries, Hex's Context Studio. Answers are marked
   *trusted* when they come from a verified definition.
2. **Accuracy is measured.** Databricks benchmarks, dbt's semantic-layer benchmark, Hex's simulations: a fixed set of questions with
   known answers, run on every change.
3. **Agents build the stack, people approve it.** Pipelines, models, metrics and dashboards are drafted by agents and reviewed.
4. **Agents watch.** Inspector, the operations agent, ZeroOps, Routines, Monte Carlo: from "ask" to "be told".
5. **Answers travel.** MCP servers, M365 and Copilot Studio, Claude and ChatGPT: the data meets people in the tools they already use.

## 3. Where we stand

| Capability | Leaders | Us today |
|---|---|---|
| Ask over governed metrics | All | **Yes**: the chat agent on Cube, with its own tools, five model providers, charts proposed as drafts |
| Curated context (synonyms, instructions, verified questions, glossary) | Databricks, Microsoft, Snowflake, Hex | **No**: only Cube's descriptions |
| Ontology of business entities | Databricks, Microsoft | **No**: `bi.mapping.SHAPES` is a small, hard-coded start |
| Accuracy benchmarks | Databricks, dbt, Hex | **No** |
| Deep analysis (multi-step, "why", forecasting with code) | Looker, Hex, Genie agent mode, Concierge | **No**: one query at a time |
| Agent builds ingestion | Databricks, Tableau, dbt | **No**: Connect data is rules (header finding, profiles, name matching); agent step 2b planned |
| Agent builds semantic models and metrics | ThoughtSpot, Hex, Snowflake, Databricks | **No**: step 2d planned |
| Agent builds dashboards | ThoughtSpot, Power BI, Databricks, Databox | **Partly**: one chart per proposal; no dashboards yet |
| Watching metrics, explaining changes | Tableau, Microsoft, Databricks, Databox, Monte Carlo | **No** |
| Scheduled briefings and reports | Databricks (Genie One), Databox | **No** |
| Classification of sensitive data | Databricks | **Yes, by rules** (names in English and Arabic, shapes, uniqueness) |
| AI-written documentation | Databricks | **No** |
| Open access (MCP, other copilots) | Databox, dbt, Microsoft, Databricks | **Yes**: the MCP server, with personal tokens and AMS sign-in |
| Governance: approval, audit, budgets, sandbox | All | **Mostly**: approval, MCP access log, token budgets; sandbox for agent code not built |

What we have that they do not, and must keep:

- **Privacy by design for student data**: the model never sees a row (DEC-017), small counts are hidden everywhere, nothing
  student-level leaves the BI. Most platforms send sample rows to the model, or offer it as an option.
- **One institution, its own server**, any model provider (including a local one), no per-seat AI pricing.
- **The AMS**: a contract with the institution's management system, so a KPI can reach the people who act on it.

## 4. What to build: the agentic roadmap

The order follows the first pattern: context and measurement first, because every other agent depends on them. Each stage keeps the
rules that make this BI safe: the model sees schemas, profiles and aggregates (never rows); every KPI is read through Cube; a person
approves what an agent builds; agent code runs in a sandbox.

### Stage A: Context and trust (the foundation)

1. **Knowledge store**, edited on a "Knowledge" page and read by every agent and by MCP: dataset and column descriptions, synonyms in
   English and Arabic ("headcount", "عدد الطلاب"), the institution's glossary (terms, programs, colleges), and instructions ("a term
   code's first four digits are the academic year").
2. **Verified questions**: a question with its governed query, approved by a steward. An answer that uses one is marked *Trusted*,
   as Genie and Power BI do.
3. **Benchmarks**: a set of questions with expected answers, run against the chat agent on every change and every model switch; a
   score per model on the Models page.
4. **AI-written documentation**: the agent drafts descriptions of datasets and columns from their profiles; a person approves them.
5. **The ontology, grown from `SHAPES`**: business entities (student, term, program, course, section, faculty), their keys and
   relationships, which datasets supply them. Both the mapping and the agents read it.

### Stage B: Agents in Connect data

1. **Mapping proposals**: when name rules leave a needed part unmatched or unsure, the agent proposes which column is which from the
   headers and the profiles, with one line of reasoning per choice. The person approves, as today.
2. **New datasets from new data** (step 2b): for a file or table that fits no dataset, the agent drafts the dataset: its dbt model,
   tests, a Cube view and first metrics. They run in the sandbox and are proposed for approval.
3. **Connectors by description**: for an API, the agent drafts a `rest_api` configuration from its OpenAPI document. For a
   database, it proposes which tables matter and which columns can serve as cursors.
4. **Data checks proposed**: from profiles, the agent proposes tests ("term code is never empty", "one row per student and term")
   and thresholds, like Monte Carlo's monitoring agent.

### Stage C: The analyst agent

1. **Multi-step analysis**: the agent plans, runs several governed queries, compares, and explains, for example "why did first-year
   enrollment drop?" broken down by program, level and term, with each step shown.
2. **Code over aggregates**: forecasting, seasonality and anomaly detection in Python. The code runs in the sandbox, on suppressed
   aggregates from Cube only.
3. **Dashboards from a prompt**: "a dashboard for the dean of engineering" becomes a draft of several charts. Review and publishing
   are already in the plan (DEC-013).
4. **Reports**: a written brief with charts, exportable, and shareable with the AMS.

### Stage D: The watcher

1. **Metric monitors**: unusual changes in governed KPIs (week on week, term on term, against a seasonal expectation), with
   suppression applied.
2. **Data health**: freshness (a source that did not sync), volume (a file with half the usual rows), layout drift. Today's review
   flow covers the last one.
3. **Root cause**: when a sync fails or a number moves, the agent tests hypotheses (a new layout, missing terms, a changed program
   code) and explains in plain words.
4. **Scheduled briefings**: a weekly enrollment brief to the people who asked for it.

### Stage E: Reach and act

1. **Where people work**: MCP is done. Next come an M365 Copilot or Teams connector if the institution uses them, email briefings,
   and the AMS through the contract (a KPI breach becomes an AMS task).
2. **Actions with approval**: an agent can propose an action (notify a program head, open an AMS request); a person confirms it.

## 5. What not to copy

- Spark, a lakehouse, model training and serving, a marketplace: built for scale and breadth we do not need.
- Sending sample rows to the model (Looker, Fabric and others can): the privacy rules forbid it, and profiles do the job.
- Per-seat AI pricing and vendor lock-in: the BI stays provider-agnostic.

## 6. Recommendation

Start with **Stage A (1 to 3) together with B1**. These are small, visible and the base for everything else:

- the knowledge store and verified questions make the chat's answers more correct and mark trusted ones;
- benchmarks tell us whether each change (and each model) helps;
- mapping proposals fix the weakness you just saw in Connect data.

Then B2 (new datasets from new data, which is agent step 2b), C1 and C3 (analysis and dashboards), and D (the watcher). Each stage
gets a spec like Connect data before it is built.

## Sources

- Databricks: [AI/BI and Genie release notes 2026](https://docs.databricks.com/aws/en/ai-bi/release-notes/2026),
  [Genie concepts](https://docs.databricks.com/aws/en/genie/concepts),
  [Data + AI Summit 2026 recap (Atlan)](https://atlan.com/know/ai-agent/databricks/databricks-data-ai-summit-2026-announcements/),
  [recap (Qubika)](https://qubika.com/blog/everything-databricks-announced-dais-data-ai-summit-2026/),
  [data classification in Unity Catalog](https://www.databricks.com/blog/find-sensitive-data-scale-data-classification-unity-catalog),
  [AI-generated comments](https://learn.microsoft.com/nb-no/azure/databricks/comments/ai-comments)
- Microsoft: [Fabric September 2026 feature summary](https://community.fabric.microsoft.com/blog/fbc_fabricupdatesblogs/fabric-september-2026-feature-summary/5325825),
  [Fabric data agents in Copilot Studio (GA)](https://community.fabric.microsoft.com/blog/fbc_fabricupdatesblogs/fabric-data-agents-in-microsoft-copilot-studio-generally-available/5362882),
  [Build 2026: agentic apps with Fabric](https://azure.microsoft.com/en-us/blog/microsoft-build-2026-building-agentic-apps-with-microsoft-fabric-and-microsoft-databases/),
  [Fabric IQ (Gartner first take)](https://www.gartner.com/en/insights/gartner-first-takes/microsoft-fabric-iq),
  [Prepare data for AI in Power BI](https://learn.microsoft.com/power-bi/create-reports/copilot-prepare-data-ai)
- Snowflake: [transition from Cortex Analyst to Cortex Agents](https://docs.snowflake.com/release-notes/2026/other/2026-08-28-cortex-analyst-transition-cortex-agents),
  [exploring Snowflake Cortex (InterWorks)](https://interworks.com/blog/2026/06/17/exploring-snowflake-cortex/)
- Tableau: [Tableau Next](https://tableau.com/en-gb/modern-bi), [TechTarget on the launch](https://www.techtarget.com/searchbusinessanalytics/news/366622614/Tableau-enters-the-agentic-AI-era-with-the-launch-of-Next)
- Looker: [Conversational Analytics overview](https://docs.cloud.google.com/looker/docs/2606/conversational-analytics-overview)
- ThoughtSpot: [Spotter agents (TechTarget)](https://www.techtarget.com/data-technologies/news/366636078/ThoughtSpot-automates-full-platform-with-new-Spotter-agents)
- Databox: [AI analytics tools](https://databox.com/best-ai-analytics-tools-for-business-teams), [Databox MCP](https://www.producthunt.com/products/databox/launches/databox-mcp)
- dbt Labs: [agentic features powered by Fusion](https://www.enterpriseaiworld.com/Articles/News/News/dbt-Labs-Offers-New-Agentic-AI-Features-Powered-by-Fusion-171965.aspx),
  [product announcements](https://www.getdbt.com/blog/dbt-labs-cost-optimization-agentic-ai-product-announcements)
- Hex and Omni: [Hex fall 2025 launch](https://hex.tech/blog/fall-2025-launch/), [Omni vs Hex](https://omni.co/omni-vs-hex)
- Monte Carlo: [observability agents](https://www.montecarlodata.com/blog-monte-carlo-observability-agents)
