from __future__ import annotations

import copy
import json
from pathlib import Path

import nex_ae_api.executable_plans as module
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api.agent_plans import build_deterministic_agent_plan
from nex_ae_api.executable_plans import (
    ExecutablePlanError,
    SqlAlchemyExecutablePlanRepository,
    compile_executable_plan,
    validate_executable_plan_contract,
)
from nex_ae_api.plan_validation import build_plan_validation_result
from nex_ae_api.planning_capabilities import build_capability_snapshot
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "docs/transition/P5/contracts/p5-executable-plan-v1.1.schema.json"
TENANT = "tenant-p5"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
INTENT_ID = "22222222-2222-4222-8222-222222222222"
CONTEXT_ID = "33333333-3333-4333-8333-333333333333"
SNAPSHOT_ID = "44444444-4444-4444-8444-444444444444"
PLAN_ID = "55555555-5555-4555-8555-555555555555"
VALIDATION_ID = "66666666-6666-4666-8666-666666666666"
EXECUTABLE_PLAN_ID = "77777777-7777-4777-8777-777777777777"
STEP_1_ID = "88888888-8888-4888-8888-888888888888"
STEP_2_ID = "99999999-9999-4999-8999-999999999999"
NOW = "2026-10-14T09:00:00Z"


def _work_intent(mode: str = "GROUNDED_ANSWER") -> dict[str, object]:
    value: dict[str, object] = {
        "work_intent_id": INTENT_ID,
        "intent_revision": 1,
        "execution_id": EXECUTION_ID,
        "compatibility_execution_mode": mode,
        "goal": "Answer through the private compatibility path.",
        "completion_criteria": [
            {
                "criterion_id": "C1",
                "description": "Answer is available.",
                "required": True,
            }
        ],
        "clarification": {"status": "NOT_REQUIRED", "reasons": [], "questions": []},
        "entity_selectors": [],
    }
    value["intent_hash"] = semantic_sha256_hash_ref(value)
    return value


def _context() -> dict[str, object]:
    value: dict[str, object] = {
        "context_id": CONTEXT_ID,
        "context_generation": 1,
        "execution_id": EXECUTION_ID,
        "identity": {"tenant_id": TENANT, "subject_id": "subject-1"},
        "runtime_policy_ref": {
            "policy_id": "p5-runtime",
            "rule_hash": semantic_sha256_hash_ref({"max_steps": 12}),
        },
        "authority_ref": "authority://oa/subject-1/v1",
        "resolved_entities": [],
        "conflicts": [],
        "degradations": [],
    }
    value["context_hash"] = semantic_sha256_hash_ref(value)
    return value


def _snapshot() -> dict[str, object]:
    return build_capability_snapshot(
        tenant_id=TENANT,
        capability_snapshot_id=SNAPSHOT_ID,
        snapshot_version=1,
        created_at=NOW,
    )


