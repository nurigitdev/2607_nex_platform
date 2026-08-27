# Slice 0391: AE Web Repaired Response Review Surface Boundary

## Scope

Start S40 by freezing the AE Web surface decision for repaired response review.
The primary user surface is the chat interaction detail area. Document detail
may link into the review flow, but it is not the primary ownership surface for
accepting or keeping repaired responses.

## Changes

- Added `apps/nex-ae-web/src/repairedResponseReviewBoundary.js`.
- Added Node regression coverage in
  `apps/nex-ae-web/test/repairedResponseReviewBoundary.test.mjs`.
- Documented the Slice in the AE Web README and global slice index.

## Boundary Decision

- Primary surface: `chat_interaction_detail`.
- Secondary surfaces: `document_detail_link`, `lineage_drilldown`.
- Decision actions: `accept_repair`, `keep_original`.
- Submitter: `chat_review`.
- Browser storage policy: decision payload and safe display metadata only.

The boundary keeps raw prompts, raw generation output, raw source text, service
tokens, provider endpoints, database endpoints, and storage locations out of
browser state and browser-safe summaries.

## Evidence

Targeted regression:

```text
node --test test/repairedResponseReviewBoundary.test.mjs
4 passed
```

AE Web Node regression:

```text
npm --prefix apps/nex-ae-web test
119 passed
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2851 passed, 1 warning in 78.05s
statement_coverage=98.68% threshold=95.00%
branch_coverage=96.13% threshold=85.00%
contract_validation=pass schemas=62 examples=92 negative_examples=68 openapi=7
```

No PostgreSQL smoke is required for this boundary Slice because it does not
execute API routes or persist repaired response decisions.
