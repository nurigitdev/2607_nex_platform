# Slice 0300: Retrieval Threshold Decision Checkpoint

## Scope

Record the retrieval low-confidence threshold decision after the protected
live RAG calibration work.

The Slice 0297 live evidence showed that a smoke-only threshold override can
allow a retrieval package that would remain below the canonical `0.2`
low-confidence threshold. Slice 0300 does not lower the canonical threshold.
Instead, it records an explicit `OBSERVE` decision in the AG retrieval policy
registry so operators can see that more live score samples are required before
publishing a threshold change.

## Implemented

- Added `retrieval_threshold_decision.v1` checkpoint metadata to the shared
  retrieval policy registry records.
- Kept both current and weighted-RRF candidate policies at canonical
  `low_confidence_threshold = 0.2`.
- Marked the current decision status as `OBSERVE` with operator action
  `collect_live_score_samples`.
- Added AG policy summary visibility via `threshold_decision_observe`.
- Kept the threshold decision as AG/operator metadata; CX runtime policy
  mapping continues to ignore this field when building scoring behavior.
- Added validation coverage for bad decision schema, status, threshold,
  sample-count, and evidence-source shapes while preserving compatibility with
  legacy policy records that do not yet include `threshold_decision`.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ag_retrieval_policies.py tests/test_nex_cx_retrieval.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Live DGX provider smoke was not required for this slice because no remote
provider request path changed. The next live office-network run should collect
additional score-calibration samples before changing canonical thresholds.
