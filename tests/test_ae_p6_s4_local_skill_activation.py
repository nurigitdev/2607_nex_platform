from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import nex_ae_api.executable_plans as executable_plan_module
import pytest
from nex_ae_api.agent_plans import build_deterministic_agent_plan
from nex_ae_api.agent_runtime_worker import (
    AgentRuntimeWorkerConfig,
    build_agent_runtime_worker_check,
    build_agent_runtime_worker_profile,
)
from nex_ae_api.executable_plans import (
    ExecutablePlanError,
    compile_executable_plan,
    validate_executable_plan_contract,
)
from nex_ae_api.multi_step_engine import StepExecutionContext
from nex_ae_api.plan_validation import validate_agent_plan
from nex_ae_api.planning_capabilities import (
    DEFAULT_P5_CAPABILITIES,
    CapabilitySnapshotError,
    build_capability_snapshot,
    build_local_skill_capability,
    validate_capability_snapshot_contract,
    validate_local_skill_binding,
)
from nex_ae_api.step_executors import (
    LocalSkillExecutorDependencies,
    P5ExecutorOutcome,
    P5StepExecutorError,
    P5StepExecutorRegistry,
    P6LocalSkillExecutor,
    default_p6_executor_registry,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

TENANT = "tenant-p6-s4"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
INTENT_ID = "22222222-2222-4222-8222-222222222222"
CONTEXT_ID = "33333333-3333-4333-8333-333333333333"
SNAPSHOT_ID = "44444444-4444-4444-8444-444444444444"
PLAN_ID = "55555555-5555-4555-8555-555555555555"
VALIDATION_ID = "66666666-6666-4666-8666-666666666666"
STEP_ID = "77777777-7777-4777-8777-777777777777"
EXECUTABLE_PLAN_ID = "88888888-8888-4888-8888-888888888888"
NOW = "2026-10-15T01:00:00Z"
SEMANTIC_HASH = "sha256:" + "a" * 64
SKILL_ID = "FINANCE.PROJECT_BUDGET_CHECK"
SKILL_VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database/nex-ae-api/migrations/2203_ae_local_skill_activation.sql"


class _ArtifactGateway:
    def resolve_verified(self, **_kwargs):
        return {}


class _BindingRepository:
    def bind_request(self, **_kwargs):
        return {}


class _Backend:
    backend_profile = "NSL_V01_PROCESS_ISOLATED"

    def execute(self, _request):
        return {}


def _local_capability(**overrides):
    values = {
        "skill_id": SKILL_ID,
        "exact_skill_version": SKILL_VERSION,
        "skill_semantic_hash": SEMANTIC_HASH,
        "input_contract_ref": "contract://nex/p6/skill-execution-request/v1",
        "output_contract_ref": "contract://nex/p6/step-result/v1.2",
        "runtime_contract_ref": "contract://nex/nsl/read-runtime/v1",
        "trust_policy_id": "p6-signed-active-v1",
        "backend_profile": "NSL_V01_PROCESS_ISOLATED",
    }
    return build_local_skill_capability(**{**values, **overrides})


def _planning_inputs():
    intent = {
        "work_intent_id": INTENT_ID,
        "intent_revision": 1,
        "execution_id": EXECUTION_ID,
        "compatibility_execution_mode": "GENERAL_ANSWER",
        "goal": "Check a project budget with an exact local Skill.",
        "completion_criteria": [
            {"criterion_id": "C1", "description": "Check completes.", "required": True}
        ],
        "clarification": {"status": "NOT_REQUIRED", "reasons": [], "questions": []},
        "entity_selectors": [],
    }
    intent["intent_hash"] = semantic_sha256_hash_ref(intent)
    context = {
        "context_id": CONTEXT_ID,
        "context_generation": 1,
        "execution_id": EXECUTION_ID,
        "identity": {"tenant_id": TENANT, "subject_id": "subject-s4"},
        "runtime_policy_ref": {
            "policy_id": "p6-runtime",
            "rule_hash": semantic_sha256_hash_ref({"max_steps": 12}),
        },
        "authority_ref": "authority://oa/subject-s4/v1",
        "resolved_entities": [],
        "conflicts": [],
        "degradations": [],
    }
    context["context_hash"] = semantic_sha256_hash_ref(context)
    snapshot = build_capability_snapshot(
        tenant_id=TENANT,
        capability_snapshot_id=SNAPSHOT_ID,
        snapshot_version=1,
        created_at=NOW,
        capabilities=(*DEFAULT_P5_CAPABILITIES, _local_capability()),
    )
    plan = build_deterministic_agent_plan(
        work_intent=intent,
        agent_context=context,
        capability_snapshot=snapshot,
        agent_plan_id=PLAN_ID,
    )
    plan["steps"][0].update(
        {
            "title": "Run exact local Skill",
            "objective": "Execute deterministic NSL READ.",
            "required_capability": SKILL_ID,
            "capability_version_constraint": SKILL_VERSION,
            "output_contract_ref": "contract://nex/p6/step-result/v1.2",
        }
    )
    plan["plan_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in plan.items() if key != "plan_hash"}
    )
    validation = validate_agent_plan(
        agent_plan=plan,
        work_intent=intent,
        agent_context=context,
        capability_snapshot=snapshot,
        validation_result_id=VALIDATION_ID,
        validated_at=NOW,
    )
    return intent, context, snapshot, plan, validation


def _compiled():
    _, context, snapshot, plan, validation = _planning_inputs()
    ids = iter((STEP_ID, EXECUTABLE_PLAN_ID))
    return compile_executable_plan(
        agent_plan=plan,
        validation_result=validation,
        agent_context=context,
        capability_snapshot=snapshot,
        compiled_at=NOW,
        id_factory=lambda: next(ids),
    )


def _dependencies(**overrides):
    values = {
        "artifact_gateway": _ArtifactGateway(),
        "binding_repository": _BindingRepository(),
        "request_builder": lambda **_kwargs: {},
        "backend": _Backend(),
        "result_mapper": lambda **_kwargs: P5ExecutorOutcome(
            state="SUCCEEDED",
            result_contract_ref="contract://nex/p6/step-result/v1.2",
            result_payload={"status": "COMPLETED"},
        ),
    }
    return LocalSkillExecutorDependencies(**{**values, **overrides})


def _context(step=None):
    return StepExecutionContext(
        job={},
        attempt={},
        step=step or _compiled()["steps"][0],
        dependency_results=(),
        existing_result=None,
    )


def test_local_skill_capability_and_compiler_activate_exact_p6_contract() -> None:
    _, _, snapshot, _, validation = _planning_inputs()
    compiled = _compiled()
    step = compiled["steps"][0]

    assert snapshot["schema_version"] == "1.2"
    assert validation["status"] == "VALID"
    assert compiled["schema_version"] == "1.2"
    assert compiled["compiler_version"] == "p6.1"
    assert step["step_type"] == "LOCAL_SKILL"
    assert step["executor_kind"] == "LOCAL_SKILL"
    assert step["skill_binding"]["skill_semantic_hash"] == SEMANTIC_HASH
    assert step["skill_binding"]["package_requirement"] == "SIGNED_TRUSTED_ACTIVE"
    assert validate_executable_plan_contract(compiled) == compiled


def test_local_skill_activation_migration_is_additive_and_uses_short_names() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS skill_binding_json JSONB NULL" in sql
    assert "'LOCAL_SKILL'" in sql
    assert "2203_ae_local_skill_activation" in sql
    assert "CREATE TABLE" not in sql
    assert "ck_ae_cap_snap_json_id" in sql
    assert "ck_ae_exec_plan_json_id" in sql


def test_p5_capability_and_compiler_contract_remain_unchanged() -> None:
    intent, context, _, _, _ = _planning_inputs()
    snapshot = build_capability_snapshot(
        tenant_id=TENANT,
        capability_snapshot_id=SNAPSHOT_ID,
        snapshot_version=1,
        created_at=NOW,
    )
    plan = build_deterministic_agent_plan(
        work_intent=intent,
        agent_context=context,
        capability_snapshot=snapshot,
        agent_plan_id=PLAN_ID,
    )
    validation = validate_agent_plan(
        agent_plan=plan,
        work_intent=intent,
        agent_context=context,
        capability_snapshot=snapshot,
        validation_result_id=VALIDATION_ID,
        validated_at=NOW,
    )
    ids = iter((STEP_ID, EXECUTABLE_PLAN_ID))
    compiled = compile_executable_plan(
        agent_plan=plan,
        validation_result=validation,
        agent_context=context,
        capability_snapshot=snapshot,
        compiled_at=NOW,
        id_factory=lambda: next(ids),
    )

    assert snapshot["schema_version"] == "1.1"
    assert compiled["schema_version"] == "1.1"
    assert compiled["compiler_version"] == "p5.1"
    assert "skill_binding" not in compiled["steps"][0]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("skill_semantic_hash", "sha256:bad"),
        ("backend_profile", "IN_PROCESS"),
        ("exact_skill_version", ""),
    ],
)
def test_local_skill_capability_rejects_inexact_contract(field, value) -> None:
    with pytest.raises(CapabilitySnapshotError):
        _local_capability(**{field: value})


