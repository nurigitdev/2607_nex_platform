from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_ae_api.agent_context import (
    SqlAlchemyAgentContextRepository,
    TrustedContextResolution,
    build_agent_context,
    runtime_policy_ref_from_compatibility_policy,
)
from nex_ae_api.agent_execution import (
    AgentExecutionAdmissionService,
    SqlAlchemyAgentExecutionRepository,
)
from nex_ae_api.agent_plans import SqlAlchemyAgentPlanRepository
from nex_ae_api.context_candidate_generation import (
    LiveContextCandidateService,
    context_candidate_hints,
)
from nex_ae_api.executable_plans import (
    SqlAlchemyExecutablePlanRepository,
    compile_executable_plan,
)
from nex_ae_api.intent_candidate_generation import (
    LiveIntentCandidateService,
    resolve_intent_candidate,
)
from nex_ae_api.plan_candidate_generation import (
    LivePlanCandidateService,
    bind_plan_candidate,
)
from nex_ae_api.plan_validation import (
    SqlAlchemyPlanValidationRepository,
    validate_agent_plan,
)
from nex_ae_api.planning_capabilities import (
    SqlAlchemyCapabilitySnapshotRepository,
    build_capability_snapshot,
)
from nex_ae_api.semantic_candidate_evidence import (
    InMemorySemanticCandidateStorage,
    SemanticCandidateStorage,
    SqlAlchemySemanticCandidateEvidenceRepository,
    build_default_semantic_candidate_storage,
    build_semantic_candidate_evidence,
    build_semantic_candidate_payload,
    candidate_payload_metadata_from_evidence,
)
from nex_ae_api.semantic_candidates import SemanticCalibrationRegistry
from nex_ae_api.work_intent import (
    SqlAlchemyWorkIntentRepository,
    build_work_intent_from_decision,
    planning_mode,
)
from nex_ae_api.mo_generation_client import build_default_ae_mo_generation_client


@dataclass(frozen=True)
class SemanticCandidateAdmissionError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class SemanticCandidateAdmissionRequest:
    tenant_id: str
    owner_subject_id: str
    profile_ref: str
    interaction_id: str
    workspace_id: str
    conversation_id: str
    correlation_id: str
    request_id: str
    trace_id: str
    user_prompt: str
    base_context: Mapping[str, Any]
    runtime_policy_ref: Mapping[str, Any]
    context_resolver: Any = field(repr=False)
    capability_snapshot: Mapping[str, Any] = field(repr=False)
    retrieval_enabled: bool = True
    authorized_resource_context_available: bool = True
    trusted_execution_mode: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True)
class SemanticStageProjection:
    semantic_stage: str
    candidate_id: str
    candidate_hash: str
    directive: str
    validation_outcome: str
    prompt_template_version_id: str
    model_profile: str
    model_ref: str
    resumed: bool

    def to_wire(self) -> dict[str, Any]:
        return {
            "semantic_stage": self.semantic_stage,
            "candidate_id": self.candidate_id,
            "candidate_hash": self.candidate_hash,
            "directive": self.directive,
            "validation_outcome": self.validation_outcome,
            "prompt_template_version_id": self.prompt_template_version_id,
            "model_profile": self.model_profile,
            "model_ref": self.model_ref,
            "resumed": self.resumed,
        }


@dataclass(frozen=True)
class SemanticCandidateAdmissionResult:
    mode: str
    status: str
    directive: str
    agent_execution_id: str | None
    work_intent_id: str | None = None
    agent_context_id: str | None = None
    agent_plan_id: str | None = None
    validation_result_id: str | None = None
    validation_status: str | None = None
    executable_plan_id: str | None = None
    executable_plan_hash: str | None = None
    stages: tuple[SemanticStageProjection, ...] = ()
    shadow_error_code: str | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "p65.deterministic_candidate_admission.v1",
            "mode": self.mode,
            "status": self.status,
            "directive": self.directive,
            "agent_execution_id": self.agent_execution_id,
            "work_intent_id": self.work_intent_id,
            "agent_context_id": self.agent_context_id,
            "agent_plan_id": self.agent_plan_id,
            "validation_result_id": self.validation_result_id,
            "validation_status": self.validation_status,
            "executable_plan_id": self.executable_plan_id,
            "executable_plan_hash": self.executable_plan_hash,
            "stages": [stage.to_wire() for stage in self.stages],
            "shadow_error_code": self.shadow_error_code,
            "raw_prompt_included": False,
            "candidate_payload_included": False,
            "provider_endpoint_included": False,
            "secret_included": False,
        }


