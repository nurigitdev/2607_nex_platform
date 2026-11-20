from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from mybee_ax.integrations.nex_business_approval_client import (
    BusinessApprovalConsumerError,
)
from mybee_ax.orchestration import load_m1_transaction_preparation_registration
from nex_ae_api.agent_context import TrustedContextResolution
from nex_ae_api.agent_runtime_worker import AgentRuntimeAssignment
from nex_ae_api.m1_plan_materialization import M1PlanMaterializationError
from nex_ae_api.m1_product_planning_coordinator import (
    build_m1_product_planning_coordinator_registry,
)
from nex_ae_api.mo_generation_client import AeMoGenerationClientError
from nex_ae_api.product_capabilities import load_product_capability_registry
from nex_ae_api.product_planning_coordinators import (
    ProductPlanningCapabilityBinding,
    ProductPlanningPolicy,
)
from nex_ae_api.product_planning_event_api import (
    register_product_planning_event_routes,
)
from nex_ae_api.product_planning_runtime import (
    InstalledProductCoordinatorAssignmentHandler,
    InstalledProductCoordinatorRuntime,
    InstalledProductCoordinatorRuntimeRegistry,
    InstalledProductPlanningEventAdmission,
    ProductPlanningRuntimeError,
    PublicProductPlanningRouter,
    SqlAlchemyProductPlanningLineageSource,
    build_contract_m1_product_planning_composition,
    build_installed_m1_product_coordinator_runtime,
    build_installed_product_planning_composition,
)
from nex_ae_api.prompts import AE_PLAN_BUILDER_BINDING
from nex_ae_api.runtime_composition import (
    RuntimeExecutorProfile,
    build_installed_runtime_composition,
)
from nex_ae_api.runtime_jobs import (
    RuntimeJobClaim,
    RuntimeJobError,
    SqlAlchemyRuntimeJobQueue,
)
from nex_ae_api.runtime_resume import ResumeRoute
from nex_ae_api.semantic_candidate_admission import SemanticCandidateAdmissionError
from nex_ae_api.semantic_candidates import SemanticCandidateStageError
from nex_ae_api.step_executors import P5StepExecutorRegistry
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from test_ae_p65_s5_candidate_admission_compile import (
    _components as _semantic_components,
)
from test_ae_p65_s5_candidate_admission_compile import (
    _request as _semantic_request,
)

ROOT = Path(__file__).resolve().parents[1]
TENANT = "VO00"
EXECUTION_ID = "11111111-1111-4111-8111-111111111153"
WORK_INTENT_ID = "22222222-2222-4222-8222-222222222253"
CHECKPOINT_ID = "33333333-3333-4333-8333-333333333353"
CHECKPOINT_HASH = "sha256:" + "3" * 64
DETERMINISTIC_POLICY = ProductPlanningPolicy(
    mode="DETERMINISTIC_ONLY",
    proposal_schema_version="ae.product_planning_proposal.v1",
    prompt_binding_key="ae.plan_builder.project_delegation.v1",
    admission_policy_ref="ae.product_planning_proposal.strict.v1",
    deterministic_fallback_ref=None,
    proposal_consumers=(),
)
OPTIONAL_POLICY = ProductPlanningPolicy(
    mode="PROVIDER_ASSISTED_OPTIONAL",
    proposal_schema_version="ae.product_planning_proposal.v1",
    prompt_binding_key=AE_PLAN_BUILDER_BINDING,
    admission_policy_ref="ae.product_planning_proposal.strict.v1",
    deterministic_fallback_ref="nex-ae:test-product-fallback:v1",
    proposal_consumers=("PREPARATION",),
)


class _LegacyProductBoundaryError(RuntimeError):
    def __init__(self, code: str, detail: str, *, retryable: bool = False) -> None:
        self.code = code
        self.detail = detail
        self.retryable = retryable
        super().__init__(detail)


REQUIRED_POLICY = replace(
    OPTIONAL_POLICY,
    mode="PROVIDER_ASSISTED_REQUIRED",
    deterministic_fallback_ref=None,
)


class _Coordinator:
    def __init__(self, registration, *, ready=False) -> None:
        self.registration = registration
        self.ready = ready
        self.begin_calls = []
        self.event_calls = []
        self.resume_calls = []
        self.started = None

    def begin(self, **values):
        self.begin_calls.append(values)
        result = {
            "checkpoint": {
                "checkpoint_id": CHECKPOINT_ID,
                "checkpoint_hash": CHECKPOINT_HASH,
                "stage": "WAITING_BUSINESS_APPROVAL",
            },
            "ready": False,
            "replayed": False,
            "planning_proposal_ref": (
                None
                if values.get("planning_proposal") is None
                else {
                    "proposal_hash": values["planning_proposal"]["proposal_hash"]
                }
            ),
            "planning_fallback_ref": values.get("planning_fallback_ref"),
        }
        self.started = result
        return result

    def replay_begin(self, **_values):
        if self.started is None:
            return None
        return {**self.started, "replayed": True}

    def resume_approval(self, **values):
        self.resume_calls.append(values)
        return {
            "checkpoint": {
                "checkpoint_id": CHECKPOINT_ID,
                "checkpoint_hash": CHECKPOINT_HASH,
                "stage": "READY_FOR_D04"
                if self.ready
                else "WAITING_ACCOUNTING_APPROVAL",
            },
            "ready": self.ready,
            "replayed": False,
        }

    def accept_approval_notification(self, **values):
        self.event_calls.append(values)
        return {"replayed": False}


class _Activation:
    def __init__(self, registration) -> None:
        self.registration = registration
        self.calls = []

    def activate(self, **values):
        self.calls.append(values)
        return {
            "executable_plan_id": "44444444-4444-4444-8444-444444444453",
            "runtime_job": {"runtime_job_id": "job-d04"},
        }


class _RouteSource:
    def __init__(self, route) -> None:
        self.route = route
        self.calls = []

    def resolve(self, **values):
        self.calls.append(values)
        return self.route


class _LineageSource:
    def __init__(self, values) -> None:
        self.values = values
        self.calls = []

    def load(self, route):
        self.calls.append(route)
        return self.values


class _ResumeService:
    def __init__(self) -> None:
        self.calls = []

    def reconcile(self, **values):
        self.calls.append(values)
        return {
            "event_state": "MATCHED",
            "wait_state": "RESUME_QUEUED",
            "resume_runtime_job_id": "runtime-job-product",
        }


class _RuntimeJobs:
    def __init__(self, *, complete_error=None, fail_error=None) -> None:
        self.complete_error = complete_error
        self.fail_error = fail_error
        self.complete_calls = []
        self.fail_calls = []

    def complete(self, **values):
        self.complete_calls.append(values)
        if self.complete_error is not None:
            raise self.complete_error
        return {"state": "DONE", "attempt_no": 1}

    def fail(self, **values):
        self.fail_calls.append(values)
        if self.fail_error is not None:
            raise self.fail_error
        return {
            "state": "QUEUED" if values.get("retry_at") else "FAILED",
            "attempt_no": 1,
        }


class _StepExecutor:
    def execute(self, _context, *, continuation_result=None):
        return continuation_result


class _StoredRepository:
    def __init__(self, value) -> None:
        self.value = value

    def get(self, *_args, **_values):
        return self.value

    def get_latest(self, **_values):
        return self.value


