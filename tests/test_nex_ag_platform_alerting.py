from __future__ import annotations

import pytest

from nex_ag.platform_alerting import (
    AlertRecord,
    AlertRoutingPolicy,
    AlertRule,
    PlatformAlertError,
    acknowledge_alert,
    apply_slo_evaluation,
    route_alert,
    suppress_alert,
)

DIGEST = "sha256:" + "a" * 64


def _rule(**overrides: object) -> AlertRule:
    values: dict[str, object] = {
        "rule_id": "rule:nex-cx:index-freshness",
        "policy_id": "slo:nex-cx:index-freshness",
        "service_id": "nex-cx",
        "minimum_consecutive_failures": 2,
        "grouping_window_seconds": 300,
    }
    values.update(overrides)
    return AlertRule(**values)  # type: ignore[arg-type]


def _evaluation(status: str = "BREACHED", **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "policy_id": "slo:nex-cx:index-freshness",
        "service_id": "nex-cx",
        "status": status,
        "reason_code": f"SLO_{status}",
        "accountable_owner": "content",
        "runbook_ref": "runbook:nex-cx:index-freshness",
    }
    values.update(overrides)
    return values


def _firing() -> AlertRecord:
    first = apply_slo_evaluation(
        _rule(), _evaluation(), evaluated_at="2026-10-08T01:00:00Z"
    )
    assert first is not None
    second = apply_slo_evaluation(
        _rule(), _evaluation(), previous=first, evaluated_at="2026-10-08T01:00:10Z"
    )
    assert second is not None
    return second


def test_alert_lifecycle_debounce_acknowledge_and_recovery() -> None:
    first = apply_slo_evaluation(_rule(), _evaluation(), evaluated_at="2026-10-08T01:00:00Z")
    assert first is not None
    assert first.state == "PENDING"
    assert first.occurrence_count == 1
    assert first.to_wire()["private_payload_included"] is False

    firing = apply_slo_evaluation(
        _rule(), _evaluation(), previous=first, evaluated_at="2026-10-08T01:00:10Z"
    )
    assert firing is not None
    assert firing.state == "FIRING"
    assert firing.occurrence_count == 2

    acknowledged = acknowledge_alert(
        firing, operator_ref_hash=DIGEST, acknowledged_at="2026-10-08T01:00:11Z"
    )
    assert acknowledged.state == "ACKNOWLEDGED"
    assert acknowledged.acknowledged_by_hash == DIGEST

    resolved = apply_slo_evaluation(
        _rule(), _evaluation("HEALTHY"), previous=acknowledged, evaluated_at="2026-10-08T01:00:20Z"
    )
    assert resolved is not None
    assert resolved.state == "RESOLVED"
    assert resolved.reason_code == "SLO_RECOVERED"
    assert apply_slo_evaluation(
        _rule(), _evaluation("HEALTHY"), previous=resolved, evaluated_at="2026-10-08T01:00:30Z"
    ) == resolved
    assert apply_slo_evaluation(
        _rule(), _evaluation("HEALTHY"), evaluated_at="2026-10-08T01:00:30Z"
    ) is None


def test_single_failure_rule_fires_and_resolved_rule_reopens() -> None:
    rule = _rule(minimum_consecutive_failures=1)
    first = apply_slo_evaluation(rule, _evaluation(), evaluated_at="2026-10-08T01:00:00Z")
    assert first is not None and first.state == "FIRING"
    resolved = apply_slo_evaluation(
        rule, _evaluation("HEALTHY"), previous=first, evaluated_at="2026-10-08T01:00:10Z"
    )
    reopened = apply_slo_evaluation(
        rule, _evaluation("AT_RISK"), previous=resolved, evaluated_at="2026-10-08T01:05:01Z"
    )
    assert reopened is not None
    assert reopened.alert_id != first.alert_id
    assert reopened.severity == "WARNING"

    no_data = apply_slo_evaluation(
        rule, _evaluation("NO_DATA"), evaluated_at="2026-10-08T01:10:00Z"
    )
    assert no_data is not None and no_data.severity == "ERROR"


