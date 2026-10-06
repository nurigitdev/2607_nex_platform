from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    AdmittedServiceClaims,
    DEFAULT_SERVICE_SCOPE,
    ServiceTokenAdmissionError,
    admit_service_token_from_request,
    admit_test_mock_service_token,
    problem_response,
)

MO_SERVICE_CLAIMS_STATE_KEY = "mo_service_claims"
MO_OPERATIONS_READ_SCOPE = "operations:read"


def authorize_mo_service_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-mo",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    if isinstance(result, JSONResponse):
        return result

    setattr(request.state, MO_SERVICE_CLAIMS_STATE_KEY, result)
    return None


def authorize_mo_operations_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-mo",
        required_scopes=(DEFAULT_SERVICE_SCOPE, MO_OPERATIONS_READ_SCOPE),
        route_class="ADMIN",
    )
    if isinstance(result, JSONResponse):
        return result
    if result.service_id != "nex-ag":
        return problem_response(
            request,
            status_code=403,
            error_code="MO_OPERATIONS_CALLER_FORBIDDEN",
            title="Authorization failed",
            detail="MO trace operations are available only to NeX-AG.",
            type_uri="https://nex-platform.local/problems/authorization-failed",
        )
    setattr(request.state, MO_SERVICE_CLAIMS_STATE_KEY, result)
    return None


def authenticated_mo_service_actor(
    request_or_authorization: Request | str | None,
) -> str:
    if isinstance(request_or_authorization, Request):
        claims = getattr(
            request_or_authorization.state,
            MO_SERVICE_CLAIMS_STATE_KEY,
            None,
        )
        if isinstance(claims, AdmittedServiceClaims):
            return claims.subject
        raise ValueError("a validated MO service claim is required")
    try:
        claims = admit_test_mock_service_token(
            request_or_authorization,
            expected_audience="nex-mo",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
        )
    except ServiceTokenAdmissionError:
        raise ValueError("a validated MO service claim is required")
    return claims.subject
