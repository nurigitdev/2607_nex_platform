from __future__ import annotations

import pytest

from nex_cx.processing_read_model import (
    CX_PROCESSING_RUN_READ_MODEL_SCHEMA_VERSION,
    DEFAULT_PROCESSING_RUN_QUERY_LIMIT,
    MAX_PROCESSING_RUN_QUERY_LIMIT,
    bounded_processing_run_query_limit,
    build_processing_run_query_filters,
    build_processing_run_read_model,
    normalize_processing_run_status,
    project_processing_run_record,
)
from nex_cx.retrieval_persistence import sha256_text


def processing_record(*, status: str = "SUCCEEDED") -> dict[str, object]:
    return {
        "processing_run_schema_version": "cx_document_processing_run.persistence.v1",
        "pipeline_run_id": "99999999-9999-4999-8999-999999999999",
        "pipeline_schema_version": "cx_document_processing_pipeline.v1",
        "document_id": "44444444-4444-4444-8444-444444444444",
        "status": status,
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "request_id": "request-001",
        "job_id": "job-001",
        "job_type": "cx.document_processing",
        "job_status": status,
        "job_attempt_count": 1,
        "job_max_attempts": 3,
        "job_retryable": status != "SUCCEEDED",
        "job_subject_ref": {"type": "cx.document", "id": "doc-secret-safe"},
        "job_links": {"processing": "/api/v1/documents/doc/processing"},
        "step_total": 1,
        "step_succeeded": 1 if status == "SUCCEEDED" else 0,
        "step_skipped": 0,
        "step_failed": 1 if status == "FAILED" else 0,
        "queued_at": None,
        "started_at": "2026-08-09T00:00:00Z",
        "completed_at": "2026-08-09T00:00:05Z",
        "updated_at": "2026-08-09T00:00:05Z",
        "source_text": "SECRET_SOURCE_TEXT",
        "steps": [
            {
                "processing_step_schema_version": (
                    "cx_document_processing_step.persistence.v1"
                ),
                "pipeline_run_id": "99999999-9999-4999-8999-999999999999",
                "step_order": 1,
                "step_id": "summary",
                "status": status,
                "output_ref_type": "cx.document_summary",
                "output_ref_id": "77777777-7777-4777-8777-777777777777",
                "output_ref_document_id": "44444444-4444-4444-8444-444444444444",
                "output_ref_hash": "a" * 64,
                "error_code": "cx.summary_failed" if status == "FAILED" else None,
                "error_detail_sha256": (
                    sha256_text("SECRET_ERROR_DETAIL")
                    if status == "FAILED"
                    else None
                ),
                "error_retryable": False if status == "FAILED" else None,
                "created_at": "2026-08-09T00:00:05Z",
                "error": {"detail": "SECRET_ERROR_DETAIL"},
            }
        ],
    }


def test_processing_run_query_filters_normalize_and_bound_inputs() -> None:
    filters = build_processing_run_query_filters(
        document_id=" doc-001 ",
        status="failed",
        trace_id=" trace-001 ",
        request_id=" request-001 ",
        job_id=" job-001 ",
        limit="999",
        include_steps=False,
    )

    assert filters == {
        "filter_schema_version": "cx_processing_run_query_filters.v1",
        "document_id": "doc-001",
        "status": "FAILED",
        "trace_id": "trace-001",
        "request_id": "request-001",
        "job_id": "job-001",
        "limit": MAX_PROCESSING_RUN_QUERY_LIMIT,
        "include_steps": False,
    }
    assert build_processing_run_query_filters()["limit"] == DEFAULT_PROCESSING_RUN_QUERY_LIMIT
    assert bounded_processing_run_query_limit(0) == 1
    assert bounded_processing_run_query_limit(None) == DEFAULT_PROCESSING_RUN_QUERY_LIMIT
    assert normalize_processing_run_status(None) is None


@pytest.mark.parametrize("bad_status", ["", "done", "SUCCESS", "FAILED " + "x"])
def test_processing_run_query_filters_reject_invalid_status(bad_status: str) -> None:
    if not bad_status:
        assert normalize_processing_run_status(bad_status) is None
        return
    with pytest.raises(ValueError, match="CX processing run status"):
        normalize_processing_run_status(bad_status)


