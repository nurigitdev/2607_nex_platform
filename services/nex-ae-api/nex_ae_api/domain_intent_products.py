from __future__ import annotations

from collections.abc import Mapping

from nex_ae_api.domain_intent_activators import DomainIntentActivatorRegistry


def build_domain_intent_activator_registry(
    environ: Mapping[str, str],
) -> DomainIntentActivatorRegistry:
    """Build the installed product registry.

    Golden A remains behind its explicit P8 Demo environment switch until S10
    promotes its authoritative bindings out of fixture-backed compatibility.
    """

    from nex_ae_api.p8_demo_semantic_activation import (
        build_p8_demo_intent_activators,
    )

    return DomainIntentActivatorRegistry.from_mapping(
        build_p8_demo_intent_activators(environ),
        version="p8-demo-golden-a.v1",
        source_identity="nex-ae:p8-demo-semantic-activation",
    )
