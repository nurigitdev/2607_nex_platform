# Slice 0304: AG Retrieval Operations Refactoring Checkpoint

## Scope

Refactor the AG retrieval operations threshold-decision logic before adding
dashboard and issue-candidate integrations.

This slice does not change external API behavior and does not call remote
embedding, reranker, or generation providers.

## Implemented

- Extracted threshold-decision constants and pure readiness/projection helpers
  into `nex_ag.retrieval_threshold_decisions`.
- Kept AG route and store wiring in `nex_ag.retrieval_operations`.
- Preserved the existing `GET /admin/v1/operations/retrieval-threshold-decisions`
  response shape.
- Added unit coverage for source-degraded, missing checkpoint, insufficient
  samples, threshold override review, low-confidence review, ready-for-review,
  and malformed count inputs.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ag_retrieval_operations.py tests/test_nex_ag_retrieval_threshold_decisions.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
