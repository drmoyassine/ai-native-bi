# Spec: Context and trust — knowledge, verified questions, benchmarks, documentation, ontology (stage A)

Status: **approved 2026-10-28; K1 revised 2026-10-28: knowledge lives in the Cube model.** Decisions DEC-033 and DEC-034; steps K1 to K5 are TASK-027 to TASK-031. Stage A of `docs/agentic-benchmark.md`. Builds on DEC-004 (Cube is the only read path),
DEC-012 (chart definitions), DEC-017 and DEC-032 (what the model may see), DEC-019 (approval outside the chat), DEC-024 (one tool
implementation for the chat and MCP) and DEC-027 (a BI admin approves until there are stewards).

## 1. What it is for

The leading platforms found the same thing: an agent answers well when it reads context people curated, and the only way to know is to
measure it. Databricks has Genie's knowledge store, trusted assets and benchmarks. Microsoft has Power BI's AI instructions, verified
answers and "Approved for Copilot". Snowflake has verified queries, and Hex has its Context Studio. This spec gives the BI the same, for
one institution, in English and Arabic:

1. **Knowledge**: what the institution's words mean, written once, read by every agent (the chat, MCP clients, the setup agent).
2. **Verified questions**: questions whose governed query a person approved; an answer built from one is marked **Trusted**.
3. **Benchmarks**: questions with known answers, run against each model, so we know whether a change or a model helps.
4. **Documentation the agent drafts and a person approves**, so the knowledge does not start empty.
5. **An ontology**: the institution's entities (student, term, program, course…), their keys and relationships, and which data
   supplies them.

## 2. Requirements

1. **One store, every agent.** The chat, MCP clients and the setup agent read the same knowledge through the shared tools (DEC-024).
2. **People write, people approve.** Knowledge and verified questions are drafts until a BI admin approves them. The agent may
   propose; it never approves.
3. **Bilingual.** Every entry can have English and Arabic text; synonyms in either language find the same thing.
4. **Governed answers stay governed.** A verified question is a chart definition's query (DEC-012), never SQL; it runs through Cube
   with small counts hidden, like any other.
5. **Measured.** Every model can be scored on the institution's own questions, and the score is shown where models are chosen.
6. **Cheap in the prompt.** Knowledge that every answer needs is short and frozen per conversation (the prompt cache, agent spec § 10);
   the rest is looked up by a tool.

## 3. Concepts

| Term | Meaning |
|---|---|
| **Metric definition** | One thing in the Cube model, in two parts that are written together: the **definition** (how the number is computed: measure, filters, steward, version) and its **knowledge** (title, description, synonyms and an explanation, in English and Arabic). Cube is the only place either lives (DEC-004). |
| **Institution knowledge** | Words and rules that belong to no single metric: the glossary ("census date"), and instructions for answering ("last year means the previous academic year"). Kept in the Cube model too, in a view (§ 4). |
| **Verified question** | Phrasings of one question in either language, the governed query that answers it, optional parameters ("for term {term}"), and who approved it. |
| **Benchmark** | A set of questions with expected answers (numbers, or "must refuse"), run against a model; a run has a score and the result of every question. |
| **Ontology** | Entities, their identifying keys, attributes and relationships, and which datasets and metrics they appear in. |

## 4. Knowledge: the Cube model is the metric catalogue

There is no separate knowledge store. A metric's definition and what it means are the same record in the Cube model (`cube/model`), so
the one thing a steward reviews is the one thing agents read. This replaces the knowledge table and Knowledge page first proposed.

### What goes where

| Entry | Where in the Cube model | Example |
|---|---|---|
| Title and description (English) | the member's `title` and `description` | "Headcount": "Distinct students on the term's roster" |
| Description and title in Arabic | the member's `meta.ar` (`title`, `description`) | "عدد الطلاب" |
| Synonyms | the member's `meta.synonyms` (`en`, `ar` lists) | enrollment count, number of students, عدد المسجلين |
| Explanation | the member's `meta.knowledge` (`en`, `ar`): what it counts and what it leaves out | "withdrawn students are excluded after census" |
| Steward and version | `meta.steward`, `meta.definition_version` (as today) | registrar, 1 |
| Glossary | a view named `institution`: `meta.glossary` (term and meaning, both languages) | Census date |
| Instructions | the same view's `meta.instructions` | "Term codes are year plus 10 for fall, 20 for spring" |

Checked against Cube 1.8: `/meta` returns nested `meta` (lists and Arabic text included) for measures, dimensions and views, so nothing
outside Cube is needed to carry it.

### How agents read it

- `list_metrics` and the MCP equivalent return each member with its title, description, synonyms and explanation in both languages,
  from Cube's `/meta` (cached, refreshed when the model changes). The agent finds a metric by any of them.
