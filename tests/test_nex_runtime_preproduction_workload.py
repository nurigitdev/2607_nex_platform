from __future__ import annotations

from dataclasses import replace
import math

import pytest

from nex_runtime.preproduction_workload import (
    MAX_CONCURRENCY,
    MAX_GENERATED_RECORDS,
    MAX_MEASUREMENT_SECONDS,
    MAX_TARGET_RPS,
    OperationMix,
    REQUIRED_OPERATIONS,
    WorkloadBudget,
    WorkloadProfileError,
    admit_workload_profile,
    build_default_workload_profiles,
)


RC = "rc:s149:test"


def _profile():
    return build_default_workload_profiles(RC)[0]


def test_default_profiles_are_release_bound_and_admitted() -> None:
    admitted = [
        admit_workload_profile(item, expected_release_candidate_id=RC)
        for item in build_default_workload_profiles(RC)
    ]

    assert [item["workload_class"] for item in admitted] == [
        "baseline",
        "concurrency",
        "soak",
    ]
    assert len({item["workload_digest"] for item in admitted}) == 3
    assert all(len(item["operations"]) == len(REQUIRED_OPERATIONS) for item in admitted)
    assert all(item["admission"] == "ADMITTED" for item in admitted)
    assert all(item["production_capacity_claimed"] is False for item in admitted)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: replace(p, profile_id="bad id"),
        lambda p: replace(p, release_candidate_id="bad id"),
        lambda p: replace(p, release_candidate_id="rc:s149:other"),
        lambda p: replace(p, workload_class="burst"),
        lambda p: replace(p, concurrency=True),
        lambda p: replace(p, concurrency=0),
        lambda p: replace(p, concurrency=MAX_CONCURRENCY + 1),
        lambda p: replace(p, target_rps=0.0),
        lambda p: replace(p, target_rps=MAX_TARGET_RPS + 1),
        lambda p: replace(p, warmup_seconds=-1),
        lambda p: replace(p, warmup_seconds=3_601),
        lambda p: replace(p, measurement_seconds=0),
        lambda p: replace(p, measurement_seconds=MAX_MEASUREMENT_SECONDS + 1),
        lambda p: replace(p, cooldown_seconds=-1),
        lambda p: replace(p, cooldown_seconds=3_601),
        lambda p: replace(p, max_generated_records=0),
        lambda p: replace(p, max_generated_records=MAX_GENERATED_RECORDS + 1),
        lambda p: replace(p, operations=()),
        lambda p: replace(p, operations=p.operations + (p.operations[0],)),
        lambda p: replace(p, operations=p.operations[:-1]),
        lambda p: replace(
            p,
            operations=(replace(p.operations[0], operation_id="bad id"), *p.operations[1:]),
        ),
        lambda p: replace(
            p,
            operations=(replace(p.operations[0], weight=0.0), *p.operations[1:]),
        ),
        lambda p: replace(
            p,
            operations=(replace(p.operations[0], timeout_seconds=301.0), *p.operations[1:]),
        ),
        lambda p: replace(
            p,
            operations=tuple(replace(item, weight=0.1) for item in p.operations),
        ),
        lambda p: replace(p, budget=replace(p.budget, max_error_rate=1.1)),
        lambda p: replace(p, budget=replace(p.budget, max_p95_latency_ms=0.0)),
        lambda p: replace(p, budget=replace(p.budget, min_throughput_rps=-1.0)),
        lambda p: replace(p, budget=replace(p.budget, max_saturation_ratio=1.1)),
        lambda p: replace(p, budget=replace(p.budget, max_duplicate_side_effects=-1)),
        lambda p: replace(p, budget=replace(p.budget, max_isolation_violations=1)),
    ],
)
def test_invalid_profiles_fail_closed(mutate) -> None:
    with pytest.raises(WorkloadProfileError):
        admit_workload_profile(mutate(_profile()), expected_release_candidate_id=RC)


@pytest.mark.parametrize("expected", ["bad", "", True])
def test_invalid_expected_release_candidate_fails(expected) -> None:
    with pytest.raises(WorkloadProfileError):
        admit_workload_profile(_profile(), expected_release_candidate_id=expected)


@pytest.mark.parametrize("bad", [math.nan, math.inf, True, "1"])
def test_non_finite_or_non_numeric_values_fail(bad) -> None:
    with pytest.raises(WorkloadProfileError):
        admit_workload_profile(
            replace(_profile(), target_rps=bad),
            expected_release_candidate_id=RC,
        )


def test_explicit_operation_and_budget_edges_are_accepted() -> None:
    operations = tuple(
        OperationMix(item, 1.0 / len(REQUIRED_OPERATIONS), 0.1)
        for item in REQUIRED_OPERATIONS
    )
    profile = replace(
        _profile(),
        concurrency=MAX_CONCURRENCY,
        target_rps=MAX_TARGET_RPS,
        warmup_seconds=0,
        measurement_seconds=MAX_MEASUREMENT_SECONDS,
        cooldown_seconds=0,
        max_generated_records=MAX_GENERATED_RECORDS,
        operations=operations,
        budget=WorkloadBudget(0.0, 1.0, 0.0, 1.0),
    )

    result = admit_workload_profile(profile, expected_release_candidate_id=RC)

    assert result["concurrency"] == MAX_CONCURRENCY
    assert result["budget"]["max_isolation_violations"] == 0

