from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Any

ALERT_RECORD_SCHEMA_VERSION = "ag_platform_alert.v1"
ALERT_ROUTING_SCHEMA_VERSION = "ag_alert_routing_decision.v1"
ALERT_STATES = ("PENDING", "FIRING", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED")
ALERT_SEVERITIES = ("INFO", "WARNING", "ERROR", "CRITICAL")
NOTIFICATION_MODES = ("local_only", "private_network", "internet_connected")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class PlatformAlertError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class AlertRule:
    rule_id: str
    policy_id: str
    service_id: str
    minimum_consecutive_failures: int
    grouping_window_seconds: int
    no_data_severity: str = "ERROR"
    at_risk_severity: str = "WARNING"
    breached_severity: str = "CRITICAL"

    def __post_init__(self) -> None:
        for field in ("rule_id", "policy_id", "service_id"):
            _identifier(getattr(self, field), field)
        if self.minimum_consecutive_failures < 1:
            raise PlatformAlertError(
                "alert.failure_floor_invalid", "minimum consecutive failures must be positive"
            )
        if self.grouping_window_seconds < 60:
            raise PlatformAlertError(
                "alert.grouping_window_invalid", "grouping window must be at least 60 seconds"
            )
        for severity in (
            self.no_data_severity,
            self.at_risk_severity,
            self.breached_severity,
        ):
            if severity not in ALERT_SEVERITIES:
                raise PlatformAlertError("alert.severity_invalid", "rule severity is invalid")


@dataclass(frozen=True)
class AlertRecord:
    alert_id: str
    dedup_key: str
    rule_id: str
    policy_id: str
    service_id: str
    state: str
    severity: str
    reason_code: str
    occurrence_count: int
    first_observed_at: str
    last_observed_at: str
    accountable_owner: str
    runbook_ref: str
    suppression_until: str | None = None
    acknowledged_by_hash: str | None = None
    state_revision: int = 1

    def __post_init__(self) -> None:
        for field in (
            "alert_id",
            "rule_id",
            "policy_id",
            "service_id",
            "reason_code",
            "accountable_owner",
            "runbook_ref",
        ):
            _identifier(getattr(self, field), field)
        _digest(self.dedup_key, "dedup_key")
        if self.state not in ALERT_STATES:
            raise PlatformAlertError("alert.state_invalid", "alert state is invalid")
        if self.severity not in ALERT_SEVERITIES:
            raise PlatformAlertError("alert.severity_invalid", "alert severity is invalid")
        if self.occurrence_count < 1:
            raise PlatformAlertError(
                "alert.occurrence_count_invalid", "occurrence count must be positive"
            )
        if self.state_revision < 1:
            raise PlatformAlertError(
                "alert.state_revision_invalid", "alert state revision must be positive"
            )
        first = _timestamp(self.first_observed_at, "first_observed_at")
        last = _timestamp(self.last_observed_at, "last_observed_at")
        if last < first:
            raise PlatformAlertError(
                "alert.timestamp_order_invalid", "last observation must not precede first"
            )
        if self.suppression_until is not None:
            _timestamp(self.suppression_until, "suppression_until")
        if self.acknowledged_by_hash is not None:
            _digest(self.acknowledged_by_hash, "acknowledged_by_hash")

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": ALERT_RECORD_SCHEMA_VERSION,
            "alert_id": self.alert_id,
            "dedup_key": self.dedup_key,
            "rule_id": self.rule_id,
            "policy_id": self.policy_id,
            "service_id": self.service_id,
            "state": self.state,
            "severity": self.severity,
            "reason_code": self.reason_code,
            "occurrence_count": self.occurrence_count,
            "first_observed_at": _wire_timestamp(_timestamp(self.first_observed_at, "first_observed_at")),
            "last_observed_at": _wire_timestamp(_timestamp(self.last_observed_at, "last_observed_at")),
            "accountable_owner": self.accountable_owner,
            "runbook_ref": self.runbook_ref,
            "suppression_until": self.suppression_until,
            "acknowledged_by_hash": self.acknowledged_by_hash,
            "state_revision": self.state_revision,
            "private_payload_included": False,
        }


