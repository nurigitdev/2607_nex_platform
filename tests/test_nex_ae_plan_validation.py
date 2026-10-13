from __future__ import annotations

import json
from pathlib import Path

import nex_ae_api.plan_validation as module
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api.agent_plans import build_deterministic_agent_plan
from nex_ae_api.plan_validation import (
    MAX_AUTO_REPLAN,
    RUNTIME_OUTCOMES,
    PlanValidationError,
    SqlAlchemyPlanValidationRepository,
    build_plan_validation_result,
    runtime_outcome_for_status,
    validate_agent_plan,
    validate_plan_validation_result,
)
from nex_ae_api.planning_capabilities import build_capability_snapshot
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (
    ROOT / "docs/transition/P5/contracts/p5-plan-validation-result-v1.1.schema.json"
)
TENANT = "tenant-p5"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
INTENT_ID = "22222222-2222-4222-8222-222222222222"
CONTEXT_ID = "33333333-3333-4333-8333-333333333333"
SNAPSHOT_ID = "44444444-4444-4444-8444-444444444444"
PLAN_ID = "55555555-5555-4555-8555-555555555555"
VALIDATION_ID = "66666666-6666-4666-8666-666666666666"
NOW = "2026-10-13T10:00:00Z"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _work_intent(mode="GROUNDED_ANSWER"):
    return {
        "work_intent_id": INTENT_ID,
        "intent_revision": 1,
        "intent_hash": HASH_A,
        "execution_id": EXECUTION_ID,
        "compatibility_execution_mode": mode,
        "goal": "Answer the private user request through the compatibility path.",
        "completion_criteria": [
            {"criterion_id": "C1", "description": "Answer is available.", "required": True}
        ],
        "clarification": {"status": "NOT_REQUIRED", "reasons": [], "questions": []},
        "entity_selectors": [],
    }


def _context():
    return {
        "context_id": CONTEXT_ID,
        "context_generation": 1,
        "context_hash": HASH_B,
        "execution_id": EXECUTION_ID,
        "identity": {"tenant_id": TENANT},
        "resolved_entities": [],
        "conflicts": [],
        "degradations": [],
    }


def _snapshot():
    return build_capability_snapshot(
        tenant_id=TENANT,
        capability_snapshot_id=SNAPSHOT_ID,
        snapshot_version=1,
        created_at=NOW,
    )


def _plan(mode="GROUNDED_ANSWER"):
    return build_deterministic_agent_plan(
        work_intent=_work_intent(mode),
        agent_context=_context(),
        capability_snapshot=_snapshot(),
        agent_plan_id=PLAN_ID,
    )


def _validate(*, plan=None, intent=None, context=None, snapshot=None):
    return validate_agent_plan(
        agent_plan=plan or _plan(),
        work_intent=intent or _work_intent(),
        agent_context=context or _context(),
        capability_snapshot=snapshot or _snapshot(),
        validation_result_id=VALIDATION_ID,
        validated_at=NOW,
    )


def _rehash_plan(plan):
    plan["plan_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in plan.items() if key != "plan_hash"}
    )
    return plan


