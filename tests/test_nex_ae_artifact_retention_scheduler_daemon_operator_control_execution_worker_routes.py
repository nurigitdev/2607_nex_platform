from __future__ import annotations

import json

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_SCHEMA_VERSION,
    SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore,
)
from test_nex_ae_artifact_retention_scheduler_daemon_operator_control_routes import (
    CHECKED_AT,
    REQUESTED_AT,
    SUBJECT,
    approval,
)
from test_nex_ae_artifacts import (
    auth_headers,
    build_client_with_artifact_store,
    sqlite_artifact_session_factory,
)


EXECUTION_ROUTE = (
    "/api/v1/artifact-retention/scheduler-daemon-operator-control-executions"
)
WORKER_ROUTE = (
    "/api/v1/artifact-retention/"
    "scheduler-daemon-operator-control-execution-workers"
)


def ready_execution_payload(
    *,
    idempotency_key: str,
    persist_execution_state: bool = False,
) -> dict[str, object]:
    return {
        "action": "start_daemon",
        "operator_subject": SUBJECT,
        "reason": "operator start execution worker route",
        "requested_at": REQUESTED_AT,
        "checked_at": CHECKED_AT,
        "observed_at": "2026-09-08T07:10:20Z",
        "execution_mode": "fake_dry_run_supervisor_persistent_dispatch",
        "enabled": True,
        "explicit_opt_in": True,
        "max_cycles": 3,
        "run_worker": True,
        "approval": approval("operator start execution worker route"),
        "persist_execution_state": persist_execution_state,
        "idempotency_key": idempotency_key,
    }


def assert_safe_worker_payload(payload: dict[str, object]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert "postgresql://" not in serialized
    assert "postgresql+psycopg://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "nuri1004" not in serialized
    assert "ed6@c496em" not in serialized
    assert '"raw_artifact_payload_included": true' not in serialized
    assert '"raw_daemon_runtime_payload_included": true' not in serialized


def test_operator_control_execution_worker_route_runs_fake_worker_from_state() -> None:
    client, _, _, _ = build_client_with_artifact_store()
    state = client.post(
        EXECUTION_ROUTE,
        json=ready_execution_payload(idempotency_key="idem-route-0605-object"),
        headers=auth_headers(),
    ).json()

    unauthorized = client.post(
        WORKER_ROUTE,
        json={"operator_control_execution_state": state},
    )
    response = client.post(
        WORKER_ROUTE,
        json={
            "operator_control_execution_state": state,
            "planned_at": "2026-09-08T07:10:30Z",
            "commanded_at": "2026-09-08T07:10:40Z",
            "worker_observed_at": "2026-09-08T07:10:50Z",
        },
        headers=auth_headers(),
    )
    payload = response.json()

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert payload["operator_control_execution_worker_result_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_SCHEMA_VERSION
    )
    assert payload["worker_status"] == "SUCCEEDED"
    assert payload["decision_reason"] == "fake_dry_run_worker_completed"
    assert payload["operator_control_execution_state_id"] == (
        state["operator_control_execution_state_id"]
    )
    assert payload["operator_control_execution_worker_command"][
        "command_status"
    ] == "READY"
    assert payload["operator_control_execution_worker_command"][
        "commanded_at"
    ] == "2026-09-08T07:10:40Z"
    planned_transitions = payload["operator_control_execution_worker_transition_plan"][
        "planned_transitions"
    ]
    assert [
        (item["from_status"], item["to_status"], item["terminal"])
        for item in planned_transitions
    ] == [
        ("ADMITTED", "EXECUTING", False),
        ("EXECUTING", "SUCCEEDED", True),
    ]
    assert payload["supervisor_result_count"] == 1
    assert payload["guardrails"]["fake_dry_run_worker_only"] is True
    assert payload["guardrails"]["supervisor_adapter_invoked"] is True
    assert payload["guardrails"]["database_write_performed"] is False
    assert payload["guardrails"]["subprocess_started"] is False
    assert payload["metadata"]["worker_execution_performed"] is True
    assert_safe_worker_payload(payload)


def test_operator_control_execution_worker_route_reads_state_by_id_from_store() -> None:
    store = SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
        sqlite_artifact_session_factory()
    )
    client, _, _, _ = build_client_with_artifact_store(
        retention_scheduler_daemon_operator_control_execution_store=store,
    )
    state = client.post(
        EXECUTION_ROUTE,
        json=ready_execution_payload(
            idempotency_key="idem-route-0605-state-id",
            persist_execution_state=True,
        ),
        headers=auth_headers(),
    ).json()

    response = client.post(
        WORKER_ROUTE,
        json={
            "operator_control_execution_state_id": state[
                "operator_control_execution_state_id"
            ],
            "checked_at": "2026-09-08T07:11:00Z",
            "worker_observed_at": "2026-09-08T07:11:10Z",
        },
        headers=auth_headers(),
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["operator_control_execution_state_id"] == (
        state["operator_control_execution_state_id"]
    )
    assert payload["operator_control_execution_worker_command"][
        "commanded_at"
    ] == "2026-09-08T07:11:00Z"
    assert payload["operator_control_execution_worker_transition_plan"][
        "terminal_status"
    ] == "SUCCEEDED"
    assert payload["metadata"]["database_write_performed"] is False
    assert_safe_worker_payload(payload)


def test_operator_control_execution_worker_route_returns_blocked_for_contract_only() -> None:
    client, _, _, _ = build_client_with_artifact_store()
    state = client.post(
        EXECUTION_ROUTE,
        json={
            **ready_execution_payload(idempotency_key="idem-route-0605-blocked"),
            "execution_mode": "contract_only",
            "persist_execution_state": False,
        },
        headers=auth_headers(),
    ).json()

    response = client.post(
        WORKER_ROUTE,
        json={"operator_control_execution_state": state},
        headers=auth_headers(),
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["worker_status"] == "BLOCKED"
    assert payload["supervisor_result_count"] == 0
    assert payload["supervisor_results"] == []
    assert payload["guardrails"]["worker_execution_performed"] is False
    assert payload["guardrails"]["supervisor_adapter_invoked"] is False
    assert payload["operator_control_execution_worker_transition_plan"][
        "planned_transitions"
    ] == []
    assert_safe_worker_payload(payload)


def test_operator_control_execution_worker_route_rejects_missing_state_inputs() -> None:
    client, _, _, _ = build_client_with_artifact_store()
    store = SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
        sqlite_artifact_session_factory()
    )
    client_with_store, _, _, _ = build_client_with_artifact_store(
        retention_scheduler_daemon_operator_control_execution_store=store,
    )

    missing_state = client.post(WORKER_ROUTE, json={}, headers=auth_headers())
    store_unavailable = client.post(
        WORKER_ROUTE,
        json={"operator_control_execution_state_id": "missing-state"},
        headers=auth_headers(),
    )
    not_found = client_with_store.post(
        WORKER_ROUTE,
        json={"operator_control_execution_state_id": "missing-state"},
        headers=auth_headers(),
    )
    invalid_state = client.post(
        WORKER_ROUTE,
        json={"operator_control_execution_state": {"bad": "state"}},
        headers=auth_headers(),
    )

    assert missing_state.status_code == 422
    assert missing_state.json()["error_code"] == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_request_invalid"
    )
    assert store_unavailable.status_code == 503
    assert store_unavailable.json()["error_code"] == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_store_unavailable"
    )
    assert not_found.status_code == 404
    assert not_found.json()["error_code"] == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_not_found"
    )
    assert invalid_state.status_code == 422
    assert invalid_state.json()["error_code"] == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid"
    )
