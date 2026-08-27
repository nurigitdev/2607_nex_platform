# Slice 0392: AE Web Repaired Response Handoff Client Adapter

## Scope

Expose repaired response review projections through AE API read-only routes and
add the AE Web client adapter that consumes those projections. Decision submit
remains deferred to the later decision adapter Slice.

## Changes

- Added AE API read-only review routes:
  - `GET /api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/review`
  - `GET /api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/{repaired_response_handoff_id}/review`
- Added `apps/nex-ae-web/src/repairedResponseReviewClient.js`.
- Registered the client in `apps/nex-ae-web/src/clientRegistry.js`.
- Added Node regression coverage for mock/fetch adapters and registry wiring.
- Added Python route coverage for authenticated list/detail review projection.
- Updated AE OpenAPI coverage for the new read-only review routes.

## Notes

The Web adapter normalizes `ae_repaired_response_review_projection.v1` into a
browser-safe `ae_web_repaired_response_review_surface.v1` state. It keeps raw
prompts, raw generation output, source text, service tokens, provider URLs,
database URLs, and storage paths out of browser summaries.

## Evidence

Targeted Python regression:

```text
./.venv/bin/pytest tests/test_nex_ae_repaired_responses.py -q --cov=nex_ae_api.repaired_responses --cov-branch --cov-report=term-missing
69 passed, 1 warning in 2.96s
services/nex-ae-api/nex_ae_api/repaired_responses.py statement_coverage=100% branch_coverage=100%
```

Targeted AE Web regression:

```text
node --test test/repairedResponseReviewClient.test.mjs test/clientRegistry.test.mjs
8 passed
```

AE Web regression:

```text
npm --prefix apps/nex-ae-web test
124 passed
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
schemas=62 examples=92 negative_examples=68 openapi=7
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2853 passed, 1 warning
statement_coverage=98.68%
branch_coverage=96.13%
```

No PostgreSQL smoke is required for this Slice because it adds read-only API
projection routes and browser client normalization without new persistence.
