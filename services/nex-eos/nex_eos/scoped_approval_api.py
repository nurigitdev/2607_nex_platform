from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .scoped_approvals import EosScopedApprovalError, EosScopedApprovalService
from .voucher_commands import EosServiceCaller


def register_scoped_approval_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v2/finance/accounting-approval-cases",
        response_model=None,
        operation_id="FINANCE.ACCOUNTING_APPROVAL.REQUEST",
    )
    def request_accounting_approval(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
            route_class="WRITE",
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        service: EosScopedApprovalService | None = getattr(
            request.app.state, "eos_scoped_approval_service", None
        )
        if service is None:
            return problem_response(
                request,
                status_code=503,
                error_code="EOS_SCOPED_APPROVAL_SERVICE_UNAVAILABLE",
                title="EOS scoped approval service unavailable",
                detail=(
                    "Scoped approval persistence, OA authorization, or WC "
                    "publication is not configured."
                ),
                retryable=True,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-scoped-approval-service-unavailable"
                ),
            )
        try:
            result = service.request_case(
                payload,
                caller=EosServiceCaller(
                    admitted.subject, admitted.audience, admitted.scopes
                ),
            )
        except EosScopedApprovalError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="EOS scoped approval request failed",
                detail=exc.detail,
                retryable=exc.retryable,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-scoped-approval-request-failed"
                ),
            )
        return JSONResponse(result, status_code=201 if result["created"] else 200)
