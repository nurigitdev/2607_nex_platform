from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from nex_ae_api.repaired_response_client import (
    AE_CX_REPAIRED_RESPONSE_SOURCE_PACKAGE_SCHEMA_VERSION,
    AE_CX_REPAIRED_RESPONSE_TIMEOUT_ENV,
    CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION,
    CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION,
    CxRepairedResponseSourceClientError,
    HttpCxRepairedResponseSourceClient,
    assert_cx_repaired_response_source_material_safe,
    build_default_cx_repaired_response_source_client,
    build_repaired_response_handoff_from_source_package,
    build_repaired_response_source_package,
    find_sensitive_cx_repaired_response_source_material_keys,
    sanitized_cx_generation_record,
    sanitized_cx_remediation_detail,
    validate_repaired_response_source_package,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def source_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "tenant_id": "tenant-001",
        "workspace_id": "workspace-001",
        "owner_user_id": "user-001",
        "chat_document_id": "chat-doc-001",
        "interaction_id": "interaction-001",
        "original_cx_generation_id": "cx-gen-001",
        "remediation_action_id": "ag-remediation-action-001",
        "actor_claims_ref": {
            "actor_type": "user",
            "actor_id": "user-001",
            "tenant_id": "tenant-001",
        },
    }
    payload.update(overrides)
    return payload


def cx_remediation_detail(**overrides: Any) -> dict[str, Any]:
    lineage = {
        "lineage_schema_version": "cx_repaired_generation_lineage.v1",
        "lineage_status": "LINKED",
        "parent_cx_generation_id": "cx-gen-001",
        "root_cx_generation_id": "cx-gen-001",
        "repair_cx_generation_id": "cx-gen-repair-001",
        "remediation_action_id": "ag-remediation-action-001",
        "action_type": "citation_repair",
        "lineage_type": "repair",
        "execution_status": "SUCCEEDED",
        "attempt_no": 1,
        "result_ref": {
            "source_service": "nex-cx",
            "ref_type": "repair_execution",
            "ref_id": "ag-remediation-action-001",
            "relation": "result_of",
        },
        "diagnostics": {
            "lineage_consistent": True,
            "repair_generation_linked": True,
            "result_ref_present": True,
            "result_ref_matches_remediation_action": True,
            "parent_generation_mutated": False,
        },
        "debug_paths": {
            "parent_generation_path": "/api/v1/generations/cx-gen-001",
            "root_generation_path": "/api/v1/generations/cx-gen-001",
            "repair_generation_path": "/api/v1/generations/cx-gen-repair-001",
            "cx_remediation_execution_path": (
                "/api/v1/generations/cx-gen-001/remediation-executions/"
                "ag-remediation-action-001"
            ),
        },
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
    }
    detail = {
        "detail_schema_version": CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION,
        "projection_status": "READY",
        "checked_at": "2026-08-27T00:00:00Z",
        "parent_cx_generation_id": "cx-gen-001",
        "remediation_action_id": "ag-remediation-action-001",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "execution_status": "SUCCEEDED",
        "execution": {
            "result_schema_version": "cx_remediation_execution_result.v1",
            "remediation_action_id": "ag-remediation-action-001",
            "parent_cx_generation_id": "cx-gen-001",
            "repair_cx_generation_id": "cx-gen-repair-001",
            "execution_status": "SUCCEEDED",
        },
        "repaired_generation_lineage": lineage,
        "attention_required": False,
        "debug_paths": {},
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
    }
    detail.update(overrides)
    return detail


def repaired_generation_record(**overrides: Any) -> dict[str, Any]:
    record = {
        "record_schema_version": CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION,
        "cx_generation_id": "cx-gen-repair-001",
        "status": "COMPLETED",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "mo_generation_id": "mo-gen-repair-001",
        "request_metadata": {
            "provider_prompt_package_hash": "a" * 64,
            "generation_request_hash": "b" * 64,
            "source_has_messages": True,
            "source_has_prompt": False,
            "grounding_required": True,
            "retrieval_package_id": "cx-ret-001",
            "retrieval_package_hash": "d" * 64,
            "selected_evidence_count": 2,
            "structured_draft_id": "draft-repair-001",
            "draft_validation_status": "VALIDATED",
            "grounded_response_quality_status": "PASS",
            "grounded_response_quality_issue_count": 0,
        },
        "response_metadata": {
            "finish_reason": "STOP",
            "output_hash": "c" * 64,
            "output_preview": "Repaired answer with citation support.",
        },
        "usage": {
            "input_tokens": 12,
            "output_tokens": 16,
            "total_tokens": 28,
        },
        "created_at": "2026-08-27T00:00:00Z",
        "updated_at": "2026-08-27T00:00:00Z",
    }
    record.update(overrides)
    return record


