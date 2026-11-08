from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from nex_ae_api import nsl_approval_publication as publication_module
from nex_ae_api.delegated_work import DelegatedWorkError
from nex_ae_api.nsl_approval_publication import (
    ApprovalPublicationError,
    HttpWcApprovalWorkItemClient,
    P8NSLApprovalPort,
    deterministic_approval_work_item_id,
)
from nex_ae_api.nsl_approval_requests import ProtectedApprovalRequestError

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
EXECUTION_ID = "22222222-2222-4222-8222-222222222247"
STEP_ID = "33333333-3333-4333-8333-333333333347"


class ApprovalRequestStub:
    def __init__(self, **changes: object) -> None:
        self.data: dict[str, object] = {
            "tenant_id": "tenant-p8-s47",
            "execution_id": "nsl-execution-p8-s47",
            "business_operation_id": "business-operation-p8-s47",
            "approval_id": "APPROVE_VOUCHER_DRAFT",
            "approval_request_id": "approval-request-p8-s47",
            "skill_id": "FINANCE.CREATE_VOUCHER_DRAFT",
            "skill_version": "0.2.0",
            "skill_semantic_hash": "sha256:" + "a" * 64,
            "write_node_id": "write-voucher-draft",
            "tool_id": "finance.create_voucher_draft",
            "payload_hash": "sha256:" + "b" * 64,
            "write_intent_hash": "write-intent-p8-s47",
            "risk_level": "R3",
            "message": "This protected message must not reach WC.",
            "expires_at": "2026-10-23T12:00:00+00:00",
            "display_safe_summary": {"line_count": 2, "amount": "12000"},
            "protected_payload_ref": "snapshot://private/p8-s47",
            "data_classification": "CONFIDENTIAL",
        }
        self.data.update(changes)

    def to_data(self) -> dict[str, object]:
        return copy.deepcopy(self.data)


def _binding(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "tenant_id": "tenant-p8-s47",
        "agent_execution_id": EXECUTION_ID,
        "executable_step_id": STEP_ID,
        "nsl_execution_id": "nsl-execution-p8-s47",
        "business_operation_id": "business-operation-p8-s47",
        "checkpoint_version": 4,
        "target_approver_ref": "approver-p8-s47",
        "target_role_ref": None,
        "target_org_scope_ref": None,
        "target_project_scope_ref": None,
    }
    value.update(changes)
    return value


class BindingSource:
    def __init__(self, events: list[str], value: object | None = None) -> None:
        self.events = events
        self.value = _binding() if value is None else value

    def resolve(self, request):
        self.events.append("checkpoint")
        return self.value


class RequestStore:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls = 0

    def persist(self, request):
        self.events.append("request")
        self.calls += 1
        value = request.to_data()
        return {
            "tenant_id": value["tenant_id"],
            "approval_request_id": value["approval_request_id"],
            "nsl_execution_id": value["execution_id"],
            "business_operation_id": value["business_operation_id"],
            "protected_request_ref": (
                "ae://nsl-approval-requests/aa/" + "c" * 64 + ".json"
            ),
            "approval_request_hash": "sha256:" + "d" * 64,
        }


class WaitRepository:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.records: dict[str, dict[str, Any]] = {}
        self.calls: list[dict[str, Any]] = []

    def register(self, **values):
        self.events.append("wait")
        self.calls.append(dict(values))
        return self.records.setdefault(values["wait_id"], dict(values))


class WcClient:
    def __init__(self, events: list[str], *, fail_once: bool = False) -> None:
        self.events = events
        self.fail_once = fail_once
        self.calls: list[dict[str, Any]] = []

    def create_or_get(self, work_item):
        self.events.append("wc")
        self.calls.append(copy.deepcopy(dict(work_item)))
        if self.fail_once:
            self.fail_once = False
            raise ApprovalPublicationError("wc.unavailable", "Unavailable", True)
        return {"work_item": dict(work_item), "created": len(self.calls) == 1}


def _port(events: list[str], *, wc: WcClient | None = None, binding=None):
    store = RequestStore(events)
    waits = WaitRepository(events)
    client = wc or WcClient(events)
    port = P8NSLApprovalPort(
        binding_source=BindingSource(events, binding),
        request_store=store,
        wait_repository=waits,
        wc_client=client,
        clock=lambda: NOW,
    )
    return port, store, waits, client


def test_approval_port_publishes_in_durable_order_without_protected_content() -> None:
    events: list[str] = []
    port, _, waits, wc = _port(events)

    asyncio.run(port.publish(ApprovalRequestStub()))

    assert events == ["checkpoint", "request", "wait", "wc"]
    assert waits.calls[0]["checkpoint_version"] == 4
    assert waits.calls[0]["wait_type"] == "NSL_APPROVAL"
    item = wc.calls[0]
    assert item["protected_request_ref"].startswith("ae://")
    assert item["resume_target_ref"].startswith("ae-wait:")
    assert item["target_approver_ref"] == "approver-p8-s47"
    assert item["expires_at"] == "2026-10-23T12:00:00Z"
    serialized = repr(item)
    assert "This protected message" not in serialized
    assert "snapshot://private" not in serialized


