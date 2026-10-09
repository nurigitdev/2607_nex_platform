from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib

import pytest

from nex_runtime.preproduction_faults import (
    FaultPlanError,
    FaultRehearsalResult,
    FaultState,
    build_default_fault_plan,
    evaluate_fault_rehearsals,
    transition_fault_state,
    validate_fault_plan,
)


DIGEST = hashlib.sha256(b"workload").hexdigest()


def _plan():
    return build_default_fault_plan(
        release_candidate_id="rc:s149:test",
        workload_digest=DIGEST,
    )


def _results():
    return [
        FaultRehearsalResult(item["scenario_id"], "RECOVERED", 500, 5_000)
        for item in _plan()["scenarios"]
    ]


def test_default_plan_and_recovery_evaluation_pass() -> None:
    plan = _plan()
    result = evaluate_fault_rehearsals(plan, _results())

    assert plan["admission"] == "ADMITTED"
    assert len(plan["scenarios"]) == 8
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"]["fault_class_count"] == 5
    assert result["summary"]["residue_count"] == 0


def test_state_machine_reaches_recovered_and_can_fail() -> None:
    state = FaultState("fault:test")
    for index, event in enumerate(
        ("begin_injection", "degradation_observed", "begin_recovery", "recovery_verified"),
        start=1,
    ):
        state = transition_fault_state(state, event, changed_at_ms=index)
    assert state.state == "RECOVERED"
    assert state.revision == 4

    failed = transition_fault_state(
        FaultState("fault:test"),
        "fail",
        changed_at_ms=1,
        failure_code="fault.inject_failed",
    )
    assert failed.state == "FAILED"
    assert failed.failure_code == "fault.inject_failed"


@pytest.mark.parametrize(
    "current,event,changed,failure",
    [
        (FaultState("fault:test", state="UNKNOWN"), "begin_injection", 1, None),
        (FaultState("fault:test"), "begin_injection", 0, None),
        (FaultState("fault:test"), "wrong", 1, None),
        (FaultState("fault:test"), "begin_injection", 1, "bad"),
        (FaultState("fault:test", state="RECOVERED"), "fail", 1, "fault.failed"),
        (FaultState("fault:test"), "fail", 1, "bad code"),
    ],
)
def test_state_machine_rejects_invalid_transitions(current, event, changed, failure) -> None:
    with pytest.raises(FaultPlanError):
        transition_fault_state(
            current,
            event,
            changed_at_ms=changed,
            failure_code=failure,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda plan: plan.update(fault_plan_schema_version="bad"),
        lambda plan: plan.update(release_candidate_id="bad id"),
        lambda plan: plan.update(workload_digest="bad"),
        lambda plan: plan.update(topology="production"),
        lambda plan: plan.update(production_targeted=True),
        lambda plan: plan.update(scenarios="bad"),
        lambda plan: plan.update(scenarios=[]),
        lambda plan: plan["scenarios"].append(deepcopy(plan["scenarios"][0])),
        lambda plan: plan["scenarios"].pop(),
        lambda plan: plan["scenarios"].__setitem__(0, "bad"),
        lambda plan: plan["scenarios"][0].update(extra=True),
        lambda plan: plan["scenarios"][0].update(scenario_id="bad id"),
        lambda plan: plan["scenarios"][0].update(fault_class="bad"),
        lambda plan: plan["scenarios"][0].update(
            fault_class="provider_degradation",
            target_alias="embedding-route",
            injection_mode="client_timeout",
        ),
        lambda plan: plan["scenarios"][0].update(target_alias="production-host"),
        lambda plan: plan["scenarios"][0].update(injection_mode="kill-host"),
        lambda plan: plan["scenarios"][0].update(maximum_fault_seconds=True),
        lambda plan: plan["scenarios"][0].update(maximum_recovery_ms=600_001),
        lambda plan: plan["scenarios"][0].update(destructive=True),
        lambda plan: plan["scenarios"][3].update(provider_process_mutation=True),
    ],
)
def test_invalid_fault_plans_fail_closed(mutation) -> None:
    plan = deepcopy(_plan())
    plan.pop("fault_plan_digest")
    plan.pop("admission")
    mutation(plan)
    with pytest.raises(FaultPlanError):
        validate_fault_plan(plan)


def test_build_rejects_bad_release_or_digest() -> None:
    with pytest.raises(FaultPlanError):
        build_default_fault_plan(release_candidate_id="bad id", workload_digest=DIGEST)
    with pytest.raises(FaultPlanError):
        build_default_fault_plan(release_candidate_id="rc:s149:test", workload_digest="bad")


def test_rehearsal_failure_reports_every_guard() -> None:
    rows = _results()
    rows[0] = replace(
        rows[0],
        final_state="FAILED",
        detection_ms=100_000,
        recovery_ms=1_000_000,
        data_loss_count=1,
        isolation_violation_count=1,
        residue_count=1,
    )
    plan = deepcopy(_plan())
    plan["scenarios"][3]["provider_process_mutation"] = True
    plan["production_targeted"] = True

    result = evaluate_fault_rehearsals(plan, rows)

    assert result["status"] == "FAIL"
    assert set(result["failed_checks"]) == set(result["checks"])


def test_rehearsal_inventory_and_measurements_fail_closed() -> None:
    with pytest.raises(FaultPlanError):
        evaluate_fault_rehearsals({}, _results())
    with pytest.raises(FaultPlanError):
        evaluate_fault_rehearsals(_plan(), [])
    with pytest.raises(FaultPlanError):
        evaluate_fault_rehearsals(_plan(), _results()[:-1])
    duplicate = _results()
    duplicate[-1] = duplicate[0]
    with pytest.raises(FaultPlanError):
        evaluate_fault_rehearsals(_plan(), duplicate)
    bad_state = _results()
    bad_state[0] = replace(bad_state[0], final_state="UNKNOWN")
    with pytest.raises(FaultPlanError):
        evaluate_fault_rehearsals(_plan(), bad_state)
    bad_metric = _results()
    bad_metric[0] = replace(bad_metric[0], detection_ms=True)
    with pytest.raises(FaultPlanError):
        evaluate_fault_rehearsals(_plan(), bad_metric)
