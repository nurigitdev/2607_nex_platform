from __future__ import annotations

from dataclasses import replace
import hashlib
import math
import time

import pytest

from nex_runtime.preproduction_load import (
    LoadHarnessError,
    LoadRequest,
    OperationOutcome,
    build_load_plan,
    run_bounded_load,
    summarize_load_results,
)
from nex_runtime.preproduction_workload import (
    admit_workload_profile,
    build_default_workload_profiles,
)


RC = "rc:s149:test"


def _admitted(index: int = 1):
    profile = build_default_workload_profiles(RC)[index]
    return admit_workload_profile(profile, expected_release_candidate_id=RC)


def _result(initial_request_id: str, **overrides):
    value = {
        "request_id": initial_request_id,
        "operation_id": "auth_trust",
        "status": "SUCCESS",
        "reason_code": "completed",
        "latency_ms": 10.0,
        "saturation_ratio": 0.5,
        "side_effect_digest": hashlib.sha256(initial_request_id.encode()).hexdigest(),
        "isolation_violation": False,
    }
    value.update(overrides)
    return value


def test_plan_and_concurrent_execution_pass_with_bounded_metadata() -> None:
    admitted = _admitted()
    plan = build_load_plan(admitted, sample_count=70)

    def runner(request):
        time.sleep(0.001)
        return OperationOutcome(
            "SUCCESS",
            "completed",
            0.5,
            hashlib.sha256(request.request_id.encode()).hexdigest(),
        )

    result = run_bounded_load(admitted, plan, runner)

    assert result["status"] == "PASS"
    assert result["metrics"]["request_count"] == 70
    assert 2 <= result["metrics"]["peak_active"] <= admitted["concurrency"]
    assert set(result["outcome_counts"]) == {"DENIED", "ERROR", "SUCCESS", "TIMEOUT"}
    assert {item.operation_id for item in plan} == {
        item["operation_id"] for item in admitted["operations"]
    }
    assert "requests" not in result


def test_runner_exception_is_redacted_to_safe_error() -> None:
    admitted = _admitted(0)
    plan = build_load_plan(admitted, sample_count=1)

    def broken(_request):
        raise RuntimeError("private-value")

    result = run_bounded_load(admitted, plan, broken)

    assert result["status"] == "FAIL"
    assert result["outcome_counts"]["ERROR"] == 1
    assert "private-value" not in str(result)


