from __future__ import annotations

from types import SimpleNamespace

import pytest
from nex_ae_api.agent_execution import AgentExecutionError, AgentRuntimeAdmission
from nex_ae_api.background_planning import (
    BackgroundPlanningError,
    InstalledClaimHandoffAdmission,
    background_runtime_policy_ref,
    build_installed_claim_handoff_admission,
)
from nex_ae_api.multi_step_engine import MultiStepEngineError

TENANT = "VO00"
EXECUTION_ID = "11111111-1111-4111-8111-111111111113"
EVENT_ID = "22222222-2222-4222-8222-222222222223"
NOW = "2026-11-15T20:00:00Z"


class _Admission:
    def __init__(self, execution: dict | None = None) -> None:
        self.execution = execution or {
            "tenant_id": TENANT,
            "agent_execution_id": EXECUTION_ID,
            "correlation_id": "m1-correlation",
        }
        self.calls: list[dict] = []

    def admit_claimed_work(self, **values):
        self.calls.append(values)
        return AgentRuntimeAdmission(mode="required", execution=self.execution)


class _Planning:
    def __init__(self, result=None, failure: Exception | None = None) -> None:
        self.result = result or SimpleNamespace(
            status="COMPILED",
            agent_execution_id=EXECUTION_ID,
            executable_plan_id="33333333-3333-4333-8333-333333333333",
        )
        self.failure = failure
        self.calls: list[dict] = []

    def plan_claimed_execution(self, **values):
        self.calls.append(values)
        if self.failure is not None:
            raise self.failure
        return self.result


class _Scheduler:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[dict] = []

    def schedule_next(self, **values):
        self.calls.append(values)
        if self.failure is not None:
            raise self.failure
        return {"runtime_job_id": "44444444-4444-4444-8444-444444444443"}


def _service(*, admission=None, planning=None, scheduler=None):
    return InstalledClaimHandoffAdmission(
        admission=admission or _Admission(),
        planning=planning or _Planning(),
        scheduler=scheduler or _Scheduler(),
        clock=lambda: NOW,
    )


def _admit(service):
    return service.admit_claimed_work(
        event_id=EVENT_ID,
        requester_ref="employee-100",
        handoff={"tenant_id": TENANT},
        planning_source={"source_type": "CLAIMED_WORKITEM"},
    )


def test_installed_claim_handoff_plans_and_schedules_before_ack() -> None:
    admission = _Admission()
    planning = _Planning()
    scheduler = _Scheduler()
    result = _admit(
        _service(admission=admission, planning=planning, scheduler=scheduler)
    )

    assert result.execution["agent_execution_id"] == EXECUTION_ID
    assert admission.calls[0]["event_id"] == EVENT_ID
    assert planning.calls == [
        {
            "tenant_id": TENANT,
            "execution_id": EXECUTION_ID,
            "runtime_policy_ref": background_runtime_policy_ref(),
            "request_id": f"claim-handoff:{EVENT_ID}",
            "trace_id": planning.calls[0]["trace_id"],
        }
    ]
    assert len(planning.calls[0]["trace_id"]) == 32
    assert scheduler.calls == [
        {"tenant_id": TENANT, "execution_id": EXECUTION_ID, "now": NOW}
    ]


def test_installed_claim_handoff_replay_reuses_durable_execution_path() -> None:
    admission = _Admission()
    planning = _Planning()
    scheduler = _Scheduler()
    service = _service(admission=admission, planning=planning, scheduler=scheduler)

    assert _admit(service).execution == _admit(service).execution
    assert len(admission.calls) == len(planning.calls) == len(scheduler.calls) == 2
    assert (
        planning.calls[0]["runtime_policy_ref"]
        == planning.calls[1]["runtime_policy_ref"]
    )


def test_installed_claim_handoff_rejects_missing_execution() -> None:
    admission = _Admission()
    admission.execution = None
    with pytest.raises(AgentExecutionError) as captured:
        _admit(_service(admission=admission))
    assert captured.value.error_code == "ae.claim_handoff_execution_missing"
    assert captured.value.retryable is True


