from __future__ import annotations

import json
from typing import Any

import pytest

import nex_ag.recovery_notification_operations as operations
from nex_ag.recovery_notification_policy import RecoveryNotificationPolicyError


def recovery_section(
    *,
    severity: str | None = "ERROR",
    effective_state: str | None = None,
    projection_status: str = "READY",
) -> dict[str, Any]:
    actions = (
        []
        if severity is None
        else [
            {
                "action_id": "inspect-daemon",
                "severity": severity,
                "raw_comment": "raw-comment-secret-0836",
            }
        ]
    )
    return {
        "projection_schema_version": "recovery-dashboard.v1",
        "projection_status": projection_status,
        "summary": {
            "liveness_status": "STALE" if actions else "FRESH",
            "action_count": len(actions),
        },
        "recommended_actions": actions,
        "acknowledgement_state_overlay": {
            "effective_state_status": effective_state,
            "provider_token": "provider-token-secret-0836",
        },
        "source_evidence": {
            "service_id": "nex-ag",
            "worker_id": "ag-dispatch-execution-daemon",
        },
        "database_url": "postgresql://private-secret-0836",
    }


def test_recovery_notification_operations_projection_ready() -> None:
    result = operations.build_recovery_notification_operations_projection(
        recovery_section(),
        request_trace_id="trace-0836",
    )

    assert result["projection_schema_version"] == operations.RECOVERY_NOTIFICATION_OPERATIONS_SCHEMA_VERSION
    assert result["projection_status"] == "READY"
    assert result["notification_status"] == "PREVIEW_ONLY"
    assert result["summary"]["decision_status"] == "ELIGIBLE"
    assert result["summary"]["severity"] == "ERROR"
    assert result["summary"]["eligible"] is True
    assert result["summary"]["provider_invocation_performed"] is False
    assert result["preview_path"] == operations.RECOVERY_NOTIFICATION_PREVIEW_PATH
    assert result["request_trace_id"] == "trace-0836"
    assert result["source_statuses"]["nex-ag"]["status"] == "READY"
    assert not any(result["redaction"].values())


def test_recovery_notification_operations_projection_delivery_ready() -> None:
    result = operations.build_recovery_notification_operations_projection(
        recovery_section(),
        environ={"NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED": "1"},
    )

    assert result["notification_status"] == "READY"
    assert result["summary"]["delivery_enabled"] is True
    assert result["preview"]["delivery"]["performed"] is False


@pytest.mark.parametrize(
    ("severity", "effective_state", "expected"),
    [
        (None, None, "NOT_REQUIRED"),
        ("ERROR", "SUPPRESSED", "SUPPRESSED"),
    ],
)
def test_recovery_notification_operations_projection_decision_statuses(
    severity: str | None,
    effective_state: str | None,
    expected: str,
) -> None:
    result = operations.build_recovery_notification_operations_projection(
        recovery_section(severity=severity, effective_state=effective_state),
    )

    assert result["projection_status"] == "READY"
    assert result["notification_status"] == expected


@pytest.mark.parametrize(
    "source",
    [None, recovery_section(projection_status="DEGRADED")],
)
def test_recovery_notification_operations_projection_source_unavailable(
    source: dict[str, Any] | None,
) -> None:
    result = operations.build_recovery_notification_operations_projection(
        source,
        request_trace_id="trace-degraded-0836",
    )

    assert result["projection_status"] == "DEGRADED"
    assert result["notification_status"] == "SOURCE_UNAVAILABLE"
    assert result["preview"] is None
    assert result["summary"]["eligible"] is False
    assert result["source_statuses"]["nex-ag"]["error_code"].endswith(
        "source_unavailable"
    )
    assert result["request_trace_id"] == "trace-degraded-0836"


def test_recovery_notification_operations_projection_normalizes_policy_error() -> None:
    malformed = recovery_section()
    malformed["recommended_actions"] = "invalid"

    result = operations.build_recovery_notification_operations_projection(malformed)

    assert result["projection_status"] == "DEGRADED"
    assert result["source_statuses"]["nex-ag"]["error_code"] == (
        "ag.recovery_notification_actions_invalid"
    )


