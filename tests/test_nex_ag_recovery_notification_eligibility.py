from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

import nex_ag.recovery_notification_policy as notification


EVALUATED_AT = "2026-09-18T08:00:00Z"


def recovery_plan(
    *severities: str,
    effective_state: str | None = None,
) -> dict[str, Any]:
    overlay = (
        {"effective_state_status": effective_state}
        if effective_state is not None
        else None
    )
    return {
        "summary": {"liveness_status": "STALE" if severities else "FRESH"},
        "recommended_actions": [
            {
                "action_id": f"action-{index}",
                "severity": severity,
                "reason_code": f"reason-{index}",
            }
            for index, severity in enumerate(severities)
        ],
        "acknowledgement_state_overlay": overlay,
    }


def test_recovery_notification_eligibility_selects_highest_severity() -> None:
    result = notification.evaluate_recovery_notification_eligibility(
        recovery_plan("WARNING", "ERROR", "INFO"),
        evaluated_at=EVALUATED_AT,
    )

    assert result["notification_decision_schema_version"] == (
        notification.RECOVERY_NOTIFICATION_DECISION_SCHEMA_VERSION
    )
    assert result["decision_status"] == "ELIGIBLE"
    assert result["eligible"] is True
    assert result["delivery_authorized_by_policy"] is False
    assert result["provider_invocation_performed"] is False
    assert result["severity"] == "ERROR"
    assert result["effective_ack_state"] == "NONE"
    assert result["reason_codes"] == ["eligible_recovery_signal"]
    assert result["evaluated_at"] == EVALUATED_AT


@pytest.mark.parametrize(
    ("plan", "policy_overrides", "reason"),
    [
        (recovery_plan("ERROR"), {"enabled": False}, "policy_disabled"),
        (recovery_plan(), {}, "no_recovery_action"),
        (
            recovery_plan("WARNING"),
            {"minimum_severity": "ERROR"},
            "below_minimum_severity",
        ),
    ],
)
def test_recovery_notification_eligibility_ineligible_paths(
    plan: dict[str, Any],
    policy_overrides: dict[str, Any],
    reason: str,
) -> None:
    policy = notification.build_recovery_notification_policy({})
    policy.update(policy_overrides)

    result = notification.evaluate_recovery_notification_eligibility(
        plan,
        policy=policy,
        evaluated_at=EVALUATED_AT,
    )

    assert result["decision_status"] == "INELIGIBLE"
    assert result["eligible"] is False
    assert result["reason_codes"] == [reason]


@pytest.mark.parametrize("state", ["ACKNOWLEDGED", "SUPPRESSED"])
def test_recovery_notification_eligibility_suppresses_repeat_or_active_state(
    state: str,
) -> None:
    result = notification.evaluate_recovery_notification_eligibility(
        recovery_plan("ERROR", effective_state=state),
        evaluated_at=EVALUATED_AT,
    )

    assert result["decision_status"] == "SUPPRESSED"
    assert result["eligible"] is False
    assert result["reason_codes"] == [
        "acknowledged_repeat" if state == "ACKNOWLEDGED" else "active_suppression"
    ]


def test_recovery_notification_critical_may_bypass_active_suppression() -> None:
    bypassed = notification.evaluate_recovery_notification_eligibility(
        recovery_plan("CRITICAL", effective_state="SUPPRESSED"),
        evaluated_at=EVALUATED_AT,
    )
    policy = notification.build_recovery_notification_policy({})
    policy["critical_bypass_suppression"] = False
    blocked = notification.evaluate_recovery_notification_eligibility(
        recovery_plan("CRITICAL", effective_state="SUPPRESSED"),
        policy=policy,
        evaluated_at=EVALUATED_AT,
    )

    assert bypassed["decision_status"] == "ELIGIBLE"
    assert bypassed["reason_codes"] == ["critical_bypass_suppression"]
    assert blocked["decision_status"] == "SUPPRESSED"
    assert blocked["reason_codes"] == ["active_suppression"]


@pytest.mark.parametrize("state", ["EXPIRED", "CLEARED"])
def test_recovery_notification_expired_or_cleared_state_does_not_block(
    state: str,
) -> None:
    result = notification.evaluate_recovery_notification_eligibility(
        recovery_plan("ERROR", effective_state=state),
        evaluated_at=EVALUATED_AT,
    )

    assert result["decision_status"] == "ELIGIBLE"


def test_recovery_notification_delivery_authorization_is_policy_only() -> None:
    result = notification.evaluate_recovery_notification_eligibility(
        recovery_plan("ERROR"),
        environ={notification.RECOVERY_NOTIFICATION_DELIVERY_ENABLED_ENV: "1"},
        evaluated_at=EVALUATED_AT,
    )

    assert result["delivery_authorized_by_policy"] is True
    assert result["provider_invocation_performed"] is False


@pytest.mark.parametrize(
    ("plan", "error_code"),
    [
        (None, "ag.recovery_notification_plan_invalid"),
        ({}, "ag.recovery_notification_summary_invalid"),
        (
            {"summary": {}, "recommended_actions": "bad"},
            "ag.recovery_notification_actions_invalid",
        ),
        (
            {"summary": {}, "recommended_actions": ["bad"]},
            "ag.recovery_notification_actions_invalid",
        ),
    ],
)
def test_recovery_notification_eligibility_rejects_invalid_plan(
    plan: Any,
    error_code: str,
) -> None:
    with pytest.raises(notification.RecoveryNotificationPolicyError) as raised:
        notification.evaluate_recovery_notification_eligibility(
            plan,
            evaluated_at=EVALUATED_AT,
        )

    assert raised.value.error_code == error_code
    assert raised.value.status_code == 400
    assert raised.value.detail


@pytest.mark.parametrize("value", ["not-a-time", 123])
def test_recovery_notification_eligibility_rejects_invalid_timestamp(
    value: object,
) -> None:
    with pytest.raises(
        notification.RecoveryNotificationPolicyError,
        match="ISO-8601",
    ):
        notification.evaluate_recovery_notification_eligibility(
            recovery_plan("ERROR"),
            evaluated_at=value,
        )


def test_recovery_notification_timestamp_and_unknown_severity_helpers() -> None:
    naive = datetime(2026, 9, 18, 8, 0, 0)
    result = notification.evaluate_recovery_notification_eligibility(
        recovery_plan("unknown"),
        policy={
            **notification.build_recovery_notification_policy({}),
            "minimum_severity": "INFO",
        },
        evaluated_at=naive,
    )
    current = notification._datetime_value(None)

    assert result["severity"] == "INFO"
    assert result["evaluated_at"] == EVALUATED_AT
    assert current.endswith("Z")
