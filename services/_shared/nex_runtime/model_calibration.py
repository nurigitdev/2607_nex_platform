from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import hmac
import json
import statistics
from typing import Any


MODEL_CALIBRATION_EVALUATION_SCHEMA_VERSION = "model_calibration_evaluation.v1"
MODEL_CALIBRATION_PROFILE_SCHEMA_VERSION = "model_calibration_profile.v1"
SUPPORTED_CAPABILITIES = frozenset({"embedding", "reranking", "generation"})
SUPPORTED_PROFILE_STATUSES = frozenset({"CANDIDATE", "ACTIVE", "RETIRED"})


@dataclass
class ModelCalibrationError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class BinaryCalibrationConstraints:
    minimum_sample_count: int = 20
    minimum_positive_count: int = 8
    minimum_negative_count: int = 8
    maximum_false_ready_rate: float = 0.10
    minimum_ready_recall: float = 0.80

    def __post_init__(self) -> None:
        if (
            self.minimum_sample_count < 1
            or self.minimum_positive_count < 1
            or self.minimum_negative_count < 1
            or not 0.0 <= self.maximum_false_ready_rate <= 1.0
            or not 0.0 <= self.minimum_ready_recall <= 1.0
        ):
            raise ModelCalibrationError(
                "model_calibration.constraints_invalid",
                "Calibration constraints are invalid.",
            )


def evaluate_binary_score_calibration(
    samples: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    constraints: BinaryCalibrationConstraints = BinaryCalibrationConstraints(),
) -> dict[str, Any]:
    normalized = _normalize_samples(samples)
    positive_count = sum(sample["expected_ready"] for sample in normalized)
    negative_count = len(normalized) - positive_count
    base = {
        "evaluation_schema_version": MODEL_CALIBRATION_EVALUATION_SCHEMA_VERSION,
        "dataset_id": _required_string(dataset_id, "dataset_id"),
        "dataset_sha256": _sha256_json(normalized),
        "sample_count": len(normalized),
        "positive_count": positive_count,
        "negative_count": negative_count,
        "score_distribution": _score_distribution(normalized),
        "constraints": _constraints_payload(constraints),
    }
    if (
        len(normalized) < constraints.minimum_sample_count
        or positive_count < constraints.minimum_positive_count
        or negative_count < constraints.minimum_negative_count
    ):
        return {
            **base,
            "status": "INSUFFICIENT_SAMPLES",
            "selected_threshold": None,
            "selected_metrics": None,
            "candidate_count": 0,
            "best_effort_metrics": None,
        }

    candidates = [
        _threshold_metrics(normalized, threshold)
        for threshold in _candidate_thresholds(normalized)
    ]
    acceptable = [
        candidate
        for candidate in candidates
        if candidate["false_ready_rate"] <= constraints.maximum_false_ready_rate
        and candidate["ready_recall"] >= constraints.minimum_ready_recall
    ]
    best_effort = max(
        candidates,
        key=lambda item: (
            item["balanced_accuracy"],
            item["ready_precision"],
            item["ready_recall"],
            -item["false_ready_rate"],
            -item["threshold"],
        ),
    )
    if not acceptable:
        return {
            **base,
            "status": "NO_ACCEPTABLE_THRESHOLD",
            "selected_threshold": None,
            "selected_metrics": None,
            "candidate_count": len(candidates),
            "best_effort_metrics": best_effort,
        }
    selected = max(
        acceptable,
        key=lambda item: (
            item["balanced_accuracy"],
            item["ready_precision"],
            item["ready_recall"],
            -item["false_ready_rate"],
            -item["threshold"],
        ),
    )
    return {
        **base,
        "status": "PASSED",
        "selected_threshold": selected["threshold"],
        "selected_metrics": selected,
        "candidate_count": len(candidates),
        "best_effort_metrics": best_effort,
    }