def test_local_skill_capability_rejects_contract_shape_and_selector_drift() -> None:
    valid = _local_capability()
    invalid_values = []
    missing_binding = {
        key: value for key, value in valid.items() if key != "local_skill_binding"
    }
    invalid_values.append(missing_binding)
    invalid_values.append({**valid, "executable_step_type": "REPORT"})
    mismatched = copy.deepcopy(valid)
    mismatched["local_skill_binding"]["skill_id"] = "FINANCE.OTHER"
    invalid_values.append(mismatched)
    invalid_values.append(
        {
            **DEFAULT_P5_CAPABILITIES[0],
            "local_skill_binding": valid["local_skill_binding"],
        }
    )
    invalid_values.append({"capability_id": SKILL_ID})
    for value in invalid_values:
        with pytest.raises(CapabilitySnapshotError):
            build_capability_snapshot(
                tenant_id=TENANT,
                capability_snapshot_id=SNAPSHOT_ID,
                snapshot_version=1,
                created_at=NOW,
                capabilities=[value],
            )

    binding = valid["local_skill_binding"]
    for changed in (
        {key: value for key, value in binding.items() if key != "trust_policy_id"},
        {**binding, "skill_id": "bad"},
        {**binding, "exact_skill_version": "bad version"},
        {**binding, "package_requirement": "UNSIGNED"},
    ):
        with pytest.raises(CapabilitySnapshotError):
            validate_local_skill_binding(changed)


