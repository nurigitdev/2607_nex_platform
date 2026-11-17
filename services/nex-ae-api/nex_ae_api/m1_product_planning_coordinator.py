from __future__ import annotations

from mybee_ax.integrations import M1_D04_CAPABILITY_ID, M1_D12_CAPABILITY_ID
from mybee_ax.orchestration import M1PreparationRegistration

from nex_ae_api.product_capabilities import ProductCapabilityRegistry
from nex_ae_api.product_planning_coordinators import (
    ProductPlanningCoordinatorError,
    ProductPlanningCoordinatorRegistration,
    ProductPlanningCoordinatorRegistry,
    build_product_planning_coordinator_registration,
    capability_binding,
)

M1_PRODUCT_COORDINATOR_ID = "MYBEE.M1.TRANSACTION_PREPARATION"
M1_PRODUCT_COORDINATOR_VERSION = "1.0.0"
M1_PRODUCT_COORDINATOR_REGISTRY_ID = "ae-product-coordinators-mybee-m1"
M1_PRODUCT_COORDINATOR_IMPLEMENTATION_REF = (
    "nex_ae_api.m1_product_planning_coordinator:"
    "InstalledM1ProductPlanningCoordinator"
)
M1_PLAN_MATERIALIZER_SOURCE_IDENTITY = (
    "nex-ae:m1-plan-materializer:ae.m1_plan_materialization.v1"
)


def build_m1_product_planning_coordinator_registration(
    *,
    product_capabilities: ProductCapabilityRegistry,
    preparation_registration: M1PreparationRegistration,
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
        activation_status="CONTRACT_ONLY",
        implementation_ref=M1_PRODUCT_COORDINATOR_IMPLEMENTATION_REF,
        trigger_capability=capability_binding(d04),
        required_capabilities=(capability_binding(d04), capability_binding(d12)),
        preparation_adapter_source_identity=preparation_registration.source_identity,
        materializer_source_identity=M1_PLAN_MATERIALIZER_SOURCE_IDENTITY,
        initial_state="PREPARATION_PENDING",
        waiting_states=(
            "WAITING_BUSINESS_APPROVAL",
            "WAITING_ACCOUNTING_APPROVAL",
        ),
        ready_state="READY_FOR_D04",
        terminal_states=("PREPARATION_FAILED", "PREPARATION_CANCELLED"),
        required_operations=operations,
    )


def build_m1_product_planning_coordinator_registry(
    *,
    product_capabilities: ProductCapabilityRegistry,
    preparation_registration: M1PreparationRegistration,
) -> ProductPlanningCoordinatorRegistry:
    registration = build_m1_product_planning_coordinator_registration(
        product_capabilities=product_capabilities,
        preparation_registration=preparation_registration,
    )
    registry = ProductPlanningCoordinatorRegistry(
        (registration,),
        registry_id=M1_PRODUCT_COORDINATOR_REGISTRY_ID,
        registry_version=1,
    )
    registry.require_product_capabilities(product_capabilities)
    return registry
