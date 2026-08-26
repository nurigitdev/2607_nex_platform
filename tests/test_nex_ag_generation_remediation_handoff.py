from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator

from nex_ag.generation_remediation_handoff import (
    AG_CX_REMEDIATION_TIMEOUT_ENV,
    CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION,
    CX_REMEDIATION_EXECUTION_RESULT_SCHEMA_VERSION,
    CxRemediationExecutionClientError,
    HttpCxRemediationExecutionClient,
    assert_remediation_action_handoff_safe,
    build_cx_remediation_execution_request,
    build_default_cx_remediation_execution_client,
)


ROOT = Path(__file__).parents[1]
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def cx_request_schema() -> dict[str, Any]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "schemas"
            / "generation"
            / "cx_remediation_execution_request.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def remediation_action(**overrides: Any) -> dict[str, Any]:
    action: dict[str, Any] = {
        "action_schema_version": "ag_generation_remediation_action.v1",
        "remediation_action_id": "ag-remediation-action-001",
        "cx_generation_id": "cx-gen-001",
        "tenant_id": "local-tenant",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "action_type": "citation_repair",
        "action_status": "WAITING_ON_CX",
        "priority": "HIGH",
        "reason_codes": [
            "negative_user_feedback",
            "citation_quality",
        ],
        "owner_ref": {
            "owner_type": "user",
            "owner_id": "employee-0001",
            "tenant_id": "local-tenant",
        },
        "source_refs": [
            {
                "source_service": "nex-ae-api",
                "ref_type": "feedback",
                "ref_id": "ae-feedback-001",
                "relation": "caused_by",
            },
            {
                "source_service": "nex-ag",
                "ref_type": "operator_disposition",
                "ref_id": "ag-gq-disposition-001",
                "relation": "recommended_by",
            },
        ],
        "evidence": {
            "evidence_hashes": [
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ],
            "evidence_previews": [
                "Citation [2] did not support the generated answer.",
            ],
            "raw_evidence_stored": False,
        },
        "result_ref": None,
        "metadata": {
            "action_source": "operator_disposition",
            "raw_prompt_stored": False,
            "raw_generation_output_stored": False,
            "raw_source_document_text_stored": False,
            "raw_feedback_comment_stored": False,
            "raw_operator_note_stored": False,
            "free_text_storage": "hash_and_short_preview_only",
        },
        "created_at": "2026-08-26T00:00:00Z",
        "updated_at": "2026-08-26T00:00:00Z",
    }
    action.update(overrides)
    return action


@pytest.mark.parametrize(
    ("action_type", "lineage_type", "retrieval_policy", "prompt_policy"),
    [
        (
            "retry_generation",
            "retry",
            "reuse_original_retrieval_package",
            "rebuild_with_retry_instruction_ref",
        ),
        (
            "retrieval_repair",
            "fresh_retrieval_regenerate",
            "fresh_retrieval_required",
            "rebuild_with_retrieval_repair_instruction_ref",
        ),
        (
            "citation_repair",
            "repair",
            "reuse_or_expand_cited_evidence",
            "rebuild_with_citation_repair_instruction_ref",
        ),
    ],
)
def test_build_cx_remediation_execution_request_matches_contract(
    action_type: str,
    lineage_type: str,
    retrieval_policy: str,
    prompt_policy: str,
) -> None:
    request = build_cx_remediation_execution_request(
        remediation_action(action_type=action_type),
        requested_at="2026-08-26T00:00:00Z",
    )

    Draft202012Validator(cx_request_schema()).validate(request)
    assert request["parent_cx_generation_id"] == "cx-gen-001"
    assert request["action_type"] == action_type
    assert request["lineage_type"] == lineage_type
    assert request["execution_policy"] == {
        "parent_generation_mutation_allowed": False,
        "retrieval_package_policy": retrieval_policy,
        "prompt_package_policy": prompt_policy,
        "provider_boundary": "cx_to_mo_service_api_only",
    }
    assert request["requested_by"] == {
        "source_service": "nex-ag",
        "owner_ref": {
            "owner_type": "user",
            "owner_id": "employee-0001",
            "tenant_id": "local-tenant",
        },
    }
    assert request["metadata"]["raw_prompt_stored"] is False
    assert request["metadata"]["raw_generation_output_stored"] is False


