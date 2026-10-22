from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api.executable_plans import compile_executable_plan
from nex_ae_api.golden_a_planning import (
    GOLDEN_A_OUTPUT_CONTRACT,
    GOLDEN_A_SKILL_ID,
    GoldenAPlanningError,
    activate_golden_a_work_intent,
    bind_golden_a_planning_candidate,
    build_golden_a_capability_snapshot,
    build_golden_a_planning_capability,
)
from nex_ae_api.intent_candidate_generation import (
    IntentCandidateStageError,
    parse_intent_candidate,
)
from nex_ae_api.plan_candidate_generation import (
    bind_plan_candidate,
    parse_plan_candidate,
)
from nex_ae_api.plan_validation import validate_agent_plan
from nex_ae_api.planning_capabilities import (
    CapabilitySnapshotError,
    build_local_skill_capability,
)
from nex_ae_api.work_intent import build_work_intent_from_decision
from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref
from p8_golden_a_fixture import load_golden_a_fixture

ROOT = Path(__file__).resolve().parents[1]
WORK_INTENT_SCHEMA = (
    ROOT / "docs/transition/P5/contracts/p5-work-intent-v1.1.schema.json"
)
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
WORK_INTENT_ID = "22222222-2222-4222-8222-222222222222"
CONTEXT_ID = "33333333-3333-4333-8333-333333333333"
SNAPSHOT_ID = "44444444-4444-4444-8444-444444444444"
PLAN_ID = "55555555-5555-4555-8555-555555555555"
VALIDATION_ID = "66666666-6666-4666-8666-666666666666"
STEP_ID = "77777777-7777-4777-8777-777777777777"
EXECUTABLE_PLAN_ID = "88888888-8888-4888-8888-888888888888"
NOW = "2026-10-23T09:00:00Z"


def _fixture() -> dict:
    return load_golden_a_fixture()


def _candidate(**overrides) -> dict:
    fixture = _fixture()
    scenario = fixture["scenario"]
    values = {
        "schema_version": "p65.intent_candidate.v1",
        "intent_label": GOLDEN_A_SKILL_ID,
        "suggested_execution_mode": "GENERAL_ANSWER",
        "entity_selectors": [
            {
                "selector_id": "E1",
                "selector_type": "QUERY_TERM",
                "value": fixture["projects"]["child"]["project_code"],
                "confidence": 0.98,
            }
        ],
        "parameter_candidates": [
            {"name": name, "value": scenario[name], "confidence": 0.97}
            for name in (
                "amount",
                "currency",
                "transaction_date",
                "voucher_type",
                "economic_category",
                "settlement_method",
            )
        ],
        "clarification": {"required": False, "reasons": [], "questions": []},
        "confidence": 0.98,
    }
    return {**values, **overrides}


def _base_work_intent() -> dict:
    return build_work_intent_from_decision(
        execution_id=EXECUTION_ID,
        source_ref="interaction-p8-s64",
        actor_ref="employee-1001",
        received_at=NOW,
        intent_decision={
            "intent_decision_schema_version": "ae_intent_decision.v1",
            "intent_label": GOLDEN_A_SKILL_ID,
            "execution_mode": "GENERAL_ANSWER",
            "confidence": 0.98,
            "raw_prompt_included": False,
            "decision_hash": "a" * 64,
        },
        input_context_hash=semantic_sha256_hash_ref({"prompt": "redacted"}),
        work_intent_id=WORK_INTENT_ID,
    )


def _activation_inputs():
    fixture = _fixture()
    candidate = _candidate()
    activation = bind_golden_a_planning_candidate(
        fixture=fixture,
        candidate=candidate,
    )
    work_intent = activate_golden_a_work_intent(
        _base_work_intent(), candidate=candidate, activation=activation
    )
    snapshot = build_golden_a_capability_snapshot(
        fixture,
        capability_snapshot_id=SNAPSHOT_ID,
        snapshot_version=64,
        created_at=NOW,
    )
    context = {
        "schema_version": "1.1",
        "context_id": CONTEXT_ID,
        "context_generation": 1,
        "execution_id": EXECUTION_ID,
        "work_intent_ref": {
            "id": WORK_INTENT_ID,
            "version": 1,
            "hash": work_intent["intent_hash"],
        },
        "identity": {"tenant_id": "p8-golden-a", "principal_id": "employee-1001"},
        "project_ref": None,
        "authority_ref": "authority://nex-oa/employee-1001/v1",
        "resolved_entities": [
            {
                "selector_id": "E1",
                "entity_type": "PROJECT",
                "resource_ref": activation["authoritative_binding"]["project_ref"],
            }
        ],
        "retrieval_refs": [],
        "evidence_refs": [],
        "conflicts": [],
        "degradations": [],
        "runtime_policy_ref": {
            "policy_id": "p8-golden-a-write",
            "rule_hash": semantic_sha256_hash_ref({"policy": "p8-s64"}),
        },
    }
    context["context_hash"] = semantic_sha256_hash_ref(context)
    return fixture, candidate, activation, work_intent, snapshot, context