class FakeCxRepairedResponseSourceClient:
    def __init__(
        self,
        *,
        detail: dict[str, Any] | None = None,
        generation: dict[str, Any] | None = None,
    ) -> None:
        self.detail = detail or cx_remediation_detail()
        self.generation = generation or repaired_generation_record()
        self.calls: list[dict[str, Any]] = []

    def get_remediation_execution_detail(
        self,
        *,
        parent_cx_generation_id: str,
        remediation_action_id: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": "detail",
                "parent_cx_generation_id": parent_cx_generation_id,
                "remediation_action_id": remediation_action_id,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        return self.detail

    def get_repaired_generation_record(
        self,
        *,
        cx_generation_id: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": "generation",
                "cx_generation_id": cx_generation_id,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        return self.generation


def test_http_cx_repaired_response_client_gets_detail_and_generation() -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        if "/remediation-executions/" in url:
            return httpx.Response(200, json=cx_remediation_detail())
        return httpx.Response(200, json=repaired_generation_record())

    client = HttpCxRepairedResponseSourceClient(
        base_url="http://cx.local/",
        service_token="cx-token",
        timeout_seconds=12.5,
        requester=fake_request,
    )

    detail = client.get_remediation_execution_detail(
        parent_cx_generation_id="cx-gen/001",
        remediation_action_id="ag-remediation-action-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    generation = client.get_repaired_generation_record(
        cx_generation_id="cx-gen-repair-001",
    )

    assert detail["detail_schema_version"] == CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION
    assert generation["record_schema_version"] == CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == (
        "http://cx.local/api/v1/generations/cx-gen%2F001/"
        "remediation-executions/ag-remediation-action-001"
    )
    assert calls[0]["headers"] == {
        "Authorization": "Bearer cx-token",
        "X-Request-ID": REQUEST_ID,
        "X-Service-ID": "nex-ae-api",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }
    assert calls[0]["timeout"] == 12.5
    assert calls[1]["url"] == (
        "http://cx.local/api/v1/generations/cx-gen-repair-001"
    )
    assert calls[1]["headers"]["X-Request-ID"] == (
        "ae-cx-repaired-generation:cx-gen-repair-001"
    )
    assert "traceparent" not in calls[1]["headers"]


def test_http_cx_repaired_response_client_maps_failures() -> None:
    assert str(
        CxRepairedResponseSourceClientError(
            status_code=503,
            error_code="example",
            detail="example detail",
        )
    ) == "example detail"

    def problem_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "error_code": "cx.remediation_execution_not_found",
                "detail": "missing",
                "retryable": False,
            },
        )

    problem_client = HttpCxRepairedResponseSourceClient(
        base_url="http://cx.local",
        requester=problem_request,
    )
    with pytest.raises(CxRepairedResponseSourceClientError) as problem:
        problem_client.get_remediation_execution_detail(
            parent_cx_generation_id="cx-gen-001",
            remediation_action_id="ag-remediation-action-001",
        )

    assert problem.value.status_code == 404
    assert problem.value.error_code == "cx.remediation_execution_not_found"
    assert problem.value.retryable is False

    def timeout_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    timeout_client = HttpCxRepairedResponseSourceClient(
        base_url="http://cx.local",
        requester=timeout_request,
    )
    with pytest.raises(CxRepairedResponseSourceClientError) as timeout:
        timeout_client.get_repaired_generation_record(cx_generation_id="cx-gen-001")

    assert timeout.value.status_code == 504
    assert timeout.value.retryable is True

    def down_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("down")

    down_client = HttpCxRepairedResponseSourceClient(
        base_url="http://cx.local",
        requester=down_request,
    )
    with pytest.raises(CxRepairedResponseSourceClientError) as down:
        down_client.get_remediation_execution_detail(
            parent_cx_generation_id="cx-gen-001",
            remediation_action_id="ag-remediation-action-001",
        )

    assert down.value.status_code == 503
    assert down.value.retryable is True


