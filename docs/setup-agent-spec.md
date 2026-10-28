# Spec: The setup agent — masked samples and AI proposals in Connect data (stage B)

Status: **draft for review, 2026-10-28.** Stage B of `docs/agentic-benchmark.md`, on top of Connect data (`docs/connect-data-spec.md`,
C1 built). Implements DEC-032 (masked sample rows in setup, through providers an admin enables). Builds on DEC-015 (the agent runs in
the worker), DEC-016 (providers configured in the app), DEC-020 (budgets), DEC-028 and DEC-029 (discovery and mappings per layout).

## 1. What it is for

Connect data finds a sheet's table, profiles it and matches columns by rules. Rules guess wrong where meaning matters: a column named
"Term" that holds codes like 202620 was proposed as the term name. A person can fix it, but the platforms we benchmarked put an agent
here: Tableau's Data Pro, Databricks' Genie Code, ThoughtSpot's SpotterModel and dbt's developer agent. This spec adds the setup agent
to Connect data:

- **S1. Masked samples**: the mechanism DEC-032 allows, built once and used by every setup step.
- **S2. Mapping proposals (B1)**: the agent proposes which column is which, with a reason for each, and flags a doubtful header row.
- **S3 to S5** (outlined here, specified when they come): proposed data checks, new datasets from new data (agent step 2b), and
  connector configurations.

## 2. Requirements

1. **The rules first, the agent where they fall short.** The rules are free and instant. The agent runs only when they leave a needed
   part unmatched or a match doubtful, or when a person asks.
2. **The agent proposes; a person approves.** Nothing the agent says is applied without the review (DEC-006, DEC-029).
3. **Masked, sampled, logged** (DEC-032): at most 20 random rows per table, personal and free-text columns masked in the tool before
   anything leaves the BI, only to a provider an admin enabled for samples, every sample logged and shown.
4. **Without samples it still works.** With a provider not enabled for samples, the agent proposes from headers and profiles alone.
5. **Checked, not trusted.** A proposal is validated like a person's: the columns exist, a part gets a column that fits it, and no
   column supplies two parts. An invalid choice is dropped and said so.
6. **Within budget.** Setup calls count against the institution's and the person's token budgets (DEC-020).

## 3. S1: Masked samples

### The provider switch

`model_provider.may_see_samples` (boolean, default false), set by a BI admin on the Models page with the warning: "Masked sample rows
(at most 20 per table, personal columns replaced) will be sent to this provider during setup. Use it only with a provider the
institution has an agreement with, or a local one." Turning it on is logged.

### Drawing a sample

`bi.connect.sample.draw(pool, schema, table, where, columns, n=20)` reads at most `n` random rows of a sync's data from the draft (or raw)
table with `order by random() limit n`. It runs in the worker only.

### Masking, by column kind (from the profile)

| Kind | What the model receives | Example |
|---|---|---|
| personal: names | A made-up name in the same script (Latin or Arabic) and word count, from a fixed list | "Hanan Saleh" → "Mariam Yousif" |
| personal: email | `person{n}@example.org` | |
| personal: phone, national ID, other personal | Same length and separators, other digits and letters | "+973 3612 4455" → "+973 3807 2190" |
| personal: dates (birth dates) | A made-up date in the same format | |
| identifier | Same shape, other digits and letters, **consistent within the sample**, so repeated IDs stay repeated | "202600017" → "202694213" |
| free text | `[text, 42 characters]` | |
| category, code, date, number, boolean | As they are, except a category value below the suppression threshold in the whole table becomes `[rare value]` | "BSME", "202610", "2026-08-24" |

The masking is a pure function of the profile and the rows, in code, with property tests: no original personal value, identifier or
free text survives; shapes and repeats are kept; rare categories are hidden. A column the rules could not classify is treated as free
text (masked), not passed through.

### The log and the notice

Each sample is logged in `sample_log` (when, who, source and sync, provider and model, rows, which columns were masked how). The review
page says: "The agent saw 15 sample rows of this file, with names, emails and IDs replaced (provider: …)."

## 4. S2: Mapping proposals (B1)

### When it runs

- **Automatically**, when a sync goes to review and the rules left a needed part unmatched, or matched a part with a column whose
  profile only partly fits (for example, a term name matched to a column of codes). It needs a **setup model**: a model the admin
  allowed for building (`provider_model.allowed_build`), chosen on the Models page as the default for setup.
- **On request**: "Ask the agent" on the review page, for any sync in review.
- Never for a layout already approved, and never twice for the same layout unless asked.

