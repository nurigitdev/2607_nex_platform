from __future__ import annotations

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .accounting_display import EosAccountingDisplayError, EosAccountingDisplayService


def register_accounting_display_routes(app: FastAPI) -> None:
    @app.get(
        "/internal/v2/finance/accounting-approval-cases/{case_id}/display",
        response_model=None,
        operation_id="FINANCE.ACCOUNTING_APPROVAL.DISPLAY",
    )
    def get_accounting_case_display(
        case_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _call(
            request,
            authorization,
            lambda service: service.project_case(
                tenant_id=tenant_id,
                case_id=case_id,
            ),
        )

    @app.get(
        "/internal/v2/finance/voucher-candidates/{candidate_id}/accounting-display",
        response_model=None,
        operation_id="FINANCE.VOUCHER_CANDIDATE.ACCOUNTING_DISPLAY",
    )
    def get_candidate_accounting_display(
        candidate_id: str,
        request: Request,
        expected_revision: int = Query(ge=1),
        expected_hash: str = Query(),
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _call(
            request,
            authorization,
            lambda service: service.project_candidate(
                tenant_id=tenant_id,
                candidate_id=candidate_id,
                expected_revision=expected_revision,
                expected_hash=expected_hash,
            ),
        )


def _call(request: Request, authorization: str | None, operation):
    admitted = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-eos",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    if isinstance(admitted, JSONResponse):
        return admitted
    service: EosAccountingDisplayService | None = getattr(
        request.app.state,
        "eos_accounting_display_service",
        None,
    )
    if service is None:
        return problem_response(
            request,
            status_code=503,
            error_code="EOS_ACCOUNTING_DISPLAY_UNAVAILABLE",
            title="EOS accounting display unavailable",
            detail="Accounting display dependencies are not configured.",
            retryable=True,
        )
    try:
        return operation(service)
    except EosAccountingDisplayError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="EOS accounting display request failed",
            detail=exc.detail,
            retryable=exc.retryable,
        )