def test_retry_reuses_request_wait_and_work_item_id_after_wc_failure() -> None:
    events: list[str] = []
    wc = WcClient(events, fail_once=True)
    port, store, waits, _ = _port(events, wc=wc)

    with pytest.raises(ApprovalPublicationError) as unavailable:
        asyncio.run(port.publish(ApprovalRequestStub()))
    assert unavailable.value.retryable is True

    asyncio.run(port.publish(ApprovalRequestStub()))

    assert store.calls == 2
    assert len(waits.records) == 1
    assert wc.calls[0]["approval_work_item_id"] == wc.calls[1][
        "approval_work_item_id"
    ]


@pytest.mark.parametrize(
    ("binding", "message"),
    [
        (_binding(checkpoint_version=0), "positive integer"),
        (_binding(nsl_execution_id="different"), "lineage differ"),
        (_binding(target_approver_ref=None), "decision target"),
        ([], "checkpoint binding must be an object"),
    ],
)
def test_checkpoint_binding_fails_closed_before_publication(binding, message) -> None:
    events: list[str] = []
    port, store, waits, wc = _port(events, binding=binding)

    with pytest.raises(ApprovalPublicationError, match=message):
        asyncio.run(port.publish(ApprovalRequestStub()))

    assert store.calls == 0
    assert waits.calls == []
    assert wc.calls == []


def test_checkpoint_source_failure_is_retryable_and_private() -> None:
    class FailingSource:
        def resolve(self, approval_request):
            raise RuntimeError("private checkpoint failure")

    events: list[str] = []
    port = P8NSLApprovalPort(
        binding_source=FailingSource(),
        request_store=RequestStore(events),
        wait_repository=WaitRepository(events),
        wc_client=WcClient(events),
        clock=lambda: NOW,
    )
    with pytest.raises(ApprovalPublicationError) as unavailable:
        asyncio.run(port.publish(ApprovalRequestStub()))
    assert unavailable.value.retryable is True
    assert "private" not in unavailable.value.detail


@pytest.mark.parametrize(
    ("failure", "expected_code", "retryable"),
    [
        (
            ProtectedApprovalRequestError("request.failed", "Request failed", True),
            "request.failed",
            True,
        ),
        (
            DelegatedWorkError("wait.failed", "Wait failed", False),
            "wait.failed",
            False,
        ),
    ],
)
def test_dependency_errors_preserve_typed_retry_semantics(
    failure, expected_code, retryable
) -> None:
    events: list[str] = []

    class FailingStore(RequestStore):
        def persist(self, request):
            if isinstance(failure, ProtectedApprovalRequestError):
                raise failure
            return super().persist(request)

    class FailingWait(WaitRepository):
        def register(self, **values):
            if isinstance(failure, DelegatedWorkError):
                raise failure
            return super().register(**values)

    port = P8NSLApprovalPort(
        binding_source=BindingSource(events),
        request_store=FailingStore(events),
        wait_repository=FailingWait(events),
        wc_client=WcClient(events),
        clock=lambda: NOW,
    )
    with pytest.raises(ApprovalPublicationError) as typed:
        asyncio.run(port.publish(ApprovalRequestStub()))
    assert typed.value.error_code == expected_code
    assert typed.value.retryable is retryable


def test_publication_rejects_protected_and_wc_lineage_drift() -> None:
    events: list[str] = []

    class DriftedStore(RequestStore):
        def persist(self, request):
            value = dict(super().persist(request))
            value["nsl_execution_id"] = "different"
            return value

    port = P8NSLApprovalPort(
        binding_source=BindingSource(events),
        request_store=DriftedStore(events),
        wait_repository=WaitRepository(events),
        wc_client=WcClient(events),
        clock=lambda: NOW,
    )
    with pytest.raises(ApprovalPublicationError, match="Protected"):
        asyncio.run(port.publish(ApprovalRequestStub()))

    class DriftedWc(WcClient):
        def create_or_get(self, work_item):
            result = dict(super().create_or_get(work_item))
            result["work_item"] = {**result["work_item"], "source_ref": "different"}
            return result

    events = []
    port, _, _, _ = _port(events, wc=DriftedWc(events))
    with pytest.raises(ApprovalPublicationError) as invalid:
        asyncio.run(port.publish(ApprovalRequestStub()))
    assert invalid.value.error_code == "ae.nsl_approval_wc_response_invalid"


