from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib

import pytest

from nex_runtime.preproduction_rollback import (
    RollbackComponentResult,
    RollbackPlanError,
    RollbackResidue,
    RollbackState,
    build_default_rollback_plan,
    evaluate_rollback_rehearsal,
    transition_rollback_state,
    validate_rollback_plan,
)


DIGEST = hashlib.sha256(b"fault-plan").hexdigest()


def _plan():
    return build_default_rollback_plan(
        release_candidate_id="rc:s149:test",
        fault_plan_digest=DIGEST,
    )


def _results(plan=None):
    plan = plan or _plan()
    return [
        RollbackComponentResult(item["component_id"], item["last_known_good_digest"], True)
        for item in plan["components"]
    ]


def _completed_state():
    state = RollbackState("rollback:s149:test")
    for index, event in enumerate(
        ("trigger", "begin_restore", "begin_verification", "verification_passed"),
        start=1,
    ):
        state = transition_rollback_state(state, event, changed_at_ms=index)
    return state


def test_default_rollback_plan_and_rehearsal_pass() -> None:
    plan = _plan()
    result = evaluate_rollback_rehearsal(
        plan,
        final_state=_completed_state(),
        component_results=_results(plan),
        recovery_ms=120_000,
        residue=RollbackResidue(),
    )

    assert plan["admission"] == "ADMITTED"
    assert len(plan["components"]) == 6
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"]["residue_count"] == 0


def test_state_machine_completion_and_failure() -> None:
    completed = _completed_state()
    assert completed.state == "COMPLETED"
    assert completed.revision == 4
    failed = transition_rollback_state(
        RollbackState("rollback:s149:test"),
        "fail",
        changed_at_ms=1,
        failure_code="rollback.trigger_failed",
    )
    assert failed.state == "FAILED"


@pytest.mark.parametrize(
    "state,event,changed,failure",
    [
        (RollbackState("rollback:test", state="UNKNOWN"), "trigger", 1, None),
        (RollbackState("rollback:test"), "trigger", 0, None),
        (RollbackState("rollback:test"), "wrong", 1, None),
        (RollbackState("rollback:test"), "trigger", 1, "bad"),
        (RollbackState("rollback:test", state="COMPLETED"), "fail", 1, "rollback.failed"),
        (RollbackState("rollback:test"), "fail", 1, "bad code"),
    ],
)
def test_state_machine_rejects_invalid_transition(state, event, changed, failure) -> None:
    with pytest.raises(RollbackPlanError):
        transition_rollback_state(
            state,
            event,
            changed_at_ms=changed,
            failure_code=failure,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda plan: plan.update(rollback_plan_schema_version="bad"),
        lambda plan: plan.update(release_candidate_id="bad id"),
        lambda plan: plan.update(fault_plan_digest="bad"),
        lambda plan: plan.update(topology="production"),
        lambda plan: plan.update(production_deployment_targeted=True),
        lambda plan: plan.update(maximum_recovery_ms=True),
        lambda plan: plan.update(maximum_recovery_ms=999),
        lambda plan: plan.update(components="bad"),
        lambda plan: plan.update(components=[]),
        lambda plan: plan["components"].append(deepcopy(plan["components"][0])),
        lambda plan: plan["components"].pop(),
        lambda plan: plan["components"].__setitem__(0, "bad"),
        lambda plan: plan["components"][0].update(extra=True),
        lambda plan: plan["components"][0].update(component_id="bad id"),
        lambda plan: plan["components"][0].update(candidate_digest="bad"),
        lambda plan: plan["components"][0].update(
            candidate_digest=plan["components"][0]["last_known_good_digest"]
        ),
        lambda plan: plan["components"][0].update(strategy="manual"),
        lambda plan: plan["components"][0].update(preserves_committed_data=False),
    ],
)
def test_invalid_rollback_plan_fails_closed(mutation) -> None:
    plan = deepcopy(_plan())
    plan.pop("rollback_plan_digest")
    plan.pop("admission")
    mutation(plan)
    with pytest.raises(RollbackPlanError):
        validate_rollback_plan(plan)


def test_builder_rejects_invalid_binding() -> None:
    with pytest.raises(RollbackPlanError):
        build_default_rollback_plan(release_candidate_id="bad id", fault_plan_digest=DIGEST)
    with pytest.raises(RollbackPlanError):
        build_default_rollback_plan(release_candidate_id="rc:s149:test", fault_plan_digest="bad")


def test_rehearsal_reports_all_failures() -> None:
    plan = deepcopy(_plan())
    plan["production_deployment_targeted"] = True
    rows = _results(plan)
    rows[0] = replace(
        rows[0],
        restored_digest="f" * 64,
        verification_passed=False,
        committed_data_loss_count=1,
    )
    result = evaluate_rollback_rehearsal(
        plan,
        final_state=RollbackState("rollback:s149:test", state="FAILED"),
        component_results=rows,
        recovery_ms=400_000,
        residue=RollbackResidue(database_row_count=1),
    )

    assert result["status"] == "FAIL"
    assert set(result["failed_checks"]) == set(result["checks"])


def test_rehearsal_inputs_fail_closed() -> None:
    plan = _plan()
    with pytest.raises(RollbackPlanError):
        evaluate_rollback_rehearsal({}, final_state=_completed_state(), component_results=_results(), recovery_ms=1, residue=RollbackResidue())
    with pytest.raises(RollbackPlanError):
        evaluate_rollback_rehearsal(plan, final_state=RollbackState("id", state="UNKNOWN"), component_results=_results(), recovery_ms=1, residue=RollbackResidue())
    with pytest.raises(RollbackPlanError):
        evaluate_rollback_rehearsal(plan, final_state=_completed_state(), component_results=_results(), recovery_ms=True, residue=RollbackResidue())
    with pytest.raises(RollbackPlanError):
        evaluate_rollback_rehearsal(plan, final_state=_completed_state(), component_results=[], recovery_ms=1, residue=RollbackResidue())
    with pytest.raises(RollbackPlanError):
        evaluate_rollback_rehearsal(plan, final_state=_completed_state(), component_results=_results()[:-1], recovery_ms=1, residue=RollbackResidue())
    duplicate = _results()
    duplicate[-1] = duplicate[0]
    with pytest.raises(RollbackPlanError):
        evaluate_rollback_rehearsal(plan, final_state=_completed_state(), component_results=duplicate, recovery_ms=1, residue=RollbackResidue())


@pytest.mark.parametrize(
    "bad_result",
    [
        "bad",
        RollbackComponentResult("bad id", "a" * 64, True),
        RollbackComponentResult("component:test", "bad", True),
        RollbackComponentResult("component:test", "a" * 64, 1),
        RollbackComponentResult("component:test", "a" * 64, True, True),
    ],
)
def test_malformed_component_result_is_rejected(bad_result) -> None:
    rows = _results()
    rows[0] = bad_result
    with pytest.raises(RollbackPlanError):
        evaluate_rollback_rehearsal(
            _plan(),
            final_state=_completed_state(),
            component_results=rows,
            recovery_ms=1,
            residue=RollbackResidue(),
        )


def test_malformed_residue_is_rejected() -> None:
    with pytest.raises(RollbackPlanError):
        evaluate_rollback_rehearsal(
            _plan(),
            final_state=_completed_state(),
            component_results=_results(),
            recovery_ms=1,
            residue=RollbackResidue(database_row_count=True),
        )

