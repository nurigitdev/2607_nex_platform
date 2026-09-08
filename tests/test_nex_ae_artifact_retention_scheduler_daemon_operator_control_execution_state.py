from __future__ import annotations

import json
from copy import deepcopy

import pytest

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_TRANSITION_SCHEMA_VERSION,
    build_artifact_retention_scheduler_daemon_operator_control_admission,
    build_artifact_retention_scheduler_daemon_operator_control_command_preview,
    build_artifact_retention_scheduler_daemon_operator_control_execution_request,
    build_artifact_retention_scheduler_daemon_operator_control_execution_state,
    build_artifact_retention_scheduler_daemon_operator_control_execution_state_transition,
    build_artifact_retention_scheduler_daemon_operator_control_facade,
    build_artifact_retention_scheduler_daemon_operator_control_policy,
    build_artifact_retention_scheduler_daemon_operator_control_request,
    operator_control_execution_state_summary_line,
    operator_control_execution_state_transition_summary_line,
    summarize_artifact_retention_scheduler_daemon_operator_control_execution_state,
    summarize_artifact_retention_scheduler_daemon_operator_control_execution_state_transition,
    validate_artifact_retention_scheduler_daemon_operator_control_execution_state,
    validate_artifact_retention_scheduler_daemon_operator_control_execution_state_transition,
)
from nex_ae_api.artifacts import ArtifactHandoffError


REQUESTED_AT = "2026-09-08T06:30:00Z"
CHECKED_AT = "2026-09-08T06:30:12Z"
OBSERVED_AT = "2026-09-08T06:30:30Z"
TRANSITIONED_AT = "2026-09-08T06:30:45Z"
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


def operator_request(
    action: str,
    *,
    idempotency_key: str,
    reason: str,
) -> dict[str, object]:
    start_like = action in {"start_daemon", "restart_daemon"}
    return build_artifact_retention_scheduler_daemon_operator_control_request(
        action=action,
        operator_subject=SUBJECT,
        idempotency_key=idempotency_key,
        reason=reason,
        requested_at=REQUESTED_AT,
        enabled=start_like,
        explicit_opt_in=start_like,
        max_cycles=3,
        run_worker=True,
        approval=approval(reason) if start_like else None,
    )


def process(process_status: str, *, process_id: int | None = None) -> dict[str, object]:
    return {
        "process_status": process_status,
        "process_id": process_id,
        "host_id": "ae-node-01" if process_id is not None else None,
        "observed_at": CHECKED_AT,
    }


