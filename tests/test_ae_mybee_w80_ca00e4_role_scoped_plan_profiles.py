from __future__ import annotations

from types import SimpleNamespace

import pytest
from nex_ae_api.plan_candidate_generation import LivePlanCandidateService
from nex_ae_api.plan_candidate_profiles import (
    PLAN_PROFILE_COMPATIBILITY_CAPABILITY_ID,
    PlanCandidateProfileError,
    PlanCandidateProfileRegistration,
    PlanCandidateProfileRegistry,
    ProfileAwarePlanCandidateService,
)
from nex_ae_api.semantic_candidate_admission import (
    _plan_profile_context,
    _planning_purpose,
)

CAPABILITY = "FINANCE.VOUCHER.APPROVE_AND_POST"


def _registration(
    *,
    source: str,
    agent: str,
    purpose: str,
    binding: str,
    capability: str = CAPABILITY,
    compatibility: bool = False,
) -> PlanCandidateProfileRegistration:
    return PlanCandidateProfileRegistration(
        capability_id=capability,
        planning_source_type=source,
        agent_type=agent,
        planning_purpose=purpose,
        profile_version="w80-ca00e4.v1",
        prompt_binding_key=binding,
        source_identity=f"registry://w80/{source}/{agent}/{purpose}",
        compatibility=compatibility,
    )


def _registry() -> PlanCandidateProfileRegistry:
    return PlanCandidateProfileRegistry(
        (
            _registration(
                source="IA_PROMPT",
                agent="IA",
                purpose="DELEGATION",
                binding="binding://ia/delegation",
            ),
            _registration(
                source="CLAIMED_WORKITEM",
                agent="PA",
                purpose="PRODUCT_PREPARATION",
                binding="binding://pa/product-preparation",
            ),
            _registration(
                source="CLAIMED_WORKITEM",
                agent="PA",
                purpose="CLAIMED_WORK_EXECUTION",
                binding="binding://pa/compatibility",
                capability=PLAN_PROFILE_COMPATIBILITY_CAPABILITY_ID,
                compatibility=True,
            ),
        )
    )


def test_registry_uses_exact_four_part_key_then_same_scope_compatibility() -> None:
    registry = _registry()

    exact = registry.resolve(
        CAPABILITY,
        planning_source_type="IA_PROMPT",
        agent_type="IA",
        planning_purpose="DELEGATION",
        required=True,
    )
    compatibility = registry.resolve(
        "DOCUMENT.SUMMARY.CREATE",
        planning_source_type="CLAIMED_WORKITEM",
        agent_type="PA",
        planning_purpose="CLAIMED_WORK_EXECUTION",
        required=True,
    )

    assert exact is not None and exact.prompt_binding_key == "binding://ia/delegation"
    assert compatibility is not None and compatibility.compatibility is True
    assert registry.to_projection()["schema_version"].endswith(".v2")
    assert registry.to_projection()["registry_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    ("source", "agent", "purpose"),
    [
        ("CLAIMED_WORKITEM", "PA", "DELEGATION"),
        ("CLAIMED_WORKITEM", "CA", "PRODUCT_PREPARATION"),
        ("IA_PROMPT", "IA", "PRODUCT_PREPARATION"),
    ],
)
def test_registry_never_falls_across_source_role_or_purpose(
    source: str, agent: str, purpose: str
) -> None:
    with pytest.raises(PlanCandidateProfileError) as raised:
        _registry().resolve(
            CAPABILITY,
            planning_source_type=source,
            agent_type=agent,
            planning_purpose=purpose,
            required=True,
        )
    assert raised.value.error_code == "PLAN_PROFILE_NOT_REGISTERED"


def test_profile_service_strips_selector_metadata_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def generate(self, **kwargs):
        captured.update(kwargs)
        return self.prompt_binding_key

    monkeypatch.setattr(LivePlanCandidateService, "generate_and_bind", generate)
    service = ProfileAwarePlanCandidateService(
        LivePlanCandidateService(object(), object()), _registry()
    )

    selected = service.generate_and_bind(
        work_intent={"intent_label": CAPABILITY},
        planning_source_type="CLAIMED_WORKITEM",
        agent_type="PA",
        planning_purpose="PRODUCT_PREPARATION",
        request_id="request",
    )

    assert selected == "binding://pa/product-preparation"
    assert captured == {
        "work_intent": {"intent_label": CAPABILITY},
        "request_id": "request",
    }
    assert service.has_exact_profile(
        capability_id=CAPABILITY,
        planning_source_type="CLAIMED_WORKITEM",
        agent_type="PA",
        planning_purpose="PRODUCT_PREPARATION",
    )


