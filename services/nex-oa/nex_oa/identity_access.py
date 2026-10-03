from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    validate_authorization_header,
)


OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE = "identity:bootstrap:write"


def authorize_identity_request(
    request: Request,
    authorization: str | None,
    *,
    required_scope: str | None = None,
) -> JSONResponse | None:
    required_scopes = [DEFAULT_SERVICE_SCOPE]
    if required_scope is not None:
        required_scopes.append(required_scope)
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-oa",
        required_scopes=required_scopes,
    )
    if result.ok:
        return None

    status_code = 403 if result.error_code == "TOKEN_SCOPE_MISSING" else 401
    return problem_response(
        request,
        status_code=status_code,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authorization failed" if status_code == 403 else "Authentication failed",
        detail=result.detail or "OA requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/identity-bootstrap-access",
    )
