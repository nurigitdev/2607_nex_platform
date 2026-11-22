from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from nex_runtime import problem_response

from .accounting_approval import (
    EosAccountingApprovalError,
    EosAccountingApprovalService,
)
from .document_signoff import (
    EosDocumentSignoffError,
    EosScopedApprovalDecisionRouter,
)

SCOPED_APPROVAL_RESUME_PREFIX = "eos.scoped-approval-case:"


def is_scoped_approval_delivery(payload: Mapping[str, Any]) -> bool:
    work_item = payload.get("work_item")
    if not isinstance(work_item, Mapping):
        return False
    target = work_item.get("resume_target_ref")
    return isinstance(target, str) and target.startswith(SCOPED_APPROVAL_RESUME_PREFIX)


def ingest_scoped_accounting_delivery(
    *, payload: Mapping[str, Any], request: Request
) -> dict[str, Any] | JSONResponse:
    router: EosScopedApprovalDecisionRouter | None = getattr(
        request.app.state, "eos_scoped_approval_decision_router", None
    )
    service: EosAccountingApprovalService | None = getattr(
        request.app.state, "eos_accounting_approval_service", None
    )
    if router is None and service is None:
        return problem_response(
            request,
            status_code=503,
            error_code="EOS_ACCOUNTING_APPROVAL_UNAVAILABLE",
            title="EOS accounting approval unavailable",
            detail=(
                "Accounting approval persistence, fresh OA authorization, or WC "
                "publication is not configured."
            ),
            retryable=True,
            type_uri=(
                "https://nex-platform.local/problems/"
                "eos-accounting-approval-unavailable"
            ),
        )
    try:
        return (
            router.ingest_wc_delivery(payload)
            if router is not None
            else service.ingest_wc_delivery(payload)
        )
    except EosAccountingApprovalError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="EOS accounting approval decision failed",
            detail=exc.detail,
            retryable=exc.retryable,
            type_uri=(
                "https://nex-platform.local/problems/"
                "eos-accounting-approval-decision-failed"
            ),
        )
    except EosDocumentSignoffError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="EOS document signoff decision failed",
            detail=exc.detail,
            retryable=exc.retryable,
            type_uri=(
                "https://nex-platform.local/problems/"
                "eos-document-signoff-decision-failed"
            ),
        )


__all__ = (
    "SCOPED_APPROVAL_RESUME_PREFIX",
    "ingest_scoped_accounting_delivery",
    "is_scoped_approval_delivery",
)