### What the model is given

- The dataset's parts: names, plain labels, descriptions, what each expects (key, date, text), whether needed.
- The ontology and approved knowledge about the dataset (context spec), when they exist.
- The table: the header row found, the rows above it (titles), each column's header as written and its profile summary.
- The rules' proposal.
- A masked sample (S1), if the provider may see samples.

### What it returns

A structured result (a Pydantic model, so the output is validated, not parsed from prose):

```python
class PartChoice(BaseModel):
    part: str
    column: str | None
    confidence: Literal['high', 'medium', 'low']
    reason: str  # one line, shown to the person


class SetupProposal(BaseModel):
    parts: list[PartChoice]
    header_row: int | None  # set only when the header row found looks wrong
    header_reason: str | None
    column_notes: dict[str, str]  # column -> what it holds, in a few words (becomes draft documentation)
```

### How it is used

1. Each choice is checked (requirement 5); invalid ones are dropped and listed.
2. The proposal is stored beside the rules' one: `layout_mapping` gains `proposed_by` (rules or agent), `reasons` (part → reason and
   confidence) and the model that proposed it. The review shows the agent's choice preselected where it differs from the rules', with
   its reason and confidence; "low" choices are left for the person, not preselected.
3. A suggested header row is shown as "The agent thinks the column names are on row 6: …", with a button to read the file again.
4. Column notes become proposed knowledge entries (context spec § 7), approved separately.
5. If the call fails (no setup model, budget, an error), the review shows the rules' proposal and why the agent did not help.

### Where it runs

A worker job `setup_propose(sync_id)` (queue `agent`), one structured model call through Pydantic AI with the configured provider; no
tools, no loop. The API never calls a model (DEC-015).

## 5. Later steps (outlined)

- **S3. Proposed checks**: from profiles and samples, the agent proposes dbt tests ("term code is never empty", "one row per student and
  term") and volume or freshness expectations for a stream; a person approves them. They feed stage D, the watcher.
- **S4. New datasets from new data** (agent step 2b, TASK-013): for a stream that feeds no dataset, the agent drafts an ontology entity
  or dataset, its dbt model, tests, a Cube view and first metrics. These run in the sandbox (agent spec § 6) and are proposed for
  approval.
- **S5. Connector configurations**: for an API (C2), a `rest_api` configuration drafted from its OpenAPI document; for a database (C3,
  C4), which tables matter and which columns can serve as cursors.

## 6. Privacy and security

- Samples leave the BI only under DEC-032: setup only, admin only, enabled providers only, masked in code, logged, shown.
- The prompt carries headers, titles above the header and profiles; titles and headers are not masked (they are the file's own labels).
  A header that is itself personal (a person's name as a column header) is rare and is accepted.
- A setup model's output is data, not instructions: it can only fill the proposal model's fields.
- Tests use the scripted model and the fake OpenAI server; no test calls a real provider.

## 7. Storage

- `model_provider.may_see_samples`; a setting for the default setup model.
- `sample_log`.
- `layout_mapping`: `proposed_by`, `reasons`, `model`.
- `sync`: the agent's header suggestion and its state (asked, proposed, failed with a reason).

## 8. Delivery

| Step | Scope | Done when |
|---|---|---|
| **S1. Masked samples** | The provider switch, drawing, masking by kind, `sample_log`, the notice; property tests | A sample of the made-up export reaches a fake provider with every name, email and ID replaced, repeats kept, a rare program hidden |
| **S2. Mapping proposals** | The setup model setting, `setup_propose`, validation, the review showing choices with reasons, header suggestions, column notes as draft knowledge | On the changed export, the agent proposes the "Term" column as the term code with a reason, and the person approves |
| S3 to S5 | As outlined, each with its own spec | |

S2's quality is measured with the benchmark runner (context spec § 6), using a set of made-up exports with known mappings.

## 9. Decisions to record once approved

- Masking is by profile kind, in code, before anything leaves the BI; unclassified columns are masked as free text; rare categories
  are hidden.
- The setup agent runs where the rules fall short or a person asks, as one structured call in the worker; its proposal is validated and
  shown with reasons, never applied without review.

## 10. Open questions

1. **Automatic or on request**: run the agent automatically whenever the rules fall short (costs tokens on every unusual file), or only
   when a person clicks "Ask the agent"? The recommendation is automatic, with the institution budget as the limit.
2. **Sample size**: 20 rows (DEC-032's limit), or fewer by default (say 10)?