def _plan_candidate(goal: str) -> dict:
    return {
        "schema_version": "p65.plan_candidate.v1",
        "suggested_plan_kind": "DIRECT",
        "goal": goal,
        "logical_steps": [
            {
                "step_id": "S1",
                "step_type": "LOCAL_CAPABILITY",
                "title": "Create governed voucher draft",
                "objective": "Run the exact admitted WRITE Skill.",
                "depends_on": [],
                "capability_hint": GOLDEN_A_SKILL_ID,
                "completion_criteria": ["A governed voucher-draft result is produced."],
            }
        ],
        "completion_mapping": [{"criterion_id": "C1", "terminal_step_refs": ["S1"]}],
        "confidence": 0.97,
    }


def _rehash_fixture(value: dict) -> dict:
    value = deepcopy(value)
    value.pop("fixture_hash", None)
    value["fixture_hash"] = semantic_sha256_hash_ref(value)
    return value


def test_write_capability_activation_is_exact_and_v02_only() -> None:
    capability = build_golden_a_planning_capability(_fixture())

    assert capability["operation_semantics"] == "WRITE"
    assert capability["capability_id"] == GOLDEN_A_SKILL_ID
    assert capability["capability_version"] == "1.0.0"
    assert capability["local_skill_binding"]["backend_profile"] == (
        "NSL_V02_IN_PROCESS"
    )
    assert capability["local_skill_binding"]["skill_semantic_hash"].startswith(
        "sha256:"
    )

    with pytest.raises(CapabilitySnapshotError, match="operation semantics"):
        build_local_skill_capability(
            skill_id=GOLDEN_A_SKILL_ID,
            exact_skill_version="1.0.0",
            skill_semantic_hash="sha256:" + "a" * 64,
            input_contract_ref="contract://input",
            output_contract_ref="contract://output",
            runtime_contract_ref="contract://runtime",
            trust_policy_id="policy://trust",
            backend_profile="NSL_V01_IN_PROCESS",
            operation_semantics="WRITE",
        )


def test_exact_project_code_binds_authoritative_project_accounts_and_balanced_lines() -> (
    None
):
    fixture = _fixture()
    result = bind_golden_a_planning_candidate(
        fixture=fixture,
        candidate=_candidate(),
    )
    binding = result["authoritative_binding"]
    lines = binding["voucher"]["lines"]

    assert result["directive"] == "CONTINUE"
    assert binding["project_ref"]["resource_id"] == (
        fixture["projects"]["child"]["project_id"]
    )
    assert [line["direction"] for line in lines] == ["DEBIT", "CREDIT"]
    assert [line["signed_amount"] for line in lines] == ["84000.00", "-84000.00"]
    assert {line["account_ref"]["resource_id"] for line in lines} == {
        fixture["voucher_line_policy"]["debit_account_id"],
        fixture["voucher_line_policy"]["credit_account_id"],
    }
    assert result == bind_golden_a_planning_candidate(
        fixture=fixture,
        candidate=_candidate(),
    )
    serialized = canonical_json(result)
    for forbidden in (
        "approval_authority",
        "idempotency_key",
        "business_operation_id",
        "eos_commit_state",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("selectors", "failure_code"),
    (
        (
            [
                {
                    "selector_id": "E1",
                    "selector_type": "ENTITY_NAME",
                    "value": "Golden A Travel Project",
                    "confidence": 0.9,
                }
            ],
            "PROJECT_CONFIRMATION_REQUIRED",
        ),
        (
            [
                {
                    "selector_id": "E1",
                    "selector_type": "ENTITY_ID",
                    "value": "82000000-0000-4000-8000-000000000001",
                    "confidence": 0.9,
                }
            ],
            "PROJECT_TRUSTED_SELECTION_REQUIRED",
        ),
        (
            [
                {
                    "selector_id": "E1",
                    "selector_type": "QUERY_TERM",
                    "value": "UNKNOWN",
                    "confidence": 0.9,
                }
            ],
            "PROJECT_CANDIDATE_NOT_FOUND",
        ),
        (
            [
                {
                    "selector_id": "E1",
                    "selector_type": "QUERY_TERM",
                    "value": "PROJECT-A-2",
                    "confidence": 0.9,
                },
                {
                    "selector_id": "E2",
                    "selector_type": "QUERY_TERM",
                    "value": "PROJECT-A-2",
                    "confidence": 0.8,
                },
            ],
            "PROJECT_CANDIDATE_AMBIGUOUS",
        ),
    ),
)
def test_project_candidate_never_wins_by_display_rank_or_model_stable_id(
    selectors, failure_code
) -> None:
    result = bind_golden_a_planning_candidate(
        fixture=_fixture(),
        candidate=_candidate(entity_selectors=selectors),
    )

    assert result["directive"] == "CLARIFICATION_REQUIRED"
    assert result["failure_code"] == failure_code
    assert result["authoritative_binding"] is None


