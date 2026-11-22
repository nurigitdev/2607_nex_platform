from __future__ import annotations

import copy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import nex_ae_api.m1_plan_activation as activation_module
import pytest
from mybee_ax.integrations import M1_D04_CAPABILITY_ID, M1_D12_CAPABILITY_ID
from nex_ae_api.m1_plan_activation import (
    InstalledM1PlanActivation,
    M1PlanActivationError,
)
from nex_ae_api.m1_product_preparation_coordinator import (
    M1ProductPreparationCoordinatorError,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_ae_mybee_w70_cp_m1_e2e_fx_01b5_plan_materialization import (
    _agent_context,
    _preparation,
    _runtime,
    _snapshot,
    _work_intent,
)
from test_ae_mybee_w70_cp_m1_e2e_fx_01b6b2_preparation_resume import (
    DETERMINISTIC_POLICY,
    ENVELOPE_ID,
    EVIDENCE_ID,
    M1_PRODUCT_PLANNING_POLICY,
    TENANT,
    _coordinator,
    _inputs,
    _match,
    _notify,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 17, 2, 0, tzinfo=UTC)
NOW_TEXT = "2026-11-17T02:00:00Z"


class _ReadyCheckpointSource:
    def __init__(
        self, registration, checkpoint, preparation, events, *, proposal_ref=None
    ) -> None:
        self.registration = registration
        self.checkpoint = checkpoint
        self.preparation = preparation
        self.events = events
        self.proposal_ref = proposal_ref

    def load_ready_checkpoint(self, **_values):
        self.events.append("ready")
        return {
            "checkpoint": copy.deepcopy(self.checkpoint),
            "preparation": copy.deepcopy(self.preparation),
            "planning_proposal_ref": copy.deepcopy(self.proposal_ref),
        }


class _Materializer:
    def __init__(self, runtime, events) -> None:
        self.runtime = runtime
        self.events = events
        self.calls = 0

    def materialize_transaction_plan(self, **values):
        self.calls += 1
        self.events.append("materialize")
        return self.runtime.materialize_transaction_plan(**values)


class _AgentPlanStore:
    def __init__(self, events, *, fail_after_save=False) -> None:
        self.records = {}
        self.events = events
        self.save_calls = 0
        self.fail_after_save = fail_after_save
        self.failed = False

    def get(self, *, tenant_id, agent_plan_id):
        value = self.records.get((tenant_id, agent_plan_id))
        return None if value is None else copy.deepcopy(value)

    def save(self, *, tenant_id, agent_plan, created_at):
        assert created_at == NOW_TEXT
        self.events.append("agent-plan")
        self.save_calls += 1
        key = (tenant_id, agent_plan["agent_plan_id"])
        saved = self.records.setdefault(key, copy.deepcopy(agent_plan))
        if self.fail_after_save and not self.failed:
            self.failed = True
            raise RuntimeError("crash after AgentPlan commit")
        return copy.deepcopy(saved)


class _ExecutionStore:
    def __init__(self, execution_id) -> None:
        self.record = {
            "tenant_id": TENANT,
            "agent_execution_id": execution_id,
            "version": 1,
            "state": "QUEUED",
            "phase": "INTAKE",
        }

    def get(self, tenant_id, agent_execution_id):
        if (
            self.record is None
            or tenant_id != self.record["tenant_id"]
            or agent_execution_id != self.record["agent_execution_id"]
        ):
            return None
        return copy.deepcopy(self.record)


class _ValidationStore:
    def __init__(self, events, executions, *, fail_after_save=False) -> None:
        self.records = {}
        self.events = events
        self.executions = executions
        self.save_calls = 0
        self.fail_after_save = fail_after_save
        self.failed = False

    def get(self, *, tenant_id, validation_result_id):
        value = self.records.get((tenant_id, validation_result_id))
        return None if value is None else copy.deepcopy(value)

    def save_and_apply_runtime(self, *, tenant_id, result, expected_execution_version):
        assert expected_execution_version == self.executions.record["version"]
        self.events.append("validation")
        self.save_calls += 1
        key = (tenant_id, result["validation_result_id"])
        saved = self.records.setdefault(key, copy.deepcopy(result))
        self.executions.record.update(
            version=expected_execution_version + 1,
            state="RUNNING",
            phase="PLAN_COMPILE",
        )
        if self.fail_after_save and not self.failed:
            self.failed = True
            raise RuntimeError("crash after PlanValidation commit")
        return copy.deepcopy(saved)


class _ExecutablePlanStore:
    def __init__(self, events, *, fail_after_save=False) -> None:
        self.records = {}
        self.events = events
        self.save_calls = 0
        self.fail_after_save = fail_after_save
        self.failed = False

    def get(self, *, tenant_id, executable_plan_id):
        value = self.records.get((tenant_id, executable_plan_id))
        return None if value is None else copy.deepcopy(value)

    def save(self, *, tenant_id, executable_plan):
        self.events.append("executable-plan")
        self.save_calls += 1
        key = (tenant_id, executable_plan["executable_plan_id"])
        saved = self.records.setdefault(key, copy.deepcopy(executable_plan))
        if self.fail_after_save and not self.failed:
            self.failed = True
            raise RuntimeError("crash after ExecutablePlan commit")
        return copy.deepcopy(saved)


class _Scheduler:
    def __init__(self, events, *, fail_after_save=False) -> None:
        self.events = events
        self.jobs = {}
        self.calls = 0
        self.fail_after_save = fail_after_save
        self.failed = False

    def schedule_next(self, *, tenant_id, execution_id, now):
        assert now == NOW_TEXT
        self.events.append("schedule")
        self.calls += 1
        job = self.jobs.setdefault(
            (tenant_id, execution_id),
            {
                "runtime_job_id": "51000000-0000-4000-8000-000000000001",
                "job_type": "START_EXECUTION",
                "execution_id": execution_id,
            },
        )
        if self.fail_after_save and not self.failed:
            self.failed = True
            raise RuntimeError("crash after RuntimeJob commit")
        return copy.deepcopy(job)


def _components(
    *,
    crash_after=None,
    planning_policy=DETERMINISTIC_POLICY,
    proposal_ref=None,
):
    events = []
    runtime = _runtime()
    intent = _work_intent()
    context = _agent_context(intent)
    snapshot = _snapshot(runtime)
    preparation = _preparation(intent)
    registration = _coordinator(planning_policy=planning_policy)[0].registration
    checkpoint = {
        "tenant_id": TENANT,
        "agent_execution_id": intent["execution_id"],
        "checkpoint_id": "51000000-0000-4000-8000-000000000002",
        "checkpoint_hash": semantic_sha256_hash_ref(
            {"preparation_hash": preparation["preparation_hash"]}
        ),
        "business_context_hash": intent["business_context_hash"],
        "materializer_source_identity": registration.materializer_source_identity,
        "stage": "READY_FOR_D04",
        "stage_kind": "READY",
    }
    ready = _ReadyCheckpointSource(
        registration,
        checkpoint,
        preparation,
        events,
        proposal_ref=proposal_ref,
    )
    materializer = _Materializer(runtime, events)
    executions = _ExecutionStore(intent["execution_id"])
    agent_plans = _AgentPlanStore(events, fail_after_save=crash_after == "agent_plan")
    validations = _ValidationStore(
        events,
        executions,
        fail_after_save=crash_after == "validation",
    )
    executable_plans = _ExecutablePlanStore(
        events, fail_after_save=crash_after == "executable_plan"
    )
    scheduler = _Scheduler(events, fail_after_save=crash_after == "scheduler")
    service = InstalledM1PlanActivation(
        registration=registration,
        ready_checkpoints=ready,
        materializer=materializer,
        agent_plans=agent_plans,
        validations=validations,
        executable_plans=executable_plans,
        executions=executions,
        scheduler=scheduler,
        clock=lambda: NOW,
    )
    values = {
        "work_intent": intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": {"execution_id": intent["execution_id"]},
    }
    return SimpleNamespace(
        service=service,
        values=values,
        events=events,
        ready=ready,
        materializer=materializer,
        executions=executions,
        agent_plans=agent_plans,
        validations=validations,
        executable_plans=executable_plans,
        scheduler=scheduler,
    )


def test_6b3_persists_complete_plan_before_existing_scheduler() -> None:
    components = _components()

    result = components.service.activate(**components.values)

    assert components.events == [
        "ready",
        "materialize",
        "agent-plan",
        "validation",
        "executable-plan",
        "schedule",
    ]
    assert result["schema_version"] == "ae.m1_plan_activation.v1"
    assert result["replayed"] == {
        "agent_plan": False,
        "validation": False,
        "executable_plan": False,
    }
    assert result["runtime_job"]["job_type"] == "START_EXECUTION"
    assert components.executions.record["state"] == "RUNNING"
    assert components.executions.record["phase"] == "PLAN_COMPILE"
    executable = next(iter(components.executable_plans.records.values()))
    assert [item["required_capability"] for item in executable["steps"]] == [
        M1_D12_CAPABILITY_ID,
        M1_D04_CAPABILITY_ID,
    ]
    assert executable["steps"][1]["depends_on_compiled_step_keys"] == ["E1"]


def test_6b3_required_proposal_hash_is_bound_to_deterministic_plan() -> None:
    proposal_ref = {
        "schema_version": "ae.product_planning_proposal_ref.v1",
        "proposal_hash": "sha256:" + "d" * 64,
        "candidate_id": "52000000-0000-4000-8000-000000000001",
        "candidate_hash": "sha256:" + "e" * 64,
        "candidate_payload_storage_ref": "private://semantic-candidates/plan-1",
    }
    components = _components(
        planning_policy=M1_PRODUCT_PLANNING_POLICY,
        proposal_ref=proposal_ref,
    )

    result = components.service.activate(**components.values)

    plan = next(iter(components.agent_plans.records.values()))
    assert plan["planner_provenance"]["route_decision_ref"] == (
        f"product-planning-proposal://{proposal_ref['proposal_hash']}"
    )
    assert result["runtime_job"]["job_type"] == "START_EXECUTION"


def test_6b3_exact_replay_reuses_all_plan_artifacts_and_runtime_job() -> None:
    components = _components()
    first = components.service.activate(**components.values)
    replay = components.service.activate(**components.values)

    assert replay["activation_hash"] == first["activation_hash"]
    assert replay["runtime_job"] == first["runtime_job"]
    assert replay["replayed"] == {
        "agent_plan": True,
        "validation": True,
        "executable_plan": True,
    }
    assert components.agent_plans.save_calls == 1
    assert components.validations.save_calls == 1
    assert components.executable_plans.save_calls == 1
    assert len(components.scheduler.jobs) == 1
    assert components.materializer.calls == 2


@pytest.mark.parametrize(
    "boundary", ["agent_plan", "validation", "executable_plan", "scheduler"]
)
def test_6b3_crash_after_each_durable_boundary_converges(boundary: str) -> None:
    components = _components(crash_after=boundary)
    with pytest.raises(RuntimeError, match="crash after"):
        components.service.activate(**components.values)

    result = components.service.activate(**components.values)

    assert result["runtime_job"]["job_type"] == "START_EXECUTION"
    assert len(components.agent_plans.records) == 1
    assert len(components.validations.records) == 1
    assert len(components.executable_plans.records) == 1
    assert len(components.scheduler.jobs) == 1


@pytest.mark.parametrize(
    ("target", "field", "value"),
    (
        ("checkpoint", "stage", "WAITING_ACCOUNTING_APPROVAL"),
        ("checkpoint", "stage_kind", "WAITING"),
        ("checkpoint", "materializer_source_identity", "drifted"),
        ("preparation", "stage", "WAITING_ACCOUNTING_APPROVAL"),
        ("preparation", "business_context_hash", "sha256:" + "f" * 64),
    ),
)
def test_6b3_rejects_non_ready_or_drifted_checkpoint(
    target: str, field: str, value: str
) -> None:
    components = _components()
    setattr(
        components.ready,
        target,
        {**getattr(components.ready, target), field: value},
    )

    with pytest.raises(M1PlanActivationError) as raised:
        components.service.activate(**components.values)

    assert raised.value.error_code == "M1_PLAN_ACTIVATION_CONFLICT"
    assert components.materializer.calls == 0
    assert components.scheduler.calls == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "agent_execution",
        "validation_execution",
        "validation_plan_id",
        "validation_plan_hash",
        "executable_execution",
        "executable_plan_id",
        "executable_plan_hash",
        "executable_validation_id",
        "executable_validation_hash",
        "validation_status",
    ],
)
def test_6b3_rejects_materialized_lineage_drift_before_persistence(
    monkeypatch, mutation: str
) -> None:
    components = _components()
    actual = components.materializer.materialize_transaction_plan(
        work_intent=components.values["work_intent"],
        agent_context=components.values["agent_context"],
        capability_snapshot=components.values["capability_snapshot"],
        preparation_checkpoint=components.ready.preparation,
    )
    plan = copy.deepcopy(actual.agent_plan)
    validation = copy.deepcopy(actual.validation_result)
    executable = copy.deepcopy(actual.executable_plan)
    replacements = {
        "agent_execution": (plan, "execution_id", "drift"),
        "validation_execution": (validation, "execution_id", "drift"),
        "validation_plan_id": (validation["agent_plan_ref"], "id", "drift"),
        "validation_plan_hash": (
            validation["agent_plan_ref"],
            "hash",
            "sha256:" + "f" * 64,
        ),
        "executable_execution": (executable, "execution_id", "drift"),
        "executable_plan_id": (executable["agent_plan_ref"], "id", "drift"),
        "executable_plan_hash": (
            executable["agent_plan_ref"],
            "hash",
            "sha256:" + "f" * 64,
        ),
        "executable_validation_id": (
            executable["validation_result_ref"],
            "id",
            "drift",
        ),
        "executable_validation_hash": (
            executable["validation_result_ref"],
            "hash",
            "sha256:" + "f" * 64,
        ),
        "validation_status": (validation, "status", "BLOCKED"),
    }
    record, field, value = replacements[mutation]
    record[field] = value
    monkeypatch.setattr(
        components.materializer,
        "materialize_transaction_plan",
        lambda **_values: SimpleNamespace(
            agent_plan=plan,
            validation_result=validation,
            executable_plan=executable,
        ),
    )

    with pytest.raises(M1PlanActivationError) as raised:
        components.service.activate(**components.values)

    assert raised.value.error_code == "M1_PLAN_ACTIVATION_CONFLICT"
    assert components.agent_plans.records == {}


