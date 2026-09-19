from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import nex_ag.recovery_notification_delivery as delivery
from nex_ag.recovery_notification_policy import build_recovery_notification_plan


ADMITTED_AT = "2026-09-19T01:00:00Z"


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
        evaluated_at=ADMITTED_AT,
    )


def case_record(**overrides: object) -> dict[str, Any]:
    return {
        "case_id": "case-0842",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
        "case_status": "OPEN",
        **overrides,
    }


def escalation_record(**overrides: object) -> dict[str, Any]:
    return {
        "escalation_id": "escalation-0842",
        "case_id": "case-0842",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
        "escalation_status": "ACTIVE",
        **overrides,
    }


def test_delivery_admission_verifies_explicit_context() -> None:
    result = delivery.build_recovery_notification_delivery_admission(
        ready_plan(),
        case_record(),
        escalation_record(),
        channel_type="notification",
        provider_profile="office-notification-v1",
        admitted_at=ADMITTED_AT,
    )

    assert result["delivery_admission_schema_version"] == (
        delivery.RECOVERY_NOTIFICATION_DELIVERY_ADMISSION_SCHEMA_VERSION
    )
    assert result["admission_status"] == "ADMITTED"
    assert result["case_id"] == "case-0842"
    assert result["escalation_id"] == "escalation-0842"
    assert result["target"]["target_service"] == "nex-ag"
    assert result["delivery"] == {
        "channel_type": "NOTIFICATION",
        "provider_profile": "office-notification-v1",
        "dispatch_intent": "NOTIFY_OPERATOR",
    }
    assert result["notification"]["severity"] == "ERROR"
    assert result["admitted_at"] == ADMITTED_AT
    assert result["guardrails"]["dispatch_persistence_performed"] is False
    assert result["guardrails"]["provider_invocation_performed"] is False


def test_delivery_admission_defaults_to_mock_without_side_effects() -> None:
    result = delivery.build_recovery_notification_delivery_admission(
        ready_plan(),
        case_record(),
        escalation_record(),
        admitted_at=datetime(2026, 9, 19, 1, 0, tzinfo=UTC),
    )

    assert result["delivery"]["channel_type"] == "MOCK"
    assert result["delivery"]["provider_profile"] == "mock-default"
    assert result["notification"]["service_id"] == "nex-ag"
    assert result["notification"]["worker_id"] == "ag-dispatch-execution-daemon"

    generated_at = delivery.build_recovery_notification_delivery_admission(
        ready_plan(),
        case_record(),
        escalation_record(),
    )["admitted_at"]
    assert generated_at.endswith("Z")

    naive_at = delivery.build_recovery_notification_delivery_admission(
        ready_plan(),
        case_record(),
        escalation_record(),
        admitted_at=datetime(2026, 9, 19, 1, 0),
    )["admitted_at"]
    assert naive_at == ADMITTED_AT


@pytest.mark.parametrize(
    ("position", "error_code"),
    [
        ("plan", "ag.recovery_notification_delivery_plan_invalid"),
        ("case", "ag.recovery_notification_delivery_case_invalid"),
        ("escalation", "ag.recovery_notification_delivery_escalation_invalid"),
    ],
)
def test_delivery_admission_requires_object_inputs(
    position: str,
    error_code: str,
) -> None:
    values: dict[str, object] = {
        "plan": ready_plan(),
        "case": case_record(),
        "escalation": escalation_record(),
    }
    values[position] = None

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_delivery_admission(
            values["plan"],  # type: ignore[arg-type]
            values["case"],  # type: ignore[arg-type]
            values["escalation"],  # type: ignore[arg-type]
        )

    assert exc_info.value.error_code == error_code
    assert exc_info.value.status_code == 422


