from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_ae_api import approval_facade
from nex_ae_api.approval_facade import (
    ApprovalFacadeError,
    HttpWcApprovalClient,
    build_default_wc_approval_client,
    register_approval_facade_routes,
)
from nex_runtime import issue_mock_service_token, issue_mock_user_token

GATE_ID = "42000000-0000-4000-8000-000000000001"


def _gate() -> dict[str, Any]:
    return {
        "schema_version": "human_gate_view.p8.v1",
        "gate_id": GATE_ID,
        "approval_domain": "NSL_WRITE",
        "state": "PENDING",
        "title": "Approve protected WRITE",
        "summary": "Create an approved draft voucher.",
        "action_ref": f"/api/v1/approval-gates/{GATE_ID}",
        "approval_provider_type": "NSL",
        "approval_target_ref": "approval-request-s42",
        "business_operation_id": "operation-s42",
        "expires_at": "2026-10-23T09:00:00Z",
    }


def _formal_gate() -> dict[str, Any]:
    gate = {
        **_gate(),
        "approval_domain": "BUSINESS_FORMAL",
        "approval_provider_type": "EOS",
        "approval_target_ref": "eos-stage-s74",
    }
    gate["formal_approval"] = {
        "schema_version": "business_formal_gate_view.p8.v1",
        "current_stage": 1,
        "stage_count": 2,
        "requested_role": "TEAM_LEAD",
        "eos_target_ref": "eos-stage-s74",
        "org_unit_id": "org-s74",
        "project_id": "project-s74",
        "terminal_state": None,
    }
    return gate


def _inbox() -> dict[str, Any]:
    return {
        "schema_version": "wc_approval_inbox.v1",
        "tenant_id": "tenant-s42",
        "subject_ref": {"type": "oa.user", "id": "approver-s42"},
        "gates": [_gate()],
        "returned_count": 1,
        "limit": 50,
        "scan_truncated": False,
    }


def _detail() -> dict[str, Any]:
    return {
        "schema_version": "wc_approval_gate_detail.v1",
        "gate": _gate(),
        "created_at": "2026-10-22T08:00:00Z",
        "version": 1,
        "decision_options": ["APPROVE", "REJECT"],
    }


def _decision() -> dict[str, Any]:
    return {
        "schema_version": "wc_approval_decision.v1",
        "tenant_id": "tenant-s42",
        "decision_id": "42100000-0000-4000-8000-000000000001",
        "approval_work_item_id": GATE_ID,
        "decision": "APPROVE",
        "decided_by": "approver-s42",
        "decision_comment": "Reviewed.",
        "decision_version": 1,
        "authorized_by_oa": True,
        "oa_decision_ref": "oa-decision-s42",
        "authorization_revision_hash": "sha256:" + "a" * 64,
        "authorization_checked_at": "2026-10-22T09:00:00Z",
        "decided_at": "2026-10-22T09:00:00Z",
    }


def _request() -> dict[str, Any]:
    return {
        "schema_version": "wc_approval_decision_request.v1",
        "decision": "APPROVE",
        "decision_comment": "Reviewed.",
        "correlation_id": "conversation-s42",
        "causation_id": "interaction-s42",
    }


@dataclass
class FakeWcClient:
    error: ApprovalFacadeError | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def _result(self, operation: str, kwargs: dict[str, Any], value: Any):
        self.calls.append((operation, kwargs))
        if self.error is not None:
            raise self.error
        return value

    def list_gates(self, **kwargs):
        return self._result("list", kwargs, _inbox())

    def get_gate(self, approval_work_item_id, **kwargs):
        return self._result(
            "get", {"approval_work_item_id": approval_work_item_id, **kwargs}, _detail()
        )

    def decide_gate(self, approval_work_item_id, payload, **kwargs):
        return self._result(
            "decide",
            {
                "approval_work_item_id": approval_work_item_id,
                "payload": dict(payload),
                **kwargs,
            },
            (_decision(), 201),
        )