def _planning_inputs(
    mode: str = "GROUNDED_ANSWER",
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    intent = _work_intent(mode)
    context = _context()
    snapshot = _snapshot()
    plan = build_deterministic_agent_plan(
        work_intent=intent,
        agent_context=context,
        capability_snapshot=snapshot,
        agent_plan_id=PLAN_ID,
    )
    validation = build_plan_validation_result(
        agent_plan=plan,
        agent_context=context,
        status="VALID",
        issues=[],
        topological_step_order=[step["step_id"] for step in plan["steps"]],
        validation_result_id=VALIDATION_ID,
        validated_at=NOW,
    )
    return intent, context, snapshot, plan, validation


def _compiled(
    *,
    ids: tuple[str, ...] = (STEP_1_ID, STEP_2_ID, EXECUTABLE_PLAN_ID),
    compiled_at: str = NOW,
    mode: str = "GROUNDED_ANSWER",
) -> dict[str, object]:
    _, context, snapshot, plan, validation = _planning_inputs(mode)
    generated = iter(ids)
    return compile_executable_plan(
        agent_plan=plan,
        validation_result=validation,
        agent_context=context,
        capability_snapshot=snapshot,
        compiled_at=compiled_at,
        id_factory=lambda: next(generated),
    )


def _factory(*, schema: bool = True, seed: bool = True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if schema:
        with engine.begin() as connection:
            for ddl in (
                """CREATE TABLE ae_agent_execution (
                    tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                    state TEXT NOT NULL, phase TEXT NOT NULL, version INTEGER NOT NULL,
                    legacy_interaction_id TEXT, correlation_id TEXT NOT NULL,
                    causation_id TEXT, PRIMARY KEY (tenant_id, agent_execution_id))""",
                """CREATE TABLE ae_work_intent (
                    tenant_id TEXT NOT NULL, work_intent_id TEXT NOT NULL,
                    intent_revision INTEGER NOT NULL, intent_hash TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, work_intent_id))""",
                """CREATE TABLE ae_agent_context (
                    tenant_id TEXT NOT NULL, context_id TEXT NOT NULL,
                    context_generation INTEGER NOT NULL, context_hash TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, context_id))""",
                """CREATE TABLE ae_capability_snapshot (
                    tenant_id TEXT NOT NULL, capability_snapshot_id TEXT NOT NULL,
                    snapshot_version INTEGER NOT NULL, snapshot_hash TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, capability_snapshot_id))""",
                """CREATE TABLE ae_agent_plan (
                    tenant_id TEXT NOT NULL, agent_plan_id TEXT NOT NULL,
                    agent_plan_version INTEGER NOT NULL, plan_hash TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, agent_plan_id))""",
                """CREATE TABLE ae_plan_validation (
                    tenant_id TEXT NOT NULL, validation_result_id TEXT NOT NULL,
                    agent_plan_id TEXT NOT NULL, agent_plan_version INTEGER NOT NULL,
                    agent_execution_id TEXT NOT NULL, status TEXT NOT NULL,
                    runtime_directive TEXT NOT NULL, result_hash TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, validation_result_id))""",
                """CREATE TABLE ae_executable_plan (
                    tenant_id TEXT NOT NULL, executable_plan_id TEXT NOT NULL,
                    executable_plan_version INTEGER NOT NULL, agent_execution_id TEXT NOT NULL,
                    agent_plan_id TEXT NOT NULL, agent_plan_version INTEGER NOT NULL,
                    validation_result_id TEXT NOT NULL, compiler_version TEXT NOT NULL,
                    plan_hash TEXT NOT NULL, plan_json TEXT NOT NULL, compiled_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, executable_plan_id),
                    UNIQUE (tenant_id, agent_execution_id, executable_plan_version))""",
                """CREATE TABLE ae_executable_step (
                    tenant_id TEXT NOT NULL, executable_step_id TEXT NOT NULL,
                    agent_execution_id TEXT NOT NULL, step_kind TEXT NOT NULL, state TEXT NOT NULL,
                    version INTEGER NOT NULL, legacy_interaction_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL, causation_id TEXT,
                    executable_plan_id TEXT, logical_step_id TEXT, compiled_step_key TEXT,
                    step_index INTEGER, step_type TEXT, executor_kind TEXT,
                    required_capability TEXT, capability_version TEXT,
                    dependency_json TEXT, input_binding_json TEXT, skill_binding_json TEXT,
                    output_contract_ref TEXT,
                    step_contract_hash TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, executable_step_id),
                    UNIQUE (tenant_id, executable_plan_id, compiled_step_key))""",
            ):
                connection.execute(text(ddl))
            if seed:
                _seed(connection)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _seed(connection) -> None:
    intent, context, snapshot, plan, validation = _planning_inputs()
    connection.execute(
        text(
            "INSERT INTO ae_agent_execution VALUES (:t, :e, 'RUNNING', 'PLAN_COMPILE', 5, :i, :c, :a)"
        ),
        {
            "t": TENANT,
            "e": EXECUTION_ID,
            "i": "interaction-1",
            "c": "corr-1",
            "a": "cause-1",
        },
    )
    connection.execute(
        text("INSERT INTO ae_work_intent VALUES (:t, :i, 1, :h)"),
        {"t": TENANT, "i": INTENT_ID, "h": intent["intent_hash"]},
    )
    connection.execute(
        text("INSERT INTO ae_agent_context VALUES (:t, :i, 1, :h)"),
        {"t": TENANT, "i": CONTEXT_ID, "h": context["context_hash"]},
    )
    connection.execute(
        text("INSERT INTO ae_capability_snapshot VALUES (:t, :i, 1, :h)"),
        {"t": TENANT, "i": SNAPSHOT_ID, "h": snapshot["snapshot_hash"]},
    )
    connection.execute(
        text("INSERT INTO ae_agent_plan VALUES (:t, :i, 1, :h)"),
        {"t": TENANT, "i": PLAN_ID, "h": plan["plan_hash"]},
    )
    connection.execute(
        text("""INSERT INTO ae_plan_validation VALUES (
            :t, :i, :p, 1, :e, 'VALID', 'PROCEED_TO_COMPILE', :h)"""),
        {
            "t": TENANT,
            "i": VALIDATION_ID,
            "p": PLAN_ID,
            "e": EXECUTION_ID,
            "h": validation["result_hash"],
        },
    )


def _rehash_plan(plan: dict[str, object]) -> dict[str, object]:
    plan["plan_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in plan.items() if key != "plan_hash"}
    )
    return plan


def _rehash_validation(result: dict[str, object]) -> dict[str, object]:
    result["result_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in result.items() if key != "result_hash"}
    )
    return result


def _rehash_step(step: dict[str, object]) -> None:
    step["step_contract_hash"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in step.items()
            if key not in {"executable_step_id", "step_contract_hash"}
        }
    )


def _binding(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "target_name": "source_result",
        "binding_type": "COMPILED_STEP_OUTPUT",
        "source_ref": "E1:$",
    }
    value.update(overrides)
    value["binding_hash"] = semantic_sha256_hash_ref(value)
    return value


def test_compiler_emits_contract_valid_s_key_e_key_uuid_lineage() -> None:
    compiled = _compiled()
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(compiled)

    assert [step["logical_step_ref"] for step in compiled["steps"]] == ["S1", "S2"]
    assert [step["compiled_step_key"] for step in compiled["steps"]] == ["E1", "E2"]
    assert [step["executable_step_id"] for step in compiled["steps"]] == [
        STEP_1_ID,
        STEP_2_ID,
    ]
    assert compiled["steps"][1]["depends_on_compiled_step_keys"] == ["E1"]
    assert compiled["logical_step_mapping"][1] == {
        "logical_step_id": "S2",
        "compiled_step_keys": ["E2"],
        "executable_step_ids": [STEP_2_ID],
    }
    assert compiled["steps"][0]["executor_kind"] == "P4_CHAT_RAG_COMPATIBILITY"
    assert compiled["steps"][1]["executor_kind"] == "DETERMINISTIC_REPORT"


def test_semantic_hashes_ignore_generated_uuid_and_compilation_time() -> None:
    first = _compiled()
    second = _compiled(
        ids=(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        ),
        compiled_at="2026-10-14T10:30:00+09:00",
    )

    assert first["executable_plan_id"] != second["executable_plan_id"]
    assert first["compiled_at"] != second["compiled_at"]
    assert [step["executable_step_id"] for step in first["steps"]] != [
        step["executable_step_id"] for step in second["steps"]
    ]
    assert [step["compiled_step_key"] for step in first["steps"]] == ["E1", "E2"]
    assert [step["step_contract_hash"] for step in first["steps"]] == [
        step["step_contract_hash"] for step in second["steps"]
    ]
    assert first["executable_plan_hash"] == second["executable_plan_hash"]


def test_direct_plan_generalizes_p4_step_without_report() -> None:
    compiled = _compiled(mode="GENERAL_ANSWER", ids=(STEP_1_ID, EXECUTABLE_PLAN_ID))

    assert len(compiled["steps"]) == 1
    assert compiled["steps"][0]["logical_step_ref"] == "S1"
    assert compiled["steps"][0]["compiled_step_key"] == "E1"
    assert compiled["completion_criteria"][0][
        "required_terminal_compiled_step_keys"
    ] == ["E1"]


def test_compiler_rejects_missing_compile_authority_and_lineage_drift() -> None:
    _, context, snapshot, plan, validation = _planning_inputs()
    invalid = copy.deepcopy(validation)
    invalid["status"] = "BLOCKED"
    invalid["runtime_directive"] = "BLOCK_EXECUTION"
    invalid["issues"] = [
        {"code": "BLOCKED", "severity": "WARNING", "message": "blocked"}
    ]
    _rehash_validation(invalid)
    with pytest.raises(ExecutablePlanError, match="compile authority"):
        compile_executable_plan(
            agent_plan=plan,
            validation_result=invalid,
            agent_context=context,
            capability_snapshot=snapshot,
        )

    changed_context = copy.deepcopy(context)
    changed_context["degradations"] = ["changed"]
    changed_context["context_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in changed_context.items() if key != "context_hash"}
    )
    with pytest.raises(ExecutablePlanError, match="does not match"):
        compile_executable_plan(
            agent_plan=plan,
            validation_result=validation,
            agent_context=changed_context,
            capability_snapshot=snapshot,
        )


def test_compiler_rejects_invalid_order_capability_and_contract() -> None:
    _, context, snapshot, plan, validation = _planning_inputs()
    reverse = copy.deepcopy(validation)
    reverse["topological_step_order"] = ["S2", "S1"]
    _rehash_validation(reverse)
    with pytest.raises(ExecutablePlanError, match="precede"):
        compile_executable_plan(
            agent_plan=plan,
            validation_result=reverse,
            agent_context=context,
            capability_snapshot=snapshot,
        )

    unavailable = copy.deepcopy(snapshot)
    unavailable["capabilities"] = unavailable["capabilities"][1:]
    unavailable["snapshot_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in unavailable.items() if key != "snapshot_hash"}
    )
    unavailable_plan = copy.deepcopy(plan)
    unavailable_plan["capability_snapshot_ref"]["hash"] = unavailable["snapshot_hash"]
    _rehash_plan(unavailable_plan)
    unavailable_validation = build_plan_validation_result(
        agent_plan=unavailable_plan,
        agent_context=context,
        status="VALID",
        issues=[],
        topological_step_order=["S1", "S2"],
        validation_result_id=VALIDATION_ID,
        validated_at=NOW,
    )
    with pytest.raises(ExecutablePlanError, match="capability"):
        compile_executable_plan(
            agent_plan=unavailable_plan,
            validation_result=unavailable_validation,
            agent_context=context,
            capability_snapshot=unavailable,
        )

    mismatched = copy.deepcopy(plan)
    mismatched["steps"][0]["output_contract_ref"] = "contract://wrong/v1"
    _rehash_plan(mismatched)
    mismatch_validation = build_plan_validation_result(
        agent_plan=mismatched,
        agent_context=context,
        status="VALID",
        issues=[],
        topological_step_order=["S1", "S2"],
        validation_result_id=VALIDATION_ID,
        validated_at=NOW,
    )
    with pytest.raises(ExecutablePlanError, match="output contract"):
        compile_executable_plan(
            agent_plan=mismatched,
            validation_result=mismatch_validation,
            agent_context=context,
            capability_snapshot=snapshot,
        )


def test_contract_detects_runtime_and_semantic_tampering() -> None:
    compiled = _compiled()
    changed = copy.deepcopy(compiled)
    changed["steps"][1]["title"] = "Tampered"
    with pytest.raises(ExecutablePlanError, match="Step hash"):
        validate_executable_plan_contract(changed)

    changed = copy.deepcopy(compiled)
    changed["logical_step_mapping"][0]["compiled_step_keys"] = ["E2"]
    with pytest.raises(ExecutablePlanError, match="mapping"):
        validate_executable_plan_contract(changed)

    changed = copy.deepcopy(compiled)
    changed["runtime_constraints"]["max_parallel_steps"] = 2
    with pytest.raises(ExecutablePlanError, match="constraints"):
        validate_executable_plan_contract(changed)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda steps: steps.append({}),
        lambda steps: steps[0].update(compiled_step_key="E9"),
        lambda steps: steps[0].update(logical_step_ref="bad"),
        lambda steps: steps[0].update(injected_for_logical_step_ref="bad"),
        lambda steps: steps[0].update(step_type="UNKNOWN"),
        lambda steps: steps[0].update(executor_kind="UNKNOWN"),
        lambda steps: steps[0].update(title=""),
        lambda steps: steps[0].update(depends_on_compiled_step_keys=["E9"]),
        lambda steps: steps[0].update(required_capability="x" * 161),
        lambda steps: steps[0].update(step_contract_hash="bad"),
    ],
)
def test_compiled_step_contract_rejects_malformed_fields(mutate) -> None:
    steps = copy.deepcopy(_compiled()["steps"])
    mutate(steps)

    with pytest.raises(ExecutablePlanError):
        module._validate_compiled_steps(steps)


