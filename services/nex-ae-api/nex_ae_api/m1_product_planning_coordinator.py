from __future__ import annotations

from mybee_ax.integrations import M1_D04_CAPABILITY_ID, M1_D12_CAPABILITY_ID
from mybee_ax.orchestration import M1PreparationRegistration

from nex_ae_api.planning_capabilities import LOCAL_SKILL_EXECUTOR_KIND
from nex_ae_api.product_capabilities import ProductCapabilityRegistry
from nex_ae_api.product_planning_coordinators import (
    ProductPlanningCoordinatorError,
    ProductPlanningCoordinatorRegistration,
    ProductPlanningCoordinatorRegistry,
    ProductPlanningPolicy,
    ProductPlanningReplayPolicy,
    build_product_planning_coordinator_registration,
    capability_binding,
    skill_bundle_lock,
)
from nex_ae_api.product_preparation_persistence import (
    PRODUCT_PREPARATION_CHECKPOINT_SCHEMA_VERSION,
)
from nex_ae_api.prompts import AE_PROJECT_DELEGATION_PLAN_BUILDER_BINDING

M1_PRODUCT_COORDINATOR_ID = "MYBEE.M1.TRANSACTION_PREPARATION"
M1_PRODUCT_COORDINATOR_VERSION = "1.3.0"
M1_PRODUCT_COORDINATOR_REGISTRY_ID = "ae-product-coordinators-mybee-m1"
M1_PRODUCT_COORDINATOR_IMPLEMENTATION_REF = "nex_ae_api.m1_product_preparation_coordinator:InstalledM1ProductPlanningCoordinator"
M1_PLAN_MATERIALIZER_SOURCE_IDENTITY = (
    "nex-ae:m1-plan-materializer:ae.m1_plan_materialization.v1"
)
M1_PRODUCT_COORDINATOR_REPLAY_POLICY = ProductPlanningReplayPolicy(
    policy_id="ae.product_preparation_resume.exact.v1",
    exact_event_replay="RETURN_ORIGINAL_RESUME",
    semantic_drift="FAIL_CLOSED_ZERO_MUTATION",
    stale_or_out_of_order="DENY",
    ack_loss_redelivery="CONVERGE",
)
M1_PRODUCT_PLANNING_POLICY = ProductPlanningPolicy(
    mode="PROVIDER_ASSISTED_REQUIRED",
    proposal_schema_version="ae.product_planning_proposal.v1",
    prompt_binding_key=AE_PROJECT_DELEGATION_PLAN_BUILDER_BINDING,
    admission_policy_ref="ae.product_planning_proposal.strict.v1",
    deterministic_fallback_ref=None,
    proposal_consumers=("MATERIALIZER", "PREPARATION"),
)


def build_m1_product_planning_coordinator_registration(
    *,
    product_capabilities: ProductCapabilityRegistry,
    preparation_registration: M1PreparationRegistration,
    activation_status: str = "CONTRACT_ONLY",
    planning_policy: ProductPlanningPolicy = M1_PRODUCT_PLANNING_POLICY,
) -> ProductPlanningCoordinatorRegistration:
    d04 = product_capabilities.resolve(M1_D04_CAPABILITY_ID, required=True)
    d12 = product_capabilities.resolve(M1_D12_CAPABILITY_ID, required=True)
    if (
        d04 is None
        or d12 is None
        or d04.capability.get("operation_semantics") != "WRITE"
        or d12.capability.get("operation_semantics") != "READ"
        or d04.capability.get("status") != "ACTIVE"
        or d12.capability.get("status") != "ACTIVE"
    ):
        raise ProductPlanningCoordinatorError(
            "PRODUCT_COORDINATOR_CAPABILITY_INVALID",
            "M1 product coordinator capabilities are not active READ/WRITE bindings.",
        )
    operations = tuple(preparation_registration.operations)
    if not operations:
        raise ProductPlanningCoordinatorError(
            "PRODUCT_COORDINATOR_PREPARATION_INVALID",
            "M1 preparation operations are unavailable.",
        )
    return build_product_planning_coordinator_registration(
        coordinator_id=M1_PRODUCT_COORDINATOR_ID,
        coordinator_version=M1_PRODUCT_COORDINATOR_VERSION,
        activation_status=activation_status,
        implementation_ref=M1_PRODUCT_COORDINATOR_IMPLEMENTATION_REF,
        trigger_capability=capability_binding(d04),
        required_capabilities=(capability_binding(d04), capability_binding(d12)),
        preparation_adapter_source_identity=preparation_registration.source_identity,
        materializer_source_identity=M1_PLAN_MATERIALIZER_SOURCE_IDENTITY,
        initial_state="PREPARATION_PENDING",
        waiting_states=(
            "WAITING_PROPOSAL_REVIEW",
            "WAITING_BUSINESS_APPROVAL",
            "WAITING_VOUCHER_REVIEW",
            "WAITING_ACCOUNTING_APPROVAL",
        ),
        ready_state="READY_FOR_D04",
        terminal_states=("PREPARATION_FAILED", "PREPARATION_CANCELLED"),
        required_operations=operations,
        checkpoint_schema_version=(PRODUCT_PREPARATION_CHECKPOINT_SCHEMA_VERSION),
        replay_policy=M1_PRODUCT_COORDINATOR_REPLAY_POLICY,
        planning_policy=planning_policy,
        supported_executor_kinds=(LOCAL_SKILL_EXECUTOR_KIND,),
        installed_skill_bundle_locks=(
            skill_bundle_lock(d04),
            skill_bundle_lock(d12),
        ),
    )


def build_m1_product_planning_coordinator_registry(
    *,
    product_capabilities: ProductCapabilityRegistry,
    preparation_registration: M1PreparationRegistration,
    activation_status: str = "CONTRACT_ONLY",
    planning_policy: ProductPlanningPolicy = M1_PRODUCT_PLANNING_POLICY,
) -> ProductPlanningCoordinatorRegistry:
    registration = build_m1_product_planning_coordinator_registration(
        product_capabilities=product_capabilities,
        preparation_registration=preparation_registration,
        activation_status=activation_status,
        planning_policy=planning_policy,
    )
    registry = ProductPlanningCoordinatorRegistry(
        (registration,),
        registry_id=M1_PRODUCT_COORDINATOR_REGISTRY_ID,
        registry_version=5,
    )
    registry.require_product_capabilities(product_capabilities)
    return registry