def test_paced_branch_and_invalid_runner_outcome_are_bounded(monkeypatch) -> None:
    admitted = _admitted(0)
    plan = (LoadRequest("load:one", "auth_trust", 0.01),)
    ticks = iter((0.0, 0.0, 0.0, 0.001, 0.02))
    sleeps = []
    monkeypatch.setattr("nex_runtime.preproduction_load.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("nex_runtime.preproduction_load.time.sleep", sleeps.append)

    result = run_bounded_load(admitted, plan, lambda _request: "invalid", paced=True)

    assert sleeps == [0.01]
    assert result["outcome_counts"]["ERROR"] == 1


def test_paced_request_already_due_does_not_sleep(monkeypatch) -> None:
    admitted = _admitted(0)
    plan = (LoadRequest("load:due", "auth_trust", 0.0),)
    sleeps = []
    monkeypatch.setattr("nex_runtime.preproduction_load.time.sleep", sleeps.append)

    result = run_bounded_load(
        admitted,
        plan,
        lambda _request: OperationOutcome("SUCCESS", "completed", 0.0),
        paced=True,
    )

    assert sleeps == []
    assert result["status"] == "PASS"
    assert result["outcome_counts"]["SUCCESS"] == 1


@pytest.mark.parametrize(
    "profile,samples",
    [
        ({}, 1),
        (_admitted(), True),
        (_admitted(), 0),
        (_admitted(), _admitted()["max_generated_records"] + 1),
    ],
)
def test_plan_rejects_unadmitted_or_unbounded_input(profile, samples) -> None:
    with pytest.raises(LoadHarnessError):
        build_load_plan(profile, sample_count=samples)


def test_execution_rejects_invalid_request_sets() -> None:
    admitted = _admitted(0)
    runner = lambda _request: OperationOutcome("SUCCESS", "ok", 0.0)
    with pytest.raises(LoadHarnessError):
        run_bounded_load({}, [LoadRequest("one", "auth_trust", 0.0)], runner)
    with pytest.raises(LoadHarnessError):
        run_bounded_load(admitted, [], runner)
    too_many = [
        LoadRequest(f"id:{index}", "auth_trust", 0.0)
        for index in range(admitted["max_generated_records"] + 1)
    ]
    with pytest.raises(LoadHarnessError):
        run_bounded_load(admitted, too_many, runner)
    duplicate = [LoadRequest("same", "auth_trust", 0.0)] * 2
    with pytest.raises(LoadHarnessError):
        run_bounded_load(admitted, duplicate, runner)
    with pytest.raises(LoadHarnessError):
        run_bounded_load(
            admitted,
            [LoadRequest("one", "unknown", 0.0)],
            runner,
        )


@pytest.mark.parametrize(
    "outcome",
    [
        OperationOutcome("BAD", "ok", 0.0),
        OperationOutcome("SUCCESS", "BAD CODE", 0.0),
        OperationOutcome("SUCCESS", "ok", math.nan),
        OperationOutcome("SUCCESS", "ok", 1.1),
        OperationOutcome("SUCCESS", "ok", 0.0, "bad"),
        OperationOutcome("SUCCESS", "ok", 0.0, isolation_violation=1),
    ],
)
def test_invalid_outcomes_become_safe_errors(outcome) -> None:
    admitted = _admitted(0)
    plan = build_load_plan(admitted, sample_count=1)

    result = run_bounded_load(admitted, plan, lambda _request: outcome)

    assert result["outcome_counts"]["ERROR"] == 1


def test_summary_reports_each_budget_failure() -> None:
    admitted = _admitted(0)
    duplicate = "a" * 64
    rows = [
        _result(
            "one",
            status="ERROR",
            latency_ms=10_000.0,
            saturation_ratio=1.0,
            side_effect_digest=duplicate,
            isolation_violation=True,
        ),
        _result("two", side_effect_digest=duplicate),
    ]

    result = summarize_load_results(
        admitted,
        rows,
        elapsed_seconds=100.0,
        peak_active=2,
    )

    assert result["status"] == "FAIL"
    assert set(result["failed_checks"]) == {
        "duplicates_within_budget",
        "error_rate_within_budget",
        "isolation_within_budget",
        "p95_latency_within_budget",
        "saturation_within_budget",
        "throughput_within_budget",
        "concurrency_bound_respected",
    }


@pytest.mark.parametrize(
    "rows,elapsed,peak",
    [
        ([], 1.0, 1),
        ([_result("one")], 0.0, 1),
        ([_result("one")], math.nan, 1),
        ([_result("one")], 1.0, True),
        ([_result("one")], 1.0, 0),
        ([_result("same"), _result("same")], 1.0, 1),
    ],
)
def test_summary_rejects_invalid_collection_bounds(rows, elapsed, peak) -> None:
    with pytest.raises(LoadHarnessError):
        summarize_load_results(
            _admitted(),
            rows,
            elapsed_seconds=elapsed,
            peak_active=peak,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"request_id": ""},
        {"operation_id": ""},
        {"status": "BAD"},
        {"reason_code": "BAD CODE"},
        {"latency_ms": True},
        {"latency_ms": -1.0},
        {"latency_ms": math.inf},
        {"saturation_ratio": True},
        {"saturation_ratio": -1.0},
        {"saturation_ratio": math.inf},
        {"side_effect_digest": "bad"},
        {"isolation_violation": 1},
    ],
)
def test_summary_rejects_malformed_results(overrides) -> None:
    with pytest.raises(LoadHarnessError):
        summarize_load_results(
            _admitted(),
            [_result("one", **overrides)],
            elapsed_seconds=1.0,
            peak_active=1,
        )
