from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import nex_ae_api.semantic_candidate_admission as admission_module
import pytest
from nex_ae_api.agent_context import TrustedContextResolution
from nex_ae_api.agent_execution import AgentRuntimeAdmission
from nex_ae_api.context_candidate_generation import LiveContextCandidateService
from nex_ae_api.intent_candidate_generation import LiveIntentCandidateService
from nex_ae_api.mo_generation_client import AeMoGenerationReadiness, AeMoGenerationResult
from nex_ae_api.plan_candidate_generation import LivePlanCandidateService
from nex_ae_api.planning_capabilities import build_capability_snapshot
from nex_ae_api.prompts import seed_ae_prompt_registry
from nex_ae_api.semantic_candidate_admission import (
    DeterministicCandidateAdmissionService,
    SemanticCandidateAdmissionRequest,
)
from nex_ae_api.semantic_candidate_evidence import (
    InMemorySemanticCandidateStorage,
    SqlAlchemySemanticCandidateEvidenceRepository,
)
from nex_ae_api.semantic_candidates import SemanticCalibrationPolicy, SemanticCalibrationRegistry
from nex_runtime.prompts import PromptRegistryStore
from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


EXECUTION_ID = "10000000-0000-4000-8000-000000000656"
AGENT_ID = "20000000-0000-4000-8000-000000000656"
WORKSPACE_ID = "30000000-0000-4000-8000-000000000656"
CONVERSATION_ID = "40000000-0000-4000-8000-000000000656"
INTERACTION_ID = "50000000-0000-4000-8000-000000000656"
SNAPSHOT_ID = "60000000-0000-4000-8000-000000000656"
NOW = "2026-10-17T02:00:00Z"
TRACE_ID = "a" * 32


class GenerationClient:
    def __init__(
        self,
        *,
        intent_confidence: float = 0.92,
        context_confidence: float = 0.91,
        plan_confidence: float = 0.93,
    ) -> None:
        self.intent_confidence = intent_confidence
        self.context_confidence = context_confidence
        self.plan_confidence = plan_confidence
        self.calls: list[str] = []

    def check_required_mode_readiness(self, **kwargs):
        return AeMoGenerationReadiness(
            provider_mode="live",
            readiness_status="READY",
            model_profile="general-llm-default",
            model_ref="model-revision-a",
            deployment_id="deployment-a",
            route_id="route-a",
            checked_at=NOW,
            expires_at="2026-10-17T02:00:30Z",
            cache_status="FRESH",
            source="active_preflight",
        )

    def generate_candidate(self, **kwargs):
        stage = kwargs["semantic_stage"]
        self.calls.append(stage)
        generation_input = __import__("json").loads(kwargs["messages"][1]["content"])
        if stage == "INTENT":
            candidate = {
                "schema_version": "p65.intent_candidate.v1",
                "intent_label": "analyze_project_budget",
                "suggested_execution_mode": "GROUNDED_ANSWER",
                "entity_selectors": [],
                "parameter_candidates": [],
                "clarification": {"required": False, "reasons": [], "questions": []},
                "confidence": self.intent_confidence,
            }
        elif stage == "CONTEXT":
            candidate = {
                "schema_version": "p65.context_candidate_set.v1",
                "entity_candidates": [],
                "retrieval_hints": [
                    {
                        "query_terms": ["예산", "집행", "잔액"],
                        "resource_types": ["DOCUMENT"],
                        "confidence": 0.91,
                    }
                ],
                "resource_selectors": [],
                "parameter_candidates": [],
                "confidence": self.context_confidence,
            }
        else:
            candidate = {
                "schema_version": "p65.plan_candidate.v1",
                "suggested_plan_kind": "DIRECT",
                "goal": generation_input["work_intent"]["goal"],
                "logical_steps": [
                    {
                        "step_id": "S1",
                        "step_type": "LOCAL_CAPABILITY",
                        "title": "Run grounded compatibility chat",
                        "objective": "Answer using admitted context.",
                        "depends_on": [],
                        "capability_hint": "AE.CHAT.COMPATIBILITY",
                        "completion_criteria": ["A grounded answer is returned."],
                    }
                ],
                "completion_mapping": [
                    {"criterion_id": "C1", "terminal_step_refs": ["S1"]}
                ],
                "confidence": self.plan_confidence,
            }
        output = canonical_json(candidate)
        return AeMoGenerationResult(
            mo_generation_id=f"generation-{stage.lower()}",
            model_profile="general-llm-default",
            model_ref="model-revision-a",
            deployment_id="deployment-a",
            provider_type="vllm-openai-compatible",
            output_text=output,
            provider_output_sha256=hashlib.sha256(output.encode()).hexdigest(),
            provider_output_size_bytes=len(output.encode()),
            finish_reason="STOP",
            input_tokens=10,
            output_tokens=10,
            total_tokens=20,
            request_id=kwargs["request_id"],
            trace_id=kwargs["trace_id"],
            route_id="route-a",
            provider_request_id=f"provider-{stage.lower()}",
            queue_ms=0,
            provider_ms=1,
            total_ms=1,
            created_at=NOW,
            updated_at=NOW,
        )