def _factory(*, with_schema=True, seed=True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if with_schema:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE ae_agent_execution (
                    tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                    state TEXT NOT NULL, phase TEXT NOT NULL,
                    version INTEGER NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, agent_execution_id)
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_agent_context (
                    tenant_id TEXT NOT NULL, context_id TEXT NOT NULL,
                    context_generation INTEGER NOT NULL,
                    agent_execution_id TEXT NOT NULL, context_hash TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, context_id)
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_agent_plan (
                    tenant_id TEXT NOT NULL, agent_plan_id TEXT NOT NULL,
                    agent_plan_version INTEGER NOT NULL,
                    agent_execution_id TEXT NOT NULL,
                    agent_context_id TEXT NOT NULL, plan_hash TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, agent_plan_id)
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_plan_validation (
                    tenant_id TEXT NOT NULL, validation_result_id TEXT NOT NULL,
                    agent_plan_id TEXT NOT NULL, agent_plan_version INTEGER NOT NULL,
                    agent_execution_id TEXT NOT NULL, status TEXT NOT NULL,
                    runtime_directive TEXT NOT NULL, result_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL, validated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, validation_result_id)
                )
            """))
            if seed:
                plan = _plan()
                context = _context()
                connection.execute(
                    text("INSERT INTO ae_agent_execution VALUES (:t, :e, 'QUEUED', 'INTAKE', 1, :now)"),
                    {"t": TENANT, "e": EXECUTION_ID, "now": NOW},
                )
                connection.execute(
                    text("INSERT INTO ae_agent_context VALUES (:t, :c, 1, :e, :h)"),
                    {"t": TENANT, "c": CONTEXT_ID, "e": EXECUTION_ID, "h": context["context_hash"]},
                )
                connection.execute(
                    text("INSERT INTO ae_agent_plan VALUES (:t, :p, 1, :e, :c, :h)"),
                    {
                        "t": TENANT,
                        "p": PLAN_ID,
                        "e": EXECUTION_ID,
                        "c": CONTEXT_ID,
                        "h": plan["plan_hash"],
                    },
                )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _rehash_result(result):
    result["result_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in result.items() if key != "result_hash"}
    )
    return result


def _result(status="VALID"):
    return build_plan_validation_result(
        agent_plan=_plan(),
        agent_context=_context(),
        status=status,
        issues=(
            []
            if status == "VALID"
            else [
                {
                    "code": f"{status}_TEST",
                    "severity": "WARNING",
                    "message": "Deterministic test outcome.",
                }
            ]
        ),
        topological_step_order=["S1", "S2"],
        validation_result_id=VALIDATION_ID,
        validated_at=NOW,
    )


def test_valid_plan_produces_contract_valid_compile_authority() -> None:
    result = _validate()
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)

    assert result["status"] == "VALID"
    assert result["runtime_directive"] == "PROCEED_TO_COMPILE"
    assert result["topological_step_order"] == ["S1", "S2"]
    assert result["issues"] == []
    assert result["result_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    ("status", "directive", "state", "phase", "compile_allowed"),
    [
        ("VALID", "PROCEED_TO_COMPILE", "RUNNING", "PLAN_COMPILE", True),
        ("CLARIFICATION_REQUIRED", "WAIT_FOR_INPUT", "WAITING_INPUT", "PLAN_VALIDATE", False),
        ("REPLAN_REQUIRED", "BLOCK_REPLAN_REQUIRED", "BLOCKED", "PLAN_VALIDATE", False),
        ("CONTEXT_REFRESH_REQUIRED", "BLOCK_CONTEXT_REFRESH_REQUIRED", "BLOCKED", "PLAN_VALIDATE", False),
        ("BLOCKED", "BLOCK_EXECUTION", "BLOCKED", "PLAN_VALIDATE", False),
        ("INVALID_TERMINAL", "FAIL_VALIDATION", "FAILED", "PLAN_VALIDATE", False),
        ("RETRYABLE_VALIDATION_FAILURE", "RETRY_VALIDATION_BOUNDED", "RUNNING", "PLAN_VALIDATE", False),
    ],
)
def test_exact_runtime_mapping_has_zero_automatic_replan(
    status, directive, state, phase, compile_allowed
) -> None:
    outcome = runtime_outcome_for_status(status)
    result = _result(status)

    assert result["runtime_directive"] == directive
    assert outcome.agent_execution_state == state
    assert outcome.agent_execution_phase == phase
    assert outcome.compile_allowed is compile_allowed
    assert outcome.auto_replan_allowed is False
    assert MAX_AUTO_REPLAN == 0


def test_validator_maps_clarification_replan_refresh_and_blocked_states() -> None:
    clarification = _work_intent()
    clarification["clarification"] = {
        "status": "REQUIRED",
        "reasons": ["MISSING_REQUIRED_PARAMETER"],
        "questions": ["Which document should be used?"],
    }
    assert _validate(intent=clarification)["status"] == "CLARIFICATION_REQUIRED"

    changed_intent = _work_intent()
    changed_intent["intent_hash"] = "sha256:" + "c" * 64
    assert _validate(intent=changed_intent)["status"] == "REPLAN_REQUIRED"

    changed_context = _context()
    changed_context["context_hash"] = "sha256:" + "c" * 64
    assert _validate(context=changed_context)["status"] == "CONTEXT_REFRESH_REQUIRED"

    blocked_context = _context()
    blocked_context["conflicts"] = ["Two authoritative owners disagree."]
    assert _validate(context=blocked_context)["status"] == "BLOCKED"


def test_validator_maps_execution_and_graph_failures_to_terminal_invalid() -> None:
    wrong_execution = _work_intent()
    wrong_execution["execution_id"] = VALIDATION_ID
    assert _validate(intent=wrong_execution)["status"] == "INVALID_TERMINAL"

    context_execution = _context()
    context_execution["execution_id"] = VALIDATION_ID
    assert _validate(context=context_execution)["status"] == "INVALID_TERMINAL"

    cyclic = _plan()
    cyclic["steps"][0]["depends_on"] = ["S2"]
    _rehash_plan(cyclic)
    terminal = _validate(plan=cyclic)
    assert terminal["status"] == "INVALID_TERMINAL"
    assert terminal["issues"][0]["code"] == "PLAN_DEPENDENCY_CYCLE"


def test_validator_checks_required_entities_and_exact_snapshot() -> None:
    intent = _work_intent()
    intent["entity_selectors"] = [
        {
            "selector_id": "E1",
            "entity_type": "DOCUMENT",
            "raw_text": "the report",
            "required": True,
            "confidence": 0.8,
        }
    ]
    assert _validate(intent=intent)["status"] == "CONTEXT_REFRESH_REQUIRED"

    snapshot = _snapshot()
    snapshot["snapshot_version"] = 2
    snapshot["snapshot_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    )
    assert _validate(snapshot=snapshot)["status"] == "REPLAN_REQUIRED"


def test_validator_blocks_future_profiles_and_unavailable_executors() -> None:
    dynamic = _plan()
    dynamic["plan_kind"] = "DYNAMIC"
    dynamic["planner_provenance"]["builder_type"] = "DYNAMIC_BUILDER"
    _rehash_plan(dynamic)
    assert _validate(plan=dynamic)["status"] == "BLOCKED"

    delegated = _plan("GENERAL_ANSWER")
    delegated["steps"][0]["step_type"] = "DELEGATE_WORK"
    _rehash_plan(delegated)
    result = _validate(plan=delegated, intent=_work_intent("GENERAL_ANSWER"))
    assert result["status"] == "BLOCKED"
    assert result["issues"][0]["code"] == "EXECUTOR_NOT_AVAILABLE"


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (
            lambda plan: plan["completion_criteria"][0].update(
                required_terminal_step_refs=["S1"]
            ),
            "INVALID_TERMINAL_STEP_REF",
        ),
        (
            lambda plan: plan["steps"][0].update(
                input_bindings=[
                    {
                        "target_name": "future",
                        "source_type": "STEP_OUTPUT",
                        "source_ref": "S2",
                    }
                ]
            ),
            "INVALID_STEP_OUTPUT_BINDING",
        ),
        (lambda plan: plan["steps"][1].update(report=None), "REPORT_CONTRACT_MISSING"),
        (
            lambda plan: plan["steps"][1]["report"].update(
                source_step_refs=["S9"]
            ),
            "REPORT_SOURCE_MISSING",
        ),
    ],
)
def test_validator_rejects_invalid_plan_semantics(mutator, code) -> None:
    plan = _plan()
    mutator(plan)
    _rehash_plan(plan)

    result = _validate(plan=plan)

    assert result["status"] == "INVALID_TERMINAL"
    assert result["issues"][0]["code"] == code


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (
            lambda plan: plan["steps"][0].update(
                capability_version_constraint="p5.2"
            ),
            "CAPABILITY_VERSION_UNAVAILABLE",
        ),
        (
            lambda plan: plan["steps"][0].update(
                output_contract_ref="contract://wrong/v1"
            ),
            "CAPABILITY_OUTPUT_CONTRACT_MISMATCH",
        ),
        (
            lambda plan: plan["steps"][0].update(
                step_type="AGGREGATE",
                required_capability=None,
                capability_version_constraint=None,
                aggregation={"mode": "DETERMINISTIC", "source_step_refs": ["S1"]},
            ),
            "CAPABILITY_VERSION_UNAVAILABLE",
        ),
    ],
)
def test_validator_requires_exact_available_capability_contract(mutator, code) -> None:
    plan = _plan("GENERAL_ANSWER")
    mutator(plan)
    _rehash_plan(plan)

    result = _validate(plan=plan, intent=_work_intent("GENERAL_ANSWER"))

    assert result["status"] == "REPLAN_REQUIRED"
    assert result["issues"][0]["code"] == code


def test_context_degradation_is_warning_and_does_not_block_compile() -> None:
    context = _context()
    context["degradations"] = ["Optional evidence unavailable."]

    result = _validate(context=context)

    assert result["status"] == "VALID"
    assert result["issues"][0]["severity"] == "WARNING"


@pytest.mark.parametrize("status", list(RUNTIME_OUTCOMES))
def test_repository_atomically_persists_and_applies_each_runtime_mapping(status) -> None:
    factory = _factory()
    repository = SqlAlchemyPlanValidationRepository(factory)
    result = _result(status)

    assert repository.get(tenant_id=TENANT, validation_result_id=VALIDATION_ID) is None
    assert repository.save_and_apply_runtime(
        tenant_id=TENANT, result=result, expected_execution_version=1
    ) == result
    assert repository.save_and_apply_runtime(
        tenant_id=TENANT, result=result, expected_execution_version=1
    ) == result

    with factory() as session:
        execution = session.execute(
            text("SELECT state, phase, version FROM ae_agent_execution")
        ).mappings().one()
        row_count = session.execute(text("SELECT count(*) FROM ae_plan_validation")).scalar_one()
    outcome = runtime_outcome_for_status(status)
    assert dict(execution) == {
        "state": outcome.agent_execution_state,
        "phase": outcome.agent_execution_phase,
        "version": 2,
    }
    assert row_count == 1
    assert (
        SqlAlchemyPlanValidationRepository(factory).get(
            tenant_id=TENANT, validation_result_id=VALIDATION_ID
        )
        == result
    )


def test_repository_rolls_back_on_execution_version_conflict() -> None:
    factory = _factory()
    repository = SqlAlchemyPlanValidationRepository(factory)

    with pytest.raises(PlanValidationError) as exc_info:
        repository.save_and_apply_runtime(
            tenant_id=TENANT, result=_result(), expected_execution_version=2
        )
    assert exc_info.value.error_code == "ae.plan_validation_execution_version_conflict"
    assert exc_info.value.retryable is True

    with factory() as session:
        assert session.execute(text("SELECT count(*) FROM ae_plan_validation")).scalar_one() == 0
        assert session.execute(text("SELECT version FROM ae_agent_execution")).scalar_one() == 1


def test_repository_rejects_missing_execution_and_exact_lineage_mismatch() -> None:
    missing_factory = _factory()
    with missing_factory.begin() as session:
        session.execute(text("DELETE FROM ae_agent_execution"))
    with pytest.raises(PlanValidationError) as missing:
        SqlAlchemyPlanValidationRepository(missing_factory).save_and_apply_runtime(
            tenant_id=TENANT, result=_result(), expected_execution_version=1
        )
    assert missing.value.error_code == "ae.plan_validation_execution_not_found"

    mismatch_factory = _factory()
    with mismatch_factory.begin() as session:
        session.execute(text("UPDATE ae_agent_plan SET plan_hash = 'sha256:' || printf('%064d', 0)"))
    with pytest.raises(PlanValidationError) as mismatch:
        SqlAlchemyPlanValidationRepository(mismatch_factory).save_and_apply_runtime(
            tenant_id=TENANT, result=_result(), expected_execution_version=1
        )
    assert mismatch.value.error_code == "ae.plan_validation_lineage_mismatch"


def test_repository_rejects_immutable_conflict_and_store_failure(monkeypatch) -> None:
    factory = _factory()
    repository = SqlAlchemyPlanValidationRepository(factory)
    repository.save_and_apply_runtime(
        tenant_id=TENANT, result=_result(), expected_execution_version=1
    )
    changed = _result("BLOCKED")
    with pytest.raises(PlanValidationError) as immutable:
        repository.save_and_apply_runtime(
            tenant_id=TENANT, result=changed, expected_execution_version=2
        )
    assert immutable.value.error_code == "ae.plan_validation_immutable_conflict"

    unavailable = SqlAlchemyPlanValidationRepository(_factory(with_schema=False))
    with pytest.raises(PlanValidationError) as save_error:
        unavailable.save_and_apply_runtime(
            tenant_id=TENANT, result=_result(), expected_execution_version=1
        )
    assert save_error.value.error_code == "ae.plan_validation_store_unavailable"
    with pytest.raises(PlanValidationError) as get_error:
        unavailable.get(tenant_id=TENANT, validation_result_id=VALIDATION_ID)
    assert get_error.value.error_code == "ae.plan_validation_store_unavailable"

    monkeypatch.setattr(module, "_load_validation", lambda *args: None)
    with pytest.raises(PlanValidationError) as conflict:
        SqlAlchemyPlanValidationRepository(_factory()).save_and_apply_runtime(
            tenant_id=TENANT, result=_result(), expected_execution_version=1
        )
    assert conflict.value.error_code == "ae.plan_validation_write_conflict"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(schema_version="1.0"),
        lambda value: value.update(validation_result_id="bad"),
        lambda value: value["agent_plan_ref"].update(version=0),
        lambda value: value.update(status="UNKNOWN"),
        lambda value: value.update(runtime_directive="BLOCK_EXECUTION"),
        lambda value: value.update(issues="bad"),
        lambda value: value.update(topological_step_order=["S1", "S1"]),
        lambda value: value.update(validated_at="2026-10-13"),
        lambda value: value.update(result_hash="bad"),
        lambda value: value.update(private=True),
    ],
)
def test_result_contract_validator_fails_closed(mutator) -> None:
    result = _result()
    mutator(result)
    if result.get("result_hash") != "bad":
        try:
            _rehash_result(result)
        except (TypeError, ValueError):
            pass
    with pytest.raises(PlanValidationError):
        validate_plan_validation_result(result)


def test_result_builder_rejects_invalid_issue_and_status_combinations() -> None:
    kwargs = {
        "agent_plan": _plan(),
        "agent_context": _context(),
        "topological_step_order": ["S1", "S2"],
        "validation_result_id": VALIDATION_ID,
        "validated_at": NOW,
    }
    with pytest.raises(PlanValidationError):
        build_plan_validation_result(status="BLOCKED", issues=[], **kwargs)
    with pytest.raises(PlanValidationError):
        build_plan_validation_result(
            status="VALID",
            issues=[{"code": "BAD_PLAN", "severity": "ERROR", "message": "bad"}],
            **kwargs,
        )
    with pytest.raises(PlanValidationError):
        build_plan_validation_result(
            status="BLOCKED",
            issues=[{"code": "bad", "severity": "WARNING", "message": "bad"}],
            **kwargs,
        )
    with pytest.raises(PlanValidationError):
        runtime_outcome_for_status("UNKNOWN")


def test_validation_error_string_and_default_identity_factories() -> None:
    error = PlanValidationError("code", "detail")
    assert str(error) == "detail"

    result = validate_agent_plan(
        agent_plan=_plan(),
        work_intent=_work_intent(),
        agent_context=_context(),
        capability_snapshot=_snapshot(),
        id_factory=lambda: VALIDATION_ID,
        clock=lambda: module.datetime.fromisoformat(NOW.replace("Z", "+00:00")),
    )
    assert result["validation_result_id"] == VALIDATION_ID
    assert result["validated_at"] == NOW


def test_validator_rejects_duplicate_and_missing_dependencies() -> None:
    duplicate = _plan()
    duplicate["steps"][1]["step_id"] = "S1"
    duplicate["completion_criteria"][0]["required_terminal_step_refs"] = ["S1"]
    _rehash_plan(duplicate)
    duplicate_result = _validate(plan=duplicate)
    assert duplicate_result["status"] == "INVALID_TERMINAL"
    assert duplicate_result["issues"][0]["code"] == "DUPLICATE_STEP_ID"

    missing = _plan()
    missing["steps"][1]["depends_on"] = ["S9"]
    _rehash_plan(missing)
    missing_result = _validate(plan=missing)
    assert missing_result["status"] == "INVALID_TERMINAL"
    assert missing_result["issues"][0]["code"] == "INVALID_STEP_DEPENDENCY"


def test_validator_allows_non_step_binding_and_detects_more_capability_gaps() -> None:
    literal = _plan()
    literal["steps"][0]["input_bindings"] = [
        {
            "target_name": "request",
            "source_type": "LITERAL",
            "literal_value": {"safe": True},
        }
    ]
    _rehash_plan(literal)
    assert _validate(plan=literal)["status"] == "VALID"

    missing_binding = _plan("GENERAL_ANSWER")
    missing_binding["steps"][0]["required_capability"] = None
    missing_binding["steps"][0]["capability_version_constraint"] = None
    _rehash_plan(missing_binding)
    assert _validate(
        plan=missing_binding, intent=_work_intent("GENERAL_ANSWER")
    )["issues"][0]["code"] == "CAPABILITY_BINDING_MISSING"

    snapshot = _snapshot()
    snapshot["capabilities"] = [snapshot["capabilities"][0]]
    snapshot["snapshot_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    )
    report_plan = _plan()
    report_plan["capability_snapshot_ref"]["hash"] = snapshot["snapshot_hash"]
    _rehash_plan(report_plan)
    report_result = _validate(plan=report_plan, snapshot=snapshot)
    assert report_result["issues"][0]["code"] == "CAPABILITY_VERSION_UNAVAILABLE"

    type_snapshot = _snapshot()
    type_snapshot["capabilities"][0]["allowed_logical_step_types"] = ["REPORT"]
    type_snapshot["snapshot_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in type_snapshot.items() if key != "snapshot_hash"}
    )
    type_plan = _plan("GENERAL_ANSWER")
    type_plan["capability_snapshot_ref"]["hash"] = type_snapshot["snapshot_hash"]
    _rehash_plan(type_plan)
    type_result = _validate(
        plan=type_plan,
        intent=_work_intent("GENERAL_ANSWER"),
        snapshot=type_snapshot,
    )
    assert type_result["issues"][0]["code"] == "CAPABILITY_STEP_TYPE_MISMATCH"


@pytest.mark.parametrize(
    "issue",
    [
        {"code": "VALID_CODE", "severity": "BAD", "message": "bad"},
        {
            "code": "VALID_CODE",
            "severity": "WARNING",
            "message": "bad",
            "step_id": "bad",
        },
        {"code": "VALID_CODE", "severity": "WARNING"},
    ],
)
def test_issue_validator_rejects_malformed_optional_fields(issue) -> None:
    with pytest.raises(PlanValidationError):
        build_plan_validation_result(
            agent_plan=_plan(),
            agent_context=_context(),
            status="BLOCKED",
            issues=[issue],
            topological_step_order=["S1", "S2"],
            validation_result_id=VALIDATION_ID,
            validated_at=NOW,
        )


def test_result_validator_rejects_semantic_combinations_and_hash_tamper() -> None:
    valid_error = _result()
    valid_error["issues"] = [
        {"code": "VALID_ERROR", "severity": "ERROR", "message": "bad"}
    ]
    _rehash_result(valid_error)
    with pytest.raises(PlanValidationError, match="ERROR"):
        validate_plan_validation_result(valid_error)

    empty_block = _result()
    empty_block["status"] = "BLOCKED"
    empty_block["runtime_directive"] = "BLOCK_EXECUTION"
    _rehash_result(empty_block)
    with pytest.raises(PlanValidationError, match="at least one issue"):
        validate_plan_validation_result(empty_block)

    tampered = _result()
    tampered["validator_version"] = "tampered"
    with pytest.raises(PlanValidationError, match="does not match"):
        validate_plan_validation_result(tampered)

    nan_result = _result()
    nan_result["issues"][0:0] = []
    nan_result["validator_version"] = float("nan")
    with pytest.raises(PlanValidationError, match="canonical JSON"):
        validate_plan_validation_result(nan_result)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(agent_plan_ref="bad"),
        lambda value: value["agent_plan_ref"].update(hash="bad"),
        lambda value: value.update(execution_id=None),
        lambda value: value.update(validator_version=""),
        lambda value: value.update(validated_at=None),
        lambda value: value.update(validated_at="not-a-date"),
    ],
)
def test_result_validator_rejects_invalid_primitives(mutator) -> None:
    result = _result()
    mutator(result)
    try:
        _rehash_result(result)
    except (TypeError, ValueError):
        pass
    with pytest.raises(PlanValidationError):
        validate_plan_validation_result(result)
