from __future__ import annotations

from collections.abc import Mapping
from secrets import token_urlsafe
from time import time
from typing import Any

from nex_oa.production_token_profiles import (
    ACCESS_TOKEN_TYPE,
    P8_DEMO_DEPLOYMENT_BOUNDARY,
    P8_DEMO_DEPLOYMENT_PROFILE,
    P8_DEMO_SERVICE_ACCESS_PROFILE,
    PRODUCTION_TOKEN_ISSUER,
    ProductionTokenProfile,
    get_production_token_profile,
    validate_production_token_shape,
)
from nex_oa.service_principal_service import OaServicePrincipalService
from nex_oa.signed_tokens import OaSignedTokenError
from nex_oa.signing_key_service import OaSigningKeyService
from nex_oa.token_signing import OaRsaSigningProvider, encode_signed_jwt


OA_TOKEN_RESPONSE_SCHEMA_VERSION = "oa_token_response.v1"


class OaClientCredentialTokenExchangeService:
    def __init__(
        self,
        *,
        principal_service: OaServicePrincipalService,
        signing_key_service: OaSigningKeyService,
        signing_provider: OaRsaSigningProvider,
        token_profile_name: str = "service_access",
    ) -> None:
        self.principal_service = principal_service
        self.signing_key_service = signing_key_service
        self.signing_provider = signing_provider
        profile = get_production_token_profile(token_profile_name)
        if profile.subject_kind != "service_principal":
            raise ValueError("token exchange profile must be a service-principal profile")
        self.token_profile = profile

    def exchange(
        self,
        payload: Mapping[str, Any],
        *,
        now_epoch: int | None = None,
        token_id: str | None = None,
    ) -> dict[str, Any]:
        _reject_unknown_fields(
            payload,
            {"grant_type", "credential_id", "client_secret", "audience", "scope"},
        )
        if payload.get("grant_type") != "client_credentials":
            raise _invalid("grant_type must be client_credentials")
        credential_id = _nonempty_string(payload.get("credential_id"), "credential_id")
        client_secret = _nonempty_string(payload.get("client_secret"), "client_secret")
        audience = _nonempty_string(payload.get("audience"), "audience")
        requested_scopes = _normalize_scope(payload.get("scope"))
        now = int(time()) if now_epoch is None else _nonnegative_integer(now_epoch, "now_epoch")

        auth = self.principal_service.authenticate_client_credential(
            credential_id,
            client_secret,
            now_epoch=now,
        )
        if audience not in auth["allowed_audiences"]:
            raise _forbidden("requested audience is not allowed")
        if not set(requested_scopes).issubset(auth["allowed_scopes"]):
            raise _forbidden("requested scope is not allowed")

        key = self.signing_key_service.active_signing_key(at_epoch=now)
        headers = {
            "alg": "RS256",
            "typ": ACCESS_TOKEN_TYPE,
            "kid": key["key_id"],
        }
        claims: dict[str, Any] = {
            "iss": PRODUCTION_TOKEN_ISSUER,
            "sub": f"service:{auth['service_id']}",
            "aud": audience,
            "iat": now,
            "nbf": now,
            "exp": now + self.token_profile.default_ttl_seconds,
            "jti": token_id or f"sat-{token_urlsafe(24)}",
            "token_use": self.token_profile.name,
            "scope": " ".join(requested_scopes),
            "service_id": auth["service_id"],
            "credential_id": auth["credential_id"],
            "credential_revision": auth["credential_revision"],
        }
        if self.token_profile.name == P8_DEMO_SERVICE_ACCESS_PROFILE:
            claims.update(
                deployment_boundary=P8_DEMO_DEPLOYMENT_BOUNDARY,
                deployment_profile=P8_DEMO_DEPLOYMENT_PROFILE,
            )
        errors = validate_production_token_shape(
            self.token_profile.name,
            headers=headers,
            claims=claims,
        )
        if errors:
            raise OaSignedTokenError(
                "oa.token_claims_invalid",
                f"issued token claims are invalid: {', '.join(errors)}",
                500,
            )
        access_token = encode_signed_jwt(
            headers=headers,
            claims=claims,
            private_key_ref=key["private_key_ref"],
            signing_provider=self.signing_provider,
        )
        return {
            "response_schema_version": OA_TOKEN_RESPONSE_SCHEMA_VERSION,
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": self.token_profile.default_ttl_seconds,
            "scope": claims["scope"],
        }


def service_token_exchange_profile_for_environment(
    environ: Mapping[str, str],
) -> ProductionTokenProfile:
    requested = str(
        environ.get("NEX_P8_DEMO_SERVICE_TOKEN_PROFILE") or ""
    ).strip()
    if not requested:
        return get_production_token_profile("service_access")
    if requested != "STARTUP_24H":
        raise ValueError("P8 Demo service-token profile is unsupported")
    if (
        str(environ.get("NEX_PROFILE") or "").strip() != P8_DEMO_DEPLOYMENT_PROFILE
        or str(environ.get("NEX_DEPLOYMENT_BOUNDARY") or "").strip()
        != P8_DEMO_DEPLOYMENT_BOUNDARY
    ):
        raise ValueError("P8 Demo service-token profile boundary is invalid")
    return get_production_token_profile(P8_DEMO_SERVICE_ACCESS_PROFILE)


def _normalize_scope(value: object) -> tuple[str, ...]:
    raw = _nonempty_string(value, "scope")
    parts = raw.split(" ")
    if any(not part or part != part.strip() for part in parts):
        raise _invalid("scope must be a space-delimited list")
    if len(parts) != len(set(parts)):
        raise _invalid("scope must not contain duplicates")
    return tuple(sorted(parts))


def _reject_unknown_fields(payload: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise _invalid(f"unsupported fields: {', '.join(unknown)}")


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _invalid(f"{field} must be a non-empty string")
    return value


def _nonnegative_integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _invalid(f"{field} must be a non-negative integer")
    return value


def _invalid(message: str) -> OaSignedTokenError:
    return OaSignedTokenError("oa.token_request_invalid", message, 400)


def _forbidden(message: str) -> OaSignedTokenError:
    return OaSignedTokenError("oa.token_request_forbidden", message, 403)
