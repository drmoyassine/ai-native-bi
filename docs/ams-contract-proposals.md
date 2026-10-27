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

## 4. Names in queries (resolved in the BI)

The BI's mirror accepted only lowercase names of 64 characters; the AMS (`NAME` in `packages/shared/src/evidence.ts`) accepts
`^[A-Za-z][A-Za-z0-9_.-]{0,99}$`, as contract 3.1 says. The mirror was wrong and now follows the AMS; nothing to raise.

## 5. A person's identity, role and data scope ([#10](https://github.com/drmoyassine/ai-native-bi/issues/10)): answered, contract 6.2 (AMS DEC-035)

Contract §6 defines the BI only as a service identity in the AMS. The BI's app, its MCP server (`docs/mcp-spec.md`) and later BI tools
must act as a *person*, with that person's rights, and those rights should come from the AMS when the two run together. The BI must
support a range of sign-in setups with one claim vocabulary: its own accounts (standalone), the AMS as identity provider, the
institution's SSO (federated by the AMS or trusted directly), and the existing service identity for machine calls.

Proposal: the AMS is an OpenID Connect issuer (discovery and published signing keys) that issues short-lived tokens with the BI as
audience, carrying a stable subject, email, name, the person's BI role (`viewer`, `steward`, `admin`) and data scope (stable org-unit or
program ids, see contract open question 6); MCP clients sign people in through it (OAuth 2.1 authorization code with PKCE); a person
disabled in the AMS is refused at the next token. Open: the AMS role mapping, whether the AMS federates the institution's SSO, client
registration for MCP clients (dynamic or pre-registered), token lifetimes.

**Answered 2026-10-27** in contract 6.2 (AMS DEC-035): the AMS is an OAuth 2.1 / OpenID Connect issuer (`{APP_URL}/api/auth`, EdDSA
keys at `/api/auth/jwks`, PKCE required), access tokens of 10 minutes with `aud` = the BI's resource (`BI_OAUTH_AUDIENCE`), claims
`sub`, `email`, `name`, `bi_role` and `bi_scope` (institution, org-unit and program ids with a role each), the AMS role mapping,
refusal and deprovisioning at the next refresh. Clients are pre-registered by an AMS admin (`OAUTH_CLIENTS`; no dynamic registration
yet); the institution's SSO is federated through the AMS. Built on the BI side as TASK-018 (DEC-025). Still open: the org chart read
(contract open question 6) that resolves scope ids, and dynamic client registration.

## 6. Co-deployment on one database (contract 6.3, AMS DEC-034 revised)

Not a request: the AMS revised the rule. When both run together they share **one PostgreSQL database**: the AMS in `ams` (and
`pgboss`), the BI in schemas of its own (its tables in `bi`, its job queue in its own schema) and `public` for its analytic data.
The BI today uses its own database with its tables in `public`; moving to this layout is TASK-021.
