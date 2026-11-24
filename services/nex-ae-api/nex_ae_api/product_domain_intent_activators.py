from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_ae_api.accounting_allocation_authority import (
    ACCOUNTING_ALLOCATION_OPERATION,
)
from nex_ae_api.accounting_allocation_intent_activation import (
    ACCOUNTING_ALLOCATION_INTENT_PROFILE_VERSION,
    AccountingAllocationIntentActivator,
)
from nex_ae_api.domain_intent_activators import (
    DomainIntentActivatorRegistration,
    DomainIntentActivatorRegistry,
)
from nex_ae_api.product_capabilities import ProductCapabilityRegistry
from nex_ae_api.product_capability_retirements import (
    ProductCapabilityRetirementProjection,
)
from nex_ae_api.project_delegation_planning import (
    M1_PROJECT_DELEGATION_CAPABILITY_ID,
    M1_PROJECT_DELEGATION_PROFILE_VERSION,
    build_http_project_delegation_activator,
)


def build_active_product_domain_intent_activator_registry(
    environ: Mapping[str, str],
    *,
    product_capability_registry: ProductCapabilityRegistry,
    retirement_projection: ProductCapabilityRetirementProjection,
    session_factory: Any,
) -> DomainIntentActivatorRegistry:
    """Build only selectable product activators for the installed runtime."""

    registrations: list[DomainIntentActivatorRegistration] = []
    if not retirement_projection.is_new_selection_denied(
        M1_PROJECT_DELEGATION_CAPABILITY_ID
    ):
        activator = build_http_project_delegation_activator(
            environ,
            session_factory=session_factory,
        )
        if activator is not None:
            capability = product_capability_registry.resolve(
                M1_PROJECT_DELEGATION_CAPABILITY_ID,
                required=True,
            )
            assert capability is not None
            registrations.append(
                DomainIntentActivatorRegistration(
                    capability_id=M1_PROJECT_DELEGATION_CAPABILITY_ID,
                    version=M1_PROJECT_DELEGATION_PROFILE_VERSION,
                    source_identity=(
                        activator.profile.source_identity
                        + ":"
                        + capability.source_identity
                    ),
                    activator=activator,
                )
            )
    allocation_capability = None
    if not retirement_projection.is_new_selection_denied(
        ACCOUNTING_ALLOCATION_OPERATION
    ):
        allocation_capability = product_capability_registry.resolve(
            ACCOUNTING_ALLOCATION_OPERATION,
            required=False,
        )
    if allocation_capability is not None:
        allocation_activator = AccountingAllocationIntentActivator()
        registrations.append(
            DomainIntentActivatorRegistration(
                capability_id=ACCOUNTING_ALLOCATION_OPERATION,
                version=ACCOUNTING_ALLOCATION_INTENT_PROFILE_VERSION,
                source_identity=(
                    allocation_activator.profile.source_identity
                    + ":"
                    + allocation_capability.source_identity
                ),
                activator=allocation_activator,
            )
        )
    return DomainIntentActivatorRegistry.from_registrations(registrations)


__all__ = ["build_active_product_domain_intent_activator_registry"]
