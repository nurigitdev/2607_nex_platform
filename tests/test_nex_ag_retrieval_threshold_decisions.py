from __future__ import annotations

from nex_ag.retrieval_threshold_decisions import (
    AG_RETRIEVAL_THRESHOLD_DECISION_PROJECTION_SCHEMA_VERSION,
    AG_RETRIEVAL_THRESHOLD_OPERATOR_REVIEW_SCHEMA_VERSION,
    RETRIEVAL_THRESHOLD_SAMPLE_READINESS,
    build_retrieval_threshold_operator_review,
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


def test_threshold_operator_review_runbooks_cover_operator_states() -> None:
    cases = [
        (
            "SOURCE_DEGRADED",
            "repair_retrieval_operations_source",
            0,
            20,
            "BLOCKED_SOURCE",
            "retrieval_threshold.repair_operations_source.v1",
        ),
        (
            "NO_DECISION_CHECKPOINT",
            "register_threshold_decision",
            0,
            20,
            "MISSING_CHECKPOINT",
            "retrieval_threshold.register_decision_checkpoint.v1",
        ),
        (
            "INSUFFICIENT_SAMPLES",
            "collect_live_score_samples",
            19,
            20,
            "COLLECTING_SAMPLES",
            "retrieval_threshold.collect_live_score_samples.v1",
        ),
        (
            "NEEDS_OPERATOR_REVIEW",
            "review_threshold_override_samples",
            20,
            20,
            "REVIEW_REQUIRED",
            "retrieval_threshold.review_override_samples.v1",
        ),
        (
            "NEEDS_OPERATOR_REVIEW",
            "review_low_confidence_samples",
            20,
            20,
            "REVIEW_REQUIRED",
            "retrieval_threshold.review_low_confidence_samples.v1",
        ),
        (
            "READY_FOR_REVIEW",
            "prepare_threshold_policy_review",
            21,
            20,
            "READY_FOR_POLICY_REVIEW",
            "retrieval_threshold.prepare_policy_review.v1",
        ),
    ]

    reviews = [
        build_retrieval_threshold_operator_review(
            service_id="nex-cx",
            policy_id="retrieval_quality_v1",
            sample_readiness=readiness,
            recommended_operator_action=action,
            observed_sample_count=observed,
            minimum_live_samples_before_change=minimum,
        )
        for readiness, action, observed, minimum, _status, _runbook_id in cases
    ]

    assert {
        (review["review_status"], review["runbook_id"])
        for review in reviews
    } == {(status, runbook_id) for *_prefix, status, runbook_id in cases}
    assert all(
        review["review_schema_version"]
        == AG_RETRIEVAL_THRESHOLD_OPERATOR_REVIEW_SCHEMA_VERSION
        for review in reviews
    )
    assert reviews[2]["remaining_sample_count"] == 1
    assert reviews[-1]["remaining_sample_count"] == 0
    assert reviews[-1]["blocking_reason"] is None
    assert reviews[0]["threshold_decision_path"] == (
        "/admin/v1/operations/retrieval-threshold-decisions?"
        "service_id=nex-cx&retrieval_policy_id=retrieval_quality_v1"
    )
    assert reviews[0]["calibration_samples_path"] == (
        "/admin/v1/operations/retrieval-score-calibration?"
        "service_id=nex-cx&retrieval_policy_id=retrieval_quality_v1"
    )
    assert reviews[0]["policy_detail_path"] == (
        "/admin/v1/policies/retrieval/retrieval_quality_v1"
    )


def test_threshold_operator_review_normalizes_unknown_action() -> None:
    review = build_retrieval_threshold_operator_review(
        service_id="nex-cx",
        policy_id="policy/with space",
        sample_readiness="UNKNOWN",
        recommended_operator_action="unexpected",
        observed_sample_count=100,
        minimum_live_samples_before_change=20,
    )

    assert review["review_status"] == "UNKNOWN_ACTION"
    assert review["operator_action"] == "unknown_operator_action"
    assert review["runbook_id"] == "retrieval_threshold.unknown_operator_action.v1"
    assert review["remaining_sample_count"] == 0
    assert review["policy_detail_path"] == (
        "/admin/v1/policies/retrieval/policy%2Fwith%20space"
    )
    assert "policy%2Fwith+space" in review["threshold_decision_path"]


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
    assert projection["operator_review"]["review_status"] == (
        "READY_FOR_POLICY_REVIEW"
    )


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