def test_processing_run_query_filters_reject_invalid_limit() -> None:
    with pytest.raises(ValueError, match="limit must be an integer"):
        bounded_processing_run_query_limit("not-an-int")


def test_project_processing_run_record_keeps_safe_metadata_only() -> None:
    projected = project_processing_run_record(processing_record(status="FAILED"))

    assert projected["pipeline_run_id"] == "99999999-9999-4999-8999-999999999999"
    assert projected["status"] == "FAILED"
    assert projected["step_failed"] == 1
    assert projected["steps_included"] is True
    assert projected["steps"][0]["error_code"] == "cx.summary_failed"
    assert projected["steps"][0]["error_detail_sha256"] == sha256_text(
        "SECRET_ERROR_DETAIL"
    )
    assert "SECRET_SOURCE_TEXT" not in str(projected)
    assert "SECRET_ERROR_DETAIL" not in str(projected)


def test_project_processing_run_record_can_omit_steps_for_list_views() -> None:
    projected = project_processing_run_record(
        processing_record(status="SUCCEEDED"),
        include_steps=False,
    )

    assert projected["steps_included"] is False
    assert projected["steps"] == []


def test_project_processing_run_record_handles_sparse_legacy_shapes() -> None:
    projected = project_processing_run_record(
        {
            "pipeline_run_id": "run-sparse",
            "status": "UNKNOWN",
            "job_attempt_count": True,
            "job_max_attempts": "3",
            "job_subject_ref": "not-a-map",
            "job_links": None,
            "steps": "not-a-list",
        }
    )

    assert projected["pipeline_run_id"] == "run-sparse"
    assert projected["status"] == "UNKNOWN"
    assert projected["job_attempt_count"] == 0
    assert projected["job_max_attempts"] == 0
    assert projected["job_subject_ref"] == {}
    assert projected["job_links"] == {}
    assert projected["steps"] == []


def test_build_processing_run_read_model_summarizes_runs_without_private_payloads() -> None:
    filters = build_processing_run_query_filters(status="FAILED", limit=25)
    read_model = build_processing_run_read_model(
        [
            processing_record(status="FAILED"),
            processing_record(status="SUCCEEDED"),
        ],
        filters=filters,
        source_kind="postgres-read",
        database_env="NEX_CX_TEST_DATABASE_URL",
        redacted_database_url="postgresql://nex_cx_user:***@127.0.0.1/nex_cx_test",
    )

    assert read_model["read_model_schema_version"] == (
        CX_PROCESSING_RUN_READ_MODEL_SCHEMA_VERSION
    )
    assert read_model["source"]["source_kind"] == "postgres-read"
    assert read_model["source"]["database_env"] == "NEX_CX_TEST_DATABASE_URL"
    assert read_model["pagination"] == {"limit": 25, "returned": 2}
    assert read_model["summary"]["run_count"] == 2
    assert read_model["summary"]["failed_count"] == 1
    assert read_model["summary"]["status_counts"] == {"SUCCEEDED": 1, "FAILED": 1}
    assert "SECRET_SOURCE_TEXT" not in str(read_model)
    assert "SECRET_ERROR_DETAIL" not in str(read_model)


def test_build_processing_run_read_model_handles_minimal_filters_and_unknown_status() -> None:
    read_model = build_processing_run_read_model(
        [project_processing_run_record({"pipeline_run_id": "run-001", "status": "UNKNOWN"})],
        filters={"limit": 0, "include_steps": False},
        source_kind="memory",
    )

    assert read_model["filters"] == {
        "filter_schema_version": "cx_processing_run_query_filters.v1",
        "document_id": None,
        "status": None,
        "trace_id": None,
        "request_id": None,
        "job_id": None,
        "include_steps": False,
    }
    assert read_model["pagination"] == {"limit": 1, "returned": 1}
    assert read_model["summary"]["status_counts"] == {}
    assert read_model["runs"][0]["steps_included"] is False