def _client(wc_client: FakeWcClient | None = None) -> tuple[TestClient, FakeWcClient]:
    app = FastAPI()
    source = wc_client or FakeWcClient()
    register_approval_facade_routes(app, wc_client=source)
    return TestClient(app), source


def _user_headers() -> dict[str, str]:
    token = issue_mock_user_token(
        tenant_id="tenant-s42",
        user_id="approver-s42",
    )
    return {"Authorization": f"Bearer {token.access_token}"}


def test_browser_facade_derives_identity_for_list_and_detail() -> None:
    client, wc = _client()

    inbox = client.get(
        "/api/v1/approval-gates?limit=25",
        headers={**_user_headers(), "X-Request-ID": "request-s42"},
    )
    detail = client.get(
        f"/api/v1/approval-gates/{GATE_ID}",
        headers=_user_headers(),
    )

    assert inbox.status_code == 200
    assert inbox.json()["gates"][0]["approval_domain"] == "NSL_WRITE"
    assert detail.status_code == 200
    assert detail.json()["decision_options"] == ["APPROVE", "REJECT"]
    assert wc.calls[0][0] == "list"
    assert wc.calls[0][1]["tenant_id"] == "tenant-s42"
    assert wc.calls[0][1]["subject_id"] == "approver-s42"
    assert wc.calls[0][1]["limit"] == 25
    assert wc.calls[0][1]["request_id"] == "request-s42"
    assert wc.calls[1][1]["approval_work_item_id"] == GATE_ID


def test_browser_facade_forwards_exact_decision_contract() -> None:
    client, wc = _client()

    response = client.post(
        f"/api/v1/approval-gates/{GATE_ID}/decisions",
        headers=_user_headers(),
        json=_request(),
    )

    assert response.status_code == 201
    assert response.json()["decision"] == "APPROVE"
    assert wc.calls == [
        (
            "decide",
            {
                "approval_work_item_id": GATE_ID,
                "payload": _request(),
                "tenant_id": "tenant-s42",
                "subject_id": "approver-s42",
                "request_id": wc.calls[0][1]["request_id"],
                "trace_id": wc.calls[0][1]["trace_id"],
            },
        )
    ]


