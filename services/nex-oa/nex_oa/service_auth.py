from __future__ import annotations

from collections.abc import Sequence

from fastapi import Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    AdmittedServiceClaims,
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
)


OA_SERVICE_CLAIMS_STATE_KEY = "oa_service_claims"


def authorize_oa_service_request(
    request: Request,
    authorization: str | None,
    *,
    required_scopes: Sequence[str] = (DEFAULT_SERVICE_SCOPE,),
    route_class: str = "CREDENTIAL",
) -> JSONResponse | None:
    result = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-oa",
        required_scopes=required_scopes,
        route_class=route_class,
    )
    if isinstance(result, JSONResponse):
        return result
    setattr(request.state, OA_SERVICE_CLAIMS_STATE_KEY, result)
    return None


def authenticated_oa_service_claims(request: Request) -> AdmittedServiceClaims:
    claims = getattr(request.state, OA_SERVICE_CLAIMS_STATE_KEY, None)
    if not isinstance(claims, AdmittedServiceClaims):
        raise ValueError("a validated OA service claim is required")
    return claims

