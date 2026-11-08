from __future__ import annotations

from collections.abc import Sequence

from fastapi import Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    AdmittedServiceClaims,
    admit_service_token_from_request,
    problem_response,
)


def authorize_wc_service_request(
    request: Request,
    authorization: str | None,
    *,
    allowed_service_ids: Sequence[str] | None = None,
    error_code: str = "WC_CALLER_FORBIDDEN",
    detail: str = "The calling service is not authorized for this WC route.",
) -> AdmittedServiceClaims | JSONResponse:
    admitted = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-wc",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    if isinstance(admitted, JSONResponse):
        return admitted
    if allowed_service_ids is not None and admitted.service_id not in frozenset(
        allowed_service_ids
    ):
        return problem_response(
            request,
            status_code=403,
            error_code=error_code,
            title="WC service authorization failed",
            detail=detail,
            retryable=False,
        )
    return admitted