def test_cx_remediation_execution_handoff_rejects_ag_only_and_sensitive_actions() -> None:
    with pytest.raises(CxRemediationExecutionClientError) as ag_only:
        build_cx_remediation_execution_request(
            remediation_action(action_type="prompt_policy_review")
        )

    assert ag_only.value.status_code == 422
    assert ag_only.value.error_code == (
        "ag.cx_remediation_execution_action_not_executable"
    )

    assert_remediation_action_handoff_safe(remediation_action())

    with pytest.raises(CxRemediationExecutionClientError) as raw_field:
        assert_remediation_action_handoff_safe(
            remediation_action(raw_prompt="hidden prompt")
        )

    assert raw_field.value.error_code == "ag.cx_remediation_execution_sensitive_payload"

    unsafe_metadata = remediation_action()
    unsafe_metadata["metadata"] = {
        **unsafe_metadata["metadata"],
        "raw_prompt_stored": True,
    }
    with pytest.raises(CxRemediationExecutionClientError) as raw_flag:
        build_cx_remediation_execution_request(unsafe_metadata)

    assert raw_flag.value.error_code == "ag.cx_remediation_execution_sensitive_payload"


def test_http_cx_remediation_execution_client_posts_guarded_payload() -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            202,
            json={
                "result_schema_version": CX_REMEDIATION_EXECUTION_RESULT_SCHEMA_VERSION,
                "remediation_action_id": "ag-remediation-action-001",
                "parent_cx_generation_id": "cx-gen-001",
                "repair_cx_generation_id": None,
                "execution_status": "ACCEPTED",
                "result_ref": None,
                "redaction_summary": {
                    "raw_content_included": False,
                    "prompt_text_included": False,
                    "evidence_text_included": False,
                    "provider_detail_included": False,
                },
            },
        )

    client = HttpCxRemediationExecutionClient(
        base_url="http://cx.local/",
        service_token="cx-token",
        timeout_seconds=2.5,
        requester=fake_request,
    )

    response = client.submit_remediation_action(
        remediation_action(),
        requested_at="2026-08-26T00:00:00Z",
        idempotency_key="handoff-001",
    )

    assert response["execution_status"] == "ACCEPTED"
    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "POST"
    assert call["url"] == (
        "http://cx.local/api/v1/generations/"
        "cx-gen-001/remediation-executions"
    )
    assert call["headers"] == {
        "Authorization": "Bearer cx-token",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        "X-Service-ID": "nex-ag",
    }
    assert call["timeout"] == 2.5
    assert call["json"]["idempotency_key"] == "handoff-001"
    assert "raw_prompt" not in call["json"]
    assert call["json"]["execution_policy"]["provider_boundary"] == (
        "cx_to_mo_service_api_only"
    )


def test_http_cx_remediation_execution_client_gets_detail_with_optional_trace() -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "detail_schema_version": CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION,
                "projection_status": "READY",
                "parent_cx_generation_id": "cx-gen-001",
                "remediation_action_id": "ag-remediation-action-001",
                "execution_status": "SUCCEEDED",
                "execution": {
                    "result_schema_version": (
                        CX_REMEDIATION_EXECUTION_RESULT_SCHEMA_VERSION
                    ),
                    "remediation_action_id": "ag-remediation-action-001",
                    "parent_cx_generation_id": "cx-gen-001",
                    "repair_cx_generation_id": "cx-gen-repair-001",
                    "execution_status": "SUCCEEDED",
                },
                "redaction_summary": {
                    "raw_content_included": False,
                    "prompt_text_included": False,
                    "evidence_text_included": False,
                    "provider_detail_included": False,
                },
            },
        )

    client = HttpCxRemediationExecutionClient(
        base_url="http://cx.local/",
        service_token="cx-token",
        timeout_seconds=3.0,
        requester=fake_request,
    )

    detail = client.get_remediation_execution_detail(
        parent_cx_generation_id="cx-gen-001",
        remediation_action_id="ag-remediation-action-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    detail_without_trace = client.get_remediation_execution_detail(
        parent_cx_generation_id="cx-gen-001",
        remediation_action_id="ag-remediation-action-001",
    )

    assert detail["detail_schema_version"] == (
        CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION
    )
    assert detail_without_trace["execution_status"] == "SUCCEEDED"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == (
        "http://cx.local/api/v1/generations/"
        "cx-gen-001/remediation-executions/ag-remediation-action-001"
    )
    assert calls[0]["headers"]["traceparent"] == (
        f"00-{TRACE_ID}-00f067aa0ba902b7-01"
    )
    assert "traceparent" not in calls[1]["headers"]
    assert calls[1]["headers"]["X-Request-ID"] == (
        "ag-cx-remediation-status:ag-remediation-action-001"
    )


