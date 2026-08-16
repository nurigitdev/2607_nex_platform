from __future__ import annotations

from nex_ag.retrieval_score_calibration import (
    _threshold_override_direction,
    build_retrieval_score_calibration_projection,
)


def retrieval_calibration_record(**overrides):
    record = {
        "status": "LOW_CONFIDENCE",
        "retrieval_policy_id": "retrieval_quality_v1",
        "score_summary": {
            "best_score": 0.12,
            "confidence_bucket": "LOW_CONFIDENCE",
            "low_confidence_threshold": 0.2,
        },
        "evidence_count": 1,
    }
    record.update(overrides)
    return record


def test_retrieval_score_calibration_reports_low_confidence_review_action() -> None:
    calibration = build_retrieval_score_calibration_projection(
        retrieval_calibration_record(),
        default_low_confidence_threshold=0.2,
    )

    assert calibration["default_confidence_bucket"] == "LOW_CONFIDENCE"
    assert calibration["threshold_override_used"] is False
    assert calibration["threshold_override_direction"] == "none"
    assert calibration["calibration_action"] == "review_low_confidence_boundary"


def test_retrieval_score_calibration_handles_bool_evidence_count_as_missing() -> None:
    calibration = build_retrieval_score_calibration_projection(
        retrieval_calibration_record(
            evidence_count=True,
            score_summary={
                "best_score": 0.9,
                "confidence_bucket": "not-supported",
                "low_confidence_threshold": 0.2,
            },
        ),
        default_low_confidence_threshold=0.2,
    )

    assert calibration["evidence_count"] == 0
    assert calibration["observed_confidence_bucket"] == "NO_ANSWER"
    assert calibration["calibration_action"] == "inspect_no_answer_retrieval"


def test_threshold_override_direction_reports_unknown_when_threshold_missing() -> None:
    assert _threshold_override_direction(None, 0.2) == "unknown"
