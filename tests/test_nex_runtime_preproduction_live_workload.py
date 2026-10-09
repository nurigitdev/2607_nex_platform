from __future__ import annotations

from collections import Counter

import pytest

from nex_runtime.preproduction_live_workload import (
    PROTECTED_LIVE_OPERATION_COUNTS,
    PROTECTED_LIVE_PROFILE_ID,
    PROTECTED_LIVE_PROVIDER_CALL_CAPS,
    PROTECTED_LIVE_REQUEST_COUNT,
    _smooth_weighted_operation_ids,
    build_protected_live_load_plan,
    build_protected_live_soak_profile,
    protected_live_plan_summary,
)
from nex_runtime.preproduction_workload import (
    WorkloadProfileError,
    admit_workload_profile,
)


RC = "rc:s149:protected-live-test"


def _admitted() -> dict[str, object]:
    profile = build_protected_live_soak_profile(RC)
    return admit_workload_profile(profile, expected_release_candidate_id=RC)


def test_protected_live_profile_preserves_soak_target_with_explicit_caps() -> None:
    admitted = _admitted()
    operations = {
        item["operation_id"]: item for item in admitted["operations"]  # type: ignore[index]
    }

    assert admitted["profile_id"] == PROTECTED_LIVE_PROFILE_ID
    assert admitted["workload_class"] == "soak"
    assert admitted["concurrency"] == 4
    assert admitted["target_rps"] == 4.0
    assert admitted["measurement_seconds"] == 1_800
    assert admitted["max_generated_records"] == PROTECTED_LIVE_REQUEST_COUNT
    assert sum(item["weight"] for item in operations.values()) == pytest.approx(1.0)
    assert operations["hybrid_retrieval"]["weight"] == pytest.approx(450 / 7_200)
    assert operations["grounded_generation"]["weight"] == pytest.approx(30 / 7_200)
    assert operations["grounded_generation"]["timeout_seconds"] == 90.0


def test_protected_live_plan_is_exact_unique_and_interleaved() -> None:
    admitted = _admitted()
    plan = build_protected_live_load_plan(admitted)
    summary = protected_live_plan_summary(plan)

    assert summary["status"] == "PASS"
    assert all(summary["checks"].values())
    assert summary["provider_call_caps"] == PROTECTED_LIVE_PROVIDER_CALL_CAPS
    assert Counter(item.operation_id for item in plan) == PROTECTED_LIVE_OPERATION_COUNTS
    assert len({item.request_id for item in plan}) == PROTECTED_LIVE_REQUEST_COUNT
    assert plan[0].scheduled_offset_seconds == 0.0
    assert plan[-1].scheduled_offset_seconds == pytest.approx(1_799.75)
    assert {item.operation_id for item in plan[:500]} == set(
        PROTECTED_LIVE_OPERATION_COUNTS
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(admission="REJECTED"), "admitted"),
        (lambda value: value.update(profile_id="wrong"), "identity"),
        (lambda value: value.update(workload_class="baseline"), "must be soak"),
        (lambda value: value.update(target_rps=True), "target RPS"),
    ],
)
def test_protected_live_plan_rejects_drift(mutation, message: str) -> None:
    admitted = _admitted()
    mutation(admitted)

    with pytest.raises(WorkloadProfileError, match=message):
        build_protected_live_load_plan(admitted)


def test_protected_live_helpers_fail_closed_for_noncanonical_plan() -> None:
    with pytest.raises(WorkloadProfileError, match="immutable"):
        _smooth_weighted_operation_ids({"readiness_probe": 1})

    assert protected_live_plan_summary(())["status"] == "FAIL"
