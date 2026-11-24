"""Separately authorized installed accounting allocation orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from mybee_ax.orchestration import M1FinancialResultIntegrator
from nex_runtime.business_context import (
    BusinessContextValidationError,
    validate_business_request_context,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_ae_api.business_result_summary import build_project_allocation_summary

ACCOUNTING_ALLOCATION_SCOPE = "finance:allocation:execute"
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
        preparation_checkpoint: Mapping[str, Any],
        existing_authority_checkpoint: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        _uuid("company_id", company_id)
        _uuid("journal_id", journal_id)
        authorization = self._authority.effective_authorization(
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
        scopes = authorization.get("scopes")
        if (
            authorization.get("active") is not True
            or not isinstance(scopes, (list, tuple))
            or ACCOUNTING_ALLOCATION_SCOPE not in scopes
        ):
            raise AccountingAllocationRuntimeError(
                "OA denied current accounting allocation authority."
            )
        revision_hash = authorization.get("revision_hash")
        try:
            validate_hash_ref(revision_hash)
            context = validate_business_request_context(
                work_intent.get("business_request_context")
            )
        except (TypeError, ValueError, BusinessContextValidationError) as exc:
            raise AccountingAllocationRuntimeError(
                "Accounting allocation authority input is invalid."
            ) from exc
        if not context["requested_allocation"]:
            raise AccountingAllocationRuntimeError(
                "Accounting allocation requires explicit Project ratios."
            )
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
