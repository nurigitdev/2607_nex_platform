from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

MOCK_SERVICE_TOKEN_PREFIX = "nex-mock-service."
MOCK_USER_TOKEN_PREFIX = "nex-mock-user."
MOCK_SERVICE_TOKEN_ISSUER = "nex-oa"
KNOWN_SERVICE_IDS = {
    "nex-oa",
    "nex-ag",
    "nex-ae-api",
    "nex-cx",
    "nex-mo",
}
DEFAULT_SERVICE_SCOPE = "service:call"
DEFAULT_USER_SCOPE = "workspace:use"


@dataclass(frozen=True)
class ServiceClaims:
    issuer: str
    subject: str
    audience: str
    service_id: str
    scopes: tuple[str, ...]
    issued_at: str
    expires_at: str
    token_use: str = "service"

    def to_wire(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer,
            "subject": self.subject,
            "audience": self.audience,
            "service_id": self.service_id,
            "scopes": list(self.scopes),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "token_use": self.token_use,
        }

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> "ServiceClaims":
        scopes = payload["scopes"]
        if not isinstance(scopes, list) or not all(
            isinstance(scope, str) for scope in scopes
        ):
            raise ValueError("scopes must be a list of strings")

        return cls(
            issuer=_require_string(payload, "issuer"),
            subject=_require_string(payload, "subject"),
            audience=_require_string(payload, "audience"),
            service_id=_require_string(payload, "service_id"),
            scopes=tuple(scopes),
            issued_at=_require_string(payload, "issued_at"),
            expires_at=_require_string(payload, "expires_at"),
            token_use=_require_string(payload, "token_use"),
        )


@dataclass(frozen=True)
class UserClaims:
    issuer: str
    subject: str
    audience: str
    tenant_id: str
    user_id: str
    scopes: tuple[str, ...]
    roles: tuple[str, ...]
    issued_at: str
    expires_at: str
    token_use: str = "user"

    def to_wire(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer,
            "subject": self.subject,
            "audience": self.audience,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "scopes": list(self.scopes),
            "roles": list(self.roles),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "token_use": self.token_use,
        }

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> "UserClaims":
        scopes = payload["scopes"]
        if not isinstance(scopes, list) or not all(
            isinstance(scope, str) for scope in scopes
        ):
            raise ValueError("scopes must be a list of strings")
        roles = payload.get("roles", [])
        if not isinstance(roles, list) or not all(
            isinstance(role, str) for role in roles
        ):
            raise ValueError("roles must be a list of strings")

        return cls(
            issuer=_require_string(payload, "issuer"),
            subject=_require_string(payload, "subject"),
            audience=_require_string(payload, "audience"),
            tenant_id=_require_string(payload, "tenant_id"),
            user_id=_require_string(payload, "user_id"),
            scopes=tuple(scopes),
            roles=tuple(roles),
            issued_at=_require_string(payload, "issued_at"),
            expires_at=_require_string(payload, "expires_at"),
            token_use=_require_string(payload, "token_use"),
        )


@dataclass(frozen=True)
class IssuedServiceToken:
    access_token: str
    claims: ServiceClaims


@dataclass(frozen=True)
class IssuedUserToken:
    access_token: str
    claims: UserClaims


@dataclass(frozen=True)
class ClaimValidationResult:
    ok: bool
    claims: ServiceClaims | None = None
    error_code: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class UserClaimValidationResult:
    ok: bool
    claims: UserClaims | None = None
    error_code: str | None = None
    detail: str | None = None


def issue_mock_service_token(
    *,
    service_id: str,
    audience: str,
    scopes: list[str] | tuple[str, ...] | None = None,
    issued_at: datetime | None = None,
    ttl_seconds: int = 3600,
) -> IssuedServiceToken:
    if service_id not in KNOWN_SERVICE_IDS:
        raise ValueError(f"unknown service_id: {service_id}")
    if audience not in KNOWN_SERVICE_IDS:
        raise ValueError(f"unknown audience: {audience}")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")

    issued = issued_at or datetime.now(UTC)
    expires = issued + timedelta(seconds=ttl_seconds)
    claim_scopes = tuple(scopes or [DEFAULT_SERVICE_SCOPE])
    claims = ServiceClaims(
        issuer=MOCK_SERVICE_TOKEN_ISSUER,
        subject=f"service:{service_id}",
        audience=audience,
        service_id=service_id,
        scopes=claim_scopes,
        issued_at=_format_utc(issued),
        expires_at=_format_utc(expires),
    )
    payload = _encode_payload(claims.to_wire())
    return IssuedServiceToken(
        access_token=f"{MOCK_SERVICE_TOKEN_PREFIX}{payload}",
        claims=claims,
    )


