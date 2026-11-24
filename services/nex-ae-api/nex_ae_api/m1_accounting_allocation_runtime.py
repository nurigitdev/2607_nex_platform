"""Separately authorized installed accounting allocation orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from mybee_ax.orchestration import M1FinancialResultIntegrator
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_ae_api.accounting_allocation_authority import (
    ACCOUNTING_ALLOCATION_SCOPE,
    AccountingAllocationAuthorityError,
    build_accounting_allocation_authority_checkpoint,
    validate_accounting_allocation_work_intent,
)
from nex_ae_api.business_result_summary import build_project_allocation_summary

ACCOUNTING_ALLOCATION_RESULT_SCHEMA = "ae.accounting_allocation_result.v1"


class AccountingAllocationRuntimeError(RuntimeError):
    pass


class InstalledAccountingAllocationRuntime:
    """Runs allocation only through an explicit, current accounting authority."""

    def __init__(
        self, *, integrator: M1FinancialResultIntegrator, authority: Any
    ) -> None:
        self._integrator = integrator
        self._authority = authority

    def readiness(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "status": "READY",
                "operation": "FINANCE.COST_ALLOCATION.RUN",
                "required_scope": ACCOUNTING_ALLOCATION_SCOPE,
                "journal_auto_invocation": False,
            }
        )

    def execute(
        self,
        *,
        tenant_id: str,
        company_id: str,
        subject_id: str,
        correlation_id: str,
        journal_id: str,
        work_intent: Mapping[str, Any],
        runtime_job: Mapping[str, Any],
        existing_execution_authority: Mapping[str, Any] | None = None,
        existing_authority_checkpoint: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        _uuid("company_id", company_id)
        _uuid("journal_id", journal_id)
        try:
            intent = validate_accounting_allocation_work_intent(work_intent)
        except Exception as exc:
            raise AccountingAllocationRuntimeError(
                "Accounting allocation WorkIntent is invalid."
            ) from exc
        if (
            intent["tenant_id"] != tenant_id
            or intent["company_id"] != company_id
            or intent["subject_id"] != subject_id
            or intent["journal_id"] != journal_id
        ):
            raise AccountingAllocationRuntimeError(
                "Accounting allocation WorkIntent scope differs."
            )
        authorization = self._authority.effective_authorization(
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
        try:
            execution_authority = build_accounting_allocation_authority_checkpoint(
                work_intent=intent,
                authorization=authorization,
                runtime_job=runtime_job,
                existing_checkpoint=existing_execution_authority,
            )
        except AccountingAllocationAuthorityError as exc:
            if exc.error_code == "ACCOUNTING_ALLOCATION_AUTHORITY_DENIED":
                raise AccountingAllocationRuntimeError(exc.detail) from exc
            raise AccountingAllocationRuntimeError(
                "Accounting allocation authority input is invalid."
            ) from exc
        except Exception as exc:
            raise AccountingAllocationRuntimeError(
                "Accounting allocation authority input is invalid."
            ) from exc
        financial = self._integrator.integrate(
            tenant_id=tenant_id,
            company_id=company_id,
            subject_id=subject_id,
            correlation_id=correlation_id,
            journal_id=journal_id,
            work_intent=intent,
            allocation_authority_checkpoint=execution_authority,
            source_record_line_ref=intent["source_record_line_ref"],
            source_kind=intent["source_kind"],
            existing_authority_checkpoint=existing_authority_checkpoint,
        )
        semantics = {
            "schema_version": ACCOUNTING_ALLOCATION_RESULT_SCHEMA,
            "operation": "FINANCE.COST_ALLOCATION.RUN",
            "tenant_id": tenant_id,
            "company_id": company_id,
            "subject_id": subject_id,
            "journal_ref": f"eos.posted_journal:{journal_id}",
            "allocation_execution_authority_hash": execution_authority[
                "authority_hash"
            ],
            "oa_authority_revision_hash": execution_authority["oa_authority"][
                "revision_hash"
            ],
            "runtime_job_ref": (
                f"ae.runtime-job:{execution_authority['runtime_job']['runtime_job_id']}"
            ),
            "replay_identity": intent["replay_identity"],
            "publication": dict(execution_authority["publication"]),
            "financial_result": dict(financial),
            "business_summary": build_project_allocation_summary(financial),
        }
        return MappingProxyType(
            {**semantics, "result_hash": semantic_sha256_hash_ref(semantics)}
        )

    def execute_historical_d04_replay(
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
        """Read/replay adapter for pre-W80 D04 allocation evidence only."""

        authorization = self._authority.effective_authorization(
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
        scopes = authorization.get("scopes")
        revision_hash = authorization.get("revision_hash")
        if (
            authorization.get("active") is not True
            or not isinstance(scopes, (list, tuple))
            or ACCOUNTING_ALLOCATION_SCOPE not in scopes
        ):
            raise AccountingAllocationRuntimeError(
                "OA denied current accounting allocation authority."
            )
        try:
            validate_hash_ref(revision_hash)
        except (TypeError, ValueError) as exc:
            raise AccountingAllocationRuntimeError(
                "Historical D04 allocation authority is invalid."
            ) from exc
        financial = self._integrator.integrate(
            tenant_id=tenant_id,
            company_id=company_id,
            subject_id=subject_id,
            correlation_id=correlation_id,
            journal_id=journal_id,
            work_intent=work_intent,
            preparation_checkpoint=preparation_checkpoint,
            existing_authority_checkpoint=existing_authority_checkpoint,
        )
        semantics = {
            "schema_version": ACCOUNTING_ALLOCATION_RESULT_SCHEMA,
            "operation": "FINANCE.COST_ALLOCATION.RUN",
            "tenant_id": tenant_id,
            "company_id": company_id,
            "subject_id": subject_id,
            "journal_ref": f"eos.posted_journal:{journal_id}",
            "authority_revision_hash": revision_hash,
            "compatibility_mode": "HISTORICAL_D04_REPLAY_ONLY",
            "financial_result": dict(financial),
            "business_summary": build_project_allocation_summary(financial),
        }
        return MappingProxyType(
            {**semantics, "result_hash": semantic_sha256_hash_ref(semantics)}
        )


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise AccountingAllocationRuntimeError(f"{field_name} is invalid.") from exc
