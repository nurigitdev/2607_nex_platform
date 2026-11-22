from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from mybee_ax.orchestration import load_m1_transaction_preparation_registration
from nex_ae_api.m1_product_planning_coordinator import (
    M1_PRODUCT_PLANNING_POLICY,
    build_m1_product_planning_coordinator_registration,
)
from nex_ae_api.product_capabilities import load_product_capability_registry
from nex_ae_api.product_planning_proposals import (
    ProductPlanningProposalError,
    build_product_planning_proposal,
    product_planning_proposal_reference,
    validate_product_planning_proposal,
    validate_product_planning_proposal_reference,
)
from nex_ae_api.semantic_candidate_evidence import (
    build_semantic_candidate_evidence,
    build_semantic_candidate_payload,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_REGISTRY = (
    ROOT / "deployment/environments/ae-product-capability-registry.mybee-m1.v4.json"
)
CAPABILITY_ID = "FINANCE.VOUCHER.APPROVE_AND_POST"


def _registration():
    capabilities = load_product_capability_registry(
        {"NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(CAPABILITY_REGISTRY)}
    )
    return build_m1_product_planning_coordinator_registration(
        product_capabilities=capabilities,
        preparation_registration=load_m1_transaction_preparation_registration(),
    )


def _candidate(capability_id: str = CAPABILITY_ID) -> dict[str, object]:
    return {
        "schema_version": "p7.plan_candidate.v1",
        "suggested_plan_kind": "DIRECT",
        "goal": "Prepare the admitted governed transaction.",
        "logical_steps": [
            {
                "step_id": "S1",
                "step_type": "LOCAL_CAPABILITY",
                "title": "Prepare transaction",
                "objective": "Prepare the admitted governed transaction.",
                "depends_on": [],
                "capability_hint": capability_id,
                "completion_criteria": ["C1"],
            }
        ],
        "completion_mapping": [{"criterion_id": "C1", "terminal_step_refs": ["S1"]}],
        "confidence": 0.97,
    }


def _lineage(candidate: dict[str, object]):
    execution_id = str(uuid4())
    work_intent_id = str(uuid4())
    context_id = str(uuid4())
    work_intent_hash = "sha256:" + "1" * 64
    context_hash = "sha256:" + "2" * 64
    work_intent = {
        "execution_id": execution_id,
        "work_intent_id": work_intent_id,
        "intent_hash": work_intent_hash,
    }
    agent_context = {
        "execution_id": execution_id,
        "context_id": context_id,
        "context_hash": context_hash,
        "work_intent_ref": {
            "id": work_intent_id,
            "version": 1,
            "hash": work_intent_hash,
        },
    }
    candidate_id = str(uuid4())
    payload = build_semantic_candidate_payload(
        candidate_id=candidate_id,
        candidate=candidate,
    )
    policy = M1_PRODUCT_PLANNING_POLICY
    evidence = build_semantic_candidate_evidence(
        tenant_id="VO00",
        owner_subject_id="employee:1001",
        candidate_id=candidate_id,
        execution_id=execution_id,
        semantic_stage="PLAN",
        candidate_revision=1,
        candidate_payload=payload,
        provider_output_sha256="a" * 64,
        input_context_hash="sha256:" + "3" * 64,
        prompt_provenance={
            "prompt_binding_id": str(uuid4()),
            "prompt_binding_key": policy.prompt_binding_key,
            "prompt_template_version_id": str(uuid4()),
            "prompt_template_version": "1.0.0",
            "prompt_content_sha256": "b" * 64,
            "rendered_prompt_hash": "c" * 64,
        },
        model_provenance={
            "model_profile": "canonical-generation",
            "model_ref": "Qwen3.5-9B",
            "deployment_id": "dgx-generation-9111",
            "mo_generation_id": "generation-1",
        },
        request_id="proposal-request-1",
        trace_id="d" * 32,
        admission_policy_ref="semantic-admission://plan/qwen35-9b/revision-1",
        directive="CONTINUE",
        failure_code=None,
        created_at="2026-11-18T00:00:00Z",
    )
    return work_intent, agent_context, evidence


def test_product_proposal_is_hash_bound_evidence_not_agent_plan() -> None:
    registration = _registration()
    candidate = _candidate()
    work_intent, agent_context, evidence = _lineage(candidate)

    proposal = build_product_planning_proposal(
        evidence=evidence,
        candidate=candidate,
        work_intent=work_intent,
        agent_context=agent_context,
        registration=registration,
        admitted_capability_ids=(CAPABILITY_ID, "PROJECT.WORK_CODE_SET.GET"),
    )

    assert proposal["schema_version"] == "ae.product_planning_proposal.v1"
    assert proposal["planning_policy"] == M1_PRODUCT_PLANNING_POLICY.projection()
    assert proposal["suggested_capability_ids"] == [CAPABILITY_ID]
    assert proposal["candidate_ref"]["candidate_hash"] == semantic_sha256_hash_ref(
        candidate
    )
    assert proposal["provider_plan_authoritative"] is False
    assert proposal["content_included"] is False
    assert "agent_plan_id" not in proposal
    assert "executable_plan_id" not in proposal
    assert validate_product_planning_proposal(proposal) == proposal
    reference = product_planning_proposal_reference(proposal)
    assert reference["proposal_hash"] == proposal["proposal_hash"]
    assert (
        reference["candidate_payload_storage_ref"]
        == (proposal["candidate_ref"]["storage_ref"])
    )
    assert validate_product_planning_proposal_reference(reference) == reference


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda registration, evidence, work, context: (
                registration,
                {**evidence, "prompt_binding_key": "ae.plan_builder.drifted"},
                work,
                context,
            ),
            "policy binding",
        ),
        (
            lambda registration, evidence, work, context: (
                registration,
                evidence,
                work,
                {**context, "execution_id": str(uuid4())},
            ),
            "execution lineage",
        ),
        (
            lambda registration, evidence, work, context: (
                replace(
                    registration,
                    planning_policy=replace(
                        registration.planning_policy,
                        mode="DETERMINISTIC_ONLY",
                        proposal_consumers=(),
                    ),
                ),
                evidence,
                work,
                context,
            ),
            "Deterministic-only",
        ),
    ),
)
def test_product_proposal_fails_closed_on_policy_or_lineage_drift(
    mutation, message: str
) -> None:
    candidate = _candidate()
    registration = _registration()
    work, context, evidence = _lineage(candidate)
    registration, evidence, work, context = mutation(
        registration, evidence, work, context
    )

    with pytest.raises(ProductPlanningProposalError, match=message):
        build_product_planning_proposal(
            evidence=evidence,
            candidate=candidate,
            work_intent=work,
            agent_context=context,
            registration=registration,
            admitted_capability_ids=(CAPABILITY_ID,),
        )