class _FailingAdmission:
    def __init__(self, error) -> None:
        self.error = error

    def ingest(self, _payload):
        raise self.error


class _ProductRouterSpy:
    def __init__(self, registration=None, *, replay_result=None) -> None:
        self.calls = []
        self.replay_calls = []
        self.registration = registration
        self.replay_result = replay_result

    def resolve_registration(self, **_values):
        return self.registration or SimpleNamespace(
            planning_policy=DETERMINISTIC_POLICY
        )

    def replay_if_registered(self, **values):
        self.replay_calls.append(values)
        return self.replay_result

    def begin_if_registered(self, **values):
        self.calls.append(values)
        return {
            "checkpoint_id": CHECKPOINT_ID,
            "checkpoint_hash": CHECKPOINT_HASH,
            "provider_plan_authoritative": False,
            "planning_fallback_ref": values.get("planning_fallback_ref"),
        }


class _FailingPlanStage:
    def __init__(self, error) -> None:
        self.error = error
        self.calls = 0

    def generate_proposal(self, **_values):
        self.calls += 1
        raise self.error


class _ClaimedResolver:
    def resolve(self, request):
        return TrustedContextResolution(
            project_ref={
                "system": "nex-wc",
                "resource_type": "PROJECT",
                "resource_id": "project-product-router",
            },
            authority_ref="WC:WORK_ITEM:work-item-product-router",
            resolved_entities=(),
            retrieval_refs=(),
            evidence_refs=(),
            conflicts=(),
            degradations=(),
            context_manifest=(
                {
                    "kind": "CLAIMED_WORKITEM_REF",
                    "source_ref": "WC:WORK_ITEM:work-item-product-router",
                    "source_version": "1",
                    "content_hash": "sha256:" + "5" * 64,
                    "as_of": "2026-10-17T02:00:00Z",
                },
            ),
            budget_tokens=4096,
            estimated_used_tokens=128,
        )


def _claimed_product_request(service):
    service.executions.record.update(
        {
            "tenant_id": "tenant-a",
            "agent_execution_id": EXECUTION_ID,
            "agent_id": "20000000-0000-4000-8000-000000000656",
            "agent_type": "PA",
            "project_id": "project-product-router",
            "source_type": "CLAIMED_WORKITEM",
            "source_ref": "work-item-product-router",
            "work_item_ref": "work-item-product-router",
            "requester_ref": "user-a",
            "received_at": "2026-10-17T02:00:00Z",
        }
    )
    return replace(
        _semantic_request(),
        planning_source_type="CLAIMED_WORKITEM",
        existing_execution_id=EXECUTION_ID,
        agent_type="PA",
        project_id="project-product-router",
        source_ref="work-item-product-router",
        planning_source={
            "schema_version": "p7.claimed_work_planning_source.v1",
            "source_type": "CLAIMED_WORKITEM",
            "source_ref": "work-item-product-router",
            "goal": "Prepare the admitted Product operation.",
            "work_class": "ANALYSIS",
            "required_capability": "AE.CHAT.COMPATIBILITY",
            "project_ref": {
                "entity_type": "PROJECT",
                "entity_id": "project-product-router",
            },
            "artifact_refs": [],
            "evidence_refs": [],
            "completion_policy": "OWNER_SUBMITS",
            "result_contract_ref": "contract://product/result/v1",
        },
        context_resolver=_ClaimedResolver(),
    )


def _provider_registration(mode: str):
    registration = _runtime()[1]
    chat_binding = ProductPlanningCapabilityBinding(
        capability_id="AE.CHAT.COMPATIBILITY",
        capability_version="1.0.0",
        capability_registration_hash="sha256:" + "7" * 64,
    )
    return replace(
        registration,
        planning_policy=ProductPlanningPolicy(
            mode=mode,
            proposal_schema_version="ae.product_planning_proposal.v1",
            prompt_binding_key=AE_PLAN_BUILDER_BINDING,
            admission_policy_ref="ae.product_planning_proposal.strict.v1",
            deterministic_fallback_ref=(
                "nex-ae:test-product-fallback:v1"
                if mode == "PROVIDER_ASSISTED_OPTIONAL"
                else None
            ),
            proposal_consumers=("PREPARATION",),
        ),
        required_capabilities=(chat_binding,),
    )


def _registry(*, active: bool, planning_policy=DETERMINISTIC_POLICY):
    capabilities = load_product_capability_registry(
        {
            "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
                ROOT
                / "deployment/environments/ae-product-capability-registry.mybee-m1.v4.json"
            )
        }
    )
    return build_m1_product_planning_coordinator_registry(
        product_capabilities=capabilities,
        preparation_registration=load_m1_transaction_preparation_registration(),
        activation_status="ACTIVE" if active else "CONTRACT_ONLY",
        planning_policy=planning_policy,
    )


def _inputs(registration):
    return {
        "work_intent": {
            "work_intent_id": WORK_INTENT_ID,
            "intent_hash": "sha256:" + "1" * 64,
            "required_capability_hints": [registration.capability_id],
        },
        "agent_context": {
            "context_id": "context-1",
            "context_hash": "sha256:" + "2" * 64,
        },
        "capability_snapshot": {
            "capabilities": [
                {
                    "capability_id": registration.capability_id,
                    "capability_version": registration.capability_version,
                }
            ]
        },
        "execution": {"execution_id": EXECUTION_ID},
    }


def _planning_proposal(registration, inputs):
    proposal = {
        "schema_version": "ae.product_planning_proposal.v1",
        "tenant_id": TENANT,
        "owner_subject_id": "employee-100",
        "execution_id": EXECUTION_ID,
        "work_intent_ref": {
            "work_intent_id": inputs["work_intent"]["work_intent_id"],
            "intent_hash": inputs["work_intent"]["intent_hash"],
        },
        "agent_context_ref": {
            "context_id": inputs["agent_context"]["context_id"],
            "context_hash": inputs["agent_context"]["context_hash"],
        },
        "coordinator_ref": {
            "coordinator_id": registration.coordinator_id,
            "coordinator_version": registration.coordinator_version,
            "coordinator_registration_hash": registration.registration_hash,
        },
        "planning_policy": registration.planning_policy.projection(),
        "candidate_ref": {
            "candidate_id": "candidate-product-plan-1",
            "candidate_hash": "sha256:" + "4" * 64,
            "storage_ref": "private://semantic-candidates/product-plan-1",
            "size_bytes": 128,
        },
        "suggested_capability_ids": [registration.capability_id],
        "provider_provenance": {"model_ref": "provider-test"},
        "created_at": "2026-11-18T01:00:00Z",
        "content_included": False,
        "provider_plan_authoritative": False,
    }
    proposal["proposal_hash"] = semantic_sha256_hash_ref(proposal)
    return proposal


def _runtime(*, ready=False, planning_policy=DETERMINISTIC_POLICY):
    registry = _registry(active=True, planning_policy=planning_policy)
    registration = registry.registrations[0]
    coordinator = _Coordinator(registration, ready=ready)
    activation = _Activation(registration)
    runtime = InstalledProductCoordinatorRuntime(
        registration=registration,
        coordinator=coordinator,
        activation=activation,
    )
    return registry, registration, coordinator, activation, runtime


