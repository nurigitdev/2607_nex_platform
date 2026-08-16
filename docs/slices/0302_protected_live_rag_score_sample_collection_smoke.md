# Slice 0302: Protected Live RAG Score Sample Collection Smoke

## Scope

Add a protected smoke runner for collecting multiple live RAG score-calibration
samples through the existing PostgreSQL-backed live RAG smoke.

This slice does not require direct remote provider connectivity in the default
regression path. The runner is disabled by default and returns `SKIPPED` unless
`NEX_PROTECTED_LIVE_RAG_SCORE_SAMPLE_SMOKE=1` is set.

## Implemented

- Added `scripts/smoke/run_protected_live_rag_score_sample_smoke.py`.
- Added activation and sample controls:
  - `NEX_PROTECTED_LIVE_RAG_SCORE_SAMPLE_SMOKE`;
  - `NEX_PROTECTED_LIVE_RAG_SCORE_SAMPLE_SMOKE_PROFILE`;
  - `NEX_PROTECTED_LIVE_RAG_SCORE_SAMPLE_COUNT`.
- Restricted write-capable execution to the `test` profile.
- Wrapped `run_protected_live_rag_postgres_smoke` and enabled the nested
  PostgreSQL live RAG smoke per collected sample.
- Generated unique trace ids per sample.
- Projected only safe score-calibration fields from nested evidence.
- Added sample rollup counts for status, confidence bucket, calibration action,
  policy, threshold overrides, default-threshold pass count, and score-margin
  range.
- Added redaction checks for provider secrets, database secrets, raw source
  fragments, and local storage paths.
- Connected the new smoke runner to `scripts/quality/run_quality_gate.sh` as a
  skipped-by-default protected smoke.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_smoke_helpers.py -k protected_live_rag_score_sample -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Live DGX provider execution was intentionally not required for this slice
because the current working environment cannot reach the remote providers.
