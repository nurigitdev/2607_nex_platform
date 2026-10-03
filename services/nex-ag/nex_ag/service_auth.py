from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    AdmittedServiceClaims,
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    admit_service_token_from_request,
    issue_mock_service_token,
    problem_response,
    validate_user_authorization_header,
)
from nex_ag.federated_operator_authorization import (
    authorize_ag_federated_operator_context,
    federated_authorization_telemetry_from_request,
    federated_operator_context_header,
)


AG_SERVICE_CLAIMS_STATE_KEY = "ag_service_claims"
AG_OUTBOUND_TOKEN_ENV_BY_AUDIENCE = {
    "nex-oa": "NEX_AG_TO_OA_SERVICE_TOKEN",
    "nex-ae-api": "NEX_AG_TO_AE_SERVICE_TOKEN",
    "nex-cx": "NEX_AG_TO_CX_SERVICE_TOKEN",
    "nex-mo": "NEX_AG_TO_MO_SERVICE_TOKEN",
}


@dataclass
class AgOutboundServiceTokenError(Exception):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def authorize_ag_service_request(
    request: Request,
    authorization: str | None,
    *,
    required_scopes: Sequence[str] = (DEFAULT_SERVICE_SCOPE,),
    route_class: str = "READ",
) -> JSONResponse | None:
    result = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-ag",
        required_scopes=required_scopes,
        route_class=route_class,
    )
    if isinstance(result, JSONResponse):
        return result
    setattr(request.state, AG_SERVICE_CLAIMS_STATE_KEY, result)
    return None


def authorize_ag_service_or_admin_request(
    request: Request,
    authorization: str | None,
    *,
    admin_error_code: str,
    admin_error_detail: str,
) -> JSONResponse | None:
    encoded_context = federated_operator_context_header(request)
    service_result = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-ag",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
        route_class="ADMIN" if encoded_context is not None else "READ",
    )
    if isinstance(service_result, AdmittedServiceClaims):
        setattr(request.state, AG_SERVICE_CLAIMS_STATE_KEY, service_result)
        if encoded_context is not None:
            return authorize_ag_federated_operator_context(
                request,
                service_claims=service_result,
                encoded_context=encoded_context,
                admin_error_code=admin_error_code,
                admin_error_detail=admin_error_detail,
                telemetry=federated_authorization_telemetry_from_request(request),
            )
        return None
    if _looks_like_service_authorization(authorization):
        return service_result

    user_result = validate_user_authorization_header(
        authorization,
        expected_audience="nex-ag",
        required_scopes=(DEFAULT_USER_SCOPE,),
    )
    if user_result.ok:
        roles = set(user_result.claims.roles if user_result.claims else ())
        if "admin" in roles:
            return None
        return problem_response(
            request,
            status_code=403,
            error_code=admin_error_code,
            title="Authorization failed",
            detail=admin_error_detail,
            type_uri="https://nex-platform.local/problems/authorization-failed",
        )
    return service_result


def resolve_ag_outbound_service_token(
    configured_token: str | None,
    *,
    audience: str,
    environ: Mapping[str, str] | None = None,
) -> str:
    if configured_token is not None:
        if not configured_token or configured_token != configured_token.strip():
            raise AgOutboundServiceTokenError(
                "ag.outbound_service_token_invalid",
                "configured outbound service token is invalid",
            )
        return configured_token
    env = os.environ if environ is None else environ
    profile = env.get("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "TEST_MOCK").strip().upper()
    if profile == "TEST_MOCK":
        return issue_mock_service_token(
            service_id="nex-ag", audience=audience
        ).access_token
    if profile not in {"DUAL_READ", "SIGNED_ONLY"}:
        raise AgOutboundServiceTokenError(
            "ag.service_token_rollout_profile_invalid",
            "service-token rollout profile is invalid",
        )
    env_name = AG_OUTBOUND_TOKEN_ENV_BY_AUDIENCE.get(audience)
    candidate = env.get(env_name) if env_name else None
    if candidate and candidate == candidate.strip():
        return candidate
    raise AgOutboundServiceTokenError(
        "ag.outbound_service_token_missing",
        "signed outbound service token is required",
    )


def _looks_like_service_authorization(authorization: str | None) -> bool:
    if not authorization or not authorization.startswith("Bearer "):
        return False
    token = authorization[7:]
    return token.startswith("nex-mock-service.") or token.count(".") == 2
