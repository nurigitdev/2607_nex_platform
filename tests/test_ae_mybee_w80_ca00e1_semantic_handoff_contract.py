from __future__ import annotations

import nex_ae_api.semantic_handoff_reuse as reuse_module
import pytest
from nex_ae_api.agent_execution import _validate_claimed_planning_source
from nex_ae_api.semantic_handoff_reuse import (
    SemanticHandoffProjectionSource,
    SemanticHandoffReuseError,
)
from nex_ae_api.work_intent import WorkIntentError, build_work_intent_from_claimed_work
from nex_runtime.semantic_handoff import (
    SemanticHandoffError,
    build_semantic_handoff_projection,
    validate_semantic_handoff_projection,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

TENANT = "VO00"
OWNER = "employee-1001"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
WORK_INTENT_ID = "22222222-2222-4222-8222-222222222222"
CONTEXT_ID = "33333333-3333-4333-8333-333333333333"
INTERACTION_ID = "44444444-4444-4444-8444-444444444444"
INTENT_CANDIDATE_ID = "55555555-5555-4555-8555-555555555555"
CONTEXT_CANDIDATE_ID = "66666666-6666-4666-8666-666666666666"
NOW = "2026-11-23T09:00:00Z"


def _hash(label: str) -> str:
    return semantic_sha256_hash_ref({"label": label})


def _parent_records() -> tuple[dict, dict, dict, dict]:
    work_intent = {
        "schema_version": "1.1",
        "work_intent_id": WORK_INTENT_ID,
        "intent_revision": 1,
        "execution_id": EXECUTION_ID,
        "source": {
            "source_type": "PROMPT",
            "source_ref": f"AE:INTERACTION:{INTERACTION_ID}",
        },
    }
    work_intent["intent_hash"] = semantic_sha256_hash_ref(work_intent)
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
        "identity": {
            "tenant_id": TENANT,
            "principal_id": OWNER,
            "agent_id": "77777777-7777-4777-8777-777777777777",
            "agent_type": "IA",
        },
        "interaction": {
            "workspace_id": "88888888-8888-4888-8888-888888888888",
            "conversation_id": "99999999-9999-4999-8999-999999999999",
            "interaction_id": INTERACTION_ID,
        },
    }
    context["context_hash"] = semantic_sha256_hash_ref(context)
    intent_evidence = {
        "tenant_id": TENANT,
        "owner_subject_id": OWNER,
        "candidate_id": INTENT_CANDIDATE_ID,
        "execution_id": EXECUTION_ID,
        "semantic_stage": "INTENT",
        "candidate_hash": _hash("intent-candidate"),
        "validation_outcome": "ADMITTED",
        "directive": "CONTINUE",
    }
    context_evidence = {
        "tenant_id": TENANT,
        "owner_subject_id": OWNER,
        "candidate_id": CONTEXT_CANDIDATE_ID,
        "execution_id": EXECUTION_ID,
        "semantic_stage": "CONTEXT",
        "candidate_hash": _hash("context-candidate"),
        "validation_outcome": "ADMITTED",
        "directive": "CONTINUE",
    }
    return work_intent, context, intent_evidence, context_evidence


def _handoff() -> dict:
    work_intent, context, intent_evidence, context_evidence = _parent_records()
    return build_semantic_handoff_projection(
        work_intent=work_intent,
        agent_context=context,
        intent_evidence=intent_evidence,
        context_evidence=context_evidence,
        created_at=NOW,
    )


def _planning_source() -> dict:
    return {
        "schema_version": "p7.claimed_work_planning_source.v3",
        "source_type": "CLAIMED_WORKITEM",
        "source_ref": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "goal": "Summarize the admitted Project evidence.",
        "work_class": "ANALYSIS",
        "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
        "project_ref": {
            "entity_type": "PROJECT",
            "entity_id": "VO00D260101",
        },
        "artifact_refs": [],
        "evidence_refs": [],
        "completion_policy": "OWNER_SUBMITS",
        "result_contract_ref": "contract://nex/mybee/project-analysis-result/v1",
        "delegation_identity": {
            "delegation_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "delegation_revision": 1,
            "requester_ref": OWNER,
            "parent_agent_execution_id": EXECUTION_ID,
        },
        "semantic_handoff": _handoff(),
    }


def test_semantic_handoff_builds_hash_bound_parent_lineage():
    handoff = _handoff()

    assert handoff["tenant_id"] == TENANT
    assert handoff["owner_subject_id"] == OWNER
    assert handoff["parent_execution_id"] == EXECUTION_ID
    assert handoff["parent_agent_type"] == "IA"
    assert handoff["parent_work_intent_id"] == WORK_INTENT_ID
    assert handoff["intent_candidate_id"] == INTENT_CANDIDATE_ID
    assert handoff["context_candidate_id"] == CONTEXT_CANDIDATE_ID
    assert handoff["source_interaction_id"] == INTERACTION_ID
    assert validate_semantic_handoff_projection(handoff) == handoff


def test_semantic_handoff_projection_source_reuses_authoritative_records():
    work_intent, context, intent_evidence, context_evidence = _parent_records()

    class WorkIntents:
        def get_latest_for_execution(self, **_kwargs):
            return work_intent

    class Contexts:
        def get_latest_for_execution(self, **_kwargs):
            return context

    class Evidence:
        def get_for_stage(self, *, semantic_stage, **_kwargs):
            return {
                "INTENT": intent_evidence,
                "CONTEXT": context_evidence,
            }[semantic_stage]

    source = SemanticHandoffProjectionSource(
        work_intents=WorkIntents(), contexts=Contexts(), evidence=Evidence()
    )
    records = source.resolve(tenant_id=TENANT, execution_id=EXECUTION_ID)

    assert records is not None
    assert source.project(records, created_at=NOW) == _handoff()


