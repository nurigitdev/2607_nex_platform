# Slice 0397: AE Web Repaired Response Review Read Model

## Scope

Add a browser-safe read-model for AE Web repaired response review collections.
This Slice prepares the chat surface to summarize and filter multiple repaired
response reviews without changing server persistence or API contracts.

## Changes

- Added `apps/nex-ae-web/src/repairedResponseReviewReadModel.js`.
- Added `apps/nex-ae-web/test/repairedResponseReviewReadModel.test.mjs`.
- Documented the new read-model in the AE Web README and global slice index.

## Notes

The read-model derives from repaired response review card summaries, so it
inherits the card's safe rendering boundary. It only stores IDs, statuses,
counts, selected state, client mode, and redaction metadata.

Supported filters are `all`, `actionable`, `ready`, `submitting`, `recorded`,
and `failed`.

## Evidence

Targeted regression:

```text
node --test apps/nex-ae-web/test/repairedResponseReviewReadModel.test.mjs
4 passed
```

AE Web regression:

```text
npm --prefix apps/nex-ae-web test
142 passed
```

Syntax check:

```text
node --check apps/nex-ae-web/src/repairedResponseReviewReadModel.js
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2868 passed, 1 warning
statement_coverage=98.69%
branch_coverage=96.14%
contract_validation=pass schemas=62 examples=92 negative_examples=68 openapi=7
```

No PostgreSQL smoke is required for this Slice because it adds a browser
read-model over already fetched review surfaces without executing new API routes
or persistence writes.
