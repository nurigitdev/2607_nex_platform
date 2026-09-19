from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import nex_ag.operations as operations
from nex_ag.operator_review_cases import (
    OperatorReviewCaseStore,
    OperatorReviewEscalationDispatchStore,
    OperatorReviewEscalationStore,
)
from nex_ag.operator_reviews import OperatorReviewNoteError
from nex_runtime import (
    InMemoryWorkerHeartbeatStore,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


PATH = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/"
    "recovery-notification-deliveries"
)


def auth_headers(*, idempotency_key: str | None = "idem-0844") -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    headers = {"Authorization": f"Bearer {issued.access_token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def case_record(**overrides: object) -> dict[str, Any]:
    return {
        "case_id": "case-0844",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
        **overrides,
    }


def escalation_record(**overrides: object) -> dict[str, Any]:
    return {
        "escalation_id": "escalation-0844",
        "candidate_id": "candidate-0844",
        "case_id": "case-0844",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
        "escalation_status": "ACTIVE",
        "escalation_level": "ATTENTION",
        "sla_state": "WARNING",
        "reason_codes": ["daemon_missing"],
        "runbook_ids": ["ag.dispatch_daemon.recover.v1"],
        "recommended_actions": ["inspect_dispatch_daemon"],
        **overrides,
    }


def build_client(
    *,
    case: dict[str, Any] | None = None,
    escalation: dict[str, Any] | None = None,
    dispatch_store_override: Any | None = None,
) -> tuple[
    TestClient,
    OperatorReviewCaseStore,
    OperatorReviewEscalationStore,
    OperatorReviewEscalationDispatchStore,
]:
    case_store = OperatorReviewCaseStore()
    escalation_store = OperatorReviewEscalationStore()
    dispatch_store = (
        dispatch_store_override or OperatorReviewEscalationDispatchStore()
    )
    if case is not None:
        case_store.save(case)
    if escalation is not None:
        escalation_store.save(escalation)
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    operations.register_unified_operation_routes(
        app,
        worker_heartbeat_stores={"nex-ag": InMemoryWorkerHeartbeatStore()},
        operator_review_case_store=case_store,
        operator_review_escalation_store=escalation_store,
        operator_review_escalation_dispatch_store=dispatch_store,
    )
    return TestClient(app), case_store, escalation_store, dispatch_store


def request_payload(**overrides: object) -> dict[str, Any]:
    return {
        "case_id": "case-0844",
        "escalation_id": "escalation-0844",
        "channel_type": "MOCK",
        "provider_profile": "mock-default",
        **overrides,
    }


def test_delivery_route_is_protected_persists_and_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED", "1")
    client, _case_store, _escalation_store, dispatch_store = build_client(
        case=case_record(),
        escalation=escalation_record(),
    )

    assert client.post(PATH, json=request_payload()).status_code == 401
    created = client.post(PATH, json=request_payload(), headers=auth_headers())
    replayed = client.post(PATH, json=request_payload(), headers=auth_headers())

    assert created.status_code == 201
    assert created.json()["idempotency_status"] == "NEW"
    assert created.json()["delivery"] == {
        "dispatch_persistence_performed": True,
        "provider_invocation_performed": False,
    }
    assert created.json()["delivery_route"]["protected"] is True
    assert replayed.status_code == 200
    assert replayed.json()["idempotency_status"] == "REPLAYED"
    assert replayed.json()["delivery"]["dispatch_persistence_performed"] is False
    assert len(dispatch_store.records) == 1


@pytest.mark.parametrize(
    ("payload", "headers", "error_code"),
    [
        (
            None,
            auth_headers(),
            "ag.recovery_notification_delivery_payload_invalid",
        ),
        (
            {"escalation_id": "escalation-0844"},
            auth_headers(),
            "ag.recovery_notification_delivery_case_id_required",
        ),
        (
            {"case_id": "case-0844"},
            auth_headers(),
            "ag.recovery_notification_delivery_escalation_id_required",
        ),
        (
            request_payload(),
            auth_headers(idempotency_key=None),
            "ag.recovery_notification_delivery_idempotency_key_required",
        ),
        (
            request_payload(),
            auth_headers(idempotency_key="x" * 201),
            "ag.recovery_notification_delivery_idempotency_key_invalid",
        ),
    ],
)
def test_delivery_route_validates_request(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any] | None,
    headers: dict[str, str],
    error_code: str,
) -> None:
    monkeypatch.setenv("NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED", "1")
    client, *_ = build_client(case=case_record(), escalation=escalation_record())

    response = client.post(PATH, json=payload, headers=headers)

    assert response.status_code == 422
    assert response.json()["error_code"] == error_code


