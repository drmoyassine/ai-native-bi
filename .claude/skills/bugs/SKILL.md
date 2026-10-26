# /bugs

Manage AI-native BI bugs via GitHub Issues.

<!-- EXTEND: If your project has an additional bug-tracking system (e.g., a database
     table, Sentry, an error-reporting service), document it here and add the
     integration to the commands below. -->

## Commands

- `list` — Show all bug reports from GitHub Issues
- `create` — Create a new bug report (GitHub Issue)
- `resolve` — Resolve a bug (close Issue)
- `sync` — Cross-reference task `related_bugs` with Issue state

## How to use

### List bugs
```
/bugs list
/bugs list status:open
/bugs list label:bug
```

Shows:
- Issue number
- Title
- Status (open/closed)
- Labels
- Created date

### Create a bug report
```
/bugs create
```
You'll be prompted for:
- Title (short description)
- Description (full details, reproduction steps)
- Severity (P0/P1/P2/P3)
- Labels (bug, feature, question)

This creates a GitHub Issue with the `bug` label:
```bash
gh issue create --title "..." --body "..." --label bug
```

### Resolve a bug
```
/bugs resolve 42
```
Closes the GitHub Issue:
```bash
gh issue close 42
```

### Sync
```
/bugs sync
```
1. Queries open GitHub Issues with `bug` label
2. Scans TASKS.md for all `related_bugs` entries
3. Reports:
   - Issues in GitHub that don't appear in any task's `related_bugs`
   - Task `related_bugs` entries pointing at closed/nonexistent Issues
4. Offers to fix discrepancies (add missing refs, flag stale ones)

## How TASKS.md references bugs

Bugs have no markdown file of their own — GitHub Issues ARE the source of truth. A task links to a bug via its `related_bugs` array using the standard `id + name + url` pattern (id = issue number, absolute URL since Issues are external):

```yaml
related_bugs:
  - id: 42
    name: "Bug title"
    url: https://github.com/drmoyassine/ai-native-bi/issues/42
```

Bugs can also link to decisions that affected or blocked them:

```yaml
related_decisions:
  - id: DEC-001
    name: "Decision title"
    url: /DECISIONS.md#DEC-001
```

When `/bugs sync` finds an Issue with no referencing task, or a task `related_bugs` entry pointing at a closed/nonexistent Issue, report it as a discrepancy.

## Cross-linking philosophy

Bugs link to **TASKS** (via `related_bugs` in task schema) and **DECISIONS** (via `related_decisions`), not to `log.md`. A bug that results from or blocks a decision should link to that decision.

## Labels

| Label | Purpose |
|---|---|
| bug | Software defect |
| feature | Feature request |
| question | Question or clarification |
<!-- EXTEND: Add project-specific labels here (e.g., platform-health, performance, security) -->

## Implementation notes

- Bugs live in **GitHub Issues** as the source of truth.
- Use `gh issue` commands for GitHub operations.
- When syncing, match by issue number stored in the `related_bugs[].id` field.