def test_profile_service_selects_product_preparation_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def generate(self, **kwargs):
        captured.update(kwargs)
        return self.prompt_binding_key

    monkeypatch.setattr(LivePlanCandidateService, "generate_proposal", generate)
    service = ProfileAwarePlanCandidateService(
        LivePlanCandidateService(object(), object()), _registry()
    )

    selected = service.generate_proposal(
        work_intent={"intent_label": CAPABILITY},
        planning_source_type="CLAIMED_WORKITEM",
        agent_type="PA",
        planning_purpose="PRODUCT_PREPARATION",
        trace_id="1" * 32,
    )

    assert selected == "binding://pa/product-preparation"
    assert captured == {
        "work_intent": {"intent_label": CAPABILITY},
        "trace_id": "1" * 32,
    }


def test_semantic_admission_selects_role_scoped_purpose() -> None:
    service = ProfileAwarePlanCandidateService(
        LivePlanCandidateService(object(), object()), _registry()
    )
    ia_request = SimpleNamespace(planning_source_type="IA_PROMPT", agent_type="IA")
    pa_request = SimpleNamespace(
        planning_source_type="CLAIMED_WORKITEM", agent_type="PA"
    )

    assert (
        _planning_purpose(
            request=ia_request,
            work_intent={"intent_label": CAPABILITY},
            plan_stage=service,
        )
        == "DELEGATION"
    )
    assert (
        _planning_purpose(
            request=ia_request,
            work_intent={"intent_label": "AE.CHAT.COMPATIBILITY"},
            plan_stage=service,
        )
        == "INTERACTION_RESPONSE"
    )
    assert (
        _planning_purpose(
            request=pa_request,
            work_intent={"intent_label": CAPABILITY},
            plan_stage=service,
        )
        == "CLAIMED_WORK_EXECUTION"
    )


def test_profile_context_is_only_forwarded_to_profile_aware_runtime() -> None:
    request = SimpleNamespace(planning_source_type="CLAIMED_WORKITEM", agent_type="EA")
    aware = ProfileAwarePlanCandidateService(
        LivePlanCandidateService(object(), object()), _registry()
    )

    assert _plan_profile_context(
        plan_stage=aware,
        request=request,
        planning_purpose="RESULT_SYNTHESIS",
    ) == {
        "planning_source_type": "CLAIMED_WORKITEM",
        "agent_type": "EA",
        "planning_purpose": "RESULT_SYNTHESIS",
    }
    assert (
        _plan_profile_context(
            plan_stage=LivePlanCandidateService(object(), object()),
            request=request,
            planning_purpose="RESULT_SYNTHESIS",
        )
        == {}
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"planning_source_type": "UNKNOWN"},
        {"agent_type": "UNKNOWN"},
        {"planning_purpose": "UNKNOWN"},
        {"capability_id": PLAN_PROFILE_COMPATIBILITY_CAPABILITY_ID},
        {"compatibility": True},
    ],
)
def test_registration_rejects_invalid_scope_or_compatibility_identity(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "capability_id": CAPABILITY,
        "planning_source_type": "IA_PROMPT",
        "agent_type": "IA",
        "planning_purpose": "DELEGATION",
        "profile_version": "v1",
        "prompt_binding_key": "binding://test",
        "source_identity": "registry://test",
        "compatibility": False,
    }
    values.update(changes)
    with pytest.raises(PlanCandidateProfileError) as raised:
        PlanCandidateProfileRegistration(**values)
    assert raised.value.error_code == "PLAN_PROFILE_INVALID"


def test_registry_rejects_non_registration_and_duplicate_key() -> None:
    registration = _registration(
        source="IA_PROMPT",
        agent="IA",
        purpose="DELEGATION",
        binding="binding://one",
    )
    with pytest.raises(PlanCandidateProfileError) as invalid:
        PlanCandidateProfileRegistry((object(),))
    assert invalid.value.error_code == "PLAN_PROFILE_INVALID"
    assert str(invalid.value) == "Plan profile registration is invalid."
    with pytest.raises(PlanCandidateProfileError) as duplicate:
        PlanCandidateProfileRegistry((registration, registration))
    assert duplicate.value.error_code == "PLAN_PROFILE_DUPLICATE"
