from __future__ import annotations

from dataclasses import replace

import pytest
from nex_mo.model_rollout import ModelRevisionIdentity, ModelRolloutError
from nex_mo.model_rollout_calibration import (
    CapabilityCalibrationProfile,
    activate_calibration_profile,
    evaluate_calibration_profile,
    retire_calibration_profile,
    select_active_calibration_profile,
)

DIGESTS = ["sha256:" + char * 64 for char in "abcdef"]


def identity(capability: str = "embedding", revision: str = "2") -> ModelRevisionIdentity:
    return ModelRevisionIdentity(
        provider_capability=capability,
        alias=f"{capability}-default",
        catalog_id=f"catalog:{capability}:r{revision}",
        model_revision=f"revision:{capability}:{revision}",
        deployment_id=f"deployment:{capability}:{revision}",
        artifact_digest=DIGESTS[0],
        runtime_engine="openai-compatible",
        precision="bfloat16",
        request_shape_hash=DIGESTS[1],
    )


def metrics(capability: str) -> dict[str, float]:
    return {
        "embedding": {
            "vector_valid_rate": 1.0,
            "repeatability_rate": 0.995,
            "retrieval_quality_score": 0.85,
        },
        "reranking": {
            "ranking_quality_score": 0.9,
            "ready_recall": 0.9,
            "false_ready_rate": 0.05,
        },
        "generation": {
            "response_contract_rate": 1.0,
            "grounded_quality_score": 0.9,
            "error_rate": 0.01,
        },
    }[capability]


def profile(capability: str = "embedding") -> CapabilityCalibrationProfile:
    model = identity(capability)
    return evaluate_calibration_profile(
        model,
        profile_id=f"calibration:{capability}:2",
        dataset_hash=DIGESTS[2],
        feature_schema_hash=DIGESTS[3],
        policy_hash=DIGESTS[4],
        sample_count=20,
        metrics=metrics(capability),
        evaluated_at="2026-10-08T00:00:00Z",
        expires_at="2026-10-09T00:00:00Z",
    )


def readiness(model: ModelRevisionIdentity) -> dict[str, str]:
    return {"status": "READY", "identity_fingerprint": model.fingerprint}


@pytest.mark.parametrize("capability", ["embedding", "reranking", "generation"])
def test_capability_specific_profile_can_activate(capability: str) -> None:
    model = identity(capability)
    candidate = profile(capability)
    active = activate_calibration_profile(
        candidate,
        model,
        readiness(model),
        activated_at="2026-10-08T01:00:00Z",
    )
    selected = select_active_calibration_profile(
        [active],
        model,
        evaluated_at="2026-10-08T02:00:00Z",
    )

    assert candidate.status == "CANDIDATE"
    assert active.status == "ACTIVE"
    assert selected["status"] == "CALIBRATED"
    assert selected["profile_id"] == candidate.profile_id
    assert selected["profile_hash"] == active.profile_hash
    assert active.profile_hash != candidate.profile_hash
    assert candidate.to_wire()["metrics"] == metrics(capability)


@pytest.mark.parametrize(
    ("capability", "changed_metric"),
    [
        ("embedding", {"retrieval_quality_score": 0.7}),
        ("reranking", {"false_ready_rate": 0.2}),
        ("generation", {"error_rate": 0.2}),
    ],
)
def test_failed_quality_metric_rejects_profile(
    capability: str,
    changed_metric: dict[str, float],
) -> None:
    values = {**metrics(capability), **changed_metric}
    rejected = evaluate_calibration_profile(
        identity(capability),
        profile_id=f"calibration:{capability}:bad",
        dataset_hash=DIGESTS[2],
        feature_schema_hash=DIGESTS[3],
        policy_hash=DIGESTS[4],
        sample_count=20,
        metrics=values,
        evaluated_at="2026-10-08T00:00:00Z",
        expires_at="2026-10-09T00:00:00Z",
    )
    assert rejected.status == "REJECTED"
    assert tuple(changed_metric) == rejected.failed_metrics


def test_sample_and_metric_schema_fail_closed() -> None:
    rejected = evaluate_calibration_profile(
        identity(),
        profile_id="calibration:embedding:small",
        dataset_hash=DIGESTS[2],
        feature_schema_hash=DIGESTS[3],
        policy_hash=DIGESTS[4],
        sample_count=5,
        metrics={"vector_valid_rate": float("nan")},
        evaluated_at="2026-10-08T00:00:00Z",
        expires_at="2026-10-09T00:00:00Z",
    )
    assert rejected.status == "REJECTED"
    assert rejected.failed_metrics == ("sample_count", "metric_schema")
    assert rejected.metrics == ()


