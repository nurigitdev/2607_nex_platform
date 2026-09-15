from __future__ import annotations

import json

from fastapi.testclient import TestClient

from nex_ag.operations import (
    OperationsQueryError,
    emit_operator_review_liveness_ack_state_audit_event,
    register_unified_operation_routes,
)
from nex_ag.operator_review_dispatch_execution import (
    DISPATCH_EXECUTION_DAEMON_HEARTBEAT_SERVICE_ID,
    DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
)
from nex_ag.operator_review_liveness_ack import OperatorReviewLivenessAckStateStore
from nex_runtime import (
    IDLE,
    InMemoryOperationalEventStore,
    InMemoryWorkerHeartbeatStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
    build_worker_heartbeat,
    issue_mock_service_token,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "req-0804",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        "Idempotency-Key": "liveness-ack-idempotency-0804",
    }


def build_client() -> tuple[
    TestClient,
    OperatorReviewLivenessAckStateStore,
    InMemoryOperationalEventStore,
    InMemoryWorkerHeartbeatStore,
]:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    ack_store = OperatorReviewLivenessAckStateStore()
    event_store = InMemoryOperationalEventStore()
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    register_unified_operation_routes(
        app,
        event_store=event_store,
        operator_review_liveness_ack_state_store=ack_store,
        worker_heartbeat_stores={
            DISPATCH_EXECUTION_DAEMON_HEARTBEAT_SERVICE_ID: heartbeat_store
        },
    )
    return TestClient(app), ack_store, event_store, heartbeat_store


def upsert_dispatch_heartbeat(
    store: InMemoryWorkerHeartbeatStore,
    *,
    last_seen_at: str,
) -> None:
    store.upsert_heartbeat(
        build_worker_heartbeat(
            service_id=DISPATCH_EXECUTION_DAEMON_HEARTBEAT_SERVICE_ID,
            worker_id="ag-dispatch-execution-daemon",
            worker_type=DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
            status=IDLE,
            active_job_id=None,
            started_at="2019-01-01T00:00:00Z",
            last_seen_at=last_seen_at,
            metadata={"source": "slice-0804-test"},
        )
    )


