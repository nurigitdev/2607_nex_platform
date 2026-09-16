from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from nex_ag.operations import (
    AG_OPERATOR_REVIEW_DISPATCH_DAEMON_LIVENESS_ACK_EXPIRY_EVENT_FAILED,
    AG_OPERATOR_REVIEW_DISPATCH_DAEMON_LIVENESS_ACK_EXPIRY_EVENT_RECONCILED,
    AG_OPERATOR_REVIEW_DISPATCH_DAEMON_LIVENESS_ACK_EXPIRY_EVENT_REJECTED,
    build_operator_review_liveness_ack_expiry_audit_event_details,
    emit_operator_review_liveness_ack_expiry_audit_event,
    register_unified_operation_routes,
)
from nex_ag.operator_review_liveness_ack import (
    OperatorReviewLivenessAckStateError,
    OperatorReviewLivenessAckStateStore,
    build_operator_review_liveness_ack_state_record,
)
from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


ROUTE = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/"
    "ack-states/reconcile-expired"
)


def headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "req-0815",
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    }


def expired_state() -> dict[str, Any]:
    return build_operator_review_liveness_ack_state_record(
        ack_state_id="ack-expiry-api",
        acknowledgement_key="nex-ag:dispatch-daemon:stale",
        service_id="nex-ag",
        worker_id="dispatch-daemon",
        worker_type="operator_review_dispatch_daemon",
        liveness_status="STALE",
        action="suppress_for_ttl",
        state_status="SUPPRESSED",
        operator_ref={"operator_type": "user", "operator_id": "employee-1"},
        reason_codes=["planned-maintenance"],
        comment="must not enter audit event",
        idempotency_key="must-not-enter-audit-event",
        requested_ttl_seconds=1800,
        suppressed_until="2026-09-17T01:30:00Z",
        created_at="2026-09-17T01:00:00Z",
        updated_at="2026-09-17T01:00:00Z",
    )


def client_with_store(
    store: Any,
) -> tuple[TestClient, InMemoryOperationalEventStore]:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    event_store = InMemoryOperationalEventStore()
    register_unified_operation_routes(
        app,
        event_store=event_store,
        operator_review_liveness_ack_state_store=store,
    )
    return TestClient(app), event_store


def test_ack_expiry_reconcile_route_applies_and_audits() -> None:
    store = OperatorReviewLivenessAckStateStore()
    store.save(expired_state())
    client, events = client_with_store(store)

    response = client.post(
        ROUTE,
        headers=headers(),
        json={"observed_at": "2026-09-17T02:00:00Z", "limit": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_status"] == "COMPLETED"
    assert payload["applied_count"] == 1
    assert payload["route"] == {
        "path": ROUTE,
        "method": "POST",
        "protected": True,
    }
    assert payload["audit_event"]["ok"] is True
    assert store.get("ack-expiry-api")["state_status"] == "EXPIRED"
    records = events.list_events(
        event_type=(
            AG_OPERATOR_REVIEW_DISPATCH_DAEMON_LIVENESS_ACK_EXPIRY_EVENT_RECONCILED
        )
    )
    assert len(records) == 1
    assert records[0]["details"]["applied_count"] == 1
    assert records[0]["details"]["redaction"]["outcomes_included"] is False
    serialized = str(records[0])
    assert "must not enter audit event" not in serialized
    assert "must-not-enter-audit-event" not in serialized


def test_ack_expiry_reconcile_route_requires_authentication() -> None:
    client, _events = client_with_store(OperatorReviewLivenessAckStateStore())

    response = client.post(ROUTE, json={})

    assert response.status_code == 401


def test_ack_expiry_reconcile_route_rejects_invalid_payload_and_audits() -> None:
    client, events = client_with_store(OperatorReviewLivenessAckStateStore())

    response = client.post(
        ROUTE,
        headers=headers(),
        json={"observed_at": "not-a-time"},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == (
        "ag.operator_review_liveness_ack_datetime_invalid"
    )
    assert len(
        events.list_events(
            event_type=(
                AG_OPERATOR_REVIEW_DISPATCH_DAEMON_LIVENESS_ACK_EXPIRY_EVENT_REJECTED
            )
        )
    ) == 1


def test_ack_expiry_reconcile_route_reports_store_failure() -> None:
    class BrokenStore:
        def list_expiry_candidates(self, **_kwargs: Any) -> list[dict[str, Any]]:
            raise OperatorReviewLivenessAckStateError(
                "store unavailable",
                error_code="ag.operator_review_liveness_ack_state_store_unavailable",
                status_code=503,
            )

    client, events = client_with_store(BrokenStore())

    response = client.post(ROUTE, headers=headers(), json={})

    assert response.status_code == 503
    assert len(
        events.list_events(
            event_type=(
                AG_OPERATOR_REVIEW_DISPATCH_DAEMON_LIVENESS_ACK_EXPIRY_EVENT_FAILED
            )
        )
    ) == 1


def test_ack_expiry_audit_helpers_cover_unconfigured_and_error_paths() -> None:
    missing = emit_operator_review_liveness_ack_expiry_audit_event(
        None,
        request_id="req-0815",
        trace_id=None,
    )
    details = build_operator_review_liveness_ack_expiry_audit_event_details(
        result={
            "run_status": "COMPLETED_WITH_CONFLICTS",
            "candidate_count": "2",
            "applied_count": 1,
            "conflict_count": 1,
            "skipped_count": None,
        }
    )
    event_store = InMemoryOperationalEventStore()
    emitted = emit_operator_review_liveness_ack_expiry_audit_event(
        OperationalEventEmitter(service_id="nex-ag", store=event_store),
        request_id="req-0815",
        trace_id=None,
        error=OperatorReviewLivenessAckStateError(
            "bad request",
            error_code="bad-request",
            status_code=400,
        ),
    )

    assert missing.ok is False
    assert missing.error_code.endswith("audit_not_configured")
    assert details["candidate_count"] == 2
    assert details["skipped_count"] == 0
    assert emitted.ok is True
