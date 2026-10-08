from __future__ import annotations

from dataclasses import replace

import pytest
from nex_mo.model_capacity_scheduler import CapacityReservation
from nex_mo.model_rollout import ModelRevisionIdentity, ModelRolloutError
from nex_mo.model_rollout_state import (
    CanaryMetrics,
    CanaryPolicy,
    begin_validation,
    evaluate_canary,
    mark_rollout_ready,
    register_rollout,
    start_canary,
)

DIGESTS = ["sha256:" + char * 64 for char in "abcdef"]


def identity(revision: str = "2") -> ModelRevisionIdentity:
    return ModelRevisionIdentity(
        provider_capability="generation",
        alias="generation-default",
        catalog_id=f"catalog:generation:r{revision}",
        model_revision=f"revision:generation:{revision}",
        deployment_id=f"deployment:generation:{revision}",
        artifact_digest=DIGESTS[0],
        runtime_engine="vllm",
        precision="bfloat16",
        request_shape_hash=DIGESTS[1],
    )


def registered():
    return register_rollout(
        identity(),
        rollout_id="rollout:generation:2",
        last_known_good_binding_id="binding:generation:1",
        last_known_good_identity_fingerprint=identity("1").fingerprint,
        created_at="2026-10-08T00:00:00Z",
    )


def reservation() -> CapacityReservation:
    return CapacityReservation(
        reservation_id="reservation:generation:2",
        rollout_id="rollout:generation:2",
        identity_fingerprint=identity().fingerprint,
        node_id="node:one",
        gpu_count=1,
        memory_mib=20_000,
        concurrency=2,
        exclusive=False,
    )


def policy() -> CanaryPolicy:
    return CanaryPolicy(
        traffic_percent=10,
        observation_seconds=300,
        minimum_sample_count=100,
        maximum_error_rate=0.02,
        minimum_quality_score=0.85,
        maximum_p95_latency_ms=2_000,
    )


def canary_record():
    validating = begin_validation(registered(), changed_at="2026-10-08T00:01:00Z")
    ready = mark_rollout_ready(
        validating,
        {
            "status": "READY",
            "identity_fingerprint": identity().fingerprint,
            "evidence_digest": DIGESTS[2],
        },
        {
            "status": "CALIBRATED",
            "identity_fingerprint": identity().fingerprint,
            "profile_id": "calibration:generation:2",
            "profile_hash": DIGESTS[3],
        },
        reservation(),
        changed_at="2026-10-08T00:02:00Z",
    )
    return start_canary(ready, policy(), changed_at="2026-10-08T00:03:00Z")


def metrics(**changes) -> CanaryMetrics:
    values = {
        "identity_fingerprint": identity().fingerprint,
        "sample_count": 120,
        "error_rate": 0.01,
        "quality_score": 0.9,
        "p95_latency_ms": 1_500,
        "observed_seconds": 360,
        "measured_at": "2026-10-08T00:09:00Z",
    }
    values.update(changes)
    return CanaryMetrics(**values)


def test_happy_path_reaches_passed_canary_without_activation() -> None:
    record = registered()
    assert record.state == "REGISTERED"
    validating = begin_validation(record, changed_at="2026-10-08T00:01:00Z")
    ready = mark_rollout_ready(
        validating,
        {
            "status": "READY",
            "identity_fingerprint": identity().fingerprint,
            "evidence_digest": DIGESTS[2],
        },
        {
            "status": "CALIBRATED",
            "identity_fingerprint": identity().fingerprint,
            "profile_id": "calibration:generation:2",
            "profile_hash": DIGESTS[3],
        },
        reservation(),
        changed_at="2026-10-08T00:02:00Z",
    )
    canary = start_canary(ready, policy(), changed_at="2026-10-08T00:03:00Z")
    updated, decision = evaluate_canary(
        canary,
        policy(),
        metrics(),
        changed_at="2026-10-08T00:09:00Z",
    )

    assert [record.state, validating.state, ready.state, canary.state] == [
        "REGISTERED",
        "VALIDATING",
        "READY",
        "CANARY",
    ]
    assert updated.state == "CANARY"
    assert updated.canary_status == "PASSED"
    assert decision["status"] == "PASS"
    assert decision["promotable"] is True
    assert all(decision["checks"].values())
    assert updated.to_wire()["identity_fingerprint"] == identity().fingerprint


@pytest.mark.parametrize(
    ("changes", "failed_check"),
    [
        ({"identity_fingerprint": DIGESTS[5]}, "identity_matches"),
        ({"sample_count": 99}, "sample_floor_met"),
        ({"observed_seconds": 299}, "observation_window_met"),
        ({"error_rate": 0.03}, "error_budget_met"),
        ({"quality_score": 0.84}, "quality_budget_met"),
        ({"p95_latency_ms": 2_001}, "latency_budget_met"),
    ],
)
def test_canary_budget_failure_blocks(changes, failed_check: str) -> None:
    updated, decision = evaluate_canary(
        canary_record(),
        policy(),
        metrics(**changes),
        changed_at="2026-10-08T00:09:00Z",
    )
    assert updated.state == "BLOCKED"
    assert updated.canary_status == "FAILED"
    assert updated.failure_code == "canary_budget_failed"
    assert decision["promotable"] is False
    assert decision["checks"][failed_check] is False