@pytest.mark.parametrize(
    ("case", "escalation", "error_code", "status_code"),
    [
        (
            None,
            escalation_record(),
            "ag.recovery_notification_delivery_case_not_found",
            404,
        ),
        (
            case_record(),
            None,
            "ag.recovery_notification_delivery_escalation_not_found",
            404,
        ),
        (
            case_record(),
            escalation_record(case_id="other-case"),
            "ag.recovery_notification_delivery_context_mismatch",
            409,
        ),
    ],
)
def test_delivery_route_requires_existing_matching_context(
    monkeypatch: pytest.MonkeyPatch,
    case: dict[str, Any] | None,
    escalation: dict[str, Any] | None,
    error_code: str,
    status_code: int,
) -> None:
    monkeypatch.setenv("NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED", "1")
    client, *_ = build_client(case=case, escalation=escalation)

    response = client.post(PATH, json=request_payload(), headers=auth_headers())

    assert response.status_code == status_code
    assert response.json()["error_code"] == error_code


def test_delivery_route_rejects_disabled_policy_and_live_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, *_ = build_client(case=case_record(), escalation=escalation_record())

    disabled = client.post(PATH, json=request_payload(), headers=auth_headers())
    assert disabled.status_code == 409
    assert disabled.json()["error_code"] == (
        "ag.recovery_notification_delivery_not_authorized"
    )

    monkeypatch.setenv("NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED", "1")
    live = client.post(
        PATH,
        json=request_payload(channel_type="NOTIFICATION"),
        headers=auth_headers(idempotency_key="idem-0844-live"),
    )
    assert live.status_code == 409
    assert live.json()["error_code"] == (
        "ag.recovery_notification_dispatch_handoff_blocked"
    )


def test_delivery_route_detects_idempotency_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED", "1")
    client, *_ = build_client(case=case_record(), escalation=escalation_record())

    created = client.post(PATH, json=request_payload(), headers=auth_headers())
    conflict = client.post(
        PATH,
        json=request_payload(provider_profile="different-profile"),
        headers=auth_headers(),
    )

    assert created.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == (
        "ag.recovery_notification_delivery_idempotency_conflict"
    )


def test_delivery_route_returns_preview_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED", "1")
    client, *_ = build_client(case=case_record(), escalation=escalation_record())

    response = client.post(
        PATH,
        params={"worker_id": " "},
        json=request_payload(),
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == (
        "ag.operator_review_dispatch_daemon_liveness_worker_id_invalid"
    )


def test_delivery_read_route_is_protected_and_filters_recovery_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED", "1")
    client, *_ = build_client(case=case_record(), escalation=escalation_record())

    assert client.get(PATH).status_code == 401
    created = client.post(PATH, json=request_payload(), headers=auth_headers())
    response = client.get(PATH, headers=auth_headers())

    assert created.status_code == 201
    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_status"] == "READY"
    assert payload["summary"]["total"] == 1
    assert payload["recent"][0]["dispatch_id"] == (
        created.json()["dispatch_record"]["dispatch_id"]
    )
    assert payload["read_route"] == {
        "path": PATH,
        "method": "GET",
        "protected": True,
        "mutation": False,
    }


def test_delivery_read_route_normalizes_store_error() -> None:
    class FailingDispatchStore:
        def list_dispatches(self, **_kwargs):
            raise OperatorReviewNoteError(
                status_code=503,
                error_code="ag.operator_review_case_store_unavailable",
                detail="dispatch source unavailable",
            )

    client, *_ = build_client(dispatch_store_override=FailingDispatchStore())

    response = client.get(PATH, headers=auth_headers())

    assert response.status_code == 503
    assert response.json()["error_code"] == (
        "ag.operator_review_case_store_unavailable"
    )
