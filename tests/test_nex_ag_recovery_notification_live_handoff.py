from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

import nex_ag.recovery_notification_delivery as delivery
from nex_ag.operator_review_dispatch_execution import (
    build_dispatch_execution_provider_config,
)
from nex_ag.recovery_notification_policy import build_recovery_notification_plan


CREATED_AT = "2026-09-19T06:00:00Z"


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
        "case_id": "case-0853",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
    }


def escalation_record() -> dict[str, Any]:
    return {
        "escalation_id": "escalation-0853",
        "case_id": "case-0853",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
        "escalation_status": "ACTIVE",
        "escalation_level": "ATTENTION",
        "reason_codes": ["daemon_stale"],
        "recommended_actions": ["inspect_dispatch_daemon"],
        "runbook_ids": ["ag.dispatch_daemon.recover.v1"],
    }


def delivery_admission(
    plan: dict[str, Any],
    *,
    channel_type: str = "NOTIFICATION",
    provider_profile: str = "notification-webhook-default",
) -> dict[str, Any]:
    return delivery.build_recovery_notification_delivery_admission(
        plan,
        case_record(),
        escalation_record(),
        channel_type=channel_type,
        provider_profile=provider_profile,
        admitted_at=CREATED_AT,
    )


def live_admission(admission: dict[str, Any]) -> dict[str, Any]:
    config = build_dispatch_execution_provider_config(
        {
            "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE": "live_http",
            "NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE": "1",
            "NEX_AG_NOTIFICATION_WEBHOOK_URL": "http://127.0.0.1:18553/notify",
        }
    )
    return delivery.build_recovery_notification_live_admission(
        admission,
        config,
        confirm_live_delivery=True,
        admitted_at=CREATED_AT,
    )


@pytest.mark.parametrize(
    ("channel_type", "provider_profile"),
    [
        ("NOTIFICATION", "notification-webhook-default"),
        ("WEBHOOK", "notification-webhook-default"),
        ("EMAIL", "email-notification-default"),
    ],
)
def test_live_handoff_opens_only_explicitly_admitted_channel(
    channel_type: str,
    provider_profile: str,
) -> None:
    plan = ready_plan()
    admitted = delivery_admission(
        plan,
        channel_type=channel_type,
        provider_profile=provider_profile,
    )
    live = live_admission(admitted)

    result = delivery.build_recovery_notification_dispatch_handoff(
        plan,
        admitted,
        escalation_record(),
        request_id="request-0853",
        idempotency_key="idem-0853",
        created_at=CREATED_AT,
        live_admission=live,
    )

    assert result["handoff_status"] == "READY_TO_PERSIST"
    assert result["blocking_reasons"] == []
    assert result["dispatch_record"]["channel_type"] == channel_type
    assert result["dispatch_record"]["provider_profile"] == provider_profile
    assert result["dispatch_record"]["metadata"][
        "live_admission_schema_version"
    ] == delivery.RECOVERY_NOTIFICATION_LIVE_ADMISSION_SCHEMA_VERSION
    assert result["guardrails"]["live_channel_explicitly_admitted"] is True
    assert result["guardrails"]["live_channel_guardrail_preserved"] is False


def test_live_handoff_keeps_default_planner_guard_closed() -> None:
    plan = ready_plan()
    admitted = delivery_admission(plan)

    result = delivery.build_recovery_notification_dispatch_handoff(
        plan,
        admitted,
        escalation_record(),
        request_id="request-0853",
        created_at=CREATED_AT,
    )

    assert result["handoff_status"] == "BLOCKED"
    assert result["blocking_reasons"] == ["live_channel_deferred"]
    assert result["guardrails"]["live_channel_explicitly_admitted"] is False
    assert result["guardrails"]["live_channel_guardrail_preserved"] is True


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (
            lambda value: value.update(live_admission_schema_version="bad"),
            "ag.recovery_notification_live_handoff_admission_required",
        ),
        (
            lambda value: value.update(admission_status="REJECTED"),
            "ag.recovery_notification_live_handoff_admission_required",
        ),
        (
            lambda value: value.update(notification_plan_id="other-plan"),
            "ag.recovery_notification_live_handoff_context_mismatch",
        ),
        (
            lambda value: value.update(case_id="other-case"),
            "ag.recovery_notification_live_handoff_context_mismatch",
        ),
        (
            lambda value: value.update(escalation_id="other-escalation"),
            "ag.recovery_notification_live_handoff_context_mismatch",
        ),
        (
            lambda value: value.update(delivery=None),
            "ag.recovery_notification_live_handoff_selection_invalid",
        ),
        (
            lambda value: value["delivery"].update(provider_mode="mock_http"),
            "ag.recovery_notification_live_handoff_selection_mismatch",
        ),
        (
            lambda value: value["delivery"].update(
                provider_profile="email-notification-default"
            ),
            "ag.recovery_notification_live_handoff_selection_mismatch",
        ),
        (
            lambda value: value["delivery"].update(
                dispatch_intent="OPEN_INCIDENT"
            ),
            "ag.recovery_notification_live_handoff_selection_mismatch",
        ),
    ],
)
def test_live_handoff_rejects_admission_drift(mutation, error_code: str) -> None:
    plan = ready_plan()
    admitted = delivery_admission(plan)
    live = live_admission(admitted)
    mutation(live)

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_dispatch_handoff(
            plan,
            admitted,
            escalation_record(),
            request_id="request-0853",
            live_admission=live,
        )

    assert exc_info.value.error_code == error_code
    assert exc_info.value.status_code == (
        422
        if error_code == "ag.recovery_notification_live_handoff_selection_invalid"
        else 409
    )


def test_live_handoff_requires_mapping_admission() -> None:
    plan = ready_plan()
    admitted = delivery_admission(plan)

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_dispatch_handoff(
            plan,
            admitted,
            escalation_record(),
            request_id="request-0853",
            live_admission=[],  # type: ignore[arg-type]
        )

    assert exc_info.value.error_code == (
        "ag.recovery_notification_live_handoff_admission_invalid"
    )


def test_live_handoff_never_opens_mock_channel_with_live_admission() -> None:
    plan = ready_plan()
    admitted = delivery_admission(
        plan,
        channel_type="MOCK",
        provider_profile="mock-default",
    )
    live = {
        "live_admission_schema_version": (
            delivery.RECOVERY_NOTIFICATION_LIVE_ADMISSION_SCHEMA_VERSION
        ),
        "admission_status": "ADMITTED",
        "notification_plan_id": admitted["notification_plan_id"],
        "case_id": admitted["case_id"],
        "escalation_id": admitted["escalation_id"],
        "delivery": {
            "channel_type": "MOCK",
            "provider_profile": "mock-default",
            "provider_mode": "live_http",
            "dispatch_intent": "NOTIFY_OPERATOR",
        },
    }

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_dispatch_handoff(
            plan,
            admitted,
            escalation_record(),
            request_id="request-0853",
            live_admission=deepcopy(live),
        )

    assert exc_info.value.error_code == (
        "ag.recovery_notification_live_handoff_channel_unsupported"
    )
