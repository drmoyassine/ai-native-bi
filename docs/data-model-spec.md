# Spec: The data model — sources, subject areas, entities, events and metrics

Status: **draft for review, 2026-10-29.** Decision DEC-036 (proposed). Grows K5 (the ontology, TASK-031, `docs/context-spec.md` § 8) into
the model of the whole BI, and replaces "dataset" (`bi.mapping.SHAPES`) as what a source's data is mapped to. Builds on DEC-004 (Cube is
the only read path), DEC-005 (raw and analytics on PostgreSQL), DEC-010 (dbt), DEC-028 and DEC-029 (discovery and mappings per layout),
DEC-033 (knowledge lives in the Cube model) and DEC-034 (the ontology is a reviewed file).

## 1. What it is for

The institution looks at its data by subject, not by system. The Institutional Effectiveness office follows students through a life cycle
(application, admission, enrollment, progression, graduation, employment) as headcounts and rates; it looks at staff through another
(recruitment, hiring, rank, promotion, separation); and at courses, programs and events. Each stage can come from a different system:
applications from a CRM, enrollment from Banner, employment from an alumni survey.

Today the model is flat: a source has streams, a stream feeds a **dataset**, and the only dataset is `enrollment`, with one dbt model and
one cube. That cannot hold a life cycle that spans systems, two subjects that share programs and terms, or rates that need a cohort.
This spec sets out the hierarchy every part of the BI follows, from a source's table to a chart.

## 2. Requirements

1. **Organised by subject, not by source.** A metric names what it measures (applicants, graduation rate), never the system it came from.
2. **Many sources feed one event; one source feeds many events.** Applications can come from the CRM and from Banner; Banner supplies
   applications, enrollment and graduation.
3. **One program, one term, one org unit everywhere.** Shared dimensions are defined once and every subject joins to them, so a
   program's applicants, enrolled students, graduates and faculty line up.