@dataclass(frozen=True)
class SemanticCandidateAdmissionRuntime:
    mode: str
    available: bool
    service: DeterministicCandidateAdmissionService | None
    unavailable_reason: str | None = None

    def admit_chat(
        self,
        *,
        payload: Mapping[str, Any],
        runtime_policy: Mapping[str, Any],
        retrieval_package: Mapping[str, Any] | None,
        request_id: str,
        trace_id: str,
    ) -> SemanticCandidateAdmissionResult:
        if self.mode == "disabled":
            return SemanticCandidateAdmissionResult(
                mode="disabled",
                status="DISABLED",
                directive="USE_COMPATIBILITY_PATH",
                agent_execution_id=None,
            )
        if not self.available or self.service is None:
            raise _error(
                503,
                "SEMANTIC_ADMISSION_NOT_READY",
                "AE semantic candidate admission is not ready.",
                True,
            )
        tenant_id = _request_text(payload, "tenant_id", 128)
        owner_subject_id = _request_text(payload, "owner_user_id", 200)
        interaction_id = _request_text(payload, "interaction_id", 64)
        workspace_id = _request_text(payload, "workspace_id", 64)
        conversation_id = _request_text(payload, "conversation_id", 64)
        user_prompt = _request_text(payload, "user_message", 65_536)
        snapshot = self.service.capabilities.get_latest(tenant_id=tenant_id)
        if snapshot is None:
            snapshot = build_capability_snapshot(
                tenant_id=tenant_id,
                capability_snapshot_id=str(
                    uuid5(
                        NAMESPACE_URL,
                        f"nex:p65:capability-snapshot:{tenant_id}:1",
                    )
                ),
                snapshot_version=1,
                created_at=_timestamp(self.service.clock()),
            )
        resolver = _ChatTrustedContextResolver(
            tenant_id=tenant_id,
            owner_subject_id=owner_subject_id,
            interaction_id=interaction_id,
            user_prompt=user_prompt,
            retrieval_package=retrieval_package,
            as_of=_timestamp(self.service.clock()),
        )
        return self.service.admit_and_compile(
            SemanticCandidateAdmissionRequest(
                tenant_id=tenant_id,
                owner_subject_id=owner_subject_id,
                profile_ref="urn:nex:agent-profile:ia:default:v1",
                interaction_id=interaction_id,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                correlation_id=f"p65:{trace_id}",
                request_id=request_id,
                trace_id=trace_id,
                user_prompt=user_prompt,
                base_context={
                    "interaction_text": user_prompt,
                    "conversation_summary": _optional_request_text(
                        payload.get("conversation_summary"), 16_384
                    ),
                    "resource_label_hints": _resource_label_hints(
                        retrieval_package
                    ),
                },
                runtime_policy_ref=runtime_policy_ref_from_compatibility_policy(
                    runtime_policy
                ),
                context_resolver=resolver,
                capability_snapshot=snapshot,
                retrieval_enabled=bool(
                    runtime_policy.get("intent_decision", {}).get(
                        "retrieval_required", False
                    )
                ),
                authorized_resource_context_available=(
                    retrieval_package is not None
                    and retrieval_package.get("status") != "NO_ANSWER"
                ),
                trusted_execution_mode=runtime_policy.get(
                    "intent_decision", {}
                ).get("execution_mode"),
            )
        )


