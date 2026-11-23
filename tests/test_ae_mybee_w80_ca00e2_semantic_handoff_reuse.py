from __future__ import annotations

from dataclasses import replace

import nex_ae_api.semantic_handoff_reuse as reuse_module
import pytest
from nex_ae_api.semantic_candidate_evidence import (
    InMemorySemanticCandidateStorage,
    build_semantic_candidate_evidence,
    build_semantic_candidate_payload,
)
from nex_ae_api.semantic_handoff_reuse import (
    ResolvedSemanticHandoff,
    SemanticHandoffAuthoritySource,
    SemanticHandoffReuseError,
    SemanticHandoffReuseEvaluator,
    SemanticReusePolicy,
    SemanticReusePolicyRegistry,
)
from nex_runtime.semantic_handoff import build_semantic_handoff_projection
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

TENANT = "VO00"
OWNER = "employee-1001"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
WORK_INTENT_ID = "22222222-2222-4222-8222-222222222222"
INTENT_CANDIDATE_ID = "33333333-3333-4333-8333-333333333333"
CONTEXT_CANDIDATE_ID = "44444444-4444-4444-8444-444444444444"
NOW = "2026-11-23T09:00:00Z"
EVALUATED_AT = "2026-11-23T10:00:00Z"
CAPABILITY = "FINANCE.PROJECT_BUDGET_CHECK"
PROJECT = "VO00D260101"


def _intent_candidate(**overrides) -> dict:
    candidate = {
        "schema_version": "p65.intent_candidate.v1",
        "intent_label": CAPABILITY,
        "suggested_execution_mode": "GROUNDED_ANSWER",
        "entity_selectors": [],
        "parameter_candidates": [],
        "clarification": {"required": False, "reasons": [], "questions": []},
        "confidence": 0.94,
    }
    candidate.update(overrides)
    return candidate


def _context_candidate(**overrides) -> dict:
    candidate = {
        "schema_version": "p65.context_candidate_set.v1",
        "entity_candidates": [],
        "retrieval_hints": [],
        "resource_selectors": [],
        "parameter_candidates": [],
        "confidence": 0.91,
    }
    candidate.update(overrides)
    return candidate


def _evidence(stage: str, candidate_id: str, candidate: dict) -> tuple[dict, dict]:
    payload = build_semantic_candidate_payload(
        candidate_id=candidate_id, candidate=candidate
    )
    evidence = build_semantic_candidate_evidence(
        tenant_id=TENANT,
        owner_subject_id=OWNER,
        candidate_id=candidate_id,
        execution_id=EXECUTION_ID,
        semantic_stage=stage,
        candidate_revision=1,
        candidate_payload=payload,
        provider_output_sha256="a" * 64,
        input_context_hash="sha256:" + "b" * 64,
        prompt_provenance={
            "prompt_binding_id": "55555555-5555-4555-8555-555555555555",
            "prompt_binding_key": f"ae.{stage.lower()}.default",
            "prompt_template_version_id": ("66666666-6666-4666-8666-666666666666"),
            "prompt_template_version": "v1",
            "prompt_content_sha256": "c" * 64,
            "rendered_prompt_hash": "d" * 64,
        },
        model_provenance={
            "model_profile": "generation-default",
            "model_ref": "provider/model@revision",
            "deployment_id": "generation-http",
            "mo_generation_id": f"generation-{stage.lower()}",
        },
        request_id=f"request-{stage.lower()}",
        trace_id="e" * 32,
        admission_policy_ref=f"semantic-admission://{stage.lower()}/v1",
        directive="CONTINUE",
        failure_code=None,
        created_at=NOW,
    )
    return evidence, payload


