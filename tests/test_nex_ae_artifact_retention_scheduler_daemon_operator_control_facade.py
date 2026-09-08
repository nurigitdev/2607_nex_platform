from __future__ import annotations

import json
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

import pytest

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_FACADE_SCHEMA_VERSION,
    build_artifact_retention_scheduler_daemon_operator_control_admission,
    build_artifact_retention_scheduler_daemon_operator_control_command_preview,
    build_artifact_retention_scheduler_daemon_operator_control_facade,
    build_artifact_retention_scheduler_daemon_operator_control_policy,
    build_artifact_retention_scheduler_daemon_operator_control_request,
    operator_control_facade_summary_line,
    summarize_artifact_retention_scheduler_daemon_operator_control_facade,
    validate_artifact_retention_scheduler_daemon_operator_control_facade,
)
from nex_ae_api.artifacts import ArtifactHandoffError


REQUESTED_AT = "2026-09-08T05:00:00Z"
CHECKED_AT = "2026-09-08T05:00:12Z"
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


def request(action: str, *, idempotency_key: str, reason: str) -> dict[str, object]:
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


def facade(
    action: str,
    *,
    current_process: dict[str, object] | None = None,
) -> dict[str, object]:
    reason = f"operator {action.replace('_daemon', '')} request"
    admission = build_artifact_retention_scheduler_daemon_operator_control_admission(
        operator_control_request=request(
            action,
            idempotency_key=f"idem-0585-{action}",
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


def test_operator_control_facade_wraps_policy_admission_and_preview_safely() -> None:
    payload = facade("start_daemon")
    summary = summarize_artifact_retention_scheduler_daemon_operator_control_facade(
        payload
    )
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["operator_control_facade_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_FACADE_SCHEMA_VERSION
    )
    assert payload["service_id"] == "nex-ae-api"
    assert payload["action"] == "start_daemon"
    assert payload["facade_status"] == "READY"
    assert payload["operator_control_policy"]["profile_policy"][
        "default_profile"
    ] == "test"
    assert payload["operator_control_admission"]["admission_status"] == "READY"
    assert payload["operator_control_command_preview"]["preview_status"] == "READY"
    assert payload["guardrails"]["preview_only"] is True
    assert payload["guardrails"]["process_control_allowed"] is False
    assert payload["guardrails"]["supervisor_adapter_invoked"] is False
    assert payload["metadata"]["command_preview_count"] == 1
    assert payload["metadata"]["supervisor_actions"] == ["start_daemon"]
    assert payload["metadata"]["ready_for_dispatch"] is True
    assert summary["command_count"] == 1
    assert "commands=1" in operator_control_facade_summary_line(payload)
    assert validate_artifact_retention_scheduler_daemon_operator_control_facade(
        payload
    ) == payload
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "nuri1004" not in serialized
    assert "ed6@c496em" not in serialized


def test_operator_control_facade_preserves_blocked_preview_without_commands() -> None:
    payload = facade(
        "restart_daemon",
        current_process=process("MISSING"),
    )

    assert payload["facade_status"] == "BLOCKED"
    assert payload["metadata"]["ready_for_dispatch"] is False
    assert payload["metadata"]["command_preview_count"] == 0
    assert payload["metadata"]["supervisor_actions"] == []
    assert payload["operator_control_command_preview"][
        "supervisor_command_previews"
    ] == []
    assert "next=none" in operator_control_facade_summary_line(payload)


def test_operator_control_facade_marks_restart_decomposition() -> None:
    payload = facade(
        "restart_daemon",
        current_process=process("RUNNING", process_id=5201),
    )

    assert payload["facade_status"] == "READY"
    assert payload["guardrails"]["restart_decomposes_to_stop_then_start"] is True
    assert payload["metadata"]["command_preview_count"] == 2
    assert payload["metadata"]["supervisor_actions"] == [
        "stop_daemon",
        "start_daemon",
    ]


@pytest.mark.parametrize(
    ("mutate", "error_code", "detail"),
    (
        (
            lambda payload: [],
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid",
            "object",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_facade_schema_version": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_schema_invalid",
            "schema",
        ),
        (
            lambda payload: {**payload, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid",
            "service id",
        ),
        (
            lambda payload: {**payload, "scheduler_id": "other"},
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid",
            "scheduler scope",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_policy_id": "other",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid",
            "policy scope",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_request_id": "other",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid",
            "request scope",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_admission_id": "other",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid",
            "admission scope",
        ),
        (
            lambda payload: {
                **payload,
                "operator_control_command_preview_id": "other",
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid",
            "preview scope",
        ),
        (
            lambda payload: {**payload, "action": "stop_daemon"},
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid",
            "action scope",
        ),
        (
            lambda payload: {**payload, "facade_status": "NOOP"},
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid",
            "status",
        ),
        (
            lambda payload: {**payload, "guardrails": {}},
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid",
            "guardrails",
        ),
        (
            lambda payload: {**payload, "metadata": {}},
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid",
            "metadata",
        ),
        (
            lambda payload: {**payload, "operator_control_facade_id": "other"},
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid",
            "id",
        ),
        (
            lambda payload: {
                key: value
                for key, value in payload.items()
                if key != "checked_at"
            },
            "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid",
            "keys",
        ),
    ),
)
def test_operator_control_facade_rejects_contract_drift(
    mutate: object,
    error_code: str,
    detail: str,
) -> None:
    payload = facade(
        "restart_daemon",
        current_process=process("RUNNING", process_id=5201),
    )
    bad_payload = mutate(deepcopy(payload))  # type: ignore[operator]

    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_operator_control_facade(
            bad_payload
        )

    assert exc_info.value.error_code == error_code
    assert detail in exc_info.value.detail


def test_operator_control_facade_rejects_policy_scheduler_mismatch_on_build() -> None:
    payload = facade("status_probe")
    policy = dict(payload["operator_control_policy"])
    policy["scheduler_id"] = "other"
    policy["operator_control_policy_id"] = str(
        uuid5(
            NAMESPACE_URL,
            (
                "nex-ae-api:artifact-retention:operator-control-policy:"
                f"other:{policy['checked_at']}"
            ),
        )
    )

    with pytest.raises(ArtifactHandoffError) as exc_info:
        build_artifact_retention_scheduler_daemon_operator_control_facade(
            operator_control_policy=policy,
            operator_control_command_preview=payload[
                "operator_control_command_preview"
            ],
            checked_at=CHECKED_AT,
        )

    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_operator_control_facade_invalid"
    )
    assert "scheduler scope" in exc_info.value.detail