def test_recovery_notification_operations_projection_normalizes_generic_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        operations,
        "build_recovery_notification_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyError("secret")),
    )

    result = operations.build_recovery_notification_operations_projection(
        recovery_section()
    )

    assert result["projection_status"] == "DEGRADED"
    assert result["source_statuses"]["nex-ag"]["error_code"] == (
        "ag.recovery_notification_projection_failed"
    )
    assert "secret" not in json.dumps(result)


def test_recovery_notification_operations_projection_excludes_source_secrets() -> None:
    result = operations.build_recovery_notification_operations_projection(
        recovery_section()
    )
    serialized = json.dumps(result, sort_keys=True)

    for forbidden in (
        "raw-comment-secret-0836",
        "provider-token-secret-0836",
        "postgresql://private-secret-0836",
    ):
        assert forbidden not in serialized


def test_recovery_notification_operations_helpers() -> None:
    assert operations._daemon_identity({}) == {
        "service_id": "nex-ag",
        "worker_id": "ag-dispatch-execution-daemon",
    }
    error = RecoveryNotificationPolicyError("bad", error_code="test")
    assert error.error_code == "test"


def delivery_record(
    dispatch_id: str,
    status: str,
    *,
    updated_at: str,
    attempt_count: int = 0,
    recovery: bool = True,
) -> dict[str, Any]:
    return {
        "dispatch_id": dispatch_id,
        "case_id": "case-0845",
        "escalation_id": "escalation-0845",
        "dispatch_status": status,
        "dispatch_intent": "NOTIFY_OPERATOR",
        "channel_type": "MOCK",
        "provider_profile": "mock-default",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
        "safe_subject": "Safe recovery subject",
        "safe_body_preview": "Safe recovery body",
        "attempt_count": attempt_count,
        "last_error_code": None,
        "created_at": updated_at,
        "updated_at": updated_at,
        "completed_at": None,
        "metadata": (
            {"recovery_notification_delivery": {"request_signature": {}}}
            if recovery
            else {}
        ),
    }


def test_recovery_notification_delivery_operations_projection() -> None:
    result = operations.build_recovery_notification_delivery_operations_projection(
        [
            delivery_record(
                "dispatch-old",
                "PENDING",
                updated_at="2026-09-19T01:00:00Z",
            ),
            delivery_record(
                "dispatch-new",
                "SUCCEEDED",
                updated_at="2026-09-19T02:00:00Z",
                attempt_count=1,
            ),
            delivery_record(
                "dispatch-unrelated",
                "FAILED",
                updated_at="2026-09-19T03:00:00Z",
                recovery=False,
            ),
        ],
        limit=1,
        request_trace_id="trace-0845",
    )

    assert result["projection_status"] == "READY"
    assert result["delivery_status"] == "ACTIVE"
    assert result["summary"]["total"] == 2
    assert result["summary"]["pending"] == 1
    assert result["summary"]["succeeded"] == 1
    assert result["summary"]["provider_invocation_performed"] is True
    assert result["by_status"] == {"PENDING": 1, "SUCCEEDED": 1}
    assert [item["dispatch_id"] for item in result["recent"]] == ["dispatch-new"]
    assert result["request_trace_id"] == "trace-0845"
    assert not any(result["redaction"].values())
    assert all(
        sensitive_key not in item
        for item in result["recent"]
        for sensitive_key in (
            "request_signature",
            "provider_payload_hash",
            "safe_body_hash",
            "idempotency_key_hash",
        )
    )


def test_recovery_notification_delivery_operations_empty_and_degraded() -> None:
    empty = operations.build_recovery_notification_delivery_operations_projection(
        [],
        limit=0,
    )
    degraded = operations.build_recovery_notification_delivery_operations_projection(
        None,
        error_code="ag.test.source_unavailable",
        request_trace_id="trace-degraded-0845",
    )

    assert empty["delivery_status"] == "EMPTY"
    assert empty["summary"]["total"] == 0
    assert degraded["projection_status"] == "DEGRADED"
    assert degraded["delivery_status"] == "SOURCE_UNAVAILABLE"
    assert degraded["source_statuses"]["nex-ag"]["error_code"] == (
        "ag.test.source_unavailable"
    )
    assert degraded["request_trace_id"] == "trace-degraded-0845"


def test_recovery_notification_delivery_operations_helper_edges() -> None:
    assert operations._is_recovery_notification_dispatch({}) is False
    assert operations._is_recovery_notification_dispatch(
        {"metadata": {"recovery_notification_delivery": "invalid"}}
    ) is False
