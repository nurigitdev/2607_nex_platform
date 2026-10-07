from __future__ import annotations

from copy import deepcopy

import pytest
from nex_oa.enterprise_oidc_registration import (
    OIDC_TRUSTED_CLAIMS,
    load_oa_enterprise_oidc_registration,
    validate_enterprise_oidc_discovery,
)
from nex_oa.federated_identities import OaFederationError

ISSUER = "https://id.nex-staging.test:8443/v1/identity/oidc/provider/nex-platform"


def _environment(**changes) -> dict[str, str]:
    environment = {
        "NEX_PROFILE": "staging_live",
        "NEX_OA_BASE_URL": "https://oa.nex-staging.test:8443",
        "NEX_OA_OIDC_PROVIDER_ID": "openbao-staging",
        "NEX_OA_OIDC_ISSUER": ISSUER,
        "NEX_OA_OIDC_DISCOVERY_URL": (f"{ISSUER}/.well-known/openid-configuration"),
        "NEX_OA_OIDC_CLIENT_ID": "nex-platform-oa-staging",
        "NEX_OA_OIDC_CLIENT_SECRET_REF": (
            "secret://openbao/nex-platform/staging/nex-oa/NEX_OA_OIDC_CLIENT_SECRET@v1"
        ),
        "NEX_OA_OIDC_REDIRECT_URI": (
            "https://oa.nex-staging.test:8443/api/v1/auth/federated/callback"
        ),
        "NEX_OA_OIDC_SCOPES": "openid",
        "NEX_OA_OIDC_GRANT_TYPE": "authorization_code",
        "NEX_OA_OIDC_RESPONSE_TYPE": "code",
        "NEX_OA_OIDC_PKCE_METHOD": "S256",
        "NEX_OA_OIDC_CLIENT_AUTH_METHOD": "client_secret_basic",
    }
    environment.update(changes)
    return environment