def _fixture(
    *,
    intent_candidate: dict | None = None,
    context_candidate: dict | None = None,
) -> tuple[dict, dict, ResolvedSemanticHandoff, dict, dict]:
    intent_candidate = intent_candidate or _intent_candidate()
    context_candidate = context_candidate or _context_candidate()
    intent_evidence, intent_payload = _evidence(
        "INTENT", INTENT_CANDIDATE_ID, intent_candidate
    )
    context_evidence, context_payload = _evidence(
        "CONTEXT", CONTEXT_CANDIDATE_ID, context_candidate
    )
    work_intent = {
        "schema_version": "1.1",
        "work_intent_id": WORK_INTENT_ID,
        "intent_revision": 1,
        "supersedes_work_intent_id": None,
        "execution_id": EXECUTION_ID,
        "source": {
            "source_type": "PROMPT",
            "source_ref": "AE:INTERACTION:77777777-7777-4777-8777-777777777777",
        },
        "project_ref": {
            "system": "nex-eos",
            "resource_type": "PROJECT",
            "resource_id": PROJECT,
        },
        "intent_label": CAPABILITY,
        "required_capability_hints": [CAPABILITY],
    }
    work_intent["intent_hash"] = semantic_sha256_hash_ref(work_intent)
    context = {
        "schema_version": "1.1",
        "context_id": "88888888-8888-4888-8888-888888888888",
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
            "agent_id": "99999999-9999-4999-8999-999999999999",
            "agent_type": "IA",
        },
        "interaction": {
            "workspace_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "conversation_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "interaction_id": "77777777-7777-4777-8777-777777777777",
        },
    }
    context["context_hash"] = semantic_sha256_hash_ref(context)
    handoff = build_semantic_handoff_projection(
        work_intent=work_intent,
        agent_context=context,
        intent_evidence=intent_evidence,
        context_evidence=context_evidence,
        created_at=NOW,
    )
    source = {
        "schema_version": "p7.claimed_work_planning_source.v3",
        "source_type": "CLAIMED_WORKITEM",
        "source_ref": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "goal": "Review Project budget evidence.",
        "work_class": "ANALYSIS",
        "required_capability": CAPABILITY,
        "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
        "delegation_identity": {
            "delegation_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            "delegation_revision": 1,
            "requester_ref": OWNER,
            "parent_agent_execution_id": EXECUTION_ID,
        },
        "semantic_handoff": handoff,
    }
    resolved = ResolvedSemanticHandoff(
        work_intent=work_intent,
        latest_work_intent=work_intent,
        intent_evidence=intent_evidence,
        context_evidence=context_evidence,
        intent_candidate=intent_candidate,
        context_candidate=context_candidate,
    )
    return handoff, source, resolved, intent_payload, context_payload


def _evaluator() -> SemanticHandoffReuseEvaluator:
    return SemanticHandoffReuseEvaluator(
        SemanticReusePolicyRegistry(
            [
                SemanticReusePolicy(
                    policy_ref="semantic-reuse://pa/analysis/v1",
                    target_agent_type="PA",
                    work_class="ANALYSIS",
                    minimum_intent_confidence=0.8,
                    minimum_context_confidence=0.75,
                    maximum_age_seconds=7200,
                )
            ]
        )
    )


def _evaluate(**overrides) -> dict:
    handoff, source, resolved, _, _ = _fixture()
    values = {
        "handoff": handoff,
        "planning_source": source,
        "target_agent_type": "PA",
        "resolved": resolved,
        "evaluated_at": EVALUATED_AT,
    }
    values.update(overrides)
    return _evaluator().evaluate(**values)


def test_reuse_evaluator_accepts_intent_and_requires_fresh_target_context():
    decision = _evaluate()

    assert decision["decision"] == "REUSE_INTENT_REBUILD_CONTEXT"
    assert decision["reason_codes"] == []
    assert decision["policy_ref"] == "semantic-reuse://pa/analysis/v1"
    assert decision["decision_hash"] == semantic_sha256_hash_ref(
        {key: value for key, value in decision.items() if key != "decision_hash"}
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        ("requester", "SCOPE_MISMATCH"),
        ("capability", "CAPABILITY_MISMATCH"),
        ("project", "SCOPE_MISMATCH"),
        ("work_intent_hash", "HASH_MISMATCH"),
        ("evidence_hash", "HASH_MISMATCH"),
        ("candidate_hash", "HASH_MISMATCH"),
    ),
)
def test_reuse_evaluator_fails_closed_for_security_drift(mutation, reason):
    handoff, source, resolved, _, _ = _fixture()
    if mutation == "requester":
        source["delegation_identity"]["requester_ref"] = "employee-other"
    elif mutation == "capability":
        source["required_capability"] = "FINANCE.OTHER"
    elif mutation == "project":
        source["project_ref"]["entity_id"] = "VO00D260999"
    elif mutation == "work_intent_hash":
        resolved = replace(
            resolved,
            work_intent={**resolved.work_intent, "intent_hash": "sha256:" + "f" * 64},
        )
    elif mutation == "evidence_hash":
        resolved = replace(
            resolved,
            intent_evidence={
                **resolved.intent_evidence,
                "request_id": "tampered-request",
            },
        )
    else:
        resolved = replace(
            resolved,
            intent_candidate={**resolved.intent_candidate, "confidence": 0.93},
        )

    decision = _evaluate(handoff=handoff, planning_source=source, resolved=resolved)

    assert decision["decision"] == "DENY_CONFLICT"
    assert reason in decision["reason_codes"]