class Resolver:
    def resolve(self, request):
        return TrustedContextResolution(
            project_ref=None,
            authority_ref="OA:EAC:p65-s5",
            resolved_entities=(),
            retrieval_refs=(),
            evidence_refs=(),
            conflicts=(),
            degradations=(),
            context_manifest=(
                {
                    "kind": "INTERACTION_REF",
                    "source_ref": f"AE:INTERACTION:{INTERACTION_ID}",
                    "source_version": "1",
                    "content_hash": semantic_sha256_hash_ref({"interaction": INTERACTION_ID}),
                    "as_of": NOW,
                },
            ),
            budget_tokens=4096,
            estimated_used_tokens=128,
        )


class Admission:
    def __init__(self) -> None:
        self.calls = 0

    def admit_prompt(self, **kwargs):
        self.calls += 1
        return AgentRuntimeAdmission(mode="required", execution={
            "tenant_id": kwargs["tenant_id"],
            "agent_execution_id": EXECUTION_ID,
            "agent_id": AGENT_ID,
            "received_at": NOW,
            "version": 1,
        })


class ExecutionRepository:
    def __init__(self) -> None:
        self.record = {"version": 1, "state": "QUEUED", "phase": "INTAKE"}
        self.available = True

    def get(self, tenant_id, execution_id):
        return dict(self.record) if self.available else None


class EntityRepository:
    def __init__(self, identity_field: str) -> None:
        self.identity_field = identity_field
        self.records = {}

    def save(self, **kwargs):
        value = next(value for key, value in kwargs.items() if key not in {"tenant_id", "created_at"})
        self.records[value[self.identity_field]] = dict(value)
        return dict(value)

    def get(self, **kwargs):
        identity = next(value for key, value in kwargs.items() if key != "tenant_id")
        value = self.records.get(identity)
        return None if value is None else dict(value)


class CapabilityRepository:
    def __init__(self) -> None:
        self.value = None

    def save(self, snapshot):
        if self.value is None:
            self.value = dict(snapshot)
        assert self.value == snapshot
        return dict(self.value)


class ValidationRepository(EntityRepository):
    def __init__(self, executions: ExecutionRepository) -> None:
        super().__init__("validation_result_id")
        self.executions = executions
        self.save_calls = 0

    def save_and_apply_runtime(self, *, tenant_id, result, expected_execution_version):
        assert expected_execution_version == self.executions.record["version"]
        self.save_calls += 1
        self.executions.record.update({"version": 2, "state": "RUNNING", "phase": "PLAN_COMPILE"})
        self.records[result["validation_result_id"]] = dict(result)
        return dict(result)


