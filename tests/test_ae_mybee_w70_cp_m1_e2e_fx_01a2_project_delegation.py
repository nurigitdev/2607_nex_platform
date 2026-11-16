from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import nex_ae_api.project_delegation_planning as delegation_module
import pytest
from nex_ae_api.plan_candidate_generation import bind_plan_candidate
from nex_ae_api.plan_candidate_profiles import (
    PlanCandidateProfileError,
    PlanCandidateProfileRegistration,
    PlanCandidateProfileRegistry,
    ProfileAwarePlanCandidateService,
    build_m1_plan_candidate_profile_registry,
)
from nex_ae_api.planning_capabilities import build_capability_snapshot
from nex_ae_api.project_agent_lifecycle import (
    AE_PROJECT_AGENT_METADATA,
    AE_PROJECT_AGENT_SYNC_TABLE,
)
from nex_ae_api.project_delegation_planning import (
    M1_PROJECT_DELEGATION_ACTION,
    M1_PROJECT_DELEGATION_CAPABILITY_ID,
    HttpEosProjectResolutionSource,
    HttpOaProjectDecisionSource,
    ProjectDelegationIntentActivator,
    ProjectDelegationPlanningError,
    SqlAlchemyActiveProjectAgentSource,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TENANT = "VO00"
SUBJECT = "employee-0001"
PROJECT_CODE = "VO00D260001"
PROJECT_ID = "d30c5668-48f7-4f4c-8d8f-1de6e4f0a50a"
AGENT_ID = "b4758c4a-c96f-450b-b282-c947cce80ab3"
EXECUTION_ID = "4192d8ca-4877-4813-87e9-a00ebf17267d"
WORK_INTENT_ID = "252d1ef9-e197-40ef-916f-119d69bf9448"
CONTEXT_ID = "a9d5d970-0dd0-43cd-b678-0c4c3cbe0f76"
PLAN_ID = "1db5003c-fc4a-440a-8ddd-3dfcc0fde253"


class _Eos:
    def resolve_active_project(self, **_kwargs):
        return {"project_code": PROJECT_CODE, "status": "ACTIVE", "version": 3}


class _Oa:
    allowed = True

    def decide(self, **kwargs):
        return {
            "decision_ref": "sha256:" + "1" * 64,
            "tenant_id": kwargs["tenant_id"],
            "subject_id": kwargs["subject_id"],
            "project_code": kwargs["project_code"],
            "action": kwargs["action"],
            "allowed": self.allowed,
            "reason_code": "ALLOW" if self.allowed else "PROJECT_GRANT_NOT_FOUND",
            "source_version": 3,
        }


class _Agents:
    status = "ACTIVE"

    def resolve_active(self, **_kwargs):
        if self.status != "ACTIVE":
            raise ProjectDelegationPlanningError("PROJECT_AGENT_NOT_ACTIVE", "inactive")
        return {
            "tenant_id": TENANT,
            "project_id": PROJECT_ID,
            "project_code": PROJECT_CODE,
            "project_state": "ACTIVE",
            "project_version": 3,
            "agent_id": AGENT_ID,
            "agent_status": "ACTIVE",
            "capability_mode": "ORDINARY",
        }


def _candidate(*, project_code: str = PROJECT_CODE):
    return {
        "schema_version": "p65.intent_candidate.v1",
        "entity_selectors": [
            {
                "selector_id": "E1",
                "selector_type": "QUERY_TERM",
                "value": project_code,
                "confidence": 0.98,
            }
        ],
    }


def _work_intent():
    value = {
        "schema_version": "1.1",
        "work_intent_id": WORK_INTENT_ID,
        "intent_revision": 1,
        "supersedes_work_intent_id": None,
        "execution_id": EXECUTION_ID,
        "source": {
            "source_type": "PROMPT",
            "source_ref": "AE:INTERACTION:test",
            "actor_ref": f"OA:SUBJECT:{SUBJECT}",
            "received_at": "2026-11-15T01:00:00Z",
        },
        "execution_mode": "INTERACTIVE",
        "compatibility_execution_mode": "GENERAL_ANSWER",
        "project_ref": None,
        "intent_label": M1_PROJECT_DELEGATION_CAPABILITY_ID,
        "goal": "Answer the admitted user request.",
        "work_class": "QUERY",
        "required_capability_hints": ["AE.CHAT.COMPATIBILITY"],
        "entity_selectors": [],
        "parameter_candidates": [],
        "constraints": [],
        "completion_criteria": [
            {
                "criterion_id": "C1",
                "description": "A direct response is returned.",
                "required": True,
                "result_contract_ref": "contract://nex/ae/general-answer/v1",
            }
        ],
        "clarification": {"status": "NOT_REQUIRED", "reasons": [], "questions": []},
        "confidence": {
            "overall": 0.98,
            "intent": 0.98,
            "entities": None,
            "parameters": None,
        },
        "provenance": {},
    }
    value["intent_hash"] = semantic_sha256_hash_ref(value)
    return value


def _activate(*, oa=None, agents=None, candidate=None):
    return ProjectDelegationIntentActivator(
        eos=_Eos(), oa=oa or _Oa(), project_agents=agents or _Agents()
    ).activate(
        candidate=candidate or _candidate(),
        work_intent=_work_intent(),
        tenant_id=TENANT,
        principal_id=SUBJECT,
        resolved_at="2026-11-15T01:00:00Z",
    )


def test_project_delegation_resolves_eos_oa_and_active_pa_without_ia_project_ref():
    activated = _activate()
    intent = activated.work_intent
    context = activated.context_resolver.resolve(None)

    assert intent["required_capability_hints"] == [M1_PROJECT_DELEGATION_CAPABILITY_ID]
    assert intent["work_class"] == "BUSINESS_TRANSACTION"
    assert intent["entity_selectors"][0]["raw_text"] == PROJECT_CODE
    assert intent["intent_hash"] == semantic_sha256_hash_ref(
        {key: value for key, value in intent.items() if key != "intent_hash"}
    )
    assert context.project_ref is None
    assert context.resolved_entities[0]["resource_ref"] == {
        "system": "nex-eos",
        "resource_type": "PROJECT",
        "resource_id": PROJECT_ID,
        "version": "3",
    }
    assert [item["kind"] for item in context.context_manifest] == [
        "EOS_PROJECT_RESOLUTION",
        "OA_PROJECT_AUTHORIZATION",
        "AE_PROJECT_AGENT_PROJECTION",
    ]


def test_project_delegation_fails_closed_for_missing_or_ambiguous_project_code():
    with pytest.raises(ProjectDelegationPlanningError) as missing:
        _activate(candidate={"entity_selectors": []})
    assert missing.value.error_code == "PROJECT_CODE_AMBIGUOUS"

    candidate = _candidate()
    candidate["entity_selectors"].append(dict(candidate["entity_selectors"][0]))
    with pytest.raises(ProjectDelegationPlanningError) as ambiguous:
        _activate(candidate=candidate)
    assert ambiguous.value.error_code == "PROJECT_CODE_AMBIGUOUS"


def test_project_delegation_fails_closed_for_oa_denial_and_inactive_pa():
    oa = _Oa()
    oa.allowed = False
    with pytest.raises(ProjectDelegationPlanningError) as denied:
        _activate(oa=oa)
    assert denied.value.error_code == "PROJECT_AUTHORIZATION_DENIED"

    agents = _Agents()
    agents.status = "INACTIVE"
    with pytest.raises(ProjectDelegationPlanningError) as inactive:
        _activate(agents=agents)
    assert inactive.value.error_code == "PROJECT_AGENT_NOT_ACTIVE"


def test_sqlalchemy_project_agent_source_requires_exactly_one_active_projection(
    tmp_path,
):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'ae.db'}")
    AE_PROJECT_AGENT_METADATA.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    source = SqlAlchemyActiveProjectAgentSource(factory)

    with pytest.raises(ProjectDelegationPlanningError) as missing:
        source.resolve_active(tenant_id=TENANT, project_code=PROJECT_CODE)
    assert missing.value.error_code == "PROJECT_AGENT_NOT_UNIQUE"

    with factory.begin() as session:
        session.execute(
            AE_PROJECT_AGENT_SYNC_TABLE.insert().values(
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                project_code=PROJECT_CODE,
                project_state="ACTIVE",
                project_version=3,
                profile_policy_ref="policy://project-agent/v1",
                profile_policy_hash="sha256:" + "2" * 64,
                agent_id=AGENT_ID,
                agent_status="ACTIVE",
                capability_mode="ORDINARY",
                last_event_id=str(uuid4()),
                last_event_payload_hash="sha256:" + "3" * 64,
                created_at=datetime(2026, 11, 15, 1, tzinfo=UTC),
                updated_at=datetime(2026, 11, 15, 1, tzinfo=UTC),
            )
        )
    assert (
        source.resolve_active(tenant_id=TENANT, project_code=PROJECT_CODE)["agent_id"]
        == AGENT_ID
    )