def operator_facade(
    action: str,
    *,
    current_process: dict[str, object] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    reason = f"operator {action.replace('_daemon', '')} execution state request"
    admission = build_artifact_retention_scheduler_daemon_operator_control_admission(
        operator_control_request=operator_request(
            action,
            idempotency_key=idempotency_key or f"idem-0593-{action}",
            reason=reason,
        ),
        current_process=current_process,
        checked_at=CHECKED_AT,
    )
    preview = build_artifact_retention_scheduler_daemon_operator_control_command_preview(
        operator_control_admission=admission,
        checked_at=CHECKED_AT,
    )
    policy = build_artifact_retention_scheduler_daemon_operator_control_policy(
        checked_at=CHECKED_AT
    )
    return build_artifact_retention_scheduler_daemon_operator_control_facade(
        operator_control_policy=policy,
        operator_control_command_preview=preview,
        checked_at=CHECKED_AT,
    )


def execution_request(
    action: str = "start_daemon",
    *,
    current_process: dict[str, object] | None = None,
    execution_mode: str = "fake_dry_run_supervisor_persistent_dispatch",
    idempotency_key: str | None = None,
) -> dict[str, object]:
    return build_artifact_retention_scheduler_daemon_operator_control_execution_request(
        operator_control_facade=operator_facade(
            action,
            current_process=current_process,
            idempotency_key=idempotency_key,
        ),
        execution_mode=execution_mode,
        requested_at=REQUESTED_AT,
    )


def execution_state(
    action: str = "start_daemon",
    *,
    current_process: dict[str, object] | None = None,
    execution_mode: str = "fake_dry_run_supervisor_persistent_dispatch",
    idempotency_key: str | None = None,
    existing_state: dict[str, object] | None = None,
    observed_at: str = OBSERVED_AT,
) -> dict[str, object]:
    return build_artifact_retention_scheduler_daemon_operator_control_execution_state(
        operator_control_execution_request=execution_request(
            action,
            current_process=current_process,
            execution_mode=execution_mode,
            idempotency_key=idempotency_key,
        ),
        existing_execution_state=existing_state,
        observed_at=observed_at,
    )


def assert_safe_metadata_only(payload: dict[str, object]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert "postgresql://" not in serialized
    assert "postgresql+psycopg://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "nuri1004" not in serialized
    assert "ed6@c496em" not in serialized
    assert "storage_ref" not in serialized
    assert "raw_text" not in serialized


def test_ready_fake_dispatch_request_is_admitted_with_next_state_options() -> None:
    payload = execution_state()
    summary = summarize_artifact_retention_scheduler_daemon_operator_control_execution_state(
        payload
    )

    assert payload["operator_control_execution_state_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_SCHEMA_VERSION
    )
    assert payload["service_id"] == "nex-ae-api"
    assert payload["execution_status"] == "ADMITTED"
    assert payload["idempotency_status"] == "NEW"
    assert payload["decision_reason"] == "admitted_for_fake_dry_run_supervisor_dispatch"
    assert payload["allowed_next_statuses"] == ["EXECUTING", "BLOCKED"]
    assert payload["prior_execution_state_id"] is None
    assert payload["guardrails"]["state_machine_only"] is True
    assert payload["guardrails"]["admitted_allows_execution_transition"] is True
    assert payload["guardrails"]["supervisor_adapter_invoked"] is False
    assert payload["metadata"]["execution_state_machine_only"] is True
    assert payload["metadata"]["allowed_next_statuses"] == ["EXECUTING", "BLOCKED"]
    assert summary["safe_for_ag_projection"] is True
    assert "status=ADMITTED" in operator_control_execution_state_summary_line(payload)
    assert validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
        payload
    ) == payload
    assert_safe_metadata_only(payload)


@pytest.mark.parametrize(
    ("action", "current_process", "execution_mode", "expected_status", "expected_reason"),
    (
        (
            "start_daemon",
            None,
            "contract_only",
            "BLOCKED",
            "execution_contract_only",
        ),
        (
            "restart_daemon",
            process("MISSING"),
            "fake_dry_run_supervisor_persistent_dispatch",
            "BLOCKED",
            "restart_requires_running_process",
        ),
        (
            "stop_daemon",
            None,
            "fake_dry_run_supervisor_persistent_dispatch",
            "NOOP",
            "daemon_not_running",
        ),
    ),
)
def test_terminal_initial_execution_states_do_not_allow_dispatch_transition(
    action: str,
    current_process: dict[str, object] | None,
    execution_mode: str,
    expected_status: str,
    expected_reason: str,
) -> None:
    payload = execution_state(
        action,
        current_process=current_process,
        execution_mode=execution_mode,
    )

    assert payload["execution_status"] == expected_status
    assert payload["idempotency_status"] == "NEW"
    assert payload["decision_reason"] == expected_reason
    assert payload["allowed_next_statuses"] == []
    assert payload["guardrails"]["terminal_state"] is True
    assert payload["metadata"]["supervisor_dispatch_performed"] is False
    assert payload["metadata"]["worker_execution_performed"] is False
    assert validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
        payload
    ) == payload
    assert_safe_metadata_only(payload)


def test_idempotency_replay_blocks_duplicate_dispatch() -> None:
    original = execution_state()
    replayed = execution_state(
        existing_state=original,
        observed_at="2026-09-08T06:31:30Z",
    )

    assert replayed["execution_status"] == "BLOCKED"
    assert replayed["idempotency_status"] == "REPLAYED"
    assert replayed["decision_reason"] == "idempotency_replay_returns_existing_state"
    assert replayed["prior_execution_state_id"] == original[
        "operator_control_execution_state_id"
    ]
    assert replayed["guardrails"]["idempotency_replay_blocks_duplicate_dispatch"] is True
    assert replayed["metadata"]["idempotency_replayed"] is True
    assert replayed["metadata"]["prior_execution_state_id"] == original[
        "operator_control_execution_state_id"
    ]
    assert replayed["allowed_next_statuses"] == []
    assert validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
        replayed
    ) == replayed


