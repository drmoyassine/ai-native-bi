# Spec: The data model — configured, agnostic of organisation and industry

Status: **draft for review, revised 2026-10-29.** Decisions DEC-036 (the model is configuration), DEC-037 (no domain is built in;
a rule without exception) and DEC-038 (the AMS's patterns for configuration, languages and the interface). Supersedes DEC-034 (the ontology as a reviewed file) and retires "dataset" (`bi.mapping.SHAPES`). Builds
on DEC-004 (Cube is the only read path), DEC-006 (a person approves), DEC-010 (dbt), DEC-028 and DEC-029 (discovery and mappings per
layout), DEC-033 (a metric's words live with its definition).

## 0. The rule

**The BI knows no organisation, industry or language.** Nothing in its code, database schema, prompts, interface or defaults names a
domain: no students, patients, customers, terms, programs or wards; no built-in language beyond the interface's own. Everything an
organisation reports on — its subjects, things, events, groups, metrics, words, languages, what counts as personal, how periods are
cut — is configuration, created in the app and approved by a person. What makes the BI useful on day one comes from **templates**:
optional packs of configuration (a university's life cycle, a hospital's patient journey, a retailer's customer journey) that an
organisation installs, changes or ignores. A template is data, never code; removing every template leaves a working, empty BI.

The rule is checked in CI (§ 12).

## 1. What it is for

An organisation looks at its data by subject, not by system, and follows things through stages: a university follows students from
application to employment; a hospital follows patients from referral to discharge; a company follows customers from lead to renewal and
staff from hire to exit. Each stage can come from a different system. Which subjects exist, how a group is drawn and what a rate means
differ between organisations and change over time.

So the BI offers general building blocks — sources, streams, subjects, entities, events, cohorts, metrics — and generates its warehouse
and metric layer from what people define with them. The agent can propose any of it; a person approves it.

## 2. Requirements

1. **Configurable, not coded.** Every definition is created and changed in the app, without a code change or a deployment.
2. **Agnostic.** The building blocks carry no domain meaning; a template supplies it as data (§ 0).
3. **Organised by subject, not by source.** A metric names what it measures, never the system it came from.
4. **Many sources feed one event; one source feeds many events.**
5. **Shared things are defined once**: an entity used by several subjects (a location, a product, a period, a department) is one entity.
6. **Rates are defined on cohorts and on stated numerators and denominators**, drawn in the app.
7. **Periods are the organisation's**: its calendar (terms, fiscal quarters, shifts, seasons) is configured, not assumed.
8. **Languages are the organisation's**: it chooses its languages; every definition has its words in each; search and masking follow
   the scripts in use.
9. **History is kept**; which load is official for a period is a setting.
10. **Nothing about a person leaves the BI** (CLAUDE.md rule 5): previews, counts and rates are aggregates with small numbers hidden.
    What is personal is configured (which entities and attributes), on top of detection that works in any language.
11. **Drafts, approval, versions** for every definition; the generated models follow the approved version only.
12. **Every number traces back** to its definitions and sources.

## 3. The hierarchy

```
Source            a system connection: an API, a database, a folder of exports, a spreadsheet, a mailbox
 └ Stream         one table, endpoint or file series of it                         → raw.<source>_<stream>
    └ Mapping     which column of a stream's layout supplies which part of an event or entity (per layout)

Subject           a domain the organisation reports on, with a steward
 ├ Entity         a thing with an identity (a person, a product, a place, a case, a period)
 ├ Event          something that happened to entities, or a state on a date
 ├ Cohort         a group drawn from an event and followed over time
 └ Metric         a count, sum, average, rate or ratio over events, entities or cohorts

Generated         from the approved definitions, never edited by hand:
                  dbt models (staging per stream, core per entity and event, a model per cohort) and the Cube model
                  (a cube per entity, event and cohort; a view per subject; a measure per metric, with its words)

Consumers         charts and dashboards, the chat, MCP, connected systems (the AMS is one)
```

| Level | Defined where | Who approves | Stored |
|---|---|---|---|
| Organisation settings | Settings: name, languages, calendar, privacy threshold, personal-data patterns | an admin | `org_setting` |
| Source, stream | Connect data | an admin | `source`, `source_stream` |
| Mapping | Connect data's review | an admin or the subject's steward | `layout_mapping` |
| Subject | the Model page | an admin creates it and names its steward | `model_subject` |
| Entity, event | the Model page | the subject's steward | `model_entity`, `model_event` |
| Cohort | the cohort builder | the subject's steward | `model_cohort` |
| Metric | the metric builder | the subject's steward | `model_metric` |
| Template | Templates: install, preview, remove | an admin | `model_template`, then ordinary definitions |
| Generated models | the BI writes them | follow the approved version | generated dbt and Cube files |
| Chart, dashboard | Chart, dashboards | private draft, approved to publish (DEC-013) | `chart`, `dashboard` |

## 4. Organisation settings

- **Name and languages** (DEC-038, as in the AMS): English is the interface's primary language; the organization chooses **one
  secondary language** from a registry of about thirty (`bi/languages.py`), which says each language's direction and script. Every
  label, description, synonym and explanation is entered in English and in the secondary language; each person chooses their interface
  language; search matches in both. Text is normalised by Unicode rules for any script; extra folding rules for a language (letter
  variants, marks) come with a **language pack** (data: folding rules, made-up names for masking, words that suggest personal or
  identifier columns), never with code.
- **Branding**: the name in both languages and an accent colour (white text on it must reach a contrast of 4.5); the sign-in page shows
  them, the only thing readable without signing in.
- **Calendar**: the organisation's periods (month, quarter, term, season, fiscal year, shift), each with its dates, used to cut every
  metric over time and to say "a year later" in a cohort. Calendar years and months exist by default; any other period is defined.
- **Privacy**: the suppression threshold (as today) and the patterns that mark a column personal, from the language packs and the
  organisation's own.

## 5. Sources and streams

- **One source per system connection**, one stream per table, endpoint or kind of export.
- A stream's rows land in `raw.<source>_<stream>` as loaded, with `_bi_as_of`, `_bi_loaded_at` and the sync that loaded them.
- **What a stream feeds is proposed, not asked**: after the first read the rules score its columns against every event and entity
  defined, the setup agent proposes where they are unsure (DEC-035), and the person approves the target with the mapping. A stream that
  fits nothing is kept as raw data, and the agent can propose a new event for it (§ 11).
- **Who a row is about** is set per stream when it carries a personal entity: which column holds its key, or how to match it (§ 9).

## 6. Subjects, entities and events (the Model page)

- **Subjects**: created by an admin, named in the organisation's languages, each with a **steward** who approves what is defined in
  it. Entities used by several subjects live in a shared subject the organisation names.
- **Entities**: a name and words in each language, a **key**, whether it is **personal**, and attributes, each with a kind (text,
  category, date, number, identifier, boolean) and aliases that help the mapping. For a personal entity the steward marks which
  attributes may be counted by; the rest never reach Cube.
- **Events**: what one row is (the entities it carries), when (a date it happened, or the as-of date of a state), its parts (kind,
  words, aliases, needed or not), for a state which load is official per period, and when several sources feed it, which one wins.
- **Derived parts**: a part an event computes from its other parts instead of reading it from a source, chosen from small structured
  forms (never SQL): **group values** (a table of value → group, such as many program names into a few levels), **join** text parts,
  a date's **year, month or the organization's period**, **arithmetic** on number parts, **bucket** a number into ranges, and **first
  non-empty** of several parts. Generated into the staging model, so every source of the event gets the same value.
- **Editing**: each is a form saved as a draft and approved by the steward; the page shows what changes downstream before approval,
  and refuses a change that would break something approved, naming what depends on it.

## 7. The warehouse, generated

| Layer | Schema | One model per | Named | Read by |
|---|---|---|---|---|
| raw | `raw` | stream | `<source>_<stream>` | staging only |
| staging | `staging` | stream and event it feeds | `stg_<source>__<event>` | core only |
| core | `core` | entity and event | `dim_<entity>`, `fct_<event>` | cohorts, Cube |
| cohorts | `cohorts` | cohort | `<subject>__<cohort>` | Cube |

- **Every model is generated** from the approved definitions and mappings, never edited by hand. Generation is a pure function of the
  definitions (the same definitions give the same SQL), tested in CI.
- **Staging** renames each stream's columns by its approved mapping, casts them to the parts' kinds, adds the source and as-of.
- **Core** unions every staging model that feeds an event, keeps the source on each row, settles overlaps by the event's precedence,
  and applies the dbt tests the definition implies (keys unique and present, entities related).
- **Which load is official** for a state event, per period: the latest load; the load nearest a date set per period (a "count date");
  or a load a person chose. Every load is kept; the setting decides which one the metrics count.
- Cube reads `core` and `cohorts` only (CLAUDE.md rule 5).

## 8. Cohorts and metrics (the builders)

### The cohort builder

A cohort is a group drawn from an event and followed over time. The builder asks, step by step, with a live count:

1. **Who**: a personal or non-personal entity (people, accounts, products, cases).
2. **Starts with**: an event and which occurrence ("their first"), in a period of the organisation's calendar.
3. **Only**: filters on that event and the entity's countable attributes.
4. **Follow**: outcomes, each an event reached within a span from the start ("again one period later", "within six years", "within 90
   days").
5. **Name it** in each language; the builder proposes the rates (outcome / cohort size) as metrics.

The preview shows the cohort's size per starting period and each outcome's count, with small numbers hidden; it never shows rows. A
cohort is fixed once its start period's official load is in. Saving generates its model (one row per member, with the date each
outcome was reached) and its cube.

### The metric builder

A metric is a **count** (distinct on a key) of an event, entity or cohort; a **sum or average** of a numeric part; a **rate** (one
metric over another sharing their dimensions, or a cohort outcome over its size, numerator and denominator shown with it); or a
**ratio across subjects** through shared entities. Each has its words in every language, synonyms and an explanation (DEC-033), the
dimensions it can be cut by (from the entities it carries and the calendar), and optionally a name for a connected system
(`meta.metric`, read by the AMS). A rate is hidden when its denominator is under the suppression threshold. Saving generates the Cube
measure and its words; the Metrics page and connected systems read the generated model.

## 9. Identity: one thing across systems

Every entity has one key in the BI. Per stream, the entity setting says which column is that key, or how to reach it: a match on
another column through a crosswalk (`core.xwalk_<entity>`: source, source ID, BI key), built inside the warehouse. Records that cannot
be matched are counted on the stream's page, never guessed. The agent can propose a matching column; a person approves it.

## 10. The metric layer (Cube), generated

A cube per core entity, event and cohort, joined on the defined keys, personal keys never public; a view per subject with its metrics
and their dimensions, carrying `meta.subject` and the steward. The BI writes the Cube files from the approved definitions, with a
schema version that changes with each approval so Cube reloads. Hand-written cubes stay possible for what the builders cannot express,
reviewed by pull request, and must follow the rule (§ 0) like everything else.

## 11. How new data finds its place

1. A source is connected; its streams are found.
2. For each stream, the rules score its columns against every event and entity; the setup agent proposes where they are unsure, with
   reasons; a person approves the target, the mapping and whom the rows are about.
3. The BI regenerates staging and core; every metric and cohort counting that event includes it.
4. A stream that fits nothing is kept raw; the agent can propose a new event (its parts from the stream's profile), as a draft on the
   Model page.

## 12. Removing the built-in domain (and keeping it out)

The BI was built on one university's enrollment exports, and that shows. All of it moves into a **higher-education template** and an
**Arabic language pack**, or becomes neutral:

| Built in today | Becomes |
|---|---|
| `SHAPES` (enrollment, student ID, term, program, level, status, aliases incl. Arabic) in `bi/mapping.py` | the higher-education template's term enrollment event |
| `stg_enrollment`, `analytics.enrollment`, the `enrollment` cube, the `institution` view | generated from the template's definitions; the glossary and instructions become organisation settings |
| the `enrollment_headcount` metric name | a metric in the template, its AMS name kept |
| Arabic in `profile.py` (personal and ID words), `sample.py` (Arabic names, script handling), `knowledge.py` (Arabic folding) | the Arabic language pack; the code applies any pack |
| domain words in prompts (`setup_agent.py`: "a registrar can check"), the chat's example question, Connect's placeholder, `main_load.py` help | neutral wording; examples drawn from the installed templates when there are any |
| "institution" for the organisation (`AGENT_INSTITUTION_MONTHLY_TOKENS`, interface text) | "organisation"; the old variable read as an alias for one release |
| the dataset choice on Add a source | proposed after the first read |

**Kept out by CI** (`tests/test_agnostic.py`, built): a test scans `src/bi`, `web/src` and generated-model templates for a list of domain words (student, enrol,
registrar, program, term code, faculty, patient, customer, invoice, …) and fails outside `templates/` and test fixtures. The list is
broad on purpose; a word that is genuinely neutral in context is allowed by name, in the test, with a reason. Tests use made-up data
from more than one template, so the code is exercised on more than one domain.

The AMS integration (contract) stays: it is a connected system that reads metrics named for it, whatever the domain.

## 13. Delivery

| Step | Scope | Done when |
|---|---|---|
| **M0a. Out with the built-in domain (code)** — built 2026-10-29 | Language packs and the language registry as data (`src/bi/packs`); the higher-education template holds the dataset parts; installed templates per organization (Settings); neutral wording; "institution" renamed "organization"; the domain-word and language checks in CI (`tests/test_agnostic.py`) | The checks pass; without a template the BI offers nothing to feed; with it, today's behaviour |
| **M0b. Template models installed** — built 2026-10-29 | The template's dbt models and Cube files move into the template and are installed by generation | No model outside a template or generation: staging and analytics are generated per approved event (`bi.generate`, at each build); a template's Cube files are written to `cube_model.file`, which Cube reads through `cube/cube.js` and reloads on change |
| **M1. Definitions** — built 2026-10-29 (storage, approval, versions, template install, API; the Model page is M3) | The `definition` table (subjects, entities, events) with drafts, approval, versions; templates install as definitions; mapping and setup agent read them; `SHAPES` removed | Connect data's parts come from the installed template's events |
| **M2. Generated warehouse** — generation built with M0b; the rest to do | dbt models generated (done); then the core and cohorts schemas, shared dimensions per entity, the official-load setting, Cube on core | A metric from the template answers the AMS from generated models |
| **M3. The Model page** — built 2026-10-29 | Subjects, entities, events edited in the app (parts, grain, snapshot, derived parts); steward approval; what-changes preview | A person defines a new event in the UI and it is generated after approval |
| **M4. Targets, proposed** | A stream's target scored and proposed; the form's choice removed; whom the rows are about | A made-up export is proposed its event, with reasons, and approved |
| **M5. Metric builder** | Counts, sums, rates, ratios; words in each language; connected-system name; generated measures | A rate defined in the UI, charted, and asked for by the AMS |
| **M6. Cohort builder** | Live, suppressed preview; generated cohort models and rates | A cohort followed over two outcomes on made-up files of two different templates |
| **M7. Identity across sources** | Crosswalks, matching settings, unmatched counts | Two sources with different keys join one entity by a matching column |

Database sources and APIs (C2 to C5) build on M2 and M4. REST API sources (C2a) are built; drafting from OpenAPI, incremental reads
and frozen contracts are C2b.

### Order from here (2026-10-29)

1. ~~M3, the Model page, with derived parts~~ and ~~C1b, column decisions at review~~: built 2026-10-29.
2. **The organization's calendar** (§ 4): its periods, which cohorts and metrics are cut by.
3. **M5. The metric builder**, then **M6. The cohort builder** (cohort rates are metrics).
4. **M2's rest** (core and cohorts schemas, shared dimensions, the official-load setting) and **M4** (targets proposed after the first
   read, the form's dataset choice removed).
5. **M7** (identity across sources), **C2b**, and database sources (C3 to C5).

## 14. Patterns adopted from the AMS (DEC-038)

- **Configuration is data, never code.** A branch on a template, subject or organization (`if subject == ...`) is forbidden; what
  configuration cannot express is a schema change, reviewed against every template.
- **One code path, several fixtures.** Tests run the same code against at least two templates from different domains, one in a
  right-to-left language, as the AMS runs WSCUC, ABET and an Arabic framework.
- **Versioned definitions.** Drafts, approval, published versions; what is published is frozen, a change is a new version.
- **Small rules as small JSON forms**, never a rule engine (the AMS's due rules and `applies_when` tags): a cohort's span, an
  official-load rule, a matching rule.
- **The organization's own words.** A glossary maps the organization's terms to the words of each template it installs.
- **Interface text through t()**, over an English catalogue; the secondary language from a translation job, reviewed in the app.
- **One look**: the AMS's tokens, components and shell.

## 15. Decisions

- **DEC-038**: the AMS's patterns for configuration, languages (English plus one secondary) and the interface.
- **DEC-037**: the BI knows no organisation, industry or language; all domain meaning is configuration or a template (data), checked in
  CI. No exception.
- **DEC-036** (supersedes DEC-034): subjects, entities, events, cohorts and metrics are defined in the app as drafts approved by the
  subject's steward and versioned; dbt and Cube models are generated from them; streams map onto events and entities, proposed after the
  first read; rates have stated numerators and denominators and are hidden when small; things are matched across systems inside the
  warehouse by approved settings, unmatched records counted, never guessed.
