from __future__ import annotations

from collections.abc import Mapping

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


def build_domain_intent_activator_registry(
    environ: Mapping[str, str],
    *,
    product_capability_registry: ProductCapabilityRegistry | None = None,
) -> DomainIntentActivatorRegistry:
    """Build product activators from separate authority and capability sources."""

    authority_source = load_golden_a_finance_authority_source(environ)
    if authority_source is None:
        return DomainIntentActivatorRegistry()
    capabilities = product_capability_registry or load_product_capability_registry(
        environ
    )
    capability = capabilities.resolve(GOLDEN_A_CAPABILITY_ID, required=True)
    assert capability is not None
    return DomainIntentActivatorRegistry.from_registrations(
        (
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
            ),
        )
    )
