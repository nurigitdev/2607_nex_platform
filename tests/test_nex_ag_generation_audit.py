from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

import nex_ag.generation_audit as ag_audit
from nex_ag.generation_audit import (
    GenerationAuditError,
    HttpGenerationAuditSourceClient,
    audit_action_type,
    artifact_handoff_summary,
    build_ag_generation_audit_event,
    build_generation_audit_projection,
    build_grounded_response_quality_gap_audit,
    failure_summary,
    grounded_response_quality_projection,
    project_timeline_events,
    register_generation_audit_routes,
    recovery_request_summary,
    safe_details,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
CONTRACTS_ROOT = Path(__file__).resolve().parents[1] / "contracts"


class FakeGenerationAuditSourceClient:
    def __init__(
        self,
        *,
        generation_record: dict[str, Any] | None = None,
        progress_payload: dict[str, Any] | None = None,
        artifact_handoff: dict[str, Any] | None = None,
        recovery_request: dict[str, Any] | None = None,
        error: GenerationAuditError | None = None,
    ) -> None:
        self.generation_record = generation_record or sample_generation_record()
        self.progress_payload = progress_payload or sample_progress_payload()
        self.artifact_handoff = artifact_handoff or sample_artifact_handoff()
        self.recovery_request = recovery_request or sample_recovery_request()
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def get_cx_generation(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("generation", cx_generation_id))
        if self.error is not None:
            raise self.error
        return self.generation_record

    def get_cx_generation_events(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("events", cx_generation_id))
        return self.progress_payload

    def get_ae_artifact_handoff(
        self,
        artifact_handoff_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("handoff", artifact_handoff_id))
        return self.artifact_handoff

    def get_ae_recovery_request(
        self,
        recovery_request_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("recovery", recovery_request_id))
        return self.recovery_request


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def sample_generation_record(*, status: str = "COMPLETED") -> dict[str, Any]:
    return {
        "cx_generation_id": "cx-gen-001",
        "status": status,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "mo_generation_id": "mo-gen-001",
        "request_metadata": {
            "compatibility_rule_id": "compat-grounded-answer-v1",
            "provider_prompt_package_hash": "a" * 64,
            "generation_request_hash": "b" * 64,
            "grounding_required": True,
            "retrieval_package_id": "cx-ret-001",
            "retrieval_package_hash": "d" * 64,
            "selected_evidence_count": 2,
            "structured_draft_id": "draft-001",
            "draft_validation_status": "VALIDATED",
            "grounded_response_quality_audit_schema_version": (
                "cx_grounded_response_citation_quality_audit.v1"
            ),
            "grounded_response_quality_status": "PASS",
            "grounded_response_quality_issue_count": 0,
        },
        "response_metadata": {
            "finish_reason": "STOP",
            "output_hash": "c" * 64,
            "output_preview": "Safe preview.",
        },
        "mo_runtime_metadata": {
            "route_id": "route-general-llm-default",
            "provider_request_id": "provider-001",
            "provider_url": "http://should-not-leak.local",
            "total_ms": 12,
        },
        "usage": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
    }


def sample_failed_generation_record() -> dict[str, Any]:
    return {
        **sample_generation_record(status="FAILED"),
        "mo_generation_id": None,
        "response_metadata": {
            "finish_reason": "ERROR",
            "output_hash": None,
            "output_preview": "",
        },
        "failure": {
            "failure_code": "mo.provider_timeout",
            "failure_class": "provider_timeout",
            "owner_service": "nex-cx",
            "failed_stage": "GENERATING",
            "retryable": True,
            "recovery_policy_id": "recovery-mo-provider-timeout-retry-v1",
            "recovery_policy_hash": "e" * 64,
            "safe_message": "Generation failed before completion.",
            "raw_prompt": "private prompt",
        },
    }


def sample_progress_payload() -> dict[str, Any]:
    return {
        "events": [
            {
                "event_id": "event-001",
                "event_schema_version": "generation_progress_event.v1",
                "event_type": "generation.prompt.packaged",
                "event_source_service": "nex-cx",
                "trace_id": TRACE_ID,
                "request_id": REQUEST_ID,
                "occurred_at": "2026-08-02T00:00:00Z",
                "sequence_no": 1,
                "job_status": "RUNNING",
                "current_stage": "PROMPT_ASSEMBLING",
                "progress_mode": "INDETERMINATE",
                "message_key": "generation.progress.prompt_packaged",
                "safe_message": "Prompt package assembled.",
                "retryable": False,
                "details": {
                    "generation_request_hash": "b" * 64,
                    "raw_prompt": "private prompt",
                    "nested": {"storage_path": "/tmp/private", "ok": True},
                },
                "provider_url": "http://should-not-leak.local",
            }
        ]
    }


def sample_artifact_handoff() -> dict[str, Any]:
    return {
        "handoff_schema_version": "ae_artifact_handoff.v1",
        "artifact_handoff_id": "handoff-001",
        "handoff_status": "READY_FOR_RENDERING",
        "artifact_intent": "create_artifact",
        "target_formats": ["MD", "HTML_PREVIEW"],
        "artifact_title": "Generated report",
        "structured_draft_id": "draft-001",
        "structured_draft_content_hash": "c" * 64,
        "actor_claims_ref": {
            "actor_type": "user",
            "actor_id": "user-001",
            "tenant_id": "tenant-001",
        },
        "quality_summary": {
            "citation_status": "VALIDATED",
            "citation_count": 2,
            "validation_error_count": 0,
            "warning_count": 0,
            "grounding_required": True,
            "retrieval_package_id": "cx-ret-001",
            "retrieval_package_hash": "d" * 64,
            "evidence_ref_count": 2,
        },
    }


def sample_recovery_request(
    *,
    requested_action: str = "retry",
) -> dict[str, Any]:
    return {
        "recovery_request_id": "ae-recovery-001",
        "status": "ACCEPTED",
        "requested_action": requested_action,
        "cx_generation_id": "cx-gen-001",
        "parent_generation_id": "cx-gen-001",
        "failure": {
            "failure_code": "mo.provider_timeout",
            "failure_class": "provider_timeout",
        },
        "policy": {
            "hash_status": "MATCHED",
        },
        "dispatch": {
            "target_service": "nex-cx",
            "endpoint_hint": "/api/v1/generations",
            "attempt_no": 2,
            "reuse_retrieval_package": True,
            "requires_user_confirmation": False,
        },
    }


def build_client(
    source_client: FakeGenerationAuditSourceClient | None = None,
) -> tuple[TestClient, FakeGenerationAuditSourceClient]:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    client = source_client or FakeGenerationAuditSourceClient()
    register_generation_audit_routes(app, source_client=client)
    return TestClient(app), client


def ag_grounded_response_quality_projection_schema() -> dict[str, Any]:
    return json.loads(
        (
            CONTRACTS_ROOT
            / "schemas/generation/ag_generation_audit_grounded_response_quality_projection.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def test_build_generation_audit_projection_reads_services_and_redacts_timeline() -> (
    None
):
    source_client = FakeGenerationAuditSourceClient()

    projection = build_generation_audit_projection(
        source_client,
        cx_generation_id="cx-gen-001",
        artifact_handoff_id="handoff-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert source_client.calls == [
        ("generation", "cx-gen-001"),
        ("events", "cx-gen-001"),
        ("handoff", "handoff-001"),
    ]
    assert (
        projection["projection_schema_version"] == "ag_generation_audit_projection.v1"
    )
    assert projection["audit_event"]["event_schema_version"] == (
        "ag_generation_audit_event.v1"
    )
    assert projection["audit_event"]["actor_ref"]["actor_id"] == "user-001"
    assert projection["generation_summary"]["output_hash"] == "c" * 64
    assert projection["artifact_handoff_summary"]["target_formats"] == [
        "MD",
        "HTML_PREVIEW",
    ]
    assert projection["grounded_response_quality"] == {
        "projection_schema_version": (
            "ag_generation_audit_grounded_response_quality_projection.v1"
        ),
        "gap_audit_schema_version": (
            "ag_generation_audit_grounded_response_quality_gap_audit.v1"
        ),
        "source_audit_schema_version": (
            "cx_grounded_response_citation_quality_audit.v1"
        ),
        "coverage_status": "PASS",
        "boundary_status": "PASS",
        "grounding_required": True,
        "citation_status": "VALIDATED",
        "source_quality_issue_count": 0,
        "projection_issue_count": 0,
        "issue_codes": [],
        "lineage_mismatches": [],
        "recommended_action": "wire_ag_quality_projection",
        "retrieval_package_id": "cx-ret-001",
        "retrieval_package_hash": "d" * 64,
        "structured_draft_id": "draft-001",
        "evidence_ref_count": 2,
        "artifact_handoff_quality_available": True,
        "raw_content_included": False,
        "prompt_text_included": False,
        "evidence_text_included": False,
        "provider_detail_included": False,
    }
    assert "private prompt" not in str(projection)
    assert "should-not-leak" not in str(projection)
    assert "/tmp/private" not in str(projection)


def test_build_generation_audit_projection_can_omit_artifact_handoff() -> None:
    source_client = FakeGenerationAuditSourceClient(artifact_handoff=None)

    projection = build_generation_audit_projection(
        source_client,
        cx_generation_id="cx-gen-001",
        artifact_handoff_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert source_client.calls == [
        ("generation", "cx-gen-001"),
        ("events", "cx-gen-001"),
    ]
    assert projection["artifact_handoff_summary"] is None
    assert projection["recovery_request_summary"] is None
    assert (
        projection["grounded_response_quality"]["artifact_handoff_quality_available"]
        is False
    )
    assert projection["grounded_response_quality"]["coverage_status"] == "PASS"
    assert projection["audit_event"]["actor_ref"]["actor_type"] == "service"


def test_generation_audit_projection_can_include_recovery_request() -> None:
    source_client = FakeGenerationAuditSourceClient(
        generation_record=sample_failed_generation_record(),
        recovery_request=sample_recovery_request(),
    )

    projection = build_generation_audit_projection(
        source_client,
        cx_generation_id="cx-gen-001",
        artifact_handoff_id=None,
        recovery_request_id="ae-recovery-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert source_client.calls == [
        ("generation", "cx-gen-001"),
        ("events", "cx-gen-001"),
        ("recovery", "ae-recovery-001"),
    ]
    assert projection["generation_summary"]["failure"] == {
        "failure_code": "mo.provider_timeout",
        "failure_class": "provider_timeout",
        "owner_service": "nex-cx",
        "failed_stage": "GENERATING",
        "retryable": True,
        "recovery_policy_id": "recovery-mo-provider-timeout-retry-v1",
        "recovery_policy_hash": "e" * 64,
    }
    assert projection["recovery_request_summary"]["requested_action"] == "retry"
    assert projection["audit_event"]["action_type"] == "retry"
    assert projection["audit_event"]["details"]["recovery_request_id"] == (
        "ae-recovery-001"
    )
    assert "private prompt" not in str(projection)


def test_generation_audit_event_marks_failed_generation() -> None:
    event = build_ag_generation_audit_event(
        generation_record=sample_generation_record(status="FAILED"),
        artifact_handoff=None,
        timeline_events=[],
        occurred_at="2026-08-02T00:00:00Z",
    )

    assert event["result_status"] == "FAILED"
    assert event["target_ref"]["target_id"] == "cx-gen-001"
    assert event["details"]["timeline_event_count"] == 0


def test_grounded_response_quality_gap_audit_reports_complete_safe_sources() -> None:
    generation_record = sample_generation_record()
    generation_record["request_metadata"]["raw_prompt"] = "private prompt"
    artifact_handoff = sample_artifact_handoff()
    artifact_handoff["quality_summary"]["source_text"] = "private evidence text"

    audit = build_grounded_response_quality_gap_audit(
        generation_record,
        artifact_handoff,
    )

    assert audit["audit_schema_version"] == (
        "ag_generation_audit_grounded_response_quality_gap_audit.v1"
    )
    assert audit["coverage_status"] == "PASS"
    assert audit["source_quality_status"] == "PASS"
    assert audit["issue_count"] == 0
    assert audit["source_summaries"]["cx_generation"]["audit_schema_version"] == (
        "cx_grounded_response_citation_quality_audit.v1"
    )
    assert audit["source_summaries"]["ae_artifact_handoff"]["citation_status"] == (
        "VALIDATED"
    )
    assert audit["recommended_action"] == "wire_ag_quality_projection"
    assert audit["redaction_summary"]["raw_content_included"] is False
    assert "private prompt" not in str(audit)
    assert "private evidence text" not in str(audit)


def test_grounded_response_quality_gap_audit_flags_missing_cx_metadata() -> None:
    generation_record = sample_generation_record()
    for field in (
        "grounded_response_quality_audit_schema_version",
        "grounded_response_quality_status",
        "grounded_response_quality_issue_count",
    ):
        del generation_record["request_metadata"][field]

    audit = build_grounded_response_quality_gap_audit(generation_record)

    assert audit["coverage_status"] == "WARN"
    assert audit["source_quality_status"] == "UNKNOWN"
    assert audit["recommended_action"] == "complete_source_quality_metadata"
    assert audit["source_summaries"]["ae_artifact_handoff"] == {
        "available": False,
        "required": False,
        "missing_fields": [],
    }
    assert audit["issues"] == [
        {
            "code": "MISSING_CX_GROUNDED_RESPONSE_QUALITY_FIELDS",
            "severity": "WARN",
            "source_service": "nex-cx",
            "fields": [
                "grounded_response_quality_audit_schema_version",
                "grounded_response_quality_status",
                "grounded_response_quality_issue_count",
            ],
        }
    ]


def test_grounded_response_quality_gap_audit_handles_not_required_generation() -> None:
    generation_record = sample_generation_record()
    generation_record["request_metadata"] = {
        "grounding_required": False,
        "raw_output": "private output",
    }

    audit = build_grounded_response_quality_gap_audit(generation_record)

    assert audit["coverage_status"] == "NOT_REQUIRED"
    assert audit["source_quality_status"] == "NOT_REQUIRED"
    assert audit["issues"] == []
    assert audit["recommended_action"] == "no_action"
    assert "private output" not in str(audit)


def test_grounded_response_quality_gap_audit_keeps_failure_signal_first() -> None:
    generation_record = sample_generation_record()
    generation_record["request_metadata"]["grounding_required"] = False
    generation_record["request_metadata"]["grounded_response_quality_status"] = "FAIL"
    generation_record["request_metadata"]["grounded_response_quality_issue_count"] = 1

    audit = build_grounded_response_quality_gap_audit(generation_record)

    assert audit["coverage_status"] == "FAIL"
    assert audit["source_quality_status"] == "FAIL"
    assert audit["recommended_action"] == "investigate_quality_failure"


def test_grounded_response_quality_gap_audit_flags_failure_and_handoff_gaps() -> None:
    generation_record = sample_generation_record()
    generation_record["request_metadata"]["grounded_response_quality_status"] = "FAIL"
    generation_record["request_metadata"][
        "grounded_response_quality_issue_count"
    ] = True
    generation_record["request_metadata"]["selected_evidence_count"] = True
    artifact_handoff = sample_artifact_handoff()
    artifact_handoff["structured_draft_id"] = "draft-mismatch"
    artifact_handoff["quality_summary"] = {
        "citation_status": "VALIDATED",
        "grounding_required": True,
        "retrieval_package_id": "cx-ret-mismatch",
        "evidence_ref_count": True,
    }

    audit = build_grounded_response_quality_gap_audit(
        generation_record,
        artifact_handoff,
    )

    assert audit["coverage_status"] == "FAIL"
    assert audit["recommended_action"] == "investigate_quality_failure"
    assert audit["source_summaries"]["cx_generation"]["issue_count"] is None
    assert (
        audit["source_summaries"]["ae_artifact_handoff"]["evidence_ref_count"] is None
    )
    assert audit["lineage_mismatches"] == [
        "retrieval_package_id",
        "structured_draft_id",
    ]
    assert [issue["code"] for issue in audit["issues"]] == [
        "MISSING_AE_ARTIFACT_QUALITY_SUMMARY_FIELDS",
        "GROUNDED_RESPONSE_QUALITY_LINEAGE_MISMATCH",
        "CX_GROUNDED_RESPONSE_QUALITY_FAILED",
    ]


def test_grounded_response_quality_gap_audit_handles_malformed_handoff_quality() -> (
    None
):
    generation_record = sample_generation_record()
    generation_record["request_metadata"]["grounded_response_quality_status"] = " "
    artifact_handoff = sample_artifact_handoff()
    artifact_handoff["quality_summary"] = "bad"

    audit = build_grounded_response_quality_gap_audit(
        generation_record,
        artifact_handoff,
    )

    assert audit["coverage_status"] == "WARN"
    assert audit["source_quality_status"] == "UNKNOWN"
    assert audit["source_summaries"]["ae_artifact_handoff"]["available"] is False
    assert audit["source_summaries"]["ae_artifact_handoff"]["missing_fields"] == [
        "citation_status",
        "grounding_required",
        "retrieval_package_id",
        "retrieval_package_hash",
        "evidence_ref_count",
    ]


def test_grounded_response_quality_projection_compacts_gap_audit_safely() -> None:
    generation_record = sample_generation_record()
    artifact_handoff = sample_artifact_handoff()
    artifact_handoff["structured_draft_id"] = "draft-mismatch"
    artifact_handoff["quality_summary"]["retrieval_package_hash"] = "e" * 64
    artifact_handoff["quality_summary"]["raw_output"] = "private output"
    gap_audit = build_grounded_response_quality_gap_audit(
        generation_record,
        artifact_handoff,
    )

    projection = grounded_response_quality_projection(gap_audit)

    assert projection["projection_schema_version"] == (
        "ag_generation_audit_grounded_response_quality_projection.v1"
    )
    assert projection["coverage_status"] == "WARN"
    assert projection["boundary_status"] == "PASS"
    assert projection["source_quality_issue_count"] == 0
    assert projection["projection_issue_count"] == 1
    assert projection["issue_codes"] == ["GROUNDED_RESPONSE_QUALITY_LINEAGE_MISMATCH"]
    assert projection["lineage_mismatches"] == [
        "retrieval_package_hash",
        "structured_draft_id",
    ]
    assert projection["retrieval_package_hash"] == "d" * 64
    assert projection["artifact_handoff_quality_available"] is True
    assert projection["raw_content_included"] is False
    assert "private output" not in str(projection)


def test_grounded_response_quality_projection_matches_contract_schema() -> None:
    gap_audit = build_grounded_response_quality_gap_audit(
        sample_generation_record(),
        sample_artifact_handoff(),
    )
    projection = grounded_response_quality_projection(gap_audit)

    Draft202012Validator(ag_grounded_response_quality_projection_schema()).validate(
        projection
    )


def test_grounded_response_quality_projection_handles_sparse_gap_audit() -> None:
    projection = grounded_response_quality_projection(
        {
            "issues": [
                {"code": "SAFE_CODE"},
                {"code": 3},
                "bad",
            ],
            "lineage_mismatches": ["retrieval_package_id", 4],
            "issue_count": "bad",
        }
    )

    assert projection["coverage_status"] == "UNKNOWN"
    assert projection["boundary_status"] == "UNKNOWN"
    assert projection["source_quality_issue_count"] is None
    assert projection["projection_issue_count"] == 0
    assert projection["issue_codes"] == ["SAFE_CODE"]
    assert projection["lineage_mismatches"] == ["retrieval_package_id"]
    assert projection["citation_status"] is None


def test_project_timeline_events_handles_invalid_shape_and_safe_details() -> None:
    assert project_timeline_events({"events": "bad"}) == []
    assert project_timeline_events({"events": ["bad"]}) == []
    assert project_timeline_events(sample_progress_payload())[0]["details"] == {
        "generation_request_hash": "b" * 64,
        "nested": {"ok": True},
    }
    assert artifact_handoff_summary(None) is None
    assert recovery_request_summary(None) is None
    assert failure_summary({"status": "COMPLETED"}) is None
    assert safe_details({"api_key": "hidden", "safe": object()})["safe"].startswith(
        "<object object"
    )


def test_recovery_summary_and_action_type_helpers_map_safe_fields() -> None:
    summary = recovery_request_summary(sample_recovery_request())

    assert summary == {
        "recovery_request_id": "ae-recovery-001",
        "status": "ACCEPTED",
        "requested_action": "retry",
        "cx_generation_id": "cx-gen-001",
        "parent_generation_id": "cx-gen-001",
        "failure_code": "mo.provider_timeout",
        "failure_class": "provider_timeout",
        "policy_hash_status": "MATCHED",
        "target_service": "nex-cx",
        "endpoint_hint": "/api/v1/generations",
        "attempt_no": 2,
        "reuse_retrieval_package": True,
        "requires_user_confirmation": False,
    }
    assert audit_action_type(None) == "generation_run"
    assert (
        audit_action_type(sample_recovery_request(requested_action="repair"))
        == "repair"
    )
    assert (
        audit_action_type(sample_recovery_request(requested_action="sectional_retry"))
        == "repair"
    )
    assert (
        audit_action_type(
            sample_recovery_request(requested_action="manual_accept_with_warning")
        )
        == "override"
    )
    assert (
        audit_action_type(sample_recovery_request(requested_action="regenerate"))
        == "retry"
    )
    assert (
        audit_action_type(sample_recovery_request(requested_action="cancel"))
        == "override"
    )


def test_generation_audit_route_requires_auth_and_returns_projection() -> None:
    client, source_client = build_client()

    unauthorized = client.get("/admin/v1/generation-audit/generations/cx-gen-001")
    response = client.get(
        "/admin/v1/generation-audit/generations/cx-gen-001",
        params={
            "artifact_handoff_id": "handoff-001",
            "recovery_request_id": "ae-recovery-001",
        },
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json()["cx_generation_id"] == "cx-gen-001"
    assert source_client.calls[-2:] == [
        ("handoff", "handoff-001"),
        ("recovery", "ae-recovery-001"),
    ]


def test_generation_quality_issue_detail_route_returns_operator_runbook() -> None:
    generation_record = sample_generation_record()
    for field in (
        "grounded_response_quality_audit_schema_version",
        "grounded_response_quality_status",
        "grounded_response_quality_issue_count",
    ):
        del generation_record["request_metadata"][field]
    client, source_client = build_client(
        FakeGenerationAuditSourceClient(generation_record=generation_record)
    )

    unauthorized = client.get(
        "/admin/v1/generation-audit/generations/cx-gen-001/quality-issue-detail"
    )
    response = client.get(
        "/admin/v1/generation-audit/generations/cx-gen-001/quality-issue-detail",
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == (
        "ag_generation_quality_issue_detail_projection.v1"
    )
    assert payload["projection_status"] == "READY"
    assert payload["attention_required"] is True
    assert payload["severity"] == "WARNING"
    assert payload["quality"]["coverage_status"] == "WARN"
    assert payload["quality"]["issue_codes"] == [
        "MISSING_CX_GROUNDED_RESPONSE_QUALITY_FIELDS"
    ]
    assert payload["quality"]["boundary_status"] == "UNKNOWN"
    assert payload["runbook"] == {
        "runbook_id": "ag.generation_quality.metadata_gap_triage.v1",
        "recommended_operator_action": "restore_missing_quality_metadata",
        "operator_steps": [
            "open_generation_audit_detail",
            "verify_cx_grounded_response_quality_metadata",
            "verify_ae_artifact_handoff_quality_summary",
        ],
    }
    assert payload["debug_paths"] == {
        "generation_audit_detail_path": (
            "/admin/v1/generation-audit/generations/cx-gen-001"
        ),
        "operations_dashboard_path": "/admin/v1/operations/dashboard",
        "retrieval_package_detail_path": (
            "/admin/v1/operations/retrieval-packages/cx-ret-001"
        ),
    }
    assert payload["request_trace_id"] == TRACE_ID
    assert "private prompt" not in str(payload)
    assert source_client.calls == [
        ("generation", "cx-gen-001"),
        ("events", "cx-gen-001"),
    ]


def test_generation_quality_issue_detail_route_maps_source_errors() -> None:
    error = GenerationAuditError(
        status_code=404,
        error_code="cx.generation_not_found",
        detail="Generation not found.",
        retryable=False,
    )
    client, _ = build_client(FakeGenerationAuditSourceClient(error=error))

    response = client.get(
        "/admin/v1/generation-audit/generations/cx-gen-missing/quality-issue-detail",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "cx.generation_not_found"
    assert response.json()["retryable"] is False


def test_generation_audit_route_maps_source_errors() -> None:
    error = GenerationAuditError(
        status_code=503,
        error_code="cx.down",
        detail="CX unavailable.",
        retryable=True,
    )
    client, _ = build_client(FakeGenerationAuditSourceClient(error=error))

    response = client.get(
        "/admin/v1/generation-audit/generations/cx-gen-001",
        headers=auth_headers(),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "cx.down"
    assert response.json()["retryable"] is True


def test_http_generation_audit_source_client_reads_cx_and_ae(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    def fake_get(
        url: str, *, headers: dict[str, str], timeout: float
    ) -> httpx.Response:
        seen.append((url, headers["X-Service-ID"]))
        if url.endswith("/events"):
            return httpx.Response(status_code=200, json={"events": []})
        if "artifact-handoffs" in url:
            return httpx.Response(
                status_code=200, json={"artifact_handoff_id": "handoff-001"}
            )
        if "generation-requests" in url:
            return httpx.Response(
                status_code=200, json={"recovery_request_id": "ae-rec-001"}
            )
        return httpx.Response(status_code=200, json={"cx_generation_id": "cx-gen-001"})

    monkeypatch.setattr(ag_audit.httpx, "get", fake_get)
    client = HttpGenerationAuditSourceClient(
        cx_base_url="http://cx.test",
        ae_base_url="http://ae.test",
    )

    assert client.get_cx_generation(
        "cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    ) == {"cx_generation_id": "cx-gen-001"}
    assert client.get_cx_generation_events(
        "cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    ) == {"events": []}
    assert client.get_ae_artifact_handoff(
        "handoff-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    ) == {"artifact_handoff_id": "handoff-001"}
    assert client.get_ae_recovery_request(
        "ae-rec-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    ) == {"recovery_request_id": "ae-rec-001"}
    assert seen == [
        ("http://cx.test/api/v1/generations/cx-gen-001", "nex-ag"),
        ("http://cx.test/api/v1/generations/cx-gen-001/events", "nex-ag"),
        ("http://ae.test/api/v1/artifact-handoffs/handoff-001", "nex-ag"),
        ("http://ae.test/api/v1/recovery/generation-requests/ae-rec-001", "nex-ag"),
    ]


def test_http_generation_audit_source_client_maps_error_and_bad_json(
    monkeypatch,
) -> None:
    def source_error(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            status_code=404,
            json={"error_code": "cx.missing", "detail": "Missing generation."},
        )

    monkeypatch.setattr(ag_audit.httpx, "get", source_error)
    with pytest.raises(GenerationAuditError) as exc_info:
        HttpGenerationAuditSourceClient(cx_base_url="http://cx.test").get_cx_generation(
            "cx-gen-001",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert exc_info.value.error_code == "cx.missing"

    def bad_json(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(status_code=500, content=b"broken")

    monkeypatch.setattr(ag_audit.httpx, "get", bad_json)
    with pytest.raises(GenerationAuditError) as fallback_exc:
        HttpGenerationAuditSourceClient(
            cx_base_url="http://cx.test"
        ).get_cx_generation_events(
            "cx-gen-001",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert fallback_exc.value.error_code == "ag.audit_source_request_failed"
