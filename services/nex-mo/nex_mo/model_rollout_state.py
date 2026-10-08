from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from nex_mo.model_capacity_scheduler import CapacityReservation
from nex_mo.model_rollout import ModelRevisionIdentity, ModelRolloutError

ROLLOUT_STATES = frozenset(
    {"REGISTERED", "VALIDATING", "READY", "CANARY", "BLOCKED", "ACTIVE", "ROLLED_BACK"}
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class CanaryPolicy:
    traffic_percent: float
    observation_seconds: int
    minimum_sample_count: int
    maximum_error_rate: float
    minimum_quality_score: float
    maximum_p95_latency_ms: int

    def __post_init__(self) -> None:
        if not 0 < self.traffic_percent <= 25:
            raise ModelRolloutError(
                "mo.canary_traffic_invalid",
                "canary traffic must be greater than zero and at most 25 percent",
            )
        if self.observation_seconds < 60 or self.minimum_sample_count < 20:
            raise ModelRolloutError(
                "mo.canary_observation_invalid",
                "canary observation and sample floors are not met",
            )
        if not 0 <= self.maximum_error_rate <= 1:
            raise ModelRolloutError(
                "mo.canary_error_budget_invalid",
                "canary error rate must be between zero and one",
            )
        if not 0 <= self.minimum_quality_score <= 1:
            raise ModelRolloutError(
                "mo.canary_quality_budget_invalid",
                "canary quality score must be between zero and one",
            )
        if self.maximum_p95_latency_ms < 1:
            raise ModelRolloutError(
                "mo.canary_latency_budget_invalid",
                "canary latency budget must be positive",
            )

    @property
    def policy_hash(self) -> str:
        return _digest(self.to_wire())

    def to_wire(self) -> dict[str, Any]:
        return {
            "traffic_percent": self.traffic_percent,
            "observation_seconds": self.observation_seconds,
            "minimum_sample_count": self.minimum_sample_count,
            "maximum_error_rate": self.maximum_error_rate,
            "minimum_quality_score": self.minimum_quality_score,
            "maximum_p95_latency_ms": self.maximum_p95_latency_ms,
        }


@dataclass(frozen=True)
class CanaryMetrics:
    identity_fingerprint: str
    sample_count: int
    error_rate: float
    quality_score: float
    p95_latency_ms: int
    observed_seconds: int
    measured_at: str

    def __post_init__(self) -> None:
        _sha256(self.identity_fingerprint, "identity_fingerprint")
        if self.sample_count < 0 or self.observed_seconds < 0 or self.p95_latency_ms < 0:
            raise ModelRolloutError(
                "mo.canary_metric_count_invalid",
                "canary count and duration metrics must not be negative",
            )
        if not 0 <= self.error_rate <= 1 or not 0 <= self.quality_score <= 1:
            raise ModelRolloutError(
                "mo.canary_metric_rate_invalid",
                "canary rate metrics must be between zero and one",
            )
        _timestamp(self.measured_at, "measured_at")

    def to_wire(self) -> dict[str, Any]:
        return {
            "identity_fingerprint": self.identity_fingerprint,
            "sample_count": self.sample_count,
            "error_rate": self.error_rate,
            "quality_score": self.quality_score,
            "p95_latency_ms": self.p95_latency_ms,
            "observed_seconds": self.observed_seconds,
            "measured_at": self.measured_at,
        }


@dataclass(frozen=True)
class ModelRolloutRecord:
    rollout_id: str
    identity: ModelRevisionIdentity
    state: str
    state_revision: int
    last_known_good_binding_id: str
    last_known_good_identity_fingerprint: str
    readiness_evidence_digest: str | None
    calibration_profile_id: str | None
    calibration_profile_hash: str | None
    reservation_id: str | None
    canary_policy_hash: str | None
    canary_status: str | None
    activated_binding_id: str | None
    failure_code: str | None
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        for field_name in ("rollout_id", "last_known_good_binding_id"):
            _identifier(getattr(self, field_name), field_name)
        _sha256(
            self.last_known_good_identity_fingerprint,
            "last_known_good_identity_fingerprint",
        )
        if self.state not in ROLLOUT_STATES:
            raise ModelRolloutError(
                "mo.rollout_state_invalid",
                "unsupported rollout state",
            )
        if self.state_revision < 1:
            raise ModelRolloutError(
                "mo.rollout_state_revision_invalid",
                "rollout state revision must be positive",
            )
        created = _timestamp(self.created_at, "created_at")
        updated = _timestamp(self.updated_at, "updated_at")
        if updated < created:
            raise ModelRolloutError(
                "mo.rollout_timestamp_invalid",
                "rollout update must not precede creation",
            )
        for field_name in (
            "readiness_evidence_digest",
            "calibration_profile_hash",
            "canary_policy_hash",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _sha256(value, field_name)
        for field_name in (
            "calibration_profile_id",
            "reservation_id",
            "activated_binding_id",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _identifier(value, field_name)

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "mo_model_rollout.v1",
            "rollout_id": self.rollout_id,
            "identity": self.identity.to_wire(),
            "identity_fingerprint": self.identity.fingerprint,
            "state": self.state,
            "state_revision": self.state_revision,
            "last_known_good_binding_id": self.last_known_good_binding_id,
            "last_known_good_identity_fingerprint": self.last_known_good_identity_fingerprint,
            "readiness_evidence_digest": self.readiness_evidence_digest,
            "calibration_profile_id": self.calibration_profile_id,
            "calibration_profile_hash": self.calibration_profile_hash,
            "reservation_id": self.reservation_id,
            "canary_policy_hash": self.canary_policy_hash,
            "canary_status": self.canary_status,
            "activated_binding_id": self.activated_binding_id,
            "failure_code": self.failure_code,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def register_rollout(
    identity: ModelRevisionIdentity,
    *,
    rollout_id: str,
    last_known_good_binding_id: str,
    last_known_good_identity_fingerprint: str,
    created_at: str,
) -> ModelRolloutRecord:
    if identity.fingerprint == last_known_good_identity_fingerprint:
        raise ModelRolloutError(
            "mo.rollout_candidate_revision_required",
            "candidate must differ from the last-known-good identity",
        )
    return ModelRolloutRecord(
        rollout_id=rollout_id,
        identity=identity,
        state="REGISTERED",
        state_revision=1,
        last_known_good_binding_id=last_known_good_binding_id,
        last_known_good_identity_fingerprint=last_known_good_identity_fingerprint,
        readiness_evidence_digest=None,
        calibration_profile_id=None,
        calibration_profile_hash=None,
        reservation_id=None,
        canary_policy_hash=None,
        canary_status=None,
        activated_binding_id=None,
        failure_code=None,
        created_at=created_at,
        updated_at=created_at,
    )


def begin_validation(record: ModelRolloutRecord, *, changed_at: str) -> ModelRolloutRecord:
    return _transition(record, expected="REGISTERED", target="VALIDATING", changed_at=changed_at)


def mark_rollout_ready(
    record: ModelRolloutRecord,
    readiness: Mapping[str, Any],
    calibration: Mapping[str, Any],
    reservation: CapacityReservation,
    *,
    changed_at: str,
) -> ModelRolloutRecord:
    if record.state != "VALIDATING":
        raise _transition_error(record.state, "READY")
    if (
        readiness.get("status") != "READY"
        or readiness.get("identity_fingerprint") != record.identity.fingerprint
        or not isinstance(readiness.get("evidence_digest"), str)
        or _SHA256.fullmatch(str(readiness.get("evidence_digest"))) is None
    ):
        raise ModelRolloutError(
            "mo.rollout_readiness_required",
            "exact revision readiness evidence is required",
        )
    if (
        calibration.get("status") != "CALIBRATED"
        or calibration.get("identity_fingerprint") != record.identity.fingerprint
        or not calibration.get("profile_id")
        or _SHA256.fullmatch(str(calibration.get("profile_hash") or "")) is None
    ):
        raise ModelRolloutError(
            "mo.rollout_calibration_required",
            "ACTIVE exact revision calibration is required",
        )
    if (
        reservation.identity_fingerprint != record.identity.fingerprint
        or reservation.state != "RESERVED"
    ):
        raise ModelRolloutError(
            "mo.rollout_reservation_required",
            "active exact revision capacity reservation is required",
        )
    _validate_changed_at(record, changed_at)
    return replace(
        record,
        state="READY",
        state_revision=record.state_revision + 1,
        readiness_evidence_digest=str(readiness["evidence_digest"]),
        calibration_profile_id=str(calibration["profile_id"]),
        calibration_profile_hash=str(calibration["profile_hash"]),
        reservation_id=reservation.reservation_id,
        updated_at=changed_at,
    )


def start_canary(
    record: ModelRolloutRecord,
    policy: CanaryPolicy,
    *,
    changed_at: str,
) -> ModelRolloutRecord:
    if record.state != "READY":
        raise _transition_error(record.state, "CANARY")
    if not all(
        (
            record.readiness_evidence_digest,
            record.calibration_profile_id,
            record.calibration_profile_hash,
            record.reservation_id,
            record.last_known_good_binding_id,
        )
    ):
        raise ModelRolloutError(
            "mo.rollout_canary_prerequisite_missing",
            "canary prerequisites are incomplete",
        )
    _validate_changed_at(record, changed_at)
    return replace(
        record,
        state="CANARY",
        state_revision=record.state_revision + 1,
        canary_policy_hash=policy.policy_hash,
        canary_status="RUNNING",
        updated_at=changed_at,
    )


def evaluate_canary(
    record: ModelRolloutRecord,
    policy: CanaryPolicy,
    metrics: CanaryMetrics,
    *,
    changed_at: str,
) -> tuple[ModelRolloutRecord, dict[str, Any]]:
    if record.state != "CANARY" or record.canary_policy_hash != policy.policy_hash:
        raise ModelRolloutError(
            "mo.rollout_canary_not_active",
            "matching active canary policy is required",
        )
    _validate_changed_at(record, changed_at)
    checks = {
        "identity_matches": metrics.identity_fingerprint == record.identity.fingerprint,
        "sample_floor_met": metrics.sample_count >= policy.minimum_sample_count,
        "observation_window_met": metrics.observed_seconds >= policy.observation_seconds,
        "error_budget_met": metrics.error_rate <= policy.maximum_error_rate,
        "quality_budget_met": metrics.quality_score >= policy.minimum_quality_score,
        "latency_budget_met": metrics.p95_latency_ms <= policy.maximum_p95_latency_ms,
    }
    passed = all(checks.values())
    decision = {
        "schema_version": "mo_canary_decision.v1",
        "status": "PASS" if passed else "FAIL",
        "promotable": passed,
        "checks": checks,
        "policy_hash": policy.policy_hash,
        "metrics_digest": _digest(metrics.to_wire()),
        "identity_fingerprint": record.identity.fingerprint,
        "evaluated_at": changed_at,
    }
    updated = replace(
        record,
        state="CANARY" if passed else "BLOCKED",
        state_revision=record.state_revision + 1,
        canary_status="PASSED" if passed else "FAILED",
        failure_code=None if passed else "canary_budget_failed",
        updated_at=changed_at,
    )
    return updated, decision


def mark_rollout_active(
    record: ModelRolloutRecord,
    *,
    activated_binding_id: str,
    changed_at: str,
) -> ModelRolloutRecord:
    if record.state != "CANARY" or record.canary_status != "PASSED":
        raise ModelRolloutError(
            "mo.rollout_promotion_not_admitted",
            "a passing canary is required before alias activation",
        )
    _identifier(activated_binding_id, "activated_binding_id")
    _validate_changed_at(record, changed_at)
    return replace(
        record,
        state="ACTIVE",
        state_revision=record.state_revision + 1,
        activated_binding_id=activated_binding_id,
        updated_at=changed_at,
    )


def mark_rollout_rolled_back(
    record: ModelRolloutRecord,
    *,
    failure_code: str,
    changed_at: str,
) -> ModelRolloutRecord:
    if record.state != "ACTIVE" or record.activated_binding_id is None:
        raise ModelRolloutError(
            "mo.rollout_rollback_not_available",
            "an active rollout binding is required before rollback",
        )
    _identifier(failure_code, "failure_code")
    _validate_changed_at(record, changed_at)
    return replace(
        record,
        state="ROLLED_BACK",
        state_revision=record.state_revision + 1,
        failure_code=failure_code,
        updated_at=changed_at,
    )


def _transition(
    record: ModelRolloutRecord,
    *,
    expected: str,
    target: str,
    changed_at: str,
) -> ModelRolloutRecord:
    if record.state != expected:
        raise _transition_error(record.state, target)
    _validate_changed_at(record, changed_at)
    return replace(
        record,
        state=target,
        state_revision=record.state_revision + 1,
        updated_at=changed_at,
    )


def _transition_error(current: str, target: str) -> ModelRolloutError:
    return ModelRolloutError(
        "mo.rollout_transition_invalid",
        f"rollout cannot transition from {current} to {target}",
    )


def _validate_changed_at(record: ModelRolloutRecord, changed_at: str) -> None:
    if _timestamp(changed_at, "changed_at") < _timestamp(record.updated_at, "updated_at"):
        raise ModelRolloutError(
            "mo.rollout_timestamp_invalid",
            "rollout transition must not precede the current state",
        )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ModelRolloutError(
            f"mo.{field_name}_invalid",
            f"{field_name} must be a stable identifier",
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ModelRolloutError(
            f"mo.{field_name}_invalid",
            f"{field_name} must be a SHA-256 digest",
        )
    return value


def _timestamp(value: object, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelRolloutError(
            f"mo.{field_name}_invalid",
            f"{field_name} must be ISO 8601",
        ) from exc
    if parsed.tzinfo is None:
        raise ModelRolloutError(
            f"mo.{field_name}_invalid",
            f"{field_name} must include a timezone",
        )
    return parsed.astimezone(UTC)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