@dataclass(frozen=True)
class DeterministicCandidateAdmissionService:
    mode: str
    admission: AgentExecutionAdmissionService = field(repr=False)
    intent_stage: LiveIntentCandidateService = field(repr=False)
    context_stage: LiveContextCandidateService = field(repr=False)
    plan_stage: LivePlanCandidateService = field(repr=False)
    evidence: SqlAlchemySemanticCandidateEvidenceRepository = field(repr=False)
    candidate_storage: SemanticCandidateStorage = field(repr=False)
    work_intents: Any = field(repr=False)
    contexts: Any = field(repr=False)
    capabilities: Any = field(repr=False)
    plans: Any = field(repr=False)
    validations: Any = field(repr=False)
    executable_plans: Any = field(repr=False)
    executions: Any = field(repr=False)
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC), repr=False
    )

    def __post_init__(self) -> None:
        if self.mode not in {"disabled", "shadow", "required"}:
            raise _error(500, "SEMANTIC_ADMISSION_MODE_INVALID", "Planning mode is invalid.")

    def admit_and_compile(
        self, request: SemanticCandidateAdmissionRequest
    ) -> SemanticCandidateAdmissionResult:
        if self.mode == "disabled":
            return SemanticCandidateAdmissionResult(
                mode="disabled",
                status="DISABLED",
                directive="USE_COMPATIBILITY_PATH",
                agent_execution_id=None,
            )
        admitted = self.admission.admit_prompt(
            tenant_id=request.tenant_id,
            principal_id=request.owner_subject_id,
            profile_ref=request.profile_ref,
            trigger_id=request.interaction_id,
            interaction_id=request.interaction_id,
            workspace_id=request.workspace_id,
            conversation_id=request.conversation_id,
            correlation_id=request.correlation_id,
            causation_id=request.causation_id,
            project_id=None,
        )
        execution = admitted.execution
        if execution is None:
            return SemanticCandidateAdmissionResult(
                mode=self.mode,
                status="SHADOW_SKIPPED",
                directive="USE_COMPATIBILITY_PATH",
                agent_execution_id=None,
                shadow_error_code=admitted.shadow_error_code,
            )
        execution_id = str(execution["agent_execution_id"])
        now = _timestamp(self.clock())
        ids = _AdmissionIds(execution_id)
        stages: list[SemanticStageProjection] = []

        intent_evidence, intent_candidate, intent_result, resumed = self._stage(
            request=request,
            execution_id=execution_id,
            semantic_stage="INTENT",
            candidate_id=ids.candidate("INTENT"),
            invoke=lambda: self.intent_stage.generate_and_resolve(
                user_prompt=request.user_prompt,
                execution_id=execution_id,
                source_ref=f"AE:INTERACTION:{request.interaction_id}",
                actor_ref=f"OA:SUBJECT:{request.owner_subject_id}",
                received_at=str(execution["received_at"]),
                request_id=request.request_id,
                trace_id=request.trace_id,
                planning_mode=self.mode,
                retrieval_enabled=request.retrieval_enabled,
                authorized_resource_context_available=(
                    request.authorized_resource_context_available
                ),
                trusted_execution_mode=request.trusted_execution_mode,
                work_intent_id=ids.work_intent,
            ),
            now=now,
        )
        stages.append(_stage_projection(intent_evidence, resumed=resumed))
        if intent_evidence["directive"] != "CONTINUE":
            return _stopped(self.mode, execution_id, stages)
        work_intent = self.work_intents.get(
            tenant_id=request.tenant_id, work_intent_id=ids.work_intent
        )
        if work_intent is None:
            if intent_result is not None and intent_result.work_intent is not None:
                work_intent = dict(intent_result.work_intent)
            else:
                intent_decision = resolve_intent_candidate(
                    intent_candidate,
                    trusted_execution_mode=request.trusted_execution_mode,
                    retrieval_enabled=request.retrieval_enabled,
                )
                work_intent = build_work_intent_from_decision(
                    execution_id=execution_id,
                    source_ref=f"AE:INTERACTION:{request.interaction_id}",
                    actor_ref=f"OA:SUBJECT:{request.owner_subject_id}",
                    received_at=str(execution["received_at"]),
                    intent_decision=intent_decision,
                    input_context_hash=intent_evidence["input_context_hash"],
                    work_intent_id=ids.work_intent,
                    prompt_provenance=_work_intent_provenance(intent_evidence),
                )
            work_intent = self.work_intents.save(
                tenant_id=request.tenant_id,
                work_intent=work_intent,
                created_at=now,
            )

        context_evidence, context_candidate, context_result, resumed = self._stage(
            request=request,
            execution_id=execution_id,
            semantic_stage="CONTEXT",
            candidate_id=ids.candidate("CONTEXT"),
            invoke=lambda: self.context_stage.generate_and_resolve(
                work_intent=work_intent,
                base_context=request.base_context,
                tenant_id=request.tenant_id,
                principal_id=request.owner_subject_id,
                agent_id=str(execution["agent_id"]),
                execution_id=execution_id,
                workspace_id=request.workspace_id,
                conversation_id=request.conversation_id,
                interaction_id=request.interaction_id,
                runtime_policy_ref=request.runtime_policy_ref,
                resolver=request.context_resolver,
                request_id=request.request_id,
                trace_id=request.trace_id,
                planning_mode=self.mode,
                context_id=ids.context,
                built_at=now,
            ),
            now=now,
        )
        stages.append(_stage_projection(context_evidence, resumed=resumed))
        if context_evidence["directive"] != "CONTINUE":
            return _stopped(
                self.mode, execution_id, stages, work_intent_id=ids.work_intent
            )
        agent_context = self.contexts.get(
            tenant_id=request.tenant_id, context_id=ids.context
        )
        if agent_context is None:
            if context_result is not None and context_result.agent_context is not None:
                agent_context = dict(context_result.agent_context)
            else:
                agent_context = build_agent_context(
                    tenant_id=request.tenant_id,
                    principal_id=request.owner_subject_id,
                    agent_id=str(execution["agent_id"]),
                    execution_id=execution_id,
                    workspace_id=request.workspace_id,
                    conversation_id=request.conversation_id,
                    interaction_id=request.interaction_id,
                    work_intent=work_intent,
                    runtime_policy_ref=request.runtime_policy_ref,
                    resolver=request.context_resolver,
                    candidate_hints=context_candidate_hints(
                        context_candidate,
                        candidate_hash=context_evidence["candidate_hash"],
                    ),
                    context_id=ids.context,
                    built_at=context_evidence["created_at"],
                )
            agent_context = self.contexts.save(
                tenant_id=request.tenant_id, agent_context=agent_context
            )

        capability_snapshot = self.capabilities.save(request.capability_snapshot)
        plan_evidence, plan_candidate, plan_result, resumed = self._stage(
            request=request,
            execution_id=execution_id,
            semantic_stage="PLAN",
            candidate_id=ids.candidate("PLAN"),
            invoke=lambda: self.plan_stage.generate_and_bind(
                work_intent=work_intent,
                agent_context=agent_context,
                capability_snapshot=capability_snapshot,
                request_id=request.request_id,
                trace_id=request.trace_id,
                planning_mode=self.mode,
                agent_plan_id=ids.plan,
            ),
            now=now,
        )
        stages.append(_stage_projection(plan_evidence, resumed=resumed))
        if plan_evidence["directive"] != "CONTINUE":
            return _stopped(
                self.mode,
                execution_id,
                stages,
                work_intent_id=ids.work_intent,
                agent_context_id=ids.context,
            )
        agent_plan = self.plans.get(
            tenant_id=request.tenant_id, agent_plan_id=ids.plan
        )
        if agent_plan is None:
            if plan_result is not None and plan_result.agent_plan is not None:
                agent_plan = dict(plan_result.agent_plan)
            else:
                agent_plan = bind_plan_candidate(
                    candidate=plan_candidate,
                    candidate_hash=plan_evidence["candidate_hash"],
                    work_intent=work_intent,
                    agent_context=agent_context,
                    capability_snapshot=capability_snapshot,
                    prompt_provenance=_prompt_provenance(plan_evidence),
                    model_provenance=_model_provenance(plan_evidence),
                    agent_plan_id=ids.plan,
                )
            agent_plan = self.plans.save(
                tenant_id=request.tenant_id,
                agent_plan=agent_plan,
                created_at=now,
            )

        validation = self.validations.get(
            tenant_id=request.tenant_id,
            validation_result_id=ids.validation,
        )
        if validation is None:
            validation = validate_agent_plan(
                agent_plan=agent_plan,
                work_intent=work_intent,
                agent_context=agent_context,
                capability_snapshot=capability_snapshot,
                validation_result_id=ids.validation,
                validated_at=now,
            )
            current_execution = self.executions.get(
                request.tenant_id, execution_id
            )
            if current_execution is None:
                raise _error(
                    409,
                    "AGENT_EXECUTION_NOT_FOUND",
                    "AgentExecution disappeared before deterministic validation.",
                )
            validation = self.validations.save_and_apply_runtime(
                tenant_id=request.tenant_id,
                result=validation,
                expected_execution_version=int(current_execution["version"]),
            )
        if validation["status"] != "VALID":
            return SemanticCandidateAdmissionResult(
                mode=self.mode,
                status="VALIDATION_BLOCKED",
                directive=str(validation["runtime_directive"]),
                agent_execution_id=execution_id,
                work_intent_id=ids.work_intent,
                agent_context_id=ids.context,
                agent_plan_id=ids.plan,
                validation_result_id=ids.validation,
                validation_status=str(validation["status"]),
                stages=tuple(stages),
            )

        executable_plan = self.executable_plans.get(
            tenant_id=request.tenant_id,
            executable_plan_id=ids.executable_plan,
        )
        if executable_plan is None:
            executable_plan = compile_executable_plan(
                agent_plan=agent_plan,
                validation_result=validation,
                agent_context=agent_context,
                capability_snapshot=capability_snapshot,
                executable_plan_id=ids.executable_plan,
                compiled_at=now,
                id_factory=ids.compiled_step_factory(),
            )
            executable_plan = self.executable_plans.save(
                tenant_id=request.tenant_id,
                executable_plan=executable_plan,
            )
        return SemanticCandidateAdmissionResult(
            mode=self.mode,
            status="COMPILED",
            directive="ACCEPT_RUNTIME_WORK",
            agent_execution_id=execution_id,
            work_intent_id=ids.work_intent,
            agent_context_id=ids.context,
            agent_plan_id=ids.plan,
            validation_result_id=ids.validation,
            validation_status=str(validation["status"]),
            executable_plan_id=ids.executable_plan,
            executable_plan_hash=str(executable_plan["executable_plan_hash"]),
            stages=tuple(stages),
        )

    def _stage(
        self,
        *,
        request: SemanticCandidateAdmissionRequest,
        execution_id: str,
        semantic_stage: str,
        candidate_id: str,
        invoke: Callable[[], Any],
        now: str,
    ) -> tuple[dict[str, Any], dict[str, Any], Any | None, bool]:
        existing = self.evidence.get(
            tenant_id=request.tenant_id, candidate_id=candidate_id
        )
        if existing is not None:
            _require_stage_lineage(
                existing,
                request=request,
                execution_id=execution_id,
                semantic_stage=semantic_stage,
            )
            candidate = self.candidate_storage.load(
                candidate_payload_metadata_from_evidence(existing),
                tenant_id=request.tenant_id,
                owner_subject_id=request.owner_subject_id,
            )
            if candidate is None:
                raise _error(
                    409,
                    "CANDIDATE_PAYLOAD_MISSING",
                    "Persisted candidate evidence has no private payload.",
                )
            return existing, candidate, None, True

        result = invoke()
        if result.admission_policy_ref is None:
            raise _error(
                503,
                "SEMANTIC_CALIBRATION_REQUIRED",
                "Durable semantic admission needs an exact calibration policy.",
            )
        payload = build_semantic_candidate_payload(
            candidate_id=candidate_id, candidate=result.candidate
        )
        if f"sha256:{payload['content_sha256']}" != result.candidate_hash:
            raise _error(
                409,
                "CANDIDATE_HASH_MISMATCH",
                "Semantic stage candidate hash does not match its payload.",
            )
        saved_ref = self.candidate_storage.save(
            payload,
            tenant_id=request.tenant_id,
            owner_subject_id=request.owner_subject_id,
        )
        if saved_ref != payload["storage_ref"]:
            raise _error(
                409,
                "CANDIDATE_STORAGE_REF_MISMATCH",
                "Semantic candidate storage returned an inconsistent reference.",
            )
        evidence = build_semantic_candidate_evidence(
            tenant_id=request.tenant_id,
            owner_subject_id=request.owner_subject_id,
            candidate_id=candidate_id,
            execution_id=execution_id,
            semantic_stage=semantic_stage,
            candidate_revision=1,
            candidate_payload=payload,
            provider_output_sha256=result.provider_output_sha256,
            input_context_hash=result.input_context_hash,
            prompt_provenance=result.prompt_provenance,
            model_provenance=result.model_provenance,
            request_id=request.request_id,
            trace_id=request.trace_id,
            admission_policy_ref=result.admission_policy_ref,
            directive=result.directive,
            failure_code=result.failure_code,
            created_at=now,
        )
        saved = self.evidence.save(evidence)
        return saved, dict(result.candidate), result, False


