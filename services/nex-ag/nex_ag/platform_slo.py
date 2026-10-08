from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import math
import re
from typing import Any, Sequence

from nex_runtime import ObservabilitySignal

SLO_POLICY_SCHEMA_VERSION = "ag_slo_policy.v1"
SLO_EVALUATION_SCHEMA_VERSION = "ag_slo_evaluation.v1"
SLO_COMPARATORS = ("GTE", "LTE")
SLO_EVALUATION_STATUSES = ("HEALTHY", "AT_RISK", "BREACHED", "NO_DATA")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")


class SloPolicyError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class SloPolicy:
    policy_id: str
    policy_revision: int
    service_id: str
    sli_name: str
    signal_name: str
    measurement_name: str
    comparator: str
    good_threshold: float
    objective_target: float
    warning_burn_rate: float
    critical_burn_rate: float
    window_seconds: int
    minimum_sample_count: int
    maximum_signal_age_seconds: int
    accountable_owner: str
    runbook_ref: str

    def __post_init__(self) -> None:
        for field in (
            "policy_id",
            "service_id",
            "sli_name",
            "signal_name",
            "measurement_name",
            "accountable_owner",
            "runbook_ref",
        ):
            _identifier(getattr(self, field), field)
        if self.policy_revision < 1:
            raise SloPolicyError("slo.policy_revision_invalid", "policy revision must be positive")
        if self.comparator not in SLO_COMPARATORS:
            raise SloPolicyError("slo.comparator_invalid", "comparator is not supported")
        numeric = (
            self.good_threshold,
            self.objective_target,
            self.warning_burn_rate,
            self.critical_burn_rate,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise SloPolicyError("slo.numeric_value_invalid", "policy values must be finite")
        if not 0 < self.objective_target < 1:
            raise SloPolicyError(
                "slo.objective_target_invalid", "objective target must be between zero and one"
            )
        if self.warning_burn_rate < 1 or self.critical_burn_rate <= self.warning_burn_rate:
            raise SloPolicyError(
                "slo.burn_rate_invalid",
                "critical burn rate must exceed a warning burn rate of at least one",
            )
        if self.window_seconds < 60:
            raise SloPolicyError("slo.window_invalid", "SLO window must be at least 60 seconds")
        if self.minimum_sample_count < 1:
            raise SloPolicyError("slo.sample_floor_invalid", "minimum sample count must be positive")
        if not 1 <= self.maximum_signal_age_seconds <= self.window_seconds:
            raise SloPolicyError(
                "slo.freshness_invalid", "signal freshness must fit within the SLO window"
            )

    @property
    def policy_hash(self) -> str:
        return "sha256:" + hashlib.sha256(
            json.dumps(self.to_wire(include_hash=False), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def to_wire(self, *, include_hash: bool = True) -> dict[str, Any]:
        wire = {
            "schema_version": SLO_POLICY_SCHEMA_VERSION,
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "service_id": self.service_id,
            "sli_name": self.sli_name,
            "signal_name": self.signal_name,
            "measurement_name": self.measurement_name,
            "comparator": self.comparator,
            "good_threshold": self.good_threshold,
            "objective_target": self.objective_target,
            "warning_burn_rate": self.warning_burn_rate,
            "critical_burn_rate": self.critical_burn_rate,
            "window_seconds": self.window_seconds,
            "minimum_sample_count": self.minimum_sample_count,
            "maximum_signal_age_seconds": self.maximum_signal_age_seconds,
            "accountable_owner": self.accountable_owner,
            "runbook_ref": self.runbook_ref,
        }
        if include_hash:
            wire["policy_hash"] = self.policy_hash
        return wire


def evaluate_slo(
    policy: SloPolicy,
    signals: Sequence[ObservabilitySignal],
    *,
    evaluated_at: str,
) -> dict[str, Any]:
    evaluated = _timestamp(evaluated_at, "evaluated_at")
    window_start = evaluated - timedelta(seconds=policy.window_seconds)
    samples: list[tuple[datetime, float]] = []
    for signal in signals:
        observed = _timestamp(signal.observed_at, "observed_at")
        if observed > evaluated:
            raise SloPolicyError("slo.signal_from_future", "SLO signal is in the future")
        if signal.service_id != policy.service_id or signal.signal_name != policy.signal_name:
            continue
        if observed < window_start:
            continue
        measurements = signal.measurements or {}
        value = measurements.get(policy.measurement_name)
        if value is None:
            continue
        numeric = float(value)
        if not math.isfinite(numeric):
            raise SloPolicyError("slo.sample_invalid", "SLO sample must be finite")
        samples.append((observed, numeric))

    samples.sort(key=lambda item: item[0])
    latest = samples[-1][0] if samples else None
    stale = latest is None or (evaluated - latest).total_seconds() > policy.maximum_signal_age_seconds
    if len(samples) < policy.minimum_sample_count or stale:
        return _evaluation(
            policy,
            evaluated,
            status="NO_DATA",
            sample_count=len(samples),
            good_count=0,
            bad_count=0,
            attainment=None,
            burn_rate=None,
            latest_observed_at=latest,
            reason_code="SLO_SIGNAL_STALE" if stale and samples else "SLO_SAMPLE_FLOOR_NOT_MET",
        )

    good_count = sum(_is_good(policy, value) for _, value in samples)
    sample_count = len(samples)
    bad_count = sample_count - good_count
    attainment = good_count / sample_count
    budget = 1.0 - policy.objective_target
    burn_rate = (1.0 - attainment) / budget
    if burn_rate >= policy.critical_burn_rate:
        status = "BREACHED"
        reason_code = "SLO_CRITICAL_BURN"
    elif burn_rate >= policy.warning_burn_rate or attainment < policy.objective_target:
        status = "AT_RISK"
        reason_code = "SLO_WARNING_BURN"
    else:
        status = "HEALTHY"
        reason_code = "SLO_OBJECTIVE_MET"
    return _evaluation(
        policy,
        evaluated,
        status=status,
        sample_count=sample_count,
        good_count=good_count,
        bad_count=bad_count,
        attainment=attainment,
        burn_rate=burn_rate,
        latest_observed_at=latest,
        reason_code=reason_code,
    )


def default_platform_slo_policies() -> tuple[SloPolicy, ...]:
    specs = (
        ("nex-oa", "oa.availability", "oa.request.availability", "success_ratio", "GTE", 1.0, "identity"),
        ("nex-ae-api", "ae.workflow", "ae.workflow.completion", "success_ratio", "GTE", 1.0, "experience"),
        ("nex-cx", "cx.index_freshness", "cx.index.freshness", "freshness_age_seconds", "LTE", 300.0, "content"),
        ("nex-mo", "mo.provider_latency", "mo.provider.latency", "latency_ms", "LTE", 12_000.0, "model-ops"),
        ("nex-ag", "ag.notification", "ag.notification.delivery", "success_ratio", "GTE", 1.0, "platform-ops"),
    )
    return tuple(
        SloPolicy(
            policy_id=f"slo:{service_id}:{sli_name.split('.', 1)[1]}",
            policy_revision=1,
            service_id=service_id,
            sli_name=sli_name,
            signal_name=signal_name,
            measurement_name=measurement_name,
            comparator=comparator,
            good_threshold=threshold,
            objective_target=0.99,
            warning_burn_rate=1.0,
            critical_burn_rate=5.0,
            window_seconds=300,
            minimum_sample_count=3,
            maximum_signal_age_seconds=60,
            accountable_owner=owner,
            runbook_ref=f"runbook:{service_id}:{sli_name.split('.', 1)[1]}",
        )
        for service_id, sli_name, signal_name, measurement_name, comparator, threshold, owner in specs
    )


def _evaluation(
    policy: SloPolicy,
    evaluated_at: datetime,
    *,
    status: str,
    sample_count: int,
    good_count: int,
    bad_count: int,
    attainment: float | None,
    burn_rate: float | None,
    latest_observed_at: datetime | None,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "schema_version": SLO_EVALUATION_SCHEMA_VERSION,
        "policy_id": policy.policy_id,
        "policy_revision": policy.policy_revision,
        "policy_hash": policy.policy_hash,
        "service_id": policy.service_id,
        "sli_name": policy.sli_name,
        "status": status,
        "reason_code": reason_code,
        "evaluated_at": _wire_timestamp(evaluated_at),
        "window_seconds": policy.window_seconds,
        "sample_count": sample_count,
        "good_count": good_count,
        "bad_count": bad_count,
        "attainment": attainment,
        "burn_rate": burn_rate,
        "latest_observed_at": _wire_timestamp(latest_observed_at) if latest_observed_at else None,
        "accountable_owner": policy.accountable_owner,
        "runbook_ref": policy.runbook_ref,
        "private_payload_included": False,
    }


def _is_good(policy: SloPolicy, value: float) -> bool:
    if policy.comparator == "GTE":
        return value >= policy.good_threshold
    return value <= policy.good_threshold


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise SloPolicyError("slo.identifier_invalid", f"{field} is invalid")
    return value


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise SloPolicyError("slo.timestamp_invalid", f"{field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SloPolicyError("slo.timestamp_invalid", f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise SloPolicyError("slo.timestamp_timezone_required", f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _wire_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
