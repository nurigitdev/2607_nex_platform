from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from nex_ae_api.golden_a_approval_journey import (
    GoldenAApprovalJourneyError,
    GoldenAPlanningJourneyService,
    _require_exact_local_skill,
)
from nex_ae_api.golden_a_planning import (
    GOLDEN_A_CAPABILITY_ID,
    GOLDEN_A_NSL_SKILL_ID,
)
from nex_ae_api.intent_candidate_generation import LiveIntentCandidateService
from nex_ae_api.mo_generation_client import (
    AeMoGenerationReadiness,
    AeMoGenerationResult,
)
from nex_ae_api.plan_candidate_generation import LivePlanCandidateService
from nex_ae_api.prompts import seed_ae_prompt_registry
from nex_ae_api.semantic_candidates import (
    SemanticCalibrationPolicy,
    SemanticCalibrationRegistry,
)
from nex_runtime.prompts import PromptRegistryStore
from nex_runtime.semantic_hashes import canonical_json, sha256_text
from p8_golden_a_fixture import load_golden_a_fixture

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-23T10:00:00Z"
MODEL_PROFILE = "general-llm-default"
MODEL_REF = "Qwen3.5-4B"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
TENANT_ID = "p8-golden-a"


def _fixture() -> dict:
    return load_golden_a_fixture()


