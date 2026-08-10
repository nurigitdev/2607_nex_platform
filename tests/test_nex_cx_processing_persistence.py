from __future__ import annotations

from nex_cx.processing_persistence import (
    CX_DOCUMENT_PROCESSING_RUN_TABLE,
    CX_DOCUMENT_PROCESSING_STEP_TABLE,
    CX_PROCESSING_RUNTIME_RECORD_SCHEMA,
    build_processing_run_persistence_decision,
    build_processing_run_persistence_preview,
    find_processing_private_payload_key_paths,
)
from nex_cx.retrieval_persistence import sha256_json, sha256_text


def test_processing_run_persistence_decision_freezes_target_mapping() -> None:
    decision = build_processing_run_persistence_decision()

    assert decision["decision_slice"] == "0181"
    assert decision["decision_status"] == "ag_dashboard_integrated"
    assert decision["runtime_record_schema"] == CX_PROCESSING_RUNTIME_RECORD_SCHEMA
    assert decision["migration_version"] == "0182_cx_processing_run_step_persistence"
    assert decision["adapter_slice"] == "0183"
    assert decision["write_through_slice"] == "0184"
    assert decision["postgres_smoke_slice"] == "0185"
    assert decision["read_model_slice"] == "0186"
    assert decision["service_api_slice"] == "0187"
    assert decision["service_api_postgres_smoke_slice"] == "0188"
    assert decision["operations_projection_contract_slice"] == "0189"
    assert decision["ag_operations_postgres_smoke_slice"] == "0190"
    assert decision["ag_dashboard_integration_slice"] == "0191"
    assert decision["target_tables"] == [
        CX_DOCUMENT_PROCESSING_RUN_TABLE,
        CX_DOCUMENT_PROCESSING_STEP_TABLE,
    ]
    assert decision["unique_keys"][CX_DOCUMENT_PROCESSING_RUN_TABLE] == [
        ["pipeline_run_id"],
        ["document_id", "updated_at", "pipeline_run_id"],
    ]
    assert ["pipeline_run_id", "step_order"] in decision["unique_keys"][
        CX_DOCUMENT_PROCESSING_STEP_TABLE
    ]
    assert "job_status" in decision["run_metadata_fields"]
    assert "error_detail_sha256" in decision["step_metadata_fields"]
    assert "steps[].error.detail" in decision["private_payload_exclusions"]
    assert decision["next_slice"] == "0198_oa_subject_registry_resolver_client"


def test_processing_run_persistence_preview_hashes_private_runtime_detail() -> None:
    output_ref = {
        "type": "cx.summary",
        "id": "summary-001",
        "document_id": "doc-001",
        "text": "SECRET_OUTPUT_REF_TEXT",
    }
    run = {
        "pipeline_schema_version": CX_PROCESSING_RUNTIME_RECORD_SCHEMA,
        "pipeline_run_id": "run-001",
        "document_id": "doc-001",
        "status": "FAILED",
        "trace_id": "trace-001",
        "request_id": "request-001",
        "job": {
            "job_id": "job-001",
            "job_type": "cx.document_processing",
            "status": "FAILED",
            "attempt_count": 2,
            "max_attempts": 3,
            "retryable": True,
            "subject_ref": {"type": "cx.document", "id": "doc-001"},
            "links": {"processing": "/api/v1/documents/doc-001/processing"},
        },
        "steps": [
            {
                "step_id": "summary",
                "status": "FAILED",
                "output_ref": output_ref,
                "error": {
                    "error_code": "cx.summary_failed",
                    "detail": "SECRET_ERROR_DETAIL",
                    "retryable": False,
                },
            }
        ],
        "step_summary": {"total": 1, "succeeded": 0, "skipped": 0, "failed": 1},
        "source_text": "SECRET_SOURCE_TEXT",
        "started_at": "2026-08-09T00:00:00Z",
        "completed_at": "2026-08-09T00:00:05Z",
        "updated_at": "2026-08-09T00:00:05Z",
    }

    preview = build_processing_run_persistence_preview(run)
    header = preview["header"]
    step = preview["steps"][0]

    assert header["target_table"] == CX_DOCUMENT_PROCESSING_RUN_TABLE
    assert header["pipeline_run_id"] == "run-001"
    assert header["job_id"] == "job-001"
    assert header["job_status"] == "FAILED"
    assert header["step_failed"] == 1
    assert step["target_table"] == CX_DOCUMENT_PROCESSING_STEP_TABLE
    assert step["step_order"] == 1
    assert step["output_ref_type"] == "cx.summary"
    assert step["output_ref_id"] == "summary-001"
    assert step["output_ref_hash"] == sha256_json(output_ref)
    assert step["error_code"] == "cx.summary_failed"
    assert step["error_detail_sha256"] == sha256_text("SECRET_ERROR_DETAIL")
    assert step["error_retryable"] is False
    assert preview["private_payload_key_paths"] == [
        "steps[0].output_ref.text",
        "steps[0].error.detail",
        "source_text",
    ]
    assert "SECRET_ERROR_DETAIL" not in str(preview)
    assert "SECRET_OUTPUT_REF_TEXT" not in str(preview)
    assert "SECRET_SOURCE_TEXT" not in str(preview)


def test_processing_run_persistence_preview_handles_sparse_runtime_shape() -> None:
    preview = build_processing_run_persistence_preview(
        {
            "pipeline_run_id": "run-sparse",
            "steps": [
                {
                    "step_id": "queued",
                    "status": "QUEUED",
                    "output_ref": None,
                    "error": {"detail": 123, "retryable": "unknown"},
                },
                "not-a-step-record",
            ],
            "step_summary": {"total": True, "succeeded": "1"},
        }
    )

    header = preview["header"]
    step = preview["steps"][0]

    assert header["step_total"] == 1
    assert header["step_succeeded"] == 0
    assert header["step_skipped"] == 0
    assert header["step_failed"] == 0
    assert step["output_ref_hash"] is None
    assert step["error_detail_sha256"] is None
    assert step["error_retryable"] is None
    assert preview["private_payload_key_paths"] == ["steps[0].error.detail"]


def test_find_processing_private_payload_key_paths_handles_nested_lists() -> None:
    assert find_processing_private_payload_key_paths(
        {
            "safe": "value",
            "items": [
                {"chunk_text": "private"},
                {"nested": {"vector": [0.1, 0.2]}},
            ],
        }
    ) == ["items[0].chunk_text", "items[1].nested.vector"]
    assert find_processing_private_payload_key_paths("plain text") == []
