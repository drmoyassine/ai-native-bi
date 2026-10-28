# Spec: Connect data — sources, discovery and mapping (ROADMAP-009, ROADMAP-003)

Status: **approved 2026-10-28.** Decisions DEC-027 to DEC-031; steps C1 to C5 are TASK-022 to TASK-026. Read with dlt 1.31 and its docs of 2026-10-27 (§ 4). Replaces the Uploads page with a Connect data page, where a file upload is one type of source.
Builds on DEC-003 (dlt for integrations), DEC-005 (raw and analytics on PostgreSQL), DEC-006 (a person approves what the agent builds),
DEC-010 (dbt), DEC-017 (the model sees schemas, profiles and suppressed aggregates, never rows), DEC-020 (secrets) and DEC-026 (columns
are discovered and mapped, not fixed). Agent steps 2b (TASK-013) and 2c (TASK-014) build on what this spec defines.

## 1. What it is for

The institution's data lives in many places: exports someone downloads (xlsx, xlsb, csv), the student system (Banner), other databases,
shared folders, cloud spreadsheets and the APIs of other systems. Connect data is the one place where a person, or the agent on their
behalf, connects any of them, sees what is in it, chooses what to bring in, says what it means, and approves it.

The first real export showed what goes wrong without this. The headers were not in the first row, the column names were not the ones the
transform expected, and the page showed a dbt error instead of a question a person could answer.

## 2. Requirements

1. **One flow for every kind of source.** Choose a type, connect, discover, choose, map, approve. A file is one type among several.
2. **Discovery, not configuration.** The BI finds the tables, sheets, header rows, columns, types, keys and sensitive columns itself.
   A person confirms or corrects what it found and never types a schema.
3. **Readable by the person who knows the data.** Headers are shown as the source writes them, and the parts of a dataset have plain
   names and a one-line description. Each column comes with a short description of what it holds, never its values.
4. **Nothing student-level leaves the BI, and the model sees no rows** (CLAUDE.md rule 5, DEC-017). Discovery produces names, types and
   profiles. The person on the page sees the same profiles, not rows.
5. **Read-only and governed.** A connection is checked to be read-only. Credentials live in the secret store. A source is not live
   until a person approves it, and a change in its layout comes back for review.
6. **The agent uses the same objects.** "Connect Banner" in the chat creates the same source and goes through the same steps, so the
   chat and the page are two entrances to one flow.

## 3. Concepts

| Term | Meaning |
|---|---|
| **Source** | One connection: a type, settings, credentials (by reference to the secret store), an owner and a state (draft, live, paused). |
| **Stream** | One thing a source contains: a table or view, a sheet, a file in a folder, an API endpoint. |
| **Catalog** | What discovery found in a source: its streams, each with its columns, declared types, keys and size. |
| **Layout** | The set of columns a stream has, after normalisation. A new export with the same columns has the same layout. |
| **Profile** | Facts about a column: kind, null rate, distinct count, value shapes, ranges, frequent categories at or above the suppression threshold. |
| **Dataset** | A governed shape the metric layer reads (`enrollment`), with its parts (`student_id`, `term_code`…), as in `bi.mapping`. |
| **Mapping** | Which column of a layout supplies which part of a dataset; proposed, then approved. |
| **Sync** | One run of reading a stream into `raw`, with its outcome. A file upload is a sync of a file source. |

## 4. What dlt already gives us

dlt (Apache 2.0, already in the stack) covers most of the connecting, and some of the discovering. We read its documentation in full:
sources, schema, naming, contracts, incremental loading, data quality, dataset access, the dltHub pages and the release notes up
to 1.31. Its destination and deployment pages do not bear on this spec.

### Sources

