# Slice 0303: Retrieval Threshold Decision AG Projection

## Scope

Add an AG read-only projection that combines the retrieval policy registry
threshold-decision checkpoint with persisted CX score-calibration samples.

This slice does not call remote embedding, reranker, or generation providers.
It evaluates already persisted retrieval package score metadata and is safe to
run while remote providers are unreachable.

## Implemented

- Added `GET /admin/v1/operations/retrieval-threshold-decisions`.
- Added `ag_retrieval_threshold_decision_projection.v1`.
- Evaluated policy threshold decision readiness by comparing observed sample
  counts with `minimum_live_samples_before_change`.
- Reported readiness states:
  - `SOURCE_DEGRADED`;
  - `NO_DECISION_CHECKPOINT`;
  - `INSUFFICIENT_SAMPLES`;
  - `NEEDS_OPERATOR_REVIEW`;
  - `READY_FOR_REVIEW`.
- Included safe operator actions such as collecting more live samples, repairing
  the read source, reviewing override samples, or preparing policy review.
- Reused AG retrieval calibration sample projections without exposing raw query
  text, source text, evidence text, vectors, provider endpoints, API keys, or
  local file paths.
- Added contract schema and positive example coverage.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ag_retrieval_operations.py tests/test_contract_validation.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Live DGX provider smoke was not required for this slice because the projection
only reads persisted retrieval score-calibration metadata.
