"""Installed, scenario-neutral allocation-to-P&L refresh boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from mybee_ax.integrations import (
    PROJECT_PNL_REFRESH_OPERATION,
    HttpProjectPnlRefreshProviderTransport,
    NexProjectPnlRefreshClient,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.service_auth import resolve_ae_outbound_service_token

PROJECT_PNL_REFRESH_RUNTIME_SCHEMA = "ae.project_pnl_refresh_runtime.v1"
PROJECT_PNL_REFRESH_TIMEOUT_ENV = "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS"


class InstalledProjectPnlRefreshError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstalledProjectPnlRefresh:
    client: NexProjectPnlRefreshClient = field(repr=False, compare=False)
    timeout_seconds: float

    def readiness(self) -> dict[str, Any]:
        projection: dict[str, Any] = {
            "schema_version": PROJECT_PNL_REFRESH_RUNTIME_SCHEMA,
            "status": "READY",
            "provider_service_id": "nex-eos",
            "operation": PROJECT_PNL_REFRESH_OPERATION,
            "timeout_seconds": self.timeout_seconds,
            "business_defaults_included": False,
            "content_included": False,
            "secret_included": False,
        }
        projection["readiness_hash"] = semantic_sha256_hash_ref(projection)
        return projection

    def refresh(
        self,
        *,
        tenant_id: str,
        company_id: str,
        batch_id: str,
        correlation_id: str,
    ) -> Mapping[str, Any]:
        return self.client.refresh(
            tenant_id=tenant_id,
            company_id=company_id,
            batch_id=batch_id,
            correlation_id=correlation_id,
        )


def build_installed_project_pnl_refresh(
    environ: Mapping[str, str],
) -> InstalledProjectPnlRefresh:
    try:
        eos_base_url = _base_url(environ.get("NEX_EOS_BASE_URL"))
        timeout_seconds = _timeout(environ.get(PROJECT_PNL_REFRESH_TIMEOUT_ENV, "15"))
        service_token = resolve_ae_outbound_service_token(
            environ.get("NEX_AE_TO_EOS_SERVICE_TOKEN") or None,
            audience="nex-eos",
            environ=environ,
        )
        client = NexProjectPnlRefreshClient(
            HttpProjectPnlRefreshProviderTransport(
                eos_base_url=eos_base_url,
                service_token=service_token,
                timeout_seconds=timeout_seconds,
            )
        )
    except Exception as exc:
        if isinstance(exc, InstalledProjectPnlRefreshError):
            raise
        raise InstalledProjectPnlRefreshError(
            "Installed Project P&L refresh is unavailable."
        ) from exc
    return InstalledProjectPnlRefresh(client=client, timeout_seconds=timeout_seconds)


def _base_url(value: object) -> str:
    normalized = str(value or "").strip()
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InstalledProjectPnlRefreshError(
            "NEX_EOS_BASE_URL must be an HTTP(S) URL."
        )
    return normalized.rstrip("/")


def _timeout(value: object) -> float:
    try:
        timeout = float(str(value))
    except (TypeError, ValueError) as exc:
        raise InstalledProjectPnlRefreshError(
            f"{PROJECT_PNL_REFRESH_TIMEOUT_ENV} must be numeric."
        ) from exc
    if not 0 < timeout <= 120:
        raise InstalledProjectPnlRefreshError(
            f"{PROJECT_PNL_REFRESH_TIMEOUT_ENV} must be between 0 and 120 seconds."
        )
    return timeout
