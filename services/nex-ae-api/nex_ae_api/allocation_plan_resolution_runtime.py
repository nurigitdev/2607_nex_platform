"""Installed, scenario-neutral AllocationPlan resolution boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from mybee_ax.integrations import (
    ALLOCATION_PLAN_RESOLVE_OPERATION,
    HttpAllocationPlanProviderTransport,
    NexAllocationPlanResolverClient,
    build_allocation_plan_resolve_by_code_request,
    build_allocation_plan_resolve_request,
)
from mybee_ax.orchestration import (
    APPROVED_ALLOCATION_PLAN_AUTHORITY_SCHEMA,
    INDEPENDENT_ALLOCATION_PLAN_AUTHORITY_SCHEMA,
    AllocationAuthorityLineage,
    ApprovedAllocationPlanAuthorityBinder,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.service_auth import resolve_ae_outbound_service_token

ALLOCATION_PLAN_RUNTIME_SCHEMA = "ae.approved_allocation_plan_resolution_runtime.v1"
ALLOCATION_PLAN_TIMEOUT_ENV = "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS"


class InstalledAllocationPlanResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstalledApprovedAllocationPlanResolution:
    client: NexAllocationPlanResolverClient = field(repr=False, compare=False)
    binder: ApprovedAllocationPlanAuthorityBinder = field(repr=False, compare=False)
    timeout_seconds: float

    def readiness(self) -> dict[str, Any]:
        projection: dict[str, Any] = {
            "schema_version": ALLOCATION_PLAN_RUNTIME_SCHEMA,
            "status": "READY",
            "provider_service_id": "nex-eos",
            "operation": ALLOCATION_PLAN_RESOLVE_OPERATION,
            "authority_schema": APPROVED_ALLOCATION_PLAN_AUTHORITY_SCHEMA,
            "independent_authority_schema": (
                INDEPENDENT_ALLOCATION_PLAN_AUTHORITY_SCHEMA
            ),
            "timeout_seconds": self.timeout_seconds,
            "business_defaults_included": False,
            "content_included": False,
            "secret_included": False,
        }
        projection["readiness_hash"] = semantic_sha256_hash_ref(projection)
        return projection

    def resolve_and_bind(
        self,
        *,
        tenant_id: str,
        company_id: str,
        source_kind: str,
        effective_on: str,
        projects: Sequence[Mapping[str, Any]],
        correlation_id: str,
        source_pool: Mapping[str, Any],
        lineage: AllocationAuthorityLineage,
        existing_checkpoint: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        request = build_allocation_plan_resolve_request(
            tenant_id=tenant_id,
            company_id=company_id,
            source_kind=source_kind,
            effective_on=effective_on,
            projects=projects,
            correlation_id=correlation_id,
        )
        resolution = self.client.resolve_request(request)
        return self.binder.bind(
            request=request,
            resolution=resolution,
            source_pool=source_pool,
            lineage=lineage,
            existing_checkpoint=existing_checkpoint,
        )

    def resolve_and_bind_by_project_codes(
        self,
        *,
        tenant_id: str,
        company_id: str,
        source_kind: str,
        effective_on: str,
        projects: Sequence[Mapping[str, Any]],
        correlation_id: str,
        source_pool: Mapping[str, Any],
        lineage: AllocationAuthorityLineage,
        existing_checkpoint: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        request = build_allocation_plan_resolve_by_code_request(
            tenant_id=tenant_id,
            company_id=company_id,
            source_kind=source_kind,
            effective_on=effective_on,
            projects=projects,
            correlation_id=correlation_id,
        )
        resolution = self.client.resolve_request(request)
        return self.binder.bind(
            request=request,
            resolution=resolution,
            source_pool=source_pool,
            lineage=lineage,
            existing_checkpoint=existing_checkpoint,
        )


def build_installed_allocation_plan_resolution(
    environ: Mapping[str, str],
) -> InstalledApprovedAllocationPlanResolution:
    try:
        eos_base_url = _base_url(environ.get("NEX_EOS_BASE_URL"))
        timeout_seconds = _timeout(environ.get(ALLOCATION_PLAN_TIMEOUT_ENV, "15"))
        service_token = resolve_ae_outbound_service_token(
            environ.get("NEX_AE_TO_EOS_SERVICE_TOKEN") or None,
            audience="nex-eos",
            environ=environ,
        )
        client = NexAllocationPlanResolverClient(
            HttpAllocationPlanProviderTransport(
                eos_base_url=eos_base_url,
                service_token=service_token,
                timeout_seconds=timeout_seconds,
            )
        )
    except Exception as exc:
        if isinstance(exc, InstalledAllocationPlanResolutionError):
            raise
        raise InstalledAllocationPlanResolutionError(
            "Installed AllocationPlan resolution is unavailable."
        ) from exc
    return InstalledApprovedAllocationPlanResolution(
        client=client,
        binder=ApprovedAllocationPlanAuthorityBinder(),
        timeout_seconds=timeout_seconds,
    )


def _base_url(value: object) -> str:
    normalized = str(value or "").strip()
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InstalledAllocationPlanResolutionError(
            "NEX_EOS_BASE_URL must be an HTTP(S) URL."
        )
    return normalized.rstrip("/")


def _timeout(value: object) -> float:
    try:
        timeout = float(str(value))
    except (TypeError, ValueError) as exc:
        raise InstalledAllocationPlanResolutionError(
            f"{ALLOCATION_PLAN_TIMEOUT_ENV} must be numeric."
        ) from exc
    if not 0 < timeout <= 120:
        raise InstalledAllocationPlanResolutionError(
            f"{ALLOCATION_PLAN_TIMEOUT_ENV} must be between 0 and 120 seconds."
        )
    return timeout