@pytest.mark.parametrize(
    "payload",
    (
        {**_request(), "extra": True},
        {**_request(), "schema_version": "old"},
        {**_request(), "decision": "DELETE"},
        {**_request(), "decision_comment": ""},
        {**_request(), "decision_comment": "x" * 2001},
        {**_request(), "correlation_id": ""},
        {**_request(), "causation_id": 1},
    ),
)
def test_facade_rejects_invalid_decision_without_wc_call(payload) -> None:
    client, wc = _client()

    response = client.post(
        f"/api/v1/approval-gates/{GATE_ID}/decisions",
        headers=_user_headers(),
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "ae.approval_decision_request_invalid"
    assert wc.calls == []


def test_facade_requires_browser_user_and_preserves_wc_denial() -> None:
    service_token = issue_mock_service_token(
        service_id="nex-ag", audience="nex-ae-api"
    )
    client, _ = _client()
    service_response = client.get(
        "/api/v1/approval-gates",
        headers={"Authorization": f"Bearer {service_token.access_token}"},
    )

    denied, _ = _client(
        FakeWcClient(
            error=ApprovalFacadeError(
                403,
                "wc.approval_authorization_denied",
                "Current approval authority was denied.",
            )
        )
    )
    denied_response = denied.post(
        f"/api/v1/approval-gates/{GATE_ID}/decisions",
        headers=_user_headers(),
        json=_request(),
    )

    assert service_response.status_code == 403
    assert service_response.json()["error_code"] == (
        "ae.approval_browser_session_required"
    )
    assert denied_response.status_code == 403
    assert denied_response.json()["error_code"] == (
        "wc.approval_authorization_denied"
    )
    assert denied_response.json()["retryable"] is False


def test_detail_and_decision_reject_missing_browser_identity() -> None:
    client, wc = _client()

    detail = client.get(f"/api/v1/approval-gates/{GATE_ID}")
    decision = client.post(
        f"/api/v1/approval-gates/{GATE_ID}/decisions",
        json=_request(),
    )

    assert detail.status_code == 401
    assert decision.status_code == 401
    assert wc.calls == []


def test_detail_preserves_wc_failure_and_error_string() -> None:
    failure = ApprovalFacadeError(
        410,
        "wc.approval_expired",
        "Approval item expired.",
    )
    client, _ = _client(FakeWcClient(error=failure))

    response = client.get(
        f"/api/v1/approval-gates/{GATE_ID}",
        headers=_user_headers(),
    )

    assert str(failure) == "Approval item expired."
    assert response.status_code == 410
    assert response.json()["error_code"] == "wc.approval_expired"


def test_facade_maps_wc_unavailability_and_query_validation() -> None:
    client, _ = _client(
        FakeWcClient(
            error=ApprovalFacadeError(
                503,
                "ae.wc_approval_unavailable",
                "WC approval service is unavailable.",
                True,
            )
        )
    )

    unavailable = client.get("/api/v1/approval-gates", headers=_user_headers())
    invalid_limit = client.get(
        "/api/v1/approval-gates?limit=101", headers=_user_headers()
    )

    assert unavailable.status_code == 503
    assert unavailable.json()["retryable"] is True
    assert invalid_limit.status_code == 422


def test_http_wc_client_uses_ae_service_identity_and_subject_headers(
    monkeypatch,
) -> None:
    captured: list[dict[str, Any]] = []

    def request(method, url, **kwargs):
        captured.append({"method": method, "url": url, **kwargs})
        return httpx.Response(200, json=_inbox())

    monkeypatch.setattr(approval_facade.httpx, "request", request)
    client = HttpWcApprovalClient(
        base_url="https://wc.local/", service_token="signed-token"
    )

    result = client.list_gates(
        tenant_id="tenant-s42",
        subject_id="approver-s42",
        limit=10,
        request_id="request-s42",
        trace_id="1" * 32,
    )

    assert result["returned_count"] == 1
    assert captured[0]["url"] == "https://wc.local/api/v1/approval-gates"
    assert captured[0]["headers"]["Authorization"] == "Bearer signed-token"
    assert captured[0]["headers"]["X-NeX-Tenant-Id"] == "tenant-s42"
    assert captured[0]["headers"]["X-NeX-Subject-Id"] == "approver-s42"
    assert "approver-s42" not in str(captured[0].get("json"))


def test_http_wc_client_admits_business_formal_projection_only_in_its_domain(
    monkeypatch,
) -> None:
    inbox = {**_inbox(), "gates": [_formal_gate()]}
    detail = {**_detail(), "gate": _formal_gate()}
    responses = iter((httpx.Response(200, json=inbox), httpx.Response(200, json=detail)))
    monkeypatch.setattr(
        approval_facade.httpx,
        "request",
        lambda *args, **kwargs: next(responses),
    )
    client = HttpWcApprovalClient(service_token="signed-token")
    common = {
        "tenant_id": "tenant-s42",
        "subject_id": "approver-s42",
        "request_id": "request-s74",
        "trace_id": "7" * 32,
    }

    projected = client.list_gates(limit=10, **common)["gates"][0]
    assert projected["formal_approval"]["current_stage"] == 1
    assert client.get_gate(GATE_ID, **common)["gate"]["formal_approval"][
        "requested_role"
    ] == "TEAM_LEAD"


@pytest.mark.parametrize(
    ("gate_overrides", "formal_overrides"),
    (
        ({"approval_provider_type": "NSL"}, {}),
        ({"business_operation_id": None}, {}),
        ({}, {"schema_version": "old"}),
        ({}, {"eos_target_ref": "eos-stage-other"}),
        ({}, {"current_stage": None}),
        ({}, {"current_stage": True}),
        ({}, {"stage_count": True}),
        ({}, {"current_stage": "1"}),
        ({}, {"stage_count": "2"}),
        ({}, {"current_stage": 0}),
        ({}, {"current_stage": 3, "stage_count": 2}),
        ({}, {"stage_count": 6}),
        ({}, {"terminal_state": "APPROVED"}),
    ),
)
def test_http_wc_client_rejects_business_formal_semantic_drift(
    monkeypatch,
    gate_overrides,
    formal_overrides,
) -> None:
    gate = _formal_gate()
    gate.update(gate_overrides)
    gate["formal_approval"].update(formal_overrides)
    monkeypatch.setattr(
        approval_facade.httpx,
        "request",
        lambda *args, **kwargs: httpx.Response(
            200,
            json={**_inbox(), "gates": [gate]},
        ),
    )
    client = HttpWcApprovalClient(service_token="signed-token")

    with pytest.raises(ApprovalFacadeError) as unsafe:
        client.list_gates(
            tenant_id="tenant-s42",
            subject_id="approver-s42",
            limit=10,
            request_id="request-s74",
            trace_id="8" * 32,
        )

    assert unsafe.value.error_code == "ae.wc_approval_response_unsafe"


def test_http_wc_client_admits_unknown_progress_and_matching_terminal_state(
    monkeypatch,
) -> None:
    unknown = _formal_gate()
    unknown["formal_approval"].update(current_stage=None, stage_count=None)
    terminal = _formal_gate()
    terminal["state"] = "APPROVED"
    terminal["formal_approval"]["terminal_state"] = "APPROVED"
    responses = iter(
        (
            httpx.Response(200, json={**_inbox(), "gates": [unknown]}),
            httpx.Response(200, json={**_detail(), "gate": terminal}),
        )
    )
    monkeypatch.setattr(
        approval_facade.httpx,
        "request",
        lambda *args, **kwargs: next(responses),
    )
    client = HttpWcApprovalClient(service_token="signed-token")
    common = {
        "tenant_id": "tenant-s42",
        "subject_id": "approver-s42",
        "request_id": "request-s74",
        "trace_id": "9" * 32,
    }

    assert client.list_gates(limit=10, **common)["gates"][0]["formal_approval"][
        "current_stage"
    ] is None
    assert client.get_gate(GATE_ID, **common)["gate"]["state"] == "APPROVED"


def test_http_wc_client_decision_status_and_failure_branches(monkeypatch) -> None:
    responses = iter(
        (
            httpx.Response(201, json=_decision()),
            httpx.Response(200, json=_detail()),
            httpx.Response(
                409,
                json={
                    "error_code": "wc.approval_decision_conflict",
                    "detail": "Already decided.",
                    "retryable": False,
                },
            ),
            httpx.Response(200, content=b"not-json"),
            httpx.Response(200, json=[]),
        )
    )
    monkeypatch.setattr(
        approval_facade.httpx,
        "request",
        lambda *args, **kwargs: next(responses),
    )
    client = HttpWcApprovalClient(service_token="signed-token")
    common = {
        "tenant_id": "tenant-s42",
        "subject_id": "approver-s42",
        "request_id": "request-s42",
        "trace_id": "2" * 32,
    }

    decision, status = client.decide_gate(GATE_ID, _request(), **common)
    assert status == 201
    assert decision["decision"] == "APPROVE"
    assert client.get_gate(GATE_ID, **common)["gate"]["gate_id"] == GATE_ID

    with pytest.raises(ApprovalFacadeError) as conflict:
        client.get_gate(GATE_ID, **common)
    assert conflict.value.status_code == 409
    assert conflict.value.retryable is False

    for expected_status in (502, 502):
        with pytest.raises(ApprovalFacadeError) as invalid:
            client.get_gate(GATE_ID, **common)
        assert invalid.value.status_code == expected_status


def test_http_wc_client_fails_closed_on_transport_and_token_errors(
    monkeypatch,
) -> None:
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("private")

    monkeypatch.setattr(approval_facade.httpx, "request", unavailable)
    common = {
        "tenant_id": "tenant-s42",
        "subject_id": "approver-s42",
        "limit": 10,
        "request_id": "request-s42",
        "trace_id": "3" * 32,
    }
    with pytest.raises(ApprovalFacadeError) as transport:
        HttpWcApprovalClient(service_token="signed-token").list_gates(**common)
    assert transport.value.status_code == 503
    assert "private" not in transport.value.detail

    with pytest.raises(ApprovalFacadeError) as token:
        HttpWcApprovalClient(service_token=" bad ").list_gates(**common)
    assert token.value.error_code == "ae.wc_approval_unavailable"


@pytest.mark.parametrize(
    ("operation", "payload"),
    (
        ("list", {**_inbox(), "protected_request_ref": "private"}),
        (
            "list",
            {**_inbox(), "subject_ref": {"type": "oa.user", "id": "x", "raw": 1}},
        ),
        ("list", {**_inbox(), "gates": "invalid"}),
        ("list", {**_inbox(), "gates": [None]}),
        (
            "list",
            {**_inbox(), "gates": [{**_gate(), "semantic_hash": "private"}]},
        ),
        (
            "list",
            {**_inbox(), "gates": [{**_gate(), "formal_approval": {}}]},
        ),
        (
            "list",
            {
                **_inbox(),
                "gates": [
                    {
                        key: value
                        for key, value in _formal_gate().items()
                        if key != "formal_approval"
                    }
                ],
            },
        ),
        (
            "detail",
            {
                **_detail(),
                "gate": {
                    **_formal_gate(),
                    "formal_approval": {
                        **_formal_gate()["formal_approval"],
                        "semantic_hash": "private",
                    },
                },
            },
        ),
        ("detail", {**_detail(), "protected_request_ref": "private"}),
        (
            "detail",
            {**_detail(), "gate": {**_gate(), "source_ref": "private"}},
        ),
        ("decision", {**_decision(), "service_token": "private"}),
        (
            "decision",
            {
                key: value
                for key, value in _decision().items()
                if key != "decision_id"
            },
        ),
    ),
)
def test_http_wc_client_rejects_unsafe_response_shapes(
    monkeypatch,
    operation,
    payload,
) -> None:
    monkeypatch.setattr(
        approval_facade.httpx,
        "request",
        lambda *args, **kwargs: httpx.Response(200, json=payload),
    )
    client = HttpWcApprovalClient(service_token="signed-token")
    common = {
        "tenant_id": "tenant-s42",
        "subject_id": "approver-s42",
        "request_id": "request-s42",
        "trace_id": "4" * 32,
    }

    with pytest.raises(ApprovalFacadeError) as unsafe:
        if operation == "list":
            client.list_gates(limit=10, **common)
        elif operation == "detail":
            client.get_gate(GATE_ID, **common)
        else:
            client.decide_gate(GATE_ID, _request(), **common)

    assert unsafe.value.status_code == 502
    assert unsafe.value.error_code == "ae.wc_approval_response_unsafe"


def test_default_wc_client_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("NEX_WC_BASE_URL", "https://wc.example")
    monkeypatch.setenv("NEX_AE_TO_WC_SERVICE_TOKEN", "token-s42")

    client = build_default_wc_approval_client()

    assert client.base_url == "https://wc.example"
    assert client.service_token == "token-s42"


def test_default_wc_client_uses_registered_wc_port(monkeypatch) -> None:
    monkeypatch.delenv("NEX_WC_BASE_URL", raising=False)

    client = build_default_wc_approval_client()

    assert client.base_url == "http://127.0.0.1:8106"
