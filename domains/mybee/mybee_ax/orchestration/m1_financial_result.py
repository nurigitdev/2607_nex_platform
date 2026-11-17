"""Authority-bound M1 allocation, P&L, and redacted result integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from ..integrations.nex_cost_allocation_client import NexCostAllocationClient
from ..integrations.nex_pnl_client import NexProjectPnlClient
from ..integrations.nex_project_pnl_refresh_client import NexProjectPnlRefreshClient
from .m1_transaction_preparation import M1PreparationRegistration

M1_FINANCIAL_RESULT_SCHEMA = "mybee.m1-financial-result.v1"


class M1FinancialResultError(RuntimeError):
    pass


class M1FinancialResultIntegrator:
    """Composes authoritative product APIs without scenario values or DB access."""

    def __init__(
        self,
        *,
        allocation_client: NexCostAllocationClient,
        refresh_client: NexProjectPnlRefreshClient,
        pnl_client: NexProjectPnlClient,
        authority_resolver: Callable[..., Mapping[str, Any]],
        registration: M1PreparationRegistration,
    ) -> None:
        self._allocation = allocation_client
        self._refresh = refresh_client
        self._pnl = pnl_client
        self._resolve_authority = authority_resolver
        self._registration = registration

    def integrate(
        self,
        *,
        tenant_id: str,
        company_id: str,
        subject_id: str,
        correlation_id: str,
        journal_id: str,
        work_intent: Mapping[str, Any],
        preparation_checkpoint: Mapping[str, Any],
        existing_authority_checkpoint: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        source_pool = self._allocation.admit_source_pool(
            tenant_id=tenant_id,
            company_id=company_id,
            journal_id=journal_id,
            subject_id=subject_id,
            correlation_id=correlation_id,
            source_record_line_ref=(
                self._registration.allocation_source_record_line_ref
            ),
            source_kind=self._registration.allocation_source_kind,
            allocation_mode=self._registration.allocation_mode,
        )
        authority = self._resolve_authority(
            work_intent=work_intent,
            preparation_checkpoint=preparation_checkpoint,
            source_pool=source_pool,
            correlation_id=correlation_id,
            existing_checkpoint=existing_authority_checkpoint,
        )
        batch, verification = self._allocation.run_verified(
            tenant_id=tenant_id,
            company_id=company_id,
            correlation_id=correlation_id,
            source_pool=source_pool,
            allocation_authority=authority,
        )
        refresh = self._refresh.refresh(
            tenant_id=tenant_id,
            company_id=company_id,
            batch_id=str(batch["batch_id"]),
            correlation_id=correlation_id,
        )
        if (
            refresh.get("period_id") != batch.get("period_id")
            or refresh.get("allocation_reconciliation_hash")
            != batch.get("reconciliation_hash")
        ):
            raise M1FinancialResultError(
                "P&L refresh differs from the verified allocation authority."
            )
        projects = _authorized_projects(preparation_checkpoint)
        refresh_projects = {
            str(item["project_code"]): dict(item)
            for item in refresh.get("projections", ())
            if isinstance(item, Mapping)
        }
        if set(refresh_projects) != set(projects):
            raise M1FinancialResultError(
                "P&L refresh Project set differs from the admitted authority."
            )
        pnl_results: list[dict[str, Any]] = []
        for project_code in sorted(projects):
            project_id = projects[project_code]
            refreshed = refresh_projects[project_code]
            projection = self._pnl.get(
                tenant_id=tenant_id,
                company_id=company_id,
                project_id=project_id,
                project_code=project_code,
                period_id=str(batch["period_id"]),
                subject_id=subject_id,
                correlation_id=correlation_id,
                projection_version=int(refreshed["projection_version"]),
            )
            if (
                projection.get("projection_id") != refreshed.get("projection_id")
                or projection.get("projection_hash")
                != refreshed.get("projection_hash")
            ):
                raise M1FinancialResultError(
                    "Authorized P&L projection differs from the refresh receipt."
                )
            pnl_results.append(
                {
                    "project_id": project_id,
                    "project_code": project_code,
                    "projection_id": projection["projection_id"],
                    "projection_version": projection["projection_version"],
                    "projection_hash": projection["projection_hash"],
                    "posted_allocated_cost": projection["posted_allocated_cost"],
                    "posted_operating_result": projection["posted_operating_result"],
                    "reconciliation_status": projection["reconciliation_status"],
                    "freshness_status": projection["freshness_status"],
                    "data_classification": projection["data_classification"],
                }
            )
        semantics = {
            "schema_version": M1_FINANCIAL_RESULT_SCHEMA,
            "stage": "ALLOCATION_AND_PNL_VERIFIED",
            "tenant_id": tenant_id,
            "company_id": company_id,
            "journal_ref": f"eos.posted_journal:{journal_id}",
            "source_pool_ref": f"eos.cost-source-pool:{source_pool['pool_id']}",
            "source_pool_hash": source_pool["source_hash"],
            "allocation_authority_hash": authority["checkpoint_hash"],
            "allocation_batch_ref": batch["business_result_ref"],
            "allocation_batch_id": batch["batch_id"],
            "allocation_business_operation_id": batch["business_operation_id"],
            "allocation_reconciliation_hash": batch["reconciliation_hash"],
            "allocation_verification_status": verification["verification_status"],
            "allocated_total": batch["allocated_total"],
            "unallocated_total": batch["unallocated_total"],
            "functional_currency": batch["functional_currency"],
            "period_id": batch["period_id"],
            "pnl_refresh_hash": refresh["refresh_hash"],
            "project_results": pnl_results,
        }
        return MappingProxyType(
            {**semantics, "result_hash": semantic_sha256_hash_ref(semantics)}
        )


def _authorized_projects(
    preparation_checkpoint: Mapping[str, Any],
) -> dict[str, str]:
    authority = preparation_checkpoint.get("authority")
    refs = authority.get("project_refs") if isinstance(authority, Mapping) else None
    if not isinstance(refs, (list, tuple)) or not refs:
        raise M1FinancialResultError("Preparation Project authority is unavailable.")
    projects: dict[str, str] = {}
    for item in refs:
        if not isinstance(item, Mapping):
            raise M1FinancialResultError("Preparation Project authority is invalid.")
        code = str(item.get("project_code") or "")
        project_id = str(item.get("project_id") or "")
        if not code or not project_id or code in projects:
            raise M1FinancialResultError("Preparation Project authority is invalid.")
        projects[code] = project_id
    return projects
