# Slice 0301: Retrieval Calibration Sample Rollup Query

## Scope

Add an AG read-only rollup/query surface for persisted CX retrieval
score-calibration samples.

This slice does not call remote embedding, reranker, or generation providers.
It reuses the existing AG retrieval package read store and projects the
already-persisted score metadata from CX retrieval packages.

## Implemented

- Added `GET /admin/v1/operations/retrieval-score-calibration`.
- Added `ag_retrieval_score_calibration_rollup_projection.v1`.
- Supported safe filters for:
  - service id;
  - retrieval package status;
  - trace id;
  - request id;
  - retrieval policy id;
  - calibration action;
  - default confidence bucket;
  - threshold override;
  - time window, sort, cursor, and limit.
- Added safe calibration sample rows without raw query text, source text,
  evidence text, provider endpoints, API keys, vectors, or local paths.
- Added rollup summary counts by policy, observed status, default confidence
  bucket, calibration action, threshold override, default pass, and score margin
  range.
- Hardened the AG operations contract schema and positive examples.
- Added route/filter/summary regression coverage.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ag_retrieval_operations.py tests/test_contract_validation.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Live DGX provider smoke was not required for this slice because the endpoint
only reads persisted retrieval package metadata.
