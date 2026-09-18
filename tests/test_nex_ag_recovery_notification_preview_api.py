from __future__ import annotations

from fastapi.testclient import TestClient

import nex_ag.operations as operations
from nex_ag.operator_review_liveness_ack import (
    OperatorReviewLivenessAckStateStore,
    acknowledgement_key_for_liveness,
    build_operator_review_liveness_ack_state_record,
)
from nex_ag.recovery_notification_policy import RecoveryNotificationPolicyError
from nex_runtime import (
    InMemoryWorkerHeartbeatStore,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


PATH = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/"
    "recovery-notification-preview"
)
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {"Authorization": f"Bearer {issued.access_token}"}


def build_client(
    *,
    state_store: OperatorReviewLivenessAckStateStore | None = None,
) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    operations.register_unified_operation_routes(
        app,
        worker_heartbeat_stores={"nex-ag": InMemoryWorkerHeartbeatStore()},
        operator_review_liveness_ack_state_store=state_store,
    )
    return TestClient(app)


def test_recovery_notification_preview_route_is_protected_and_read_only() -> None:
    client = build_client()

    missing_auth = client.get(PATH)
    response = client.get(
        PATH,
        headers={
            **auth_headers(),
            "traceparent": (
                f"00-{TRACE_ID}-00f067aa0ba902b7-01"
            ),
        },
    )

    assert missing_auth.status_code == 401
    assert response.status_code == 200
    payload = response.json()
    assert payload["notification_plan_schema_version"] == (
        "ag_recovery_notification_plan.v1"
    )
    assert payload["plan_status"] == "PREVIEW_ONLY"
    assert payload["safe_payload"]["liveness_status"] == "MISSING"
    assert payload["safe_payload"]["severity"] == "ERROR"
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["delivery"]["performed"] is False
    assert payload["delivery"]["provider_invocation_performed"] is False
    assert payload["preview_route"] == {
        "path": PATH,
        "method": "GET",
        "protected": True,
        "mutation": False,
    }


def test_recovery_notification_preview_route_applies_active_suppression() -> None:
    state_store = OperatorReviewLivenessAckStateStore()
    state_store.save(
        build_operator_review_liveness_ack_state_record(
            ack_state_id="ack-state-0835",
            acknowledgement_key=acknowledgement_key_for_liveness(
                service_id="nex-ag",
                worker_id="ag-dispatch-execution-daemon",
                liveness_status="MISSING",
            ),
            service_id="nex-ag",
            worker_id="ag-dispatch-execution-daemon",
            worker_type="operator_review_dispatch_daemon",
            liveness_status="MISSING",
            action="suppress_for_ttl",
            state_status="SUPPRESSED",
            operator_ref={"operator_type": "user", "operator_id": "employee-0835"},
            reason_codes=["maintenance"],
            requested_ttl_seconds=600,
            suppressed_until="2999-01-01T00:00:00Z",
            created_at="2026-09-18T09:30:00Z",
            updated_at="2026-09-18T09:30:00Z",
        )
    )
    client = build_client(state_store=state_store)

    response = client.get(PATH, headers=auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan_status"] == "SUPPRESSED"
    assert payload["decision"]["effective_ack_state"] == "SUPPRESSED"
    assert payload["decision"]["reason_codes"] == ["active_suppression"]


def test_recovery_notification_preview_route_rejects_invalid_worker() -> None:
    client = build_client()

    response = client.get(
        PATH,
        params={"worker_id": " "},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == (
        "ag.operator_review_dispatch_daemon_liveness_worker_id_invalid"
    )


def test_recovery_notification_preview_route_normalizes_policy_error(
    monkeypatch,
) -> None:
    def fail(*_args, **_kwargs):
        raise RecoveryNotificationPolicyError(
            "invalid policy",
            error_code="ag.recovery_notification_test_invalid",
        )

    monkeypatch.setattr(operations, "build_recovery_notification_plan", fail)
    client = build_client()

    response = client.get(PATH, headers=auth_headers())

    assert response.status_code == 400
    assert response.json()["error_code"] == (
        "ag.recovery_notification_test_invalid"
    )