def test_publication_rejects_oversized_summary_and_naive_clock() -> None:
    events: list[str] = []
    port, _, _, _ = _port(events)
    with pytest.raises(ApprovalPublicationError, match="summary exceeds"):
        asyncio.run(
            port.publish(ApprovalRequestStub(display_safe_summary={"x": "y" * 2000}))
        )

    port = P8NSLApprovalPort(
        binding_source=BindingSource([]),
        request_store=RequestStore([]),
        wait_repository=WaitRepository([]),
        wc_client=WcClient([]),
        clock=lambda: datetime(2026, 10, 22, 12),
    )
    with pytest.raises(ApprovalPublicationError, match="timezone-aware"):
        asyncio.run(port.publish(ApprovalRequestStub()))


def test_deterministic_work_item_id_is_stable_and_request_scoped() -> None:
    first = deterministic_approval_work_item_id(
        tenant_id="tenant-p8-s47", approval_request_id="approval-request-p8-s47"
    )
    assert first == deterministic_approval_work_item_id(
        tenant_id="tenant-p8-s47", approval_request_id="approval-request-p8-s47"
    )
    assert first != deterministic_approval_work_item_id(
        tenant_id="tenant-p8-s47", approval_request_id="other-request"
    )


def test_http_wc_client_uses_service_boundary_and_accepts_replay(monkeypatch) -> None:
    item = {
        "tenant_id": "tenant-p8-s47",
        "approval_work_item_id": "47000000-0000-4000-8000-000000000001",
    }
    captured: list[dict[str, Any]] = []

    def post(url, **kwargs):
        captured.append({"url": url, **kwargs})
        return httpx.Response(200, json={"work_item": item, "created": False})

    monkeypatch.setattr(httpx, "post", post)
    client = HttpWcApprovalWorkItemClient(
        base_url="https://wc.local/", service_token="signed-token"
    )

    result = client.create_or_get(item)

    assert result["created"] is False
    assert captured[0]["url"] == "https://wc.local/api/v1/approval-work-items"
    assert captured[0]["headers"]["Authorization"] == "Bearer signed-token"
    assert captured[0]["headers"]["X-NeX-Tenant-Id"] == "tenant-p8-s47"


def test_http_wc_client_types_transport_http_and_shape_failures(monkeypatch) -> None:
    client = HttpWcApprovalWorkItemClient(service_token="signed-token")
    item = {"tenant_id": "tenant-p8-s47"}

    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("private")),
    )
    with pytest.raises(ApprovalPublicationError) as transport:
        client.create_or_get(item)
    assert transport.value.retryable is True
    assert "private" not in transport.value.detail

    responses = iter(
        (
            httpx.Response(503, json={"retryable": True}),
            httpx.Response(409, json={"retryable": False}),
            httpx.Response(500, json=[]),
            httpx.Response(400, json={"retryable": "invalid"}),
            httpx.Response(200, content=b"not-json"),
            httpx.Response(500, content=b"not-json"),
            httpx.Response(200, json=[]),
            httpx.Response(200, json={"created": True}),
        )
    )
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: next(responses))
    for retryable in (True, False):
        with pytest.raises(ApprovalPublicationError) as rejected:
            client.create_or_get(item)
        assert rejected.value.retryable is retryable
    for retryable in (True, False):
        with pytest.raises(ApprovalPublicationError) as rejected:
            client.create_or_get(item)
        assert rejected.value.retryable is retryable
    for retryable in (False, True):
        with pytest.raises(ApprovalPublicationError) as invalid_json:
            client.create_or_get(item)
        assert invalid_json.value.retryable is retryable
    for _ in range(2):
        with pytest.raises(ApprovalPublicationError) as invalid:
            client.create_or_get(item)
        assert invalid.value.error_code == "ae.nsl_approval_wc_response_invalid"


def test_default_wc_client_reads_environment(monkeypatch) -> None:
    from nex_ae_api.nsl_approval_publication import (
        build_default_wc_approval_work_item_client,
    )

    monkeypatch.setenv("NEX_WC_BASE_URL", "https://wc.example")
    monkeypatch.setenv("NEX_AE_TO_WC_SERVICE_TOKEN", "token-p8-s47")

    client = build_default_wc_approval_work_item_client()

    assert client.base_url == "https://wc.example"
    assert client.service_token == "token-p8-s47"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (None, None),
        (123, "RFC3339"),
        ("not-a-time", "RFC3339"),
        ("2026-10-22T12:00:00", "timezone"),
    ],
)
def test_optional_expiration_normalization_branches(value, message) -> None:
    if message is None:
        assert publication_module._optional_time(value) is None
    else:
        with pytest.raises(ApprovalPublicationError, match=message):
            publication_module._optional_time(value)


def test_required_boundary_rejects_empty_and_oversized_values() -> None:
    for value in (None, "", "x" * 3):
        with pytest.raises(ApprovalPublicationError):
            publication_module._required("field", value, 2)
