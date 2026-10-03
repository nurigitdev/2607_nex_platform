from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


JWKS_CACHE_TTL_SECONDS = 300
UNKNOWN_KID_REFRESH_ATTEMPTS = 1
INTROSPECTION_TIMEOUT_SECONDS = 3
ROUTE_CLASSES = ("READ", "WRITE", "ADMIN", "CREDENTIAL", "KEY_MANAGEMENT")
REVOCATION_SENSITIVE_ROUTE_CLASSES = frozenset(
    {"WRITE", "ADMIN", "CREDENTIAL", "KEY_MANAGEMENT"}
)
LOCAL_VALIDATION_CHECKS = (
    "allowed_algorithm",
    "known_kid_and_signature",
    "type",
    "issuer",
    "audience",
    "token_use",
    "issued_not_before_expiry",
    "required_scope",
)
LOCAL_STATUSES = (
    "valid",
    "invalid_signature",
    "expired",
    "unknown_kid_after_refresh",
    "claim_invalid",
)
INTROSPECTION_STATUSES = ("active", "inactive", "unavailable", "not_requested")


@dataclass(frozen=True)
class TokenValidationPolicy:
    jwks_cache_ttl_seconds: int
    unknown_kid_refresh_attempts: int
    introspection_timeout_seconds: int
    local_validation_checks: tuple[str, ...]
    revocation_sensitive_route_classes: tuple[str, ...]
    stale_jwks_acceptance_allowed: bool
    introspection_error_acceptance_allowed: bool
    raw_token_logging_allowed: bool

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TokenValidationDecision:
    accepted: bool
    http_status: int
    reason_code: str
    introspection_required: bool

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


PRODUCTION_TOKEN_VALIDATION_POLICY = TokenValidationPolicy(
    jwks_cache_ttl_seconds=JWKS_CACHE_TTL_SECONDS,
    unknown_kid_refresh_attempts=UNKNOWN_KID_REFRESH_ATTEMPTS,
    introspection_timeout_seconds=INTROSPECTION_TIMEOUT_SECONDS,
    local_validation_checks=LOCAL_VALIDATION_CHECKS,
    revocation_sensitive_route_classes=tuple(
        sorted(REVOCATION_SENSITIVE_ROUTE_CLASSES)
    ),
    stale_jwks_acceptance_allowed=False,
    introspection_error_acceptance_allowed=False,
    raw_token_logging_allowed=False,
)


def build_token_validation_plan(
    *,
    route_class: str,
    kid_known: bool,
    jwks_cache_age_seconds: int,
) -> dict[str, Any]:
    _validate_route_class(route_class)
    if not isinstance(kid_known, bool):
        raise ValueError("kid_known must be a boolean")
    if not _nonnegative_integer(jwks_cache_age_seconds):
        raise ValueError("jwks_cache_age_seconds must be a non-negative integer")
    refresh_required = (
        not kid_known or jwks_cache_age_seconds > JWKS_CACHE_TTL_SECONDS
    )
    return {
        "route_class": route_class,
        "local_checks": LOCAL_VALIDATION_CHECKS,
        "jwks_refresh_required": refresh_required,
        "jwks_refresh_attempts": (
            UNKNOWN_KID_REFRESH_ATTEMPTS if refresh_required else 0
        ),
        "stale_cache_accepted_after_refresh_failure": False,
        "introspection_required": (
            route_class in REVOCATION_SENSITIVE_ROUTE_CLASSES
        ),
        "introspection_timeout_seconds": INTROSPECTION_TIMEOUT_SECONDS,
        "introspection_binding_checks": (
            "active",
            "issuer",
            "audience",
            "subject",
            "token_use",
            "jti",
            "credential_or_authorization_revision",
        ),
    }


def evaluate_token_validation(
    *,
    route_class: str,
    local_status: str,
    scope_satisfied: bool,
    introspection_status: str,
) -> TokenValidationDecision:
    _validate_route_class(route_class)
    if local_status not in LOCAL_STATUSES:
        raise ValueError(f"unsupported local validation status: {local_status}")
    if not isinstance(scope_satisfied, bool):
        raise ValueError("scope_satisfied must be a boolean")
    if introspection_status not in INTROSPECTION_STATUSES:
        raise ValueError(
            f"unsupported introspection status: {introspection_status}"
        )
    introspection_required = route_class in REVOCATION_SENSITIVE_ROUTE_CLASSES
    if local_status != "valid":
        return TokenValidationDecision(
            accepted=False,
            http_status=401,
            reason_code=f"token_{local_status}",
            introspection_required=introspection_required,
        )
    if not scope_satisfied:
        return TokenValidationDecision(
            accepted=False,
            http_status=403,
            reason_code="token_scope_insufficient",
            introspection_required=introspection_required,
        )
    if introspection_required:
        if introspection_status == "active":
            return _accepted(introspection_required=True)
        if introspection_status == "inactive":
            return TokenValidationDecision(
                accepted=False,
                http_status=401,
                reason_code="token_introspection_inactive",
                introspection_required=True,
            )
        return TokenValidationDecision(
            accepted=False,
            http_status=503,
            reason_code="token_introspection_required_unavailable",
            introspection_required=True,
        )
    if introspection_status == "inactive":
        return TokenValidationDecision(
            accepted=False,
            http_status=401,
            reason_code="token_introspection_inactive",
            introspection_required=False,
        )
    if introspection_status == "unavailable":
        return TokenValidationDecision(
            accepted=False,
            http_status=503,
            reason_code="token_introspection_unavailable",
            introspection_required=False,
        )
    return _accepted(introspection_required=False)


def _accepted(*, introspection_required: bool) -> TokenValidationDecision:
    return TokenValidationDecision(
        accepted=True,
        http_status=200,
        reason_code="token_accepted",
        introspection_required=introspection_required,
    )


def _validate_route_class(route_class: str) -> None:
    if route_class not in ROUTE_CLASSES:
        raise ValueError(f"unsupported route class: {route_class}")


def _nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