@pytest.mark.parametrize("duplicate", ["logical", "runtime"])
def test_compiled_step_contract_rejects_duplicate_identities(duplicate: str) -> None:
    steps = copy.deepcopy(_compiled()["steps"])
    if duplicate == "logical":
        steps[1]["logical_step_ref"] = steps[0]["logical_step_ref"]
        _rehash_step(steps[1])
    else:
        steps[1]["executable_step_id"] = steps[0]["executable_step_id"]

    with pytest.raises(ExecutablePlanError, match="unique"):
        module._validate_compiled_steps(steps)


def test_compiled_binding_variants_and_guards() -> None:
    literal = module._compile_binding(
        {"target_name": "value", "source_type": "LITERAL", "literal_value": 3},
        {},
    )
    parameter = module._compile_binding(
        {
            "target_name": "value",
            "source_type": "WORK_INTENT_PARAMETER",
            "source_ref": "work-intent://parameter/value",
        },
        {},
    )
    entity = module._compile_binding(
        {
            "target_name": "entity",
            "source_type": "ENTITY_SELECTOR",
            "source_ref": "entity://selector/1",
        },
        {},
    )

    assert literal["binding_type"] == "LITERAL"
    assert parameter["binding_type"] == entity["binding_type"] == "RESOURCE_REF"
    module._validate_compiled_bindings([literal], [])
    with pytest.raises(ExecutablePlanError, match="unknown logical"):
        module._compile_binding(
            {"target_name": "value", "source_type": "STEP_OUTPUT", "source_ref": "S9"},
            {"S1": "E1"},
        )
    with pytest.raises(ExecutablePlanError, match="literal_value"):
        module._compile_binding({"target_name": "value", "source_type": "LITERAL"}, {})
    with pytest.raises(ExecutablePlanError, match="unsupported"):
        module._compile_binding({"target_name": "value", "source_type": "FUTURE"}, {})