def test_snapshot_and_executable_step_versions_fail_closed_on_content_drift() -> None:
    _, _, snapshot, _, _ = _planning_inputs()
    changed_snapshot = copy.deepcopy(snapshot)
    changed_snapshot["schema_version"] = "1.1"
    changed_snapshot["snapshot_hash"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in changed_snapshot.items()
            if key != "snapshot_hash"
        }
    )
    with pytest.raises(CapabilitySnapshotError, match="version"):
        validate_capability_snapshot_contract(changed_snapshot)

    compiled = _compiled()
    changed_step = copy.deepcopy(compiled)
    changed_step["steps"][0]["skill_binding"]["skill_semantic_hash"] = "bad"
    with pytest.raises(ExecutablePlanError, match="binding"):
        validate_executable_plan_contract(changed_step)

    non_local = copy.deepcopy(compiled)
    non_local["steps"][0]["executor_kind"] = "DETERMINISTIC_REPORT"
    with pytest.raises(ExecutablePlanError, match="Non-LOCAL_SKILL"):
        validate_executable_plan_contract(non_local)


def test_executable_plan_rejects_local_skill_version_and_binding_drift() -> None:
    compiled = _compiled()
    changed = copy.deepcopy(compiled)
    changed["schema_version"] = "1.1"
    with pytest.raises(ExecutablePlanError, match="version"):
        validate_executable_plan_contract(changed)

    changed = copy.deepcopy(compiled)
    changed["steps"][0]["skill_binding"]["exact_skill_version"] = "2.0.0"
    changed["steps"][0]["step_contract_hash"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in changed["steps"][0].items()
            if key not in {"executable_step_id", "step_contract_hash"}
        }
    )
    with pytest.raises(ExecutablePlanError, match="selector"):
        validate_executable_plan_contract(changed)

    changed = copy.deepcopy(compiled)
    changed["steps"][0]["step_type"] = "REPORT"
    with pytest.raises(ExecutablePlanError, match="step type"):
        validate_executable_plan_contract(changed)

    assert executable_plan_module._json_optional_object('{"skill_id":"x"}') == {
        "skill_id": "x"
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("artifact_gateway", None),
        ("binding_repository", object()),
        ("request_builder", None),
        ("backend", object()),
        ("result_mapper", None),
    ],
)
def test_local_skill_registry_fails_closed_when_dependency_is_missing(
    field, value
) -> None:
    with pytest.raises(P5StepExecutorError) as exc_info:
        default_p6_executor_registry(
            lambda _context: {},
            local_skill_dependencies=_dependencies(**{field: value}),
            local_skill_handler=lambda _context, _dependencies: P5ExecutorOutcome(
                state="SUCCEEDED",
                result_contract_ref="contract://nex/p6/step-result/v1.2",
                result_payload={},
            ),
        )
    assert exc_info.value.error_code == "ae.local_skill_dependency_unavailable"