def test_ia_resolved_project_entity_admits_delegate_work_scope():
    activated = _activate()
    intent = activated.work_intent
    context_resolution = activated.context_resolver.resolve(None)
    context = {
        "schema_version": "1.1",
        "context_id": CONTEXT_ID,
        "context_generation": 1,
        "execution_id": EXECUTION_ID,
        "work_intent_ref": {
            "id": WORK_INTENT_ID,
            "version": 1,
            "hash": intent["intent_hash"],
        },
        "identity": {"tenant_id": TENANT, "agent_type": "IA"},
        "project_ref": None,
        "resolved_entities": list(context_resolution.resolved_entities),
        "retrieval_refs": [],
        "evidence_refs": [],
        "conflicts": [],
        "degradations": [],
        "context_hash": "sha256:" + "4" * 64,
    }
    candidate = {
        "schema_version": "p7.plan_candidate.v1",
        "suggested_plan_kind": "DIRECT",
        "goal": intent["goal"],
        "logical_steps": [
            {
                "step_id": "S1",
                "step_type": "DELEGATE_WORK",
                "title": "Delegate governed Project accounting work",
                "objective": intent["goal"],
                "depends_on": [],
                "capability_hint": M1_PROJECT_DELEGATION_CAPABILITY_ID,
                "completion_criteria": ["The Project Agent returns the result."],
                "delegation": {
                    "work_class": "BUSINESS_TRANSACTION",
                    "required_agent_type": "PA",
                    "project_scope_ref": PROJECT_ID,
                    "result_contract_ref": intent["completion_criteria"][0][
                        "result_contract_ref"
                    ],
                    "completion_policy": "OWNER_SUBMITS",
                },
            }
        ],
        "completion_mapping": [{"criterion_id": "C1", "terminal_step_refs": ["S1"]}],
        "confidence": 0.95,
    }
    snapshot = build_capability_snapshot(
        tenant_id=TENANT,
        capability_snapshot_id=str(uuid4()),
        snapshot_version=1,
        created_at="2026-11-15T01:00:00Z",
    )
    plan = bind_plan_candidate(
        candidate=candidate,
        candidate_hash=semantic_sha256_hash_ref(candidate),
        work_intent=intent,
        agent_context=context,
        capability_snapshot=snapshot,
        prompt_provenance={
            "prompt_binding_key": "ae.plan_builder.project_delegation.v1",
            "prompt_template_version_id": str(uuid4()),
            "prompt_content_sha256": "6" * 64,
            "rendered_prompt_hash": "7" * 64,
        },
        model_provenance={"model_profile": "test", "model_ref": "test-model"},
        agent_plan_id=PLAN_ID,
    )
    assert plan["steps"][0]["delegation"]["project_scope_ref"] == PROJECT_ID

    bad_context = dict(context)
    bad_context["resolved_entities"] = []
    with pytest.raises(Exception, match="trusted AgentContext project"):
        bind_plan_candidate(
            candidate=candidate,
            candidate_hash=semantic_sha256_hash_ref(candidate),
            work_intent=intent,
            agent_context=bad_context,
            capability_snapshot=snapshot,
            prompt_provenance={
                "prompt_binding_key": "ae.plan_builder.project_delegation.v1",
                "prompt_template_version_id": str(uuid4()),
                "prompt_content_sha256": "6" * 64,
                "rendered_prompt_hash": "7" * 64,
            },
            model_provenance={"model_profile": "test", "model_ref": "test-model"},
            agent_plan_id=PLAN_ID,
        )


