from __future__ import annotations

from typing import Any

import pytest

import nex_ag.recovery_notification_delivery as delivery
from nex_ag.recovery_notification_policy import build_recovery_notification_plan


CREATED_AT = "2026-09-19T02:00:00Z"


def ready_plan() -> dict[str, Any]:
    return build_recovery_notification_plan(
        {
            "projection_schema_version": "recovery-plan.v1",
            "summary": {"liveness_status": "STALE"},
            "daemon_identity": {
                "service_id": "nex-ag",
                "worker_id": "ag-dispatch-execution-daemon",
            },
            "recommended_actions": [{"severity": "ERROR"}],
        },
        environ={"NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED": "1"},
        evaluated_at=CREATED_AT,
    )


def case_record() -> dict[str, Any]:
    return {
        "case_id": "case-0843",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
    }


def escalation_record(**overrides: object) -> dict[str, Any]:
    return {
        "escalation_schema_version": "ag_operator_review_escalation.v1",
        "escalation_id": "escalation-0843",
        "candidate_id": "candidate-0843",
        "case_id": "case-0843",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
        "trace_id": "0" * 32,
        "request_id": "request-0843",
        "operator_ref": {"operator_type": "service", "operator_id": "nex-ag"},
        "assignment_ref": {},
        "escalation_status": "ACTIVE",
        "escalation_level": "ATTENTION",
        "sla_state": "WARNING",
        "reason_codes": ["daemon_stale"],
        "runbook_ids": ["ag.dispatch_daemon.recover.v1"],
        "recommended_actions": ["inspect_dispatch_daemon"],
        "action_comment_hash": None,
        "action_comment_preview": None,
        "snoozed_until": None,
        "metadata": {},
        "created_at": CREATED_AT,
        "updated_at": CREATED_AT,
        "closed_at": None,
        **overrides,
    }


def admission(
    plan: dict[str, Any],
    *,
    channel_type: str = "MOCK",
) -> dict[str, Any]:
    return delivery.build_recovery_notification_delivery_admission(
        plan,
        case_record(),
        escalation_record(),
        channel_type=channel_type,
        admitted_at=CREATED_AT,
    )


def test_dispatch_handoff_reuses_existing_planner() -> None:
    plan = ready_plan()
    result = delivery.build_recovery_notification_dispatch_handoff(
        plan,
        admission(plan),
        escalation_record(),
        request_id="request-0843",
        trace_id="0" * 32,
        idempotency_key="idem-0843",
        created_at=CREATED_AT,
    )

    assert result["dispatch_handoff_schema_version"] == (
        delivery.RECOVERY_NOTIFICATION_DISPATCH_HANDOFF_SCHEMA_VERSION
    )
    assert result["handoff_status"] == "READY_TO_PERSIST"
    assert result["blocking_reasons"] == []
    record = result["dispatch_record"]
    assert record["case_id"] == "case-0843"
    assert record["escalation_id"] == "escalation-0843"
    assert record["channel_type"] == "MOCK"
    assert record["dispatch_status"] == "PENDING"
    assert record["safe_subject"] == "[ERROR] AG dispatch recovery attention: STALE"
    assert record["safe_body_preview"].startswith("Dispatch recovery policy")
    assert record["metadata"]["source_kind"] == "recovery_notification_delivery"
    assert result["guardrails"]["dispatch_persistence_performed"] is False


def test_dispatch_handoff_preserves_live_channel_guardrail() -> None:
    plan = ready_plan()
    result = delivery.build_recovery_notification_dispatch_handoff(
        plan,
        admission(plan, channel_type="NOTIFICATION"),
        escalation_record(),
        request_id="request-0843",
        created_at=CREATED_AT,
    )

    assert result["handoff_status"] == "BLOCKED"
    assert result["dispatch_record"] is None
    assert result["blocking_reasons"] == ["live_channel_deferred"]
    assert result["guardrails"]["live_channel_guardrail_preserved"] is True


