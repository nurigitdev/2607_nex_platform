# Slice 0310: Retrieval Threshold Calibration Closure Checkpoint

## Scope

Close the S31 retrieval threshold calibration sequence with an explicit AG
closure checkpoint. Operators need a compact answer to whether calibration is
blocked, still collecting samples, waiting for review, or ready for policy
review.

This slice does not call remote embedding, reranker, or generation providers.

## Implemented

- Added `ag_retrieval_threshold_calibration_closure.v1` summary metadata.
- Added closure status priority:
  - `NO_DECISIONS`
  - `BLOCKED`
  - `COLLECTING_SAMPLES`
  - `OPERATOR_REVIEW_REQUIRED`
  - `READY_FOR_POLICY_REVIEW`
- Added closure metadata to:
  - `GET /admin/v1/operations/retrieval-threshold-decisions`
  - the AG operations dashboard `retrieval_threshold_decisions` section
- Included readiness counts, blocked/ready policy ids, recommended next actions,
  minimum-live-sample satisfaction, and policy-review readiness.
- Hardened the AG operations JSON Schema so threshold decision projections and
  dashboard snapshots must include the closure checkpoint.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_ag_retrieval_operations.py tests/test_nex_ag_retrieval_threshold_decisions.py tests/test_contract_validation.py -q`
- Contract validation:
  `./.venv/bin/python scripts/quality/validate_contracts.py`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Observed quality gate summary:

```text
2131 passed, 1 warning
statement_coverage=98.49% threshold=95.00%
branch_coverage=95.20% threshold=85.00%
contract_validation=pass schemas=50 examples=81 negative_examples=56 openapi=7
```