def test_plan_profile_registry_is_ordered_hashed_and_rejects_duplicates():
    registration = PlanCandidateProfileRegistration(
        capability_id=M1_PROJECT_DELEGATION_CAPABILITY_ID,
        profile_version="mybee-m1-project-delegation.v1",
        prompt_binding_key="ae.plan_builder.project_delegation.v1",
        source_identity="registry://mybee-m1",
    )
    registry = PlanCandidateProfileRegistry((registration,))
    assert registry.resolve(M1_PROJECT_DELEGATION_CAPABILITY_ID) == registration
    assert registry.to_projection()["registry_hash"].startswith("sha256:")
    with pytest.raises(PlanCandidateProfileError) as duplicate:
        PlanCandidateProfileRegistry((registration, replace(registration)))
    assert duplicate.value.error_code == "PLAN_PROFILE_DUPLICATE"
    with pytest.raises(PlanCandidateProfileError) as invalid:
        PlanCandidateProfileRegistration("", "v1", "binding", "source")
    assert invalid.value.error_code == "PLAN_PROFILE_INVALID"


def test_profile_aware_plan_service_selects_registered_binding(monkeypatch):
    from nex_ae_api.plan_candidate_generation import LivePlanCandidateService

    registration = PlanCandidateProfileRegistration(
        capability_id=M1_PROJECT_DELEGATION_CAPABILITY_ID,
        profile_version="v1",
        prompt_binding_key="ae.plan_builder.project_delegation.v1",
        source_identity="registry://mybee-m1",
    )
    service = LivePlanCandidateService(object(), object())
    monkeypatch.setattr(
        LivePlanCandidateService,
        "generate_and_bind",
        lambda self, **_kwargs: self.prompt_binding_key,
    )
    wrapped = ProfileAwarePlanCandidateService(
        service, PlanCandidateProfileRegistry((registration,))
    )
    assert (
        wrapped.generate_and_bind(
            work_intent={"intent_label": M1_PROJECT_DELEGATION_CAPABILITY_ID}
        )
        == "ae.plan_builder.project_delegation.v1"
    )
    assert (
        wrapped.generate_and_bind(work_intent={"intent_label": "AE.CHAT.COMPATIBILITY"})
        == "ae.plan_builder.default"
    )


