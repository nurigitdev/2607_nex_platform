from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .transaction_preparation_authority import (
    TRANSACTION_PREPARATION_AUTHORITY_OPERATION,
    TRANSACTION_PREPARATION_AUTHORITY_PATH,
    EosTransactionPreparationAuthorityError,
    EosTransactionPreparationAuthorityService,
)

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
}
_REQUIRED_BODY = Body(...)


def register_transaction_preparation_authority_routes(app: FastAPI) -> None:
    @app.post(
        TRANSACTION_PREPARATION_AUTHORITY_PATH,
        response_model=None,
        operation_id=TRANSACTION_PREPARATION_AUTHORITY_OPERATION,
    )
    def resolve_transaction_preparation_authority(
        request: Request,
        payload: Any = _REQUIRED_BODY,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
        )
        if isinstance(admitted, JSONResponse):
            return _no_store(admitted)
        service: EosTransactionPreparationAuthorityService | None = getattr(
            request.app.state,
            "eos_transaction_preparation_authority_service",
            None,
        )
        if service is None:
            return _no_store(
                _problem(
                    request,
                    EosTransactionPreparationAuthorityError(
                        "EOS_TRANSACTION_PREPARATION_AUTHORITY_UNAVAILABLE",
                        "Transaction preparation authority dependencies are unavailable",
                        status_code=503,
                        retryable=True,
                    ),
                )
            )
        try:
            result = service.resolve(
                tenant_id=tenant_id,
                requester_subject_id=requester_subject_id,
                payload=payload,
            )
        except EosTransactionPreparationAuthorityError as exc:
            return _no_store(_problem(request, exc))
        return JSONResponse(result, headers=_NO_STORE_HEADERS)


def _problem(request: Request, exc: EosTransactionPreparationAuthorityError):
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS transaction preparation authority resolution failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/"
            "eos-transaction-preparation-authority-failed"
        ),
    )


def _no_store(response: JSONResponse) -> JSONResponse:
    response.headers.update(_NO_STORE_HEADERS)
    return response


__all__ = ["register_transaction_preparation_authority_routes"]