@pytest.mark.parametrize(
    ("position", "error_code"),
    [
        ("plan", "ag.recovery_notification_delivery_plan_invalid"),
        ("admission", "ag.recovery_notification_delivery_admission_invalid"),
        ("escalation", "ag.recovery_notification_delivery_escalation_invalid"),
    ],
)
def test_dispatch_handoff_requires_object_inputs(
    position: str,
    error_code: str,
) -> None:
    plan = ready_plan()
    values: dict[str, object] = {
        "plan": plan,
        "admission": admission(plan),
        "escalation": escalation_record(),
    }
    values[position] = None

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_dispatch_handoff(
            values["plan"],  # type: ignore[arg-type]
            values["admission"],  # type: ignore[arg-type]
            values["escalation"],  # type: ignore[arg-type]
            request_id="request-0843",
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (
            lambda value: value.update(admission_status="REJECTED"),
            "ag.recovery_notification_delivery_admission_not_admitted",
        ),
        (
            lambda value: value.update(notification_plan_id="other-plan"),
            "ag.recovery_notification_delivery_plan_context_mismatch",
        ),
        (
            lambda value: value.update(case_id="other-case"),
            "ag.recovery_notification_delivery_context_mismatch",
        ),
        (
            lambda value: value.update(escalation_id="other-escalation"),
            "ag.recovery_notification_delivery_context_mismatch",
        ),
        (
            lambda value: value.update(target=None),
            "ag.recovery_notification_delivery_target_invalid",
        ),
        (
            lambda value: value["target"].update(target_id="other-target"),
            "ag.recovery_notification_delivery_target_mismatch",
        ),
    ],
)
def test_dispatch_handoff_rejects_context_drift(
    mutation,
    error_code: str,
) -> None:
    plan = ready_plan()
    admitted = admission(plan)
    mutation(admitted)

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_dispatch_handoff(
            plan,
            admitted,
            escalation_record(),
            request_id="request-0843",
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (
            lambda plan, admitted: admitted.update(delivery=None),
            "ag.recovery_notification_delivery_selection_invalid",
        ),
        (
            lambda plan, admitted: admitted["delivery"].update(
                provider_profile=None
            ),
            "ag.recovery_notification_delivery_provider_profile_required",
        ),
        (
            lambda plan, admitted: admitted["delivery"].update(
                dispatch_intent="OPEN_INCIDENT"
            ),
            "ag.recovery_notification_delivery_dispatch_intent_invalid",
        ),
        (
            lambda plan, admitted: plan["safe_payload"].update(title=None),
            "ag.recovery_notification_delivery_title_required",
        ),
        (
            lambda plan, admitted: plan["safe_payload"].update(summary=None),
            "ag.recovery_notification_delivery_summary_required",
        ),
        (
            lambda plan, admitted: admitted.update(reason_codes="invalid"),
            None,
        ),
    ],
)
def test_dispatch_handoff_validates_selection_and_safe_payload(
    mutation,
    error_code: str | None,
) -> None:
    plan = ready_plan()
    admitted = admission(plan)
    mutation(plan, admitted)

    if error_code is None:
        result = delivery.build_recovery_notification_dispatch_handoff(
            plan,
            admitted,
            escalation_record(),
            request_id="request-0843",
        )
        assert result["dispatch_record"]["reason_codes"] == [
            "recovery_notification_delivery"
        ]
        return

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_dispatch_handoff(
            plan,
            admitted,
            escalation_record(),
            request_id="request-0843",
        )
    assert exc_info.value.error_code == error_code


def test_dispatch_handoff_reason_codes_are_safe_and_unique() -> None:
    plan = ready_plan()
    admitted = admission(plan)
    admitted["reason_codes"] = [
        "case_escalation_context_verified",
        " ",
        7,
        "case_escalation_context_verified",
    ]

    result = delivery.build_recovery_notification_dispatch_handoff(
        plan,
        admitted,
        escalation_record(),
        request_id="request-0843",
    )

    assert result["dispatch_record"]["reason_codes"] == [
        "recovery_notification_delivery",
        "case_escalation_context_verified",
    ]
