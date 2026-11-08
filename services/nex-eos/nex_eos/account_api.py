from __future__ import annotations

from datetime import date

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import DEFAULT_SERVICE_SCOPE, admit_service_token_from_request, problem_response

from .accounts import EosAccountError, SqlAlchemyEosAccountRepository


def register_account_routes(app: FastAPI) -> None:
    @app.get(
        "/internal/v1/accounts",
        response_model=None,
        operation_id="FINANCE.ACCOUNT.RESOLVE",
    )
    def resolve_account(
        request: Request,
        account_code: str,
        effective_at: date,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _read_account(
            request,
            authorization,
            lambda repository: repository.get_effective_account_by_code(
                tenant_id=tenant_id,
                account_code=account_code,
                effective_at=effective_at,
            ),
        )

    @app.get(
        "/internal/v1/accounts/{account_id}",
        response_model=None,
        operation_id="FINANCE.ACCOUNT.GET",
    )
    def get_account(
        account_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _read_account(
            request,
            authorization,
            lambda repository: repository.get_account(
                tenant_id=tenant_id,
                account_id=account_id,
            ),
        )


def _read_account(request: Request, authorization: str | None, operation):
    admitted = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-eos",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    if isinstance(admitted, JSONResponse):
        return admitted
    repository: SqlAlchemyEosAccountRepository | None = getattr(
        request.app.state, "eos_accounts", None
    )
    if repository is None:
        return problem_response(
            request,
            status_code=503,
            error_code="EOS_ACCOUNT_QUERY_UNAVAILABLE",
            title="EOS Account query unavailable",
            detail="EOS Account persistence is not configured.",
            retryable=True,
            type_uri="https://nex-platform.local/problems/eos-account-query-unavailable",
        )
    try:
        account = operation(repository)
    except EosAccountError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="EOS Account query failed",
            detail=exc.detail,
            retryable=False,
            type_uri="https://nex-platform.local/problems/eos-account-query-failed",
        )
    if account is None:
        return problem_response(
            request,
            status_code=404,
            error_code="EOS_ACCOUNT_NOT_FOUND",
            title="EOS Account not found",
            detail="The tenant-scoped Account does not exist.",
            retryable=False,
            type_uri="https://nex-platform.local/problems/eos-account-not-found",
        )
    return account
