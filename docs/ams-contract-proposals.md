# Contract changes to raise in the AMS

The AMS owns the contract (`docs/ams-bi-contract-v0.md` is a copy). These are changes the BI needs; each is decided and made in the
AMS first, then mirrored here. v0 is still a draft, so none of them waits for v1.

## 1. More kinds of request

Today the AMS asks for one thing: collect one run of an evidence item (`POST /ams/collect`, answered 200 or 202 and the callback). The
BI owns its KPIs end to end, and the AMS should be able to ask it for:

| Request | The BI answers with |
|---|---|
| A reading of a KPI (for a period, with dimensions and filters) | Rows, `asOf`, `lineage` (what `collect` does today) |
| A table | A table built from governed KPIs |
| A dashboard | A dashboard, or its address |
| A new KPI, described by a request schema | The KPI once a person in the BI has approved it, or a refusal with the reason |

Proposal: each is a new request kind beside `collect`, with the same key, the same callback and the same one-time token. `collect`
does not change.

## 2. Manual entry, sheets and forms move to the BI

The AMS has the collection methods `form` and `manual` today (contract 3.1, 3.6). Data typed or uploaded by people becomes a source
of the BI like any other: the AMS asks for it (as a `bi` item) and the BI sends it back in the format asked. What happens to the AMS's
existing `form` and `manual` items is the AMS's decision.

## 3. The contract mirror in Python

The BI is now Python (FastAPI, Pydantic; its mirror is `src/bi/contract.py`). Proposal: the AMS publishes its contract schemas as JSON Schema (generated from its Zod
schemas), and the BI generates its Pydantic models from them, with a test that fails when the two drift.

## 4. Names in queries

The BI's mirror accepts names (metric, dimension, filter field) of lowercase letters, digits and `_`; contract 3.1 says names may also
have `.` and `-`. To check against the AMS's `packages/shared/src/collection.ts` and align the contract text or the schema.