def _route(registration):
    return ResumeRoute(
        tenant_id=TENANT,
        runtime_job_id="runtime-job-product",
        execution_id=EXECUTION_ID,
        wait_id="wait-product",
        event_id="approval-event",
        resume_target_kind="PRODUCT_COORDINATOR",
        executable_step_id=None,
        payload={},
        product_context={
            "checkpoint_id": CHECKPOINT_ID,
            "checkpoint_hash": CHECKPOINT_HASH,
            "coordinator_id": registration.coordinator_id,
            "coordinator_version": registration.coordinator_version,
            "coordinator_registration_hash": registration.registration_hash,
            "work_intent_id": WORK_INTENT_ID,
        },
    )


def _assignment():
    return AgentRuntimeAssignment(
        tenant_id=TENANT,
        executor_kind=None,
        backend_profile=None,
        assignment_kind="PRODUCT_COORDINATOR",
        claim=RuntimeJobClaim(
            job={
                "tenant_id": TENANT,
                "runtime_job_id": "runtime-job-product",
                "execution_id": EXECUTION_ID,
                "state": "RUNNING",
                "lease_owner": "worker-1",
                "lease_token": "lease-1",
            },
            attempt={"attempt_no": 1},
            assignment_kind="PRODUCT_COORDINATOR",
        ),
    )


def test_public_router_selects_exact_active_capability_and_begins_product() -> None:
    registry, registration, coordinator, _activation, runtime = _runtime()
    runtimes = InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,))
    router = PublicProductPlanningRouter(registry, runtimes)

    result = router.begin_if_registered(**_inputs(registration))

    assert result["stage"] == "WAITING_BUSINESS_APPROVAL"
    assert result["provider_plan_authoritative"] is False
    assert result["coordinator_registration_hash"] == registration.registration_hash
    assert len(coordinator.begin_calls) == 1


def test_public_router_records_and_replays_exact_optional_fallback() -> None:
    registry, registration, coordinator, _activation, runtime = _runtime(
        planning_policy=OPTIONAL_POLICY
    )
    router = PublicProductPlanningRouter(
        registry,
        InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
    )
    inputs = _inputs(registration)

    assert router.replay_if_registered(**inputs) is None
    first = router.begin_if_registered(
        **inputs,
        planning_fallback_ref=OPTIONAL_POLICY.deterministic_fallback_ref,
    )
    replay = router.replay_if_registered(**inputs)

    assert first["planning_proposal_hash"] is None
    assert first["planning_fallback_ref"] == (
        OPTIONAL_POLICY.deterministic_fallback_ref
    )
    assert replay["admission_hash"] != first["admission_hash"]
    assert replay["replayed"] is True
    assert replay["planning_fallback_ref"] == first["planning_fallback_ref"]
    assert len(coordinator.begin_calls) == 1


def test_public_router_replay_preserves_non_product_and_legacy_runtime() -> None:
    registry, registration, _coordinator, activation, runtime = _runtime()
    router = PublicProductPlanningRouter(
        registry,
        InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
    )
    non_product = _inputs(registration)
    non_product["work_intent"] = {"required_capability_hints": ["REPORT.GENERATE"]}
    assert router.replay_if_registered(**non_product) is None

    legacy_runtime = InstalledProductCoordinatorRuntime(
        registration=registration,
        coordinator=SimpleNamespace(
            registration=registration,
            begin=lambda **_values: {},
            accept_approval_notification=lambda **_values: {},
            resume_approval=lambda **_values: {},
        ),
        activation=activation,
    )
    legacy_router = PublicProductPlanningRouter(
        registry,
        InstalledProductCoordinatorRuntimeRegistry(registry, (legacy_runtime,)),
    )
    assert legacy_router.replay_if_registered(**_inputs(registration)) is None


@pytest.mark.parametrize(
    ("policy", "proposal_kind", "fallback_ref", "error_code", "retryable"),
    (
        (
            DETERMINISTIC_POLICY,
            "VALID",
            None,
            "ae.product_planning_runtime_invalid",
            False,
        ),
        (
            DETERMINISTIC_POLICY,
            None,
            "nex-ae:unadmitted-fallback:v1",
            "ae.product_planning_runtime_invalid",
            False,
        ),
        (
            OPTIONAL_POLICY,
            None,
            "nex-ae:drifted-fallback:v1",
            "ae.product_planning_runtime_unavailable",
            True,
        ),
        (
            REQUIRED_POLICY,
            None,
            None,
            "ae.product_planning_runtime_unavailable",
            True,
        ),
        (
            OPTIONAL_POLICY,
            "MALFORMED",
            None,
            "ae.product_planning_runtime_conflict",
            False,
        ),
    ),
)
def test_public_router_rejects_unadmitted_product_planning_selection(
    policy,
    proposal_kind,
    fallback_ref,
    error_code,
    retryable,
) -> None:
    registry, registration, coordinator, _activation, runtime = _runtime(
        planning_policy=policy
    )
    router = PublicProductPlanningRouter(
        registry,
        InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
    )
    inputs = _inputs(registration)
    proposal = (
        _planning_proposal(registration, inputs)
        if proposal_kind == "VALID"
        else ({"schema_version": "invalid"} if proposal_kind == "MALFORMED" else None)
    )

    with pytest.raises(ProductPlanningRuntimeError) as raised:
        router.begin_if_registered(
            **inputs,
            planning_proposal=proposal,
            planning_fallback_ref=fallback_ref,
        )

    assert raised.value.error_code == error_code
    assert raised.value.retryable is retryable
    assert coordinator.begin_calls == []


def test_public_router_rejects_ambiguous_optional_selection() -> None:
    registry, registration, coordinator, _activation, runtime = _runtime(
        planning_policy=OPTIONAL_POLICY
    )
    router = PublicProductPlanningRouter(
        registry,
        InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
    )
    inputs = _inputs(registration)

    with pytest.raises(ProductPlanningRuntimeError) as raised:
        router.begin_if_registered(
            **inputs,
            planning_proposal=_planning_proposal(registration, inputs),
            planning_fallback_ref=OPTIONAL_POLICY.deterministic_fallback_ref,
        )

    assert raised.value.error_code == "ae.product_planning_runtime_invalid"
    assert coordinator.begin_calls == []


def test_public_router_accepts_exact_optional_proposal_without_fallback() -> None:
    registry, registration, coordinator, _activation, runtime = _runtime(
        planning_policy=OPTIONAL_POLICY
    )
    router = PublicProductPlanningRouter(
        registry,
        InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
    )
    inputs = _inputs(registration)
    proposal = _planning_proposal(registration, inputs)

    result = router.begin_if_registered(**inputs, planning_proposal=proposal)

    assert result["planning_proposal_hash"] == proposal["proposal_hash"]
    assert result["planning_fallback_ref"] is None
    assert len(coordinator.begin_calls) == 1