def test_suppression_expiry_and_acknowledged_severity_escalation() -> None:
    firing = _firing()
    suppressed = suppress_alert(
        firing,
        suppression_until="2026-10-08T01:10:00Z",
        reason_code="MAINTENANCE_WINDOW",
        changed_at="2026-10-08T01:00:20Z",
    )
    still_suppressed = apply_slo_evaluation(
        _rule(), _evaluation("AT_RISK"), previous=suppressed, evaluated_at="2026-10-08T01:01:00Z"
    )
    assert still_suppressed is not None and still_suppressed.state == "SUPPRESSED"
    expired = apply_slo_evaluation(
        _rule(), _evaluation(), previous=still_suppressed, evaluated_at="2026-10-08T01:10:01Z"
    )
    assert expired is not None and expired.state == "FIRING"
    assert expired.suppression_until is None

    warning = apply_slo_evaluation(
        _rule(minimum_consecutive_failures=1),
        _evaluation("AT_RISK"),
        evaluated_at="2026-10-08T01:20:00Z",
    )
    assert warning is not None
    acknowledged = acknowledge_alert(
        warning, operator_ref_hash=DIGEST, acknowledged_at="2026-10-08T01:20:01Z"
    )
    escalated = apply_slo_evaluation(
        _rule(minimum_consecutive_failures=1),
        _evaluation(),
        previous=acknowledged,
        evaluated_at="2026-10-08T01:20:02Z",
    )
    assert escalated is not None and escalated.state == "FIRING"
    assert escalated.severity == "CRITICAL"

    unchanged = apply_slo_evaluation(
        _rule(minimum_consecutive_failures=1),
        _evaluation("AT_RISK"),
        previous=acknowledged,
        evaluated_at="2026-10-08T01:20:03Z",
    )
    assert unchanged is not None and unchanged.state == "ACKNOWLEDGED"

    suppression_without_expiry = AlertRecord(
        **{**suppressed.__dict__, "suppression_until": None}
    )
    resumed = apply_slo_evaluation(
        _rule(),
        _evaluation(),
        previous=suppression_without_expiry,
        evaluated_at="2026-10-08T01:02:00Z",
    )
    assert resumed is not None and resumed.state == "FIRING"


def test_routing_modes_and_honest_external_activation() -> None:
    alert = _firing()
    local = route_alert(
        alert,
        AlertRoutingPolicy("local_only", "test", "ag-local"),
    )
    assert local["routing_status"] == "ROUTED"
    assert local["external_activation"] == "LOCAL_ONLY"
    assert [item["channel"] for item in local["intents"]] == ["LOCAL"]

    blocked = route_alert(
        alert,
        AlertRoutingPolicy("internet_connected", "staging", "ag-local"),
    )
    assert blocked["routing_status"] == "BLOCKED"
    assert blocked["external_activation"] == "EXTERNAL_NOT_ACTIVATED"
    assert blocked["external_required"] is True

    private = route_alert(
        alert,
        AlertRoutingPolicy("private_network", "staging", "ag-local", "incident-internal"),
    )
    internet = route_alert(
        alert,
        AlertRoutingPolicy("internet_connected", "staging", "ag-local", "incident-external"),
    )
    assert [item["channel"] for item in private["intents"]] == ["LOCAL", "INTERNAL_WEBHOOK"]
    assert [item["channel"] for item in internet["intents"]] == ["LOCAL", "EXTERNAL_WEBHOOK"]
    assert all(item["payload_hash"].startswith("sha256:") for item in internet["intents"])
    assert "endpoint" not in str(internet).lower()


def test_routing_suppressed_acknowledged_and_optional_external() -> None:
    firing = _firing()
    suppressed = suppress_alert(
        firing,
        suppression_until="2026-10-08T01:10:00Z",
        reason_code="MAINTENANCE_WINDOW",
        changed_at="2026-10-08T01:00:20Z",
    )
    suppressed_route = route_alert(
        suppressed, AlertRoutingPolicy("internet_connected", "test", "ag-local")
    )
    assert suppressed_route["routing_status"] == "NO_DELIVERY_REQUIRED"
    assert suppressed_route["external_activation"] == "SUPPRESSED"
    assert suppressed_route["intents"] == []

    acknowledged = acknowledge_alert(
        firing, operator_ref_hash=DIGEST, acknowledged_at="2026-10-08T01:00:20Z"
    )
    assert route_alert(
        acknowledged, AlertRoutingPolicy("local_only", "test", "ag-local")
    )["external_activation"] == "ACKNOWLEDGED"

    warning = apply_slo_evaluation(
        _rule(minimum_consecutive_failures=1),
        _evaluation("AT_RISK"),
        evaluated_at="2026-10-08T01:30:00Z",
    )
    assert warning is not None
    optional = route_alert(
        warning, AlertRoutingPolicy("internet_connected", "test", "ag-local")
    )
    assert optional["routing_status"] == "ROUTED"
    assert optional["external_activation"] == "EXTERNAL_NOT_ACTIVATED"


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"rule_id": "bad value"}, "alert.identifier_invalid"),
        ({"minimum_consecutive_failures": 0}, "alert.failure_floor_invalid"),
        ({"grouping_window_seconds": 59}, "alert.grouping_window_invalid"),
        ({"no_data_severity": "PANIC"}, "alert.severity_invalid"),
    ],
)
def test_rule_rejects_invalid_values(overrides: dict[str, object], error_code: str) -> None:
    with pytest.raises(PlatformAlertError) as exc_info:
        _rule(**overrides)
    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("policy", "error_code"),
    [
        (lambda: AlertRoutingPolicy("bad", "test", "local"), "alert.notification_mode_invalid"),
        (lambda: AlertRoutingPolicy("local_only", "bad value", "local"), "alert.identifier_invalid"),
        (lambda: AlertRoutingPolicy("local_only", "test", "local", "bad value"), "alert.identifier_invalid"),
        (lambda: AlertRoutingPolicy("local_only", "test", "local", required_external_severities=("CRITICAL", "CRITICAL")), "alert.required_severity_duplicate"),
        (lambda: AlertRoutingPolicy("local_only", "test", "local", required_external_severities=("PANIC",)), "alert.required_severity_invalid"),
    ],
)
def test_routing_policy_rejects_invalid_values(policy, error_code: str) -> None:
    with pytest.raises(PlatformAlertError) as exc_info:
        policy()
    assert exc_info.value.error_code == error_code


