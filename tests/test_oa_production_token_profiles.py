from __future__ import annotations

import pytest

from nex_oa.production_token_profiles import (
    ACCESS_TOKEN_TYPE,
    DEFAULT_TOKEN_TTL_SECONDS,
    MAX_CLOCK_SKEW_SECONDS,
    PRODUCTION_TOKEN_ISSUER,
    PRODUCTION_TOKEN_PROFILES,
    get_production_token_profile,
    validate_production_token_shape,
)


def _headers(**changes: object) -> dict[str, object]:
    return {"alg": "RS256", "typ": ACCESS_TOKEN_TYPE, "kid": "key-1"} | changes


def _service_claims(**changes: object) -> dict[str, object]:
    return {
        "iss": PRODUCTION_TOKEN_ISSUER,
        "sub": "service:nex-ae-api",
        "aud": "nex-cx",
        "iat": 1_000,
        "nbf": 990,
        "exp": 1_300,
        "jti": "jti-1",
        "token_use": "service_access",
        "scope": "service:call document:read",
        "service_id": "nex-ae-api",
        "credential_id": "cred-ae-runtime",
        "credential_revision": 1,
    } | changes


def _delegated_claims(**changes: object) -> dict[str, object]:
    return {
        "iss": PRODUCTION_TOKEN_ISSUER,
        "sub": "user:tenant-1:user-1",
        "aud": "nex-cx",
        "iat": 1_000,
        "nbf": 1_000,
        "exp": 1_300,
        "jti": "jti-2",
        "token_use": "delegated_user_access",
        "scope": "workspace:use document:read",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "session_ref": "session-ref-1",
        "authorization_revision": 4,
        "azp": "nex-ae-api",
    } | changes


def test_production_token_profiles_freeze_canonical_contract() -> None:
    assert set(PRODUCTION_TOKEN_PROFILES) == {
        "service_access",
        "delegated_user_access",
    }
    service = get_production_token_profile("service_access")
    delegated = get_production_token_profile("delegated_user_access")

    assert service.default_ttl_seconds == DEFAULT_TOKEN_TTL_SECONDS == 300
    assert delegated.maximum_clock_skew_seconds == MAX_CLOCK_SKEW_SECONDS == 30
    assert service.required_headers == ("alg", "typ", "kid")
    assert "credential_revision" in service.profile_claims
    assert "credential_id" in service.profile_claims
    assert "authorization_revision" in delegated.profile_claims
    assert "roles" in delegated.forbidden_claims
    assert service.to_wire()["subject_kind"] == "service_principal"
    with pytest.raises(ValueError, match="unsupported production token profile"):
        get_production_token_profile("mock")
    with pytest.raises(ValueError):
        get_production_token_profile(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("profile", "claims"),
    [
        ("service_access", _service_claims()),
        ("delegated_user_access", _delegated_claims()),
    ],
)
def test_valid_canonical_shapes_pass(profile: str, claims: dict[str, object]) -> None:
    assert validate_production_token_shape(
        profile,
        headers=_headers(),
        claims=claims,
    ) == ()


def test_unknown_profile_and_required_fields_fail_closed() -> None:
    assert validate_production_token_shape(
        "unknown",
        headers={},
        claims={},
    ) == ("token_profile_unsupported",)

    errors = validate_production_token_shape(
        "service_access",
        headers={},
        claims={},
    )
    assert errors[:3] == (
        "header_missing:alg",
        "header_missing:typ",
        "header_missing:kid",
    )
    assert "claim_missing:credential_revision" in errors
    assert "claim_missing:credential_id" in errors


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (_headers(alg=""), "header_invalid:alg"),
        (_headers(kid=" key "), "header_invalid:kid"),
        (_headers(alg="none"), "header_alg_unsigned"),
        (_headers(typ="JWT"), "header_typ_invalid"),
    ],
)
def test_invalid_headers_are_rejected(
    headers: dict[str, object], expected: str
) -> None:
    assert expected in validate_production_token_shape(
        "service_access",
        headers=headers,
        claims=_service_claims(),
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"iss": "nex-oa"}, "claim_issuer_invalid"),
        ({"aud": "unknown"}, "claim_audience_invalid"),
        ({"token_use": "delegated_user_access"}, "claim_token_use_invalid"),
        ({"jti": 1}, "claim_invalid:jti"),
        ({"scope": "a  b"}, "claim_scope_invalid"),
        ({"scope": "a a"}, "claim_scope_invalid"),
        ({"iat": True}, "claim_invalid:iat"),
        ({"nbf": "now"}, "claim_invalid:nbf"),
        ({"exp": 1000.0}, "claim_invalid:exp"),
        ({"nbf": 1_001}, "claim_time_not_before_after_issued_at"),
        ({"exp": 1_000}, "claim_time_expiry_invalid"),
        ({"exp": 1_301}, "claim_time_ttl_exceeded"),
        ({"nbf": 969}, "claim_time_not_before_skew_exceeded"),
    ],
)
def test_common_claim_failures_are_explicit(
    changes: dict[str, object], expected: str
) -> None:
    assert expected in validate_production_token_shape(
        "service_access",
        headers=_headers(),
        claims=_service_claims(**changes),
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"service_id": ""}, "claim_invalid:service_id"),
        ({"service_id": "unknown"}, "claim_service_id_invalid"),
        ({"credential_id": ""}, "claim_invalid:credential_id"),
        ({"sub": "service:nex-cx"}, "claim_service_subject_invalid"),
        ({"credential_revision": 0}, "claim_credential_revision_invalid"),
        ({"credential_revision": True}, "claim_credential_revision_invalid"),
        ({"tenant_id": "tenant-1"}, "claim_forbidden:tenant_id"),
        ({"client_secret": "secret"}, "claim_forbidden:client_secret"),
    ],
)
def test_service_profile_failures_are_explicit(
    changes: dict[str, object], expected: str
) -> None:
    assert expected in validate_production_token_shape(
        "service_access",
        headers=_headers(),
        claims=_service_claims(**changes),
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"tenant_id": ""}, "claim_invalid:tenant_id"),
        ({"session_ref": 1}, "claim_invalid:session_ref"),
        ({"sub": "user:other:user-1"}, "claim_delegated_subject_invalid"),
        ({"azp": "external"}, "claim_authorized_party_invalid"),
        ({"authorization_revision": -1}, "claim_authorization_revision_invalid"),
        ({"roles": ["admin"]}, "claim_forbidden:roles"),
        ({"session_token": "secret"}, "claim_forbidden:session_token"),
    ],
)
def test_delegated_profile_failures_are_explicit(
    changes: dict[str, object], expected: str
) -> None:
    assert expected in validate_production_token_shape(
        "delegated_user_access",
        headers=_headers(),
        claims=_delegated_claims(**changes),
    )