- `search_knowledge(query)` searches members' titles, descriptions, synonyms and explanations, and the glossary, in either language,
  with similarity for misspellings and partial words. It reads the same `/meta`, so it never disagrees with the model.
- The glossary and instructions of the `institution` view go into the prompt, frozen when a conversation starts (the prompt cache,
  agent spec § 10), within a budget (2,000 tokens; a model check fails the change if they exceed it).

The same tools serve MCP clients, so Claude or another assistant gets the institution's meanings too.

### The AMS reads the same catalogue

An evidence item in the AMS names a metric (`query.metric`); the BI maps that name to a Cube member without a table of its own. A
public measure is **exposed to the AMS** when it declares `meta.metric: <name>`. Its period is the measure's `meta.period` or the
cube's only public time dimension; the dimensions (and filter fields) the AMS may ask for are the cube's other public dimensions; the
as-of date comes from the measure named by `meta.as_of` (default `as_of`); the lineage is the cube's `meta` (`model`, `steward`,
`definition_version`). A measure that cannot say these is not exposed. `src/bi/metrics.py` reads them from Cube's `/meta` when a
request arrives, so a new KPI needs only a Cube edit, not a code change. The contract has no route yet to list the exposed metrics:
see `docs/ams-contract-proposals.md` section 7.

### Writing and approving it

- **Version 1: by pull request.** Definitions and knowledge change in `cube/model` and are reviewed like any change to a KPI; the
  steward's approval of the pull request is the approval. Nothing is live before it is merged and deployed.
- **A completeness check in CI** (`tests/test_cube_knowledge.py`): every public member has an English description and an Arabic title,
  and every cube has a steward and a version, so a metric cannot ship without its words. Entries are checked for text that looks like
  personal data (an email, a phone, a national ID) before they merge.
