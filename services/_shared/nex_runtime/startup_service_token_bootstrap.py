from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from time import time
from typing import Any

import httpx

from .canonical_platform_trust import (
    CANONICAL_PLATFORM_DEPLOYMENT_BOUNDARY,
    CANONICAL_PLATFORM_OWNERS,
    CANONICAL_PLATFORM_TRUST_GRANTS,
    SERVICE_CLIENT_SECRET_ENV,
    SERVICE_CREDENTIAL_ID_ENV,
    SERVICE_TOKEN_BOOTSTRAP_PROFILE,
    SERVICE_TOKEN_BOOTSTRAP_PROFILE_ENV,
    STARTUP_SERVICE_TOKEN_BOOTSTRAP_ENV,
    CanonicalTrustGrant,
)
from .service_token_admission import HttpOaJwksSource
from .signed_token_verifier import BoundedJwksCache, SignedServiceTokenVerifier

STARTUP_SERVICE_TOKEN_USE = "startup_service_access"
STARTUP_SERVICE_TOKEN_TTL_SECONDS = 86_400
STARTUP_SERVICE_TOKEN_BOOTSTRAP_SCHEMA_VERSION = "startup_service_token_bootstrap.v1"
INTROSPECTION_TOKEN_ENV = "NEX_OA_INTROSPECTION_SERVICE_TOKEN"


class StartupServiceTokenBootstrapError(ValueError):
    pass


@dataclass(frozen=True)
class StartupServiceTokenBootstrapEvidence:
    schema_version: str
    owner: str
    token_profile: str
    token_ttl_seconds: int
    issued_token_count: int
    audiences: tuple[str, ...]
    environment_names: tuple[str, ...]
    raw_token_values_included: bool = False
    credential_values_included: bool = False

    def to_wire(self) -> dict[str, Any]:
        result = asdict(self)
        result["audiences"] = list(self.audiences)
        result["environment_names"] = list(self.environment_names)
        return result


def startup_service_token_grants_for_owner(
    owner: str,
) -> tuple[CanonicalTrustGrant, ...]:
    if owner not in CANONICAL_PLATFORM_OWNERS:
        raise StartupServiceTokenBootstrapError("startup token owner is invalid")
    if owner == "nex-oa":
        return ()
    grants = tuple(
        grant for grant in CANONICAL_PLATFORM_TRUST_GRANTS if grant.owner == owner
    )
    return (
        *grants,
        CanonicalTrustGrant(
            INTROSPECTION_TOKEN_ENV,
            owner,
            "nex-oa",
            ("token:introspect",),
        ),
    )


def issue_startup_service_tokens(
    owner: str,
    environ: Mapping[str, str],
    *,
    requester: Callable[..., httpx.Response] = httpx.request,
    clock: Callable[[], float] = time,
) -> tuple[dict[str, str], StartupServiceTokenBootstrapEvidence]:
    _validate_boundary(owner, environ)
    process_environment = dict(environ)
    grants = startup_service_token_grants_for_owner(owner)
    if not grants:
        return process_environment, _evidence(owner, grants)

    credential_id = _secret(process_environment.get(SERVICE_CREDENTIAL_ID_ENV))
    client_secret = _secret(process_environment.get(SERVICE_CLIENT_SECRET_ENV))
    base_url = _base_url(process_environment.get("NEX_OA_BASE_URL"))
    timeout = _timeout(process_environment.get("NEX_OPENBAO_TIMEOUT_SECONDS", "10"))
    verifier = SignedServiceTokenVerifier(
        BoundedJwksCache(
            HttpOaJwksSource(
                base_url=base_url,
                timeout_seconds=timeout,
                requester=requester,
            ),
            clock=clock,
        ),
        clock=clock,
        allow_startup_profile=True,
    )
    now_epoch = int(clock())

    for grant in grants:
        response = _exchange(
            requester,
            base_url=base_url,
            timeout_seconds=timeout,
            credential_id=credential_id,
            client_secret=client_secret,
            grant=grant,
        )
        token = _token(response)
        claims = verifier.verify(
            token,
            expected_audience=grant.audience,
            required_scopes=grant.scopes,
            now_epoch=now_epoch,
        )
        if (
            claims.service_id != owner
            or claims.token_use != STARTUP_SERVICE_TOKEN_USE
            or claims.expires_at - claims.issued_at != STARTUP_SERVICE_TOKEN_TTL_SECONDS
            or response.get("expires_in") != STARTUP_SERVICE_TOKEN_TTL_SECONDS
        ):
            raise StartupServiceTokenBootstrapError(
                "startup token response is not bound to the requested profile"
            )
        process_environment[grant.environment_name] = token

    process_environment.pop(SERVICE_CREDENTIAL_ID_ENV, None)
    process_environment.pop(SERVICE_CLIENT_SECRET_ENV, None)
    return process_environment, _evidence(owner, grants)