def test_missing_mismatched_and_model_requested_clarification_stop_activation() -> None:
    candidate = _candidate()
    candidate["parameter_candidates"] = candidate["parameter_candidates"][:-1]
    candidate["parameter_candidates"][0]["value"] = "1.00"
    candidate["clarification"] = {
        "required": True,
        "reasons": ["결제수단이 불명확합니다."],
        "questions": ["현금 결제가 맞습니까?"],
    }

    result = bind_golden_a_planning_candidate(
        fixture=_fixture(),
        candidate=candidate,
    )

    assert result["directive"] == "CLARIFICATION_REQUIRED"
    assert result["failure_code"] == "MODEL_CLARIFICATION_REQUIRED"
    assert any("amount" in item for item in result["clarification"]["reasons"])
    assert any(
        "settlement_method" in item for item in result["clarification"]["reasons"]
    )


@pytest.mark.parametrize(
    "authority_name",
    ("idempotency_key", "commit_state", "account_id", "approval_authority"),
)
def test_intent_candidate_rejects_authority_bearing_parameter_names(
    authority_name: str,
) -> None:
    candidate = _candidate()
    candidate["parameter_candidates"].append(
        {"name": authority_name, "value": "model-value", "confidence": 1.0}
    )

    with pytest.raises(IntentCandidateStageError) as failure:
        parse_intent_candidate(canonical_json(candidate))

    assert failure.value.error_code == "CANDIDATE_AUTHORITY_VIOLATION"


def test_fixture_and_intent_drift_fail_closed() -> None:
    fixture = _fixture()
    fixture["scenario"]["amount"] = "1.00"
    with pytest.raises(GoldenAPlanningError, match="hash does not match"):
        build_golden_a_planning_capability(fixture)

    fixture = _fixture()
    fixture["admission"]["backend_profile"] = "NSL_V01_IN_PROCESS"
    fixture = _rehash_fixture(fixture)
    with pytest.raises(GoldenAPlanningError, match="does not match P8-S64"):
        build_golden_a_planning_capability(fixture)

    candidate = _candidate(intent_label="AE.CHAT.COMPATIBILITY")
    with pytest.raises(GoldenAPlanningError) as unsupported:
        bind_golden_a_planning_candidate(fixture=_fixture(), candidate=candidate)
    assert unsupported.value.error_code == "P8_GOLDEN_A_INTENT_UNSUPPORTED"


