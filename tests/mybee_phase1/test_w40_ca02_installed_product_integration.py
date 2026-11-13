from __future__ import annotations

from pathlib import Path

import pytest
from nex_ae_api.domain_intent_activators import DomainIntentActivatorRegistry
from nex_ae_api.golden_a_planning import GOLDEN_A_CAPABILITY_ID
from nex_ae_api.mybee_product_consumer import (
    MYBEE_CONSUMER_OPERATIONS,
    InstalledMyBeeVoucherCandidateConsumer,
    MyBeeProductConsumerError,
    _base_url,
    _timeout,
    build_installed_mybee_voucher_candidate_consumer,
    mybee_consumer_binding_ready,
    not_required_mybee_consumer_binding,
)
from nex_ae_api.product_capabilities import ProductCapabilityRegistry

ROOT = Path(__file__).resolve().parents[2]
CAPABILITY_REGISTRY = (
    ROOT / "deployment/environments/ae-product-capability-registry.v1.json"
)
AUTHORITY_PROFILE = ROOT / "deployment/environments/finance-golden-a-vo00.v1.json"


def _environment(**overrides: str) -> dict[str, str]:
    value = {
        "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(CAPABILITY_REGISTRY),
        "NEX_AE_FINANCE_GOLDEN_A_AUTHORITY_PROFILE_PATH": str(AUTHORITY_PROFILE),
        "NEX_EOS_BASE_URL": "https://eos.example",
        "NEX_AE_TO_EOS_SERVICE_TOKEN": "signed-ae-to-eos-token",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
        "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS": "17.5",
    }
    value.update(overrides)
    return value


def test_installed_binding_reuses_admitted_capability_activator_and_http_client() -> (
    None
):
    binding = build_installed_mybee_voucher_candidate_consumer(_environment())

    assert isinstance(binding, InstalledMyBeeVoucherCandidateConsumer)
    assert binding.client.__class__.__name__ == "NexVoucherCandidateClient"
    readiness = binding.readiness()
    assert readiness["status"] == "PASS"
    assert readiness["upstream_capability_id"] == GOLDEN_A_CAPABILITY_ID
    assert readiness["operations"] == list(MYBEE_CONSUMER_OPERATIONS)
    assert readiness["provider_service_id"] == "nex-eos"
    assert readiness["package_version"] == "0.1.0"
    assert readiness["timeout_seconds"] == 17.5
    assert readiness["binding_hash"].startswith("sha256:")
    assert readiness["secret_included"] is False
    assert "signed-ae-to-eos-token" not in repr(binding)
    assert "signed-ae-to-eos-token" not in str(readiness)


def test_installed_binding_fails_closed_without_capability_or_activator() -> None:
    with pytest.raises(MyBeeProductConsumerError, match="unavailable"):
        build_installed_mybee_voucher_candidate_consumer(
            _environment(),
            product_capability_registry=ProductCapabilityRegistry(),
        )

    with pytest.raises(MyBeeProductConsumerError, match="unavailable"):
        build_installed_mybee_voucher_candidate_consumer(
            _environment(),
            activator_registry=DomainIntentActivatorRegistry(),
        )


@pytest.mark.parametrize(
    "environment",
    (
        {"NEX_EOS_BASE_URL": "eos.invalid"},
        {"NEX_AE_TO_EOS_SERVICE_TOKEN": ""},
        {"NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS": "0"},
        {"NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS": "not-numeric"},
    ),
)
def test_installed_binding_rejects_missing_or_malformed_runtime_configuration(
    environment: dict[str, str],
) -> None:
    with pytest.raises(MyBeeProductConsumerError):
        build_installed_mybee_voucher_candidate_consumer(_environment(**environment))


def test_consumer_binding_helpers_are_bounded_and_non_protected_is_explicit() -> None:
    assert _base_url("https://eos.example/") == "https://eos.example"
    assert _timeout("120") == 120.0
    for value in ("", "ftp://eos.example", "http:///missing"):
        with pytest.raises(MyBeeProductConsumerError):
            _base_url(value)
    with pytest.raises(MyBeeProductConsumerError):
        _timeout("121")

    not_required = not_required_mybee_consumer_binding()
    assert not_required["status"] == "NOT_REQUIRED"
    assert not_required["operations"] == []
    assert mybee_consumer_binding_ready(not_required) is True
    assert mybee_consumer_binding_ready({"status": "FAIL"}) is False


def test_canonical_worker_configuration_admits_mybee_consumer_without_new_service() -> (
    None
):
    compose = (ROOT / "deployment/compose/canonical-platform.override.yaml").read_text(
        encoding="utf-8"
    )
    process = (
        ROOT / "services/nex-ae-api/nex_ae_api/agent_runtime_process.py"
    ).read_text(encoding="utf-8")

    assert 'NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS: "15"' in compose
    assert "NEX_AE_TO_EOS_SERVICE_TOKEN_REF" in compose
    assert "build_installed_mybee_voucher_candidate_consumer(env)" in process
    assert "mybee_product_consumer_bound" in process
    assert "nex-mybee" not in compose