def test_semantic_handoff_projection_source_rejects_partial_lineage():
    work_intent, _, _, _ = _parent_records()

    class WorkIntents:
        def get_latest_for_execution(self, **_kwargs):
            return work_intent

    class Missing:
        def get_latest_for_execution(self, **_kwargs):
            return None

        def get_for_stage(self, **_kwargs):
            return None

    source = SemanticHandoffProjectionSource(
        work_intents=WorkIntents(), contexts=Missing(), evidence=Missing()
    )

    with pytest.raises(SemanticHandoffReuseError, match="incomplete"):
        source.resolve(tenant_id=TENANT, execution_id=EXECUTION_ID)


def test_semantic_handoff_projection_source_supports_empty_and_sqlalchemy_factory(
    monkeypatch,
):
    class Missing:
        def get_latest_for_execution(self, **_kwargs):
            return None

        def get_for_stage(self, **_kwargs):
            return None

    source = SemanticHandoffProjectionSource(
        work_intents=Missing(), contexts=Missing(), evidence=Missing()
    )
    assert source.resolve(tenant_id=TENANT, execution_id=EXECUTION_ID) is None

    sentinel = object()
    work_intents = object()
    contexts = object()
    evidence = object()
    monkeypatch.setattr(
        reuse_module, "SqlAlchemyWorkIntentRepository", lambda value: work_intents
    )
    monkeypatch.setattr(
        reuse_module, "SqlAlchemyAgentContextRepository", lambda value: contexts
    )
    monkeypatch.setattr(
        reuse_module,
        "SqlAlchemySemanticCandidateEvidenceRepository",
        lambda value: evidence,
    )

    built = SemanticHandoffProjectionSource.from_sqlalchemy(
        session_factory=sentinel
    )
    assert built._work_intents is work_intents
    assert built._contexts is contexts
    assert built._evidence is evidence


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("tenant_id", "OTHER"),
        ("owner_subject_id", "employee-other"),
        ("parent_work_intent_hash", _hash("tampered")),
        ("source_revision", 2),
    ),
)
def test_semantic_handoff_rejects_tampered_projection(field, value):
    handoff = _handoff()
    handoff[field] = value

    with pytest.raises(SemanticHandoffError, match="hash does not match"):
        validate_semantic_handoff_projection(handoff)


def test_semantic_handoff_builder_rejects_cross_execution_evidence():
    work_intent, context, intent_evidence, context_evidence = _parent_records()
    context_evidence["execution_id"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

    with pytest.raises(SemanticHandoffError, match="execution lineage"):
        build_semantic_handoff_projection(
            work_intent=work_intent,
            agent_context=context,
            intent_evidence=intent_evidence,
            context_evidence=context_evidence,
            created_at=NOW,
        )


def test_claimed_planning_source_v3_is_accepted_by_both_ae_boundaries():
    source = _planning_source()

    assert _validate_claimed_planning_source(source) == source
    work_intent = build_work_intent_from_claimed_work(
        execution_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        actor_ref=f"OA:SUBJECT:{OWNER}",
        received_at=NOW,
        planning_source=source,
        intent_decision={
            "intent_decision_schema_version": "ae_intent_decision.v1",
            "raw_prompt_included": False,
            "execution_mode": "DOCUMENT_SUMMARY",
            "intent_label": "FINANCE.PROJECT_BUDGET_CHECK",
            "confidence": 0.95,
            "decision_hash": "a" * 64,
        },
        input_context_hash=_hash("claimed-input"),
        work_intent_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
    )

    assert work_intent["schema_version"] == "1.1"
    assert work_intent["intent_label"] == "FINANCE.PROJECT_BUDGET_CHECK"
    assert work_intent["source"]["source_type"] == "CLAIMED_WORKITEM"


def test_claimed_planning_source_v1_v2_compatibility_remains_explicit():
    source_v3 = _planning_source()
    source_v1 = {
        key: value
        for key, value in source_v3.items()
        if key not in {"delegation_identity", "semantic_handoff"}
    }
    source_v1["schema_version"] = "p7.claimed_work_planning_source.v1"

    assert _validate_claimed_planning_source(source_v1) == source_v1
    source_v2 = {
        **source_v1,
        "schema_version": "p7.claimed_work_planning_source.v2",
        "delegation_identity": source_v3["delegation_identity"],
        "business_request_context": {
            "schema_version": "mybee.business_request_context.v1",
            "tenant_id": TENANT,
        },
        "business_context_hash": _hash("legacy-business-context"),
    }
    with pytest.raises(WorkIntentError, match="business planning source profile"):
        build_work_intent_from_claimed_work(
            execution_id="ffffffff-ffff-4fff-8fff-ffffffffffff",
            actor_ref=f"OA:SUBJECT:{OWNER}",
            received_at=NOW,
            planning_source=source_v2,
            intent_decision={
                "intent_decision_schema_version": "ae_intent_decision.v1",
                "raw_prompt_included": False,
                "execution_mode": "GENERAL_ANSWER",
                "intent_label": "FINANCE.PROJECT_BUDGET_CHECK",
                "confidence": 0.9,
                "decision_hash": "b" * 64,
            },
            input_context_hash=_hash("legacy-input"),
            work_intent_id="12121212-1212-4212-8212-121212121212",
        )