def test_product_proposal_rejects_unadmitted_capability_and_hash_tamper() -> None:
    registration = _registration()
    candidate = _candidate("FINANCE.UNADMITTED.WRITE")
    work, context, evidence = _lineage(candidate)

    with pytest.raises(ProductPlanningProposalError, match="unadmitted capability"):
        build_product_planning_proposal(
            evidence=evidence,
            candidate=candidate,
            work_intent=work,
            agent_context=context,
            registration=registration,
            admitted_capability_ids=(CAPABILITY_ID,),
        )

    admitted_candidate = _candidate()
    work, context, evidence = _lineage(admitted_candidate)
    proposal = build_product_planning_proposal(
        evidence=evidence,
        candidate=admitted_candidate,
        work_intent=work,
        agent_context=context,
        registration=registration,
        admitted_capability_ids=(CAPABILITY_ID,),
    )
    proposal["provider_plan_authoritative"] = True
    with pytest.raises(ProductPlanningProposalError, match="execution authority"):
        validate_product_planning_proposal(proposal)

    proposal["provider_plan_authoritative"] = False
    proposal["suggested_capability_ids"] = [CAPABILITY_ID, CAPABILITY_ID]
    with pytest.raises(ProductPlanningProposalError, match="capability identities"):
        validate_product_planning_proposal(proposal)