def _evidence_factory():
    engine = create_engine("sqlite+pysqlite://", future=True)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ae_semantic_candidate (
                tenant_id TEXT, candidate_id TEXT, owner_subject_id TEXT,
                agent_execution_id TEXT, semantic_stage TEXT, candidate_revision INTEGER,
                candidate_hash TEXT, candidate_payload_storage_ref TEXT,
                candidate_payload_size_bytes INTEGER, provider_output_sha256 TEXT,
                input_context_hash TEXT, prompt_binding_id TEXT, prompt_binding_key TEXT,
                prompt_template_version_id TEXT, prompt_template_version TEXT,
                prompt_content_sha256 TEXT, rendered_prompt_hash TEXT,
                model_profile TEXT, model_ref TEXT, deployment_id TEXT,
                mo_generation_id TEXT, request_id TEXT, trace_id TEXT,
                admission_policy_ref TEXT, validation_outcome TEXT, directive TEXT,
                failure_code TEXT, evidence_json TEXT, created_at TEXT,
                PRIMARY KEY (tenant_id, candidate_id),
                UNIQUE (tenant_id, agent_execution_id, semantic_stage, candidate_revision)
            )
        """))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _policy(stage: str) -> SemanticCalibrationPolicy:
    return SemanticCalibrationPolicy(
        semantic_stage=stage,
        policy_ref=f"semantic-admission://{stage.lower()}/model/p65.1",
        policy_version="p65.1",
        model_profile="general-llm-default",
        model_ref="model-revision-a",
        minimum_confidence=0.7,
        golden_evidence_ref=f"test://{stage.lower()}/golden",
        adversarial_evidence_ref=f"test://{stage.lower()}/adversarial",
    )


def _components(
    *,
    intent_confidence: float = 0.92,
    context_confidence: float = 0.91,
    plan_confidence: float = 0.93,
):
    client = GenerationClient(
        intent_confidence=intent_confidence,
        context_confidence=context_confidence,
        plan_confidence=plan_confidence,
    )
    store = PromptRegistryStore()
    seed_ae_prompt_registry(store)
    policies = SemanticCalibrationRegistry(tuple(_policy(stage) for stage in ("INTENT", "CONTEXT", "PLAN")))
    executions = ExecutionRepository()
    work_intents = EntityRepository("work_intent_id")
    contexts = EntityRepository("context_id")
    plans = EntityRepository("agent_plan_id")
    validations = ValidationRepository(executions)
    executable_plans = EntityRepository("executable_plan_id")
    admission = Admission()
    service = DeterministicCandidateAdmissionService(
        mode="required",
        admission=admission,
        intent_stage=LiveIntentCandidateService(client, store, policies),
        context_stage=LiveContextCandidateService(client, store, policies),
        plan_stage=LivePlanCandidateService(client, store, policies),
        evidence=SqlAlchemySemanticCandidateEvidenceRepository(_evidence_factory()),
        candidate_storage=InMemorySemanticCandidateStorage(),
        work_intents=work_intents,
        contexts=contexts,
        capabilities=CapabilityRepository(),
        plans=plans,
        validations=validations,
        executable_plans=executable_plans,
        executions=executions,
        clock=lambda: datetime(2026, 10, 17, 2, 0, tzinfo=UTC),
    )
    return service, client, admission, work_intents, contexts, plans, validations, executable_plans


def _request() -> SemanticCandidateAdmissionRequest:
    return SemanticCandidateAdmissionRequest(
        tenant_id="tenant-a",
        owner_subject_id="user-a",
        profile_ref="urn:nex:agent-profile:ia:default:v1",
        interaction_id=INTERACTION_ID,
        workspace_id=WORKSPACE_ID,
        conversation_id=CONVERSATION_ID,
        correlation_id="p65-s5:correlation",
        request_id="p65-s5-request",
        trace_id=TRACE_ID,
        user_prompt="프로젝트 예산 집행 잔액을 한국어로 요약해줘.",
        base_context={
            "interaction_text": "프로젝트 예산 집행 잔액을 한국어로 요약해줘.",
            "conversation_summary": None,
            "resource_label_hints": ["프로젝트 예산 현황"],
        },
        runtime_policy_ref={
            "rule_id": "ae.compatibility.general-answer",
            "rule_version": "v1",
            "rule_hash": "sha256:" + "f" * 64,
        },
        context_resolver=Resolver(),
        capability_snapshot=build_capability_snapshot(
            tenant_id="tenant-a",
            capability_snapshot_id=SNAPSHOT_ID,
            snapshot_version=1,
            created_at=NOW,
        ),
    )


def test_required_pipeline_compiles_and_replays_without_provider_calls() -> None:
    service, client, admission, intents, contexts, plans, validations, executables = _components()

    first = service.admit_and_compile(_request())
    assert first.status == "COMPILED"
    assert first.directive == "ACCEPT_RUNTIME_WORK"
    assert first.validation_status == "VALID"
    assert [stage.semantic_stage for stage in first.stages] == ["INTENT", "CONTEXT", "PLAN"]
    assert all(stage.resumed is False for stage in first.stages)
    assert client.calls == ["INTENT", "CONTEXT", "PLAN"]
    assert validations.save_calls == 1
    assert len(intents.records) == len(contexts.records) == len(plans.records) == 1
    assert len(executables.records) == 1

    client.calls.clear()
    second = service.admit_and_compile(_request())
    assert second.executable_plan_id == first.executable_plan_id
    assert second.executable_plan_hash == first.executable_plan_hash
    assert all(stage.resumed is True for stage in second.stages)
    assert client.calls == []
    assert validations.save_calls == 1
    assert admission.calls == 2


def test_resume_reconstructs_missing_canonical_work_intent_without_provider() -> None:
    service, client, _, intents, _, _, _, _ = _components()
    first = service.admit_and_compile(_request())
    intents.records.clear()
    client.calls.clear()

    resumed = service.admit_and_compile(_request())
    assert resumed.status == "COMPILED"
    assert resumed.work_intent_id == first.work_intent_id
    assert client.calls == []
    assert len(intents.records) == 1


def test_low_confidence_stops_before_context_validation_and_compile() -> None:
    service, client, _, intents, contexts, plans, validations, executables = _components(intent_confidence=0.69)
    result = service.admit_and_compile(_request())
    assert result.status == "CANDIDATE_BLOCKED"
    assert result.directive == "CLARIFICATION_REQUIRED"
    assert [stage.semantic_stage for stage in result.stages] == ["INTENT"]
    assert client.calls == ["INTENT"]
    assert not intents.records and not contexts.records and not plans.records
    assert validations.save_calls == 0
    assert not executables.records


def test_disabled_mode_is_provider_and_persistence_free() -> None:
    service, client, admission, *_ = _components()
    disabled = replace(service, mode="disabled")
    result = disabled.admit_and_compile(_request())
    assert result.status == "DISABLED"
    assert result.agent_execution_id is None
    assert client.calls == []
    assert admission.calls == 0


@pytest.mark.parametrize(
    ("confidence_field", "expected_calls", "expected_directive"),
    [
        ("context_confidence", ["INTENT", "CONTEXT"], "CONTEXT_REFRESH_REQUIRED"),
        ("plan_confidence", ["INTENT", "CONTEXT", "PLAN"], "REPLAN_REQUIRED"),
    ],
)
def test_downstream_low_confidence_stops_before_validation_and_compile(
    confidence_field: str,
    expected_calls: list[str],
    expected_directive: str,
) -> None:
    service, client, _, _, _, plans, validations, executables = _components(
        **{confidence_field: 0.49}
    )
    result = service.admit_and_compile(_request())
    assert result.status == "CANDIDATE_BLOCKED"
    assert result.directive == expected_directive
    assert client.calls == expected_calls
    assert validations.save_calls == 0
    assert not executables.records
    if confidence_field == "plan_confidence":
        assert not plans.records


def test_resume_reconstructs_missing_context_and_plan_without_provider() -> None:
    service, client, _, _, contexts, plans, _, _ = _components()
    first = service.admit_and_compile(_request())
    contexts.records.clear()
    plans.records.clear()
    client.calls.clear()

    resumed = service.admit_and_compile(_request())
    assert resumed.executable_plan_hash == first.executable_plan_hash
    assert client.calls == []
    assert len(contexts.records) == len(plans.records) == 1


def test_resume_fails_closed_when_private_candidate_payload_is_missing() -> None:
    service, client, *_ = _components()
    service.admit_and_compile(_request())
    service.candidate_storage.payloads.clear()
    client.calls.clear()

    with pytest.raises(admission_module.SemanticCandidateAdmissionError) as raised:
        service.admit_and_compile(_request())
    assert raised.value.error_code == "CANDIDATE_PAYLOAD_MISSING"
    assert client.calls == []


def test_new_candidate_fails_closed_on_storage_reference_mismatch() -> None:
    service, *_ = _components()

    class WrongReferenceStorage:
        def save(self, *_args, **_kwargs):
            return "ae://semantic-candidates/wrong"

    with pytest.raises(admission_module.SemanticCandidateAdmissionError) as raised:
        replace(service, candidate_storage=WrongReferenceStorage()).admit_and_compile(
            _request()
        )
    assert raised.value.error_code == "CANDIDATE_STORAGE_REF_MISMATCH"


def test_validation_block_and_disappeared_execution_do_not_compile(monkeypatch) -> None:
    service, _, _, _, _, _, validations, executables = _components()
    monkeypatch.setattr(
        admission_module,
        "validate_agent_plan",
        lambda **kwargs: {
            "validation_result_id": kwargs["validation_result_id"],
            "status": "INVALID",
            "runtime_directive": "REPLAN_REQUIRED",
        },
    )
    blocked = service.admit_and_compile(_request())
    assert blocked.status == "VALIDATION_BLOCKED"
    assert blocked.directive == "REPLAN_REQUIRED"
    assert not executables.records
    assert validations.save_calls == 1

    service, *_ = _components()
    service.executions.available = False
    with pytest.raises(admission_module.SemanticCandidateAdmissionError) as missing:
        service.admit_and_compile(_request())
    assert missing.value.error_code == "AGENT_EXECUTION_NOT_FOUND"


def test_admission_mode_shadow_skip_and_stage_integrity_guards() -> None:
    service, _, _, *_ = _components()
    with pytest.raises(admission_module.SemanticCandidateAdmissionError):
        replace(service, mode="invalid")

    skipped = replace(
        service,
        mode="shadow",
        admission=SimpleNamespace(
            admit_prompt=lambda **_kwargs: AgentRuntimeAdmission(
                mode="shadow", execution=None, shadow_error_code="shadow.failure"
            )
        ),
    ).admit_and_compile(_request())
    assert skipped.status == "SHADOW_SKIPPED"
    assert skipped.shadow_error_code == "shadow.failure"

    candidate = {"schema_version": "p65.intent_candidate.v1"}
    base_result = SimpleNamespace(
        candidate=candidate,
        candidate_hash=semantic_sha256_hash_ref(candidate),
        provider_output_sha256="b" * 64,
        input_context_hash="sha256:" + "c" * 64,
        prompt_provenance={
            "prompt_binding_id": "30000000-0000-4000-8000-000000000699",
            "prompt_binding_key": "ae.intent_resolution.default",
            "prompt_template_version_id": "40000000-0000-4000-8000-000000000699",
            "prompt_template_version": "v1",
            "prompt_content_sha256": "d" * 64,
            "rendered_prompt_hash": "e" * 64,
        },
        model_provenance={
            "model_profile": "general-llm-default",
            "model_ref": "model-revision-a",
            "deployment_id": "deployment-a",
            "mo_generation_id": "generation-a",
        },
        admission_policy_ref="semantic-admission://intent/model/p65.1",
        directive="CONTINUE",
        failure_code=None,
    )
    ids = admission_module._AdmissionIds(EXECUTION_ID)
    for result, expected_code in (
        (
            SimpleNamespace(**{**vars(base_result), "admission_policy_ref": None}),
            "SEMANTIC_CALIBRATION_REQUIRED",
        ),
        (
            SimpleNamespace(
                **{**vars(base_result), "candidate_hash": "sha256:" + "f" * 64}
            ),
            "CANDIDATE_HASH_MISMATCH",
        ),
    ):
        with pytest.raises(admission_module.SemanticCandidateAdmissionError) as raised:
            service._stage(
                request=_request(),
                execution_id=EXECUTION_ID,
                semantic_stage="INTENT",
                candidate_id=ids.candidate("INTENT"),
                invoke=lambda result=result: result,
                now=NOW,
            )
        assert raised.value.error_code == expected_code


def test_resumed_candidate_lineage_conflict_fails_closed() -> None:
    service, *_ = _components()
    first = service.admit_and_compile(_request())
    original = service.evidence

    class ConflictingEvidence:
        def get(self, **kwargs):
            value = original.get(**kwargs)
            return None if value is None else {**value, "owner_subject_id": "other"}

        def save(self, value):
            return original.save(value)

    conflicting = replace(service, evidence=ConflictingEvidence())
    with pytest.raises(admission_module.SemanticCandidateAdmissionError) as raised:
        conflicting.admit_and_compile(_request())
    assert raised.value.error_code == "CANDIDATE_EVIDENCE_LINEAGE_CONFLICT"
    assert first.status == "COMPILED"


def test_claimed_workitem_reuses_candidate_validation_and_compile_pipeline() -> None:
    service, client, admission, intents, contexts, plans, validations, executables = (
        _components()
    )
    source = {
        "schema_version": "p7.claimed_work_planning_source.v1",
        "source_type": "CLAIMED_WORKITEM",
        "source_ref": "70000000-0000-4000-8000-000000000657",
        "goal": "Analyze the authorized project evidence.",
        "work_class": "ANALYSIS",
        "required_capability": "AE.CHAT.COMPATIBILITY",
        "project_ref": {
            "entity_type": "PROJECT",
            "entity_id": "project-p7-s7",
        },
        "artifact_refs": [],
        "evidence_refs": [],
        "completion_policy": "OWNER_SUBMITS",
        "result_contract_ref": "urn:nex:result:background-analysis:1",
    }
    service.executions.record.update(
        {
            "tenant_id": "tenant-a",
            "agent_execution_id": EXECUTION_ID,
            "agent_id": AGENT_ID,
            "agent_type": "PA",
            "source_type": "CLAIMED_WORKITEM",
            "source_ref": source["source_ref"],
            "work_item_ref": source["source_ref"],
            "project_id": "project-p7-s7",
            "requester_ref": "user-a",
            "received_at": NOW,
        }
    )

    class ClaimedResolver:
        def resolve(self, request):
            assert request.agent_type == "PA"
            assert request.source_type == "CLAIMED_WORKITEM"
            assert request.source_ref == source["source_ref"]
            return TrustedContextResolution(
                project_ref={
                    "system": "nex-wc",
                    "resource_type": "PROJECT",
                    "resource_id": "project-p7-s7",
                },
                authority_ref=f"WC:WORK_ITEM:{source['source_ref']}",
                resolved_entities=(),
                retrieval_refs=(),
                evidence_refs=(),
                conflicts=(),
                degradations=(),
                context_manifest=(
                    {
                        "kind": "CLAIMED_WORKITEM_REF",
                        "source_ref": f"WC:WORK_ITEM:{source['source_ref']}",
                        "source_version": "sha256:" + "7" * 64,
                        "content_hash": "sha256:" + "8" * 64,
                        "as_of": NOW,
                    },
                ),
                budget_tokens=4096,
                estimated_used_tokens=128,
            )

    result = service.admit_and_compile(
        replace(
            _request(),
            context_resolver=ClaimedResolver(),
            planning_source_type="CLAIMED_WORKITEM",
            existing_execution_id=EXECUTION_ID,
            agent_type="PA",
            project_id="project-p7-s7",
            source_ref=source["source_ref"],
            planning_source=source,
        )
    )

    assert result.status == "COMPILED"
    assert client.calls == ["INTENT", "CONTEXT", "PLAN"]
    assert admission.calls == 0
    work_intent = next(iter(intents.records.values()))
    assert work_intent["source"]["source_type"] == "CLAIMED_WORKITEM"
    assert work_intent["goal"] == source["goal"]
    assert work_intent["project_ref"]["resource_id"] == "project-p7-s7"
    context = next(iter(contexts.records.values()))
    assert context["identity"]["agent_type"] == "PA"
    assert context["source"]["source_ref"] == source["source_ref"]
    assert len(plans.records) == 1
    assert validations.save_calls == 1
    assert len(executables.records) == 1