def test_revision_change_and_retirement_require_recalibration() -> None:
    model = identity()
    active = activate_calibration_profile(
        profile(), model, readiness(model), activated_at="2026-10-08T01:00:00Z"
    )
    changed = identity(revision="3")
    assert select_active_calibration_profile(
        [active], changed, evaluated_at="2026-10-08T02:00:00Z"
    )["status"] == "CALIBRATION_REQUIRED"

    retired = retire_calibration_profile(active)
    assert retired.status == "RETIRED"
    assert retire_calibration_profile(retired) is retired
    assert select_active_calibration_profile(
        [retired], model, evaluated_at="2026-10-08T02:00:00Z"
    )["reason"] == "active_calibration_profile_missing"


def test_profile_conflict_and_staleness_fail_closed() -> None:
    model = identity()
    active = activate_calibration_profile(
        profile(), model, readiness(model), activated_at="2026-10-08T01:00:00Z"
    )
    duplicate = replace(active, profile_id="calibration:embedding:duplicate")
    assert select_active_calibration_profile(
        [active, duplicate], model, evaluated_at="2026-10-08T02:00:00Z"
    )["reason"] == "active_calibration_profile_conflict"
    assert select_active_calibration_profile(
        [active], model, evaluated_at="2026-10-10T00:00:00Z"
    )["status"] == "CALIBRATION_REQUIRED"


@pytest.mark.parametrize(
    ("candidate", "model", "ready", "time", "code"),
    [
        (replace(profile(), status="REJECTED", failed_metrics=("x",)), identity(), readiness(identity()), "2026-10-08T01:00:00Z", "mo.calibration_candidate_required"),
        (profile(), identity(revision="3"), readiness(identity(revision="3")), "2026-10-08T01:00:00Z", "mo.calibration_identity_mismatch"),
        (profile(), identity(), {"status": "BLOCKED", "identity_fingerprint": identity().fingerprint}, "2026-10-08T01:00:00Z", "mo.calibration_readiness_required"),
        (profile(), identity(), readiness(identity()), "2026-10-10T00:00:00Z", "mo.calibration_profile_stale"),
    ],
)
def test_activation_guards(candidate, model, ready, time: str, code: str) -> None:
    with pytest.raises(ModelRolloutError) as exc:
        activate_calibration_profile(candidate, model, ready, activated_at=time)
    assert exc.value.error_code == code


def test_profile_validation_errors() -> None:
    valid = profile()
    cases = (
        ({"profile_id": "bad id"}, "mo.profile_id_invalid"),
        ({"provider_capability": "vision"}, "mo.calibration_capability_invalid"),
        ({"dataset_hash": "bad"}, "mo.dataset_hash_invalid"),
        ({"sample_count": 0}, "mo.calibration_sample_count_invalid"),
        ({"metrics": (("x", float("inf")),)}, "mo.calibration_metrics_invalid"),
        ({"status": "UNKNOWN"}, "mo.calibration_status_invalid"),
        ({"expires_at": valid.evaluated_at}, "mo.calibration_expiry_invalid"),
        ({"failed_metrics": ("x",)}, "mo.calibration_status_metrics_conflict"),
        ({"status": "REJECTED"}, "mo.calibration_rejection_reason_missing"),
    )
    for changes, code in cases:
        with pytest.raises(ModelRolloutError) as exc:
            replace(valid, **changes)
        assert exc.value.error_code == code


def test_invalid_minimum_and_timestamp_are_rejected() -> None:
    with pytest.raises(ModelRolloutError) as exc:
        evaluate_calibration_profile(
            identity(),
            profile_id="calibration:embedding:bad-minimum",
            dataset_hash=DIGESTS[2],
            feature_schema_hash=DIGESTS[3],
            policy_hash=DIGESTS[4],
            sample_count=20,
            metrics=metrics("embedding"),
            evaluated_at="2026-10-08T00:00:00Z",
            expires_at="2026-10-09T00:00:00Z",
            minimum_sample_count=0,
        )
    assert exc.value.error_code == "mo.calibration_minimum_sample_invalid"

    with pytest.raises(ModelRolloutError) as exc:
        replace(profile(), evaluated_at="bad")
    assert exc.value.error_code == "mo.evaluated_at_invalid"
    with pytest.raises(ModelRolloutError) as exc:
        profile().is_fresh("2026-10-08T00:00:00")
    assert exc.value.error_code == "mo.at_invalid"
