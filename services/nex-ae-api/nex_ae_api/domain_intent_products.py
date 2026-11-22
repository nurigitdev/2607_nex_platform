from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.domain_intent_activators import (
    DomainIntentActivatorRegistration,
    DomainIntentActivatorRegistry,
)
from nex_ae_api.finance_golden_a_activation import (
    GoldenAFinanceIntentActivator,
    load_golden_a_finance_authority_source,
)
from nex_ae_api.golden_a_planning import GOLDEN_A_CAPABILITY_ID
from nex_ae_api.product_capabilities import (
    ProductCapabilityRegistry,
    load_product_capability_registry,
)
from nex_ae_api.product_capability_retirements import (
    ProductCapabilityRetirementProjection,
    load_product_capability_retirement_projection,
)
from nex_ae_api.project_delegation_planning import (
    M1_PROJECT_DELEGATION_CAPABILITY_ID,
    M1_PROJECT_DELEGATION_PROFILE_VERSION,
    build_http_project_delegation_activator,
)


def build_domain_intent_activator_registry(
    environ: Mapping[str, str],
    *,
    product_capability_registry: ProductCapabilityRegistry | None = None,
    retirement_projection: ProductCapabilityRetirementProjection | None = None,
    include_replay_only: bool = False,
    session_factory: Any | None = None,
) -> DomainIntentActivatorRegistry:
    """Build product activators from separate authority and capability sources."""

    retirements = retirement_projection or (
        load_product_capability_retirement_projection(
            environ,
            required=(
                str(environ.get("NEX_DEPLOYMENT_BOUNDARY") or "").strip()
                == "CANONICAL_PLATFORM"
            ),
        )
    )
    capabilities = product_capability_registry or load_product_capability_registry(
        environ
    )
    registrations: list[DomainIntentActivatorRegistration] = []
    authority_source = load_golden_a_finance_authority_source(environ)
    if authority_source is not None and (
        include_replay_only
        or not retirements.is_new_selection_denied(GOLDEN_A_CAPABILITY_ID)
    ):
        capability = capabilities.resolve(GOLDEN_A_CAPABILITY_ID, required=True)
        assert capability is not None
        registrations.append(
            DomainIntentActivatorRegistration(
                capability_id=GOLDEN_A_CAPABILITY_ID,
                version="finance-golden-a.v1",
                source_identity=(
                    "nex-ae:finance-golden-a:v1:"
                    + semantic_sha256_hash_ref(
                        {
                            "authority": authority_source.source_identity,
                            "capability": capability.source_identity,
                        }
                    )
                ),
                activator=GoldenAFinanceIntentActivator(
                    authority_source,
                    capability.capability,
                ),
            )
        )
    if session_factory is not None:
        delegation_activator = build_http_project_delegation_activator(
            environ, session_factory=session_factory
        )
        if delegation_activator is not None:
            capability = capabilities.resolve(
                M1_PROJECT_DELEGATION_CAPABILITY_ID, required=True
            )
            assert capability is not None
            registrations.append(
                DomainIntentActivatorRegistration(
                    capability_id=M1_PROJECT_DELEGATION_CAPABILITY_ID,
                    version=M1_PROJECT_DELEGATION_PROFILE_VERSION,
                    source_identity=(
                        delegation_activator.profile.source_identity
                        + ":"
                        + capability.source_identity
                    ),
                    activator=delegation_activator,
                )
            )
    return DomainIntentActivatorRegistry.from_registrations(registrations)
