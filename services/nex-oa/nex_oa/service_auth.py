from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from time import time
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    AdmittedServiceClaims,
    BoundedJwksCache,
    DEFAULT_SERVICE_SCOPE,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    admit_service_token_from_request,
)
from nex_oa.signing_key_service import OaSigningKeyService
from nex_oa.token_validation_service import OaSignedTokenValidationService

OA_SERVICE_CLAIMS_STATE_KEY = "oa_service_claims"
OA_OPERATIONS_READ_SCOPE = "operations:read"


@dataclass(frozen=True)
class LocalOaJwksSource:
    signing_key_service: OaSigningKeyService

    def fetch_jwks(self) -> Mapping[str, Any]:
        return self.signing_key_service.jwks()


@dataclass(frozen=True)
class LocalOaTokenIntrospector:
    validation_service: OaSignedTokenValidationService

    def introspect(
        self,
        token: str,
        *,
        expected_audience: str,
        required_scopes: Sequence[str],
    ) -> Mapping[str, Any]:
        return self.validation_service.introspect(
            token,
            expected_audience=expected_audience,
            required_scopes=required_scopes,
        )


def build_oa_local_service_token_admission(
    *,
    signing_key_service: OaSigningKeyService,
    validation_service: OaSignedTokenValidationService,
    environ: Mapping[str, str] | None = None,
    clock: Callable[[], float] = time,
) -> ServiceTokenAdmissionRuntime:
    env = os.environ if environ is None else environ
    profile = env.get("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "TEST_MOCK").strip().upper()
    if profile == "TEST_MOCK":
        return ServiceTokenAdmissionRuntime(
            expected_audience="nex-oa",
            rollout_profile=profile,
            clock=clock,
        )
    verifier = SignedServiceTokenVerifier(
        BoundedJwksCache(LocalOaJwksSource(signing_key_service), clock=clock),
        clock=clock,
    )
    callers = tuple(
        item.strip()
        for item in env.get("NEX_LEGACY_MOCK_CALLERS", "").split(",")
        if item.strip()
    )
    raw_deadline = env.get("NEX_MOCK_COMPATIBILITY_DEADLINE_EPOCH")
    try:
        deadline = int(raw_deadline) if raw_deadline is not None else None
    except ValueError as exc:
        raise ValueError("mock compatibility deadline must be an integer") from exc
    return ServiceTokenAdmissionRuntime(
        expected_audience="nex-oa",
        rollout_profile=profile,
        signed_verifier=verifier,
        introspector=LocalOaTokenIntrospector(validation_service),
        legacy_mock_callers=callers,
        compatibility_deadline_epoch=deadline,
        clock=clock,
    )


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


def authorize_oa_operations_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-oa",
        required_scopes=(DEFAULT_SERVICE_SCOPE, OA_OPERATIONS_READ_SCOPE),
        route_class="ADMIN",
    )
    if isinstance(result, JSONResponse):
        return result
    if result.service_id != "nex-ag":
        from nex_runtime import problem_response

        return problem_response(
            request,
            status_code=403,
            error_code="OA_OPERATIONS_CALLER_FORBIDDEN",
            title="Authorization failed",
            detail="OA trace operations are available only to NeX-AG.",
            type_uri="https://nex-platform.local/problems/authorization-failed",
        )
    setattr(request.state, OA_SERVICE_CLAIMS_STATE_KEY, result)
    return None


def authenticated_oa_service_claims(request: Request) -> AdmittedServiceClaims:
    claims = getattr(request.state, OA_SERVICE_CLAIMS_STATE_KEY, None)
    if not isinstance(claims, AdmittedServiceClaims):
        raise ValueError("a validated OA service claim is required")
    return claims
