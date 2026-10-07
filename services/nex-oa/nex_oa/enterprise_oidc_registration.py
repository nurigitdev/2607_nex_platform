from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit

from nex_oa.federated_identities import OaFederationError

OIDC_REGISTRATION_SCHEMA_VERSION = "oa_enterprise_oidc_registration.v1"
OIDC_GRANT_TYPE = "authorization_code"
OIDC_RESPONSE_TYPE = "code"
OIDC_PKCE_METHOD = "S256"
OIDC_CLIENT_AUTH_METHOD = "client_secret_basic"
OIDC_SCOPES = ("openid",)
OIDC_TRUSTED_CLAIMS = (
    "iss",
    "sub",
    "aud",
    "azp",
    "iat",
    "exp",
    "nbf",
    "nonce",
)
OIDC_CALLBACK_PATH = "/api/v1/auth/federated/callback"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9._-]{1,127}$")
_SECRET_REFERENCE = re.compile(
    r"^/nex-platform/(?P<namespace>staging|production)/nex-oa/"
    r"NEX_OA_OIDC_CLIENT_SECRET@v[1-9][0-9]*$"
)


@dataclass(frozen=True)
class OaEnterpriseOidcRegistration:
    registration_schema_version: str
    provider_id: str
    issuer: str
    discovery_url: str
    client_id: str
    client_secret_reference: str
    redirect_uri: str
    scopes: tuple[str, ...]
    grant_type: str
    response_type: str
    pkce_method: str
    client_auth_method: str
    trusted_claims: tuple[str, ...]

    def provider_payload(self, *, display_name: str) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "issuer": self.issuer,
            "client_id": self.client_id,
            "discovery_url": self.discovery_url,
            "display_name": display_name,
            "status": "ACTIVE",
        }

    def safe_projection(self) -> dict[str, Any]:
        projection = asdict(self)
        projection.pop("client_secret_reference")
        projection["client_secret_reference_digest"] = sha256(
            self.client_secret_reference.encode("utf-8")
        ).hexdigest()
        projection["client_secret_reference_included"] = False
        projection["client_secret_included"] = False
        return projection


def load_oa_enterprise_oidc_registration(
    environ: Mapping[str, str],
) -> OaEnterpriseOidcRegistration:
    profile = _required(environ, "NEX_PROFILE").lower()
    if profile == "staging_live":
        namespace = "staging"
    elif profile == "production":
        namespace = "production"
    else:
        raise _configuration_error(
            "enterprise OIDC registration requires a production-shaped profile"
        )

    provider_id = _identifier(
        _required(environ, "NEX_OA_OIDC_PROVIDER_ID"), "provider id"
    )
    issuer = _https_url(_required(environ, "NEX_OA_OIDC_ISSUER"), "issuer")
    discovery_url = _https_url(
        _required(environ, "NEX_OA_OIDC_DISCOVERY_URL"), "discovery URL"
    )
    if discovery_url != f"{issuer}/.well-known/openid-configuration":
        raise _configuration_error(
            "enterprise OIDC discovery URL must be issuer-relative"
        )
    base_url = _https_url(_required(environ, "NEX_OA_BASE_URL"), "OA base URL")
    redirect_uri = _https_url(
        _required(environ, "NEX_OA_OIDC_REDIRECT_URI"), "redirect URI"
    )
    if redirect_uri != f"{base_url}{OIDC_CALLBACK_PATH}":
        raise _configuration_error("enterprise OIDC redirect URI is not canonical")
    client_id = _client_id(_required(environ, "NEX_OA_OIDC_CLIENT_ID"))
    secret_reference = _secret_reference(
        _required(environ, "NEX_OA_OIDC_CLIENT_SECRET_REF"),
        namespace=namespace,
    )
    scopes = tuple(_required(environ, "NEX_OA_OIDC_SCOPES").split(" "))
    if scopes != OIDC_SCOPES:
        raise _configuration_error("enterprise OIDC scopes must be exactly openid")
    _exact_setting(environ, "NEX_OA_OIDC_GRANT_TYPE", OIDC_GRANT_TYPE)
    _exact_setting(environ, "NEX_OA_OIDC_RESPONSE_TYPE", OIDC_RESPONSE_TYPE)
    _exact_setting(environ, "NEX_OA_OIDC_PKCE_METHOD", OIDC_PKCE_METHOD)
    _exact_setting(
        environ,
        "NEX_OA_OIDC_CLIENT_AUTH_METHOD",
        OIDC_CLIENT_AUTH_METHOD,
    )
    return OaEnterpriseOidcRegistration(
        registration_schema_version=OIDC_REGISTRATION_SCHEMA_VERSION,
        provider_id=provider_id,
        issuer=issuer,
        discovery_url=discovery_url,
        client_id=client_id,
        client_secret_reference=secret_reference,
        redirect_uri=redirect_uri,
        scopes=scopes,
        grant_type=OIDC_GRANT_TYPE,
        response_type=OIDC_RESPONSE_TYPE,
        pkce_method=OIDC_PKCE_METHOD,
        client_auth_method=OIDC_CLIENT_AUTH_METHOD,
        trusted_claims=OIDC_TRUSTED_CLAIMS,
    )