def test_registry_worker_startup_and_local_dispatch_use_complete_dependencies() -> None:
    seen = []

    def handler(context, dependencies):
        seen.append(
            (context.step["executable_step_id"], dependencies.backend.backend_profile)
        )
        return P5ExecutorOutcome(
            state="SUCCEEDED",
            result_contract_ref="contract://nex/p6/step-result/v1.2",
            result_payload={"activation": "verified"},
        )

    registry = default_p6_executor_registry(
        lambda _context: {},
        local_skill_dependencies=_dependencies(),
        local_skill_handler=handler,
    )
    profile = build_agent_runtime_worker_profile(
        worker_id="worker-p6-s4",
        declared_at=NOW,
        supported_backend_profiles=registry.backend_profiles,
    )
    check = build_agent_runtime_worker_check(
        AgentRuntimeWorkerConfig(mode="enabled", profile=profile),
        available_executor_kinds=registry.registered_kinds,
        available_backend_profiles=registry.backend_profiles,
    )
    outcome = registry.execute(_context())

    assert check["status"] == "PASS"
    assert check["startup_ready"] is True
    assert registry.registered_kinds == (
        "DETERMINISTIC_AGGREGATE",
        "DETERMINISTIC_REPORT",
        "LOCAL_SKILL",
        "P4_CHAT_RAG_COMPATIBILITY",
    )
    assert registry.backend_profiles == ("NSL_V01_PROCESS_ISOLATED",)
    assert outcome.result_payload == {"activation": "verified"}
    assert seen == [(STEP_ID, "NSL_V01_PROCESS_ISOLATED")]


def test_local_skill_executor_rejects_registry_bypass_and_runtime_drift() -> None:
    with pytest.raises(P5StepExecutorError, match="dependency composition"):
        P5StepExecutorRegistry({"LOCAL_SKILL": object()})
    with pytest.raises(P5StepExecutorError, match="dependencies"):
        P6LocalSkillExecutor(
            dependencies=object(),  # type: ignore[arg-type]
            handler=lambda _context, _dependencies: None,
        )
    with pytest.raises(P5StepExecutorError, match="handler"):
        P6LocalSkillExecutor(dependencies=_dependencies(), handler=None)  # type: ignore[arg-type]

    executor = P6LocalSkillExecutor(
        dependencies=_dependencies(),
        handler=lambda _context, _dependencies: P5ExecutorOutcome(
            state="SUCCEEDED",
            result_contract_ref="contract://nex/p6/step-result/v1.2",
            result_payload={},
        ),
    )
    step = copy.deepcopy(_compiled()["steps"][0])
    step["step_type"] = "REPORT"
    with pytest.raises(P5StepExecutorError, match="step"):
        executor.execute(_context(step))

    with pytest.raises(P5StepExecutorError, match="continuation"):
        executor.execute(_context(), continuation_result={})

    resumed = P5ExecutorOutcome(
        state="SUCCEEDED",
        result_contract_ref="contract://nex/p6/step-result/v1.2",
        result_payload={"resumed": True},
    )
    observed: list[object] = []
    resumable = P6LocalSkillExecutor(
        dependencies=_dependencies(),
        handler=lambda _context, _dependencies: (_ for _ in ()).throw(AssertionError),
        continuation_handler=lambda _context, _dependencies, continuation: (
            observed.append(continuation) or resumed
        ),
    )
    continuation = {"schema_version": "ae_nsl_approval_resume_authority.v1"}
    assert resumable.execute(_context(), continuation_result=continuation) is resumed
    assert observed == [continuation]

    invalid_binding = copy.deepcopy(_compiled()["steps"][0])
    invalid_binding["skill_binding"]["backend_profile"] = "IN_PROCESS"
    with pytest.raises(P5StepExecutorError, match="compiled binding") as exc_info:
        executor.execute(_context(invalid_binding))
    assert exc_info.value.error_code == "ae.p5_executor_invalid"

    wrong_backend = replace(
        _dependencies(),
        backend=type(
            "OtherBackend",
            (),
            {"backend_profile": "OTHER", "execute": lambda self, value: value},
        )(),
    )
    with pytest.raises(P5StepExecutorError, match="backend profile"):
        P6LocalSkillExecutor(
            dependencies=wrong_backend,
            handler=lambda _context, _dependencies: None,
        )


def test_local_skill_executor_rejects_invalid_handler_outcome() -> None:
    executor = P6LocalSkillExecutor(
        dependencies=_dependencies(),
        handler=lambda _context, _dependencies: None,
    )
    with pytest.raises(P5StepExecutorError, match="invalid outcome"):
        executor.execute(_context())
