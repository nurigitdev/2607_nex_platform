from __future__ import annotations

from nex_ag.retrieval_threshold_decisions import (
    AG_RETRIEVAL_THRESHOLD_DECISION_PROJECTION_SCHEMA_VERSION,
    RETRIEVAL_THRESHOLD_SAMPLE_READINESS,
    project_retrieval_threshold_decision,
    summarize_retrieval_threshold_decisions,
    threshold_decision_readiness,
)


def sample_summary(**overrides: object) -> dict[str, object]:
    summary: dict[str, object] = {
        "total_samples": 20,
        "by_default_confidence_bucket": {"READY": 20},
        "by_calibration_action": {"default_threshold_accepts_score": 20},
        "threshold_override_count": 0,
        "would_pass_default_threshold": 20,
        "score_margin_to_default_threshold": {"min": 0.31, "max": 0.72},
    }
    summary.update(overrides)
    return summary


def policy_record(**decision_overrides: object) -> dict[str, object]:
    decision: dict[str, object] = {
        "decision_id": "retrieval_quality_v1_threshold_0001",
        "decision_status": "OBSERVE",
        "canonical_low_confidence_threshold": 0.2,
        "candidate_low_confidence_threshold": None,
        "live_smoke_override_threshold": 0.0,
        "minimum_live_samples_before_change": 20,
        "review_owner_service": "nex-ag",
        "evidence_sources": ["Slice 0297 protected_live_rag_score_calibration.v1"],
        "decision_note": "Collect live samples first.",
    }
    decision.update(decision_overrides)
    return {
        "policy_id": "retrieval_quality_v1",
        "version": "0001",
        "status": "ACTIVE",
        "policy_hash": "a" * 64,
        "threshold_decision": decision,
    }


def test_threshold_decision_readiness_reports_all_operator_states() -> None:
    decision = policy_record()["threshold_decision"]

    assert RETRIEVAL_THRESHOLD_SAMPLE_READINESS == (
        "SOURCE_DEGRADED",
        "NO_DECISION_CHECKPOINT",
        "INSUFFICIENT_SAMPLES",
        "NEEDS_OPERATOR_REVIEW",
        "READY_FOR_REVIEW",
    )
    assert AG_RETRIEVAL_THRESHOLD_DECISION_PROJECTION_SCHEMA_VERSION == (
        "ag_retrieval_threshold_decision_projection.v1"
    )
    assert threshold_decision_readiness(
        decision=decision,
        sample_summary=sample_summary(),
        minimum_samples=20,
        source_degraded=True,
    ) == ("SOURCE_DEGRADED", "repair_retrieval_operations_source")
    assert threshold_decision_readiness(
        decision={},
        sample_summary=sample_summary(),
        minimum_samples=20,
        source_degraded=False,
    ) == ("NO_DECISION_CHECKPOINT", "register_threshold_decision")
    assert threshold_decision_readiness(
        decision=decision,
        sample_summary=sample_summary(total_samples=19),
        minimum_samples=20,
        source_degraded=False,
    ) == ("INSUFFICIENT_SAMPLES", "collect_live_score_samples")
    assert threshold_decision_readiness(
        decision=decision,
        sample_summary=sample_summary(threshold_override_count=1),
        minimum_samples=20,
        source_degraded=False,
    ) == ("NEEDS_OPERATOR_REVIEW", "review_threshold_override_samples")
    assert threshold_decision_readiness(
        decision=decision,
        sample_summary=sample_summary(
            by_default_confidence_bucket={"LOW_CONFIDENCE": 1, "READY": 19}
        ),
        minimum_samples=20,
        source_degraded=False,
    ) == ("NEEDS_OPERATOR_REVIEW", "review_low_confidence_samples")
    assert threshold_decision_readiness(
        decision=decision,
        sample_summary=sample_summary(),
        minimum_samples=20,
        source_degraded=False,
    ) == ("READY_FOR_REVIEW", "prepare_threshold_policy_review")


def test_project_threshold_decision_sanitizes_unexpected_count_shapes() -> None:
    projection = project_retrieval_threshold_decision(
        policy_record(minimum_live_samples_before_change=True),
        sample_summary=sample_summary(
            total_samples=True,
            threshold_override_count=-5,
            would_pass_default_threshold="bad",
            by_default_confidence_bucket=["bad"],
            by_calibration_action=None,
        ),
        source_degraded=False,
        service_id="nex-cx",
    )

    assert projection["operation_type"] == "retrieval_threshold_decision"
    assert projection["minimum_live_samples_before_change"] == 0
    assert projection["observed_sample_count"] == 0
    assert projection["observed_threshold_override_count"] == 0
    assert projection["observed_default_pass_count"] == 0
    assert projection["observed_default_confidence_buckets"] == {}
    assert projection["observed_calibration_actions"] == {}
    assert projection["sample_readiness"] == "READY_FOR_REVIEW"


def test_summarize_threshold_decisions_handles_bad_count_values() -> None:
    summary = summarize_retrieval_threshold_decisions(
        [
            {
                "sample_readiness": "READY_FOR_REVIEW",
                "decision_status": "OBSERVE",
                "observed_sample_count": True,
                "observed_threshold_override_count": -1,
            },
            {
                "sample_readiness": "SOURCE_DEGRADED",
                "decision_status": "OBSERVE",
                "observed_sample_count": 7,
                "observed_threshold_override_count": 2,
            },
        ]
    )

    assert summary == {
        "total_decisions": 2,
        "by_sample_readiness": {"READY_FOR_REVIEW": 1, "SOURCE_DEGRADED": 1},
        "by_decision_status": {"OBSERVE": 2},
        "observed_sample_count": 7,
        "threshold_override_count": 2,
        "ready_for_review": 1,
        "needs_operator_review": 0,
        "insufficient_samples": 0,
        "source_degraded": 1,
    }