@pytest.mark.parametrize("artifact", ["agent_plan", "validation", "executable"])
def test_6b3_rejects_immutable_persistence_drift(artifact: str) -> None:
    components = _components()
    first = components.service.activate(**components.values)
    stores = {
        "agent_plan": components.agent_plans.records,
        "validation": components.validations.records,
        "executable": components.executable_plans.records,
    }
    record = next(iter(stores[artifact].values()))
    record["drift"] = True

    with pytest.raises(M1PlanActivationError) as raised:
        components.service.activate(**components.values)

    assert raised.value.error_code == "M1_PLAN_ACTIVATION_CONFLICT"
    assert first["runtime_job"] is not None


@pytest.mark.parametrize(
    "execution_record", [None, {}, {"version": True}, {"version": 0}]
)
def test_6b3_requires_exact_persisted_execution(execution_record) -> None:
    components = _components()
    if execution_record is None:
        components.executions.record = None
    else:
        components.executions.record = {
            "tenant_id": TENANT,
            "agent_execution_id": components.values["work_intent"]["execution_id"],
            **execution_record,
        }

    with pytest.raises(M1PlanActivationError) as raised:
        components.service.activate(**components.values)

    assert raised.value.error_code == "M1_PLAN_ACTIVATION_CONFLICT"
    assert components.validations.records == {}
    assert components.scheduler.calls == 0