@dataclass(frozen=True)
class _AdmissionIds:
    execution_id: str

    @property
    def work_intent(self) -> str:
        return self._id("work-intent")

    @property
    def context(self) -> str:
        return self._id("agent-context")

    @property
    def plan(self) -> str:
        return self._id("agent-plan")

    @property
    def validation(self) -> str:
        return self._id("plan-validation")

    @property
    def executable_plan(self) -> str:
        return self._id("executable-plan")

    def candidate(self, semantic_stage: str) -> str:
        return self._id(f"candidate:{semantic_stage.lower()}:1")

    def compiled_step_factory(self) -> Callable[[], str]:
        index = 0

        def next_id() -> str:
            nonlocal index
            index += 1
            return self._id(f"compiled-step:{index}")

        return next_id

    def _id(self, identity: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"nex:p65:{self.execution_id}:{identity}"))


def _stage_projection(
    evidence: Mapping[str, Any], *, resumed: bool
) -> SemanticStageProjection:
    return SemanticStageProjection(
        semantic_stage=str(evidence["semantic_stage"]),
        candidate_id=str(evidence["candidate_id"]),
        candidate_hash=str(evidence["candidate_hash"]),
        directive=str(evidence["directive"]),
        validation_outcome=str(evidence["validation_outcome"]),
        prompt_template_version_id=str(evidence["prompt_template_version_id"]),
        model_profile=str(evidence["model_profile"]),
        model_ref=str(evidence["model_ref"]),
        resumed=resumed,
    )


