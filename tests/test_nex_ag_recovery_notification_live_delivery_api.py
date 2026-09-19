from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import nex_ag.operations as operations
import nex_ag.recovery_notification_delivery as delivery
from nex_ag.operator_review_cases import (
    OperatorReviewCaseStore,
    OperatorReviewEscalationDispatchStore,
    OperatorReviewEscalationStore,
)
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


def auth_headers(key: str = "idem-0854") -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "Idempotency-Key": key,
    }


def case_record() -> dict[str, Any]:
    return {
        "case_id": "case-0854",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
    }


def escalation_record() -> dict[str, Any]:
    return {
        "escalation_id": "escalation-0854",
        "candidate_id": "candidate-0854",
        "case_id": "case-0854",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
        "escalation_status": "ACTIVE",
        "escalation_level": "ATTENTION",
        "sla_state": "WARNING",
        "reason_codes": ["daemon_missing"],
        "runbook_ids": ["ag.dispatch_daemon.recover.v1"],
        "recommended_actions": ["inspect_dispatch_daemon"],
    }


def build_client() -> tuple[TestClient, OperatorReviewEscalationDispatchStore]:
    case_store = OperatorReviewCaseStore()
    escalation_store = OperatorReviewEscalationStore()
    dispatch_store = OperatorReviewEscalationDispatchStore()
    case_store.save(case_record())
    escalation_store.save(escalation_record())
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    operations.register_unified_operation_routes(
        app,
        worker_heartbeat_stores={"nex-ag": InMemoryWorkerHeartbeatStore()},
        operator_review_case_store=case_store,
        operator_review_escalation_store=escalation_store,
        operator_review_escalation_dispatch_store=dispatch_store,
    )
    return TestClient(app), dispatch_store


def live_payload(**overrides: object) -> dict[str, Any]:
    return {
        "case_id": "case-0854",
        "escalation_id": "escalation-0854",
        "channel_type": "NOTIFICATION",
        "provider_profile": "notification-webhook-default",
        "confirm_live_delivery": True,
        **overrides,
    }


def enable_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED", "1")


def enable_live_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE", "live_http")
    monkeypatch.setenv("NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE", "1")
    monkeypatch.setenv(
        "NEX_AG_NOTIFICATION_WEBHOOK_URL",
        "http://127.0.0.1:18554/recovery-notification",
    )
    monkeypatch.setenv("NEX_AG_NOTIFICATION_SERVICE_TOKEN", "token-0854")


def test_live_delivery_api_persists_without_invocation_and_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_policy(monkeypatch)
    enable_live_provider(monkeypatch)
    client, store = build_client()

    assert client.post(PATH, json=live_payload()).status_code == 401
    created = client.post(PATH, json=live_payload(), headers=auth_headers())
    replayed = client.post(PATH, json=live_payload(), headers=auth_headers())

    assert created.status_code == 201
    assert replayed.status_code == 200
    assert created.json()["idempotency_status"] == "NEW"
    assert replayed.json()["idempotency_status"] == "REPLAYED"
    assert created.json()["dispatch_record"]["dispatch_status"] == "PENDING"
    assert created.json()["dispatch_record"]["channel_type"] == "NOTIFICATION"
    assert created.json()["live_delivery"] == {
        "requested": True,
        "admitted": True,
        "provider_mode": "live_http",
        "provider_invocation_performed": False,
    }
    serialized = str(created.json())
    assert "127.0.0.1" not in serialized
    assert "token-0854" not in serialized
    assert len(store.records) == 1


def test_live_delivery_api_requires_explicit_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_policy(monkeypatch)
    enable_live_provider(monkeypatch)
    client, _store = build_client()

    response = client.post(
        PATH,
        json=live_payload(confirm_live_delivery=False),
        headers=auth_headers(),
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == (
        "ag.recovery_notification_live_confirmation_required"
    )


def test_live_delivery_api_validates_confirmation_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_policy(monkeypatch)
    client, _store = build_client()

    response = client.post(
        PATH,
        json=live_payload(confirm_live_delivery="yes"),
        headers=auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == (
        "ag.recovery_notification_delivery_live_confirmation_invalid"
    )


@pytest.mark.parametrize(
    ("setup", "error_code"),
    [
        ("disabled", "ag.recovery_notification_live_provider_not_enabled"),
        ("missing_endpoint", "ag.recovery_notification_live_endpoint_required"),
    ],
)
def test_live_delivery_api_requires_provider_readiness(
    monkeypatch: pytest.MonkeyPatch,
    setup: str,
    error_code: str,
) -> None:
    enable_policy(monkeypatch)
    if setup == "missing_endpoint":
        monkeypatch.setenv("NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE", "live_http")
        monkeypatch.setenv("NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE", "1")
    client, store = build_client()

    response = client.post(PATH, json=live_payload(), headers=auth_headers())

    assert response.status_code == 409
    assert response.json()["error_code"] == error_code
    assert store.records == {}


def test_live_delivery_api_rejects_profile_channel_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_policy(monkeypatch)
    enable_live_provider(monkeypatch)
    client, store = build_client()

    response = client.post(
        PATH,
        json=live_payload(provider_profile="email-notification-default"),
        headers=auth_headers(),
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == (
        "ag.recovery_notification_live_profile_channel_mismatch"
    )
    assert store.records == {}


def test_mock_delivery_ignores_live_confirmation_and_remains_non_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_policy(monkeypatch)
    client, _store = build_client()

    response = client.post(
        PATH,
        json=live_payload(
            channel_type="MOCK",
            provider_profile="mock-default",
            confirm_live_delivery=True,
        ),
        headers=auth_headers("idem-0854-mock"),
    )

    assert response.status_code == 201
    assert response.json()["live_delivery"] == {
        "requested": False,
        "admitted": False,
        "provider_mode": None,
        "provider_invocation_performed": False,
    }


def test_persistence_still_rejects_blocked_live_handoff() -> None:
    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.persist_recovery_notification_dispatch_handoff(
            {
                "dispatch_handoff_schema_version": (
                    delivery.RECOVERY_NOTIFICATION_DISPATCH_HANDOFF_SCHEMA_VERSION
                ),
                "handoff_status": "BLOCKED",
                "dispatch_record": None,
            },
            object(),
        )

    assert exc_info.value.error_code == (
        "ag.recovery_notification_dispatch_handoff_blocked"
    )
    assert exc_info.value.status_code == 409
