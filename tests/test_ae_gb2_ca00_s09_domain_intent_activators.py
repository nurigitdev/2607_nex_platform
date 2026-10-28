from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from nex_ae_api.domain_intent_activators import (
    DomainIntentActivatorRegistration,
    DomainIntentActivatorRegistry,
    DomainIntentActivatorRegistryError,
)
from nex_ae_api.domain_intent_products import (
    build_domain_intent_activator_registry,
)
from nex_runtime.semantic_hashes import validate_hash_ref

ROOT = Path(__file__).resolve().parents[1]


class _EchoActivator:
    def activate(self, **kwargs):
        return SimpleNamespace(
            work_intent=dict(kwargs["work_intent"]),
            context_resolver={"principal_id": kwargs["principal_id"]},
        )


def _registration(
    capability_id: str, *, version: str = "1.0"
) -> DomainIntentActivatorRegistration:
    return DomainIntentActivatorRegistration(
        capability_id=capability_id,
        version=version,
        source_identity="test:gb2-s09",
        activator=_EchoActivator(),
    )


def test_empty_registry_treats_unknown_optional_activation_as_absent() -> None:
    registry = DomainIntentActivatorRegistry()

    assert registry.resolve("FINANCE.OPTIONAL", required=False) is None
    projection = registry.to_projection()
    assert projection["registrations"] == []
    validate_hash_ref(projection["registry_hash"])


def test_single_registration_resolves_and_replays_deterministically() -> None:
    registry = DomainIntentActivatorRegistry((_registration("FINANCE.CREATE"),))
    registration = registry.resolve("FINANCE.CREATE", required=True)
    assert registration is not None

    first = registration.activator.activate(
        candidate={"intent_label": "FINANCE.CREATE"},
        work_intent={"intent_label": "FINANCE.CREATE"},
        principal_id="employee-1001",
        resolved_at="2026-10-28T00:00:00Z",
    )
    replay = registration.activator.activate(
        candidate={"intent_label": "FINANCE.CREATE"},
        work_intent=first.work_intent,
        principal_id="employee-1001",
        resolved_at="2026-10-28T00:00:00Z",
    )

    assert first.work_intent == replay.work_intent
    assert first.context_resolver == replay.context_resolver
    validate_hash_ref(registration.to_projection()["registration_hash"])


def test_registration_order_does_not_change_projection_or_hash() -> None:
    first = _registration("FINANCE.CREATE", version="2.0")
    second = _registration("MANUFACTURING.READ", version="1.0")

    forward = DomainIntentActivatorRegistry((first, second)).to_projection()
    reverse = DomainIntentActivatorRegistry((second, first)).to_projection()

    assert forward == reverse
    assert [item["capability_id"] for item in forward["registrations"]] == [
        "FINANCE.CREATE",
        "MANUFACTURING.READ",
    ]


def test_duplicate_and_unknown_required_capabilities_fail_closed() -> None:
    duplicate = _registration("FINANCE.CREATE")
    with pytest.raises(DomainIntentActivatorRegistryError) as raised:
        DomainIntentActivatorRegistry((duplicate, duplicate))
    assert raised.value.error_code == "DOMAIN_INTENT_ACTIVATOR_DUPLICATE"
    assert str(raised.value) == "Domain intent capability registration must be unique."

    with pytest.raises(DomainIntentActivatorRegistryError) as raised:
        DomainIntentActivatorRegistry().resolve("FINANCE.CREATE", required=True)
    assert raised.value.error_code == "DOMAIN_INTENT_ACTIVATOR_REQUIRED"


@pytest.mark.parametrize(
    "registration",
    [
        None,
        "invalid",
    ],
)
def test_registry_rejects_non_registration_entries(registration) -> None:
    with pytest.raises(DomainIntentActivatorRegistryError) as raised:
        DomainIntentActivatorRegistry((registration,))  # type: ignore[arg-type]
    assert raised.value.error_code == "DOMAIN_INTENT_ACTIVATOR_REGISTRATION_INVALID"


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"capability_id": ""}, "DOMAIN_INTENT_ACTIVATOR_REGISTRATION_INVALID"),
        (
            {"version": " 1.0"},
            "DOMAIN_INTENT_ACTIVATOR_REGISTRATION_INVALID",
        ),
        (
            {"source_identity": ""},
            "DOMAIN_INTENT_ACTIVATOR_REGISTRATION_INVALID",
        ),
        ({"activator": object()}, "DOMAIN_INTENT_ACTIVATOR_INVALID"),
    ],
)
def test_registration_rejects_noncanonical_metadata(overrides, error_code) -> None:
    values = {
        "capability_id": "FINANCE.CREATE",
        "version": "1.0",
        "source_identity": "test:gb2-s09",
        "activator": _EchoActivator(),
        **overrides,
    }
    with pytest.raises(DomainIntentActivatorRegistryError) as raised:
        DomainIntentActivatorRegistration(**values)
    assert raised.value.error_code == error_code


def test_mapping_builder_and_product_builder_preserve_empty_default() -> None:
    mapped = DomainIntentActivatorRegistry.from_mapping(
        {"FINANCE.CREATE": _EchoActivator()},
        version="1.0",
        source_identity="test:mapping",
    )
    assert mapped.resolve("FINANCE.CREATE", required=True) is not None
    assert build_domain_intent_activator_registry({}).registrations == ()

def test_semantic_admission_depends_only_on_canonical_registry_boundary() -> None:
    source = (
        ROOT / "services/nex-ae-api/nex_ae_api/semantic_candidate_admission.py"
    ).read_text(encoding="utf-8")

    assert "DomainIntentActivatorRegistry" in source
    assert "p8_demo_semantic_activation" not in source