def _stopped(
    mode: str,
    execution_id: str,
    stages: list[SemanticStageProjection],
    *,
    work_intent_id: str | None = None,
    agent_context_id: str | None = None,
) -> SemanticCandidateAdmissionResult:
    directive = stages[-1].directive
    return SemanticCandidateAdmissionResult(
        mode=mode,
        status="CANDIDATE_BLOCKED" if directive != "SHADOW_ONLY" else "SHADOW_ONLY",
        directive=directive,
        agent_execution_id=execution_id,
        work_intent_id=work_intent_id,
        agent_context_id=agent_context_id,
        stages=tuple(stages),
    )


def _require_stage_lineage(
    evidence: Mapping[str, Any],
    *,
    request: SemanticCandidateAdmissionRequest,
    execution_id: str,
    semantic_stage: str,
) -> None:
    if (
        evidence.get("tenant_id") != request.tenant_id
        or evidence.get("owner_subject_id") != request.owner_subject_id
        or evidence.get("execution_id") != execution_id
        or evidence.get("semantic_stage") != semantic_stage
        or evidence.get("candidate_revision") != 1
    ):
        raise _error(
            409,
            "CANDIDATE_EVIDENCE_LINEAGE_CONFLICT",
            "Semantic candidate evidence lineage does not match the request.",
        )