def test_evaluation_and_operator_actions_fail_closed() -> None:
    with pytest.raises(PlatformAlertError) as exc_info:
        apply_slo_evaluation(_rule(), _evaluation("BAD"), evaluated_at="2026-10-08T01:00:00Z")
    assert exc_info.value.error_code == "alert.evaluation_status_invalid"
    with pytest.raises(PlatformAlertError) as exc_info:
        apply_slo_evaluation(_rule(), _evaluation(policy_id="other"), evaluated_at="2026-10-08T01:00:00Z")
    assert exc_info.value.error_code == "alert.evaluation_binding_invalid"
    previous = _firing()
    other = AlertRecord(**{**previous.__dict__, "rule_id": "rule:other"})
    with pytest.raises(PlatformAlertError) as exc_info:
        apply_slo_evaluation(_rule(), _evaluation(), previous=other, evaluated_at="2026-10-08T01:01:00Z")
    assert exc_info.value.error_code == "alert.previous_binding_invalid"
    with pytest.raises(PlatformAlertError) as exc_info:
        acknowledge_alert(previous, operator_ref_hash="bad", acknowledged_at="2026-10-08T01:01:00Z")
    assert exc_info.value.error_code == "alert.digest_invalid"
    with pytest.raises(PlatformAlertError) as exc_info:
        acknowledge_alert(replace_state(previous, "PENDING"), operator_ref_hash=DIGEST, acknowledged_at="2026-10-08T01:01:00Z")
    assert exc_info.value.error_code == "alert.acknowledge_state_invalid"
    with pytest.raises(PlatformAlertError) as exc_info:
        suppress_alert(replace_state(previous, "RESOLVED"), suppression_until="2026-10-08T01:10:00Z", reason_code="MAINTENANCE", changed_at="2026-10-08T01:01:00Z")
    assert exc_info.value.error_code == "alert.suppression_state_invalid"
    with pytest.raises(PlatformAlertError) as exc_info:
        suppress_alert(previous, suppression_until="2026-10-08T01:00:00Z", reason_code="MAINTENANCE", changed_at="2026-10-08T01:01:00Z")
    assert exc_info.value.error_code == "alert.suppression_expiry_invalid"
    with pytest.raises(PlatformAlertError) as exc_info:
        acknowledge_alert(previous, operator_ref_hash=DIGEST, acknowledged_at="2026-10-08T00:59:00Z")
    assert exc_info.value.error_code == "alert.change_time_invalid"
    with pytest.raises(PlatformAlertError) as exc_info:
        apply_slo_evaluation(_rule(), _evaluation(), evaluated_at=None)  # type: ignore[arg-type]
    assert exc_info.value.error_code == "alert.timestamp_invalid"
    with pytest.raises(PlatformAlertError) as exc_info:
        apply_slo_evaluation(
            _rule(), _evaluation(), evaluated_at="2026-10-08T01:00:00"
        )
    assert exc_info.value.error_code == "alert.timestamp_timezone_required"


def replace_state(alert: AlertRecord, state: str) -> AlertRecord:
    return AlertRecord(**{**alert.__dict__, "state": state})


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"dedup_key": "bad"}, "alert.digest_invalid"),
        ({"state": "BAD"}, "alert.state_invalid"),
        ({"severity": "BAD"}, "alert.severity_invalid"),
        ({"occurrence_count": 0}, "alert.occurrence_count_invalid"),
        ({"state_revision": 0}, "alert.state_revision_invalid"),
        ({"last_observed_at": "2026-10-08T00:00:00Z"}, "alert.timestamp_order_invalid"),
        ({"suppression_until": "bad"}, "alert.timestamp_invalid"),
        ({"acknowledged_by_hash": "bad"}, "alert.digest_invalid"),
    ],
)
def test_alert_record_rejects_invalid_values(overrides: dict[str, object], error_code: str) -> None:
    alert = _firing()
    with pytest.raises(PlatformAlertError) as exc_info:
        AlertRecord(**{**alert.__dict__, **overrides})
    assert exc_info.value.error_code == error_code