def test_ready_requires_exact_evidence_and_reservation() -> None:
    validating = begin_validation(registered(), changed_at="2026-10-08T00:01:00Z")
    base_readiness = {
        "status": "READY",
        "identity_fingerprint": identity().fingerprint,
        "evidence_digest": DIGESTS[2],
    }
    base_calibration = {
        "status": "CALIBRATED",
        "identity_fingerprint": identity().fingerprint,
        "profile_id": "calibration:generation:2",
        "profile_hash": DIGESTS[3],
    }
    for readiness_value, calibration_value, reservation_value, code in (
        ({**base_readiness, "status": "BLOCKED"}, base_calibration, reservation(), "mo.rollout_readiness_required"),
        (base_readiness, {**base_calibration, "status": "CALIBRATION_REQUIRED"}, reservation(), "mo.rollout_calibration_required"),
        (base_readiness, base_calibration, replace(reservation(), state="RELEASED"), "mo.rollout_reservation_required"),
    ):
        with pytest.raises(ModelRolloutError) as exc:
            mark_rollout_ready(
                validating,
                readiness_value,
                calibration_value,
                reservation_value,
                changed_at="2026-10-08T00:02:00Z",
            )
        assert exc.value.error_code == code


def test_transition_and_canary_prerequisite_guards() -> None:
    with pytest.raises(ModelRolloutError) as exc:
        begin_validation(canary_record(), changed_at="2026-10-08T00:10:00Z")
    assert exc.value.error_code == "mo.rollout_transition_invalid"
    with pytest.raises(ModelRolloutError) as exc:
        mark_rollout_ready(
            registered(),
            {},
            {},
            reservation(),
            changed_at="2026-10-08T00:01:00Z",
        )
    assert exc.value.error_code == "mo.rollout_transition_invalid"
    with pytest.raises(ModelRolloutError) as exc:
        start_canary(registered(), policy(), changed_at="2026-10-08T00:01:00Z")
    assert exc.value.error_code == "mo.rollout_transition_invalid"

    incomplete = replace(
        canary_record(),
        state="READY",
        reservation_id=None,
        canary_policy_hash=None,
        canary_status=None,
    )
    with pytest.raises(ModelRolloutError) as exc:
        start_canary(incomplete, policy(), changed_at="2026-10-08T00:10:00Z")
    assert exc.value.error_code == "mo.rollout_canary_prerequisite_missing"

    with pytest.raises(ModelRolloutError) as exc:
        evaluate_canary(
            canary_record(),
            replace(policy(), traffic_percent=5),
            metrics(),
            changed_at="2026-10-08T00:09:00Z",
        )
    assert exc.value.error_code == "mo.rollout_canary_not_active"


def test_candidate_must_differ_and_timestamps_move_forward() -> None:
    with pytest.raises(ModelRolloutError) as exc:
        register_rollout(
            identity(),
            rollout_id="rollout:same",
            last_known_good_binding_id="binding:same",
            last_known_good_identity_fingerprint=identity().fingerprint,
            created_at="2026-10-08T00:00:00Z",
        )
    assert exc.value.error_code == "mo.rollout_candidate_revision_required"

    with pytest.raises(ModelRolloutError) as exc:
        begin_validation(registered(), changed_at="2026-10-07T23:00:00Z")
    assert exc.value.error_code == "mo.rollout_timestamp_invalid"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"traffic_percent": 0}, "mo.canary_traffic_invalid"),
        ({"traffic_percent": 26}, "mo.canary_traffic_invalid"),
        ({"observation_seconds": 59}, "mo.canary_observation_invalid"),
        ({"maximum_error_rate": 2}, "mo.canary_error_budget_invalid"),
        ({"minimum_quality_score": -1}, "mo.canary_quality_budget_invalid"),
        ({"maximum_p95_latency_ms": 0}, "mo.canary_latency_budget_invalid"),
    ],
)
def test_canary_policy_validation(changes, code: str) -> None:
    with pytest.raises(ModelRolloutError) as exc:
        replace(policy(), **changes)
    assert exc.value.error_code == code


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"identity_fingerprint": "bad"}, "mo.identity_fingerprint_invalid"),
        ({"sample_count": -1}, "mo.canary_metric_count_invalid"),
        ({"error_rate": 2}, "mo.canary_metric_rate_invalid"),
        ({"measured_at": "bad"}, "mo.measured_at_invalid"),
    ],
)
def test_canary_metric_validation(changes, code: str) -> None:
    with pytest.raises(ModelRolloutError) as exc:
        metrics(**changes)
    assert exc.value.error_code == code


def test_timezone_is_required() -> None:
    with pytest.raises(ModelRolloutError) as exc:
        metrics(measured_at="2026-10-08T00:00:00")
    assert exc.value.error_code == "mo.measured_at_invalid"


def test_rollout_record_validation() -> None:
    valid = registered()
    for changes, code in (
        ({"rollout_id": "bad id"}, "mo.rollout_id_invalid"),
        ({"last_known_good_identity_fingerprint": "bad"}, "mo.last_known_good_identity_fingerprint_invalid"),
        ({"state": "UNKNOWN"}, "mo.rollout_state_invalid"),
        ({"state_revision": 0}, "mo.rollout_state_revision_invalid"),
        ({"updated_at": "2026-10-07T00:00:00Z"}, "mo.rollout_timestamp_invalid"),
        ({"canary_policy_hash": "bad"}, "mo.canary_policy_hash_invalid"),
        ({"reservation_id": "bad id"}, "mo.reservation_id_invalid"),
    ):
        with pytest.raises(ModelRolloutError) as exc:
            replace(valid, **changes)
        assert exc.value.error_code == code