@pytest.mark.parametrize(
    "bindings",
    [
        "bad",
        [{}],
        [_binding(target_name="INVALID")],
        [_binding(binding_type="UNKNOWN")],
        [_binding(source_ref=None)],
        [_binding(source_ref="E2:$")],
        [_binding(binding_type="RESOURCE_REF", source_ref="x" * 257)],
        [{**_binding(), "binding_hash": "bad"}],
        [{**_binding(), "source_ref": "E1:/changed"}],
    ],
)
def test_compiled_binding_contract_rejects_malformed_values(bindings) -> None:
    with pytest.raises(ExecutablePlanError):
        module._validate_compiled_bindings(bindings, ["E1"])


@pytest.mark.parametrize(
    "criteria",
    [
        [],
        ["bad"],
        [
            {
                "criterion_id": "bad",
                "required": True,
                "required_terminal_compiled_step_keys": ["E2"],
            }
        ],
        [
            {
                "criterion_id": "C1",
                "required": "yes",
                "required_terminal_compiled_step_keys": ["E2"],
            }
        ],
        [
            {
                "criterion_id": "C1",
                "required": True,
                "required_terminal_compiled_step_keys": ["E9"],
            }
        ],
    ],
)
def test_completion_criteria_contract_rejects_malformed_values(criteria) -> None:
    with pytest.raises(ExecutablePlanError):
        module._validate_completion_criteria(criteria, _compiled()["steps"])