def test_6b3_rejects_invalid_materializer_output_and_naive_clock(monkeypatch) -> None:
    components = _components()
    monkeypatch.setattr(
        components.materializer,
        "materialize_transaction_plan",
        lambda **_values: object(),
    )
    with pytest.raises(M1PlanActivationError) as raised:
        components.service.activate(**components.values)
    assert raised.value.error_code == "M1_PLAN_ACTIVATION_INVALID"

    components = _components()
    components.service._clock = lambda: NOW.replace(tzinfo=None)
    with pytest.raises(M1PlanActivationError, match="timezone-aware"):
        components.service.activate(**components.values)


def test_6b3_constructor_rejects_registration_and_dependency_drift() -> None:
    components = _components()
    values = {
        "registration": components.service.registration,
        "ready_checkpoints": components.ready,
        "materializer": components.materializer,
        "agent_plans": components.agent_plans,
        "validations": components.validations,
        "executable_plans": components.executable_plans,
        "executions": components.executions,
        "scheduler": components.scheduler,
    }
    with pytest.raises(M1PlanActivationError):
        InstalledM1PlanActivation(
            **{
                **values,
                "registration": replace(
                    values["registration"], coordinator_version="drift"
                ),
            }
        )
    with pytest.raises(M1PlanActivationError):
        InstalledM1PlanActivation(**{**values, "scheduler": object()})


