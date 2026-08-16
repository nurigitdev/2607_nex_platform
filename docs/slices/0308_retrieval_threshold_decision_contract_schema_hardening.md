# Slice 0308: Retrieval Threshold Decision Contract Schema Hardening

## Scope

Harden the AG retrieval score calibration and threshold decision contract surface
after the PostgreSQL smoke evidence proved the runtime behavior. This slice
aligns JSON Schema, OpenAPI, and negative contract fixtures so operators and
clients can depend on the AG retrieval operations projections without relying on
implementation-only knowledge.

This slice does not call remote embedding, reranker, or generation providers.

## Implemented

- Added strict `allOf` requirements for:
  - `ag_retrieval_score_calibration_rollup_projection.v1`
  - `ag_retrieval_threshold_decision_projection.v1`
- Added reusable summary definitions for score calibration and threshold
  decision projections.
- Added a reusable score margin range definition shared by calibration
  summaries.
- Hardened threshold decision operation enums for:
  - policy status
  - decision status
  - recommended operator action
- Added AG OpenAPI paths for:
  - `/admin/v1/operations/retrieval-score-calibration`
  - `/admin/v1/operations/retrieval-threshold-decisions`
- Added both retrieval projection schema versions to the OpenAPI
  `AgOperationsProjection` enum.
- Added a negative fixture proving non-canonical threshold operator actions do
  not validate.
- Added regression checks for schema conditional requirements and OpenAPI path
  exposure.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_contract_validation.py -q`
- Contract validation:
  `./.venv/bin/python scripts/quality/validate_contracts.py`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Observed quality gate summary:

```text
2128 passed, 1 warning
statement_coverage=98.48% threshold=95.00%
branch_coverage=95.19% threshold=85.00%
contract_validation=pass schemas=50 examples=81 negative_examples=56 openapi=7
```