def test_public_router_rejects_drifted_proposal_lineage() -> None:
    registry, registration, coordinator, _activation, runtime = _runtime(
        planning_policy=OPTIONAL_POLICY
    )
    router = PublicProductPlanningRouter(
        registry,
        InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
    )
    inputs = _inputs(registration)
    proposal = _planning_proposal(registration, inputs)
    proposal["work_intent_ref"]["work_intent_id"] = "drifted-work-intent"
    proposal["proposal_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in proposal.items() if key != "proposal_hash"}
    )

    with pytest.raises(ProductPlanningRuntimeError) as raised:
        router.begin_if_registered(**inputs, planning_proposal=proposal)

    assert raised.value.error_code == "ae.product_planning_runtime_conflict"
    assert coordinator.begin_calls == []


def test_claimed_semantic_pipeline_keeps_intent_context_evidence_but_skips_plan() -> (
    None
):
    service, client, *_ = _semantic_components()
    router = _ProductRouterSpy()
    service = replace(service, product_planning_router=router)
    service.executions.record.update(
        {
            "tenant_id": "tenant-a",
            "agent_execution_id": EXECUTION_ID,
            "agent_id": "20000000-0000-4000-8000-000000000656",
            "agent_type": "PA",
            "project_id": "project-product-router",
            "source_type": "CLAIMED_WORKITEM",
            "source_ref": "work-item-product-router",
            "work_item_ref": "work-item-product-router",
            "requester_ref": "user-a",
            "received_at": "2026-10-17T02:00:00Z",
        }
    )
    planning_source = {
        "schema_version": "p7.claimed_work_planning_source.v1",
        "source_type": "CLAIMED_WORKITEM",
        "source_ref": "work-item-product-router",
        "goal": "Prepare the admitted Product operation.",
        "work_class": "ANALYSIS",
        "required_capability": "AE.CHAT.COMPATIBILITY",
        "project_ref": {
            "entity_type": "PROJECT",
            "entity_id": "project-product-router",
        },
        "artifact_refs": [],
        "evidence_refs": [],
        "completion_policy": "OWNER_SUBMITS",
        "result_contract_ref": "contract://product/result/v1",
    }
    request = replace(
        _semantic_request(),
        planning_source_type="CLAIMED_WORKITEM",
        existing_execution_id=EXECUTION_ID,
        agent_type="PA",
        project_id="project-product-router",
        source_ref="work-item-product-router",
        planning_source=planning_source,
        context_resolver=_ClaimedResolver(),
    )

    result = service.admit_and_compile(request)

    assert result.status == "PRODUCT_COORDINATION_STARTED"
    assert result.directive == "WAIT_FOR_PRODUCT_COORDINATION"
    assert [stage.semantic_stage for stage in result.stages] == ["INTENT", "CONTEXT"]
    assert client.calls == ["INTENT", "CONTEXT"]
    assert result.product_planning_admission["provider_plan_authoritative"] is False
    assert len(router.calls) == 1


def test_claimed_product_route_generates_advisory_plan_before_coordinator() -> None:
    service, client, *_ = _semantic_components()
    registration = _runtime()[1]
    chat_binding = ProductPlanningCapabilityBinding(
        capability_id="AE.CHAT.COMPATIBILITY",
        capability_version="1.0.0",
        capability_registration_hash="sha256:" + "7" * 64,
    )
    registration = replace(
        registration,
        planning_policy=ProductPlanningPolicy(
            mode="PROVIDER_ASSISTED_REQUIRED",
            proposal_schema_version="ae.product_planning_proposal.v1",
            prompt_binding_key=AE_PLAN_BUILDER_BINDING,
            admission_policy_ref="ae.product_planning_proposal.strict.v1",
            deterministic_fallback_ref=None,
            proposal_consumers=("PREPARATION",),
        ),
        required_capabilities=(chat_binding,),
    )
    router = _ProductRouterSpy(registration)
    service = replace(service, product_planning_router=router)
    service.executions.record.update(
        {
            "tenant_id": "tenant-a",
            "agent_execution_id": EXECUTION_ID,
            "agent_id": "20000000-0000-4000-8000-000000000656",
            "agent_type": "PA",
            "project_id": "project-product-router",
            "source_type": "CLAIMED_WORKITEM",
            "source_ref": "work-item-product-router",
            "work_item_ref": "work-item-product-router",
            "requester_ref": "user-a",
            "received_at": "2026-10-17T02:00:00Z",
        }
    )
    request = replace(
        _semantic_request(),
        planning_source_type="CLAIMED_WORKITEM",
        existing_execution_id=EXECUTION_ID,
        agent_type="PA",
        project_id="project-product-router",
        source_ref="work-item-product-router",
        planning_source={
            "schema_version": "p7.claimed_work_planning_source.v1",
            "source_type": "CLAIMED_WORKITEM",
            "source_ref": "work-item-product-router",
            "goal": "Prepare the admitted Product operation.",
            "work_class": "ANALYSIS",
            "required_capability": "AE.CHAT.COMPATIBILITY",
            "project_ref": {
                "entity_type": "PROJECT",
                "entity_id": "project-product-router",
            },
            "artifact_refs": [],
            "evidence_refs": [],
            "completion_policy": "OWNER_SUBMITS",
            "result_contract_ref": "contract://product/result/v1",
        },
        context_resolver=_ClaimedResolver(),
    )

    result = service.admit_and_compile(request)

    assert result.status == "PRODUCT_COORDINATION_STARTED"
    assert [stage.semantic_stage for stage in result.stages] == [
        "INTENT",
        "CONTEXT",
        "PLAN",
    ]
    assert client.calls == ["INTENT", "CONTEXT", "PLAN"]
    proposal = router.calls[0]["planning_proposal"]
    assert proposal["provider_plan_authoritative"] is False
    assert proposal["suggested_capability_ids"] == ["AE.CHAT.COMPATIBILITY"]
    assert service.plans.records == {}


def test_optional_provider_unavailable_uses_named_fallback_and_replays() -> None:
    service, client, *_ = _semantic_components()
    registration = _provider_registration("PROVIDER_ASSISTED_OPTIONAL")
    router = _ProductRouterSpy(registration)
    failure = _FailingPlanStage(
        AeMoGenerationClientError(
            503,
            "PROVIDER_NOT_READY",
            "provider is unavailable",
            True,
        )
    )
    service = replace(
        service,
        plan_stage=failure,
        product_planning_router=router,
    )
    request = _claimed_product_request(service)

    first = service.admit_and_compile(request)
    router.replay_result = {
        **first.product_planning_admission,
        "replayed": True,
    }
    client.calls.clear()
    replay = service.admit_and_compile(request)

    fallback_ref = registration.planning_policy.deterministic_fallback_ref
    assert first.status == replay.status == "PRODUCT_COORDINATION_STARTED"
    assert first.product_planning_admission["planning_fallback_ref"] == fallback_ref
    assert router.calls[0]["planning_fallback_ref"] == fallback_ref
    assert failure.calls == 1
    assert client.calls == []
    assert len(router.calls) == 1
    assert len(router.replay_calls) == 2


def test_optional_provider_admitted_proposal_wins_over_fallback() -> None:
    service, client, *_ = _semantic_components()
    registration = _provider_registration("PROVIDER_ASSISTED_OPTIONAL")
    router = _ProductRouterSpy(registration)
    service = replace(service, product_planning_router=router)

    result = service.admit_and_compile(_claimed_product_request(service))

    assert result.status == "PRODUCT_COORDINATION_STARTED"
    assert client.calls == ["INTENT", "CONTEXT", "PLAN"]
    assert router.calls[0]["planning_proposal"] is not None
    assert router.calls[0]["planning_fallback_ref"] is None