def test_top_level_contract_and_scalar_guards() -> None:
    compiled = _compiled()
    with pytest.raises(ExecutablePlanError, match="canonical JSON"):
        validate_executable_plan_contract({"value": float("nan")})
    with pytest.raises(ExecutablePlanError, match="fields"):
        validate_executable_plan_contract({})
    with pytest.raises(ExecutablePlanError, match="steps"):
        module._validate_compiled_steps([])

    changed = copy.deepcopy(compiled)
    changed["agent_plan_ref"] = {"id": PLAN_ID}
    with pytest.raises(ExecutablePlanError, match="versioned hash"):
        validate_executable_plan_contract(changed)
    changed = copy.deepcopy(compiled)
    changed["executable_plan_hash"] = "bad"
    with pytest.raises(ExecutablePlanError, match="semantic hash"):
        validate_executable_plan_contract(changed)
    changed = copy.deepcopy(compiled)
    changed["executable_plan_hash"] = "sha256:" + "f" * 64
    with pytest.raises(ExecutablePlanError, match="does not match"):
        validate_executable_plan_contract(changed)

    for function, arguments in (
        (module._required_uuid, ("id", None)),
        (module._required_uuid, ("id", "bad")),
        (module._bounded_int, ("version", True, 1, 9)),
        (module._required_text, ("name", "", 10)),
        (module._required_datetime, ("time", None)),
        (module._required_datetime, ("time", "bad")),
        (module._required_datetime, ("time", "2026-10-14T10:00:00")),
        (module._versioned_ref, (PLAN_ID, 1, "bad")),
        (
            module._validate_versioned_ref,
            ("ref", {"id": PLAN_ID, "version": 1, "hash": "bad"}),
        ),
    ):
        with pytest.raises(ExecutablePlanError):
            function(*arguments)