@pytest.mark.parametrize(
    ("mutator", "detail"),
    (
        (lambda value: value.update(schema_version="unsupported"), "schema version"),
        (lambda value: value.update(fixture_hash="bad"), "hash is invalid"),
        (lambda value: value.pop("tenant"), "missing planning data"),
        (
            lambda value: value["accounts"].pop(),
            "account mapping is invalid",
        ),
        (
            lambda value: value["scenario"].update(currency="USD"),
            "does not match its line policy",
        ),
        (
            lambda value: value["voucher_line_policy"].update(
                effective_from="2027-01-01"
            ),
            "not yet effective",
        ),
        (
            lambda value: value["voucher_line_policy"].update(effective_from="bad"),
            "policy dates are invalid",
        ),
    ),
)
def test_planning_projection_rejects_fixture_contract_damage(mutator, detail) -> None:
    fixture = _fixture()
    mutator(fixture)
    if fixture.get("fixture_hash") != "bad":
        fixture = _rehash_fixture(fixture)

    with pytest.raises(GoldenAPlanningError, match=detail):
        build_golden_a_planning_capability(fixture)

    with pytest.raises(GoldenAPlanningError, match="must be an object"):
        build_golden_a_planning_capability([])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("name", "value"),
    (("amount", "not-a-decimal"), ("transaction_date", "not-a-date")),
)
def test_invalid_candidate_value_requires_business_input_clarification(
    name: str, value: str
) -> None:
    candidate = _candidate()
    next(item for item in candidate["parameter_candidates"] if item["name"] == name)[
        "value"
    ] = value

    result = bind_golden_a_planning_candidate(
        fixture=_fixture(),
        candidate=candidate,
    )

    assert result["directive"] == "CLARIFICATION_REQUIRED"
    assert result["failure_code"] == "BUSINESS_INPUT_CLARIFICATION_REQUIRED"


def test_work_intent_activation_rejects_forged_continue_binding() -> None:
    activation = bind_golden_a_planning_candidate(
        fixture=_fixture(),
        candidate=_candidate(),
    )
    activation["authoritative_binding"] = None

    with pytest.raises(GoldenAPlanningError) as invalid:
        activate_golden_a_work_intent(
            _base_work_intent(), candidate=_candidate(), activation=activation
        )

    assert invalid.value.error_code == "P8_GOLDEN_A_ACTIVATION_MISMATCH"

    activation["activation_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in activation.items() if key != "activation_hash"}
    )
    with pytest.raises(GoldenAPlanningError) as binding:
        activate_golden_a_work_intent(
            _base_work_intent(), candidate=_candidate(), activation=activation
        )
    assert binding.value.error_code == "P8_GOLDEN_A_BINDING_INVALID"

    valid_binding = bind_golden_a_planning_candidate(
        fixture=_fixture(), candidate=_candidate()
    )["authoritative_binding"]
    for malformed in (
        {"capability_ref": []},
        {**valid_binding, "project_code": "OTHER-PROJECT"},
    ):
        activation = bind_golden_a_planning_candidate(
            fixture=_fixture(), candidate=_candidate()
        )
        activation["authoritative_binding"] = malformed
        activation["activation_hash"] = semantic_sha256_hash_ref(
            {
                key: value
                for key, value in activation.items()
                if key != "activation_hash"
            }
        )
        with pytest.raises(GoldenAPlanningError) as malformed_binding:
            activate_golden_a_work_intent(
                _base_work_intent(), candidate=_candidate(), activation=activation
            )
        assert malformed_binding.value.error_code == "P8_GOLDEN_A_BINDING_INVALID"


def test_work_intent_activation_handles_non_project_hint_before_exact_code() -> None:
    candidate = _candidate()
    candidate["entity_selectors"].insert(
        0,
        {
            "selector_id": "E2",
            "selector_type": "QUERY_TERM",
            "value": "TRAVEL",
            "confidence": 0.7,
        },
    )
    activation = bind_golden_a_planning_candidate(
        fixture=_fixture(),
        candidate=candidate,
    )

    work_intent = activate_golden_a_work_intent(
        _base_work_intent(), candidate=candidate, activation=activation
    )

    assert work_intent["entity_selectors"][0]["raw_text"] == "PROJECT-A-2"
    assert work_intent["confidence"]["entities"] == 0.98


def test_work_intent_activation_rejects_candidate_substitution() -> None:
    valid_candidate = _candidate()
    activation = bind_golden_a_planning_candidate(
        fixture=_fixture(),
        candidate=valid_candidate,
    )
    incomplete = deepcopy(valid_candidate)
    incomplete["parameter_candidates"] = incomplete["parameter_candidates"][:-1]

    with pytest.raises(GoldenAPlanningError) as missing:
        activate_golden_a_work_intent(
            _base_work_intent(), candidate=incomplete, activation=activation
        )

    assert missing.value.error_code == "P8_GOLDEN_A_ACTIVATION_MISMATCH"

    activation["candidate_hash"] = semantic_sha256_hash_ref(
        parse_intent_candidate(canonical_json(incomplete))
    )
    activation["activation_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in activation.items() if key != "activation_hash"}
    )
    with pytest.raises(GoldenAPlanningError) as candidate_shape:
        activate_golden_a_work_intent(
            _base_work_intent(), candidate=incomplete, activation=activation
        )
    assert candidate_shape.value.error_code == "P8_GOLDEN_A_BINDING_INVALID"

    activation["activation_hash"] = "bad"
    with pytest.raises(GoldenAPlanningError) as invalid_hash:
        activate_golden_a_work_intent(
            _base_work_intent(), candidate=valid_candidate, activation=activation
        )
    assert invalid_hash.value.error_code == "P8_GOLDEN_A_ACTIVATION_INVALID"