def test_6b3_product_coordinator_exposes_only_latest_ready_checkpoint() -> None:
    coordinator, _adapter, _source, checkpoints, waits = _coordinator()
    work_intent, context, snapshot, execution = _inputs()
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
    }
    with pytest.raises(M1ProductPreparationCoordinatorError) as missing:
        coordinator.load_ready_checkpoint(**values)
    assert missing.value.error_code == "ae.m1_product_preparation_not_found"

    business = coordinator.begin(**values)
    with pytest.raises(M1ProductPreparationCoordinatorError) as waiting:
        coordinator.load_ready_checkpoint(**values)
    assert waiting.value.error_code == "ae.m1_product_preparation_conflict"
    _notify(
        coordinator,
        business["checkpoint"],
        event_id="business-ready-6b3",
        evidence_ref=ENVELOPE_ID,
    )
    accounting = coordinator.resume_approval(
        event_id="business-ready-6b3",
        runtime_job_id=_match(waits, event_id="business-ready-6b3"),
        **values,
    )
    _notify(
        coordinator,
        accounting["checkpoint"],
        event_id="accounting-ready-6b3",
        evidence_ref=EVIDENCE_ID,
    )
    ready = coordinator.resume_approval(
        event_id="accounting-ready-6b3",
        runtime_job_id=_match(waits, event_id="accounting-ready-6b3"),
        **values,
    )

    loaded = coordinator.load_ready_checkpoint(**values)
    assert loaded["checkpoint"] == ready["checkpoint"]
    assert loaded["preparation"]["stage"] == "READY_FOR_D04"
    assert len(checkpoints.records) == 3


