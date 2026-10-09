from __future__ import annotations

from dataclasses import replace
import math

import pytest

from nex_runtime.preproduction_soak import (
    SoakEvaluationError,
    SoakPolicy,
    SoakWindow,
    evaluate_soak_windows,
)
from nex_runtime.preproduction_workload import (
    admit_workload_profile,
    build_default_workload_profiles,
)


RC = "rc:s149:test"


def _profile(index: int = 2):
    profile = build_default_workload_profiles(RC)[index]
    return admit_workload_profile(profile, expected_release_candidate_id=RC)


def _windows():
    return tuple(
        SoakWindow(
            window_id=f"w:{index}",
            sequence=index,
            duration_seconds=300.0,
            request_count=1_200,
            error_rate=0.001,
            p95_latency_ms=1_000.0 + index,
            throughput_rps=4.0,
            saturation_ratio=0.5,
            process_memory_bytes=100_000_000 + index * 100_000,
            open_connection_count=10,
            queue_age_ms=20.0 + index,
        )
        for index in range(6)
    )


def test_stable_soak_windows_pass() -> None:
    result = evaluate_soak_windows(_profile(), _windows())

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["metrics"]["duration_seconds"] == 1_800.0
    assert result["metrics"]["request_count"] == 7_200
    assert result["failed_checks"] == []


def test_all_soak_budget_and_trend_failures_are_reported() -> None:
    profile = _profile()
    rows = list(_windows())
    rows[0] = replace(rows[0], request_count=0)
    rows[-2] = replace(rows[-2], error_rate=0.0, p95_latency_ms=100.0)
    rows[-1] = replace(
        rows[-1],
        duration_seconds=1.0,
        error_rate=0.5,
        p95_latency_ms=9_000.0,
        throughput_rps=0.1,
        saturation_ratio=1.0,
        process_memory_bytes=130_000_000,
        open_connection_count=20,
        queue_age_ms=500.0,
        duplicate_side_effect_count=1,
        isolation_violation_count=1,
    )

    result = evaluate_soak_windows(profile, rows)

    assert result["status"] == "FAIL"
    assert set(result["failed_checks"]) == set(result["checks"])


def test_profile_window_inventory_and_policy_fail_closed() -> None:
    with pytest.raises(SoakEvaluationError):
        evaluate_soak_windows({}, _windows())
    with pytest.raises(SoakEvaluationError):
        evaluate_soak_windows(_profile(0), _windows())
    with pytest.raises(SoakEvaluationError):
        evaluate_soak_windows(_profile(), _windows()[:2])
    with pytest.raises(SoakEvaluationError):
        evaluate_soak_windows(
            _profile(),
            (replace(_windows()[0], sequence=1), *_windows()[1:]),
        )
    with pytest.raises(SoakEvaluationError):
        evaluate_soak_windows(
            _profile(),
            (replace(_windows()[0], window_id="w:1"), *_windows()[1:]),
        )
    with pytest.raises(SoakEvaluationError):
        evaluate_soak_windows(_profile(), _windows(), policy=SoakPolicy(minimum_window_count=True))
    with pytest.raises(SoakEvaluationError):
        evaluate_soak_windows(
            _profile(),
            _windows(),
            policy=SoakPolicy(maximum_memory_growth_ratio=math.nan),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: replace(value, window_id=""),
        lambda value: replace(value, sequence=True),
        lambda value: replace(value, request_count=-1),
        lambda value: replace(value, duration_seconds=math.nan),
        lambda value: replace(value, duration_seconds=0.0),
        lambda value: replace(value, process_memory_bytes=0),
        lambda value: replace(value, error_rate=1.1),
        lambda value: replace(value, saturation_ratio=1.1),
    ],
)
def test_malformed_window_is_rejected(mutation) -> None:
    rows = list(_windows())
    rows[0] = mutation(rows[0])
    with pytest.raises(SoakEvaluationError):
        evaluate_soak_windows(_profile(), rows)

