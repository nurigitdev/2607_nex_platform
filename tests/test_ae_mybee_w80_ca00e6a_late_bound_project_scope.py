from __future__ import annotations

import json
from dataclasses import replace

import pytest
from nex_ae_api.agent_context import (
    AgentContextError,
    SqlAlchemyAgentContextRepository,
)
from nex_ae_api.semantic_candidate_evidence import (
    build_semantic_candidate_evidence,
    build_semantic_candidate_payload,
)
from nex_ae_api.semantic_handoff_reuse import (
    ResolvedSemanticHandoff,
    SemanticHandoffAuthoritySource,
    SemanticHandoffReuseEvaluator,
    SemanticReusePolicy,
    SemanticReusePolicyRegistry,
)
from nex_runtime.semantic_handoff import build_semantic_handoff_projection
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

TENANT = "VO00"
OWNER = "employee-1001"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
WORK_INTENT_ID = "22222222-2222-4222-8222-222222222222"
CONTEXT_ID = "33333333-3333-4333-8333-333333333333"
INTERACTION_ID = "44444444-4444-4444-8444-444444444444"
INTENT_CANDIDATE_ID = "55555555-5555-4555-8555-555555555555"
CONTEXT_CANDIDATE_ID = "66666666-6666-4666-8666-666666666666"
PROJECT = "77777777-7777-4777-8777-777777777777"
OTHER_PROJECT = "88888888-8888-4888-8888-888888888888"
CAPABILITY = "FINANCE.VOUCHER.APPROVE_AND_POST"
BUILT_AT = "2026-11-24T09:00:00Z"
HANDOFF_AT = "2026-11-24T09:05:00Z"


def _intent_candidate() -> dict:
    return {
        "schema_version": "p65.intent_candidate.v1",
        "intent_label": CAPABILITY,
        "suggested_execution_mode": "GENERAL_ANSWER",
        "entity_selectors": [],
        "parameter_candidates": [],
        "clarification": {"required": False, "reasons": [], "questions": []},
        "confidence": 0.95,
    }


def _context_candidate() -> dict:
    return {
        "schema_version": "p65.context_candidate_set.v1",
        "entity_candidates": [],
        "retrieval_hints": [],
        "resource_selectors": [],
        "parameter_candidates": [],
        "confidence": 0.9,
    }


def _evidence(stage: str, candidate_id: str, candidate: dict) -> dict:
    payload = build_semantic_candidate_payload(
        candidate_id=candidate_id,
        candidate=candidate,
    )
    return build_semantic_candidate_evidence(
        tenant_id=TENANT,
        owner_subject_id=OWNER,
        candidate_id=candidate_id,
        execution_id=EXECUTION_ID,
        semantic_stage=stage,
        candidate_revision=1,
        candidate_payload=payload,
        provider_output_sha256="a" * 64,
        input_context_hash=semantic_sha256_hash_ref({"stage": stage}),
        prompt_provenance={
            "prompt_binding_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            "prompt_binding_key": f"ae.{stage.lower()}.default",
            "prompt_template_version_id": (
                "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
            ),
            "prompt_template_version": "v1",
            "prompt_content_sha256": "b" * 64,
            "rendered_prompt_hash": "c" * 64,
        },
        model_provenance={
            "model_profile": "general-llm-default",
            "model_ref": "provider/model@revision",
            "deployment_id": "generation-http",
            "mo_generation_id": f"generation-{stage.lower()}",
        },
        request_id=f"request-{stage.lower()}",
        trace_id="d" * 32,
        admission_policy_ref=f"semantic-admission://{stage.lower()}/v1",
        directive="CONTINUE",
        failure_code=None,
        created_at=BUILT_AT,
    )


def _work_intent(*, project_ref: dict | None = None) -> dict:
    record = {
        "schema_version": "1.2",
        "work_intent_id": WORK_INTENT_ID,
        "intent_revision": 1,
        "execution_id": EXECUTION_ID,
        "source": {
            "source_type": "PROMPT",
            "source_ref": f"AE:INTERACTION:{INTERACTION_ID}",
        },
        "project_ref": project_ref,
        "intent_label": CAPABILITY,
        "required_capability_hints": [CAPABILITY],
    }
    record["intent_hash"] = semantic_sha256_hash_ref(record)
    return record