def test_idempotency_conflict_blocks_dispatch_for_different_prior_key() -> None:
    prior = execution_state("status_probe", idempotency_key="idem-0593-status")
    conflicting = build_artifact_retention_scheduler_daemon_operator_control_execution_state(
        operator_control_execution_request=execution_request(
            "start_daemon",
            idempotency_key="idem-0593-start-conflict",
        ),
        existing_execution_state=prior,
        observed_at="2026-09-08T06:32:30Z",
    )

    assert conflicting["execution_status"] == "BLOCKED"
    assert conflicting["idempotency_status"] == "CONFLICT"
    assert conflicting["decision_reason"] == "idempotency_key_conflict"
    assert conflicting["prior_execution_state_id"] == prior[
        "operator_control_execution_state_id"
    ]
    assert conflicting["guardrails"]["idempotency_conflict_blocks_dispatch"] is True
    assert conflicting["metadata"]["idempotency_conflict"] is True
    assert conflicting["allowed_next_statuses"] == []


def test_idempotency_conflict_blocks_same_key_with_different_request_hash() -> None:
    prior = execution_state("start_daemon", idempotency_key="idem-0593-shared")
    conflicting_request = execution_request(
        "restart_daemon",
        current_process=process("RUNNING", process_id=5301),
        idempotency_key="idem-0593-shared",
    )
    conflicting = build_artifact_retention_scheduler_daemon_operator_control_execution_state(
        operator_control_execution_request=conflicting_request,
        existing_execution_state=prior,
        observed_at="2026-09-08T06:33:30Z",
    )

    assert conflicting["execution_status"] == "BLOCKED"
    assert conflicting["idempotency_status"] == "CONFLICT"
    assert conflicting["decision_reason"] == "idempotency_key_conflict"
    assert conflicting["idempotency_key"] == prior["idempotency_key"]
    assert conflicting["operator_control_execution_request_hash"] != prior[
        "operator_control_execution_request_hash"
    ]
    assert conflicting["prior_execution_state_id"] == prior[
        "operator_control_execution_state_id"
    ]
    assert conflicting["metadata"]["idempotency_conflict"] is True


@pytest.mark.parametrize(
    ("target_status", "expected_flag"),
    (
        ("EXECUTING", "admitted_to_executing"),
        ("BLOCKED", "admitted_to_blocked"),
    ),
)
def test_admitted_state_allows_bounded_transition_contract(
    target_status: str,
    expected_flag: str,
) -> None:
    state = execution_state()
    transition = (
        build_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
            operator_control_execution_state=state,
            target_status=target_status.lower(),
            decision_reason=f"operator_transition_to_{target_status.lower()}",
            transitioned_at=TRANSITIONED_AT,
        )
    )
    summary = (
        summarize_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
            transition
        )
    )

    assert transition["operator_control_execution_state_transition_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_TRANSITION_SCHEMA_VERSION
    )
    assert transition["from_status"] == "ADMITTED"
    assert transition["to_status"] == target_status
    assert transition["guardrails"]["state_transition_only"] is True
    assert transition["guardrails"][expected_flag] is True
    assert transition["guardrails"]["supervisor_adapter_invoked"] is False
    assert transition["metadata"]["to_terminal"] is (target_status == "BLOCKED")
    assert summary["safe_for_ag_projection"] is True
    assert f"to={target_status}" in operator_control_execution_state_transition_summary_line(
        transition
    )
    assert validate_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
        transition
    ) == transition
    assert_safe_metadata_only(transition)


def test_terminal_state_rejects_execution_transition() -> None:
    state = execution_state(
        "start_daemon",
        execution_mode="contract_only",
    )

    with pytest.raises(ArtifactHandoffError) as exc_info:
        build_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
            operator_control_execution_state=state,
            target_status="EXECUTING",
            decision_reason="should_not_dispatch_terminal_state",
            transitioned_at=TRANSITIONED_AT,
        )

    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid"
    )
    assert "transition is not allowed" in exc_info.value.detail