def test_6b3_source_has_no_fixture_or_generic_runtime_branch_residue() -> None:
    source = (ROOT / "services/nex-ae-api/nex_ae_api/m1_plan_activation.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    assert "schedule_next(" in source
    assert "materialize_transaction_plan(" in source
    assert "fixture" not in lowered
    assert "demo" not in lowered
    assert "if capability_id ==" not in source
    assert "40/60" not in source


@pytest.mark.parametrize(
    ("value", "label"),
    [(None, "READY checkpoint"), ("invalid", "M1 preparation")],
)
def test_6b3_rejects_missing_ready_projection(value, label) -> None:
    components = _components()
    if label == "READY checkpoint":
        components.ready.checkpoint = value
    else:
        components.ready.preparation = value
    with pytest.raises(M1PlanActivationError, match=label):
        components.service.activate(**components.values)


def test_6b3_post_persistence_non_valid_replay_does_not_schedule() -> None:
    components = _components()
    first = components.service.activate(**components.values)
    validation = next(iter(components.validations.records.values()))
    validation["status"] = "BLOCKED"
    components.validations.records = {
        key: validation for key in components.validations.records
    }
    with pytest.raises(M1PlanActivationError):
        components.service.activate(**components.values)
    assert first["runtime_job"] is not None
    assert components.scheduler.calls == 1


def test_6b3_scheduler_may_return_no_new_job_after_complete_persistence(
    monkeypatch,
) -> None:
    components = _components()
    monkeypatch.setattr(components.scheduler, "schedule_next", lambda **_values: None)
    result = components.service.activate(**components.values)
    assert result["runtime_job"] is None
    assert result["activation_hash"].startswith("sha256:")


def test_6b3_private_helpers_reject_invalid_scalar_and_persistence_return() -> None:
    with pytest.raises(M1PlanActivationError):
        activation_module._text("", "field", 10)
    with pytest.raises(M1PlanActivationError):
        activation_module._mapping([], "record")
    with pytest.raises(M1PlanActivationError):
        activation_module._require_exact({}, {"expected": True}, "record")

    components = _components()
    components.agent_plans.save = lambda **_values: {"different": True}
    with pytest.raises(M1PlanActivationError):
        components.service.activate(**components.values)
