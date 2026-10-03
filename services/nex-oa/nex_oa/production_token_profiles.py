from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Any


PRODUCTION_TOKEN_ISSUER = "urn:nex-platform:oa"
ACCESS_TOKEN_TYPE = "at+jwt"
DEFAULT_TOKEN_TTL_SECONDS = 300
MAX_CLOCK_SKEW_SECONDS = 30
TOKEN_AUDIENCES = frozenset(
    {"nex-oa", "nex-ag", "nex-ae-api", "nex-cx", "nex-mo"}
)
COMMON_REQUIRED_HEADERS = ("alg", "typ", "kid")
COMMON_REQUIRED_CLAIMS = (
    "iss",
    "sub",
    "aud",
    "iat",
    "nbf",
    "exp",
    "jti",
    "token_use",
    "scope",
)
SENSITIVE_FORBIDDEN_CLAIMS = (
    "password",
    "client_secret",
    "credential_secret",
    "private_key",
    "session_token",
)


@dataclass(frozen=True)
class ProductionTokenProfile:
    name: str
    subject_kind: str
    default_ttl_seconds: int
    maximum_ttl_seconds: int
    maximum_clock_skew_seconds: int
    required_headers: tuple[str, ...]
    required_claims: tuple[str, ...]
    profile_claims: tuple[str, ...]
    forbidden_claims: tuple[str, ...]

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


_SERVICE_ACCESS = ProductionTokenProfile(
    name="service_access",
    subject_kind="service_principal",
    default_ttl_seconds=DEFAULT_TOKEN_TTL_SECONDS,
    maximum_ttl_seconds=DEFAULT_TOKEN_TTL_SECONDS,
    maximum_clock_skew_seconds=MAX_CLOCK_SKEW_SECONDS,
    required_headers=COMMON_REQUIRED_HEADERS,
    required_claims=COMMON_REQUIRED_CLAIMS,
    profile_claims=("service_id", "credential_id", "credential_revision"),
    forbidden_claims=(
        *SENSITIVE_FORBIDDEN_CLAIMS,
        "tenant_id",
        "user_id",
        "session_ref",
        "authorization_revision",
        "azp",
    ),
)
_DELEGATED_USER_ACCESS = ProductionTokenProfile(
    name="delegated_user_access",
    subject_kind="tenant_user",
    default_ttl_seconds=DEFAULT_TOKEN_TTL_SECONDS,
    maximum_ttl_seconds=DEFAULT_TOKEN_TTL_SECONDS,
    maximum_clock_skew_seconds=MAX_CLOCK_SKEW_SECONDS,
    required_headers=COMMON_REQUIRED_HEADERS,
    required_claims=COMMON_REQUIRED_CLAIMS,
    profile_claims=(
        "tenant_id",
        "user_id",
        "session_ref",
        "authorization_revision",
        "azp",
    ),
    forbidden_claims=(
        *SENSITIVE_FORBIDDEN_CLAIMS,
        "service_id",
        "credential_revision",
        "roles",
        "groups",
    ),
)
PRODUCTION_TOKEN_PROFILES: Mapping[str, ProductionTokenProfile] = MappingProxyType(
    {
        _SERVICE_ACCESS.name: _SERVICE_ACCESS,
        _DELEGATED_USER_ACCESS.name: _DELEGATED_USER_ACCESS,
    }
)


def get_production_token_profile(name: str) -> ProductionTokenProfile:
    try:
        return PRODUCTION_TOKEN_PROFILES[name]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unsupported production token profile: {name}") from exc


def validate_production_token_shape(
    profile_name: str,
    *,
    headers: Mapping[str, Any],
    claims: Mapping[str, Any],
) -> tuple[str, ...]:
    try:
        profile = get_production_token_profile(profile_name)
    except ValueError:
        return ("token_profile_unsupported",)

    errors: list[str] = []
    _validate_required_fields(
        headers,
        profile.required_headers,
        "header",
        errors,
    )
    _validate_required_fields(
        claims,
        (*profile.required_claims, *profile.profile_claims),
        "claim",
        errors,
    )
    _validate_headers(headers, errors)
    _validate_common_claims(profile, claims, errors)
    _validate_profile_claims(profile, claims, errors)
    for claim in profile.forbidden_claims:
        if claim in claims:
            errors.append(f"claim_forbidden:{claim}")
    return tuple(errors)