4. **Rates are defined on cohorts**, with their numerator and denominator stated, so a graduation rate means one thing.
5. **History is kept.** Every load carries its as-of date; snapshots (a term's roster at census) are kept, not overwritten.
6. **Nothing student-level leaves the BI** (CLAUDE.md rule 5). Personal data stays in the warehouse; Cube exposes aggregates with small
   counts hidden; matching people across systems happens inside.
7. **The agent can build it, a person approves it.** Every level is a reviewed file or an approved record the agent can draft (DEC-006).
8. **Every number traces back** to its sources, through lineage carried on each level.

## 3. The hierarchy

```
Source            a system connection: Banner (API), the CRM, the HR system, the alumni survey, a folder of exports
 └ Stream         one table, endpoint or file series of it                        → raw.<source>_<stream>
    └ Mapping     which column of a stream's layout supplies which part of a target (per layout, approved)

Subject area      Students, Staff, Academics, Events, Finance … : a steward, entities, events, views
 ├ Entity         a thing with an identity: student, staff member, program, course, term, org unit, event
 └ Event          something that happened to an entity at a time, or a state at a date: application, admission decision,
                  term enrollment, course registration, graduation, employment outcome, hire, separation

Warehouse (dbt)   staging (one model per stream) → core (one dimension per entity, one fact per event) → marts (life cycles)

Metric layer      Cube: a cube per fact and dimension, joined on keys; a view per subject area and per lens;
                  measures are the metrics (headcounts, rates), with their words (DEC-033) and `meta.metric` for the AMS

Consumers         charts and dashboards, the chat, MCP, the AMS's evidence items
```

| Level | What it is | Where it lives | Who approves | Example |
|---|---|---|---|---|
| Source | A connection and its credentials, owner, schedule | `source` table; secrets in the secret store | an admin | "Banner (API)" |
| Stream | One table or endpoint of a source | `source_stream`; rows in `raw` | with the source | `/applications` → `raw.banner_applications` |
| Mapping | Column → part of a target, per layout | `layout_mapping` | an admin or the steward | `APPL_DATE` → `application.applied_on` |
| Subject area | A domain with a steward | `src/bi/ontology.yml` | the subject's steward, by pull request | Students (registrar), Staff (HR) |
| Entity, event | What the institution talks about, with its parts | `src/bi/ontology.yml` | the subject's steward, by pull request | `student`, `application` |
| Staging model | One stream, typed and renamed by its mapping | `transform/models/staging` | generated from the mapping | `stg_banner__applications` |
| Core model | One entity or event, from every stream that feeds it | `transform/models/core` | by pull request | `dim_program`, `fct_application` |
| Mart | Facts combined for a way of looking | `transform/models/marts` | by pull request | `student_lifecycle` |
| Cube, view, measure | The governed metrics and their words | `cube/model` | the steward, by pull request | `students.graduation_rate` |
| Chart, dashboard | A query and a visual over the metrics | the app's database | private draft, approved to publish (DEC-013) | "Yield by program" |

## 4. Sources and streams

- **One source per system connection.** Banner read through its API is one source with one set of credentials and a schedule; each
  endpoint or table it exposes is a stream. A database source (Oracle, PostgreSQL) works the same way, one stream per table or view.
  A file source has one stream per kind of export.
- A stream's rows land in `raw.<source>_<stream>` as loaded, with `_bi_as_of`, `_bi_loaded_at` and the sync that loaded them (as today).
- A stream **targets** zero or more entities or events of the ontology, through a mapping per layout (DEC-029). A stream with no target
  is kept as raw data only, until one is defined (setup agent S4).
- Which target a stream feeds is **proposed, not asked**: after the first read, the rules score the stream's columns against every
  entity and event of the ontology, and the setup agent decides where the rules are unsure (DEC-035). The person approves the target
  with the mapping. The "What its data is" choice on the Add a source form goes.

## 5. The ontology

`src/bi/ontology.yml` declares the subject areas and, in each, its entities and events with their parts. It replaces `SHAPES` and is
the file the mapping, the setup agent, the generated staging models and the chat read.

### Subject areas

A subject area is a domain the institution reports on, with a **steward** who approves changes to it: Students (registrar and
admissions), Staff (HR), Academics (the provost's office: programs, courses, outcomes), Events, Finance later. Entities shared by several
subject areas (term, program, course, org unit, date, campus) belong to **Institution**, owned by Institutional Effectiveness.

### Entities

A thing with an identity and attributes: a key, a label in both languages, whether it is personal, and its attributes.
Personal entities (student, staff member, applicant) never reach Cube as rows; their attributes reach Cube only as dimensions to count
by (level, gender, nationality), and only those the steward marks as reportable.

### Events

Something that happened to an entity at a time, or a state on a date. Each event has:

- a **grain**: what one row is (one application per person, program and term);
- its **entities** (the keys it carries: student, program, term);
- a **date** (when it happened) or an **as-of** (the date the state was true, for snapshots such as a term roster at census);
- its **parts**: the attributes a source must supply, with kinds, labels in both languages and aliases (what `SHAPES` holds today);
- **which parts are needed** for a row to count.

```yaml
subject_areas:
  institution:
    steward: institutional-effectiveness
    label: {en: Institution, ar: المؤسسة}
    entities:
      term: {key: term_code, label: {en: Term, ar: الفصل الدراسي},
             attributes: {term_label: {kind: text}, term_start: {kind: date}, term_end: {kind: date}, census_date: {kind: date}}}
      program: {key: program_code, label: {en: Program, ar: البرنامج},
                attributes: {program_name: {kind: text}, level: {kind: category}, college: {kind: category}}}
      org_unit: {key: org_unit_code, label: {en: Department, ar: القسم}}

  students:
    steward: registrar
    label: {en: Students, ar: الطلاب}
    entities:
      student: {key: student_id, personal: true, label: {en: Student, ar: طالب},
                reportable: [gender, nationality, entry_type]}
    events:
      application:
        grain: [student, program, term]
        date: applied_on
        parts: {student_id: {kind: identifier, needed: true}, program_code: {needed: true}, term_code: {needed: true},
                applied_on: {kind: date, needed: true}, application_type: {kind: category, aliases: [admit type, نوع القبول]}}
      admission_decision:
        grain: [student, program, term]
        date: decided_on
        parts: {decision: {kind: category, values: [admitted, rejected, waitlisted, withdrawn]}, …}
      term_enrollment:
        grain: [student, term]
        as_of: census_date
        parts: {program_code: {needed: true}, level: {}, status: {}, load: {kind: category, values: [full_time, part_time]}}
      graduation:
        grain: [student, program]
        date: graduated_on
      employment_outcome:
        grain: [student, survey]
        date: surveyed_on
        parts: {status: {values: [employed, further_study, seeking, not_seeking]}, months_after_graduation: {kind: number}}
```

## 6. The warehouse: layers and names

| Layer | Schema | One model per | Named | Holds personal data | Read by |
|---|---|---|---|---|---|
| raw | `raw` | stream | `<source>_<stream>` | yes, as loaded | staging only |
| staging | `staging` | stream × target | `stg_<source>__<event>` | yes | core only |
| core | `core` | entity or event | `dim_<entity>`, `fct_<event>` | yes (keys) | marts, Cube |
| marts | `marts` | way of looking | `<subject>_<lens>` | keys only | Cube |

- **Staging is generated from the approved mapping**, not hand-written: rename the columns, cast to the part's kind, add the source and
  as-of. The `dataset_rows` macro grows into this. A new stream that maps onto a known event needs no hand-written SQL.
- **Core unions every staging model that feeds an event**, keeps the source on each row, and settles overlaps by the precedence the
  ontology declares for that event (for example, Banner over the CRM for admission decisions). Keys are checked (unique, not null,
  related) by dbt tests the ontology implies.
- **Snapshots are kept**: a snapshot event (term enrollment) keeps one set of rows per as-of, and core marks the official one (the
  census snapshot); "latest" is a filter, not an overwrite.
- **Marts combine facts for a way of looking**, for example `students_lifecycle` (§ 7).
- Cube reads `core` and `marts` only; `raw` and `staging` are never read by any consumer (CLAUDE.md rule 5).
- Today's `analytics.enrollment` becomes `core.fct_term_enrollment`; `stg_enrollment` becomes the generated staging models.

## 7. The student life cycle

### Stages

| Stage | Event | Typical source | Headcount metric | Rate metric (numerator / denominator) |
|---|---|---|---|---|
| Application | `application` | CRM, Banner | applicants | — |
| Admission | `admission_decision` | Banner | admits | admit rate = admits / applicants (same term and program) |
| Enrollment | `term_enrollment` | Banner | enrolled (new entrants) | yield = new entrants / admits |
| Progression | `term_enrollment` | Banner | retained | retention rate = cohort still enrolled at the next fall census / cohort |
| Graduation | `graduation` | Banner | graduates (completions) | graduation rate = cohort graduated within N years / cohort |
| Employment | `employment_outcome` | alumni survey | employed | employment rate = employed or further study / graduates who responded |

Headcounts are counted from the facts by term and program; rates are counted on cohorts.

### Cohorts

A **cohort** is the students who first enrolled in a term, at a level, by entry type (first-time, transfer). It is fixed at the entry
term's census and never changes afterwards. Retention, graduation and time to degree are measured on cohorts, so a rate's numerator and
denominator are the same students. The institution decides the cohort rules (open question 1).

### The mart

`marts.students_lifecycle`: one row per student and cohort, with the program and level at entry, the date of each stage reached
(applied, admitted, enrolled), whether retained into the second year, graduation date and time to degree, and the latest employment
outcome. It holds a key, never a name. Cube counts it: a cohort's size, how many reached each stage, the rates.

Rates with a small denominator are hidden like small counts (DEC-017): a rate is shown only when its denominator reaches the
suppression threshold.

## 8. Staff, academics and events

- **Staff**: `staff_member` (personal); events `requisition`, `hire`, `staff_snapshot` (rank, FTE, contract, org unit, at a date),
  `promotion`, `separation`. Metrics: faculty headcount by rank, FTE, hires, turnover rate (separations / average headcount).
- **Academics**: `course`, `section`; events `course_registration` (student, section, term), `grade`, `outcome_assessment`. Metrics:
  sections, enrollments per section, pass rates, outcome attainment.
- **Events**: `event`; events `event_registration`, `attendance`. Metrics: events held, registrations, attendance rate.
- **Across subjects**: some indicators combine subject areas, such as the student–faculty ratio (FTE students / FTE faculty). They are
  defined once, in an `institution` view of Cube that joins the subjects through the shared dimensions (term, program, org unit).

## 9. Identity: one person across systems

- Every personal entity has one **key in the BI**, the institution's ID (Banner's ID for students and staff) where a source carries it.
- A source with its own IDs (a CRM's applicant ID, a survey's respondent ID) is linked through a **crosswalk** in core
  (`core.xwalk_<entity>`: source, source ID, BI key), built by declared rules: an exact match on the institution's ID first, then on a
  field the steward allows (a university email). Matching happens inside the warehouse only.
- Records that cannot be matched are counted and shown on the source's page, never guessed. An agent may propose a matching rule; a
  person approves it.

## 10. The metric layer (Cube)

- One cube per core dimension and fact and per mart, joined on the ontology's keys; personal keys are never public.
- **Views by subject area** ("Students", "Staff", "Academics") and **by lens** ("Student life cycle", "Institution indicators") are what
  consumers see; each carries `meta.subject_area` and its steward.
- Measures are the metrics, named `<subject>_<what>` when exposed to the AMS (`meta.metric: students_graduation_rate`), with their words
  in both languages (DEC-033). A rate is a measure built from its numerator and denominator measures, which are exposed too.
- The AMS's dataset list (contract § 7) maps onto these: enrollment by level → `students.enrolled` by level; retention →
  `students.retention_rate`; graduation → `students.graduation_rate`; completions → `students.graduates`; faculty by rank →
  `staff.faculty_headcount` by rank; student–faculty ratio → `institution.student_faculty_ratio`; outcome attainment →
  `academics.outcome_attainment`; financial indicators → Finance, later.

## 11. How new data finds its place

1. A source is connected; its streams are found (C1 files today; C2 to C5 next).
2. For each stream, the rules score its columns against every entity and event; the setup agent proposes where they are unsure, with
   reasons; a person approves the target and the mapping.
3. The staging model is generated; core picks it up as another feed of the event; the metrics that count that event include it.
4. A stream whose data matches nothing is kept raw. The setup agent may propose a new entity or event (S4): an ontology change, its
   staging and core models, a cube and first metrics, as a pull request the subject's steward approves.

## 12. What changes from today

| Today | After |
|---|---|
| `SHAPES` in `bi/mapping.py`, one dataset | `src/bi/ontology.yml`: subject areas, entities, events |
| `source_stream.dataset` | the stream's targets (events or entities), proposed and approved |
| `layout_mapping (layout, dataset)` | `layout_mapping (layout, target)`: same table, the target is an ontology name |
| "What its data is" on Add a source | proposed after the first read, approved with the mapping |
| `stg_enrollment`, `analytics.enrollment` | generated `stg_<source>__term_enrollment`, `core.fct_term_enrollment` |
| one `enrollment` cube | cubes per fact and dimension; views per subject area and lens |
| metric names like `enrollment_headcount` | `students_enrolled`; the old name kept as an alias while the AMS uses it |

A migration renames the dataset `enrollment` to the event `term_enrollment` in stored mappings and streams; Cube keeps answering
`enrollment_headcount` until the AMS's items are moved to the new name.

## 13. Delivery

| Step | Scope | Done when |
|---|---|---|
| **M1. The ontology file** (K5) | `src/bi/ontology.yml` with Institution and Students; `mapping` and the setup agent read it; `SHAPES` removed | Connect data's parts and labels come from the ontology; the enrollment tests pass unchanged |
| **M2. Warehouse layers** | `staging`, `core`, `marts` schemas; staging generated from mappings; `core.fct_term_enrollment`, `dim_term`, `dim_program`; Cube reads core | The enrollment metric answers the AMS from the new layers |
| **M3. Targets, proposed** | A stream's target scored by the rules and proposed by the agent; the form's dataset choice removed | A made-up admissions export is proposed as `admission_decision` with reasons, and approved |
| **M4. The student life cycle** | `application`, `admission_decision`, `graduation`, cohorts, `students_lifecycle`, the rates, the "Student life cycle" view | Admit rate, yield, retention and graduation rate on made-up test files (DEC-011), small denominators hidden |
| **M5. Identity across sources** | Crosswalks, matching rules, unmatched counts on the source's page | A CRM export with its own IDs joins the life cycle by email, with unmatched records counted |
| **M6. Staff** | Staff subject area, its events and view; `institution.student_faculty_ratio` | Faculty by rank and the student–faculty ratio on made-up files |

Banner through its API (C2) builds on M2 and M3: one source, a stream per endpoint, each proposed a target.

## 14. Decisions (recorded as DEC-036)

- The BI is organised by subject area, entity and event, declared in `src/bi/ontology.yml`; sources and streams map onto them, never
  the other way round. "Dataset" is retired as a mapping target.
- The warehouse has four layers (raw, staging, core, marts); staging is generated from approved mappings; core has one model per entity
  and event, shared across subjects; Cube reads core and marts only.
- Rates are defined on cohorts with stated numerators and denominators, and hidden when the denominator is small.
- People are matched across systems inside the warehouse, by declared rules a person approves; unmatched records are counted, never guessed.

## 15. Open questions

1. **Cohort rules**: first-time and transfer students separately? Full-time only, or all? Graduation within 100 %, 150 % or 200 % of the
   normal time? (Accreditor or ministry definitions may decide.)
2. **Census**: is there a census date per term, and which snapshot is official when there is none?
3. **Applicants' IDs**: do applicants get a Banner ID at application, or only at admission? (Decides how much the CRM needs a crosswalk.)
4. **Employment**: which survey, when, and is it per graduate or aggregated already?
5. **After students**: which subject area next — Staff, Academics or Events?
6. **History**: keep every snapshot, or only the census snapshot per term plus the latest?