@dataclass(frozen=True)
class AlertRoutingPolicy:
    notification_mode: str
    environment_class: str
    local_route_alias: str
    external_route_alias: str | None = None
    required_external_severities: tuple[str, ...] = ("CRITICAL",)

    def __post_init__(self) -> None:
        if self.notification_mode not in NOTIFICATION_MODES:
            raise PlatformAlertError("alert.notification_mode_invalid", "notification mode is invalid")
        for field in ("environment_class", "local_route_alias"):
            _identifier(getattr(self, field), field)
        if self.external_route_alias is not None:
            _identifier(self.external_route_alias, "external_route_alias")
        if len(self.required_external_severities) != len(set(self.required_external_severities)):
            raise PlatformAlertError(
                "alert.required_severity_duplicate", "required external severities must be unique"
            )
        if any(item not in ALERT_SEVERITIES for item in self.required_external_severities):
            raise PlatformAlertError(
                "alert.required_severity_invalid", "required external severity is invalid"
            )


def apply_slo_evaluation(
    rule: AlertRule,
    evaluation: Mapping[str, Any],
    *,
    evaluated_at: str,
    previous: AlertRecord | None = None,
) -> AlertRecord | None:
    now = _timestamp(evaluated_at, "evaluated_at")
    status = str(evaluation.get("status") or "")
    if status not in {"HEALTHY", "AT_RISK", "BREACHED", "NO_DATA"}:
        raise PlatformAlertError("alert.evaluation_status_invalid", "SLO evaluation status is invalid")
    if evaluation.get("policy_id") != rule.policy_id or evaluation.get("service_id") != rule.service_id:
        raise PlatformAlertError(
            "alert.evaluation_binding_invalid", "SLO evaluation does not match the alert rule"
        )
    if previous is not None and (
        previous.rule_id != rule.rule_id
        or previous.policy_id != rule.policy_id
        or previous.service_id != rule.service_id
    ):
        raise PlatformAlertError(
            "alert.previous_binding_invalid", "previous alert does not match the alert rule"
        )
    if status == "HEALTHY":
        if previous is None or previous.state == "RESOLVED":
            return previous
        return replace(
            previous,
            state="RESOLVED",
            reason_code="SLO_RECOVERED",
            last_observed_at=_wire_timestamp(now),
            suppression_until=None,
            state_revision=previous.state_revision + 1,
        )

    severity = _severity(rule, status)
    reason_code = str(evaluation.get("reason_code") or "SLO_UNHEALTHY")
    _identifier(reason_code, "reason_code")
    owner = _identifier(evaluation.get("accountable_owner"), "accountable_owner")
    runbook = _identifier(evaluation.get("runbook_ref"), "runbook_ref")
    if previous is None or previous.state == "RESOLVED":
        dedup_key = _dedup_key(rule, now)
        return AlertRecord(
            alert_id=f"alert:{dedup_key[7:31]}",
            dedup_key=dedup_key,
            rule_id=rule.rule_id,
            policy_id=rule.policy_id,
            service_id=rule.service_id,
            state="FIRING" if rule.minimum_consecutive_failures == 1 else "PENDING",
            severity=severity,
            reason_code=reason_code,
            occurrence_count=1,
            first_observed_at=_wire_timestamp(now),
            last_observed_at=_wire_timestamp(now),
            accountable_owner=owner,
            runbook_ref=runbook,
        )

    suppression_active = previous.state == "SUPPRESSED" and previous.suppression_until is not None and _timestamp(previous.suppression_until, "suppression_until") > now
    occurrence_count = previous.occurrence_count + 1
    state = previous.state
    if not suppression_active:
        if state in {"PENDING", "SUPPRESSED"} and occurrence_count >= rule.minimum_consecutive_failures:
            state = "FIRING"
        elif state == "ACKNOWLEDGED" and _severity_rank(severity) > _severity_rank(previous.severity):
            state = "FIRING"
    return replace(
        previous,
        state=state,
        severity=_maximum_severity(previous.severity, severity),
        reason_code=reason_code,
        occurrence_count=occurrence_count,
        last_observed_at=_wire_timestamp(now),
        suppression_until=previous.suppression_until if suppression_active else None,
        state_revision=previous.state_revision + 1,
    )


def acknowledge_alert(
    alert: AlertRecord, *, operator_ref_hash: str, acknowledged_at: str
) -> AlertRecord:
    if alert.state != "FIRING":
        raise PlatformAlertError("alert.acknowledge_state_invalid", "only a firing alert can be acknowledged")
    _digest(operator_ref_hash, "operator_ref_hash")
    changed = _timestamp(acknowledged_at, "acknowledged_at")
    _not_before(alert, changed)
    return replace(
        alert,
        state="ACKNOWLEDGED",
        acknowledged_by_hash=operator_ref_hash,
        last_observed_at=_wire_timestamp(changed),
        state_revision=alert.state_revision + 1,
    )