def issue_mock_user_token(
    *,
    tenant_id: str,
    user_id: str,
    audience: str = "nex-ae-api",
    scopes: list[str] | tuple[str, ...] | None = None,
    roles: list[str] | tuple[str, ...] | None = None,
    issued_at: datetime | None = None,
    ttl_seconds: int = 3600,
) -> IssuedUserToken:
    if audience not in KNOWN_SERVICE_IDS:
        raise ValueError(f"unknown audience: {audience}")
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if not user_id:
        raise ValueError("user_id is required")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")

    issued = issued_at or datetime.now(UTC)
    expires = issued + timedelta(seconds=ttl_seconds)
    claim_scopes = tuple(scopes or [DEFAULT_USER_SCOPE])
    claim_roles = tuple(roles or [])
    claims = UserClaims(
        issuer=MOCK_SERVICE_TOKEN_ISSUER,
        subject=f"user:{tenant_id}:{user_id}",
        audience=audience,
        tenant_id=tenant_id,
        user_id=user_id,
        scopes=claim_scopes,
        roles=claim_roles,
        issued_at=_format_utc(issued),
        expires_at=_format_utc(expires),
    )
    payload = _encode_payload(claims.to_wire())
    return IssuedUserToken(
        access_token=f"{MOCK_USER_TOKEN_PREFIX}{payload}",
        claims=claims,
    )


def validate_authorization_header(
    authorization: str | None,
    *,
    expected_audience: str | None = None,
    required_scopes: list[str] | tuple[str, ...] = (),
    now: datetime | None = None,
) -> ClaimValidationResult:
    if not authorization:
        return ClaimValidationResult(
            ok=False,
            error_code="AUTHORIZATION_HEADER_MISSING",
            detail="Authorization header is required.",
        )

    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return ClaimValidationResult(
            ok=False,
            error_code="AUTHORIZATION_HEADER_INVALID",
            detail="Authorization header must use the Bearer scheme.",
        )

    return validate_mock_service_token(
        authorization[len(prefix) :],
        expected_audience=expected_audience,
        required_scopes=required_scopes,
        now=now,
    )


def validate_user_authorization_header(
    authorization: str | None,
    *,
    expected_audience: str | None = None,
    required_scopes: list[str] | tuple[str, ...] = (),
    now: datetime | None = None,
) -> UserClaimValidationResult:
    if not authorization:
        return UserClaimValidationResult(
            ok=False,
            error_code="AUTHORIZATION_HEADER_MISSING",
            detail="Authorization header is required.",
        )

    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return UserClaimValidationResult(
            ok=False,
            error_code="AUTHORIZATION_HEADER_INVALID",
            detail="Authorization header must use the Bearer scheme.",
        )

    return validate_mock_user_token(
        authorization[len(prefix) :],
        expected_audience=expected_audience,
        required_scopes=required_scopes,
        now=now,
    )


def validate_mock_service_token(
    token: str,
    *,
    expected_audience: str | None = None,
    required_scopes: list[str] | tuple[str, ...] = (),
    now: datetime | None = None,
) -> ClaimValidationResult:
    try:
        claims = _decode_claims(token)
    except ValueError as exc:
        return ClaimValidationResult(
            ok=False,
            error_code="TOKEN_FORMAT_INVALID",
            detail=str(exc),
        )

    static_failure = _validate_static_claims(claims, expected_audience, required_scopes)
    if static_failure is not None:
        return static_failure

    temporal_failure = _validate_temporal_claims(claims, now or datetime.now(UTC))
    if temporal_failure is not None:
        return temporal_failure

    return ClaimValidationResult(ok=True, claims=claims)


def validate_mock_user_token(
    token: str,
    *,
    expected_audience: str | None = None,
    required_scopes: list[str] | tuple[str, ...] = (),
    now: datetime | None = None,
) -> UserClaimValidationResult:
    try:
        claims = _decode_user_claims(token)
    except ValueError as exc:
        return UserClaimValidationResult(
            ok=False,
            error_code="TOKEN_FORMAT_INVALID",
            detail=str(exc),
        )

    static_failure = _validate_static_user_claims(
        claims,
        expected_audience,
        required_scopes,
    )
    if static_failure is not None:
        return static_failure

    temporal_failure = _validate_temporal_user_claims(claims, now or datetime.now(UTC))
    if temporal_failure is not None:
        return temporal_failure

    return UserClaimValidationResult(ok=True, claims=claims)