def _context(
    work_intent: dict,
    *,
    project_id: str = PROJECT,
    context_id: str = CONTEXT_ID,
    generation: int = 1,
    built_at: str = BUILT_AT,
) -> dict:
    record = {
        "schema_version": "1.1",
        "context_id": context_id,
        "context_generation": generation,
        "execution_id": EXECUTION_ID,
        "work_intent_ref": {
            "id": WORK_INTENT_ID,
            "version": 1,
            "hash": work_intent["intent_hash"],
        },
        "identity": {
            "tenant_id": TENANT,
            "principal_id": OWNER,
            "agent_id": "99999999-9999-4999-8999-999999999999",
            "agent_type": "IA",
        },
        "interaction": {
            "workspace_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "conversation_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "interaction_id": INTERACTION_ID,
        },
        "project_ref": None,
        "authority_ref": "EOS:PROJECT_RESOLUTION",
        "resolved_entities": [
            {
                "selector_id": "E1",
                "resource_ref": {
                    "system": "nex-eos",
                    "resource_type": "PROJECT",
                    "resource_id": project_id,
                    "version": "1",
                },
                "source_ref": "EOS:PROJECT_CODE:VO00D260001",
                "resolved_at": built_at,
            }
        ],
        "retrieval_refs": [],
        "evidence_refs": [],
        "runtime_policy_ref": {
            "rule_id": "ae.general_answer.v1",
            "rule_version": "v1",
            "rule_hash": semantic_sha256_hash_ref({"policy": "general"}),
        },
        "conflicts": [],
        "degradations": [],
        "context_manifest": [
            {
                "kind": "EOS_PROJECT_PROJECTION",
                "source_ref": "EOS:PROJECT_CODE:VO00D260001",
                "source_version": "1",
                "content_hash": semantic_sha256_hash_ref(
                    {"project_id": project_id}
                ),
                "as_of": built_at,
            }
        ],
        "budget": {
            "budget_tokens": 4096,
            "estimated_used_tokens": 128,
            "truncated_optional_items": 0,
        },
        "built_at": built_at,
    }
    record["context_hash"] = semantic_sha256_hash_ref(record)
    return record


def _fixture(*, explicit_project: str | None = None):
    project_ref = (
        None
        if explicit_project is None
        else {
            "system": "nex-eos",
            "resource_type": "PROJECT",
            "resource_id": explicit_project,
        }
    )
    work_intent = _work_intent(project_ref=project_ref)
    context = _context(work_intent)
    intent_candidate = _intent_candidate()
    context_candidate = _context_candidate()
    intent_evidence = _evidence(
        "INTENT", INTENT_CANDIDATE_ID, intent_candidate
    )
    context_evidence = _evidence(
        "CONTEXT", CONTEXT_CANDIDATE_ID, context_candidate
    )
    handoff = build_semantic_handoff_projection(
        work_intent=work_intent,
        agent_context=context,
        intent_evidence=intent_evidence,
        context_evidence=context_evidence,
        created_at=HANDOFF_AT,
    )
    planning_source = {
        "required_capability": CAPABILITY,
        "work_class": "BUSINESS_TRANSACTION",
        "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
        "delegation_identity": {
            "requester_ref": OWNER,
            "parent_agent_execution_id": EXECUTION_ID,
        },
    }
    resolved = ResolvedSemanticHandoff(
        work_intent=work_intent,
        latest_work_intent=work_intent,
        intent_evidence=intent_evidence,
        context_evidence=context_evidence,
        intent_candidate=intent_candidate,
        context_candidate=context_candidate,
        parent_context=context,
    )
    return handoff, planning_source, resolved, context


def _evaluate(*, resolved=None, explicit_project=None) -> dict:
    handoff, source, default_resolved, _ = _fixture(
        explicit_project=explicit_project
    )
    evaluator = SemanticHandoffReuseEvaluator(
        SemanticReusePolicyRegistry(
            [
                SemanticReusePolicy(
                    policy_ref="semantic-reuse://pa/business-transaction/v1",
                    target_agent_type="PA",
                    work_class="BUSINESS_TRANSACTION",
                    minimum_intent_confidence=0.8,
                    minimum_context_confidence=0.75,
                    maximum_age_seconds=3600,
                )
            ]
        )
    )
    return evaluator.evaluate(
        handoff=handoff,
        planning_source=source,
        target_agent_type="PA",
        resolved=default_resolved if resolved is None else resolved,
        evaluated_at="2026-11-24T09:10:00Z",
    )


def test_late_bound_eos_project_scope_is_admitted_without_mutating_work_intent():
    decision = _evaluate()

    assert decision["decision"] == "REUSE_INTENT_REBUILD_CONTEXT"
    assert decision["reason_codes"] == []


def test_explicit_work_intent_scope_cannot_be_overridden_by_late_context():
    decision = _evaluate(explicit_project=OTHER_PROJECT)

    assert decision["decision"] == "DENY_CONFLICT"
    assert decision["reason_codes"] == ["SCOPE_MISMATCH"]