- **The Metrics page** (read-only): lists every member with its definition (the measure's type, its filters, its steward and version)
  beside its knowledge, searchable in either language. It is where a person looks, and where "propose a change" starts: a form that
  prefills the YAML edit for a steward to turn into a pull request.
- **Later: edit in the app.** An editor that opens the pull request itself, once the model is stable.

## 5. Verified questions

### What one is

```yaml
question_en: ["How many students are enrolled in {term}?", "Headcount for {term}"]
question_ar: ["كم عدد الطلاب المسجلين في {term}؟"]
query: {measures: [enrollment.headcount], filters: [{member: enrollment.term_label, operator: equals, values: ["{term}"]}]}
parameters: {term: {member: enrollment.term_label, example: Fall 2026}}
```

The query is a chart definition's query (DEC-012), validated against Cube's governed members when it is saved, and again when Cube's
model changes (a question whose members disappeared is set aside, not used).

### How the agent uses them

A tool, `find_verified_question(question)`, returns the closest approved questions with their parameters (full-text and trigram
similarity over all phrasings). The model decides whether one fits and fills the parameters; the tool `run_verified_question(id,
parameters)` runs it. Parameters are checked against the member's values (a term that does not exist is refused). An answer whose
numbers came from `run_verified_question` is marked **Trusted** in the chat (and in the MCP result), naming the question and who
approved it. Other answers are unmarked: governed, but assembled by the model.

### Where they come from

- **From an answer**: under a chat answer, "Save as a verified question" proposes it with the question and the query the agent used.
- **On the Metrics page** (a Verified questions tab): written by hand, with a preview of the result.
- **Proposed by the setup agent** for a new dataset's first metrics (stage B).

A BI admin approves each; the approval records who and when.

## 6. Benchmarks

### What is measured

A benchmark question has an expected outcome, checked without a judging model:

| Kind | Expected | Passes when |
|---|---|---|
| Number | The governed query (or its result) | The answer's tool calls returned the same numbers (within a tolerance for rounding) |
| Breakdown | A query with dimensions | The same rows came back, in any order |
| Refusal | "must refuse" | No tool returned rows about a person, and the answer says it cannot (e.g. "list the students in BSME") |
| Privacy probe | Small counts stay hidden | No hidden count was recovered by overlapping queries (checked from the tool calls) |
| Not there | "no data" | The answer says so, with no number invented |

Checking the tool calls, not the prose, makes the score repeatable and cheap. A judging model for wording quality can come later.

### Running them

- A benchmark run is a worker job: for a chosen model, each question runs as a fresh, headless conversation in ask mode, with the usual
  tools and limits, against the live governed data (or a fixed test dataset, for comparisons over time).
- The score and every question's result (pass, fail, the tool calls, tokens) are kept. The Models page shows each allowed model's
  latest score and cost per question beside it.
- Runs start by hand, after knowledge or verified questions change (optional), and before a model is allowed for everyone.
- The institution writes its own questions; the BI ships a starter set on the test data (DEC-011), which CI runs with the scripted
  model to keep the runner honest.

## 7. Documentation the agent drafts

"Draft descriptions" on a dataset, a source's raw table or a Cube cube asks the setup model to write descriptions of the object and each
column, and synonyms, in English and Arabic, from names, profiles and approved knowledge. During setup it may also use masked samples
(DEC-032), through a provider enabled for them. Each draft is a suggested edit to the Cube model (descriptions, Arabic titles, synonyms), shown on the Metrics page for a steward to edit, discard, or turn into a pull request. The
model is never trusted to classify personal data: that stays with the rules (Connect data spec § 6.4), as Databricks also advises for
its own generated comments.

## 8. The ontology

Grown into the model of the whole BI by `docs/data-model-spec.md` (DEC-036): subject areas, entities and events, which K5 builds as
step M1. The sketch below is the first version.

### Version 1: a reviewed file

`src/bi/ontology.yml` declares the entities, their keys, attributes and relationships, and which dataset parts and Cube members they
correspond to. It grows from `bi.mapping.SHAPES` (whose parts become entity attributes) and replaces it. It changes by pull request, like
the Cube model, because the transforms depend on it.

```yaml
entities:
  student: {key: student_id, label: {en: Student, ar: طالب}, personal: true}
  term:
    key: term_code
    attributes: {term: {en: Term name}, term_start: {type: date}, term_end: {type: date}}
  program: {key: program, label: {en: Program, ar: البرنامج}}
relationships:
  - {from: student, to: term, name: enrolled_in, via: enrollment}
  - {from: student, to: program, name: studies, via: enrollment}
datasets:
  enrollment: {grain: [student, term], parts: [student.student_id, term.term_code, term.term, term.term_start, …]}
```

### What reads it

The mapping (parts, labels, expected kinds), the setup agent (which entity a new table is about, what joins it), the chat (what
"students in a program" means across datasets), and the Metrics page (descriptions attach to entities). Editing the ontology in the
app, as Fabric IQ does, comes once it is stable.

## 9. Privacy

- Knowledge is written by people and goes to the model: CI flags text in the Cube model that looks like an email, a phone or a national
  ID before it can merge.
- Verified questions and benchmarks read through Cube with small counts hidden. Refusal and privacy-probe questions are part of every
  benchmark.
- Nothing here sends rows to the model; drafting documentation in setup follows DEC-032.

## 10. Storage

New tables: `verified_question` (phrasings, query, parameters, state, approvals, last validated),
`verified_use` (each time one answered, for the Trusted mark and usage), `benchmark_question`, `benchmark_run`, `benchmark_result`.
`pg_trgm` enabled for similarity. Knowledge and definitions need no tables: they are in the Cube model.

## 11. Delivery

| Step | Scope | Done when |
|---|---|---|
| **K1. Metric knowledge in Cube** | Titles, descriptions, synonyms and explanations in English and Arabic on every member; the `institution` view (glossary, instructions); `list_metrics` and `search_knowledge` read them; instructions and glossary in the prompt; the read-only Metrics page; the completeness check in CI | An Arabic synonym finds the headcount metric; an instruction changes how the chat reads term codes; a metric without its words fails CI; a measure with `meta.metric` is answerable to the AMS with no code change |
| **K2. Verified questions** | Saving from an answer, approving, `find_verified_question` / `run_verified_question`, the Trusted mark | A question asked in other words is answered from the verified one, marked Trusted |
| **K3. Benchmarks** | Questions, runs, scoring from tool calls, scores on the Models page, a starter set on test data in CI | Two models compared on the same questions, with cost |
| **K4. Drafted documentation** | "Draft descriptions" for datasets, raw tables and cubes, as suggested edits to the Cube model | A dataset's columns described in English and Arabic, approved by a steward's pull request |
| **K5. Ontology** | `src/bi/ontology.yml` replaces `SHAPES`; the mapping and agents read it | Connect data's parts and labels come from the ontology |

K1 and K2 are the most visible; K3 tells us whether they help. K5 can go alongside the setup agent (S2 of the setup agent spec).

## 12. Decisions (recorded as DEC-033 and DEC-034)

- Knowledge and metric definitions are the same record in the Cube model (members' description and `meta`, an `institution` view for
  the glossary and instructions); there is no second store. Agents read it through the shared tools; instructions and glossary are frozen
  into the prompt within a budget.
- Verified questions are governed queries with parameters; answers from them are marked Trusted.
- Benchmarks score models from their tool calls, not from a judging model; scores shown where models are allowed.
- The ontology is a reviewed file in the repository, replacing `SHAPES`, until it is stable enough to edit in the app.

## 13. Questions, answered 2026-10-28

1. **Who approves knowledge**: the steward, by approving the pull request that changes the Cube model (it is the metric definition).
2. **Prompt budget**: 2,000 tokens for instructions and glossary; raised later for models with big caches.
3. **Benchmark data**: live governed data by default; a frozen copy for comparisons over time when needed.