def _prompt_provenance(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "prompt_binding_id": evidence["prompt_binding_id"],
        "prompt_binding_key": evidence["prompt_binding_key"],
        "prompt_template_version_id": evidence["prompt_template_version_id"],
        "prompt_template_version": evidence["prompt_template_version"],
        "prompt_content_sha256": evidence["prompt_content_sha256"],
        "rendered_prompt_hash": evidence["rendered_prompt_hash"],
        "input_context_hash": evidence["input_context_hash"],
    }


def _model_provenance(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "model_profile": evidence["model_profile"],
        "model_ref": evidence["model_ref"],
        "deployment_id": evidence["deployment_id"],
        "mo_generation_id": evidence["mo_generation_id"],
    }


def _work_intent_provenance(evidence: Mapping[str, Any]) -> dict[str, Any]:
    prompt = _prompt_provenance(evidence)
    return {
        "prompt_binding_key": prompt["prompt_binding_key"],
        "prompt_template_version_id": prompt["prompt_template_version_id"],
        "prompt_content_sha256": prompt["prompt_content_sha256"],
        "rendered_prompt_hash": prompt["rendered_prompt_hash"],
        "model_profile": evidence["model_profile"],
        "model_ref": evidence["model_ref"],
    }


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def attach_semantic_candidate_admission(
    app: Any,
    persistence: Any,
    agent_runtime: Any,
    *,
    prompt_store: Any,
    environ: Mapping[str, str] | None = None,
) -> SemanticCandidateAdmissionRuntime:
    mode = planning_mode(environ)
    if mode == "disabled":
        runtime = SemanticCandidateAdmissionRuntime(
            mode=mode,
            available=False,
            service=None,
            unavailable_reason="planning_disabled",
        )
        app.state.ae_semantic_candidate_admission = runtime
        return runtime
    runtime_mode = getattr(agent_runtime, "mode", "disabled")
    if (mode == "required" and runtime_mode != "required") or (
        mode == "shadow" and runtime_mode not in {"shadow", "required"}
    ):
        raise _error(
            500,
            "SEMANTIC_RUNTIME_MODE_MISMATCH",
            "Planning and Agent Runtime modes are incompatible.",
        )
    session_factory = getattr(persistence, "api_session_factory", None)
    admission = getattr(agent_runtime, "admission", None)
    if session_factory is None or admission is None:
        if mode == "required":
            raise _error(
                503,
                "SEMANTIC_ADMISSION_PERSISTENCE_REQUIRED",
                "Required semantic admission needs AE PostgreSQL persistence.",
                True,
            )
        runtime = SemanticCandidateAdmissionRuntime(
            mode=mode,
            available=False,
            service=None,
            unavailable_reason="persistence_not_configured",
        )
        app.state.ae_semantic_candidate_admission = runtime
        return runtime

    candidate_storage = build_default_semantic_candidate_storage(environ)
    if mode == "required" and isinstance(
        candidate_storage, InMemorySemanticCandidateStorage
    ):
        raise _error(
            503,
            "SEMANTIC_CANDIDATE_STORAGE_REQUIRED",
            "Required semantic admission needs durable AE private storage.",
            True,
        )
    client = build_default_ae_mo_generation_client(environ)
    calibrations = SemanticCalibrationRegistry.from_environment(environ)
    service = DeterministicCandidateAdmissionService(
        mode=mode,
        admission=admission,
        intent_stage=LiveIntentCandidateService(client, prompt_store, calibrations),
        context_stage=LiveContextCandidateService(client, prompt_store, calibrations),
        plan_stage=LivePlanCandidateService(client, prompt_store, calibrations),
        evidence=SqlAlchemySemanticCandidateEvidenceRepository(session_factory),
        candidate_storage=candidate_storage,
        work_intents=SqlAlchemyWorkIntentRepository(session_factory),
        contexts=SqlAlchemyAgentContextRepository(session_factory),
        capabilities=SqlAlchemyCapabilitySnapshotRepository(session_factory),
        plans=SqlAlchemyAgentPlanRepository(session_factory),
        validations=SqlAlchemyPlanValidationRepository(session_factory),
        executable_plans=SqlAlchemyExecutablePlanRepository(session_factory),
        executions=SqlAlchemyAgentExecutionRepository(session_factory),
    )
    runtime = SemanticCandidateAdmissionRuntime(
        mode=mode,
        available=True,
        service=service,
    )
    app.state.ae_semantic_candidate_admission = runtime
    return runtime