def test_reuse_evaluator_distinguishes_authority_role_and_recoverable_fallbacks():
    handoff, source, resolved, _, _ = _fixture()
    authority = _evaluate(authority_changed=True)
    unsupported = _evaluate(target_agent_type="EA")
    missing = _evaluate(resolved=replace(resolved, context_candidate=None))
    superseded = _evaluate(
        resolved=replace(
            resolved,
            latest_work_intent={
                **resolved.work_intent,
                "work_intent_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            },
        )
    )
    stale = _evaluate(evaluated_at="2026-11-24T09:00:01Z")

    assert (authority["decision"], authority["reason_codes"]) == (
        "DENY_AUTHORITY_CHANGE",
        ["AUTHORITY_CHANGED"],
    )
    assert (unsupported["decision"], unsupported["reason_codes"]) == (
        "DENY_CONFLICT",
        ["UNSUPPORTED_AGENT_ROLE"],
    )
    assert missing["decision"] == "FULL_SEMANTIC_REPLAN"
    assert missing["reason_codes"] == ["MISSING"]
    assert superseded["reason_codes"] == ["SUPERSEDED"]
    assert stale["reason_codes"] == ["STALE"]
    assert source["semantic_handoff"] == handoff


def test_reuse_evaluator_handles_schema_confidence_and_clarification():
    values = _fixture(context_candidate={**_context_candidate(), "extra": True})
    schema_drift = _evaluate(
        handoff=values[0], planning_source=values[1], resolved=values[2]
    )
    values = _fixture(intent_candidate=_intent_candidate(confidence=0.2))
    low_intent = _evaluate(
        handoff=values[0], planning_source=values[1], resolved=values[2]
    )
    values = _fixture(context_candidate=_context_candidate(confidence=0.3))
    low_context = _evaluate(
        handoff=values[0], planning_source=values[1], resolved=values[2]
    )
    values = _fixture(
        intent_candidate=_intent_candidate(
            clarification={
                "required": True,
                "reasons": ["PROJECT_AMBIGUOUS"],
                "questions": ["Which Project?"],
            }
        )
    )
    clarification = _evaluate(
        handoff=values[0], planning_source=values[1], resolved=values[2]
    )

    assert schema_drift["reason_codes"] == ["SCHEMA_DRIFT"]
    assert low_intent["decision"] == "FULL_SEMANTIC_REPLAN"
    assert low_intent["reason_codes"] == ["LOW_CONFIDENCE"]
    assert low_context["decision"] == "REUSE_INTENT_AUGMENT_CONTEXT"
    assert low_context["reason_codes"] == ["LOW_CONFIDENCE"]
    assert clarification["decision"] == "RETURN_FOR_CLARIFICATION"
    assert clarification["reason_codes"] == ["CONFLICT"]


def test_authority_source_resolves_referenced_records_and_private_payloads():
    handoff, _, resolved, intent_payload, context_payload = _fixture()
    storage = InMemorySemanticCandidateStorage()
    storage.save(intent_payload, tenant_id=TENANT, owner_subject_id=OWNER)
    storage.save(context_payload, tenant_id=TENANT, owner_subject_id=OWNER)

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

    source = SemanticHandoffAuthoritySource(
        work_intents=WorkIntents(), evidence=Evidence(), candidate_storage=storage
    )

    actual = source.resolve(handoff)

    assert actual.intent_candidate == resolved.intent_candidate
    assert actual.context_candidate == resolved.context_candidate
    assert actual.work_intent == resolved.work_intent

    from_factory = SemanticHandoffAuthoritySource.from_sqlalchemy(
        work_intents=WorkIntents(),
        evidence=Evidence(),
        candidate_storage=storage,
    )
    assert from_factory.resolve(handoff).intent_candidate == resolved.intent_candidate


def test_authority_source_preserves_missing_authoritative_records():
    handoff, _, resolved, _, _ = _fixture()

    class WorkIntents:
        def get(self, **_kwargs):
            return resolved.work_intent

        def get_latest_for_execution(self, **_kwargs):
            return resolved.latest_work_intent

    class Evidence:
        def get(self, **_kwargs):
            return None

    actual = SemanticHandoffAuthoritySource(
        work_intents=WorkIntents(),
        evidence=Evidence(),
        candidate_storage=InMemorySemanticCandidateStorage(),
    ).resolve(handoff)

    assert actual.intent_evidence is None
    assert actual.context_evidence is None
    assert actual.intent_candidate is None
    assert actual.context_candidate is None


def test_policy_registry_and_input_validation_fail_closed():
    policy = SemanticReusePolicy(
        policy_ref="semantic-reuse://pa/analysis/v1",
        target_agent_type="PA",
        work_class="ANALYSIS",
        minimum_intent_confidence=0.8,
        minimum_context_confidence=0.7,
        maximum_age_seconds=60,
    )
    with pytest.raises(SemanticHandoffReuseError, match="duplicated"):
        SemanticReusePolicyRegistry([policy, policy])
    with pytest.raises(SemanticHandoffReuseError, match="maximum age"):
        SemanticReusePolicy(
            policy_ref="bad",
            target_agent_type="PA",
            work_class="ANALYSIS",
            minimum_intent_confidence=0.8,
            minimum_context_confidence=0.7,
            maximum_age_seconds=0,
        )
    invalid_values = (
        {"policy_ref": ""},
        {"target_agent_type": "UNKNOWN"},
        {"work_class": ""},
        {"minimum_intent_confidence": True},
        {"minimum_context_confidence": 1.1},
    )
    base = {
        "policy_ref": "semantic-reuse://pa/analysis/v2",
        "target_agent_type": "PA",
        "work_class": "ANALYSIS",
        "minimum_intent_confidence": 0.8,
        "minimum_context_confidence": 0.7,
        "maximum_age_seconds": 60,
    }
    for mutation in invalid_values:
        with pytest.raises(SemanticHandoffReuseError):
            SemanticReusePolicy(**{**base, **mutation})
    handoff, source, resolved, _, _ = _fixture()
    source["project_ref"] = None
    with pytest.raises(SemanticHandoffReuseError, match="project_ref"):
        _evaluate(handoff=handoff, planning_source=source, resolved=resolved)


def test_reuse_evaluator_rejects_missing_inputs_and_invalid_internal_decisions():
    handoff, source, resolved, _, _ = _fixture()
    no_work_intent = _evaluate(
        handoff=handoff,
        planning_source=source,
        resolved=replace(resolved, work_intent=None),
    )
    no_evidence = _evaluate(
        handoff=handoff,
        planning_source=source,
        resolved=replace(resolved, intent_evidence=None),
    )
    assert no_work_intent["reason_codes"] == ["MISSING"]
    assert no_evidence["reason_codes"] == ["MISSING"]
    with pytest.raises(SemanticHandoffReuseError, match="decision"):
        reuse_module._decision(
            handoff,
            decision="UNKNOWN",
            reasons=(),
            policy_ref=None,
            target_agent_type="PA",
            capability=CAPABILITY,
            project_scope=PROJECT,
            evaluated_at=EVALUATED_AT,
        )
    for invalid_time in (None, "not-a-time", "2026-11-23T10:00:00"):
        with pytest.raises(SemanticHandoffReuseError, match="timestamp"):
            reuse_module._datetime(invalid_time)
    with pytest.raises(SemanticHandoffReuseError, match="required_capability"):
        reuse_module._text("required_capability", "")