def test_compiler_rejects_exact_order_and_reference_drift() -> None:
    _, context, snapshot, plan, validation = _planning_inputs()
    incomplete = copy.deepcopy(validation)
    incomplete["topological_step_order"] = ["S1"]
    _rehash_validation(incomplete)
    with pytest.raises(ExecutablePlanError, match="exact AgentPlan"):
        compile_executable_plan(
            agent_plan=plan,
            validation_result=incomplete,
            agent_context=context,
            capability_snapshot=snapshot,
        )

    for field, value, message in (
        (
            "agent_plan_ref",
            {**validation["agent_plan_ref"], "hash": "sha256:" + "f" * 64},
            "exact AgentPlan",
        ),
        ("execution_id", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "execution"),
        (
            "validated_context_ref",
            {
                **validation["validated_context_ref"],
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            },
            "context",
        ),
    ):
        changed = copy.deepcopy(validation)
        changed[field] = value
        _rehash_validation(changed)
        with pytest.raises(ExecutablePlanError, match=message):
            compile_executable_plan(
                agent_plan=plan,
                validation_result=changed,
                agent_context=context,
                capability_snapshot=snapshot,
            )

    other_snapshot = build_capability_snapshot(
        tenant_id=TENANT,
        capability_snapshot_id=SNAPSHOT_ID,
        snapshot_version=2,
        created_at=NOW,
    )
    with pytest.raises(ExecutablePlanError, match="snapshot"):
        compile_executable_plan(
            agent_plan=plan,
            validation_result=validation,
            agent_context=context,
            capability_snapshot=other_snapshot,
        )


