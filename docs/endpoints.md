# Endpoint map (from docs/ams-bi-contract-v0.md)

The contract is owned by the AMS repo (drmoyassine/ams, `docs/ams-bi-contract-v0.md`); this copy is for reading. Change it there first.

## Calls the BI receives (the BI serves these)

| Route | Built in AMS | Mode | What |
|---|---|---|---|
| `POST {BI_BASE_URL}{path}` — default path `/ams/collect`; the AMS's `BI_ENDPOINTS` maps an item's endpoint name to another path | yes | sync **or** async | One collection run. Answer **200** with the supply (sync), or **202** and call back later (async). Anything else fails the run; the AMS retries after 15 min, 1 h, 4 h, 12 h (5 attempts). Bearer `BI_API_KEY`, HTTPS, timeout = the item's `timeoutSeconds` or 60 s |
| `POST {bi}/hooks/ams` | no (planned) | async | Webhook: `run.created|updated`, `evidence.version.created`, `link.reviewed`, `dataset.specification.updated` |

## Calls the BI makes (the AMS serves these, under `/api/bi/v0`)

| Route | Built in AMS | What |
|---|---|---|
| `POST /runs/{id}/supply` | yes | The async answer to a run. Bearer = the run's one-time `callbackToken` (14 days, single use). Body: exactly one of `rows`, `fileBase64` (+`fileName`, `mime`), `url`; plus `asOf`, `lineage`, `notes`. 200 supplied · 401 token · 409 not waiting · 422 `issues` (fix and resend) |
| `GET /runs?updatedSince=` | no | List of runs (not needed: the AMS pushes each run) |
| `GET /datasets/{evidenceItemId}/specification` | no | Columns and grain |
| `GET /evidence?updatedSince=` | no | Item metadata, latest version summary |
| `GET /evidence-versions/{id}/file` | no | A version's file (DEC-019) |
| `POST /datasets/{evidenceItemId}/versions` | no | Supply rows without a run |
| `POST /evidence/{id}/versions` | no | Supply a file or URL without a run |
| `POST /links` | no | Propose an evidence link with a rationale |
| `GET /org` | no (open question) | The org chart, read-only |

The planned AMS routes need a BI service identity (contract §6), which is not built yet. Every POST will take an `Idempotency-Key`.

## Sync vs async in practice

- A fast query (seconds): answer 200 with `rows` + `asOf` + `lineage`.
- Anything slower than the timeout, or needing a person/steward: answer 202 at once, queue the job, then `POST` the callback with the token.