def _intent_candidate(**overrides) -> dict:
    fixture = _fixture()
    scenario = fixture["scenario"]
    value = {
        "schema_version": "p65.intent_candidate.v1",
        "intent_label": GOLDEN_A_CAPABILITY_ID,
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
    value.update(overrides)
    return value


def _plan_candidate(**overrides) -> dict:
    value = {
        "schema_version": "p65.plan_candidate.v1",
        "suggested_plan_kind": "DIRECT",
        "goal": (
            "Create a governed voucher draft after deterministic business binding."
        ),
        "logical_steps": [
            {
                "step_id": "S1",
                "step_type": "LOCAL_CAPABILITY",
                "title": "Create governed voucher draft",
                "objective": "Run the exact admitted WRITE Skill.",
                "depends_on": [],
                "capability_hint": GOLDEN_A_CAPABILITY_ID,
                "completion_criteria": ["A governed voucher-draft result is produced."],
            }
        ],
        "completion_mapping": [{"criterion_id": "C1", "terminal_step_refs": ["S1"]}],
        "confidence": 0.98,
    }
    value.update(overrides)
    return value


def _policy(stage: str) -> SemanticCalibrationPolicy:
    lower = stage.lower()
    return SemanticCalibrationPolicy(
        semantic_stage=stage,
        policy_ref=f"semantic-admission://{lower}/{MODEL_PROFILE}/p8-s65.1",
        policy_version="p8-s65.1",
        model_profile=MODEL_PROFILE,
        model_ref=MODEL_REF,
        minimum_confidence=0.7,
        golden_evidence_ref=f"test://p8-s65/{lower}/golden",
        adversarial_evidence_ref=f"test://p8-s65/{lower}/adversarial",
    )


class CandidateClient:
    def __init__(self, *, intent: dict | None = None, plan: dict | None = None) -> None:
        self.intent = intent or _intent_candidate()
        self.plan = plan or _plan_candidate()
        self.calls: list[str] = []

    def check_required_mode_readiness(self, **_kwargs):
        return AeMoGenerationReadiness(
            provider_mode="live",
            readiness_status="READY",
            model_profile=MODEL_PROFILE,
            model_ref=MODEL_REF,
            deployment_id="vllm-generation-http",
            route_id="route-general-llm-default",
            checked_at=NOW,
            expires_at="2026-10-23T10:00:30Z",
            cache_status="FRESH",
            source="active_preflight",
        )

    def generate_candidate(self, **kwargs):
        stage = kwargs["semantic_stage"]
        self.calls.append(stage)
        output = canonical_json(self.intent if stage == "INTENT" else self.plan)
        return AeMoGenerationResult(
            mo_generation_id=f"p8-s65-{stage.lower()}",
            model_profile=MODEL_PROFILE,
            model_ref=MODEL_REF,
            deployment_id="vllm-generation-http",
            provider_type="vllm-openai-compatible",
            output_text=output,
            provider_output_sha256=sha256_text(output),
            provider_output_size_bytes=len(output.encode()),
            finish_reason="STOP",
            input_tokens=100,
            output_tokens=100,
            total_tokens=200,
            request_id=kwargs["request_id"],
            trace_id=kwargs["trace_id"],
            route_id="route-general-llm-default",
            provider_request_id=f"provider-p8-s65-{stage.lower()}",
            queue_ms=1,
            provider_ms=20,
            total_ms=21,
            created_at=NOW,
            updated_at=NOW,
        )


def _service(client: CandidateClient) -> GoldenAPlanningJourneyService:
    store = PromptRegistryStore()
    seed_ae_prompt_registry(store)
    return GoldenAPlanningJourneyService(
        intent_service=LiveIntentCandidateService(
            client=client,
            prompt_store=store,
            calibration_registry=SemanticCalibrationRegistry((_policy("INTENT"),)),
        ),
        plan_service=LivePlanCandidateService(
            client=client,
            prompt_store=store,
            calibration_registry=SemanticCalibrationRegistry((_policy("PLAN"),)),
        ),
    )


def _run(service: GoldenAPlanningJourneyService, **overrides):
    fixture = overrides.pop("fixture", _fixture())
    canonical = _fixture()
    values = {
        "fixture": fixture,
        "user_prompt": canonical["scenario"]["prompt"],
        "tenant_id": TENANT_ID,
        "principal_id": canonical["principals"][0]["subject_id"],
        "agent_id": "10000000-0000-4000-8000-000000000065",
        "execution_id": "20000000-0000-4000-8000-000000000065",
        "workspace_id": "30000000-0000-4000-8000-000000000065",
        "conversation_id": "40000000-0000-4000-8000-000000000065",
        "interaction_id": "50000000-0000-4000-8000-000000000065",
        "received_at": NOW,
        "request_id": "p8-s65-request",
        "trace_id": TRACE_ID,
        "authority_ref": "OA:EAC:p8-s65",
    }
    values.update(overrides)
    return service.plan(**values)


def test_live_candidates_compile_to_exact_golden_a_local_skill() -> None:
    client = CandidateClient()

    result = _run(_service(client))

    step = result.executable_plan["steps"][0]
    binding = step["skill_binding"]
    fixture = _fixture()
    assert client.calls == ["INTENT", "PLAN"]
    assert result.validation["status"] == "VALID"
    assert result.activation["authoritative_binding"]["project_code"] == (
        fixture["projects"]["child"]["project_code"]
    )
    assert step["executor_kind"] == "LOCAL_SKILL"
    assert step["required_capability"] == GOLDEN_A_CAPABILITY_ID
    assert binding["capability_id"] == GOLDEN_A_CAPABILITY_ID
    assert binding["skill_id"] == GOLDEN_A_NSL_SKILL_ID
    assert binding["skill_semantic_hash"] == fixture["admission"]["skill_semantic_hash"]


def test_tenant_mismatch_fails_before_provider_call() -> None:
    client = CandidateClient()

    with pytest.raises(GoldenAApprovalJourneyError) as raised:
        _run(_service(client), tenant_id="other-tenant")

    assert raised.value.error_code == "P8_GOLDEN_A_TENANT_MISMATCH"
    assert client.calls == []


def test_low_confidence_intent_fails_before_plan_generation() -> None:
    client = CandidateClient(intent=_intent_candidate(confidence=0.2))

    with pytest.raises(GoldenAApprovalJourneyError) as raised:
        _run(_service(client))

    assert raised.value.error_code == "CANDIDATE_LOW_CONFIDENCE"
    assert client.calls == ["INTENT"]


def test_unresolved_project_requires_clarification() -> None:
    candidate = _intent_candidate()
    candidate["entity_selectors"][0]["value"] = "Golden A Travel Project"
    client = CandidateClient(intent=candidate)

    with pytest.raises(GoldenAApprovalJourneyError) as raised:
        _run(_service(client))

    assert raised.value.error_code == "PROJECT_CONFIRMATION_REQUIRED"
    assert client.calls == ["INTENT"]


def test_low_confidence_plan_fails_closed() -> None:
    client = CandidateClient(plan=_plan_candidate(confidence=0.2))

    with pytest.raises(GoldenAApprovalJourneyError) as raised:
        _run(_service(client))

    assert raised.value.error_code == "CANDIDATE_LOW_CONFIDENCE"
    assert client.calls == ["INTENT", "PLAN"]


def test_deterministic_validation_rejection_fails_before_compile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nex_ae_api.golden_a_approval_journey.validate_agent_plan",
        lambda **_kwargs: {"status": "BLOCKED"},
    )

    with pytest.raises(GoldenAApprovalJourneyError) as raised:
        _run(_service(CandidateClient()))

    assert raised.value.error_code == "P8_GOLDEN_A_PLAN_INVALID"
    assert str(raised.value) == (
        "Golden A deterministic PlanValidation rejected the live plan."
    )


def test_exact_skill_guard_rejects_cardinality_and_binding_drift() -> None:
    result = _run(_service(CandidateClient()))
    activation = result.activation
    plan = deepcopy(result.executable_plan)
    plan["steps"] = []

    with pytest.raises(GoldenAApprovalJourneyError) as raised:
        _require_exact_local_skill(plan, activation)
    assert raised.value.error_code == "P8_GOLDEN_A_LOCAL_SKILL_CARDINALITY"

    plan = deepcopy(result.executable_plan)
    plan["steps"][0]["skill_binding"]["skill_id"] = "FINANCE.WRONG_SKILL"
    with pytest.raises(GoldenAApprovalJourneyError) as raised:
        _require_exact_local_skill(plan, activation)
    assert raised.value.error_code == "P8_GOLDEN_A_SKILL_BINDING_MISMATCH"


@pytest.mark.parametrize("fixture", ({}, {"tenant": {"tenant_id": ""}}))
def test_invalid_fixture_tenant_fails_closed(fixture: dict) -> None:
    with pytest.raises(GoldenAApprovalJourneyError) as raised:
        _run(_service(CandidateClient()), fixture=fixture)

    assert raised.value.error_code == "P8_GOLDEN_A_FIXTURE_INVALID"