def test_context_and_capability_fail_closed_helpers() -> None:
    context = _context()
    changed = copy.deepcopy(context)
    changed["identity"] = {"tenant_id": "changed"}
    with pytest.raises(ExecutablePlanError, match="hash"):
        module._validate_context_lineage(changed)
    with pytest.raises(ExecutablePlanError, match="lineage"):
        module._validate_context_lineage({"value": float("nan")})
    assert module._policy_snapshot_ref({}) is None
    with pytest.raises(ExecutablePlanError, match="policy hash"):
        module._policy_snapshot_ref({"runtime_policy_ref": {"rule_hash": "bad"}})

    logical = copy.deepcopy(_planning_inputs()[3]["steps"][0])
    logical["step_type"] = "DELEGATE_WORK"
    with pytest.raises(ExecutablePlanError, match="DELEGATE_WORK"):
        module._resolve_capability(logical, _snapshot())
    with pytest.raises(ExecutablePlanError, match="absent"):
        module._compile_step(
            _planning_inputs()[3]["steps"][1],
            step_index=1,
            compiled_step_key="E2",
            key_by_logical={"S2": "E2"},
            capability_snapshot=_snapshot(),
            executable_step_id=STEP_2_ID,
            execution_id=EXECUTION_ID,
            agent_plan_version=1,
        )


def test_repository_atomically_materializes_and_reads_restart_safe_plan() -> None:
    factory = _factory()
    repository = SqlAlchemyExecutablePlanRepository(factory)
    compiled = _compiled()

    assert repository.save(tenant_id=TENANT, executable_plan=compiled) == compiled
    assert repository.save(tenant_id=TENANT, executable_plan=compiled) == compiled
    restarted = SqlAlchemyExecutablePlanRepository(factory)
    assert (
        restarted.get(tenant_id=TENANT, executable_plan_id=EXECUTABLE_PLAN_ID)
        == compiled
    )
    steps = restarted.list_steps(
        tenant_id=TENANT, executable_plan_id=EXECUTABLE_PLAN_ID
    )
    assert [step["state"] for step in steps] == ["READY", "PENDING"]
    assert [step["compiled_step_key"] for step in steps] == ["E1", "E2"]
    assert steps[1]["dependencies"] == ["E1"]


def test_repository_rolls_back_on_authority_lineage_and_version_conflicts() -> None:
    factory = _factory()
    compiled = _compiled()
    repository = SqlAlchemyExecutablePlanRepository(factory)
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_agent_execution SET phase = 'STEP_EXECUTION' WHERE tenant_id = :t"
            ),
            {"t": TENANT},
        )
    with pytest.raises(ExecutablePlanError) as exc_info:
        repository.save(tenant_id=TENANT, executable_plan=compiled)
    assert exc_info.value.error_code == "ae.executable_plan_authority_missing"
    with factory.begin() as session:
        assert (
            session.execute(
                text("SELECT count(*) FROM ae_executable_plan")
            ).scalar_one()
            == 0
        )
        session.execute(
            text(
                "UPDATE ae_agent_execution SET phase = 'PLAN_COMPILE' WHERE tenant_id = :t"
            ),
            {"t": TENANT},
        )
        session.execute(
            text("UPDATE ae_agent_plan SET plan_hash = :h WHERE tenant_id = :t"),
            {"t": TENANT, "h": "sha256:" + "f" * 64},
        )
    with pytest.raises(ExecutablePlanError) as exc_info:
        repository.save(tenant_id=TENANT, executable_plan=compiled)
    assert exc_info.value.error_code == "ae.executable_plan_lineage_mismatch"

    factory = _factory()
    repository = SqlAlchemyExecutablePlanRepository(factory)
    repository.save(tenant_id=TENANT, executable_plan=compiled)
    conflict = copy.deepcopy(compiled)
    conflict["executable_plan_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    conflict["logical_step_mapping"][0]["executable_step_ids"] = [
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    ]
    conflict["steps"][0]["executable_step_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    conflict["logical_step_mapping"][1]["executable_step_ids"] = [
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    ]
    conflict["steps"][1]["executable_step_id"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    with pytest.raises(ExecutablePlanError) as exc_info:
        repository.save(tenant_id=TENANT, executable_plan=conflict)
    assert exc_info.value.error_code == "ae.executable_plan_version_conflict"


def test_repository_detects_persisted_validation_and_step_drift() -> None:
    factory = _factory()
    repository = SqlAlchemyExecutablePlanRepository(factory)
    compiled = _compiled()
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_plan_validation SET status = 'BLOCKED' WHERE tenant_id = :t"
            ),
            {"t": TENANT},
        )
    with pytest.raises(ExecutablePlanError) as exc_info:
        repository.save(tenant_id=TENANT, executable_plan=compiled)
    assert exc_info.value.error_code == "ae.executable_plan_validation_mismatch"

    with pytest.raises(ExecutablePlanError, match="exactly once"):
        module._require_persisted_steps(compiled, [])
    persisted = [
        {
            "executable_step_id": step["executable_step_id"],
            "agent_execution_id": compiled["execution_id"],
            "executable_plan_id": compiled["executable_plan_id"],
            "logical_step_id": step["logical_step_ref"],
            "compiled_step_key": step["compiled_step_key"],
            "step_index": step["step_index"],
            "step_type": step["step_type"],
            "executor_kind": step["executor_kind"],
            "required_capability": step["required_capability"],
            "capability_version": step["capability_version"],
            "dependencies": step["depends_on_compiled_step_keys"],
            "compiled_input_bindings": step["compiled_input_bindings"],
            "output_contract_ref": step["output_contract_ref"],
            "step_contract_hash": step["step_contract_hash"],
        }
        for step in compiled["steps"]
    ]
    persisted[0]["compiled_step_key"] = "E9"
    with pytest.raises(ExecutablePlanError, match="differs"):
        module._require_persisted_steps(compiled, persisted)


