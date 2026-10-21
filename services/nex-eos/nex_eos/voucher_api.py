from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .voucher_commands import (
    EosCreateVoucherDraftService,
    EosServiceCaller,
    EosVoucherCommandError,
)
from .business_queries import EosBusinessQueryError
from .voucher_verification import EosVoucherVerificationError


def register_voucher_command_routes(app: FastAPI) -> None:
    @app.post("/internal/v1/finance/voucher-drafts", response_model=None)
    def create_voucher_draft(
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
        service: EosCreateVoucherDraftService | None = getattr(
            request.app.state, "eos_voucher_command_service", None
        )
        if service is None:
            return problem_response(
                request,
                status_code=503,
                error_code="EOS_VOUCHER_COMMAND_UNAVAILABLE",
                title="EOS Voucher command unavailable",
                detail="EOS Voucher command dependencies are not configured.",
                retryable=True,
                type_uri="https://nex-platform.local/problems/eos-voucher-command-unavailable",
            )
        try:
            result = service.execute(
                payload,
                caller=EosServiceCaller(
                    subject=admitted.subject,
                    audience=admitted.audience,
                    scopes=admitted.scopes,
                ),
            )
        except EosVoucherCommandError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="EOS Voucher command failed",
                detail=exc.detail,
                retryable=exc.retryable,
                type_uri="https://nex-platform.local/problems/eos-voucher-command-failed",
            )
        return JSONResponse(
            result,
            status_code=201 if result["idempotency_disposition"] == "CREATED" else 200,
        )

    @app.get(
        "/internal/v1/business-operations/{business_operation_id}",
        response_model=None,
    )
    def get_business_operation(
        business_operation_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        query = getattr(request.app.state, "eos_business_operation_query", None)
        if query is None:
            return problem_response(
                request,
                status_code=503,
                error_code="EOS_BUSINESS_QUERY_UNAVAILABLE",
                title="EOS BusinessOperation query unavailable",
                detail="EOS BusinessOperation query dependency is not configured.",
                retryable=True,
                type_uri="https://nex-platform.local/problems/eos-business-query-unavailable",
            )
        try:
            return query.get(
                tenant_id=tenant_id,
                business_operation_id=business_operation_id,
            )
        except EosBusinessQueryError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="EOS BusinessOperation query failed",
                detail=exc.detail,
                retryable=exc.retryable,
                type_uri="https://nex-platform.local/problems/eos-business-query-failed",
            )

    @app.get(
        "/internal/v1/finance/voucher-drafts/{voucher_id}/verification",
        response_model=None,
    )
    def verify_voucher_draft(
        voucher_id: str,
        request: Request,
        business_operation_id: str,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        query = getattr(request.app.state, "eos_voucher_verification_query", None)
        if query is None:
            return problem_response(
                request,
                status_code=503,
                error_code="EOS_VOUCHER_VERIFICATION_UNAVAILABLE",
                title="EOS Voucher verification unavailable",
                detail="EOS Voucher verification dependency is not configured.",
                retryable=True,
                type_uri="https://nex-platform.local/problems/eos-voucher-verification-unavailable",
            )
        try:
            return query.verify(
                tenant_id=tenant_id,
                voucher_id=voucher_id,
                business_operation_id=business_operation_id,
            )
        except EosVoucherVerificationError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="EOS Voucher verification failed",
                detail=exc.detail,
                retryable=exc.retryable,
                type_uri="https://nex-platform.local/problems/eos-voucher-verification-failed",
            )
