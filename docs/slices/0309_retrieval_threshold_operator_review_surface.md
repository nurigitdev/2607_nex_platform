# Slice 0309: Retrieval Threshold Operator Review Surface

## Scope

Add an operator-facing runbook/review surface to AG retrieval threshold
decisions. The goal is to make each threshold decision self-explanatory for
operations review: what state it is in, which runbook applies, which AG paths
should be inspected, what evidence is still needed, and whether live provider or
policy-registry work is required.

This slice does not call remote embedding, reranker, or generation providers.

## Implemented

- Added `ag_retrieval_threshold_operator_review.v1` metadata to each AG
  retrieval threshold decision.
- Added canonical runbook mappings for:
  - repairing degraded retrieval operation sources
  - registering missing threshold decision checkpoints
  - collecting live score samples
  - reviewing threshold override samples
  - reviewing low-confidence/no-answer samples
  - preparing threshold policy review
- Added direct operator paths for threshold decisions, calibration samples, and
  retrieval policy detail review.
- Added remaining-sample-count calculation so operators can see how far a
  policy is from the minimum live-sample checkpoint.
- Enriched retrieval threshold issue-candidate signals with runbook ids and
  review paths.
- Hardened the AG operations JSON Schema so `operator_review` is required and
  strict.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ag_retrieval_threshold_decisions.py tests/test_nex_ag_retrieval_operations.py::test_retrieval_threshold_decision_projection_evaluates_sample_readiness tests/test_nex_ag_retrieval_operations.py::test_retrieval_threshold_decision_projection_reports_review_and_gaps tests/test_nex_ag_retrieval_operations.py::test_retrieval_threshold_decision_route_filters_and_validates tests/test_nex_ag_operations.py::test_operations_issue_candidate_projection_flags_retrieval_threshold_decisions tests/test_nex_ag_operations.py::test_operations_issue_candidates_group_threshold_decision_readiness tests/test_contract_validation.py::test_nex_ag_operations_contract_hardens_retrieval_threshold_decisions -q`
- Contract validation:
  `./.venv/bin/python scripts/quality/validate_contracts.py`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Observed quality gate summary:

```text
2130 passed, 1 warning
statement_coverage=98.48% threshold=95.00%
branch_coverage=95.19% threshold=85.00%
contract_validation=pass schemas=50 examples=81 negative_examples=56 openapi=7
```
