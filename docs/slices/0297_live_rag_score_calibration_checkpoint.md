# Slice 0297: Live RAG Score Calibration Checkpoint

## Scope

Make protected live RAG PostgreSQL smoke evidence explain the retrieval score
boundary used for generation.

Slice 0295 proved that the end-to-end live path can hit a generation guard when
the retrieval package is `LOW_CONFIDENCE`. Slice 0296 made that failure visible.
This slice records the score/threshold calibration data on successful runs so
operators can see whether the smoke passed under the default policy or only
because the protected smoke lowered the test threshold.

## Implemented

- Added a `score_calibration` execution stage to protected live RAG PostgreSQL
  smoke evidence.
- Added `protected_live_rag_score_calibration.v1` evidence with:
  - retrieval `best_score`;
  - evidence count;
  - observed smoke `low_confidence_threshold`;
  - default low-confidence threshold;
  - observed and default confidence buckets;
  - threshold override direction;
  - whether the score would pass the default threshold;
  - score margins to both thresholds;
  - a compact calibration action for operators.
- Added a `score_calibration_recorded` check so successful evidence must include
  the checkpoint and match the retrieval status.
- Kept all checkpoint fields safe for smoke evidence: no provider endpoints,
  credentials, database passwords, source text, or local paths.

## Evidence

- Python regression:
  `./.venv/bin/pytest tests/test_protected_live_rag_postgres_smoke.py -q`
- Protected live PostgreSQL smoke:
  `NEX_PROTECTED_LIVE_RAG_POSTGRES_SMOKE=1 ./.venv/bin/python scripts/smoke/run_protected_live_rag_postgres_smoke.py --summary`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