def suppress_alert(
    alert: AlertRecord, *, suppression_until: str, reason_code: str, changed_at: str
) -> AlertRecord:
    if alert.state not in {"PENDING", "FIRING", "ACKNOWLEDGED"}:
        raise PlatformAlertError("alert.suppression_state_invalid", "alert cannot be suppressed from this state")
    changed = _timestamp(changed_at, "changed_at")
    until = _timestamp(suppression_until, "suppression_until")
    _not_before(alert, changed)
    if until <= changed:
        raise PlatformAlertError("alert.suppression_expiry_invalid", "suppression must expire in the future")
    _identifier(reason_code, "reason_code")
    return replace(
        alert,
        state="SUPPRESSED",
        reason_code=reason_code,
        last_observed_at=_wire_timestamp(changed),
        suppression_until=_wire_timestamp(until),
        state_revision=alert.state_revision + 1,
    )


def route_alert(alert: AlertRecord, policy: AlertRoutingPolicy) -> dict[str, Any]:
    routes: list[dict[str, str]] = []
    if alert.state not in {"SUPPRESSED", "ACKNOWLEDGED"}:
        routes.append({"channel": "LOCAL", "route_alias": policy.local_route_alias})
    external_required = alert.severity in policy.required_external_severities
    activation = "LOCAL_ONLY"
    status = "ROUTED" if routes else "NO_DELIVERY_REQUIRED"
    if alert.state in {"SUPPRESSED", "ACKNOWLEDGED"}:
        activation = "SUPPRESSED" if alert.state == "SUPPRESSED" else "ACKNOWLEDGED"
    elif policy.notification_mode != "local_only":
        if policy.external_route_alias is None:
            activation = "EXTERNAL_NOT_ACTIVATED"
            if external_required:
                status = "BLOCKED"
        else:
            routes.append(
                {
                    "channel": "INTERNAL_WEBHOOK"
                    if policy.notification_mode == "private_network"
                    else "EXTERNAL_WEBHOOK",
                    "route_alias": policy.external_route_alias,
                }
            )
            activation = "EXTERNAL_ACTIVATED"
    intents = [_notification_intent(alert, policy, route) for route in routes]
    return {
        "schema_version": ALERT_ROUTING_SCHEMA_VERSION,
        "alert_id": alert.alert_id,
        "alert_state": alert.state,
        "severity": alert.severity,
        "notification_mode": policy.notification_mode,
        "environment_class": policy.environment_class,
        "routing_status": status,
        "external_activation": activation,
        "external_required": external_required,
        "intents": intents,
        "private_payload_included": False,
    }


def _notification_intent(
    alert: AlertRecord, policy: AlertRoutingPolicy, route: Mapping[str, str]
) -> dict[str, str]:
    payload = {
        "alert_id": alert.alert_id,
        "state": alert.state,
        "severity": alert.severity,
        "service_id": alert.service_id,
        "reason_code": alert.reason_code,
        "runbook_ref": alert.runbook_ref,
    }
    payload_hash = _hash(payload)
    identity = _hash(
        {
            "dedup_key": alert.dedup_key,
            "state": alert.state,
            "channel": route["channel"],
            "route_alias": route["route_alias"],
            "environment_class": policy.environment_class,
        }
    )
    return {
        "channel": route["channel"],
        "route_alias": route["route_alias"],
        "idempotency_key_hash": identity,
        "payload_hash": payload_hash,
    }


def _severity(rule: AlertRule, status: str) -> str:
    if status == "NO_DATA":
        return rule.no_data_severity
    if status == "AT_RISK":
        return rule.at_risk_severity
    return rule.breached_severity


def _maximum_severity(left: str, right: str) -> str:
    return left if _severity_rank(left) >= _severity_rank(right) else right


def _severity_rank(value: str) -> int:
    return ALERT_SEVERITIES.index(value)


def _dedup_key(rule: AlertRule, observed_at: datetime) -> str:
    bucket = int(observed_at.timestamp()) // rule.grouping_window_seconds
    return _hash({"rule_id": rule.rule_id, "service_id": rule.service_id, "bucket": bucket})


def _hash(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PlatformAlertError("alert.digest_invalid", f"{field} must be a SHA-256 digest")
    return value


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PlatformAlertError("alert.identifier_invalid", f"{field} is invalid")
    return value


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise PlatformAlertError("alert.timestamp_invalid", f"{field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlatformAlertError("alert.timestamp_invalid", f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise PlatformAlertError("alert.timestamp_timezone_required", f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _wire_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _not_before(alert: AlertRecord, changed_at: datetime) -> None:
    if changed_at < _timestamp(alert.last_observed_at, "last_observed_at"):
        raise PlatformAlertError("alert.change_time_invalid", "alert change cannot precede its last observation")