@pytest.mark.parametrize(
    ("mutate", "error_code", "status_code"),
    [
        (
            lambda plan: plan.update(notification_plan_schema_version="unsupported"),
            "ag.recovery_notification_delivery_plan_schema_unsupported",
            422,
        ),
        (
            lambda plan: plan.update(decision=None),
            "ag.recovery_notification_delivery_decision_invalid",
            422,
        ),
        (
            lambda plan: plan.update(delivery=None),
            "ag.recovery_notification_delivery_state_invalid",
            422,
        ),
        (
            lambda plan: plan.update(plan_status="PREVIEW_ONLY"),
            "ag.recovery_notification_delivery_not_authorized",
            409,
        ),
        (
            lambda plan: plan["delivery"].update(performed=True),
            "ag.recovery_notification_delivery_already_performed",
            409,
        ),
        (
            lambda plan: plan["delivery"].update(provider_invocation_performed=True),
            "ag.recovery_notification_delivery_already_performed",
            409,
        ),
    ],
)
def test_delivery_admission_rejects_inadmissible_plan(
    mutate,
    error_code: str,
    status_code: int,
) -> None:
    plan = ready_plan()
    mutate(plan)

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_delivery_admission(
            plan,
            case_record(),
            escalation_record(),
        )

    assert exc_info.value.error_code == error_code
    assert exc_info.value.status_code == status_code


@pytest.mark.parametrize(
    ("case_overrides", "escalation_overrides", "error_code", "status_code"),
    [
        (
            {"case_id": None},
            {},
            "ag.recovery_notification_delivery_case_id_required",
            422,
        ),
        (
            {},
            {"escalation_id": None},
            "ag.recovery_notification_delivery_escalation_id_required",
            422,
        ),
        (
            {},
            {"case_id": None},
            "ag.recovery_notification_delivery_escalation_case_id_required",
            422,
        ),
        (
            {},
            {"case_id": "different-case"},
            "ag.recovery_notification_delivery_context_mismatch",
            409,
        ),
        (
            {},
            {"target_service": "nex-cx"},
            "ag.recovery_notification_delivery_target_mismatch",
            409,
        ),
        (
            {"target_kind": None},
            {},
            "ag.recovery_notification_delivery_case_target_kind_required",
            422,
        ),
        (
            {},
            {"target_id": None},
            "ag.recovery_notification_delivery_escalation_target_id_required",
            422,
        ),
    ],
)
def test_delivery_admission_rejects_invalid_context(
    case_overrides: dict[str, object],
    escalation_overrides: dict[str, object],
    error_code: str,
    status_code: int,
) -> None:
    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_delivery_admission(
            ready_plan(),
            case_record(**case_overrides),
            escalation_record(**escalation_overrides),
        )

    assert exc_info.value.error_code == error_code
    assert exc_info.value.status_code == status_code


@pytest.mark.parametrize(
    ("kwargs", "error_code"),
    [
        (
            {"channel_type": "sms"},
            "ag.recovery_notification_delivery_channel_unsupported",
        ),
        (
            {"provider_profile": "x" * 129},
            "ag.recovery_notification_delivery_provider_profile_required",
        ),
        (
            {"admitted_at": "not-a-time"},
            "ag.recovery_notification_delivery_admitted_at_invalid",
        ),
        (
            {"admitted_at": object()},
            "ag.recovery_notification_delivery_admitted_at_invalid",
        ),
    ],
)
def test_delivery_admission_rejects_invalid_options(
    kwargs: dict[str, object],
    error_code: str,
) -> None:
    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_delivery_admission(
            ready_plan(),
            case_record(),
            escalation_record(),
            **kwargs,
        )

    assert exc_info.value.error_code == error_code


def test_delivery_admission_requires_safe_payload_and_plan_id() -> None:
    no_payload = ready_plan()
    no_payload["safe_payload"] = None
    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_delivery_admission(
            no_payload,
            case_record(),
            escalation_record(),
        )
    assert exc_info.value.error_code == (
        "ag.recovery_notification_delivery_safe_payload_invalid"
    )

    no_id = ready_plan()
    no_id["notification_plan_id"] = ""
    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_delivery_admission(
            no_id,
            case_record(),
            escalation_record(),
        )
    assert exc_info.value.error_code == (
        "ag.recovery_notification_delivery_plan_id_required"
    )