@pytest.mark.parametrize(
    ("response", "method_name", "error_code"),
    [
        (
            httpx.Response(200, content=b"{not-json"),
            "get_remediation_execution_detail",
            "ae.cx_repaired_response_source_response_invalid",
        ),
        (
            httpx.Response(200, json=["not", "object"]),
            "get_remediation_execution_detail",
            "ae.cx_repaired_response_source_response_invalid",
        ),
        (
            httpx.Response(200, json={"detail_schema_version": "old"}),
            "get_remediation_execution_detail",
            "ae.cx_repaired_response_source_response_invalid",
        ),
        (
            httpx.Response(200, json={"record_schema_version": "old"}),
            "get_repaired_generation_record",
            "ae.cx_repaired_response_source_response_invalid",
        ),
    ],
)
def test_http_cx_repaired_response_client_rejects_invalid_responses(
    response: httpx.Response,
    method_name: str,
    error_code: str,
) -> None:
    def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        return response

    client = HttpCxRepairedResponseSourceClient(requester=fake_request)
    method = getattr(client, method_name)
    kwargs = (
        {
            "parent_cx_generation_id": "cx-gen-001",
            "remediation_action_id": "ag-remediation-action-001",
        }
        if method_name == "get_remediation_execution_detail"
        else {"cx_generation_id": "cx-gen-repair-001"}
    )

    with pytest.raises(CxRepairedResponseSourceClientError) as exc_info:
        method(**kwargs)

    assert exc_info.value.status_code == 502
    assert exc_info.value.error_code == error_code


def test_default_cx_repaired_response_client_reads_env_and_validates_timeout() -> None:
    default_client = build_default_cx_repaired_response_source_client({})

    assert default_client.base_url == "http://127.0.0.1:8104"
    assert default_client.service_token is None
    assert default_client.timeout_seconds == 10.0

    client = build_default_cx_repaired_response_source_client(
        {
            "NEX_CX_BASE_URL": "http://cx.local/",
            "NEX_AE_TO_CX_SERVICE_TOKEN": "cx-token",
            AE_CX_REPAIRED_RESPONSE_TIMEOUT_ENV: "21.5",
        }
    )

    assert client.base_url == "http://cx.local"
    assert client.service_token == "cx-token"
    assert client.timeout_seconds == 21.5

    with pytest.raises(CxRepairedResponseSourceClientError) as text_error:
        build_default_cx_repaired_response_source_client(
            {AE_CX_REPAIRED_RESPONSE_TIMEOUT_ENV: "slow"}
        )

    assert text_error.value.error_code == "ae.cx_repaired_response_timeout_invalid"

    with pytest.raises(CxRepairedResponseSourceClientError) as number_error:
        build_default_cx_repaired_response_source_client(
            {AE_CX_REPAIRED_RESPONSE_TIMEOUT_ENV: "0"}
        )

    assert number_error.value.error_code == "ae.cx_repaired_response_timeout_invalid"


