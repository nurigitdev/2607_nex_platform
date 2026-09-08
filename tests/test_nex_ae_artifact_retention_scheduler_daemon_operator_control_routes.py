from __future__ import annotations

import json

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_FACADE_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POLICY_SCHEMA_VERSION,
)
from test_nex_ae_artifacts import auth_headers, build_client_with_artifact_store


REQUESTED_AT = "2026-09-08T06:00:00Z"
CHECKED_AT = "2026-09-08T06:00:08Z"
SUBJECT = {
    "actor_type": "operator",
    "actor_id": "employee-1001",
    "tenant_id": "tenant-a",
    "workspace_id": "workspace-a",
    "service_id": "nex-ag",
}


def approval(reason: str) -> dict[str, object]:
    return {
        "approved": True,
        "approved_by": dict(SUBJECT),
        "approved_at": REQUESTED_AT,
        "reason": reason,
    }


def test_scheduler_daemon_operator_control_policy_route_is_authenticated() -> None:
    client, _, _, _ = build_client_with_artifact_store()

    unauthorized = client.get(
        "/api/v1/artifact-retention/scheduler-daemon-operator-control-policy"
    )
    invalid_checked_at = client.get(
        "/api/v1/artifact-retention/scheduler-daemon-operator-control-policy",
        params={"checked_at": "bad"},
        headers=auth_headers(),
    )
    response = client.get(
        "/api/v1/artifact-retention/scheduler-daemon-operator-control-policy",
        params={"checked_at": CHECKED_AT},
        headers=auth_headers(),
    )
    payload = response.json()
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert unauthorized.status_code == 401
    assert invalid_checked_at.status_code == 422
    assert invalid_checked_at.json()["error_code"] == (
        "ae.artifact_retention_timestamp_invalid"
    )
    assert response.status_code == 200
    assert payload["operator_control_policy_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POLICY_SCHEMA_VERSION
    )
    assert payload["checked_at"] == CHECKED_AT
    assert payload["supported_actions"][0]["action"] == "status_probe"
    assert payload["guardrails"]["ag_direct_process_control_allowed"] is False
    assert payload["metadata"]["policy_contract_only"] is True
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "nuri1004" not in serialized


def test_scheduler_daemon_operator_control_preview_route_returns_facade() -> None:
    client, _, _, _ = build_client_with_artifact_store()

    unauthorized = client.post(
        "/api/v1/artifact-retention/scheduler-daemon-operator-control-preview",
        json={"action": "status_probe"},
    )
    response = client.post(
        "/api/v1/artifact-retention/scheduler-daemon-operator-control-preview",
        json={
            "action": "status_probe",
            "operator_subject": SUBJECT,
            "reason": "operator status check",
            "requested_at": REQUESTED_AT,
            "checked_at": CHECKED_AT,
        },
        headers={
            **auth_headers(),
            "Idempotency-Key": "idem-route-0585-status",
        },
    )
    payload = response.json()
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert payload["operator_control_facade_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_FACADE_SCHEMA_VERSION
    )
    assert payload["action"] == "status_probe"
    assert payload["facade_status"] == "READY"
    assert payload["operator_control_request"]["operator_subject"] == SUBJECT
    assert payload["operator_control_request"]["idempotency_key"] == (
        "idem-route-0585-status"
    )
    assert payload["operator_control_admission"]["admission_status"] == "READY"
    assert payload["operator_control_command_preview"]["metadata"][
        "command_preview_count"
    ] == 1
    assert payload["guardrails"]["preview_only"] is True
    assert payload["guardrails"]["supervisor_adapter_invoked"] is False
    assert payload["metadata"]["database_write_performed"] is False
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "nuri1004" not in serialized
    assert "ed6@c496em" not in serialized