def _exchange(
    requester: Callable[..., httpx.Response],
    *,
    base_url: str,
    timeout_seconds: float,
    credential_id: str,
    client_secret: str,
    grant: CanonicalTrustGrant,
) -> Mapping[str, Any]:
    try:
        response = requester(
            "POST",
            f"{base_url.rstrip('/')}/api/v1/auth/service-token",
            headers={"Accept": "application/json"},
            json={
                "grant_type": "client_credentials",
                "credential_id": credential_id,
                "client_secret": client_secret,
                "audience": grant.audience,
                "scope": " ".join(grant.scopes),
            },
            timeout=timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise StartupServiceTokenBootstrapError(
            "OA startup token endpoint is unavailable"
        ) from exc
    if response.status_code >= 400:
        raise StartupServiceTokenBootstrapError("OA startup token request was rejected")
    try:
        payload = response.json()
    except ValueError as exc:
        raise StartupServiceTokenBootstrapError(
            "OA startup token response is invalid"
        ) from exc
    if not isinstance(payload, Mapping):
        raise StartupServiceTokenBootstrapError("OA startup token response is invalid")
    return payload


def _validate_boundary(owner: str, environ: Mapping[str, str]) -> None:
    if owner not in CANONICAL_PLATFORM_OWNERS:
        raise StartupServiceTokenBootstrapError("startup token owner is invalid")
    expected = {
        STARTUP_SERVICE_TOKEN_BOOTSTRAP_ENV: "true",
        "NEX_PROFILE": "staging_live",
        "NEX_DEPLOYMENT_BOUNDARY": CANONICAL_PLATFORM_DEPLOYMENT_BOUNDARY,
        SERVICE_TOKEN_BOOTSTRAP_PROFILE_ENV: SERVICE_TOKEN_BOOTSTRAP_PROFILE,
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
    }
    for name, value in expected.items():
        if str(environ.get(name) or "").strip() != value:
            raise StartupServiceTokenBootstrapError(
                f"startup token boundary is invalid: {name}"
            )


def _evidence(
    owner: str,
    grants: tuple[CanonicalTrustGrant, ...],
) -> StartupServiceTokenBootstrapEvidence:
    return StartupServiceTokenBootstrapEvidence(
        schema_version=STARTUP_SERVICE_TOKEN_BOOTSTRAP_SCHEMA_VERSION,
        owner=owner,
        token_profile=SERVICE_TOKEN_BOOTSTRAP_PROFILE,
        token_ttl_seconds=STARTUP_SERVICE_TOKEN_TTL_SECONDS,
        issued_token_count=len(grants),
        audiences=tuple(grant.audience for grant in grants),
        environment_names=tuple(grant.environment_name for grant in grants),
    )


def _token(payload: Mapping[str, Any]) -> str:
    token = payload.get("access_token")
    if not isinstance(token, str) or not token or token != token.strip():
        raise StartupServiceTokenBootstrapError("OA startup token response is invalid")
    return token


def _secret(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise StartupServiceTokenBootstrapError("startup service credential is invalid")
    return value


def _base_url(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("https://"):
        raise StartupServiceTokenBootstrapError("OA base URL is invalid")
    return value.rstrip("/")


def _timeout(value: object) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise StartupServiceTokenBootstrapError(
            "startup token timeout is invalid"
        ) from exc
    if timeout <= 0 or timeout > 60:
        raise StartupServiceTokenBootstrapError("startup token timeout is invalid")
    return timeout
