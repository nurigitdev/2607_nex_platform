# Slice 0306: Threshold Decision Issue Candidate Rules

## Scope

Promote retrieval threshold decision readiness from the AG dashboard snapshot
into deterministic issue-candidate rules.

This slice stays mock-first and does not call remote providers or PostgreSQL
smoke paths.

## Implemented

- Added threshold-specific issue rule catalog entries for missing checkpoints,
  insufficient live samples, operator review, and policy review readiness.
- Wired retrieval package stores into
  `build_operations_issue_candidate_projection` so
  `/admin/v1/operations/issue-candidates` can reuse the dashboard threshold
  decision section.
- Added grouped issue candidates by service and threshold readiness.
- Kept `SOURCE_DEGRADED` on the existing degraded-source candidate path to
  avoid duplicate source-failure alerts.
- Updated issue-candidate contract examples and mock dashboard smoke evidence.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ag_operations.py::test_build_operations_issue_candidate_projection_flags_service_scope tests/test_nex_ag_operations.py::test_operations_issue_candidate_projection_flags_retrieval_threshold_decisions tests/test_nex_ag_operations.py::test_operations_issue_candidates_group_threshold_decision_readiness tests/test_smoke_helpers.py::test_ag_operations_dashboard_smoke_passes_mock_pack tests/test_contract_validation.py -q`
- Mock dashboard smoke:
  `./.venv/bin/python scripts/smoke/run_ag_operations_dashboard_smoke.py --summary`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