@pytest.mark.parametrize(
    "error",
    (
        AeMoGenerationClientError(
            502,
            "PROVIDER_RESPONSE_INVALID",
            "provider response is malformed",
            True,
        ),
        SemanticCandidateStageError(
            422,
            "CANDIDATE_AUTHORITY_VIOLATION",
            "provider candidate contains authority",
        ),
        SemanticCandidateStageError(
            422,
            "CANDIDATE_PRIVATE_DATA_VIOLATION",
            "provider candidate contains private data",
        ),
    ),
)
def test_optional_product_does_not_fallback_on_malformed_or_authority_failure(
    error,
) -> None:
    service, _client, *_ = _semantic_components()
    router = _ProductRouterSpy(
        _provider_registration("PROVIDER_ASSISTED_OPTIONAL")
    )
    failure = _FailingPlanStage(error)
    service = replace(
        service,
        plan_stage=failure,
        product_planning_router=router,
    )

    with pytest.raises(SemanticCandidateAdmissionError):
        service.admit_and_compile(_claimed_product_request(service))

    assert router.calls == []
    assert service.plans.records == {}


def test_required_product_provider_unavailable_fails_without_mutation() -> None:
    service, _client, *_ = _semantic_components()
    router = _ProductRouterSpy(
        _provider_registration("PROVIDER_ASSISTED_REQUIRED")
    )
    failure = _FailingPlanStage(
        AeMoGenerationClientError(
            504,
            "PROVIDER_TIMEOUT",
            "provider timed out",
            True,
        )
    )
    service = replace(
        service,
        plan_stage=failure,
        product_planning_router=router,
    )

    with pytest.raises(SemanticCandidateAdmissionError) as raised:
        service.admit_and_compile(_claimed_product_request(service))

    assert raised.value.error_code == "PROVIDER_TIMEOUT"
    assert router.calls == []
    assert service.plans.records == {}


def test_optional_low_confidence_stops_without_fallback_or_product_mutation() -> None:
    service, client, *_ = _semantic_components(plan_confidence=0.49)
    router = _ProductRouterSpy(
        _provider_registration("PROVIDER_ASSISTED_OPTIONAL")
    )
    service = replace(service, product_planning_router=router)

    result = service.admit_and_compile(_claimed_product_request(service))

    assert result.status == "CANDIDATE_BLOCKED"
    assert result.directive == "REPLAN_REQUIRED"
    assert client.calls == ["INTENT", "CONTEXT", "PLAN"]
    assert router.calls == []
    assert service.plans.records == {}


def test_public_router_preserves_non_product_and_fails_closed_before_activation() -> (
    None
):
    registry, registration, *_ = _runtime()
    router = PublicProductPlanningRouter(
        registry,
        InstalledProductCoordinatorRuntimeRegistry(registry, (_runtime()[-1],)),
    )
    inputs = _inputs(registration)
    inputs["work_intent"] = {"required_capability_hints": ["REPORT.GENERATE"]}
    assert router.begin_if_registered(**inputs) is None

    contract = _registry(active=False)
    contract_router = PublicProductPlanningRouter(
        contract, InstalledProductCoordinatorRuntimeRegistry(contract)
    )
    with pytest.raises(ProductPlanningRuntimeError) as captured:
        contract_router.begin_if_registered(**_inputs(contract.registrations[0]))
    assert captured.value.error_code == "ae.product_planning_runtime_unavailable"
    assert captured.value.retryable is True


@pytest.mark.parametrize("ready", (False, True))
def test_product_assignment_resumes_and_only_activates_exact_ready_state(ready) -> None:
    registry, registration, coordinator, activation, runtime = _runtime(ready=ready)
    route = _route(registration)
    inputs = _inputs(registration)
    runtime_jobs = _RuntimeJobs()
    handler = InstalledProductCoordinatorAssignmentHandler(
        route_source=_RouteSource(route),
        lineage_source=_LineageSource(inputs),
        runtimes=InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
        runtime_jobs=runtime_jobs,
        clock=lambda: datetime(2026, 11, 20, 1, 0, tzinfo=UTC),
    )

    result = handler(_assignment())

    assert result["ready"] is ready
    assert result["runtime_job_state"] == "DONE"
    assert result["runtime_job_attempt_no"] == 1
    assert len(coordinator.resume_calls) == 1
    assert len(activation.calls) == int(ready)
    assert (result["activation"] is not None) is ready
    assert runtime_jobs.complete_calls == [
        {
            "tenant_id": TENANT,
            "runtime_job_id": "runtime-job-product",
            "worker_id": "worker-1",
            "lease_token": "lease-1",
            "now": "2026-11-20T01:00:00Z",
        }
    ]
    assert runtime_jobs.fail_calls == []


@pytest.mark.parametrize(
    ("error", "raised_type", "retry_at", "retry_ref", "error_ref"),
    (
        (
            ProductPlanningRuntimeError("product.unavailable", "unavailable", True),
            ProductPlanningRuntimeError,
            "2026-11-20T01:00:05Z",
            "ae.product_coordinator.retryable",
            "product.unavailable",
        ),
        (
            BusinessApprovalConsumerError(
                "EOS_APPROVED_DOCUMENT_AUTHORIZATION_DENIED",
                "EOS rejected the ApprovedDocument read",
                status_code=403,
            ),
            ProductPlanningRuntimeError,
            None,
            None,
            "EOS_APPROVED_DOCUMENT_AUTHORIZATION_DENIED",
        ),
        (
            M1PlanMaterializationError(
                "M1_PLAN_CONTEXT_DEGRADED",
                "M1 AgentContext contains unresolved degradations.",
            ),
            ProductPlanningRuntimeError,
            None,
            None,
            "M1_PLAN_CONTEXT_DEGRADED",
        ),
        (
            _LegacyProductBoundaryError(
                "legacy.product.unavailable", "legacy unavailable", retryable=True
            ),
            ProductPlanningRuntimeError,
            "2026-11-20T01:00:05Z",
            "ae.product_coordinator.retryable",
            "legacy.product.unavailable",
        ),
        (
            _LegacyProductBoundaryError("unsafe error code!", "unsafe"),
            _LegacyProductBoundaryError,
            None,
            None,
            "ae.product_coordinator_assignment_failed",
        ),
        (
            ValueError("invalid Product state"),
            ValueError,
            None,
            None,
            "ae.product_coordinator_assignment_failed",
        ),
    ),
)
def test_product_assignment_settles_failure_with_bounded_retry_policy(
    error, raised_type, retry_at, retry_ref, error_ref
) -> None:
    registry, registration, coordinator, _activation, runtime = _runtime()
    coordinator.resume_approval = lambda **_values: (_ for _ in ()).throw(error)
    runtime_jobs = _RuntimeJobs()
    handler = InstalledProductCoordinatorAssignmentHandler(
        route_source=_RouteSource(_route(registration)),
        lineage_source=_LineageSource(_inputs(registration)),
        runtimes=InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
        runtime_jobs=runtime_jobs,
        clock=lambda: datetime(2026, 11, 20, 1, 0, tzinfo=UTC),
    )

    with pytest.raises(raised_type, match=str(error)):
        handler(_assignment())

    assert runtime_jobs.complete_calls == []
    assert runtime_jobs.fail_calls == [
        {
            "tenant_id": TENANT,
            "runtime_job_id": "runtime-job-product",
            "worker_id": "worker-1",
            "lease_token": "lease-1",
            "now": "2026-11-20T01:00:00Z",
            "error_ref": error_ref,
            "retry_at": retry_at,
            "retry_disposition_ref": retry_ref,
            "max_attempts": 3,
        }
    ]


