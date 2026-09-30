from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    validate_authorization_header,
)


def authorize_mo_service_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-mo",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "MO requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )
