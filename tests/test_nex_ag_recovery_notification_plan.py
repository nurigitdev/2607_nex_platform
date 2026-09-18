from __future__ import annotations

import json
from typing import Any

import pytest

import nex_ag.recovery_notification_policy as notification


EVALUATED_AT = "2026-09-18T09:00:00Z"


def recovery_plan(
    severity: str | None = "ERROR",
    *,
    effective_state: str | None = None,
    service_id: object = "nex-ag",
    worker_id: object = "ag-dispatch-execution-daemon",
) -> dict[str, Any]:
    actions = (
        []
        if severity is None
        else [
            {
                "action_id": "private-action-id",
                "severity": severity,
                "title": "raw-title-secret-0834",
                "reason_code": "private-reason",
                "raw_comment": "raw-comment-secret-0834",
                "idempotency_key": "raw-idempotency-secret-0834",
            }
        ]
    )
    return {
        "projection_schema_version": "recovery-plan.v1",
        "summary": {"liveness_status": "STALE" if actions else "FRESH"},
        "daemon_identity": {"service_id": service_id, "worker_id": worker_id},
        "recommended_actions": actions,
        "acknowledgement_state_overlay": {
            "effective_state_status": effective_state,
            "raw_comment": "overlay-secret-0834",
        },
        "provider_endpoint": "https://private.example/secret",
        "provider_token": "provider-token-secret-0834",
        "database_url": "postgresql://private-secret-0834",
    }


def test_recovery_notification_plan_builds_redacted_preview() -> None:
    result = notification.build_recovery_notification_plan(
        recovery_plan(),
        evaluated_at=EVALUATED_AT,
        request_trace_id="trace-0834",
    )

    assert result["notification_plan_schema_version"] == (
        notification.RECOVERY_NOTIFICATION_PLAN_SCHEMA_VERSION
    )
    assert result["plan_status"] == "PREVIEW_ONLY"
    assert result["audience"] == ["nex-ag-operators"]
    assert result["preview_channels"] == ["operations_dashboard"]
    assert result["safe_payload"]["service_id"] == "nex-ag"
    assert result["safe_payload"]["worker_id"] == "ag-dispatch-execution-daemon"
    assert result["safe_payload"]["severity"] == "ERROR"
    assert result["request_trace_id"] == "trace-0834"
    assert result["delivery"]["performed"] is False
    assert result["delivery"]["provider_endpoint"] is None
    assert result["source"]["raw_recovery_plan_included"] is False
    assert not any(result["redaction"].values())


def test_recovery_notification_plan_ready_is_still_not_delivered() -> None:
    result = notification.build_recovery_notification_plan(
        recovery_plan(),
        environ={notification.RECOVERY_NOTIFICATION_DELIVERY_ENABLED_ENV: "1"},
        evaluated_at=EVALUATED_AT,
    )

    assert result["plan_status"] == "READY"
    assert result["delivery"]["authorized_by_policy"] is True
    assert result["delivery"]["performed"] is False
    assert result["delivery"]["provider_invocation_performed"] is False


@pytest.mark.parametrize(
    ("severity", "effective_state", "expected"),
    [
        (None, None, "NOT_REQUIRED"),
        ("ERROR", "ACKNOWLEDGED", "SUPPRESSED"),
        ("ERROR", "SUPPRESSED", "SUPPRESSED"),
    ],
)
def test_recovery_notification_plan_non_delivery_statuses(
    severity: str | None,
    effective_state: str | None,
    expected: str,
) -> None:
    result = notification.build_recovery_notification_plan(
        recovery_plan(severity, effective_state=effective_state),
        evaluated_at=EVALUATED_AT,
    )

    assert result["plan_status"] == expected
    assert result["delivery"]["performed"] is False


def test_recovery_notification_plan_id_is_deterministic() -> None:
    first = notification.build_recovery_notification_plan(
        recovery_plan(),
        evaluated_at=EVALUATED_AT,
    )
    second = notification.build_recovery_notification_plan(
        recovery_plan(),
        evaluated_at=EVALUATED_AT,
    )
    changed = notification.build_recovery_notification_plan(
        recovery_plan("CRITICAL"),
        evaluated_at=EVALUATED_AT,
    )

    assert first["notification_plan_id"] == second["notification_plan_id"]
    assert first["notification_plan_id"] != changed["notification_plan_id"]


def test_recovery_notification_plan_rejects_unsafe_identifiers() -> None:
    result = notification.build_recovery_notification_plan(
        recovery_plan(
            service_id="unsafe service/id",
            worker_id="x" * 65,
        ),
        evaluated_at=EVALUATED_AT,
        request_trace_id="unsafe trace/id",
    )

    assert result["safe_payload"]["service_id"] == "nex-ag"
    assert result["safe_payload"]["worker_id"] == "ag-dispatch-execution-daemon"
    assert result["request_trace_id"] is None
    assert notification._safe_identifier(None, default="fallback") == "fallback"
    assert notification._safe_identifier("", default="fallback") == "fallback"


def test_recovery_notification_plan_excludes_sensitive_source_values() -> None:
    result = notification.build_recovery_notification_plan(
        recovery_plan(),
        policy={
            **notification.build_recovery_notification_policy({}),
            "redaction": {"provider_token": "policy-secret-0834"},
        },
        evaluated_at=EVALUATED_AT,
    )
    serialized = json.dumps(result, sort_keys=True)

    for forbidden in (
        "raw-title-secret-0834",
        "raw-comment-secret-0834",
        "raw-idempotency-secret-0834",
        "overlay-secret-0834",
        "https://private.example/secret",
        "provider-token-secret-0834",
        "postgresql://private-secret-0834",
        "policy-secret-0834",
    ):
        assert forbidden not in serialized


def test_recovery_notification_plan_helpers() -> None:
    assert notification._notification_plan_status(
        {"decision_status": "OTHER", "eligible": False}
    ) == "NOT_REQUIRED"
    assert notification._notification_title("ERROR", "STALE") == (
        "[ERROR] AG dispatch recovery attention: STALE"
    )
    assert notification._notification_summary({}) == (
        "Dispatch recovery policy evaluated 0 action(s) as UNKNOWN."
    )