def test_product_assignment_preserves_stale_lease_completion_fencing() -> None:
    registry, registration, _coordinator, _activation, runtime = _runtime()
    stale = RuntimeJobError(
        "ae.runtime_job_stale_lease",
        "RuntimeJob completion requires its current unexpired worker lease.",
        True,
    )
    runtime_jobs = _RuntimeJobs(complete_error=stale)
    handler = InstalledProductCoordinatorAssignmentHandler(
        route_source=_RouteSource(_route(registration)),
        lineage_source=_LineageSource(_inputs(registration)),
        runtimes=InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
        runtime_jobs=runtime_jobs,
        clock=lambda: datetime(2026, 11, 20, 1, 0, tzinfo=UTC),
    )

    with pytest.raises(RuntimeJobError) as captured:
        handler(_assignment())

    assert captured.value.error_code == "ae.runtime_job_stale_lease"
    assert len(runtime_jobs.complete_calls) == 1
    assert runtime_jobs.fail_calls == []


@pytest.mark.parametrize(
    "runtime_jobs",
    (
        SimpleNamespace(fail=lambda **_values: None),
        SimpleNamespace(complete=lambda **_values: None),
    ),
)
def test_product_assignment_requires_complete_runtime_job_settlement_authority(
    runtime_jobs,
) -> None:
    registry, registration, _coordinator, _activation, runtime = _runtime()

    with pytest.raises(ProductPlanningRuntimeError, match="authority is unavailable"):
        InstalledProductCoordinatorAssignmentHandler(
            route_source=_RouteSource(_route(registration)),
            lineage_source=_LineageSource(_inputs(registration)),
            runtimes=InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
            runtime_jobs=runtime_jobs,
        )


def test_product_assignment_rejects_naive_settlement_clock() -> None:
    registry, registration, _coordinator, _activation, runtime = _runtime()
    runtime_jobs = _RuntimeJobs()
    handler = InstalledProductCoordinatorAssignmentHandler(
        route_source=_RouteSource(_route(registration)),
        lineage_source=_LineageSource(_inputs(registration)),
        runtimes=InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
        runtime_jobs=runtime_jobs,
        clock=lambda: datetime(2026, 11, 20, 1, 0),  # noqa: DTZ001
    )

    with pytest.raises(ProductPlanningRuntimeError, match="timezone-aware"):
        handler(_assignment())

    assert runtime_jobs.complete_calls == []
    assert runtime_jobs.fail_calls == []


def test_product_assignment_settles_actual_runtime_job_and_attempt() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE ae_agent_execution ("
                "tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL, "
                "PRIMARY KEY (tenant_id, agent_execution_id))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ae_runtime_job ("
                "tenant_id TEXT NOT NULL, runtime_job_id TEXT NOT NULL, "
                "job_type TEXT NOT NULL, execution_id TEXT NOT NULL, "
                "executable_step_id TEXT, wait_id TEXT, reconciliation_id TEXT, "
                "result_delivery_id TEXT, publication_reconciliation_id TEXT, "
                "state TEXT NOT NULL, dedup_key TEXT NOT NULL, attempt_no INTEGER NOT NULL, "
                "run_after TEXT NOT NULL, lease_owner TEXT, lease_token TEXT, "
                "lease_until TEXT, payload_json TEXT NOT NULL, correlation_id TEXT NOT NULL, "
                "causation_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
                "PRIMARY KEY (tenant_id, runtime_job_id), UNIQUE (tenant_id, dedup_key))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ae_runtime_job_attempt ("
                "attempt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, "
                "runtime_job_id TEXT NOT NULL, attempt_no INTEGER NOT NULL, "
                "worker_id TEXT NOT NULL, lease_token TEXT NOT NULL, "
                "started_at TEXT NOT NULL, ended_at TEXT, outcome TEXT NOT NULL, "
                "error_ref TEXT, retry_disposition_ref TEXT, "
                "UNIQUE (tenant_id, runtime_job_id, attempt_no))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ae_agent_execution (tenant_id, agent_execution_id) "
                "VALUES (:tenant_id, :execution_id)"
            ),
            {"tenant_id": TENANT, "execution_id": EXECUTION_ID},
        )
    jobs = SqlAlchemyRuntimeJobQueue(sessionmaker(engine))
    jobs.enqueue_unique(
        tenant_id=TENANT,
        runtime_job_id="runtime-job-product",
        job_type="RESUME_EXECUTION",
        execution_id=EXECUTION_ID,
        wait_id="wait-product",
        resume_target_kind="PRODUCT_COORDINATOR",
        dedup_key="product-resume:settlement",
        run_after="2026-11-20T01:00:00Z",
        payload={},
        correlation_id=EXECUTION_ID,
        now="2026-11-20T01:00:00Z",
    )
    claim = jobs.claim(
        tenant_id=TENANT,
        worker_id="worker-1",
        lease_seconds=600,
        now="2026-11-20T01:00:00Z",
    )
    assert claim is not None
    assignment = replace(
        _assignment(),
        claim=replace(claim, assignment_kind="PRODUCT_COORDINATOR"),
    )
    registry, registration, _coordinator, _activation, runtime = _runtime()
    handler = InstalledProductCoordinatorAssignmentHandler(
        route_source=_RouteSource(_route(registration)),
        lineage_source=_LineageSource(_inputs(registration)),
        runtimes=InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
        runtime_jobs=jobs,
        clock=lambda: datetime(2026, 11, 20, 1, 1, tzinfo=UTC),
    )

    result = handler(assignment)

    assert result["runtime_job_state"] == "DONE"
    assert jobs.get(TENANT, "runtime-job-product")["state"] == "DONE"
    assert jobs.list_attempts(TENANT, "runtime-job-product")[0]["outcome"] == "DONE"


def test_product_event_admission_persists_then_schedules_generalized_resume() -> None:
    registry, registration, coordinator, _activation, runtime = _runtime()
    resume = _ResumeService()
    admission = InstalledProductPlanningEventAdmission(
        runtimes=InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
        resume_service=resume,
    )

    result = admission.ingest(
        {
            "tenant_id": TENANT,
            "coordinator_id": registration.coordinator_id,
            "coordinator_version": registration.coordinator_version,
            "coordinator_registration_hash": registration.registration_hash,
            "checkpoint_id": CHECKPOINT_ID,
            "event_id": "approval-event",
            "notification_ref": "eos-event://approval-event",
            "authority_evidence_ref": "eos-evidence://approval-event",
            "received_at": "2026-11-18T01:00:00Z",
        }
    )

    assert result["event_state"] == "MATCHED"
    assert result["wait_state"] == "RESUME_QUEUED"
    assert len(coordinator.event_calls) == 1
    assert resume.calls == [{"tenant_id": TENANT, "event_id": "approval-event"}]