def test_activation_produces_schema_valid_candidate_only_work_intent() -> None:
    _, candidate, activation, work_intent, _, _ = _activation_inputs()
    schema = __import__("json").loads(WORK_INTENT_SCHEMA.read_text(encoding="utf-8"))

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(work_intent)
    assert work_intent["required_capability_hints"] == [GOLDEN_A_SKILL_ID]
    assert work_intent["project_ref"] is None
    assert work_intent["entity_selectors"][0]["raw_text"] == "PROJECT-A-2"
    assert {item["source"] for item in work_intent["parameter_candidates"]} == {
        "MODEL_CANDIDATE"
    }
    assert work_intent["completion_criteria"][0]["result_contract_ref"] == (
        GOLDEN_A_OUTPUT_CONTRACT
    )
    assert work_intent["intent_hash"] == semantic_sha256_hash_ref(
        {key: value for key, value in work_intent.items() if key != "intent_hash"}
    )
    assert activation["candidate_hash"] == semantic_sha256_hash_ref(
        parse_intent_candidate(canonical_json(candidate))
    )


def test_plan_candidate_binds_exact_write_capability_and_compiles() -> None:
    _, _, _, work_intent, snapshot, context = _activation_inputs()
    candidate = parse_plan_candidate(
        canonical_json(_plan_candidate(work_intent["goal"]))
    )
    plan = bind_plan_candidate(
        candidate=candidate,
        candidate_hash=semantic_sha256_hash_ref(candidate),
        work_intent=work_intent,
        agent_context=context,
        capability_snapshot=snapshot,
        prompt_provenance={
            "prompt_binding_key": "ae.plan.candidate.v1",
            "prompt_template_version_id": "99999999-9999-4999-8999-999999999999",
            "prompt_content_sha256": "b" * 64,
            "rendered_prompt_hash": "c" * 64,
        },
        model_provenance={
            "model_profile": "planning-live",
            "model_ref": "provider-selected",
        },
        agent_plan_id=PLAN_ID,
    )
    validation = validate_agent_plan(
        agent_plan=plan,
        work_intent=work_intent,
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

    assert validation["status"] == "VALID"
    assert plan["steps"][0]["required_capability"] == GOLDEN_A_SKILL_ID
    assert plan["steps"][0]["capability_version_constraint"] == "1.0.0"
    assert compiled["steps"][0]["executor_kind"] == "LOCAL_SKILL"
    assert compiled["steps"][0]["capability_version"] == "1.0.0"
    assert compiled["steps"][0]["skill_binding"]["backend_profile"] == (
        "NSL_V02_IN_PROCESS"
    )


def test_work_intent_activation_rejects_unbound_and_tampered_inputs() -> None:
    fixture = _fixture()
    candidate = _candidate()
    clarification = bind_golden_a_planning_candidate(
        fixture=fixture,
        candidate=_candidate(entity_selectors=[]),
    )
    with pytest.raises(GoldenAPlanningError) as unavailable:
        activate_golden_a_work_intent(
            _base_work_intent(), candidate=candidate, activation=clarification
        )
    assert unavailable.value.error_code == "P8_GOLDEN_A_BINDING_UNAVAILABLE"

    tampered = _base_work_intent()
    tampered["goal"] = "tampered"
    activation = bind_golden_a_planning_candidate(
        fixture=fixture,
        candidate=candidate,
    )
    with pytest.raises(GoldenAPlanningError) as invalid:
        activate_golden_a_work_intent(
            tampered, candidate=candidate, activation=activation
        )
    assert invalid.value.error_code == "P8_GOLDEN_A_WORK_INTENT_INVALID"
