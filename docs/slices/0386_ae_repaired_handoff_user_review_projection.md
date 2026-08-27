# Slice 0386: AE Repaired Handoff User Review Projection

## Scope

Define the AE Web-facing review projection for repaired response handoffs before
adding user decision persistence or decision routes.

This slice does not add a database migration, external route, remote provider
call, or PostgreSQL smoke. It turns a validated
`ae_repaired_response_handoff.v1` record into a redaction-safe
`ae_repaired_response_review_projection.v1` read model that AE Web can render.

## Implemented

- Added `services/nex-ae-api/nex_ae_api/repaired_response_review.py`.
- Added `repaired_response_review_projection.v1` JSON Schema.
- The projection includes:
  - owner and conversation scope;
  - original/repaired generation refs;
  - safe repaired output hash and short preview;
  - lineage summary;
  - review card state;
  - primary user actions: `accept_repair`, `keep_original`;
  - secondary actions: `view_original`, `view_repaired`, `view_lineage`;
  - future decision submit path ending in `/decisions`;
  - redaction flags proving raw prompt/output/source/evidence are excluded.
- Added collection helper coverage for interaction-scoped lists and stable
  newest-first ordering.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ae_repaired_responses.py -q --cov=nex_ae_api.repaired_response_review --cov-branch --cov-report=term-missing
43 passed, 1 warning in 1.22s
services/nex-ae-api/nex_ae_api/repaired_response_review.py statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2807 passed, 1 warning in 79.10s
statement_coverage=98.66%
branch_coverage=96.08%
contract_validation=pass schemas=61 examples=92 negative_examples=68 openapi=7
```

Recommended next slice:

```text
Slice 0387: AE repaired handoff user decision contract and persistence foundation
```