def test_dispatch_liveness_ack_state_route_applies_and_audits() -> None:
    client, ack_store, event_store, heartbeat_store = build_client()
    upsert_dispatch_heartbeat(heartbeat_store, last_seen_at="2020-01-01T00:00:00Z")

    response = client.post(
        "/admin/v1/operator-review/dispatch-daemon/liveness/ack-state",
        headers=auth_headers(),
        json={
            "action": "suppress_for_ttl",
            "operator_ref": {
                "operator_type": "user",
                "operator_id": "employee-0804",
            },
            "reason_codes": ["planned-maintenance"],
            "comment": "suppress for scheduled daemon maintenance",
            "requested_ttl_seconds": 60,
            "observed_at": "2026-09-16T04:00:00Z",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    state = payload["state"]
    assert payload["mutation_status"] == "ACCEPTED"
    assert payload["liveness_summary"]["liveness_status"] == "STALE"
    assert payload["liveness_summary"]["source_projection_suppressed"] is False
    assert state["state_status"] == "SUPPRESSED"
    assert state["suppressed_until"] == "2026-09-16T04:01:00Z"
    assert ack_store.get_by_acknowledgement_key(
        "nex-ag:ag-dispatch-execution-daemon:stale"
    )["state_status"] == "SUPPRESSED"
    serialized = json.dumps(payload)
    assert "liveness-ack-idempotency-0804" not in serialized
    assert payload["audit_event"]["ok"] is True
    events = event_store.list_events(event_type=(
        "ag.operator_review_escalation_dispatch_daemon.liveness_ack_state.applied"
    ))
    assert len(events) == 1
    assert events[0]["details"]["redaction"]["raw_idempotency_key_included"] is False


def test_dispatch_liveness_ack_state_route_clears_by_acknowledgement_key() -> None:
    client, ack_store, _event_store, heartbeat_store = build_client()
    upsert_dispatch_heartbeat(heartbeat_store, last_seen_at="2020-01-01T00:00:00Z")
    first = client.post(
        "/admin/v1/operator-review/dispatch-daemon/liveness/ack-state",
        headers=auth_headers(),
        json={
            "action": "acknowledge_once",
            "operator_ref": {
                "operator_type": "user",
                "operator_id": "employee-0804",
            },
            "reason_codes": ["reviewed"],
            "observed_at": "2026-09-16T04:05:00Z",
        },
    )
    acknowledgement_key = first.json()["state"]["acknowledgement_key"]
    upsert_dispatch_heartbeat(heartbeat_store, last_seen_at="2099-01-01T00:00:00Z")

    response = client.post(
        "/admin/v1/operator-review/dispatch-daemon/liveness/ack-state",
        headers=auth_headers(),
        json={
            "action": "clear",
            "acknowledgement_key": acknowledgement_key,
            "operator_ref": {
                "operator_type": "user",
                "operator_id": "employee-0804",
            },
            "reason_codes": ["daemon-recovered"],
            "observed_at": "2026-09-16T04:10:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json()["state"]["state_status"] == "CLEARED"
    assert ack_store.get_by_acknowledgement_key(acknowledgement_key)[
        "state_status"
    ] == "CLEARED"


def test_dispatch_liveness_ack_state_route_rejects_without_auth() -> None:
    client, _ack_store, _event_store, heartbeat_store = build_client()
    upsert_dispatch_heartbeat(heartbeat_store, last_seen_at="2020-01-01T00:00:00Z")

    response = client.post(
        "/admin/v1/operator-review/dispatch-daemon/liveness/ack-state",
        json={"action": "acknowledge_once"},
    )

    assert response.status_code == 401


def test_dispatch_liveness_ack_state_route_rejects_bad_action_matrix() -> None:
    client, _ack_store, event_store, heartbeat_store = build_client()
    upsert_dispatch_heartbeat(heartbeat_store, last_seen_at="2020-01-01T00:00:00Z")

    response = client.post(
        "/admin/v1/operator-review/dispatch-daemon/liveness/ack-state",
        headers=auth_headers(),
        json={
            "action": "acknowledge_source_attention",
            "operator_ref": {
                "operator_type": "user",
                "operator_id": "employee-0804",
            },
            "reason_codes": ["wrong-action"],
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "ag.operator_review_liveness_ack_action_not_allowed"
    assert payload["details"]["audit_event"]["ok"] is True
    rejected_events = event_store.list_events(event_type=(
        "ag.operator_review_escalation_dispatch_daemon.liveness_ack_state.rejected"
    ))
    assert len(rejected_events) == 1


def test_dispatch_liveness_ack_state_route_rejects_blank_worker_id() -> None:
    client, _ack_store, event_store, _heartbeat_store = build_client()

    response = client.post(
        "/admin/v1/operator-review/dispatch-daemon/liveness/ack-state",
        params={"worker_id": "   "},
        headers=auth_headers(),
        json={
            "action": "acknowledge_once",
            "operator_ref": {
                "operator_type": "user",
                "operator_id": "employee-0804",
            },
            "reason_codes": ["bad-worker-id"],
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == (
        "ag.operator_review_dispatch_daemon_liveness_worker_id_invalid"
    )
    rejected_events = event_store.list_events(event_type=(
        "ag.operator_review_escalation_dispatch_daemon.liveness_ack_state.rejected"
    ))
    assert len(rejected_events) == 1


def test_dispatch_liveness_ack_state_route_rejects_bad_payload_shape() -> None:
    client, _ack_store, event_store, heartbeat_store = build_client()
    upsert_dispatch_heartbeat(heartbeat_store, last_seen_at="2020-01-01T00:00:00Z")

    response = client.post(
        "/admin/v1/operator-review/dispatch-daemon/liveness/ack-state",
        headers=auth_headers(),
        json={
            "action": "acknowledge_once",
            "operator_ref": ["not", "an", "object"],
            "reason_codes": ["bad-payload"],
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "ag.operator_review_liveness_ack_payload_invalid"
    rejected_events = event_store.list_events(event_type=(
        "ag.operator_review_escalation_dispatch_daemon.liveness_ack_state.rejected"
    ))
    assert len(rejected_events) == 1


def test_dispatch_liveness_ack_state_route_rejects_blank_action() -> None:
    client, _ack_store, event_store, heartbeat_store = build_client()
    upsert_dispatch_heartbeat(heartbeat_store, last_seen_at="2020-01-01T00:00:00Z")

    response = client.post(
        "/admin/v1/operator-review/dispatch-daemon/liveness/ack-state",
        headers=auth_headers(),
        json={
            "action": "   ",
            "operator_ref": {
                "operator_type": "user",
                "operator_id": "employee-0804",
            },
            "reason_codes": ["blank-action"],
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "ag.operator_review_liveness_ack_payload_invalid"
    rejected_events = event_store.list_events(event_type=(
        "ag.operator_review_escalation_dispatch_daemon.liveness_ack_state.rejected"
    ))
    assert len(rejected_events) == 1


def test_dispatch_liveness_ack_state_route_rejects_bad_reason_codes_shape() -> None:
    client, _ack_store, event_store, heartbeat_store = build_client()
    upsert_dispatch_heartbeat(heartbeat_store, last_seen_at="2020-01-01T00:00:00Z")

    response = client.post(
        "/admin/v1/operator-review/dispatch-daemon/liveness/ack-state",
        headers=auth_headers(),
        json={
            "action": "acknowledge_once",
            "operator_ref": {
                "operator_type": "user",
                "operator_id": "employee-0804",
            },
            "reason_codes": "not-a-list",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "ag.operator_review_liveness_ack_payload_invalid"
    rejected_events = event_store.list_events(event_type=(
        "ag.operator_review_escalation_dispatch_daemon.liveness_ack_state.rejected"
    ))
    assert len(rejected_events) == 1


def test_dispatch_liveness_ack_state_route_rejects_clear_missing_state() -> None:
    client, ack_store, event_store, heartbeat_store = build_client()
    upsert_dispatch_heartbeat(heartbeat_store, last_seen_at="2020-01-01T00:00:00Z")

    response = client.post(
        "/admin/v1/operator-review/dispatch-daemon/liveness/ack-state",
        headers=auth_headers(),
        json={
            "action": "clear",
            "acknowledgement_key": "nex-ag:ag-dispatch-execution-daemon:missing",
            "operator_ref": {
                "operator_type": "user",
                "operator_id": "employee-0804",
            },
            "reason_codes": ["not-found"],
        },
    )

    assert response.status_code == 404
    payload = response.json()
    assert payload["error_code"] == (
        "ag.operator_review_liveness_ack_clear_state_missing"
    )
    assert ack_store.records == {}
    rejected_events = event_store.list_events(event_type=(
        "ag.operator_review_escalation_dispatch_daemon.liveness_ack_state.rejected"
    ))
    assert len(rejected_events) == 1


def test_liveness_ack_state_audit_reports_missing_emitter() -> None:
    result = emit_operator_review_liveness_ack_state_audit_event(
        None,
        request_id="req-0804",
        trace_id=None,
    )

    assert result.ok is False
    assert result.error_code == (
        "ag.operator_review_liveness_ack_state_audit_not_configured"
    )
    assert result.status_code == 503


def test_liveness_ack_state_audit_emits_failed_event_for_server_error() -> None:
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ag", store=event_store)
    error = OperationsQueryError(
        error_code="ag.operator_review_liveness_ack_state_store_unavailable",
        detail="ack state store unavailable",
        status_code=503,
    )

    result = emit_operator_review_liveness_ack_state_audit_event(
        emitter,
        request_id="req-0804",
        trace_id=TRACE_ID,
        error=error,
    )

    assert result.ok is True
    assert result.event is not None
    assert result.event["event_type"] == (
        "ag.operator_review_escalation_dispatch_daemon.liveness_ack_state.failed"
    )
    assert result.event["severity"] == "ERROR"
    assert result.event["details"]["error_code"] == (
        "ag.operator_review_liveness_ack_state_store_unavailable"
    )