def test_repaired_response_source_package_fetches_and_sanitizes_materials() -> None:
    client = FakeCxRepairedResponseSourceClient(
        detail=cx_remediation_detail(debug_paths={"extra": "ignored"}),
        generation=repaired_generation_record(
            response_metadata={
                "finish_reason": "STOP",
                "output_hash": "c" * 64,
                "output_preview": "x" * 140,
                "extra": "ignored",
            },
            mo_runtime_metadata={"extra": "ignored"},
        ),
    )

    package = build_repaired_response_source_package(
        source_payload=source_payload(),
        client=client,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert package["source_package_schema_version"] == (
        AE_CX_REPAIRED_RESPONSE_SOURCE_PACKAGE_SCHEMA_VERSION
    )
    assert package["status"] == "READY_FOR_HANDOFF"
    assert package["source"] == {
        "source_service": "nex-cx",
        "parent_cx_generation_id": "cx-gen-001",
        "repair_cx_generation_id": "cx-gen-repair-001",
        "remediation_action_id": "ag-remediation-action-001",
    }
    assert package["repaired_generation_record"]["response_metadata"][
        "output_preview"
    ] == "x" * 120
    assert "debug_paths" not in package["cx_remediation_detail"]
    assert "mo_runtime_metadata" not in package["repaired_generation_record"]
    assert client.calls == [
        {
            "method": "detail",
            "parent_cx_generation_id": "cx-gen-001",
            "remediation_action_id": "ag-remediation-action-001",
            "request_id": REQUEST_ID,
            "trace_id": TRACE_ID,
        },
        {
            "method": "generation",
            "cx_generation_id": "cx-gen-repair-001",
            "request_id": REQUEST_ID,
            "trace_id": TRACE_ID,
        },
    ]
    serialized = json.dumps(package, sort_keys=True)
    assert "source_has_messages" not in serialized
    assert "raw_generation_output" not in serialized


def test_repaired_response_source_package_builds_final_handoff() -> None:
    package = build_repaired_response_source_package(
        source_payload=source_payload(),
        client=FakeCxRepairedResponseSourceClient(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    handoff = build_repaired_response_handoff_from_source_package(
        source_payload=source_payload(),
        source_package=package,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at="2026-08-27T00:00:00Z",
    )

    assert handoff["handoff_schema_version"] == "ae_repaired_response_handoff.v1"
    assert handoff["source"]["repair_cx_generation_id"] == "cx-gen-repair-001"
    assert handoff["repaired_response"]["output_hash"] == "c" * 64


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ({}, "ae.repaired_response_original_generation_id_required"),
        (
            {"original_cx_generation_id": "cx-gen-001"},
            "ae.repaired_response_remediation_action_id_required",
        ),
    ],
)
def test_repaired_response_source_package_requires_source_ids(
    payload: dict[str, Any],
    error_code: str,
) -> None:
    with pytest.raises(CxRepairedResponseSourceClientError) as exc_info:
        build_repaired_response_source_package(
            source_payload=payload,
            client=FakeCxRepairedResponseSourceClient(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("detail", "error_code"),
    [
        (
            cx_remediation_detail(execution_status="RUNNING"),
            "ae.repaired_response_execution_not_succeeded",
        ),
        (
            cx_remediation_detail(
                repaired_generation_lineage={
                    **cx_remediation_detail()["repaired_generation_lineage"],
                    "lineage_status": "PENDING_REPAIR_GENERATION",
                }
            ),
            "ae.repaired_response_lineage_not_linked",
        ),
        (
            cx_remediation_detail(
                repaired_generation_lineage={
                    **cx_remediation_detail()["repaired_generation_lineage"],
                    "diagnostics": {
                        **cx_remediation_detail()["repaired_generation_lineage"][
                            "diagnostics"
                        ],
                        "parent_generation_mutated": True,
                    },
                }
            ),
            "ae.repaired_response_lineage_invalid",
        ),
        (
            cx_remediation_detail(
                repaired_generation_lineage={
                    **cx_remediation_detail()["repaired_generation_lineage"],
                    "repair_cx_generation_id": None,
                }
            ),
            "ae.repaired_response_repair_generation_id_required",
        ),
    ],
)
def test_repaired_response_source_package_rejects_not_ready_lineage(
    detail: dict[str, Any],
    error_code: str,
) -> None:
    with pytest.raises(CxRepairedResponseSourceClientError) as exc_info:
        build_repaired_response_source_package(
            source_payload=source_payload(),
            client=FakeCxRepairedResponseSourceClient(detail=detail),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc_info.value.error_code == error_code


def test_repaired_response_source_package_rejects_generation_mismatch() -> None:
    with pytest.raises(CxRepairedResponseSourceClientError) as mismatch:
        build_repaired_response_source_package(
            source_payload=source_payload(),
            client=FakeCxRepairedResponseSourceClient(
                generation=repaired_generation_record(cx_generation_id="other")
            ),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert mismatch.value.error_code == "ae.repaired_response_repair_generation_mismatch"

    with pytest.raises(CxRepairedResponseSourceClientError) as not_completed:
        build_repaired_response_source_package(
            source_payload=source_payload(),
            client=FakeCxRepairedResponseSourceClient(
                generation=repaired_generation_record(status="FAILED")
            ),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert not_completed.value.error_code == (
        "ae.repaired_response_generation_not_completed"
    )


def test_repaired_response_source_package_validation_rejects_invalid_shape() -> None:
    package = build_repaired_response_source_package(
        source_payload=source_payload(),
        client=FakeCxRepairedResponseSourceClient(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    with pytest.raises(CxRepairedResponseSourceClientError) as schema_error:
        validate_repaired_response_source_package(
            {**package, "source_package_schema_version": "old"}
        )

    assert schema_error.value.error_code == "ae.repaired_response_source_package_invalid"

    with pytest.raises(CxRepairedResponseSourceClientError) as status_error:
        validate_repaired_response_source_package(
            {**package, "status": "WAITING_ON_CX"}
        )

    assert status_error.value.error_code == (
        "ae.repaired_response_source_package_not_ready"
    )

    mismatched = {
        **package,
        "repaired_generation_record": {
            **package["repaired_generation_record"],
            "cx_generation_id": "other",
        },
    }
    with pytest.raises(CxRepairedResponseSourceClientError) as mismatch:
        validate_repaired_response_source_package(mismatched)

    assert mismatch.value.error_code == (
        "ae.repaired_response_source_package_lineage_mismatch"
    )


def test_source_material_sanitizers_validate_schema_versions() -> None:
    with pytest.raises(CxRepairedResponseSourceClientError) as detail_error:
        sanitized_cx_remediation_detail({"detail_schema_version": "old"})

    assert detail_error.value.error_code == "ae.repaired_response_cx_detail_invalid"

    with pytest.raises(CxRepairedResponseSourceClientError) as generation_error:
        sanitized_cx_generation_record({"record_schema_version": "old"})

    assert generation_error.value.error_code == "ae.repaired_response_generation_invalid"


def test_source_material_sanitizers_default_sparse_numeric_and_refs() -> None:
    detail = cx_remediation_detail(
        repaired_generation_lineage={
            **cx_remediation_detail()["repaired_generation_lineage"],
            "attempt_no": 0,
            "result_ref": {"source_service": "nex-cx"},
        }
    )
    generation = repaired_generation_record(
        request_metadata={
            **repaired_generation_record()["request_metadata"],
            "selected_evidence_count": True,
            "grounded_response_quality_issue_count": "one",
        }
    )

    safe_detail = sanitized_cx_remediation_detail(detail)
    safe_generation = sanitized_cx_generation_record(generation)

    lineage = safe_detail["repaired_generation_lineage"]
    assert lineage["attempt_no"] == 1
    assert lineage["result_ref"] is None
    assert safe_generation["request_metadata"]["selected_evidence_count"] == 0
    assert safe_generation["request_metadata"][
        "grounded_response_quality_issue_count"
    ] == 0


def test_source_material_redaction_guard_allows_safe_flags_and_rejects_raw_keys() -> None:
    safe_payload = {
        "request_metadata": {
            "source_has_messages": True,
            "source_has_prompt": False,
        },
        "redaction_summary": {
            "raw_prompt_stored": False,
            "raw_content_included": False,
        },
    }

    assert find_sensitive_cx_repaired_response_source_material_keys(safe_payload) == []
    assert_cx_repaired_response_source_material_safe(safe_payload)

    unsafe_payload = {
        "request_metadata": {
            "messages": [{"role": "user", "content": "hidden prompt"}],
            "raw_prompt_stored": True,
        },
        "provider": {"provider_url": "http://provider.local"},
    }

    assert find_sensitive_cx_repaired_response_source_material_keys(unsafe_payload) == [
        "request_metadata.messages",
        "request_metadata.raw_prompt_stored",
        "provider.provider_url",
    ]
    with pytest.raises(CxRepairedResponseSourceClientError) as exc_info:
        assert_cx_repaired_response_source_material_safe(unsafe_payload)

    assert exc_info.value.error_code == (
        "ae.cx_repaired_response_source_sensitive_payload"
    )


def test_source_material_required_text_rejects_blank_http_ids() -> None:
    client = HttpCxRepairedResponseSourceClient(
        requester=lambda method, url, **kwargs: httpx.Response(200, json={})
    )

    with pytest.raises(CxRepairedResponseSourceClientError) as parent_error:
        client.get_remediation_execution_detail(
            parent_cx_generation_id=" ",
            remediation_action_id="ag-remediation-action-001",
        )

    assert "parent_cx_generation_id" in parent_error.value.error_code

    with pytest.raises(CxRepairedResponseSourceClientError) as generation_error:
        client.get_repaired_generation_record(cx_generation_id="")

    assert "cx_generation_id" in generation_error.value.error_code