| Kind | dlt source | What it does | Notes for us |
|---|---|---|---|
| **Databases** | `sql_database` / `sql_table` (core, in the library) | Any SQLAlchemy dialect: PostgreSQL, SQL Server, Oracle, MySQL/MariaDB, DB2, SQLite, Snowflake… Reflects tables and views, columns, types (`reflection_level`: `minimal`, `full` (default), `full_with_precision`), nullability and keys. Chooses tables (`table_names`) and columns (`included_columns`, `table_adapter_callback`), filters rows (`query_adapter_callback`), loads incrementally on a cursor column, in chunks, with backends `sqlalchemy`, `pyarrow`, `pandas`, `connectorx`. | Needs the `sql_database` extra and a driver: `oracledb` (thin mode, tested by dlt), `pyodbc` or `pymssql`, `psycopg`. On Oracle, SQLAlchemy lower-cases identifiers and `NUMBER` loads as decimal; time-zoned timestamps load correctly only from dlt **1.32** (we run 1.31). |
| **Files in storage** | `filesystem` + readers (core) | Lists files in S3, Google Cloud Storage, **Google Drive**, Azure Blob, **SFTP**, a local or network path, or over HTTP, without reading them (`FileItem`: name, path, size, modified time). Readers for CSV (pandas or DuckDB), Parquet and JSONL. New files only, by modified time. | **No Excel reader**: the docs show writing one as a transformer. Ours is the calamine reader with header detection (§ 5.2). **No SharePoint or OneDrive**: neither the docs nor the verified sources have them; they would need Microsoft Graph through `rest_api` or an fsspec plugin. |
| **Google Sheets** | `google_sheets` (verified source, copied in with `dlt init`) | Reads named ranges, whole sheets or given ranges with a service account or OAuth (read-only scope), in two API calls; writes a `spreadsheet_info` table of what it read. | It expects the header in **the first row of each range**. A header that is not a unique string makes it fall back to generated names. Named ranges are its answer to title rows. Types come from the first data row, and it no longer detects dates. |
| **APIs** | `rest_api` (core) | Declarative: base URL, auth (bearer, API key, basic, OAuth2 client credentials), paginators, data selectors, parent and child endpoints, incremental parameters. `dlt-init-openapi` turns an OpenAPI document into such a configuration, guessing pagination, primary keys, relationships and auth. | A configuration is **data, not code**: the agent can propose one, and a person can review it, with no sandboxed code to run. |
| **Email** | `inbox` (verified) | Reads a mailbox over IMAP and saves attachments. | Fits the way exports often arrive: the registrar emails a monthly file. |
| **Change capture** | `pg_replication` (verified); SQL Server change tracking | Inserts, updates and deletes from PostgreSQL logical replication. | SQL Server change tracking is **dltHub (paid)**; plain reading of SQL Server is free. |

### Schema discovery

- **`source.discover_schema()`** gives a source's tables and columns with types, without loading anything. For `sql_database`, that comes
  from reflection, so it reads metadata and no rows. `resource.compute_table_schema()` does the same for one table. **This is our `discover`
  for databases.**
- For data without declared types (files, sheets, APIs), dlt infers types from the values as it normalises them. It coerces where it can
  and puts values that do not fit in a variant column (`col__v_text`). Its only built-in detector is ISO timestamps.
- **Naming**: dlt turns headers into identifiers (`snake_case` by default). Non-ASCII characters become `_` (an Arabic header ends up
  as `x`), and `+`, `*`, `@`, `-` and `|` are replaced. `sql_ci_v1`, `duck_case` and `direct` keep more of the name. We keep the header
  as written beside the identifier (§ 8), whichever convention we choose.

### Control after discovery

- **Schema contracts** (`schema_contract`: `evolve`, `freeze`, `discard_row`, `discard_value`, for `tables`, `columns` and
  `data_type`). An approved stream runs with columns and types **frozen**. A new export with another layout then stops before
  anything loads, and comes back for review (§ 6.6). A draft runs with `evolve`.
- **Schema change alerts**: each run's `load_info` lists new tables and columns (`schema_update`), and every row carries
  `_dlt_load_id`, which ties it to its run in `_dlt_loads`. Together these give a sync its lineage.
- **Leaving columns out at the source**: `table_adapter_callback` / `included_columns` mean a personal column that no dataset needs
  is **never read**. `add_map` can pseudonymise a value (a salted hash from the secret store) before it lands.