@pytest.mark.parametrize(
    ("mutate", "error_code", "detail"),
    (
        (
            lambda payload: [],
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "object",
        ),
        (
            lambda payload: {
                key: value for key, value in payload.items() if key != "metadata"
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "keys",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_execution_state_schema_version": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_schema_invalid",
            "schema",
        ),
        (
            lambda payload: {**payload, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "service id",
        ),
        (
            lambda payload: {**payload, "scheduler_id": "other-scheduler"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "scheduler scope",
        ),
        (
            lambda payload: {**payload, "operator_control_facade_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "source scope",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_execution_request_id": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "request scope",
        ),
        (
            lambda payload: {**payload, "action": "stop_daemon"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "action scope",
        ),
        (
            lambda payload: {**payload, "execution_mode": "production"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "mode",
        ),
        (
            lambda payload: {**payload, "execution_mode": "contract_only"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "mode scope",
        ),
        (
            lambda payload: {**payload, "execution_status": "SUCCEEDED"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "status",
        ),
        (
            lambda payload: {**payload, "execution_status": "STALE"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "state status",
        ),
        (
            lambda payload: {**payload, "idempotency_key": "wrong"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "idempotency scope",
        ),
        (
            lambda payload: {**payload, "idempotency_status": "STALE"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "idempotency status",
        ),
        (
            lambda payload: {**payload, "decision_reason": "wrong"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "decision reason",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_execution_request_hash": "0" * 64,
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "request hash",
        ),
        (
            lambda payload: {**payload, "allowed_next_statuses": ["BLOCKED"]},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "next statuses",
        ),
        (
            lambda payload: {
                **payload,
                "guardrails": {**payload["guardrails"], "metadata_only": False},
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "guardrails",
        ),
        (
            lambda payload: {
                **payload,
                "metadata": {**payload["metadata"], "metadata_only": False},
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "metadata",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_execution_state_id": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid",
            "id",
        ),
    ),
)
def test_execution_state_validation_edges(
    mutate,
    error_code: str,
    detail: str,
) -> None:
    payload = execution_state()
    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_operator_control_execution_state(
            mutate(deepcopy(payload))
        )

    assert exc_info.value.error_code == error_code
    assert detail in exc_info.value.detail


@pytest.mark.parametrize(
    ("mutate", "error_code", "detail"),
    (
        (
            lambda payload: [],
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid",
            "object",
        ),
        (
            lambda payload: {
                key: value for key, value in payload.items() if key != "metadata"
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid",
            "keys",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_execution_state_transition_schema_version": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_schema_invalid",
            "schema",
        ),
        (
            lambda payload: {**payload, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid",
            "service id",
        ),
        (
            lambda payload: {**payload, "scheduler_id": "other-scheduler"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid",
            "scheduler scope",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_execution_state_id": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid",
            "state scope",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_execution_request_id": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid",
            "request scope",
        ),
        (
            lambda payload: {**payload, "from_status": "BLOCKED"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid",
            "from status",
        ),
        (
            lambda payload: {**payload, "to_status": "SUCCEEDED"},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid",
            "transition is not allowed",
        ),
        (
            lambda payload: {**payload, "decision_reason": ""},
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid",
            "decision_reason",
        ),
        (
            lambda payload: {
                **payload,
                "guardrails": {**payload["guardrails"], "metadata_only": False},
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid",
            "guardrails",
        ),
        (
            lambda payload: {
                **payload,
                "metadata": {**payload["metadata"], "metadata_only": False},
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid",
            "metadata",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_execution_state_transition_id": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid",
            "id",
        ),
    ),
)
def test_execution_state_transition_validation_edges(
    mutate,
    error_code: str,
    detail: str,
) -> None:
    transition = (
        build_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
            operator_control_execution_state=execution_state(),
            target_status="EXECUTING",
            decision_reason="operator_transition_to_executing",
            transitioned_at=TRANSITIONED_AT,
        )
    )
    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
            mutate(deepcopy(transition))
        )

    assert exc_info.value.error_code == error_code
    assert detail in exc_info.value.detail