def validate_enterprise_oidc_discovery(
    registration: OaEnterpriseOidcRegistration,
    document: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        raise _metadata_error("enterprise OIDC discovery document is invalid")
    if document.get("issuer") != registration.issuer:
        raise _metadata_error("enterprise OIDC discovery issuer is invalid")
    endpoints = {}
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        try:
            endpoints[name] = _https_url(document.get(name), name.replace("_", " "))
        except OaFederationError:
            raise _metadata_error(f"enterprise OIDC {name} is invalid") from None
        if _origin(endpoints[name]) != _origin(registration.issuer):
            raise _metadata_error(
                "enterprise OIDC discovery endpoint origin is invalid"
            )
    _supports(document, "response_types_supported", registration.response_type)
    _supports(document, "grant_types_supported", registration.grant_type)
    pkce_methods = document.get("code_challenge_methods_supported")
    if pkce_methods is not None:
        _supports(
            document,
            "code_challenge_methods_supported",
            registration.pkce_method,
        )
    _supports(
        document,
        "token_endpoint_auth_methods_supported",
        registration.client_auth_method,
    )
    _supports(document, "scopes_supported", "openid")
    _supports(document, "id_token_signing_alg_values_supported", "RS256")
    return {
        "metadata_schema_version": "oa_enterprise_oidc_metadata.v1",
        "provider_id": registration.provider_id,
        "issuer": registration.issuer,
        "endpoint_count": len(endpoints),
        "authorization_code_supported": True,
        "pkce_s256_required_by_oa": True,
        "pkce_s256_advertised": pkce_methods is not None,
        "client_secret_basic_supported": True,
        "openid_scope_supported": True,
        "rs256_supported": True,
        "endpoint_origins_match": True,
    }


def _required(environ: Mapping[str, str], name: str) -> str:
    value = str(environ.get(name) or "").strip()
    if not value:
        raise _configuration_error(f"enterprise OIDC setting is missing: {name}")
    return value


def _exact_setting(
    environ: Mapping[str, str],
    name: str,
    expected: str,
) -> None:
    if _required(environ, name) != expected:
        raise _configuration_error(f"enterprise OIDC setting is invalid: {name}")


def _identifier(value: str, label: str) -> str:
    if _IDENTIFIER.fullmatch(value) is None:
        raise _configuration_error(f"enterprise OIDC {label} is invalid")
    return value


def _client_id(value: str) -> str:
    if (
        not 2 <= len(value) <= 255
        or any(character.isspace() for character in value)
        or any(ord(character) < 33 or ord(character) == 127 for character in value)
    ):
        raise _configuration_error("enterprise OIDC client id is invalid")
    return value


def _https_url(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _configuration_error(f"enterprise OIDC {label} is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise _configuration_error(f"enterprise OIDC {label} is invalid") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port is not None
        and not 1 <= port <= 65_535
        or parsed.path.endswith("/")
    ):
        raise _configuration_error(f"enterprise OIDC {label} is invalid")
    return value


def _secret_reference(value: str, *, namespace: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise _configuration_error(
            "enterprise OIDC client secret reference is invalid"
        ) from None
    match = _SECRET_REFERENCE.fullmatch(parsed.path)
    if (
        parsed.scheme != "secret"
        or parsed.hostname != "openbao"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or match is None
        or match.group("namespace") != namespace
    ):
        raise _configuration_error("enterprise OIDC client secret reference is invalid")
    return value


def _supports(document: Mapping[str, Any], field: str, expected: str) -> None:
    values = document.get(field)
    if not isinstance(values, list) or expected not in values:
        raise _metadata_error(f"enterprise OIDC {field} is unsupported")


def _origin(value: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(value)
    return parsed.scheme, str(parsed.hostname), parsed.port


def _configuration_error(message: str) -> OaFederationError:
    return OaFederationError(503, "oa.enterprise_oidc_configuration_invalid", message)


def _metadata_error(message: str) -> OaFederationError:
    return OaFederationError(503, "oa.enterprise_oidc_metadata_invalid", message)