def test_product_event_admission_rejects_unknown_authority_state() -> None:
    registry, registration, coordinator, _activation, runtime = _runtime()
    admission = InstalledProductPlanningEventAdmission(
        runtimes=InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
        resume_service=_ResumeService(),
    )

    with pytest.raises(ProductPlanningRuntimeError, match="authority state is invalid"):
        admission.ingest(
            {
                "tenant_id": TENANT,
                "coordinator_id": registration.coordinator_id,
                "coordinator_version": registration.coordinator_version,
                "coordinator_registration_hash": registration.registration_hash,
                "checkpoint_id": CHECKPOINT_ID,
                "event_id": "approval-event",
                "notification_ref": "eos-event://approval-event",
                "authority_evidence_ref": "eos-evidence://approval-event",
                "authority_state": "PENDING",
                "received_at": "2026-11-18T01:00:00Z",
            }
        )

    assert coordinator.event_calls == []


def test_one_factory_installs_same_product_handler_in_generic_worker() -> None:
    registry, _registration, _coordinator, _activation, runtime = _runtime()
    sessions = sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))
    product = build_installed_product_planning_composition(
        sessions=sessions,
        coordinator_registry=registry,
        runtimes=(runtime,),
    )
    executor_registry = P5StepExecutorRegistry(
        {"DETERMINISTIC_REPORT": _StepExecutor()}
    )
    installed = build_installed_runtime_composition(
        sessions=sessions,
        heartbeat_emitter=SimpleNamespace(store=object()),
        worker_id="worker-product-router",
        environ={},
        executor_profile=RuntimeExecutorProfile(
            registry=executor_registry,
            executor_backends={"DETERMINISTIC_REPORT": "NSL_V02_IN_PROCESS"},
        ),
        product_planning=product,
        declared_at="2026-11-18T00:00:00Z",
    )

    assert installed.product_planning is product
    assert installed.assignment_handlers.registered_kinds == (
        "EXECUTABLE_STEP",
        "PRODUCT_COORDINATOR",
    )
    assert installed.dispatcher.assignment_kinds == (
        "EXECUTABLE_STEP",
        "PRODUCT_COORDINATOR",
    )


def test_m1_runtime_builder_reuses_existing_plan_and_runtime_stores() -> None:
    registry = _registry(active=True)
    registration = registry.registrations[0]
    preparation_registration = load_m1_transaction_preparation_registration()
    sessions = sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))
    runtime = build_installed_m1_product_coordinator_runtime(
        sessions=sessions,
        registration=registration,
        transaction_preparation=SimpleNamespace(
            adapter=SimpleNamespace(registration=preparation_registration)
        ),
        authority_source=SimpleNamespace(resolve=lambda **_values: None),
        materializer=SimpleNamespace(
            materialize_transaction_plan=lambda **_values: None
        ),
    )

    assert runtime.registration is registration
    assert runtime.coordinator.registration is registration
    assert runtime.activation.registration is registration


def test_runtime_registry_rejects_missing_or_contract_only_implementation() -> None:
    active = _registry(active=True)
    with pytest.raises(ProductPlanningRuntimeError):
        InstalledProductCoordinatorRuntimeRegistry(active)

    contract = _registry(active=False)
    registration = contract.registrations[0]
    with pytest.raises(ProductPlanningRuntimeError):
        InstalledProductCoordinatorRuntimeRegistry(
            contract,
            (
                InstalledProductCoordinatorRuntime(
                    registration=registration,
                    coordinator=_Coordinator(registration),
                    activation=_Activation(registration),
                ),
            ),
        )


def test_runtime_registry_rejects_invalid_duplicate_and_drifted_runtime() -> None:
    registry, registration, coordinator, activation, runtime = _runtime()
    with pytest.raises(ProductPlanningRuntimeError, match="dependencies differ"):
        InstalledProductCoordinatorRuntime(
            registration=registration,
            coordinator=SimpleNamespace(registration=registration),
            activation=activation,
        )
    with pytest.raises(ProductPlanningRuntimeError, match="duplicated"):
        InstalledProductCoordinatorRuntimeRegistry(registry, (runtime, runtime))

    runtimes = InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,))
    assert runtimes.identities == (runtime.identity,)
    with pytest.raises(ProductPlanningRuntimeError, match="not installed"):
        runtimes.resolve_registration(
            replace(registration, activation_status="CONTRACT_ONLY")
        )
    with pytest.raises(ProductPlanningRuntimeError, match="has drifted"):
        runtimes.resolve_identity(
            coordinator_id=registration.coordinator_id,
            coordinator_version=registration.coordinator_version,
            coordinator_registration_hash="sha256:" + "0" * 64,
        )
    with pytest.raises(ProductPlanningRuntimeError, match="not installed"):
        runtimes.resolve_identity(
            coordinator_id="missing",
            coordinator_version="v1",
            coordinator_registration_hash=registration.registration_hash,
        )
    with pytest.raises(ProductPlanningRuntimeError, match="not a Product"):
        runtimes.resolve_route(replace(_route(registration), product_context=None))

    missing = _route(registration)
    missing.product_context["coordinator_id"] = "missing"
    with pytest.raises(ProductPlanningRuntimeError, match="not installed"):
        runtimes.resolve_route(missing)

    drifted = _route(registration)
    drifted.product_context["coordinator_registration_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ProductPlanningRuntimeError, match="resume registration"):
        runtimes.resolve_route(drifted)

    assert str(ProductPlanningRuntimeError("code", "detail")) == "detail"
    assert coordinator.registration is registration


def test_router_and_handler_reject_invalid_product_shapes() -> None:
    registry, registration, coordinator, _activation, runtime = _runtime()
    runtimes = InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,))
    router = PublicProductPlanningRouter(registry, runtimes)

    invalid = _inputs(registration)
    invalid["work_intent"] = {"required_capability_hints": "not-a-list"}
    with pytest.raises(ProductPlanningRuntimeError, match="inputs are invalid"):
        router.begin_if_registered(**invalid)

    coordinator.begin = lambda **_values: {"checkpoint": "invalid"}
    with pytest.raises(ProductPlanningRuntimeError, match="checkpoint is unavailable"):
        router.begin_if_registered(**_inputs(registration))

    coordinator.begin = lambda **_values: (_ for _ in ()).throw(
        ProductPlanningRuntimeError("owner.invalid", "owner invalid")
    )
    with pytest.raises(ProductPlanningRuntimeError, match="owner invalid"):
        router.begin_if_registered(**_inputs(registration))

    coordinator.begin = lambda **_values: (_ for _ in ()).throw(
        ValueError("unexpected product bug")
    )
    with pytest.raises(ValueError, match="unexpected product bug"):
        router.begin_if_registered(**_inputs(registration))

    with pytest.raises(ProductPlanningRuntimeError, match="coordinator_id is required"):
        runtimes.resolve_identity(
            coordinator_id=" ",
            coordinator_version=registration.coordinator_version,
            coordinator_registration_hash=registration.registration_hash,
        )

    handler = InstalledProductCoordinatorAssignmentHandler(
        route_source=_RouteSource(_route(registration)),
        lineage_source=_LineageSource(_inputs(registration)),
        runtimes=runtimes,
        runtime_jobs=_RuntimeJobs(),
    )
    with pytest.raises(ProductPlanningRuntimeError, match="another assignment kind"):
        handler(replace(_assignment(), assignment_kind="EXECUTABLE_STEP"))