def test_scheduler_daemon_operator_control_preview_supports_requested_by_fallback() -> None:
    client, _, _, _ = build_client_with_artifact_store()

    response = client.post(
        "/api/v1/artifact-retention/scheduler-daemon-operator-control-preview",
        json={
            "action": "start_daemon",
            "requested_by": {
                **SUBJECT,
                "request_id": "route-request-id-should-not-leak",
            },
            "reason": "operator start request",
            "requested_at": REQUESTED_AT,
            "checked_at": CHECKED_AT,
            "enabled": True,
            "explicit_opt_in": True,
            "max_cycles": "3",
            "run_worker": True,
            "approval": approval("operator start request"),
        },
        headers={
            **auth_headers(),
            "Idempotency-Key": "idem-route-0585-start",
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["facade_status"] == "READY"
    assert payload["operator_control_request"]["operator_subject"] == SUBJECT
    assert payload["operator_control_command_preview"]["metadata"][
        "start_preview_count"
    ] == 1
    assert payload["metadata"]["supervisor_actions"] == ["start_daemon"]
    assert "request_id" not in payload["operator_control_request"][
        "operator_subject"
    ]


def test_scheduler_daemon_operator_control_preview_defaults_service_subject() -> None:
    client, _, _, _ = build_client_with_artifact_store()

    response = client.post(
        "/api/v1/artifact-retention/scheduler-daemon-operator-control-preview",
        json={
            "action": "status_probe",
            "reason": "operator status check",
            "requested_at": REQUESTED_AT,
            "checked_at": CHECKED_AT,
            "idempotency_key": "idem-route-0585-default-subject",
        },
        headers=auth_headers(),
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["operator_control_request"]["operator_subject"] == {
        "actor_type": "service",
        "actor_id": "nex-ag",
        "service_id": "nex-ag",
    }
    assert payload["facade_status"] == "READY"
    assert payload["metadata"]["supervisor_actions"] == ["status_probe"]


def test_scheduler_daemon_operator_control_preview_decomposes_restart() -> None:
    client, _, _, _ = build_client_with_artifact_store()

    response = client.post(
        "/api/v1/artifact-retention/scheduler-daemon-operator-control-preview",
        json={
            "action": "restart_daemon",
            "operator_subject": SUBJECT,
            "reason": "operator restart request",
            "requested_at": REQUESTED_AT,
            "checked_at": CHECKED_AT,
            "enabled": True,
            "explicit_opt_in": True,
            "approval": approval("operator restart request"),
            "current_process": {
                "process_status": "RUNNING",
                "process_id": 6251,
                "host_id": "ae-node-route",
                "observed_at": CHECKED_AT,
            },
        },
        headers={
            **auth_headers(),
            "Idempotency-Key": "idem-route-0585-restart",
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["facade_status"] == "READY"
    assert payload["guardrails"]["restart_decomposes_to_stop_then_start"] is True
    assert payload["metadata"]["command_preview_count"] == 2
    assert payload["metadata"]["supervisor_actions"] == [
        "stop_daemon",
        "start_daemon",
    ]
    assert payload["operator_control_command_preview"][
        "supervisor_command_previews"
    ][1]["requires_follow_up_admission"] is True


def test_scheduler_daemon_operator_control_preview_rejects_invalid_payloads() -> None:
    client, _, _, _ = build_client_with_artifact_store()

    missing_idempotency = client.post(
        "/api/v1/artifact-retention/scheduler-daemon-operator-control-preview",
        json={
            "action": "status_probe",
            "operator_subject": SUBJECT,
            "reason": "operator status check",
            "requested_at": REQUESTED_AT,
        },
        headers={
            key: value
            for key, value in auth_headers().items()
            if key != "Idempotency-Key"
        },
    )
    invalid_bool = client.post(
        "/api/v1/artifact-retention/scheduler-daemon-operator-control-preview",
        json={
            "action": "status_probe",
            "operator_subject": SUBJECT,
            "reason": "operator status check",
            "requested_at": REQUESTED_AT,
            "idempotency_key": "idem-route-invalid-bool",
            "run_worker": "yes",
        },
        headers=auth_headers(),
    )
    invalid_subject = client.post(
        "/api/v1/artifact-retention/scheduler-daemon-operator-control-preview",
        json={
            "action": "status_probe",
            "operator_subject": {
                **SUBJECT,
                "request_id": "not-allowed-on-explicit-subject",
            },
            "reason": "operator status check",
            "requested_at": REQUESTED_AT,
            "idempotency_key": "idem-route-invalid-subject",
        },
        headers=auth_headers(),
    )
    invalid_requested_by = client.post(
        "/api/v1/artifact-retention/scheduler-daemon-operator-control-preview",
        json={
            "action": "status_probe",
            "requested_by": "nex-ag",
            "reason": "operator status check",
            "requested_at": REQUESTED_AT,
            "idempotency_key": "idem-route-invalid-requested-by",
        },
        headers=auth_headers(),
    )

    assert missing_idempotency.status_code == 422
    assert missing_idempotency.json()["error_code"] == (
        "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid"
    )
    assert invalid_bool.status_code == 422
    assert "run_worker" in invalid_bool.json()["detail"]
    assert invalid_subject.status_code == 422
    assert "operator subject keys" in invalid_subject.json()["detail"]
    assert invalid_requested_by.status_code == 422
    assert "operator subject is invalid" in invalid_requested_by.json()["detail"]
