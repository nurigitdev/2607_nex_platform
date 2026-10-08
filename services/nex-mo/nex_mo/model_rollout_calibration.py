from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from nex_mo.model_rollout import (
    MODEL_CAPABILITIES,
    ModelRevisionIdentity,
    ModelRolloutError,
)

CALIBRATION_STATUSES = frozenset({"CANDIDATE", "ACTIVE", "REJECTED", "RETIRED"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED_METRICS = {
    "embedding": {
        "vector_valid_rate": ("min", 0.999),
        "repeatability_rate": ("min", 0.99),
        "retrieval_quality_score": ("min", 0.75),
    },
    "reranking": {
        "ranking_quality_score": ("min", 0.80),
        "ready_recall": ("min", 0.80),
        "false_ready_rate": ("max", 0.10),
    },
    "generation": {
        "response_contract_rate": ("min", 0.99),
        "grounded_quality_score": ("min", 0.80),
        "error_rate": ("max", 0.05),
    },
}


@dataclass(frozen=True)
class CapabilityCalibrationProfile:
    profile_id: str
    provider_capability: str
    identity_fingerprint: str
    model_revision: str
    deployment_id: str
    request_shape_hash: str
    dataset_hash: str
    feature_schema_hash: str
    policy_hash: str
    sample_count: int
    metrics: tuple[tuple[str, float], ...]
    failed_metrics: tuple[str, ...]
    status: str
    evaluated_at: str
    expires_at: str

    def __post_init__(self) -> None:
        _identifier(self.profile_id, "profile_id")
        if self.provider_capability not in MODEL_CAPABILITIES:
            raise ModelRolloutError(
                "mo.calibration_capability_invalid",
                "unsupported calibration capability",
            )
        for field_name in ("model_revision", "deployment_id"):
            _identifier(getattr(self, field_name), field_name)
        for field_name in (
            "identity_fingerprint",
            "request_shape_hash",
            "dataset_hash",
            "feature_schema_hash",
            "policy_hash",
        ):
            _digest(getattr(self, field_name), field_name)
        if self.sample_count < 1:
            raise ModelRolloutError(
                "mo.calibration_sample_count_invalid",
                "sample count must be positive",
            )
        metric_names = [name for name, _ in self.metrics]
        if len(metric_names) != len(set(metric_names)) or any(
            not isinstance(value, (int, float)) or not math.isfinite(value)
            for _, value in self.metrics
        ):
            raise ModelRolloutError(
                "mo.calibration_metrics_invalid",
                "calibration metrics must be unique and finite",
            )
        if self.status not in CALIBRATION_STATUSES:
            raise ModelRolloutError(
                "mo.calibration_status_invalid",
                "unsupported calibration status",
            )
        evaluated = _timestamp(self.evaluated_at, "evaluated_at")
        expires = _timestamp(self.expires_at, "expires_at")
        if expires <= evaluated:
            raise ModelRolloutError(
                "mo.calibration_expiry_invalid",
                "calibration expiry must follow evaluation",
            )
        if self.status in {"CANDIDATE", "ACTIVE"} and self.failed_metrics:
            raise ModelRolloutError(
                "mo.calibration_status_metrics_conflict",
                "admissible calibration cannot contain failed metrics",
            )
        if self.status == "REJECTED" and not self.failed_metrics:
            raise ModelRolloutError(
                "mo.calibration_rejection_reason_missing",
                "rejected calibration requires failed metrics",
            )

    @property
    def profile_hash(self) -> str:
        return _sha256(self.to_wire(include_hash=False))

    def is_fresh(self, at: str) -> bool:
        instant = _timestamp(at, "at")
        return _timestamp(self.evaluated_at, "evaluated_at") <= instant < _timestamp(
            self.expires_at,
            "expires_at",
        )

    def to_wire(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "profile_id": self.profile_id,
            "provider_capability": self.provider_capability,
            "identity_fingerprint": self.identity_fingerprint,
            "model_revision": self.model_revision,
            "deployment_id": self.deployment_id,
            "request_shape_hash": self.request_shape_hash,
            "dataset_hash": self.dataset_hash,
            "feature_schema_hash": self.feature_schema_hash,
            "policy_hash": self.policy_hash,
            "sample_count": self.sample_count,
            "metrics": dict(self.metrics),
            "failed_metrics": list(self.failed_metrics),
            "status": self.status,
            "evaluated_at": self.evaluated_at,
            "expires_at": self.expires_at,
        }
        if include_hash:
            payload["profile_hash"] = self.profile_hash
        return payload


def evaluate_calibration_profile(
    identity: ModelRevisionIdentity,
    *,
    profile_id: str,
    dataset_hash: str,
    feature_schema_hash: str,
    policy_hash: str,
    sample_count: int,
    metrics: Mapping[str, float],
    evaluated_at: str,
    expires_at: str,
    minimum_sample_count: int = 20,
) -> CapabilityCalibrationProfile:
    if minimum_sample_count < 1:
        raise ModelRolloutError(
            "mo.calibration_minimum_sample_invalid",
            "minimum sample count must be positive",
        )
    requirements = _REQUIRED_METRICS[identity.provider_capability]
    failed = []
    if sample_count < minimum_sample_count:
        failed.append("sample_count")
    if set(metrics) != set(requirements):
        failed.append("metric_schema")
    else:
        for name, (operator, threshold) in requirements.items():
            value = metrics[name]
            if not isinstance(value, (int, float)) or not math.isfinite(value) or operator == "min" and value < threshold or operator == "max" and value > threshold:
                failed.append(name)
    normalized_metrics = tuple(
        sorted(
            (str(name), float(value))
            for name, value in metrics.items()
            if isinstance(value, (int, float)) and math.isfinite(value)
        )
    )
    return CapabilityCalibrationProfile(
        profile_id=profile_id,
        provider_capability=identity.provider_capability,
        identity_fingerprint=identity.fingerprint,
        model_revision=identity.model_revision,
        deployment_id=identity.deployment_id,
        request_shape_hash=identity.request_shape_hash,
        dataset_hash=dataset_hash,
        feature_schema_hash=feature_schema_hash,
        policy_hash=policy_hash,
        sample_count=sample_count,
        metrics=normalized_metrics,
        failed_metrics=tuple(failed),
        status="REJECTED" if failed else "CANDIDATE",
        evaluated_at=evaluated_at,
        expires_at=expires_at,
    )


def activate_calibration_profile(
    profile: CapabilityCalibrationProfile,
    identity: ModelRevisionIdentity,
    readiness: Mapping[str, Any],
    *,
    activated_at: str,
) -> CapabilityCalibrationProfile:
    if profile.status != "CANDIDATE":
        raise ModelRolloutError(
            "mo.calibration_candidate_required",
            "only a candidate calibration can be activated",
        )
    if not _profile_matches_identity(profile, identity):
        raise ModelRolloutError(
            "mo.calibration_identity_mismatch",
            "calibration profile does not match the model revision identity",
        )
    if (
        readiness.get("status") != "READY"
        or readiness.get("identity_fingerprint") != identity.fingerprint
    ):
        raise ModelRolloutError(
            "mo.calibration_readiness_required",
            "exact revision readiness is required for activation",
        )
    if not profile.is_fresh(activated_at):
        raise ModelRolloutError(
            "mo.calibration_profile_stale",
            "calibration profile is not fresh",
        )
    return replace(profile, status="ACTIVE")


def retire_calibration_profile(
    profile: CapabilityCalibrationProfile,
) -> CapabilityCalibrationProfile:
    if profile.status == "RETIRED":
        return profile
    return replace(profile, status="RETIRED", failed_metrics=())


def select_active_calibration_profile(
    profiles: Sequence[CapabilityCalibrationProfile],
    identity: ModelRevisionIdentity,
    *,
    evaluated_at: str,
) -> dict[str, Any]:
    matching = [
        profile
        for profile in profiles
        if profile.status == "ACTIVE"
        and _profile_matches_identity(profile, identity)
        and profile.is_fresh(evaluated_at)
    ]
    if len(matching) != 1:
        reason = (
            "active_calibration_profile_conflict"
            if len(matching) > 1
            else "active_calibration_profile_missing"
        )
        return {
            "status": "CALIBRATION_REQUIRED",
            "reason": reason,
            "identity_fingerprint": identity.fingerprint,
            "profile_id": None,
            "profile_hash": None,
        }
    selected = matching[0]
    return {
        "status": "CALIBRATED",
        "reason": None,
        "identity_fingerprint": identity.fingerprint,
        "profile_id": selected.profile_id,
        "profile_hash": selected.profile_hash,
    }


def _profile_matches_identity(
    profile: CapabilityCalibrationProfile,
    identity: ModelRevisionIdentity,
) -> bool:
    return (
        profile.provider_capability == identity.provider_capability
        and profile.identity_fingerprint == identity.fingerprint
        and profile.model_revision == identity.model_revision
        and profile.deployment_id == identity.deployment_id
        and profile.request_shape_hash == identity.request_shape_hash
    )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ModelRolloutError(
            f"mo.{field_name}_invalid",
            f"{field_name} must be a stable identifier",
        )
    return value


def _digest(value: object, field_name: str) -> str:
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


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
