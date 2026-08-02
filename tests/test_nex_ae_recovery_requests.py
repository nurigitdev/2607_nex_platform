from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient

import nex_ae_api.recovery_requests as ae_recovery
from nex_ae_api.recovery_requests import (
    GenerationRecoveryRequestStore,
    HttpCxRecoverySourceClient,
    RecoveryRequestError,
    build_generation_recovery_request_record,
    endpoint_hint_for_action,
    policy_hash_status,
    recovery_action_is_allowed,
    register_generation_recovery_request_routes,
    safe_changed_fields,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
from nex_runtime.recovery import recovery_policy_hash, select_generation_recovery_policy


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


class FakeCxRecoveryClient:
    def __init__(self, record: dict[str, Any] | None = None) -> None:
        self.record = record or failed_cx_generation_record()
        self.calls: list[dict[str, Any]] = []

    def get_generation(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "cx_generation_id": cx_generation_id,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        return self.record


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def failed_cx_generation_record(
    *,
    failure_code: str = "mo.provider_timeout",
    stored_policy_hash: str | None = None,
    status: str = "FAILED",
) -> dict[str, Any]:
    policy = select_generation_recovery_policy(failure_code)
    return {
        "cx_generation_id": "cx-gen-timeout-001",
        "status": status,
        "failure": {
            "failure_code": failure_code,
            "failure_class": policy["failure_class"],
            "owner_service": policy["owner_service"],
            "failed_stage": "GENERATING",
            "retryable": policy["retryable"],
            "recovery_policy_id": policy["recovery_policy_id"],
            "recovery_policy_hash": stored_policy_hash
            if stored_policy_hash is not None
            else recovery_policy_hash(policy),
        },
        "recovery_lineage": {
            "parent_generation_id": None,
            "attempt_no": 1,
            "reuse_retrieval_package": True,
        },
    }


def unknown_policy_failed_record() -> dict[str, Any]:
    return {
        "cx_generation_id": "cx-gen-unknown-001",
        "status": "FAILED",
        "failure": {
            "failure_code": "mo.unknown_failure",
            "failure_class": "unclassified_failure",
            "owner_service": "nex-cx",
            "failed_stage": "FAILED",
            "retryable": False,
            "recovery_policy_id": None,
            "recovery_policy_hash": None,
        },
        "recovery_lineage": {
            "parent_generation_id": None,
            "attempt_no": 7,
            "reuse_retrieval_package": False,
        },
    }


def build_client(
    record: dict[str, Any] | None = None,
) -> tuple[TestClient, FakeCxRecoveryClient, GenerationRecoveryRequestStore]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = GenerationRecoveryRequestStore()
    client = FakeCxRecoveryClient(record)
    register_generation_recovery_request_routes(app, store=store, cx_client=client)
    return TestClient(app), client, store


def test_build_generation_recovery_request_record_accepts_retry() -> None:
    record = build_generation_recovery_request_record(
        source_payload={
            "interaction_id": "ae-chat-001",
            "chat_document_id": "ae-chat-doc-001",
            "changed_fields": [" timeout_ms ", "raw_prompt", "timeout_ms"],
        },
        cx_record=failed_cx_generation_record(),
        requested_action="retry",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert record["status"] == "ACCEPTED"
    assert record["requested_action"] == "retry"
    assert record["parent_generation_id"] == "cx-gen-timeout-001"
    assert record["policy"]["hash_status"] == "MATCHED"
    assert record["dispatch"] == {
        "target_service": "nex-cx",
        "endpoint_hint": "/api/v1/generations",
        "attempt_no": 2,
        "retry_after_seconds": 5,
        "reuse_retrieval_package": True,
        "changed_fields": ["timeout_ms"],
        "requires_user_confirmation": False,
    }
    assert "raw_prompt" not in str(record)


def test_recovery_request_route_creates_and_reads_record() -> None:
    client, cx_client, store = build_client()

    created = client.post(
        "/api/v1/recovery/generation-requests",
        json={
            "cx_generation_id": "cx-gen-timeout-001",
            "requested_action": "retry",
            "interaction_id": "ae-chat-001",
        },
        headers=auth_headers(),
    )

    assert created.status_code == 202
    payload = created.json()
    assert payload["cx_generation_id"] == "cx-gen-timeout-001"
    assert cx_client.calls[0]["cx_generation_id"] == "cx-gen-timeout-001"
    assert store.get(payload["recovery_request_id"]) == payload

    read_back = client.get(
        f"/api/v1/recovery/generation-requests/{payload['recovery_request_id']}",
        headers=auth_headers(),
    )
    assert read_back.status_code == 200
    assert read_back.json() == payload


def test_recovery_request_routes_require_auth_and_report_missing_record() -> None:
    client, _, _ = build_client()

    unauthorized = client.post(
        "/api/v1/recovery/generation-requests",
        json={"cx_generation_id": "cx-gen-timeout-001", "requested_action": "retry"},
    )
    missing = client.get(
        "/api/v1/recovery/generation-requests/missing",
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ae.recovery_request_not_found"


def test_recovery_request_rejects_invalid_source_and_actions() -> None:
    client, _, _ = build_client(failed_cx_generation_record(status="COMPLETED"))
    not_failed = client.post(
        "/api/v1/recovery/generation-requests",
        json={"cx_generation_id": "cx-gen-timeout-001", "requested_action": "retry"},
        headers=auth_headers(),
    )

    bad_action = build_client()[0].post(
        "/api/v1/recovery/generation-requests",
        json={"cx_generation_id": "cx-gen-timeout-001", "requested_action": "explode"},
        headers=auth_headers(),
    )
    not_allowed = build_client()[0].post(
        "/api/v1/recovery/generation-requests",
        json={"cx_generation_id": "cx-gen-timeout-001", "requested_action": "repair"},
        headers=auth_headers(),
    )

    assert not_failed.status_code == 409
    assert not_failed.json()["error_code"] == "ae.recovery_source_not_failed"
    assert bad_action.status_code == 422
    assert bad_action.json()["error_code"] == "ae.recovery_action_invalid"
    assert not_allowed.status_code == 409
    assert not_allowed.json()["error_code"] == "ae.recovery_action_not_allowed"


def test_unknown_policy_allows_cancel_fallback_only() -> None:
    cancel = build_generation_recovery_request_record(
        source_payload={},
        cx_record=unknown_policy_failed_record(),
        requested_action="cancel",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert cancel["policy"]["hash_status"] == "UNAVAILABLE"
    assert cancel["dispatch"]["target_service"] == "nex-ae-api"
    assert cancel["dispatch"]["endpoint_hint"] == "/api/v1/recovery/cancellations"
    assert cancel["dispatch"]["attempt_no"] == 8

    try:
        build_generation_recovery_request_record(
            source_payload={},
            cx_record=unknown_policy_failed_record(),
            requested_action="retry",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    except RecoveryRequestError as exc:
        assert exc.error_code == "ae.recovery_action_not_allowed"
    else:
        raise AssertionError("expected RecoveryRequestError")


def test_recovery_request_helpers_cover_policy_and_dispatch_edges() -> None:
    stale = failed_cx_generation_record(stored_policy_hash="e" * 64)
    record = build_generation_recovery_request_record(
        source_payload={"changed_fields": ["quality_policy", "api_key", 7, ""]},
        cx_record=stale,
        requested_action="retry",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert record["policy"]["hash_status"] == "STALE"
    assert safe_changed_fields(["source_text", "render_policy", "render_policy"]) == [
        "render_policy"
    ]
    assert policy_hash_status(stored_hash=None, active_hash="a" * 64) == "UNAVAILABLE"
    assert policy_hash_status(stored_hash="a" * 64, active_hash=None) == "UNAVAILABLE"
    assert endpoint_hint_for_action("manual_accept_with_warning") == (
        "/api/v1/recovery/manual-acceptances"
    )
    assert recovery_action_is_allowed(None, "cancel") is True
    assert recovery_action_is_allowed(None, "retry") is False

    low_confidence = failed_cx_generation_record(
        failure_code="cx.low_confidence_generation_blocked"
    )
    fresh = build_generation_recovery_request_record(
        source_payload={},
        cx_record=low_confidence,
        requested_action="fresh_retrieval_regenerate",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    assert fresh["policy"]["operator_override_allowed"] is True
    assert fresh["dispatch"]["reuse_retrieval_package"] is False


def test_http_cx_recovery_source_client_gets_generation_with_mock_token(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_get(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return httpx.Response(200, json={"cx_generation_id": "cx-gen-001"})

    monkeypatch.setattr(ae_recovery.httpx, "get", fake_get)

    response = HttpCxRecoverySourceClient(base_url="http://cx.test").get_generation(
        "cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert response["cx_generation_id"] == "cx-gen-001"
    assert calls[0]["args"] == ("http://cx.test/api/v1/generations/cx-gen-001",)
    assert calls[0]["kwargs"]["headers"]["X-Service-ID"] == "nex-ae-api"


def test_http_cx_recovery_source_client_maps_problem_and_non_json(monkeypatch) -> None:
    def fake_problem(*args, **kwargs):
        return httpx.Response(
            503,
            json={
                "error_code": "cx.unavailable",
                "detail": "CX unavailable.",
                "retryable": True,
            },
        )

    monkeypatch.setattr(ae_recovery.httpx, "get", fake_problem)
    try:
        HttpCxRecoverySourceClient(base_url="http://cx.test").get_generation(
            "cx-gen-001",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    except RecoveryRequestError as exc:
        assert exc.error_code == "cx.unavailable"
        assert exc.retryable is True
    else:
        raise AssertionError("expected RecoveryRequestError")

    def fake_non_json(*args, **kwargs):
        return httpx.Response(503, content=b"nope")

    monkeypatch.setattr(ae_recovery.httpx, "get", fake_non_json)
    try:
        HttpCxRecoverySourceClient(base_url="http://cx.test").get_generation(
            "cx-gen-001",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    except RecoveryRequestError as exc:
        assert exc.error_code == "cx.generation_lookup_failed"
    else:
        raise AssertionError("expected RecoveryRequestError")