@pytest.mark.parametrize(
    "execution",
    (
        {"tenant_id": "", "agent_execution_id": EXECUTION_ID},
        {"tenant_id": TENANT, "agent_execution_id": ""},
    ),
)
def test_installed_claim_handoff_rejects_invalid_execution_identity(execution) -> None:
    with pytest.raises(AgentExecutionError) as captured:
        _admit(_service(admission=_Admission(execution)))
    assert captured.value.error_code == "ae.claim_handoff_execution_invalid"


def test_installed_claim_handoff_preserves_planning_failure_semantics() -> None:
    planning = _Planning(
        failure=BackgroundPlanningError(
            "ae.background_provider_unavailable", "provider unavailable", True
        )
    )
    with pytest.raises(AgentExecutionError) as captured:
        _admit(_service(planning=planning))
    assert captured.value.error_code == "ae.background_provider_unavailable"
    assert captured.value.retryable is True


@pytest.mark.parametrize(
    "result",
    (
        SimpleNamespace(
            status="VALIDATION_BLOCKED",
            agent_execution_id=EXECUTION_ID,
            executable_plan_id=None,
        ),
        SimpleNamespace(
            status="COMPILED",
            agent_execution_id="different-execution",
            executable_plan_id="33333333-3333-4333-8333-333333333333",
        ),
        SimpleNamespace(
            status="COMPILED",
            agent_execution_id=EXECUTION_ID,
            executable_plan_id=None,
        ),
    ),
)
def test_installed_claim_handoff_requires_exact_compiled_plan(result) -> None:
    with pytest.raises(AgentExecutionError) as captured:
        _admit(_service(planning=_Planning(result=result)))
    assert captured.value.error_code == "ae.claim_handoff_plan_not_compiled"


def test_installed_claim_handoff_preserves_scheduler_failure_semantics() -> None:
    scheduler = _Scheduler(
        MultiStepEngineError("ae.multi_step_queue_unavailable", "queue down", True)
    )
    with pytest.raises(AgentExecutionError) as captured:
        _admit(_service(scheduler=scheduler))
    assert captured.value.error_code == "ae.multi_step_queue_unavailable"
    assert captured.value.retryable is True


@pytest.mark.parametrize(
    ("agent_runtime", "semantic_runtime", "sessions"),
    (
        (
            SimpleNamespace(mode="shadow", admission=object(), jobs=object()),
            SimpleNamespace(mode="required", service=object()),
            object(),
        ),
        (
            SimpleNamespace(mode="required", admission=None, jobs=object()),
            SimpleNamespace(mode="required", service=object()),
            object(),
        ),
        (
            SimpleNamespace(mode="required", admission=object(), jobs=None),
            SimpleNamespace(mode="required", service=object()),
            object(),
        ),
        (
            SimpleNamespace(mode="required", admission=object(), jobs=object()),
            SimpleNamespace(mode="shadow", service=object()),
            object(),
        ),
        (
            SimpleNamespace(mode="required", admission=object(), jobs=object()),
            SimpleNamespace(mode="required", service=None),
            object(),
        ),
        (
            SimpleNamespace(mode="required", admission=object(), jobs=object()),
            SimpleNamespace(mode="required", service=object()),
            None,
        ),
    ),
)
def test_installed_claim_handoff_builder_is_fail_closed(
    agent_runtime, semantic_runtime, sessions
) -> None:
    assert (
        build_installed_claim_handoff_admission(
            agent_runtime=agent_runtime,
            semantic_runtime=semantic_runtime,
            session_factory=sessions,
        )
        is None
    )


def test_installed_claim_handoff_builder_uses_existing_runtime_components() -> None:
    built = build_installed_claim_handoff_admission(
        agent_runtime=SimpleNamespace(
            mode="required", admission=_Admission(), jobs=object()
        ),
        semantic_runtime=SimpleNamespace(mode="required", service=object()),
        session_factory=object(),
    )
    assert isinstance(built, InstalledClaimHandoffAdmission)


def test_background_runtime_policy_is_stable_and_domain_separated() -> None:
    first = background_runtime_policy_ref()
    second = background_runtime_policy_ref()
    assert first == second
    assert first["rule_id"] == "ae.background.claimed_work.v1"
    assert first["rule_hash"].startswith("sha256:")
    assert len(first["rule_hash"]) == 71
