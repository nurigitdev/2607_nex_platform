from __future__ import annotations

import json
from copy import deepcopy

import pytest

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POLICY_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_REQUEST_SCHEMA_VERSION,
    build_artifact_retention_scheduler_daemon_operator_control_policy,
    build_artifact_retention_scheduler_daemon_operator_control_request,
    operator_control_request_summary_line,
    summarize_artifact_retention_scheduler_daemon_operator_control_request,
    validate_artifact_retention_scheduler_daemon_operator_control_policy,
    validate_artifact_retention_scheduler_daemon_operator_control_request,
)
from nex_ae_api.artifacts import ArtifactHandoffError


REQUESTED_AT = "2026-09-08T02:00:00Z"
SUBJECT = {
    "actor_type": "operator",
    "actor_id": "employee-1001",
    "tenant_id": "tenant-a",
    "workspace_id": "workspace-a",
    "service_id": "nex-ag",
}


def approval(reason: str = "operator start request") -> dict[str, object]:
    return {
        "approved": True,
        "approved_by": dict(SUBJECT),
        "approved_at": REQUESTED_AT,
        "reason": reason,
    }


def test_operator_control_policy_is_metadata_only() -> None:
    policy = build_artifact_retention_scheduler_daemon_operator_control_policy(
        checked_at=REQUESTED_AT
    )
    serialized = json.dumps(policy, ensure_ascii=False, sort_keys=True)

    assert policy["operator_control_policy_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POLICY_SCHEMA_VERSION
    )
    assert policy["service_id"] == "nex-ae-api"
    assert policy["scheduler_id"] == "ae-artifact-retention-scheduler-local-v1"
    assert policy["supported_actions"] == [
        {
            "action": "status_probe",
            "mutates_process": False,
            "requires_approval": False,
            "requires_running_process": False,
            "starts_process": False,
            "stops_process": False,
        },
        {
            "action": "start_daemon",
            "mutates_process": True,
            "requires_approval": True,
            "requires_running_process": False,
            "starts_process": True,
            "stops_process": False,
        },
        {
            "action": "stop_daemon",
            "mutates_process": True,
            "requires_approval": False,
            "requires_running_process": True,
            "starts_process": False,
            "stops_process": True,
        },
        {
            "action": "restart_daemon",
            "mutates_process": True,
            "requires_approval": True,
            "requires_running_process": True,
            "starts_process": True,
            "stops_process": True,
        },
    ]
    assert policy["profile_policy"] == {
        "default_profile": "test",
        "allowed_profiles": ["test"],
        "production_profiles_allowed": False,
        "production_continuous_start_enabled": False,
    }
    assert policy["restart_policy"]["restart_semantics"] == "stop_then_start"
    assert policy["guardrails"]["ag_direct_process_control_allowed"] is False
    assert policy["metadata"]["policy_contract_only"] is True
    assert validate_artifact_retention_scheduler_daemon_operator_control_policy(
        policy
    ) == policy
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "nuri1004" not in serialized


def test_operator_control_status_probe_request_requires_operator_context() -> None:
    request = build_artifact_retention_scheduler_daemon_operator_control_request(
        action="STATUS_PROBE",
        operator_subject=SUBJECT,
        idempotency_key="idem-0582-status",
        reason="operator status check",
        requested_at=REQUESTED_AT,
    )
    summary = summarize_artifact_retention_scheduler_daemon_operator_control_request(
        request
    )

    assert request["operator_control_request_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_REQUEST_SCHEMA_VERSION
    )
    assert request["action"] == "status_probe"
    assert request["operator_subject"] == SUBJECT
    assert request["approval"] is None
    assert request["execution_intent"] == {
        "action": "status_probe",
        "mutates_process": False,
        "reads_status": True,
        "requests_start": False,
        "requests_stop": False,
        "restart_decomposes_to_stop_then_start": False,
        "requires_running_process": False,
        "requires_bounded_subprocess_adapter": False,
        "starts_continuous_loop": False,
        "enqueues_job_queue": False,
        "runs_worker": False,
        "physical_delete_enabled": False,
    }
    assert request["guardrails"]["approval_required"] is False
    assert request["metadata"]["approval_granted"] is False
    assert summary["mutates_process"] is False
    assert "mutates=0" in operator_control_request_summary_line(request)
    assert validate_artifact_retention_scheduler_daemon_operator_control_request(
        request
    ) == request


