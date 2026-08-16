from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_runtime.retrieval_policies import active_retrieval_policy_record


AG_RETRIEVAL_SCORE_CALIBRATION_SCHEMA_VERSION = (
    "ag_retrieval_score_calibration.v1"
)
RETRIEVAL_SCORE_CALIBRATION_BUCKETS = (
    "READY",
    "LOW_CONFIDENCE",
    "NO_ANSWER",
    "UNKNOWN",
)
RETRIEVAL_SCORE_CALIBRATION_ACTIONS = (
    "default_threshold_accepts_score",
    "review_low_confidence_boundary",
    "inspect_no_answer_retrieval",
    "review_live_threshold_before_canonical_policy",
    "compare_observed_and_default_confidence",
    "calibration_data_incomplete",
)
DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.2


def summarize_retrieval_score_calibration_samples(
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    by_policy: dict[str, int] = {}
    by_observed_status: dict[str, int] = {}
    by_default_bucket: dict[str, int] = {}
    by_action: dict[str, int] = {}
    margins = [
        margin
        for sample in samples
        if (
            margin := _number_or_none(
                _mapping_value(sample.get("score_calibration")).get(
                    "score_margin_to_default_threshold"
                )
            )
        )
        is not None
    ]
    for sample in samples:
        calibration = _mapping_value(sample.get("score_calibration"))
        policy_id = str(sample["retrieval_policy_id"])
        observed_status = str(sample["status"])
        default_bucket = str(calibration.get("default_confidence_bucket", "UNKNOWN"))
        action = str(calibration.get("calibration_action", "UNKNOWN"))
        by_policy[policy_id] = by_policy.get(policy_id, 0) + 1
        by_observed_status[observed_status] = (
            by_observed_status.get(observed_status, 0) + 1
        )
        by_default_bucket[default_bucket] = by_default_bucket.get(default_bucket, 0) + 1
        by_action[action] = by_action.get(action, 0) + 1
    return {
        "total_samples": len(samples),
        "by_policy": by_policy,
        "by_observed_status": by_observed_status,
        "by_default_confidence_bucket": by_default_bucket,
        "by_calibration_action": by_action,
        "threshold_override_count": sum(
            1
            for sample in samples
            if _mapping_value(sample.get("score_calibration")).get(
                "threshold_override_used"
            )
            is True
        ),
        "would_pass_default_threshold": sum(
            1
            for sample in samples
            if _mapping_value(sample.get("score_calibration")).get(
                "would_pass_default_threshold"
            )
            is True
        ),
        "score_margin_to_default_threshold": (
            {"min": min(margins), "max": max(margins)} if margins else None
        ),
    }


def build_retrieval_score_calibration_projection(
    record: Mapping[str, Any],
    *,
    default_low_confidence_threshold: float | None = None,
) -> dict[str, Any]:
    score_summary = _mapping_value(record.get("score_summary"))
    evidence_count = _integer_or_none(record.get("evidence_count")) or 0
    best_score = _number_or_none(score_summary.get("best_score"))
    observed_threshold = _number_or_none(
        score_summary.get("low_confidence_threshold")
    )
    default_threshold = (
        default_low_confidence_threshold
        if default_low_confidence_threshold is not None
        else _active_low_confidence_threshold()
    )
    if observed_threshold is None:
        observed_threshold = default_threshold
    observed_bucket = _safe_confidence_bucket(
        score_summary.get("confidence_bucket"),
        fallback=_confidence_bucket(
            evidence_count=evidence_count,
            best_score=best_score,
            threshold=observed_threshold,
        ),
    )
    default_bucket = _confidence_bucket(
        evidence_count=evidence_count,
        best_score=best_score,
        threshold=default_threshold,
    )
    override_used = not _float_values_match(observed_threshold, default_threshold)
    override_direction = _threshold_override_direction(
        observed_threshold,
        default_threshold,
    )
    return {
        "calibration_schema_version": AG_RETRIEVAL_SCORE_CALIBRATION_SCHEMA_VERSION,
        "quality_policy_id": str(
            score_summary.get("quality_policy_id")
            or record.get("retrieval_policy_id")
            or "UNKNOWN"
        ),
        "observed_status": str(record.get("status") or "UNKNOWN"),
        "observed_confidence_bucket": observed_bucket,
        "default_confidence_bucket": default_bucket,
        "best_score": best_score,
        "evidence_count": evidence_count,
        "observed_low_confidence_threshold": observed_threshold,
        "default_low_confidence_threshold": default_threshold,
        "threshold_override_used": override_used,
        "threshold_override_direction": override_direction,
        "would_pass_default_threshold": (
            True if default_bucket == "READY" else False
        ),
        "score_margin_to_observed_threshold": _score_margin(
            best_score,
            observed_threshold,
        ),
        "score_margin_to_default_threshold": _score_margin(
            best_score,
            default_threshold,
        ),
        "calibration_action": _calibration_action(
            observed_bucket=observed_bucket,
            default_bucket=default_bucket,
            override_used=override_used,
            override_direction=override_direction,
        ),
    }


def _active_low_confidence_threshold() -> float:
    confidence = _mapping_value(active_retrieval_policy_record().get("confidence"))
    threshold = _number_or_none(confidence.get("low_confidence_threshold"))
    return (
        threshold
        if threshold is not None
        else DEFAULT_LOW_CONFIDENCE_THRESHOLD
    )


def _confidence_bucket(
    *,
    evidence_count: int,
    best_score: float | None,
    threshold: float | None,
) -> str:
    if evidence_count <= 0:
        return "NO_ANSWER"
    if best_score is None or threshold is None:
        return "UNKNOWN"
    if best_score < threshold:
        return "LOW_CONFIDENCE"
    return "READY"


def _safe_confidence_bucket(value: Any, *, fallback: str) -> str:
    if isinstance(value, str) and value in RETRIEVAL_SCORE_CALIBRATION_BUCKETS:
        return value
    return fallback


def _threshold_override_direction(
    observed_threshold: float | None,
    default_threshold: float | None,
) -> str:
    if observed_threshold is None or default_threshold is None:
        return "unknown"
    if _float_values_match(observed_threshold, default_threshold):
        return "none"
    if observed_threshold < default_threshold:
        return "lowered"
    return "raised"


def _float_values_match(left: float, right: float) -> bool:
    return abs(left - right) < 0.000001


def _score_margin(
    best_score: float | None,
    threshold: float | None,
) -> float | None:
    if best_score is None or threshold is None:
        return None
    return round(best_score - threshold, 6)


def _calibration_action(
    *,
    observed_bucket: str,
    default_bucket: str,
    override_used: bool,
    override_direction: str,
) -> str:
    if default_bucket == "NO_ANSWER":
        return "inspect_no_answer_retrieval"
    if override_used and override_direction == "lowered" and default_bucket != "READY":
        return "review_live_threshold_before_canonical_policy"
    if observed_bucket != default_bucket:
        return "compare_observed_and_default_confidence"
    if default_bucket == "READY":
        return "default_threshold_accepts_score"
    if default_bucket == "LOW_CONFIDENCE":
        return "review_low_confidence_boundary"
    return "calibration_data_incomplete"


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _integer_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
