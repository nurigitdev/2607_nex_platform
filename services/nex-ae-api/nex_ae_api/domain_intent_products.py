from __future__ import annotations

from collections.abc import Mapping

from nex_ae_api.domain_intent_activators import (
    DomainIntentActivatorRegistration,
    DomainIntentActivatorRegistry,
)
from nex_ae_api.finance_golden_a_activation import (
    GoldenAFinanceIntentActivator,
    load_golden_a_finance_authority_source,
)
from nex_ae_api.golden_a_planning import GOLDEN_A_CAPABILITY_ID


def build_domain_intent_activator_registry(
    environ: Mapping[str, str],
) -> DomainIntentActivatorRegistry:
    """Build activators from admitted product authority sources."""

    authority_source = load_golden_a_finance_authority_source(environ)
    if authority_source is None:
        return DomainIntentActivatorRegistry()
    return DomainIntentActivatorRegistry.from_registrations(
        (
            DomainIntentActivatorRegistration(
                capability_id=GOLDEN_A_CAPABILITY_ID,
                version="finance-golden-a.v1",
                source_identity=authority_source.source_identity,
                activator=GoldenAFinanceIntentActivator(authority_source),
            ),
        )
    )