def test_http_cx_remediation_execution_client_maps_failures() -> None:
    assert str(
        CxRemediationExecutionClientError(
            status_code=503,
            error_code="example",
            detail="example detail",
        )
    ) == "example detail"

    def problem_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "error_code": "cx.remediation_parent_state_invalid",
                "detail": "parent generation cannot be repaired.",
                "retryable": False,
            },
        )

    client = HttpCxRemediationExecutionClient(
        base_url="http://cx.local",
        requester=problem_request,
    )

    with pytest.raises(CxRemediationExecutionClientError) as problem:
        client.submit_remediation_action(remediation_action())

    assert problem.value.status_code == 409
    assert problem.value.error_code == "cx.remediation_parent_state_invalid"
    assert problem.value.retryable is False

    def timeout_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    timeout_client = HttpCxRemediationExecutionClient(
        base_url="http://cx.local",
        requester=timeout_request,
    )
    with pytest.raises(CxRemediationExecutionClientError) as timeout:
        timeout_client.submit_remediation_action(remediation_action())

    assert timeout.value.status_code == 503
    assert timeout.value.retryable is True

    def malformed_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(202, content=b"{not-json")

    malformed_client = HttpCxRemediationExecutionClient(
        base_url="http://cx.local",
        requester=malformed_request,
    )
    with pytest.raises(CxRemediationExecutionClientError) as malformed:
        malformed_client.submit_remediation_action(remediation_action())

    assert malformed.value.error_code == (
        "ag.cx_remediation_execution_response_invalid"
    )

    def list_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(202, json=["not", "object"])

    list_client = HttpCxRemediationExecutionClient(
        base_url="http://cx.local",
        requester=list_request,
    )
    with pytest.raises(CxRemediationExecutionClientError) as list_response:
        list_client.submit_remediation_action(remediation_action())

    assert list_response.value.error_code == (
        "ag.cx_remediation_execution_response_invalid"
    )

    def wrong_schema_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(202, json={"result_schema_version": "old"})

    wrong_schema_client = HttpCxRemediationExecutionClient(
        base_url="http://cx.local",
        requester=wrong_schema_request,
    )
    with pytest.raises(CxRemediationExecutionClientError) as wrong_schema:
        wrong_schema_client.submit_remediation_action(remediation_action())

    assert wrong_schema.value.status_code == 502
    assert wrong_schema.value.retryable is True


def test_http_cx_remediation_execution_client_maps_detail_failures() -> None:
    def problem_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "error_code": "cx.remediation_execution_not_found",
                "detail": "missing",
                "retryable": False,
            },
        )

    client = HttpCxRemediationExecutionClient(
        base_url="http://cx.local",
        requester=problem_request,
    )

    with pytest.raises(CxRemediationExecutionClientError) as problem:
        client.get_remediation_execution_detail(
            parent_cx_generation_id="cx-gen-001",
            remediation_action_id="ag-remediation-action-001",
        )

    assert problem.value.status_code == 404
    assert problem.value.error_code == "cx.remediation_execution_not_found"

    def timeout_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("down")

    timeout_client = HttpCxRemediationExecutionClient(
        base_url="http://cx.local",
        requester=timeout_request,
    )
    with pytest.raises(CxRemediationExecutionClientError) as timeout:
        timeout_client.get_remediation_execution_detail(
            parent_cx_generation_id="cx-gen-001",
            remediation_action_id="ag-remediation-action-001",
        )

    assert timeout.value.status_code == 503
    assert timeout.value.retryable is True

    def wrong_schema_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(200, json={"detail_schema_version": "old"})

    wrong_schema_client = HttpCxRemediationExecutionClient(
        base_url="http://cx.local",
        requester=wrong_schema_request,
    )
    with pytest.raises(CxRemediationExecutionClientError) as wrong_schema:
        wrong_schema_client.get_remediation_execution_detail(
            parent_cx_generation_id="cx-gen-001",
            remediation_action_id="ag-remediation-action-001",
        )

    assert wrong_schema.value.status_code == 502
    assert wrong_schema.value.error_code == (
        "ag.cx_remediation_execution_response_invalid"
    )