- **Credentials**: dlt reads secrets from its providers (TOML, environment, Google, AWS, Airflow vaults). We pass credentials from our
  own secret table straight to the source objects instead (`ConnectionStringCredentials`, a SQLAlchemy `Engine`, `GcpServiceAccountCredentials`).

### Sources dlt lacks: written as dlt sources

Every source reaches `raw` through dlt. A type dlt does not have becomes a dlt source, resource or transformer of our own, never a
loader beside dlt. A dlt resource is a Python function that yields rows, which is code we would write anyway. Writing it this way
gives every source the same things for free:

- one loading path: the same naming, types, tables per stream and metadata columns in `raw`, whatever the source;
- frozen schema contracts, so a layout change becomes a review (§ 6.6);
- lineage: `_dlt_load_id` on every row and a list of schema changes for each run;
- incremental loading, with its state kept in the BI's database;
- `discover_schema()` for a source that declares its columns, so the connector interface (§ 5) is the same for every type;
- write dispositions (append, replace, merge) and primary keys as settings.

| Missing | Filled by |
|---|---|
| Excel files (uploads, folders, mail) | Our calamine reader with header detection (§ 6.2), as a dlt transformer after `filesystem`, `inbox` or an upload |
| SharePoint / OneDrive | Microsoft Graph through a `rest_api` configuration (list, download), then the same reader; or an fsspec plugin for SharePoint, which `filesystem` would take directly, if a maintained one exists |
| An API with no OpenAPI document | A `rest_api` configuration, written by a person or proposed by the agent: data to review, not code to sandbox |
| A system with neither an API nor a database | A small `@dlt.source` in `src/bi/connectors/`, with tests on made-up data (DEC-011) |

What stays outside dlt: header detection, profiles and the classification of columns. These run before or after a load and read what
was discovered or loaded. Documents to be parsed (PDF, Word) stay outside too; once parsed into a table they can go through dlt. So does
the AMS contract, which is a request and a supply, not ingestion.

The cost is dlt's own upgrades: releases 1.25 to 1.31 each changed some default behaviour. dlt is pinned and upgraded on purpose, with
every connector's tests run first.

### What we do not take

- **dltHub** (the paid product): data quality metrics and checks, transformations, the AI harness, MS SQL change tracking and the
  managed runtime. Its licence allows use **only with dltHub's platform**, so none of it can run inside the BI. Profiles (§ 6.3) and
  checks stay ours, in PostgreSQL and dbt.
- dlt's `dlt pipeline … show` dashboard and MCP, which moved to `dlt[hub]` in 1.27.

## 5. The connector interface

Every type implements the same four operations, named as in the Airbyte protocol (`spec`, `check`, `discover`, `read`). Each operation
is a thin layer over the dlt source for that type.

```python
class Connector(Protocol):
    type: str  # 'file', 'sql:postgres', 'sql:mssql', 'sql:oracle', 'gsheets', 'folder', 'rest_api', 'inbox'

    # the settings a person fills in; secret fields are marked as such
    def spec(self) -> type[BaseModel]: ...

    # can we connect, and only read? the reason when not
    def check(self, settings, secrets) -> Check: ...

    # the streams and their columns, from metadata only
    def discover(self, settings, secrets) -> Catalog: ...

    # the dlt source or resource for one stream, with our hints
    def read(self, settings, secrets, stream) -> DltSource: ...
```