def test_repository_maps_insert_reload_conflicts(monkeypatch) -> None:
    compiled = _compiled()
    repository = SqlAlchemyExecutablePlanRepository(_factory())
    monkeypatch.setattr(module, "_load_plan", lambda *args: None)
    monkeypatch.setattr(module, "_load_plan_by_version", lambda *args: None)
    with pytest.raises(ExecutablePlanError) as exc_info:
        repository.save(tenant_id=TENANT, executable_plan=compiled)
    assert exc_info.value.error_code == "ae.executable_plan_write_conflict"
    assert exc_info.value.retryable is True

    different = copy.deepcopy(compiled)
    different["compiler_version"] = "different"
    monkeypatch.setattr(module, "_load_plan", lambda *args: different)
    with pytest.raises(ExecutablePlanError) as exc_info:
        repository.save(tenant_id=TENANT, executable_plan=compiled)
    assert exc_info.value.error_code == "ae.executable_plan_immutable_conflict"


def test_same_execution_version_guard_rejects_different_content() -> None:
    factory = _factory()
    compiled = _compiled()
    SqlAlchemyExecutablePlanRepository(factory).save(
        tenant_id=TENANT, executable_plan=compiled
    )
    changed = copy.deepcopy(compiled)
    changed["compiled_at"] = "2026-10-14T10:00:00Z"
    with (
        factory() as session,
        pytest.raises(ExecutablePlanError, match="different ExecutablePlan"),
    ):
        module._require_same_execution_version(session, TENANT, changed)


def test_repository_maps_database_failures_and_validates_identity() -> None:
    repository = SqlAlchemyExecutablePlanRepository(_factory(schema=False))
    with pytest.raises(ExecutablePlanError) as exc_info:
        repository.save(tenant_id=TENANT, executable_plan=_compiled())
    assert exc_info.value.error_code == "ae.executable_plan_store_unavailable"
    assert exc_info.value.retryable is True

    with pytest.raises(ExecutablePlanError) as exc_info:
        repository.get(tenant_id=TENANT, executable_plan_id=EXECUTABLE_PLAN_ID)
    assert exc_info.value.error_code == "ae.executable_plan_store_unavailable"
    with pytest.raises(ExecutablePlanError) as exc_info:
        repository.list_steps(tenant_id=TENANT, executable_plan_id=EXECUTABLE_PLAN_ID)
    assert exc_info.value.error_code == "ae.executable_plan_store_unavailable"

    with pytest.raises(ExecutablePlanError, match="UUID"):
        repository.get(tenant_id=TENANT, executable_plan_id="bad")
    with pytest.raises(ExecutablePlanError, match="UUID"):
        repository.list_steps(tenant_id=TENANT, executable_plan_id="bad")