@pytest.mark.parametrize(
    "mutation",
    (
        "missing",
        "wrong_project",
        "conflict",
        "interaction_mismatch",
        "malformed_entities",
    ),
)
def test_late_bound_scope_fails_closed_without_matching_authority(mutation):
    _, _, resolved, context = _fixture()
    if mutation == "missing":
        changed = replace(resolved, parent_context=None)
    else:
        changed_context = json.loads(json.dumps(context))
        if mutation == "wrong_project":
            changed_context["resolved_entities"][0]["resource_ref"][
                "resource_id"
            ] = OTHER_PROJECT
        elif mutation == "interaction_mismatch":
            changed_context["interaction"]["interaction_id"] = (
                "aaaaaaaa-1111-4111-8111-111111111111"
            )
        elif mutation == "malformed_entities":
            changed_context["resolved_entities"] = {"project": PROJECT}
        else:
            changed_context["conflicts"] = ["PROJECT_AMBIGUOUS"]
        changed_context["context_hash"] = semantic_sha256_hash_ref(
            {
                key: value
                for key, value in changed_context.items()
                if key != "context_hash"
            }
        )
        changed = replace(resolved, parent_context=changed_context)

    decision = _evaluate(resolved=changed)

    assert decision["decision"] == "DENY_CONFLICT"
    assert decision["reason_codes"] == ["SCOPE_MISMATCH"]


def test_late_bound_scope_rejects_parent_context_hash_tamper():
    _, _, resolved, context = _fixture()
    tampered = {**context, "authority_ref": "EOS:TAMPERED"}

    decision = _evaluate(resolved=replace(resolved, parent_context=tampered))

    assert decision["decision"] == "DENY_CONFLICT"
    assert decision["reason_codes"] == ["HASH_MISMATCH"]


def test_late_bound_scope_rejects_parent_context_identity_mismatch():
    _, _, resolved, context = _fixture()
    changed_context = json.loads(json.dumps(context))
    changed_context["identity"]["principal_id"] = "employee-elsewhere"
    changed_context["context_hash"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in changed_context.items()
            if key != "context_hash"
        }
    )

    decision = _evaluate(
        resolved=replace(resolved, parent_context=changed_context)
    )

    assert decision["decision"] == "DENY_CONFLICT"
    assert decision["reason_codes"] == ["HASH_MISMATCH"]


def test_authority_source_resolves_context_at_handoff_time():
    handoff, _, resolved, context = _fixture()

    class WorkIntents:
        def get(self, **_kwargs):
            return resolved.work_intent

        def get_latest_for_execution(self, **_kwargs):
            return resolved.latest_work_intent

    class Evidence:
        def get(self, *, candidate_id, **_kwargs):
            if candidate_id == INTENT_CANDIDATE_ID:
                return resolved.intent_evidence
            return resolved.context_evidence

    class Candidates:
        def load(self, metadata, **_kwargs):
            if metadata["candidate_id"] == INTENT_CANDIDATE_ID:
                return resolved.intent_candidate
            return resolved.context_candidate

    class Contexts:
        def get_latest_for_execution_at_or_before(self, **kwargs):
            assert kwargs["built_at"] == HANDOFF_AT
            return context

    actual = SemanticHandoffAuthoritySource(
        work_intents=WorkIntents(),
        evidence=Evidence(),
        candidate_storage=Candidates(),
        contexts=Contexts(),
    ).resolve(handoff)

    assert actual.parent_context == context


def test_agent_context_repository_selects_latest_generation_before_handoff():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    sessions = sessionmaker(bind=engine, future=True)
    work_intent = _work_intent()
    first = _context(work_intent)
    second = _context(
        work_intent,
        context_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        generation=2,
        built_at="2026-11-24T09:06:00Z",
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE ae_agent_context ("
                "tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL, "
                "context_generation INTEGER NOT NULL, built_at TEXT NOT NULL, "
                "context_json TEXT NOT NULL)"
            )
        )
        for context in (first, second):
            connection.execute(
                text(
                    "INSERT INTO ae_agent_context VALUES "
                    "(:tenant_id, :execution_id, :generation, :built_at, :payload)"
                ),
                {
                    "tenant_id": TENANT,
                    "execution_id": EXECUTION_ID,
                    "generation": context["context_generation"],
                    "built_at": context["built_at"],
                    "payload": json.dumps(context),
                },
            )
    repository = SqlAlchemyAgentContextRepository(sessions)

    assert repository.get_latest_for_execution_at_or_before(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        built_at=HANDOFF_AT,
    ) == first
    assert repository.get_latest_for_execution_at_or_before(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        built_at="2026-11-24T08:59:59Z",
    ) is None
    with pytest.raises(AgentContextError, match="built_at"):
        repository.get_latest_for_execution_at_or_before(
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            built_at="invalid",
        )


def test_agent_context_repository_maps_store_failure_to_typed_error():
    def unavailable_session():
        raise SQLAlchemyError("store unavailable")

    repository = SqlAlchemyAgentContextRepository(unavailable_session)

    with pytest.raises(
        AgentContextError, match="AgentContext store is unavailable"
    ) as raised:
        repository.get_latest_for_execution_at_or_before(
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            built_at=HANDOFF_AT,
        )

    assert raised.value.error_code == "ae.agent_context_store_unavailable"
    assert raised.value.retryable is True