@dataclass(frozen=True)
class _ChatTrustedContextResolver:
    tenant_id: str
    owner_subject_id: str
    interaction_id: str
    user_prompt: str = field(repr=False)
    retrieval_package: Mapping[str, Any] | None = field(repr=False)
    as_of: str

    def resolve(self, request: Any) -> TrustedContextResolution:
        if (
            request.tenant_id != self.tenant_id
            or request.principal_id != self.owner_subject_id
            or request.interaction_id != self.interaction_id
        ):
            raise _error(
                409,
                "TRUSTED_CONTEXT_SCOPE_MISMATCH",
                "Trusted context resolver scope does not match the request.",
            )
        manifest = [
            {
                "kind": "INTERACTION_REF",
                "source_ref": f"AE:INTERACTION:{self.interaction_id}",
                "source_version": "1",
                "content_hash": semantic_sha256_hash_ref(
                    {"interaction_text": self.user_prompt}
                ),
                "as_of": self.as_of,
            }
        ]
        retrieval_refs: tuple[Mapping[str, Any], ...] = ()
        evidence_refs: tuple[Mapping[str, Any], ...] = ()
        if self.retrieval_package is not None:
            package_id = _request_text(
                self.retrieval_package, "retrieval_package_id", 200
            )
            package_hash = _package_hash(self.retrieval_package)
            package_ref = {
                "system": "nex-cx",
                "resource_type": "RETRIEVAL_PACKAGE",
                "resource_id": package_id,
                "version": package_hash,
            }
            retrieval_refs = (package_ref,)
            evidence_refs = (package_ref,)
            manifest.append(
                {
                    "kind": "RETRIEVAL_PACKAGE_REF",
                    "source_ref": f"CX:RETRIEVAL_PACKAGE:{package_id}",
                    "source_version": package_hash,
                    "content_hash": package_hash,
                    "as_of": self.as_of,
                }
            )
        return TrustedContextResolution(
            project_ref=None,
            authority_ref=f"OA:SUBJECT:{self.owner_subject_id}",
            resolved_entities=(),
            retrieval_refs=retrieval_refs,
            evidence_refs=evidence_refs,
            conflicts=(),
            degradations=(),
            context_manifest=tuple(manifest),
            budget_tokens=4096,
            estimated_used_tokens=min(512, 128 + 64 * len(manifest)),
        )


