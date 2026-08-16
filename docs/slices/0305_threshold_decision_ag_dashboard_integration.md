# Slice 0305: Threshold Decision AG Dashboard Integration

## Scope

Surface retrieval threshold decision readiness in the AG operations dashboard
without calling remote embedding, reranker, or generation providers.

## Implemented

- Added a `retrieval_threshold_decisions` section to
  `ag_operations_dashboard_snapshot_projection.v1`.
- Reused the shared retrieval score-calibration and threshold-decision helpers
  so dashboard summaries match the dedicated retrieval operations endpoints.
- Wired optional retrieval package stores into
  `/admin/v1/operations/dashboard` and the mock dashboard smoke fixture.
- Reported retrieval threshold source failures as dashboard degraded-source
  signals.
- Updated the AG operations contract schema and dashboard mock example.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ag_operations.py::test_build_operations_dashboard_snapshot_projection_combines_sections tests/test_nex_ag_operations.py::test_operations_dashboard_snapshot_reports_retrieval_threshold_source_unavailable tests/test_nex_ag_operations.py::test_operations_dashboard_snapshot_route_requires_auth_returns_projection tests/test_smoke_helpers.py::test_ag_operations_dashboard_smoke_passes_mock_pack -q`
- Mock dashboard smoke:
  `./.venv/bin/python scripts/smoke/run_ag_operations_dashboard_smoke.py --summary`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