def _valid_proposal():
    registration = _registration()
    candidate = _candidate()
    work, context, evidence = _lineage(candidate)
    proposal = build_product_planning_proposal(
        evidence=evidence,
        candidate=candidate,
        work_intent=work,
        agent_context=context,
        registration=registration,
        admitted_capability_ids=(CAPABILITY_ID,),
    )
    return registration, candidate, work, context, evidence, proposal


def test_product_proposal_build_rejects_evidence_and_contract_drift() -> None:
    registration, candidate, work, context, evidence, _proposal = _valid_proposal()
    cases = (
        (
            replace(
                registration,
                planning_policy=replace(
                    registration.planning_policy,
                    proposal_schema_version="ae.product_planning_proposal.v2",
                ),
            ),
            evidence,
            work,
            context,
            candidate,
            "schema differs",
        ),
        (
            registration,
            {**evidence, "semantic_stage": "INTENT"},
            work,
            context,
            candidate,
            "admitted PLAN evidence",
        ),
        (
            registration,
            {**evidence, "candidate_hash": "sha256:" + "f" * 64},
            work,
            context,
            candidate,
            "candidate hash",
        ),
        (
            registration,
            evidence,
            work,
            {**context, "work_intent_ref": None},
            candidate,
            "WorkIntent context",
        ),
    )
    for (
        selected,
        selected_evidence,
        selected_work,
        selected_context,
        value,
        message,
    ) in cases:
        with pytest.raises(ProductPlanningProposalError, match=message):
            build_product_planning_proposal(
                evidence=selected_evidence,
                candidate=value,
                work_intent=selected_work,
                agent_context=selected_context,
                registration=selected,
                admitted_capability_ids=(CAPABILITY_ID,),
            )

    with pytest.raises(ProductPlanningProposalError, match="candidate is invalid"):
        build_product_planning_proposal(
            evidence=evidence,
            candidate={"invalid": object()},
            work_intent=work,
            agent_context=context,
            registration=registration,
            admitted_capability_ids=(CAPABILITY_ID,),
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    (
        (lambda value: value.pop("schema_version"), "fields do not match"),
        (lambda value: value.update(tenant_id=""), "tenant_id is invalid"),
        (
            lambda value: value.update(work_intent_ref={"work_intent_id": "x"}),
            "work_intent_ref is invalid",
        ),
        (
            lambda value: value.update(coordinator_ref=None),
            "coordinator_ref is invalid",
        ),
        (
            lambda value: value["coordinator_ref"].update(extra="value"),
            "coordinator reference is invalid",
        ),
        (
            lambda value: value.update(planning_policy={}),
            "planning policy is unavailable",
        ),
        (lambda value: value["candidate_ref"].pop("size_bytes"), "candidate reference"),
        (
            lambda value: value["candidate_ref"].update(size_bytes=True),
            "candidate size",
        ),
        (
            lambda value: value.update(suggested_capability_ids="CAPABILITY"),
            "capability identities",
        ),
        (
            lambda value: value.update(provider_provenance={}),
            "provider provenance",
        ),
        (
            lambda value: value.update(proposal_hash="sha256:" + "0" * 64),
            "hash has drifted",
        ),
    ),
)
def test_product_proposal_validator_rejects_malformed_projection(
    mutator, message: str
) -> None:
    *_values, proposal = _valid_proposal()
    malformed = deepcopy(proposal)
    mutator(malformed)
    with pytest.raises(ProductPlanningProposalError, match=message):
        validate_product_planning_proposal(malformed)


def test_product_proposal_validator_rejects_non_mapping_and_bad_hash_fields() -> None:
    with pytest.raises(ProductPlanningProposalError, match="must be an object"):
        validate_product_planning_proposal([])  # type: ignore[arg-type]

    *_values, proposal = _valid_proposal()
    proposal["candidate_ref"]["candidate_hash"] = "not-a-hash"
    with pytest.raises(ProductPlanningProposalError, match="candidate_hash"):
        validate_product_planning_proposal(proposal)
