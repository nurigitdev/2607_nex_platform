from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .voucher_candidate_commands import (
    EosCreateVoucherCandidateService,
    EosVoucherCandidateCommandError,
)
from .voucher_candidates import (
    EosVoucherCandidateError,
    SqlAlchemyEosVoucherCandidateRepository,
)
from .voucher_commands import EosServiceCaller


def register_finance_v2_routes(app: FastAPI) -> None:
    @app.post("/internal/v2/finance/voucher-candidates", response_model=None)
    def create_voucher_candidate(
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
        service: EosCreateVoucherCandidateService | None = getattr(
            request.app.state,
            "eos_voucher_candidate_command_service",
            None,
        )
        if service is None:
            return _problem(
                request,
                EosVoucherCandidateCommandError(
                    "EOS_VOUCHER_CANDIDATE_COMMAND_UNAVAILABLE",
                    "VoucherCandidate command dependencies are not configured.",
                    status_code=503,
                    retryable=True,
                ),
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
        except EosVoucherCandidateCommandError as exc:
            return _problem(request, exc)
        return JSONResponse(
            result,
            status_code=201 if result["idempotency_disposition"] == "CREATED" else 200,
        )

    @app.get(
        "/internal/v2/finance/voucher-candidates/{candidate_id}",
        response_model=None,
        operation_id="FINANCE.VOUCHER_CANDIDATE.GET_V2",
    )
    def get_voucher_candidate(
        candidate_id: str,
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
        repository: SqlAlchemyEosVoucherCandidateRepository | None = getattr(
            request.app.state,
            "eos_voucher_candidates",
            None,
        )
        if repository is None:
            return problem_response(
                request,
                status_code=503,
                error_code="EOS_VOUCHER_CANDIDATE_QUERY_UNAVAILABLE",
                title="EOS VoucherCandidate query unavailable",
                detail="VoucherCandidate query persistence is not configured.",
                retryable=True,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-voucher-candidate-query-unavailable"
                ),
            )
        try:
            result = repository.get(tenant_id=tenant_id, candidate_id=candidate_id)
        except EosVoucherCandidateError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="EOS VoucherCandidate query failed",
                detail=exc.detail,
                retryable=exc.retryable,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-voucher-candidate-query-failed"
                ),
            )
        if result is None:
            return problem_response(
                request,
                status_code=404,
                error_code="EOS_VOUCHER_CANDIDATE_NOT_FOUND",
                title="EOS VoucherCandidate not found",
                detail="VoucherCandidate was not found in tenant scope.",
                retryable=False,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-voucher-candidate-not-found"
                ),
            )
        return result


def _problem(request: Request, exc: EosVoucherCandidateCommandError):
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS VoucherCandidate command failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/eos-voucher-candidate-command-failed"
        ),
    )
