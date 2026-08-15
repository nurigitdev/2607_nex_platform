# Slice 0299: Live RAG Score Calibration AG Observability

## Scope

Expose safe live-RAG score calibration signals through AG retrieval package
operations without requiring live remote provider access.

Slice 0297 captured a live score boundary where the observed retrieval package
could be accepted by the smoke harness while still sitting below the canonical
default low-confidence threshold. Slice 0299 keeps the default retrieval policy
unchanged and makes that comparison visible to operators in AG.

## Implemented

- Added `ag_retrieval_score_calibration.v1` records to AG retrieval package
  list/detail projections.
- Compared each persisted CX retrieval package score bucket against the active
  default retrieval low-confidence threshold.
- Added aggregate calibration counts to the retrieval package operations
  summary:
  - threshold override count;
  - default READY/LOW_CONFIDENCE/NO_ANSWER counts;
  - would-pass-default-threshold count;
  - calibration action counts.
- Hardened the AG operations contract schema and positive examples with the
  optional nested score-calibration object.
- Added regression coverage for no-answer, ready, lowered-threshold,
  raised-threshold, and incomplete-score calibration branches.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ag_retrieval_operations.py tests/test_contract_validation.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Live DGX provider smoke was intentionally not run for this slice because this
slice only projects already-persisted CX retrieval package metadata. Run the
protected live provider/RAG smoke suite again from the office network before
changing canonical retrieval thresholds.