def test_router_rejects_multiple_registered_capabilities_without_scenario_choice() -> (
    None
):
    _registry_value, registration, *_ = _runtime()
    second_binding = replace(
        registration.trigger_capability,
        capability_id="FINANCE.PROJECT_PNL.GET",
    )
    second = replace(
        registration,
        coordinator_id="nex-ae:another-product-coordinator",
        coordinator_version="v1",
        trigger_capability=second_binding,
    )
    by_capability = {
        registration.capability_id: registration,
        second.capability_id: second,
    }
    fake_registry = SimpleNamespace(
        resolve=lambda capability_id, _version, required=False: by_capability.get(
            capability_id
        )
    )
    router = PublicProductPlanningRouter(fake_registry, SimpleNamespace())
    inputs = _inputs(registration)
    inputs["work_intent"]["required_capability_hints"] = [
        registration.capability_id,
        registration.capability_id,
        second.capability_id,
    ]
    inputs["capability_snapshot"]["capabilities"].append(
        {
            "capability_id": second.capability_id,
            "capability_version": second.capability_version,
        }
    )

    with pytest.raises(ProductPlanningRuntimeError, match="multiple Product"):
        router.begin_if_registered(**inputs)


def test_lineage_source_validates_missing_incomplete_and_drifted_authority() -> None:
    _registry_value, registration, *_ = _runtime()
    route = _route(registration)

    source = SqlAlchemyProductPlanningLineageSource.__new__(
        SqlAlchemyProductPlanningLineageSource
    )
    source._checkpoints = _StoredRepository(None)
    with pytest.raises(ProductPlanningRuntimeError, match="not found"):
        source.load(route)

    checkpoint = {
        "checkpoint_hash": CHECKPOINT_HASH,
        "agent_execution_id": EXECUTION_ID,
        "work_intent_id": WORK_INTENT_ID,
        "agent_context_id": "context-1",
        "work_intent_hash": "sha256:" + "1" * 64,
        "context_hash": "sha256:" + "2" * 64,
    }
    source._checkpoints = _StoredRepository({**checkpoint, "checkpoint_hash": "bad"})
    with pytest.raises(ProductPlanningRuntimeError, match="lineage differs"):
        source.load(route)

    source._checkpoints = _StoredRepository(checkpoint)
    source._work_intents = _StoredRepository(None)
    source._contexts = _StoredRepository({"context_hash": checkpoint["context_hash"]})
    source._capabilities = _StoredRepository({"tenant_id": TENANT})
    source._executions = _StoredRepository({"agent_execution_id": EXECUTION_ID})
    with pytest.raises(ProductPlanningRuntimeError, match="lineage is incomplete"):
        source.load(route)

    source._work_intents = _StoredRepository({"intent_hash": "bad"})
    with pytest.raises(ProductPlanningRuntimeError, match="authority has drifted"):
        source.load(route)

    source._work_intents = _StoredRepository(
        {"intent_hash": checkpoint["work_intent_hash"]}
    )
    loaded = source.load(route)
    assert loaded["execution"]["execution_id"] == EXECUTION_ID

    with pytest.raises(ProductPlanningRuntimeError, match="binding is unavailable"):
        source.load(replace(route, product_context=None))


def test_event_admission_rejects_malformed_payload_and_preserves_typed_error() -> None:
    registry, registration, coordinator, _activation, runtime = _runtime()
    admission = InstalledProductPlanningEventAdmission(
        runtimes=InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
        resume_service=_ResumeService(),
    )
    with pytest.raises(ProductPlanningRuntimeError, match="fields are invalid"):
        admission.ingest({"tenant_id": TENANT})

    class _TypedFailure(Exception):
        error_code = "owner.conflict"
        detail = "owner rejected the event"
        retryable = True

    coordinator.accept_approval_notification = lambda **_values: (_ for _ in ()).throw(
        _TypedFailure()
    )
    payload = {
        "tenant_id": TENANT,
        "coordinator_id": registration.coordinator_id,
        "coordinator_version": registration.coordinator_version,
        "coordinator_registration_hash": registration.registration_hash,
        "checkpoint_id": CHECKPOINT_ID,
        "event_id": "approval-event",
        "notification_ref": "eos-event://approval-event",
        "authority_evidence_ref": "eos-evidence://approval-event",
        "received_at": "2026-11-18T01:00:00Z",
    }
    with pytest.raises(ProductPlanningRuntimeError) as captured:
        admission.ingest(payload)
    assert captured.value.error_code == "owner.conflict"
    assert captured.value.retryable is True


def test_product_planning_event_api_protects_unavailable_and_error_paths(
    monkeypatch,
) -> None:
    from nex_ae_api import product_planning_event_api as api

    monkeypatch.setattr(
        api,
        "authorize_ae_internal_service_request",
        lambda *_args, **_values: SimpleNamespace(service_id="nex-eos"),
    )
    app = FastAPI()
    register_product_planning_event_routes(app, admission=None)
    unavailable = TestClient(app).post("/internal/v1/product-planning-events", json={})
    assert unavailable.status_code == 503

    failed_app = FastAPI()
    register_product_planning_event_routes(
        failed_app,
        admission=_FailingAdmission(
            ProductPlanningRuntimeError("owner.conflict", "conflict", False)
        ),
    )
    failed = TestClient(failed_app).post(
        "/internal/v1/product-planning-events", json={}
    )
    assert failed.status_code == 409
    assert failed.json()["error_code"] == "owner.conflict"

    retrying_app = FastAPI()
    register_product_planning_event_routes(
        retrying_app,
        admission=_FailingAdmission(
            ProductPlanningRuntimeError("owner.unavailable", "retry", True)
        ),
    )
    retrying = TestClient(retrying_app).post(
        "/internal/v1/product-planning-events", json={}
    )
    assert retrying.status_code == 503

    success_app = FastAPI()
    register_product_planning_event_routes(
        success_app,
        admission=SimpleNamespace(ingest=lambda _payload: {"accepted": True}),
    )
    success = TestClient(success_app).post(
        "/internal/v1/product-planning-events", json={}
    )
    assert success.status_code == 202
    assert success.json() == {"accepted": True}

    denied_app = FastAPI()
    monkeypatch.setattr(
        api,
        "authorize_ae_internal_service_request",
        lambda *_args, **_values: JSONResponse({"denied": True}, status_code=403),
    )
    register_product_planning_event_routes(denied_app, admission=None)
    denied = TestClient(denied_app).post(
        "/internal/v1/product-planning-events", json={}
    )
    assert denied.status_code == 403


def test_contract_factory_exposes_router_without_active_worker() -> None:
    capabilities = load_product_capability_registry(
        {
            "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
                ROOT
                / "deployment/environments/ae-product-capability-registry.mybee-m1.v4.json"
            )
        }
    )
    sessions = sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))
    composition = build_contract_m1_product_planning_composition(
        sessions=sessions,
        product_capabilities=capabilities,
    )

    assert composition.public_router is not None
    assert composition.runtime_registry.identities == ()
    assert composition.assignment_handler is None
    assert composition.event_admission is None
