#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-./.venv/bin/python}"
STATEMENT_COVERAGE_MIN="${STATEMENT_COVERAGE_MIN:-95}"
BRANCH_COVERAGE_MIN="${BRANCH_COVERAGE_MIN:-85}"
REPORT_DIR="${REPORT_DIR:-reports/coverage}"

export PYTHONPATH="services/_shared:services/nex-oa:services/nex-ag:services/nex-ae-api:services/nex-cx:services/nex-mo:providers/nex-compatible-provider:scripts/db:scripts/dev:scripts/smoke:scripts/quality${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$REPORT_DIR"

"$PYTHON_BIN" -m pytest \
  --cov=services \
  --cov=scripts \
  --cov=providers \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report="json:$REPORT_DIR/coverage.json" \
  "$@"

"$PYTHON_BIN" scripts/quality/check_coverage_thresholds.py \
  "$REPORT_DIR/coverage.json" \
  "$STATEMENT_COVERAGE_MIN" \
  "$BRANCH_COVERAGE_MIN"

"$PYTHON_BIN" scripts/quality/validate_contracts.py

"$PYTHON_BIN" scripts/smoke/run_ae_web_static_browser_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_retrieval_quality_warning_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_grounded_response_quality_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_fetch_mode_protected_smoke_boundary.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_fetch_mode_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_traceable_mock_flow.py --summary
"$PYTHON_BIN" scripts/smoke/run_generation_recovery_mock_flow.py --summary
"$PYTHON_BIN" scripts/smoke/run_ag_operations_dashboard_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ag_generation_quality_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ag_generation_quality_disposition_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ag_job_control_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ag_service_log_retention_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ag_service_log_retention_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/check_local_live_provider_config.py --summary
"$PYTHON_BIN" scripts/smoke/run_protected_remote_provider_live_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_protected_live_rag_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_protected_live_rag_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_protected_live_rag_score_sample_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_postgres_jobqueue_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_postgres_job_replay_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_postgres_operational_event_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_postgres_service_log_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_postgres_service_log_retention_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_postgres_service_log_retention_http_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_postgres_operations_smoke_pack.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_retrieval_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_upload_ownership_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_upload_duplicate_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_document_library_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_document_detail_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_document_detail_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_oa_session_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_oa_user_login_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_oa_auth_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_credential_login_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_generation_feedback_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_credential_login_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_credential_login_browser_operator_profile.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_same_origin_runtime_boundary.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_playwright_readiness.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_credential_login_playwright_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_post_login_document_workflow_audit.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_source_file_materialization_boundary_audit.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_authenticated_upload_fetch_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_authenticated_upload_playwright_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_uploaded_source_extraction_readiness_audit.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_source_file_reader_fallback_audit.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_uploaded_source_extraction_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_extractor_backend_gap_audit.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_real_document_extraction_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_real_document_processing_pipeline_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_credential_login_browser_execution_readiness.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_credential_login_browser_live_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_credential_login_browser_postgres_evidence_hardening.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_credential_login_browser_smoke_boundary.py --summary
"$PYTHON_BIN" scripts/smoke/run_ae_web_credential_login_browser_harness_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ag_retrieval_package_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ag_retrieval_threshold_decision_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_processing_postgres_jobqueue_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_processing_postgres_event_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_processing_postgres_persistence_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_cx_processing_postgres_api_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ag_cx_processing_run_postgres_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_ag_cross_service_observability_smoke.py --summary
"$PYTHON_BIN" scripts/smoke/run_postgres_test_smoke_suite.py --summary