def test_m1_plan_profile_registry_requires_admitted_capability():
    class _Capability:
        source_identity = "registry://mybee-m1/d04"

    class _Registry:
        def __init__(self, found):
            self.found = found

        def resolve(self, capability_id, *, required=False):
            assert capability_id == M1_PROJECT_DELEGATION_CAPABILITY_ID
            assert required is False
            return _Capability() if self.found else None

    empty = build_m1_plan_candidate_profile_registry(_Registry(False))
    admitted = build_m1_plan_candidate_profile_registry(_Registry(True))
    assert empty.registrations == ()
    assert admitted.registrations[0].source_identity == "registry://mybee-m1/d04"


def test_http_project_sources_use_service_tokens_and_validate_shapes(monkeypatch):
    monkeypatch.setattr(
        delegation_module,
        "resolve_ae_outbound_service_token",
        lambda token, *, audience: f"resolved:{audience}:{token}",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("Bearer resolved:nex-")
        if request.url.path.endswith("projects:resolve"):
            assert request.url.params["active_only"] == "true"
            return httpx.Response(
                200,
                json={"project_code": PROJECT_CODE, "status": "ACTIVE", "version": 3},
            )
        body = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={
                "decision": {
                    "decision_ref": "sha256:" + "8" * 64,
                    "tenant_id": body["tenant_id"],
                    "subject_id": body["subject_id"],
                    "project_code": body["project_code"],
                    "action": body["action"],
                    "allowed": True,
                    "reason_code": "ALLOW",
                    "source_version": 3,
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    eos = HttpEosProjectResolutionSource("https://eos.test", "token", client)
    oa = HttpOaProjectDecisionSource("https://oa.test", "token", client)
    assert (
        eos.resolve_active_project(
            tenant_id=TENANT, subject_id=SUBJECT, project_code=PROJECT_CODE
        )["status"]
        == "ACTIVE"
    )
    assert (
        oa.decide(
            tenant_id=TENANT,
            subject_id=SUBJECT,
            project_code=PROJECT_CODE,
            action=M1_PROJECT_DELEGATION_ACTION,
            correlation_id=EXECUTION_ID,
            minimum_source_version=3,
        )["allowed"]
        is True
    )


def test_http_project_sources_fail_closed_on_malformed_and_network(monkeypatch):
    monkeypatch.setattr(
        delegation_module,
        "resolve_ae_outbound_service_token",
        lambda _token, *, audience: audience,
    )
    malformed = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[]))
    )
    with pytest.raises(ProjectDelegationPlanningError) as eos_invalid:
        HttpEosProjectResolutionSource(
            "https://eos.test", "token", malformed
        ).resolve_active_project(
            tenant_id=TENANT, subject_id=SUBJECT, project_code=PROJECT_CODE
        )
    assert eos_invalid.value.error_code == "PROJECT_DELEGATION_INVALID"
    with pytest.raises(ProjectDelegationPlanningError) as oa_invalid:
        HttpOaProjectDecisionSource("https://oa.test", "token", malformed).decide(
            tenant_id=TENANT,
            subject_id=SUBJECT,
            project_code=PROJECT_CODE,
            action=M1_PROJECT_DELEGATION_ACTION,
            correlation_id=EXECUTION_ID,
            minimum_source_version=3,
        )
    assert oa_invalid.value.error_code == "PROJECT_DELEGATION_INVALID"

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("offline", request=request)

    offline = httpx.Client(transport=httpx.MockTransport(timeout))
    with pytest.raises(ProjectDelegationPlanningError) as unavailable:
        HttpEosProjectResolutionSource(
            "https://eos.test", "token", offline
        ).resolve_active_project(
            tenant_id=TENANT, subject_id=SUBJECT, project_code=PROJECT_CODE
        )
    assert unavailable.value.error_code == "PROJECT_RESOLUTION_UNAVAILABLE"
    assert unavailable.value.retryable is True


def test_active_intent_prompt_is_v10_and_delegation_prompt_is_separate():
    source = Path("services/nex-ae-api/nex_ae_api/prompts.py").read_text(
        encoding="utf-8"
    )
    assert 'version="v10"' in source
    assert "allocation_project_code_1" in source
    assert '"ae.plan_builder.project_delegation.v1"' in source
    assert "p7.plan_candidate.v1" in source
    assert "FINANCE.VOUCHER.APPROVE_AND_POST" in source
    assert "project_ref=None" in Path(
        "services/nex-ae-api/nex_ae_api/project_delegation_planning.py"
    ).read_text(encoding="utf-8")


def test_oa_action_is_project_scoped_finance_authority():
    assert M1_PROJECT_DELEGATION_ACTION == "finance:voucher-candidate:create"