def _validate_static_claims(
    claims: ServiceClaims,
    expected_audience: str | None,
    required_scopes: list[str] | tuple[str, ...],
) -> ClaimValidationResult | None:
    if claims.issuer != MOCK_SERVICE_TOKEN_ISSUER:
        return _claim_failure("TOKEN_ISSUER_INVALID", "Token issuer is not trusted.")
    if claims.token_use != "service":
        return _claim_failure("TOKEN_USE_INVALID", "Token is not a service token.")
    if claims.service_id not in KNOWN_SERVICE_IDS:
        return _claim_failure("SERVICE_ID_INVALID", "Service ID is not recognized.")
    if claims.subject != f"service:{claims.service_id}":
        return _claim_failure("TOKEN_SUBJECT_INVALID", "Token subject does not match service_id.")
    if expected_audience is not None and claims.audience != expected_audience:
        return _claim_failure("TOKEN_AUDIENCE_INVALID", "Token audience does not match.")

    missing_scopes = sorted(set(required_scopes) - set(claims.scopes))
    if missing_scopes:
        return _claim_failure(
            "TOKEN_SCOPE_MISSING",
            f"Token is missing required scope: {missing_scopes[0]}",
        )

    return None


def _validate_static_user_claims(
    claims: UserClaims,
    expected_audience: str | None,
    required_scopes: list[str] | tuple[str, ...],
) -> UserClaimValidationResult | None:
    if claims.issuer != MOCK_SERVICE_TOKEN_ISSUER:
        return _user_claim_failure("TOKEN_ISSUER_INVALID", "Token issuer is not trusted.")
    if claims.token_use != "user":
        return _user_claim_failure("TOKEN_USE_INVALID", "Token is not a user token.")
    if claims.audience not in KNOWN_SERVICE_IDS:
        return _user_claim_failure("TOKEN_AUDIENCE_INVALID", "Token audience is not recognized.")
    if claims.subject != f"user:{claims.tenant_id}:{claims.user_id}":
        return _user_claim_failure("TOKEN_SUBJECT_INVALID", "Token subject does not match user.")
    if expected_audience is not None and claims.audience != expected_audience:
        return _user_claim_failure("TOKEN_AUDIENCE_INVALID", "Token audience does not match.")

    missing_scopes = sorted(set(required_scopes) - set(claims.scopes))
    if missing_scopes:
        return _user_claim_failure(
            "TOKEN_SCOPE_MISSING",
            f"Token is missing required scope: {missing_scopes[0]}",
        )

    return None


def _validate_temporal_claims(
    claims: ServiceClaims,
    now: datetime,
) -> ClaimValidationResult | None:
    issued_at = _parse_utc(claims.issued_at)
    expires_at = _parse_utc(claims.expires_at)
    if issued_at > now:
        return _claim_failure("TOKEN_NOT_YET_VALID", "Token issued_at is in the future.")
    if expires_at <= now:
        return _claim_failure("TOKEN_EXPIRED", "Token has expired.")
    return None


def _validate_temporal_user_claims(
    claims: UserClaims,
    now: datetime,
) -> UserClaimValidationResult | None:
    issued_at = _parse_utc(claims.issued_at)
    expires_at = _parse_utc(claims.expires_at)
    if issued_at > now:
        return _user_claim_failure("TOKEN_NOT_YET_VALID", "Token issued_at is in the future.")
    if expires_at <= now:
        return _user_claim_failure("TOKEN_EXPIRED", "Token has expired.")
    return None


def _decode_claims(token: str) -> ServiceClaims:
    if not token.startswith(MOCK_SERVICE_TOKEN_PREFIX):
        raise ValueError("token prefix is not a mock service token")

    payload = token[len(MOCK_SERVICE_TOKEN_PREFIX) :]
    try:
        decoded = _decode_payload(payload)
        if not isinstance(decoded, dict):
            raise ValueError("token payload must be an object")
        return ServiceClaims.from_wire(decoded)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"token payload is invalid: {exc}") from exc


def _decode_user_claims(token: str) -> UserClaims:
    if not token.startswith(MOCK_USER_TOKEN_PREFIX):
        raise ValueError("token prefix is not a mock user token")

    payload = token[len(MOCK_USER_TOKEN_PREFIX) :]
    try:
        decoded = _decode_payload(payload)
        if not isinstance(decoded, dict):
            raise ValueError("token payload must be an object")
        return UserClaims.from_wire(decoded)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"token payload is invalid: {exc}") from exc


def _encode_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_payload(payload: str) -> Any:
    padding = "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(f"{payload}{padding}").decode("utf-8"))


def _claim_failure(error_code: str, detail: str) -> ClaimValidationResult:
    return ClaimValidationResult(ok=False, error_code=error_code, detail=detail)


def _user_claim_failure(error_code: str, detail: str) -> UserClaimValidationResult:
    return UserClaimValidationResult(ok=False, error_code=error_code, detail=detail)


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
