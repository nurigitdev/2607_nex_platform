from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from mybee_ax.integrations import (
    HttpBusinessApprovalProviderTransport,
    HttpVoucherCandidateProviderTransport,
    NexBusinessApprovalClient,
    NexVoucherCandidateClient,
)
from mybee_ax.orchestration import (
    M1TransactionPreparationAdapter,
    load_m1_transaction_preparation_registration,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.service_auth import resolve_ae_outbound_service_token

M1_PREPARATION_RUNTIME_SCHEMA_VERSION = "ae.m1_transaction_preparation_runtime.v1"
M1_PREPARATION_TIMEOUT_ENV = "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS"


class InstalledM1TransactionPreparationError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstalledM1TransactionPreparation:
    adapter: M1TransactionPreparationAdapter = field(repr=False, compare=False)
    timeout_seconds: float

    def readiness(self) -> dict[str, Any]:
        projection: dict[str, Any] = {
            "schema_version": M1_PREPARATION_RUNTIME_SCHEMA_VERSION,
            "status": "READY",
            "provider_service_id": "nex-eos",
            "adapter_id": self.adapter.registration.adapter_id,
            "adapter_version": self.adapter.registration.adapter_version,
            "adapter_source_identity": self.adapter.registration.source_identity,
            "operations": list(self.adapter.registration.operations),
            "timeout_seconds": self.timeout_seconds,
            "content_included": False,
            "secret_included": False,
        }
        projection["readiness_hash"] = semantic_sha256_hash_ref(projection)
        return projection


def build_installed_m1_transaction_preparation(
    environ: Mapping[str, str],
) -> InstalledM1TransactionPreparation:
    try:
        eos_base_url = _base_url(environ.get("NEX_EOS_BASE_URL"))
        timeout_seconds = _timeout(environ.get(M1_PREPARATION_TIMEOUT_ENV, "15"))
        service_token = resolve_ae_outbound_service_token(
            environ.get("NEX_AE_TO_EOS_SERVICE_TOKEN") or None,
            audience="nex-eos",
            environ=environ,
        )
        business_approvals = NexBusinessApprovalClient(
            HttpBusinessApprovalProviderTransport(
                eos_base_url=eos_base_url,
                service_token=service_token,
                timeout_seconds=timeout_seconds,
            )
        )
        voucher_candidates = NexVoucherCandidateClient(
            HttpVoucherCandidateProviderTransport(
                eos_base_url=eos_base_url,
                service_token=service_token,
                timeout_seconds=timeout_seconds,
            )
        )
        adapter = M1TransactionPreparationAdapter(
            registration=load_m1_transaction_preparation_registration(),
            business_approvals=business_approvals,
            voucher_candidates=voucher_candidates,
            review_boundaries_enabled=True,
        )
    except Exception as exc:
        if isinstance(exc, InstalledM1TransactionPreparationError):
            raise
        raise InstalledM1TransactionPreparationError(
            "Installed M1 transaction preparation is unavailable."
        ) from exc
    return InstalledM1TransactionPreparation(
        adapter=adapter,
        timeout_seconds=timeout_seconds,
    )


def _base_url(value: object) -> str:
    normalized = str(value or "").strip()
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InstalledM1TransactionPreparationError(
            "NEX_EOS_BASE_URL must be an HTTP(S) URL."
        )
    return normalized.rstrip("/")


def _timeout(value: object) -> float:
    try:
        timeout = float(str(value))
    except (TypeError, ValueError) as exc:
        raise InstalledM1TransactionPreparationError(
            f"{M1_PREPARATION_TIMEOUT_ENV} must be numeric."
        ) from exc
    if not 0 < timeout <= 120:
        raise InstalledM1TransactionPreparationError(
            f"{M1_PREPARATION_TIMEOUT_ENV} must be between 0 and 120 seconds."
        )
    return timeout