def test_operator_control_start_and_restart_require_approval_and_opt_in() -> None:
    start = build_artifact_retention_scheduler_daemon_operator_control_request(
        action="start_daemon",
        operator_subject=SUBJECT,
        idempotency_key="idem-0582-start",
        reason="operator start request",
        requested_at=REQUESTED_AT,
        enabled=True,
        explicit_opt_in=True,
        max_cycles="3",
        run_worker=True,
        approval=approval(),
    )
    restart = build_artifact_retention_scheduler_daemon_operator_control_request(
        action="restart_daemon",
        operator_subject=SUBJECT,
        idempotency_key="idem-0582-restart",
        reason="operator restart request",
        requested_at=REQUESTED_AT,
        enabled=True,
        explicit_opt_in=True,
        approval=approval("operator restart request"),
    )

    assert start["action"] == "start_daemon"
    assert start["enabled"] is True
    assert start["explicit_opt_in"] is True
    assert start["max_cycles"] == 3
    assert start["run_worker"] is True
    assert start["approval"]["approved"] is True
    assert start["execution_intent"]["requests_start"] is True
    assert start["execution_intent"]["requests_stop"] is False
    assert start["guardrails"]["explicit_opt_in_required"] is True
    assert start["metadata"]["approval_required"] is True
    assert start["metadata"]["approval_granted"] is True
    assert restart["execution_intent"]["requests_start"] is True
    assert restart["execution_intent"]["requests_stop"] is True
    assert restart["execution_intent"]["restart_decomposes_to_stop_then_start"] is True
    assert restart["guardrails"]["restart_is_stop_then_start"] is True
    assert "approved=1" in operator_control_request_summary_line(restart)


def test_operator_control_stop_allows_non_required_approval_metadata() -> None:
    stop = build_artifact_retention_scheduler_daemon_operator_control_request(
        action="stop_daemon",
        operator_subject={"actor_type": "operator", "actor_id": "employee-1001"},
        idempotency_key="idem-0582-stop",
        reason="operator stop request",
        requested_at=REQUESTED_AT,
        approval={
            "approved": False,
            "approved_by": {"actor_type": "operator", "actor_id": "delegate"},
            "approved_at": REQUESTED_AT,
            "reason": "not required for stop",
        },
    )

    assert stop["action"] == "stop_daemon"
    assert stop["approval"]["approved"] is False
    assert stop["execution_intent"]["requires_running_process"] is True
    assert stop["execution_intent"]["requests_stop"] is True
    assert stop["guardrails"]["approval_required"] is False
    assert stop["metadata"]["approval_granted"] is False