def _validate_required_fields(
    values: Mapping[str, Any],
    names: tuple[str, ...],
    kind: str,
    errors: list[str],
) -> None:
    for name in names:
        if name not in values:
            errors.append(f"{kind}_missing:{name}")


def _validate_headers(headers: Mapping[str, Any], errors: list[str]) -> None:
    for name in COMMON_REQUIRED_HEADERS:
        if name in headers and not _nonempty_string(headers[name]):
            errors.append(f"header_invalid:{name}")
    if headers.get("alg") == "none":
        errors.append("header_alg_unsigned")
    if "typ" in headers and headers.get("typ") != ACCESS_TOKEN_TYPE:
        errors.append("header_typ_invalid")


def _validate_common_claims(
    profile: ProductionTokenProfile,
    claims: Mapping[str, Any],
    errors: list[str],
) -> None:
    for name in ("iss", "sub", "aud", "jti", "token_use", "scope"):
        if name in claims and not _nonempty_string(claims[name]):
            errors.append(f"claim_invalid:{name}")
    if "iss" in claims and claims.get("iss") != PRODUCTION_TOKEN_ISSUER:
        errors.append("claim_issuer_invalid")
    if "aud" in claims and claims.get("aud") not in TOKEN_AUDIENCES:
        errors.append("claim_audience_invalid")
    if "token_use" in claims and claims.get("token_use") != profile.name:
        errors.append("claim_token_use_invalid")
    if "scope" in claims and _nonempty_string(claims["scope"]):
        scopes = claims["scope"].split(" ")
        if (
            any(not scope for scope in scopes)
            or len(scopes) != len(set(scopes))
            or any(scope != scope.strip() for scope in scopes)
        ):
            errors.append("claim_scope_invalid")

    numeric_names = ("iat", "nbf", "exp")
    for name in numeric_names:
        if name in claims and not _integer(claims[name]):
            errors.append(f"claim_invalid:{name}")
    if all(_integer(claims.get(name)) for name in numeric_names):
        issued_at = claims["iat"]
        not_before = claims["nbf"]
        expires_at = claims["exp"]
        if not_before > issued_at:
            errors.append("claim_time_not_before_after_issued_at")
        if issued_at >= expires_at:
            errors.append("claim_time_expiry_invalid")
        if expires_at - issued_at > profile.maximum_ttl_seconds:
            errors.append("claim_time_ttl_exceeded")
        if issued_at - not_before > profile.maximum_clock_skew_seconds:
            errors.append("claim_time_not_before_skew_exceeded")


def _validate_profile_claims(
    profile: ProductionTokenProfile,
    claims: Mapping[str, Any],
    errors: list[str],
) -> None:
    if profile.name == "service_access":
        _validate_string_claims(claims, ("service_id", "credential_id"), errors)
        service_id = claims.get("service_id")
        if _nonempty_string(service_id) and service_id not in TOKEN_AUDIENCES:
            errors.append("claim_service_id_invalid")
        if _nonempty_string(service_id) and claims.get("sub") != f"service:{service_id}":
            errors.append("claim_service_subject_invalid")
        if "credential_revision" in claims and not _positive_integer(
            claims["credential_revision"]
        ):
            errors.append("claim_credential_revision_invalid")
        return

    string_claims = ("tenant_id", "user_id", "session_ref", "azp")
    _validate_string_claims(claims, string_claims, errors)
    tenant_id = claims.get("tenant_id")
    user_id = claims.get("user_id")
    if (
        _nonempty_string(tenant_id)
        and _nonempty_string(user_id)
        and claims.get("sub") != f"user:{tenant_id}:{user_id}"
    ):
        errors.append("claim_delegated_subject_invalid")
    if _nonempty_string(claims.get("azp")) and claims.get("azp") not in TOKEN_AUDIENCES:
        errors.append("claim_authorized_party_invalid")
    if "authorization_revision" in claims and not _positive_integer(
        claims["authorization_revision"]
    ):
        errors.append("claim_authorization_revision_invalid")


def _validate_string_claims(
    claims: Mapping[str, Any],
    names: tuple[str, ...],
    errors: list[str],
) -> None:
    for name in names:
        if name in claims and not _nonempty_string(claims[name]):
            errors.append(f"claim_invalid:{name}")


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive_integer(value: Any) -> bool:
    return _integer(value) and value > 0
