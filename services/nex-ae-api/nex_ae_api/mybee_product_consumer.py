from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from mybee_ax.integrations import (
    HttpVoucherCandidateProviderTransport,
    NexVoucherCandidateClient,
)
from mybee_ax.integrations.nex_approval_client import (
    ACCOUNTING_APPROVAL_REQUEST_OPERATION,
)
from mybee_ax.integrations.nex_voucher_candidate_client import (
    CREATE_OPERATION,
    REVIEW_GET_OPERATION,
    VALIDATE_OPERATION,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.domain_intent_activators import DomainIntentActivatorRegistry
from nex_ae_api.domain_intent_products import build_domain_intent_activator_registry
from nex_ae_api.golden_a_planning import GOLDEN_A_CAPABILITY_ID
from nex_ae_api.mybee_product_admission import require_mybee_product_package
from nex_ae_api.product_capabilities import (
    ProductCapabilityRegistry,
    load_product_capability_registry,
)
from nex_ae_api.service_auth import resolve_ae_outbound_service_token

MYBEE_CONSUMER_BINDING_SCHEMA_VERSION = "ae.mybee_consumer_binding.v1"
MYBEE_CONSUMER_ID = "MYBEE.FINANCE.VOUCHER_CANDIDATE"
MYBEE_CONSUMER_TIMEOUT_ENV = "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS"
MYBEE_CONSUMER_OPERATIONS = (
    CREATE_OPERATION,
    VALIDATE_OPERATION,
    ACCOUNTING_APPROVAL_REQUEST_OPERATION,
    REVIEW_GET_OPERATION,
)


class MyBeeProductConsumerError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstalledMyBeeVoucherCandidateConsumer:
    client: NexVoucherCandidateClient = field(repr=False, compare=False)
    capability_source_identity: str
    activator_source_identity: str
    package_admission: Mapping[str, Any] = field(repr=False)
    timeout_seconds: float

    def readiness(self) -> dict[str, Any]:
        projection: dict[str, Any] = {
            "schema_version": MYBEE_CONSUMER_BINDING_SCHEMA_VERSION,
            "status": "PASS",
            "consumer_id": MYBEE_CONSUMER_ID,
            "upstream_capability_id": GOLDEN_A_CAPABILITY_ID,
            "provider_service_id": "nex-eos",
            "operations": list(MYBEE_CONSUMER_OPERATIONS),
            "capability_source_identity": self.capability_source_identity,
            "activator_source_identity": self.activator_source_identity,
            "package_version": self.package_admission["package_version"],
            "timeout_seconds": self.timeout_seconds,
            "content_included": False,
            "secret_included": False,
        }
        projection["binding_hash"] = semantic_sha256_hash_ref(projection)
        return projection


def build_installed_mybee_voucher_candidate_consumer(
    environ: Mapping[str, str],
    *,
    product_capability_registry: ProductCapabilityRegistry | None = None,
    activator_registry: DomainIntentActivatorRegistry | None = None,
) -> InstalledMyBeeVoucherCandidateConsumer:
    """Bind the admitted planning capability to the non-NSL MyBee HTTP client."""

    try:
        package_admission = require_mybee_product_package()
        capabilities = product_capability_registry or load_product_capability_registry(
            environ
        )
        capability = capabilities.resolve(GOLDEN_A_CAPABILITY_ID, required=True)
        assert capability is not None
        activators = activator_registry or build_domain_intent_activator_registry(
            environ,
            product_capability_registry=capabilities,
        )
        activator = activators.resolve(GOLDEN_A_CAPABILITY_ID, required=True)
        assert activator is not None
        eos_base_url = _base_url(environ.get("NEX_EOS_BASE_URL"))
        timeout_seconds = _timeout(environ.get(MYBEE_CONSUMER_TIMEOUT_ENV, "15"))
        service_token = resolve_ae_outbound_service_token(
            environ.get("NEX_AE_TO_EOS_SERVICE_TOKEN") or None,
            audience="nex-eos",
            environ=environ,
        )
        client = NexVoucherCandidateClient(
            HttpVoucherCandidateProviderTransport(
                eos_base_url=eos_base_url,
                service_token=service_token,
                timeout_seconds=timeout_seconds,
            )
        )
    except Exception as exc:
        if isinstance(exc, MyBeeProductConsumerError):
            raise
        raise MyBeeProductConsumerError(
            "Installed MyBee VoucherCandidate consumer is unavailable."
        ) from exc
    return InstalledMyBeeVoucherCandidateConsumer(
        client=client,
        capability_source_identity=capability.source_identity,
        activator_source_identity=activator.source_identity,
        package_admission=package_admission,
        timeout_seconds=timeout_seconds,
    )


def not_required_mybee_consumer_binding() -> dict[str, Any]:
    return {
        "schema_version": MYBEE_CONSUMER_BINDING_SCHEMA_VERSION,
        "status": "NOT_REQUIRED",
        "consumer_id": MYBEE_CONSUMER_ID,
        "upstream_capability_id": GOLDEN_A_CAPABILITY_ID,
        "provider_service_id": "nex-eos",
        "operations": [],
        "content_included": False,
        "secret_included": False,
    }


def mybee_consumer_binding_ready(value: Mapping[str, Any]) -> bool:
    return value.get("status") in {"PASS", "NOT_REQUIRED"}


def _base_url(value: object) -> str:
    normalized = str(value or "").strip()
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MyBeeProductConsumerError("NEX_EOS_BASE_URL must be an HTTP(S) URL.")
    return normalized.rstrip("/")


def _timeout(value: object) -> float:
    try:
        timeout = float(str(value))
    except (TypeError, ValueError) as exc:
        raise MyBeeProductConsumerError(
            f"{MYBEE_CONSUMER_TIMEOUT_ENV} must be numeric."
        ) from exc
    if not 0 < timeout <= 120:
        raise MyBeeProductConsumerError(
            f"{MYBEE_CONSUMER_TIMEOUT_ENV} must be between 0 and 120 seconds."
        )
    return timeout