@pytest.mark.parametrize(
    ("mutate", "error_code", "detail"),
    (
        (
            lambda policy: [],
            "ae.artifact_retention_scheduler_daemon_operator_control_policy_invalid",
            "object",
        ),
        (
            lambda policy: {
                **policy,
                "operator_control_policy_schema_version": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_policy_schema_invalid",
            "schema",
        ),
        (
            lambda policy: {**policy, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_operator_control_policy_invalid",
            "service id",
        ),
        (
            lambda policy: {**policy, "supported_actions": []},
            "ae.artifact_retention_scheduler_daemon_operator_control_policy_invalid",
            "actions",
        ),
        (
            lambda policy: {
                **policy,
                "required_fields": {
                    **policy["required_fields"],
                    "idempotency_key": False,
                },
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_policy_invalid",
            "required fields",
        ),
        (
            lambda policy: {
                **policy,
                "profile_policy": {
                    **policy["profile_policy"],
                    "production_profiles_allowed": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_policy_invalid",
            "profile policy",
        ),
        (
            lambda policy: {
                **policy,
                "restart_policy": {
                    **policy["restart_policy"],
                    "restart_semantics": "in_place",
                },
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_policy_invalid",
            "restart policy",
        ),
        (
            lambda policy: {
                **policy,
                "guardrails": {
                    **policy["guardrails"],
                    "ag_direct_process_control_allowed": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_policy_invalid",
            "guardrails",
        ),
        (
            lambda policy: {
                **policy,
                "metadata": {**policy["metadata"], "subprocess_started": True},
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_policy_invalid",
            "metadata",
        ),
        (
            lambda policy: {**policy, "operator_control_policy_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_operator_control_policy_invalid",
            "id",
        ),
        (
            lambda policy: {**policy, "database_url": "postgresql://secret"},
            "ae.artifact_retention_scheduler_daemon_operator_control_policy_invalid",
            "keys",
        ),
    ),
)
def test_operator_control_policy_validation_edges(
    mutate: object,
    error_code: str,
    detail: str,
) -> None:
    policy = build_artifact_retention_scheduler_daemon_operator_control_policy(
        checked_at=REQUESTED_AT
    )

    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_operator_control_policy(
            mutate(deepcopy(policy))  # type: ignore[misc]
        )

    assert exc_info.value.error_code == error_code
    assert detail in exc_info.value.detail


@pytest.mark.parametrize(
    ("mutate", "error_code", "detail"),
    (
        (
            lambda request: [],
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "object",
        ),
        (
            lambda request: {
                **request,
                "operator_control_request_schema_version": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_request_schema_invalid",
            "schema",
        ),
        (
            lambda request: {**request, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "service id",
        ),
        (
            lambda request: {**request, "scheduler_id": ""},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "scheduler_id",
        ),
        (
            lambda request: {**request, "action": "launch"},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "action",
        ),
        (
            lambda request: {**request, "operator_subject": "bad"},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "operator subject",
        ),
        (
            lambda request: {
                **request,
                "operator_subject": {**request["operator_subject"], "secret": "x"},
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "operator subject keys",
        ),
        (
            lambda request: {**request, "idempotency_key": ""},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "idempotency_key",
        ),
        (
            lambda request: {**request, "reason": ""},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "reason",
        ),
        (
            lambda request: {**request, "requested_at": ""},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "requested_at",
        ),
        (
            lambda request: {**request, "profile": "prod"},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "profile must be test",
        ),
        (
            lambda request: {**request, "enabled": "true"},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "enabled",
        ),
        (
            lambda request: {**request, "explicit_opt_in": "true"},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "explicit_opt_in",
        ),
        (
            lambda request: {**request, "max_cycles": 0},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "positive integer",
        ),
        (
            lambda request: {**request, "run_worker": "yes"},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "run_worker",
        ),
        (
            lambda request: {**request, "approval": []},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "approval is invalid",
        ),
        (
            lambda request: {**request, "approval": {**request["approval"], "x": True}},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "approval keys",
        ),
        (
            lambda request: {
                **request,
                "approval": {**request["approval"], "approved": False},
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "approval must be granted",
        ),
        (
            lambda request: {
                **request,
                "approval": {
                    **request["approval"],
                    "approved_by": {"actor_type": "operator", "actor_id": "other"},
                },
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "approval subject",
        ),
        (
            lambda request: {
                **request,
                "approval": {**request["approval"], "approved_at": "later"},
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "approval time",
        ),
        (
            lambda request: {
                **request,
                "approval": {**request["approval"], "reason": "other"},
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "approval reason",
        ),
        (
            lambda request: {
                **request,
                "execution_intent": {
                    **request["execution_intent"],
                    "starts_continuous_loop": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "execution intent",
        ),
        (
            lambda request: {
                **request,
                "guardrails": {
                    **request["guardrails"],
                    "ag_direct_process_control_allowed": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "guardrails",
        ),
        (
            lambda request: {
                **request,
                "metadata": {**request["metadata"], "subprocess_started": True},
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "metadata",
        ),
        (
            lambda request: {**request, "operator_control_request_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "id",
        ),
        (
            lambda request: {**request, "database_url": "postgresql://secret"},
            "ae.artifact_retention_scheduler_daemon_operator_control_request_invalid",
            "keys",
        ),
    ),
)
def test_operator_control_request_validation_edges(
    mutate: object,
    error_code: str,
    detail: str,
) -> None:
    request = build_artifact_retention_scheduler_daemon_operator_control_request(
        action="start_daemon",
        operator_subject=SUBJECT,
        idempotency_key="idem-0582-start",
        reason="operator start request",
        requested_at=REQUESTED_AT,
        enabled=True,
        explicit_opt_in=True,
        approval=approval(),
    )

    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_operator_control_request(
            mutate(deepcopy(request))  # type: ignore[misc]
        )

    assert exc_info.value.error_code == error_code
    assert detail in exc_info.value.detail


def test_operator_control_start_rejects_missing_approval_and_opt_in() -> None:
    with pytest.raises(ArtifactHandoffError) as approval_exc:
        build_artifact_retention_scheduler_daemon_operator_control_request(
            action="start_daemon",
            operator_subject=SUBJECT,
            idempotency_key="idem-0582-start-no-approval",
            reason="operator start request",
            requested_at=REQUESTED_AT,
            enabled=True,
            explicit_opt_in=True,
        )
    assert "approval is required" in approval_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as opt_in_exc:
        build_artifact_retention_scheduler_daemon_operator_control_request(
            action="restart_daemon",
            operator_subject=SUBJECT,
            idempotency_key="idem-0582-restart-no-opt-in",
            reason="operator restart request",
            requested_at=REQUESTED_AT,
            enabled=False,
            explicit_opt_in=False,
            approval=approval("operator restart request"),
        )
    assert "enabled runtime and explicit opt-in" in opt_in_exc.value.detail