def _discovery(**changes) -> dict:
    document = {
        "issuer": ISSUER,
        "authorization_endpoint": (
            "https://id.nex-staging.test:8443/ui/oidc/authorize"
        ),
        "token_endpoint": ("https://id.nex-staging.test:8443/v1/identity/oidc/token"),
        "jwks_uri": ("https://id.nex-staging.test:8443/v1/identity/oidc/keys"),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic"],
        "scopes_supported": ["openid"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }
    document.update(changes)
    return document


def test_loads_exact_registration_and_safe_projection() -> None:
    registration = load_oa_enterprise_oidc_registration(_environment())

    assert registration.provider_id == "openbao-staging"
    assert registration.scopes == ("openid",)
    assert registration.trusted_claims == OIDC_TRUSTED_CLAIMS
    assert registration.provider_payload(display_name="OpenBao staging") == {
        "provider_id": "openbao-staging",
        "issuer": ISSUER,
        "client_id": "nex-platform-oa-staging",
        "discovery_url": f"{ISSUER}/.well-known/openid-configuration",
        "display_name": "OpenBao staging",
        "status": "ACTIVE",
    }
    safe = registration.safe_projection()
    assert "client_secret_reference" not in safe
    assert len(safe["client_secret_reference_digest"]) == 64
    assert safe["client_secret_reference_included"] is False
    assert safe["client_secret_included"] is False


def test_validates_authorization_code_discovery_metadata() -> None:
    registration = load_oa_enterprise_oidc_registration(_environment())

    result = validate_enterprise_oidc_discovery(registration, _discovery())

    assert result["endpoint_count"] == 3
    assert result["authorization_code_supported"] is True
    assert result["pkce_s256_supported"] is True
    assert result["endpoint_origins_match"] is True


@pytest.mark.parametrize(
    "changes",
    (
        {"NEX_PROFILE": "test"},
        {"NEX_OA_OIDC_PROVIDER_ID": "UPPER"},
        {"NEX_OA_OIDC_CLIENT_ID": "bad client"},
        {"NEX_OA_OIDC_SCOPES": "openid profile"},
        {"NEX_OA_OIDC_GRANT_TYPE": "implicit"},
        {"NEX_OA_OIDC_RESPONSE_TYPE": "token"},
        {"NEX_OA_OIDC_PKCE_METHOD": "plain"},
        {"NEX_OA_OIDC_CLIENT_AUTH_METHOD": "none"},
        {"NEX_OA_OIDC_DISCOVERY_URL": ISSUER},
        {"NEX_OA_OIDC_REDIRECT_URI": "https://oa.nex-staging.test:8443/wrong"},
        {"NEX_OA_OIDC_ISSUER": "http://id.nex-staging.test/issuer"},
        {"NEX_OA_BASE_URL": "https://user:pass@oa.nex-staging.test"},
        {"NEX_OA_OIDC_REDIRECT_URI": "https://oa.nex-staging.test/cb?code=x"},
        {"NEX_OA_OIDC_ISSUER": "https://id.nex-staging.test:bad/issuer"},
        {"NEX_OA_OIDC_ISSUER": "https://id.nex-staging.test/issuer/"},
    ),
)
def test_registration_rejects_drift(changes) -> None:
    with pytest.raises(OaFederationError) as exc:
        load_oa_enterprise_oidc_registration(_environment(**changes))
    assert exc.value.error_code == "oa.enterprise_oidc_configuration_invalid"
    assert exc.value.status_code == 503


@pytest.mark.parametrize(
    "reference",
    (
        "secret://openbao/nex-platform/production/nex-oa/NEX_OA_OIDC_CLIENT_SECRET@v1",
        "secret://other/nex-platform/staging/nex-oa/NEX_OA_OIDC_CLIENT_SECRET@v1",
        "secret://user:pass@openbao/nex-platform/staging/nex-oa/NEX_OA_OIDC_CLIENT_SECRET@v1",
        "secret://openbao:8200/nex-platform/staging/nex-oa/NEX_OA_OIDC_CLIENT_SECRET@v1",
        "secret://openbao/nex-platform/staging/nex-cx/NEX_OA_OIDC_CLIENT_SECRET@v1",
        "secret://openbao/nex-platform/staging/nex-oa/NEX_OA_OIDC_CLIENT_SECRET@v0",
        "secret://openbao/nex-platform/staging/nex-oa/NEX_OA_OIDC_CLIENT_SECRET@v1?x=y",
        "secret://openbao:bad/nex-platform/staging/nex-oa/NEX_OA_OIDC_CLIENT_SECRET@v1",
    ),
)
def test_registration_rejects_unsafe_or_cross_namespace_secret_reference(
    reference,
) -> None:
    with pytest.raises(OaFederationError, match="secret reference"):
        load_oa_enterprise_oidc_registration(
            _environment(NEX_OA_OIDC_CLIENT_SECRET_REF=reference)
        )


def test_production_profile_requires_production_secret_namespace() -> None:
    registration = load_oa_enterprise_oidc_registration(
        _environment(
            NEX_PROFILE="production",
            NEX_OA_OIDC_CLIENT_SECRET_REF=(
                "secret://openbao/nex-platform/production/nex-oa/"
                "NEX_OA_OIDC_CLIENT_SECRET@v7"
            ),
        )
    )
    assert "production" in registration.client_secret_reference


@pytest.mark.parametrize(
    "changes",
    (
        {"issuer": "https://other.example.test/issuer"},
        {"authorization_endpoint": None},
        {"authorization_endpoint": "http://id.nex-staging.test/authorize"},
        {"token_endpoint": "https://other.example.test/token"},
        {"jwks_uri": "https://id.nex-staging.test:8443/keys#fragment"},
        {"response_types_supported": ["token"]},
        {"grant_types_supported": ["implicit"]},
        {"code_challenge_methods_supported": ["plain"]},
        {"token_endpoint_auth_methods_supported": ["none"]},
        {"scopes_supported": ["profile"]},
        {"id_token_signing_alg_values_supported": ["HS256"]},
    ),
)
def test_discovery_metadata_rejects_trust_drift(changes) -> None:
    registration = load_oa_enterprise_oidc_registration(_environment())
    with pytest.raises(OaFederationError) as exc:
        validate_enterprise_oidc_discovery(
            registration,
            _discovery(**deepcopy(changes)),
        )
    assert exc.value.error_code == "oa.enterprise_oidc_metadata_invalid"


def test_missing_settings_and_non_mapping_discovery_fail_closed() -> None:
    environment = _environment()
    environment.pop("NEX_OA_OIDC_CLIENT_ID")
    with pytest.raises(OaFederationError, match="missing"):
        load_oa_enterprise_oidc_registration(environment)

    registration = load_oa_enterprise_oidc_registration(_environment())
    with pytest.raises(OaFederationError, match="document"):
        validate_enterprise_oidc_discovery(registration, None)  # type: ignore[arg-type]