def build_model_calibration_profile(
    *,
    profile_id: str,
    version: str,
    status: str,
    capability: str,
    model_revision: str,
    request_shape: str,
    score_semantics: str,
    policy_id: str,
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_status = _required_string(status, "status").upper()
    if normalized_status not in SUPPORTED_PROFILE_STATUSES:
        raise _invalid("status")
    normalized_capability = _required_string(capability, "capability")
    if normalized_capability not in SUPPORTED_CAPABILITIES:
        raise _invalid("capability")
    if evaluation.get("evaluation_schema_version") != (
        MODEL_CALIBRATION_EVALUATION_SCHEMA_VERSION
    ):
        raise _invalid("evaluation_schema_version")
    if evaluation.get("status") != "PASSED":
        raise ModelCalibrationError(
            "model_calibration.evaluation_not_passed",
            "A calibration profile requires a passed evaluation.",
        )
    threshold = _bounded_score(
        evaluation.get("selected_threshold"),
        "selected_threshold",
    )
    binding = {
        "capability": normalized_capability,
        "model_revision": _required_string(model_revision, "model_revision"),
        "request_shape": _required_string(request_shape, "request_shape"),
        "score_semantics": _required_string(score_semantics, "score_semantics"),
        "policy_id": _required_string(policy_id, "policy_id"),
    }
    profile = {
        "profile_schema_version": MODEL_CALIBRATION_PROFILE_SCHEMA_VERSION,
        "profile_id": _required_string(profile_id, "profile_id"),
        "version": _required_string(version, "version"),
        "status": normalized_status,
        "binding": binding,
        "threshold": threshold,
        "evaluation": json.loads(json.dumps(evaluation, sort_keys=True)),
    }
    profile["profile_hash"] = _sha256_json(profile)
    return profile


def select_model_calibration_profile(
    profiles: Sequence[Mapping[str, Any]],
    *,
    capability: str,
    model_revision: str,
    request_shape: str,
    score_semantics: str,
    policy_id: str,
) -> dict[str, Any] | None:
    expected = {
        "capability": capability,
        "model_revision": model_revision,
        "request_shape": request_shape,
        "score_semantics": score_semantics,
        "policy_id": policy_id,
    }
    matches = [
        profile
        for profile in profiles
        if profile.get("profile_schema_version")
        == MODEL_CALIBRATION_PROFILE_SCHEMA_VERSION
        and profile.get("status") == "ACTIVE"
        and dict(_mapping(profile.get("binding"))) == expected
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise ModelCalibrationError(
            "model_calibration.active_profile_ambiguous",
            "Exactly one active calibration profile may match a model binding.",
        )
    _validate_profile_integrity(matches[0])
    return json.loads(json.dumps(matches[0], sort_keys=True))


def classify_calibrated_score(
    score: object,
    *,
    profile: Mapping[str, Any] | None,
) -> dict[str, Any]:
    numeric_score = _bounded_score(score, "score")
    if profile is None:
        return {
            "status": "CALIBRATION_REQUIRED",
            "reason": "active_model_calibration_profile_missing",
            "score": numeric_score,
            "threshold": None,
            "profile_id": None,
            "profile_hash": None,
        }
    if profile.get("status") != "ACTIVE":
        return {
            "status": "CALIBRATION_REQUIRED",
            "reason": "active_model_calibration_profile_missing",
            "score": numeric_score,
            "threshold": None,
            "profile_id": None,
            "profile_hash": None,
        }
    threshold = _validate_profile_integrity(profile)
    ready = numeric_score >= threshold
    return {
        "status": "READY" if ready else "LOW_CONFIDENCE",
        "reason": None if ready else "score_below_calibrated_threshold",
        "score": numeric_score,
        "threshold": threshold,
        "profile_id": profile.get("profile_id"),
        "profile_hash": profile.get("profile_hash"),
    }


def _normalize_samples(
    samples: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sample in samples:
        sample_id = _required_string(sample.get("sample_id"), "sample_id")
        if sample_id in seen:
            raise ModelCalibrationError(
                "model_calibration.sample_duplicate",
                "Calibration sample IDs must be unique.",
            )
        seen.add(sample_id)
        expected_ready = sample.get("expected_ready")
        if not isinstance(expected_ready, bool):
            raise _invalid("expected_ready")
        normalized.append(
            {
                "sample_id": sample_id,
                "expected_ready": expected_ready,
                "score": _bounded_score(sample.get("score"), "score"),
            }
        )
    return sorted(normalized, key=lambda item: item["sample_id"])


def _validate_profile_integrity(profile: Mapping[str, Any]) -> float:
    if profile.get("profile_schema_version") != MODEL_CALIBRATION_PROFILE_SCHEMA_VERSION:
        raise _invalid("profile_schema_version")
    threshold = _bounded_score(profile.get("threshold"), "threshold")
    evaluation = _mapping(profile.get("evaluation"))
    if evaluation.get("status") != "PASSED":
        raise _invalid("evaluation.status")
    selected_threshold = _bounded_score(
        evaluation.get("selected_threshold"),
        "evaluation.selected_threshold",
    )
    if threshold != selected_threshold:
        raise ModelCalibrationError(
            "model_calibration.threshold_mismatch",
            "Profile threshold does not match the passed evaluation.",
        )
    profile_hash = _required_string(profile.get("profile_hash"), "profile_hash")
    unsigned = dict(profile)
    unsigned.pop("profile_hash", None)
    expected_hash = _sha256_json(unsigned)
    if not hmac.compare_digest(profile_hash, expected_hash):
        raise ModelCalibrationError(
            "model_calibration.profile_integrity_invalid",
            "Calibration profile integrity validation failed.",
        )
    return threshold


def _candidate_thresholds(samples: Sequence[Mapping[str, Any]]) -> list[float]:
    scores = sorted({float(sample["score"]) for sample in samples})
    thresholds = {0.0, 1.0}
    thresholds.update(scores)
    thresholds.update(
        round((left + right) / 2.0, 8)
        for left, right in zip(scores, scores[1:], strict=False)
    )
    return sorted(thresholds)


def _threshold_metrics(
    samples: Sequence[Mapping[str, Any]],
    threshold: float,
) -> dict[str, Any]:
    true_ready = false_low = false_ready = true_low = 0
    for sample in samples:
        predicted_ready = float(sample["score"]) >= threshold
        expected_ready = bool(sample["expected_ready"])
        if predicted_ready and expected_ready:
            true_ready += 1
        elif predicted_ready:
            false_ready += 1
        elif expected_ready:
            false_low += 1
        else:
            true_low += 1
    positive_count = true_ready + false_low
    negative_count = true_low + false_ready
    ready_precision = _ratio(true_ready, true_ready + false_ready)
    ready_recall = _ratio(true_ready, positive_count)
    low_specificity = _ratio(true_low, negative_count)
    return {
        "threshold": threshold,
        "true_ready": true_ready,
        "false_low_confidence": false_low,
        "false_ready": false_ready,
        "true_low_confidence": true_low,
        "ready_precision": ready_precision,
        "ready_recall": ready_recall,
        "false_ready_rate": _ratio(false_ready, negative_count),
        "false_low_rate": _ratio(false_low, positive_count),
        "balanced_accuracy": round((ready_recall + low_specificity) / 2.0, 8),
    }


def _constraints_payload(constraints: BinaryCalibrationConstraints) -> dict[str, Any]:
    return {
        "minimum_sample_count": constraints.minimum_sample_count,
        "minimum_positive_count": constraints.minimum_positive_count,
        "minimum_negative_count": constraints.minimum_negative_count,
        "maximum_false_ready_rate": constraints.maximum_false_ready_rate,
        "minimum_ready_recall": constraints.minimum_ready_recall,
    }


def _score_distribution(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    positive = [float(item["score"]) for item in samples if item["expected_ready"]]
    negative = [float(item["score"]) for item in samples if not item["expected_ready"]]
    return {
        "positive": _distribution_summary(positive),
        "negative": _distribution_summary(negative),
        "overlap": (
            round(max(negative) - min(positive), 8)
            if positive and negative
            else None
        ),
    }


def _distribution_summary(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "min": min(values),
        "max": max(values),
        "mean": round(statistics.fmean(values), 8),
        "median": round(statistics.median(values), 8),
    }


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 8) if denominator else 0.0


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(field_name)
    return value.strip()


def _bounded_score(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid(field_name)
    numeric = float(value)
    if not 0.0 <= numeric <= 1.0:
        raise _invalid(field_name)
    return numeric


def _invalid(field_name: str) -> ModelCalibrationError:
    return ModelCalibrationError(
        "model_calibration.field_invalid",
        f"{field_name} is invalid.",
    )