def _package_hash(value: Mapping[str, Any]) -> str:
    candidate = value.get("package_hash")
    if isinstance(candidate, str):
        try:
            return validate_hash_ref(candidate)
        except ValueError:
            if len(candidate) == 64 and all(
                character in "0123456789abcdef" for character in candidate
            ):
                return f"sha256:{candidate}"
    return semantic_sha256_hash_ref(
        {
            "retrieval_package_id": value.get("retrieval_package_id"),
            "status": value.get("status"),
            "evidence_count": len(value.get("evidence_items", []))
            if isinstance(value.get("evidence_items"), list)
            else 0,
        }
    )


def _resource_label_hints(
    retrieval_package: Mapping[str, Any] | None,
) -> list[str]:
    if retrieval_package is None:
        return []
    labels: list[str] = []
    evidence_items = retrieval_package.get("evidence_items")
    if not isinstance(evidence_items, list):
        return labels
    for item in evidence_items:
        if not isinstance(item, Mapping):
            continue
        for key in ("document_title", "source_label", "resource_label"):
            label = _optional_request_text(item.get(key), 256)
            if label is not None and label not in labels:
                labels.append(label)
                break
        if len(labels) >= 32:
            break
    return labels


def _request_text(value: Mapping[str, Any], field_name: str, maximum: int) -> str:
    selected = _optional_request_text(value.get(field_name), maximum)
    if selected is None:
        raise _error(
            400,
            "SEMANTIC_ADMISSION_SCOPE_REQUIRED",
            f"{field_name} is required for semantic admission.",
        )
    return selected


def _optional_request_text(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _error(
            400,
            "SEMANTIC_ADMISSION_REQUEST_INVALID",
            "Semantic admission request text is invalid.",
        )
    return value.strip()


def _error(
    status_code: int,
    error_code: str,
    detail: str,
    retryable: bool = False,
) -> SemanticCandidateAdmissionError:
    return SemanticCandidateAdmissionError(
        status_code, error_code, detail, retryable
    )