def test_default_cx_remediation_execution_client_reads_env_and_rejects_bad_timeout() -> None:
    default_client = build_default_cx_remediation_execution_client({})

    assert default_client.base_url == "http://127.0.0.1:8104"
    assert default_client.service_token is None
    assert default_client.timeout_seconds == 10.0

    client = build_default_cx_remediation_execution_client(
        {
            "NEX_CX_BASE_URL": "http://cx.local/",
            "NEX_AG_TO_CX_SERVICE_TOKEN": "cx-token",
            AG_CX_REMEDIATION_TIMEOUT_ENV: "12.5",
        }
    )

    assert client.base_url == "http://cx.local"
    assert client.service_token == "cx-token"
    assert client.timeout_seconds == 12.5

    with pytest.raises(CxRemediationExecutionClientError) as bad_text:
        build_default_cx_remediation_execution_client(
            {AG_CX_REMEDIATION_TIMEOUT_ENV: "slow"}
        )

    assert bad_text.value.status_code == 422
    assert bad_text.value.error_code == "ag.cx_remediation_execution_timeout_invalid"

    with pytest.raises(CxRemediationExecutionClientError) as bad_number:
        build_default_cx_remediation_execution_client(
            {AG_CX_REMEDIATION_TIMEOUT_ENV: "0"}
        )

    assert bad_number.value.error_code == "ag.cx_remediation_execution_timeout_invalid"


def test_build_cx_remediation_execution_request_rejects_missing_lists() -> None:
    for field in ("reason_codes", "source_refs"):
        action = remediation_action()
        action[field] = []

        with pytest.raises(CxRemediationExecutionClientError) as exc_info:
            build_cx_remediation_execution_request(action)

        assert exc_info.value.status_code == 422
        assert field in exc_info.value.error_code

    for field in ("remediation_action_id", "cx_generation_id"):
        action = remediation_action()
        action[field] = " "

        with pytest.raises(CxRemediationExecutionClientError) as exc_info:
            build_cx_remediation_execution_request(action)

        assert exc_info.value.status_code == 422
        assert field in exc_info.value.error_code

    missing_reason_list = remediation_action(reason_codes=None)
    with pytest.raises(CxRemediationExecutionClientError) as reason_error:
        build_cx_remediation_execution_request(missing_reason_list)

    assert reason_error.value.error_code == (
        "ag.cx_remediation_execution_reason_codes_invalid"
    )

    missing_source_refs = remediation_action(source_refs=None)
    with pytest.raises(CxRemediationExecutionClientError) as source_error:
        build_cx_remediation_execution_request(missing_source_refs)

    assert source_error.value.error_code == (
        "ag.cx_remediation_execution_source_refs_invalid"
    )

    bad_evidence = remediation_action(
        evidence={
            "evidence_hashes": [],
            "evidence_previews": ["preview"],
            "raw_evidence_stored": False,
        }
    )
    with pytest.raises(CxRemediationExecutionClientError) as evidence_error:
        build_cx_remediation_execution_request(bad_evidence)

    assert evidence_error.value.error_code == (
        "ag.cx_remediation_execution_evidence_hashes_invalid"
    )

    missing_raw_evidence_flag = remediation_action(
        evidence={
            "evidence_hashes": [
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ],
            "evidence_previews": ["preview"],
        }
    )
    with pytest.raises(CxRemediationExecutionClientError) as flag_error:
        build_cx_remediation_execution_request(missing_raw_evidence_flag)

    assert flag_error.value.error_code == (
        "ag.cx_remediation_execution_evidence_invalid"
    )

    raw_evidence = remediation_action(
        evidence={
            "evidence_hashes": [
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ],
            "evidence_previews": ["preview"],
            "raw_evidence_stored": True,
        }
    )
    with pytest.raises(CxRemediationExecutionClientError) as raw_evidence_error:
        build_cx_remediation_execution_request(raw_evidence)

    assert raw_evidence_error.value.error_code == (
        "ag.cx_remediation_execution_sensitive_payload"
    )


def test_build_cx_remediation_execution_request_defaults_owner_ref_when_absent() -> None:
    action = remediation_action(owner_ref=None, tenant_id=None)

    request = build_cx_remediation_execution_request(
        action,
        requested_at="2026-08-26T00:00:00Z",
    )

    assert request["tenant_id"] is None
    assert request["requested_by"]["owner_ref"] == {
        "owner_type": "service",
        "owner_id": "nex-ag",
        "tenant_id": None,
    }