| Type | `check` | `discover` | `read` |
|---|---|---|---|
| File (upload) | the file opens | sheets and their header rows (§ 6.2) | our calamine reader as a dlt resource |
| Database | connect; session read-only; no write grants | `sql_database(…, reflection_level="full_with_precision").discover_schema()` and the catalog's row estimates | `sql_table` per chosen table, chosen columns only, incremental if a cursor is set |
| Folder (S3, Drive, SFTP, path) | list the folder | `filesystem` listing, then each file as an upload | `filesystem` with modified-time incremental, piped to our reader |
| Google Sheets | read the spreadsheet's metadata | sheets and named ranges, with their first rows' headers | `google_spreadsheet` with the chosen ranges |
| API | one authenticated request | the OpenAPI document (`dlt-init-openapi`'s analysis) or one page per endpoint | `rest_api_resources(config)` |
| Email | log in to the mailbox | the attachments found, as files | `inbox` attachments, then each file as an upload |

- **`check`** confirms the session can only read. On PostgreSQL that means `default_transaction_read_only` and no write grants. On SQL
  Server it means only `db_datareader`-style rights, and on Oracle no write privileges and a `READ ONLY` transaction. A connection that
  can write is refused with that reason, not merely warned about.
- **`read`** runs only in the worker, never in the API. It writes to `raw.<source>__<stream>` with `_dlt_load_id` and the BI's
  columns (`_bi_sync_id`, `_bi_as_of`). Files and sheets are appended as snapshots, as today. Databases follow open question 3.

## 6. Discovery and introspection

Discovery has four layers. Each layer uses what the source declares where it can, and infers the rest.

### 6.1 Structure: streams and columns

| Source | How |
|---|---|
| **Databases** (PostgreSQL, SQL Server, Oracle, MySQL) | `sql_database(...).discover_schema()`: SQLAlchemy reflection through dlt, giving tables and views, columns, types with precision (`reflection_level="full_with_precision"`), nullability and primary keys, without reading rows. Foreign keys and comments come from SQLAlchemy's inspector on the same engine. Row counts come from the catalog statistics (`pg_class.reltuples`, `sys.partitions`, `ALL_TABLES.NUM_ROWS`), never `count(*)` on a large table. |
| **APIs** | The OpenAPI document when there is one, read by `dlt-init-openapi` (endpoints, pagination, keys, relationships, auth); otherwise one page per endpoint through `rest_api`, whose columns dlt infers. |
| **Folders** (Drive, S3, Azure, SFTP, a path) | The `filesystem` listing (names, sizes, modified times), then each file as for files. |
| **Google Sheets** | The spreadsheet's sheets and named ranges, then the header of each as for files (named ranges are what the source reads best). |
| **Files** (xlsx, xlsb, xls, ods, csv) | Nothing is declared, so everything is inferred: see 6.2. |

### 6.2 Files: finding the table in the sheet

A spreadsheet is not a table until its header row is found. The reader (calamine, which already reads every format the BI accepts) gives
the sheet as cells. The BI then scores each of the first 30 rows as a candidate header:

- most of its cells are non-empty text;
- the texts are distinct and look like labels (short, few digits);
- the rows below it agree with each other in each column's kind (numbers under a column, dates under another), and differ from it.

The best candidate becomes the header. Rows above it, such as a title, the institution's name or "Report run on …", are kept as the
file's notes and are not loaded. A header that spans two rows ("Term" above "Start | End") is joined ("Term Start", "Term End").
Empty columns and trailing empty rows are dropped, and so is a total row at the bottom whose first cell says "Total".

The page shows what was found ("Header on row 4; 3 rows above it ignored; 18 columns") and lets the person pick another row. Their
choice is remembered for that layout. Sheets with several tables side by side are out of scope for now; the person picks the range.

dlt does not do this: its Google Sheets source takes the first row of a range as the header, and its filesystem source has no Excel
reader. We looked at libraries for this and chose not to use them. [messytables](https://messytables.readthedocs.io/) (`headers_guess`) has the
right idea but is unmaintained and reads only old Excel formats; [tableintuit](https://pypi.python.org/pypi/tableintuit) is similar. The
heuristic is about a hundred lines and testable on made-up sheets (DEC-011).

### 6.3 Profiles: what each column holds

A profile is computed in PostgreSQL on the copy in `raw` (or in a draft's scratch schema before approval), with the queries
`agent/catalog.py` already runs. Rows are never read at the source to profile them, and never pulled into Python. Each column gets:

- its **kind**: identifier, category, number, date, boolean, free text or metadata. For text loaded from files, the kind comes from the
  share of values that parse as a number, a date (ISO and the common local forms) or a boolean;
- its **null rate** and **distinct count**;
- **value shapes** as patterns (`999999999`, `A-9999`, `9999-99-99`), only those at or above the suppression threshold;
- **ranges** for numbers and dates, and for categories the values and counts at or above the threshold.

What the page and the model see is the same profile. A column whose name or shape marks it as personal (6.4) is shown as a count and a
shape, never with values.

### 6.4 Sensitive columns

Each column is classified as *identifier*, *personal* (name, email, phone, address, birth date, national ID), *category*, *measure*
or *other*. The classification comes from three signals:

1. **Names.** Rules on the header in English and Arabic, extending `catalog.ID_NAME`.
2. **Shapes.** Patterns on the profile: an email, a phone number, a national ID format, a 9-digit student number.
3. **Uniqueness.** A non-null column that is nearly unique is an identifier, whatever its name.

The classification drives privacy (TASK-002): personal columns are flagged on the page, never shown as values, and left out of a
dataset unless a person maps them on purpose. OpenMetadata's auto-PII tagging uses the same split of name rules plus entity
recognition on sample rows. We use the first part. The second would need sample rows in Python, and we add it only if the rules miss
too much; then it would be [Presidio](https://microsoft.github.io/presidio/) on the BI's own machine.

For databases, a personal column that no approved mapping uses is left out of the read (`table_adapter_callback`), so it never
leaves the source. Discovery shows it from metadata alone.

### 6.5 Keys and relationships

Databases declare primary and foreign keys, and discovery reports them. For files and for databases that declare none, the BI proposes:

- **candidate keys**: a column or pair of columns with no nulls and no duplicates (`count(*) = count(distinct …)`), computed in PostgreSQL;
- **join candidates** between streams: columns whose values mostly fall within another stream's key (an inclusion check by counting),
  reported as "93% of `term_code` here appear in `Terms.code`".

These are proposals for the mapping and for the agent's draft dbt models, shown with their counts.

### 6.6 Meaning: matching a layout to a dataset

Matching uses three signals, cheapest first:

1. **Names and aliases**, as `bi.mapping.propose` does today.
2. **Profiles that fit the part.** `term_start` needs a date-shaped column and `student_id` an identifier. A candidate that does not
   fit is never proposed, whatever its name.
3. **The agent**, given the dataset's parts with their descriptions and the layout's headers with their profiles (DEC-017 allows
   both). It proposes a mapping with one line of reasoning per part.

The proposal is shown to the person, who approves or corrects it. Mappings are kept **per layout**, not per dataset, so a dataset can be
fed by files of several layouts (an old export and a new one) and by a database table at once. This lifts the one-mapping limit noted
in DEC-026. A stream whose layout changes comes back for review; its earlier mapping is the starting proposal.

A layout change is caught by dlt itself: an approved stream runs with a **frozen schema contract** (columns and types), so a file or
table with a new or changed column stops before anything loads (§ 4). The sync is then marked for review, not failed.

[Valentine](https://github.com/delftdata/valentine) (schema matching: COMA, Cupid, Similarity Flooding, distribution-based) can match a
new layout to an approved one by their data. We keep it in mind for layout changes if names and profiles turn out not to be enough.

### 6.7 Projects considered

| Project | What it offers | Use |
|---|---|---|
| [dlt](https://dlthub.com/docs/dlt-ecosystem/verified-sources/) | `sql_database`, `filesystem`, `rest_api`, Google Sheets, inbox; `discover_schema()`; schema inference, contracts, naming and lineage (§ 4) | **Use**: connecting, structural discovery, loading, layout-change detection |
| dltHub (paid) | Data quality metrics and checks, transformations, MS SQL change tracking, AI harness, runtime | **No**: licensed for use on dltHub's platform only |
| SQLAlchemy inspector | Tables, columns, keys and comments on every major database | **Use**, through dlt |
| [Airbyte protocol](https://docs.airbyte.com/platform/understanding-airbyte/airbyte-protocol) | `spec` / `check` / `discover` / `read`, a catalog of streams | **Borrow** the shape; running its connectors means a container per connector |
| [OpenMetadata](https://docs.open-metadata.org/latest/how-to-guides/data-quality-observability/profiler/auto-pii-tagging) / DataHub | Full catalogs with many connectors, profiler and PII tagging | Too heavy for one institution (they need their own servers, search and queue); **borrow** the PII approach |
| [DataProfiler](https://pypi.org/project/dataprofiler) (Capital One) | Schema, statistics and a deep-learning PII labeller | Heavy (TensorFlow); a later option for the labeller |
| [whylogs](https://docs.whylabs.ai/docs/data-security) | Statistical profiles (sketches) that hold no records | More than we need at this volume; the idea matches § 6.3 |
| [messytables](https://messytables.readthedocs.io/) / tableintuit | Guessing header rows and types in spreadsheets | Unmaintained; **own heuristic** (§ 6.2) |
| [Valentine](https://github.com/delftdata/valentine) | Schema matching between tables | Later, for layout changes |
| Presidio | PII recognisers | Later, if name and shape rules miss too much |

## 7. The flow on the page

**Connect data** lists the sources: name, type, state, last sync, datasets fed and anything waiting for review. **Add a source** starts:

1. **Choose a type.** File, a database (PostgreSQL, SQL Server, Oracle, MySQL), a shared folder or cloud spreadsheet, or an API.
2. **Connect.** For a file, drop it here. For anything else, fill in the type's settings (its `spec`), with credentials going to the
   secret store. **Test connection** runs `check`.
3. **Discover.** The catalog appears: streams with their sizes, and for files the header row found.
4. **Choose.** Tick the streams to bring in. The first sync runs into a draft area and the profiles appear.
5. **Map.** For each stream, choose the dataset it feeds (or "keep as raw only", or "new dataset", which is the agent's step 2b), then
   check the proposed mapping. Each part shows its plain name and description; each column, its header as written and its profile.
6. **Approve.** The source becomes live, the analytics are built, and later syncs run on their own (on upload for files, on a schedule
   for the others).

A source page shows its syncs. Each one is queued, running, loaded with its row count and tests, needing review because the layout
changed, or failed with a reason a person can act on. A dbt error is never shown as the explanation.

## 8. Storage

New tables in the BI's database (forward-only migrations):

- `source` (id, name, type, settings jsonb, secret refs, owner, state, created/approved by and at);
- `source_stream` (source, stream name, selected, raw table, header row, current layout);
- `layout` (fingerprint of the normalised columns, the columns as written, first seen);
- `layout_mapping` (layout, dataset, mapping, status, approved by and at), replacing `column_mapping`;
- `sync` (source, stream, started, finished, status, rows, tests, note, error), replacing `upload`.

Existing uploads become syncs of one file source per dataset, and `column_mapping` becomes the mapping of the layouts in raw.

## 9. Security

- Connections are opened only by the worker. The API stores settings and queues work.
- Credentials are in the secret table (DEC-020), never in settings, logs or the model's view, and are shown as "set" or "not set".
- `check` refuses a connection that can write (§ 5).
- Personal columns no mapping uses are not read from databases (§ 6.4).
- Each source's host is the only place the worker connects for it. Outbound access in production is an allowlist that grows by
  approved sources.
- Discovery reads metadata. Profiles are computed inside the BI, small counts are hidden, and personal columns are never shown as values.
- Every source, approval and sync is in the audit log, with who did it.

## 10. The agent

The chat agent gets the same operations as tools: `list_sources`, `discover_source`, `profile_stream`, `propose_mapping` and, with step
2b, `propose_integration`. They return catalogs and profiles, never rows. Connecting a source that needs credentials goes through
`request_credentials` (TASK-014): the person types them into the page, not the chat. These tools are not served on MCP (DEC-024 covers
only the read tools).

## 11. Delivery

| Step | Scope | Done when |
|---|---|---|
| **C1. Sources and files** | The source, stream, layout and sync model; Connect data page; the file type through the whole flow (header detection, profiles, mappings per layout, plain part names); uploads migrated | The real xlsb loads: header found, mapping proposed with profiles, approved, analytics built |
| **C2. APIs and schedules** | `rest_api` configurations, drafted from an OpenAPI document; syncs on a schedule, incremental with state; frozen contracts on approved streams | One endpoint syncs on a schedule; a changed field pauses the stream with a review |
| **C3. Oracle (Banner)** | `sql_database` with `oracledb`: `check` (read-only), `discover_schema()`, choose tables and columns, incremental history (§ 13, 3). Needs dlt 1.32 | Tables of a test Oracle (a container in CI) appear with types and keys; chosen ones load incrementally; an unmapped personal column is not read |
| **C4. PostgreSQL** | The same on `psycopg` | As C3 |
| **C5. The rest** | SQL Server, MySQL; folders (Drive, S3, Azure, SFTP, a path), Google Sheets, mail attachments; SharePoint/OneDrive through Microsoft Graph | A folder or mailbox of exports syncs new files |
| **Agent** | The tools of § 10, then 2b and 2c on top | "Connect Banner" in the chat ends in a source waiting for approval |

## 12. Decisions (recorded as DEC-027 to DEC-031)

- Connect data: sources of several types behind one connector interface (`spec`, `check`, `discover`, `read`), each a thin layer on
  a dlt source; dlt's open-source library only, not dltHub.
- Every source reaches raw through dlt; a type dlt lacks is written as a dlt source, resource or transformer, never as a separate loader.
- Approved streams load under a frozen schema contract; a layout change comes back for review.
- Discovery reads metadata at the source and profiles inside the BI; header rows are found by a heuristic; sensitive columns are
  classified by name, shape and uniqueness.
- Mappings are kept per layout, and a layout change comes back for review (amends DEC-026).

## 13. Questions, answered 2026-10-28

1. **Order of source types.** Files, then APIs, Oracle, PostgreSQL and the rest (§ 11). If dlt 1.32 is not out when C3 starts,
   PostgreSQL goes first: both use the same `sql_database` connector, so nothing is lost.
2. **Who approves a source.** Not needed now. Until the BI has stewards (people responsible for a kind of data, DEC-019), a BI admin
   approves. Approval is one step in the flow, so naming the steward later changes who sees the button, not the flow.
3. **History from databases: incremental.** Each sync reads only the rows changed since the last one, using a column the table keeps
   up to date (Banner's tables usually carry an activity date). Rows are merged with dlt's `scd2` strategy: a changed row closes the
   old version (`_dlt_valid_to`) and opens a new one (`_dlt_valid_from`). The current state and any past date stay answerable
   (contract `asOf`) without keeping a full copy per sync. A table with no reliable change column is read in full and merged the
   same way. Deletes are not seen by a cursor, so a full read reconciles each table on a slower schedule (weekly, say), closing the
   rows that disappeared. Files stay snapshots: each file is the state on its as-of date.
4. **Draft data.** Profiles are computed on loaded data, so connecting a source loads some of it before anyone approves it. That draft
   data goes to its own schema per source (`draft_<source>`), never to `raw`. It is dropped if the source is abandoned, and replaced
   by the first real sync on approval. Nothing in a draft schema is read by dbt, Cube or the chat.
5. **Column names in raw.** dlt turns each header into a database column name. With its default (`snake_case`), any non-Latin
   character is dropped: "اسم الطالب" and "رقم الطالب" both become `x` (`sql_ci_v1` makes both `_`). Tried on PostgreSQL with dlt
   1.31: a row with both columns loaded **one** column `x` holding the second value; the first was lost without an error. With
   `duck_case`, both columns loaded under their Arabic names. Raw therefore uses `duck_case` (C1, which also fixes today's upload
   path). The transforms already quote column names (`mapped` macro). The header as written is still kept in `layout` for display.
   PostgreSQL allows 63 bytes per name, about 30 Arabic letters; dlt shortens longer names with a hash.
6. **dlt version.** 1.31.0 is the latest release (PyPI, 2026-10-07), and the BI already runs it. The docs describe 1.32, which is
   not released yet; Oracle's time-zoned timestamps need it (C3).
