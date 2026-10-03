from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
import json
from time import time
from typing import Any, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from nex_oa.federated_identities import OaFederationError


OIDC_ID_TOKEN_ALGORITHM = "RS256"
OIDC_ID_TOKEN_TYPE = "JWT"
OIDC_CACHE_TTL_SECONDS = 300
OIDC_MAX_CACHE_TTL_SECONDS = 900
OIDC_MAX_KEYS = 16
OIDC_MAX_TOKEN_BYTES = 16_384
OIDC_MAX_CLOCK_SKEW_SECONDS = 60
OIDC_MAX_TOKEN_TTL_SECONDS = 3_600
OIDC_MIN_RSA_BITS = 2_048
OIDC_FORBIDDEN_HEADERS = frozenset({"crit", "jku", "x5c", "x5u"})
OIDC_PRIVATE_JWK_MEMBERS = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth"})


class OidcDocumentSource(Protocol):
    def fetch_json(self, url: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class VerifiedOidcIdentity:
    provider_id: str
    issuer: str
    audiences: tuple[str, ...]
    authorized_party: str
    issued_at: int
    expires_at: int
    key_id: str
    external_subject_digest: str
    nonce_digest: str
    _external_subject: str = field(repr=False)

    @property
    def external_subject(self) -> str:
        return self._external_subject

    def safe_projection(self) -> dict[str, Any]:
        return {
            "verification_schema_version": "oa_oidc_verification.v1",
            "provider_id": self.provider_id,
            "issuer": self.issuer,
            "audiences": self.audiences,
            "authorized_party": self.authorized_party,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "key_id_digest": sha256(self.key_id.encode()).hexdigest(),
            "external_subject_digest": self.external_subject_digest,
            "nonce_digest": self.nonce_digest,
            "raw_external_subject_included": False,
            "raw_nonce_included": False,
            "raw_id_token_included": False,
        }


class StaticOidcDocumentSource:
    def __init__(self, documents: Mapping[str, Mapping[str, Any]]) -> None:
        self._documents = {url: dict(value) for url, value in documents.items()}
        self.fetches: list[str] = []

    def replace(self, url: str, document: Mapping[str, Any]) -> None:
        self._documents[url] = dict(document)

    def fetch_json(self, url: str) -> Mapping[str, Any]:
        self.fetches.append(url)
        if url not in self._documents:
            raise OaFederationError(
                503,
                "oa.oidc_document_unavailable",
                "OIDC provider document is unavailable.",
            )
        return self._documents[url]


class OidcDiscoveryJwksCache:
    def __init__(
        self,
        provider: Mapping[str, Any],
        source: OidcDocumentSource,
        *,
        ttl_seconds: int = OIDC_CACHE_TTL_SECONDS,
        max_keys: int = OIDC_MAX_KEYS,
        clock: Callable[[], float] = time,
    ) -> None:
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or not 1 <= ttl_seconds <= OIDC_MAX_CACHE_TTL_SECONDS:
            raise ValueError("OIDC cache TTL is outside the supported range")
        if not isinstance(max_keys, int) or isinstance(max_keys, bool) or not 1 <= max_keys <= OIDC_MAX_KEYS:
            raise ValueError("OIDC cache key limit is outside the supported range")
        if not callable(getattr(source, "fetch_json", None)):
            raise TypeError("OIDC document source must implement fetch_json")
        if not callable(clock):
            raise TypeError("OIDC cache clock must be callable")
        self._provider = dict(provider)
        self._source = source
        self._ttl_seconds = ttl_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._keys: dict[str, rsa.RSAPublicKey] = {}
        self._jwks_uri: str | None = None
        self._refreshed_at: int | None = None

    def key_for(self, key_id: object, *, now_epoch: int | None = None) -> rsa.RSAPublicKey:
        kid = _nonempty_text(key_id, "kid")
        now = self._now(now_epoch)
        if self._refreshed_at is None or now - self._refreshed_at >= self._ttl_seconds:
            self.refresh(now_epoch=now)
        key = self._keys.get(kid)
        if key is None:
            self.refresh(now_epoch=now)
            key = self._keys.get(kid)
        if key is None:
            raise _auth_error("oa.oidc_key_unavailable", "OIDC signing key is unavailable.")
        return key

    def refresh(self, *, now_epoch: int | None = None) -> int:
        now = self._now(now_epoch)
        try:
            discovery = self._source.fetch_json(str(self._provider["discovery_url"]))
            jwks_uri = _validated_discovery(discovery, provider=self._provider)
            jwks = self._source.fetch_json(jwks_uri)
            keys = _validated_jwks(jwks, max_keys=self._max_keys)
        except OaFederationError:
            raise
        except Exception as exc:
            raise OaFederationError(
                503,
                "oa.oidc_document_unavailable",
                "OIDC provider document is unavailable.",
            ) from exc
        self._jwks_uri = jwks_uri
        self._keys = keys
        self._refreshed_at = now
        return len(keys)

    def safe_snapshot(self) -> dict[str, Any]:
        return {
            "cache_schema_version": "oa_oidc_cache.v1",
            "provider_id": self._provider.get("provider_id"),
            "status": "POPULATED" if self._keys else "EMPTY",
            "key_count": len(self._keys),
            "refreshed_at_epoch": self._refreshed_at,
            "ttl_seconds": self._ttl_seconds,
            "max_keys": self._max_keys,
            "jwks_uri_configured": self._jwks_uri is not None,
            "key_ids_included": False,
        }

    def _now(self, now_epoch: int | None) -> int:
        value = int(self._clock()) if now_epoch is None else now_epoch
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("OIDC cache clock must return a non-negative integer")
        return value


class OidcIdTokenVerifier:
    def __init__(
        self,
        provider: Mapping[str, Any],
        cache: OidcDiscoveryJwksCache,
        *,
        clock: Callable[[], float] = time,
    ) -> None:
        if provider.get("status") != "ACTIVE":
            raise ValueError("OIDC provider must be active")
        if not callable(clock):
            raise TypeError("OIDC verifier clock must be callable")
        self._provider = dict(provider)
        self._cache = cache
        self._clock = clock

    def verify(
        self,
        id_token: object,
        *,
        expected_nonce: object,
        now_epoch: int | None = None,
    ) -> VerifiedOidcIdentity:
        compact = _nonempty_text(id_token, "id_token")
        if len(compact.encode()) > OIDC_MAX_TOKEN_BYTES:
            raise _auth_error("oa.oidc_token_oversized", "OIDC ID token is too large.")
        nonce = _nonempty_text(expected_nonce, "nonce")
        now = self._now(now_epoch)
        parts = compact.split(".")
        if len(parts) != 3 or any(not part for part in parts):
            raise _auth_error("oa.oidc_token_malformed", "OIDC ID token is malformed.")
        headers = _json_object(parts[0], "header")
        claims = _json_object(parts[1], "claims")
        signature = _decode_segment(parts[2], "signature")
        key_id = _validated_headers(headers)
        key = self._cache.key_for(key_id, now_epoch=now)
        try:
            key.verify(
                signature,
                f"{parts[0]}.{parts[1]}".encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, ValueError) as exc:
            raise _auth_error(
                "oa.oidc_signature_invalid", "OIDC ID token signature is invalid."
            ) from exc
        return _validated_identity(
            claims,
            provider=self._provider,
            key_id=key_id,
            expected_nonce=nonce,
            now_epoch=now,
        )

    def _now(self, now_epoch: int | None) -> int:
        value = int(self._clock()) if now_epoch is None else now_epoch
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise _auth_error("oa.oidc_clock_invalid", "OIDC validation clock is invalid.")
        return value


def _validated_discovery(
    document: object, *, provider: Mapping[str, Any]
) -> str:
    if not isinstance(document, Mapping):
        raise _provider_error("oa.oidc_discovery_invalid", "OIDC discovery document is invalid.")
    if document.get("issuer") != provider.get("issuer"):
        raise _provider_error("oa.oidc_discovery_issuer_invalid", "OIDC discovery issuer is invalid.")
    algorithms = document.get("id_token_signing_alg_values_supported")
    if not isinstance(algorithms, list) or OIDC_ID_TOKEN_ALGORITHM not in algorithms:
        raise _provider_error("oa.oidc_discovery_algorithm_invalid", "OIDC provider does not support RS256.")
    jwks_uri = _nonempty_text(document.get("jwks_uri"), "jwks_uri")
    if not jwks_uri.startswith("https://"):
        raise _provider_error("oa.oidc_jwks_uri_invalid", "OIDC JWKS URI must use HTTPS.")
    return jwks_uri


def _validated_jwks(document: object, *, max_keys: int) -> dict[str, rsa.RSAPublicKey]:
    if not isinstance(document, Mapping):
        raise _provider_error("oa.oidc_jwks_invalid", "OIDC JWKS document is invalid.")
    items = document.get("keys")
    if not isinstance(items, list) or not items or len(items) > max_keys:
        raise _provider_error("oa.oidc_jwks_invalid", "OIDC JWKS key set is invalid.")
    keys: dict[str, rsa.RSAPublicKey] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise _provider_error("oa.oidc_jwk_invalid", "OIDC JWK is invalid.")
        kid = _nonempty_text(item.get("kid"), "kid")
        if kid in keys:
            raise _provider_error("oa.oidc_jwk_duplicate", "OIDC JWKS contains duplicate key ids.")
        keys[kid] = _public_key(item)
    return keys


def _public_key(jwk: Mapping[str, Any]) -> rsa.RSAPublicKey:
    if OIDC_PRIVATE_JWK_MEMBERS.intersection(jwk):
        raise _provider_error("oa.oidc_jwk_private", "OIDC JWK contains private material.")
    if any(jwk.get(name) != value for name, value in {"kty": "RSA", "use": "sig", "alg": "RS256"}.items()):
        raise _provider_error("oa.oidc_jwk_metadata_invalid", "OIDC JWK metadata is invalid.")
    modulus = _jwk_integer(jwk.get("n"), "n")
    exponent = _jwk_integer(jwk.get("e"), "e")
    if modulus.bit_length() < OIDC_MIN_RSA_BITS or exponent < 3 or exponent % 2 == 0:
        raise _provider_error("oa.oidc_jwk_numbers_invalid", "OIDC JWK RSA parameters are invalid.")
    try:
        return rsa.RSAPublicNumbers(e=exponent, n=modulus).public_key()
    except ValueError as exc:
        raise _provider_error("oa.oidc_jwk_invalid", "OIDC JWK is invalid.") from exc


def _validated_headers(headers: Mapping[str, Any]) -> str:
    if headers.get("alg") != OIDC_ID_TOKEN_ALGORITHM:
        raise _auth_error("oa.oidc_algorithm_invalid", "OIDC ID token algorithm is invalid.")
    if headers.get("typ") not in {None, OIDC_ID_TOKEN_TYPE}:
        raise _auth_error("oa.oidc_type_invalid", "OIDC ID token type is invalid.")
    if OIDC_FORBIDDEN_HEADERS.intersection(headers):
        raise _auth_error("oa.oidc_header_forbidden", "OIDC ID token header is forbidden.")
    return _nonempty_text(headers.get("kid"), "kid")


def _validated_identity(
    claims: Mapping[str, Any],
    *,
    provider: Mapping[str, Any],
    key_id: str,
    expected_nonce: str,
    now_epoch: int,
) -> VerifiedOidcIdentity:
    required = ("iss", "sub", "aud", "iat", "exp", "nonce")
    if any(name not in claims for name in required):
        raise _auth_error("oa.oidc_claim_missing", "OIDC ID token claims are incomplete.")
    issuer = _nonempty_text(claims["iss"], "iss")
    subject = _nonempty_text(claims["sub"], "sub")
    if issuer != provider.get("issuer"):
        raise _auth_error("oa.oidc_issuer_invalid", "OIDC ID token issuer is invalid.")
    audiences = _audiences(claims["aud"])
    client_id = str(provider.get("client_id") or "")
    if client_id not in audiences:
        raise _auth_error("oa.oidc_audience_invalid", "OIDC ID token audience is invalid.")
    authorized_party = claims.get("azp", client_id)
    if len(audiences) > 1 and "azp" not in claims:
        raise _auth_error("oa.oidc_azp_missing", "OIDC authorized party is required.")
    if authorized_party != client_id:
        raise _auth_error("oa.oidc_azp_invalid", "OIDC authorized party is invalid.")
    nonce = _nonempty_text(claims["nonce"], "nonce")
    if nonce != expected_nonce:
        raise _auth_error("oa.oidc_nonce_invalid", "OIDC nonce is invalid.")
    issued_at = _integer_claim(claims["iat"], "iat")
    expires_at = _integer_claim(claims["exp"], "exp")
    not_before = _integer_claim(claims.get("nbf", issued_at), "nbf")
    if not_before > issued_at or issued_at >= expires_at:
        raise _auth_error("oa.oidc_time_invalid", "OIDC ID token time claims are invalid.")
    if expires_at - issued_at > OIDC_MAX_TOKEN_TTL_SECONDS:
        raise _auth_error("oa.oidc_ttl_invalid", "OIDC ID token lifetime is invalid.")
    if issued_at > now_epoch + OIDC_MAX_CLOCK_SKEW_SECONDS or not_before > now_epoch + OIDC_MAX_CLOCK_SKEW_SECONDS:
        raise _auth_error("oa.oidc_not_yet_valid", "OIDC ID token is not yet valid.")
    if expires_at <= now_epoch - OIDC_MAX_CLOCK_SKEW_SECONDS:
        raise _auth_error("oa.oidc_expired", "OIDC ID token is expired.")
    return VerifiedOidcIdentity(
        provider_id=str(provider["provider_id"]),
        issuer=issuer,
        audiences=audiences,
        authorized_party=client_id,
        issued_at=issued_at,
        expires_at=expires_at,
        key_id=key_id,
        external_subject_digest=sha256(f"{issuer}\x00{subject}".encode()).hexdigest(),
        nonce_digest=sha256(nonce.encode()).hexdigest(),
        _external_subject=subject,
    )


def _audiences(value: object) -> tuple[str, ...]:
    if isinstance(value, str) and value:
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        audiences = tuple(item for item in value if isinstance(item, str) and item)
        if audiences and len(audiences) == len(value):
            return audiences
    raise _auth_error("oa.oidc_audience_invalid", "OIDC ID token audience is invalid.")


def _json_object(segment: str, label: str) -> Mapping[str, Any]:
    try:
        decoded = json.loads(_decode_segment(segment, label).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _auth_error("oa.oidc_token_malformed", f"OIDC ID token {label} is invalid.") from exc
    if not isinstance(decoded, Mapping):
        raise _auth_error("oa.oidc_token_malformed", f"OIDC ID token {label} is invalid.")
    return decoded


def _decode_segment(segment: str, label: str) -> bytes:
    try:
        return base64.b64decode(segment + "=" * (-len(segment) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _auth_error("oa.oidc_token_malformed", f"OIDC ID token {label} is invalid.") from exc


def _jwk_integer(value: object, label: str) -> int:
    text = _nonempty_text(value, label)
    raw = _decode_segment(text, label)
    if not raw:
        raise _provider_error("oa.oidc_jwk_invalid", "OIDC JWK is invalid.")
    return int.from_bytes(raw, "big")


def _integer_claim(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _auth_error("oa.oidc_claim_invalid", f"OIDC ID token {label} claim is invalid.")
    return value


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _auth_error("oa.oidc_value_invalid", f"OIDC {label} is invalid.")
    return value


def _auth_error(code: str, detail: str) -> OaFederationError:
    return OaFederationError(401, code, detail)


def _provider_error(code: str, detail: str) -> OaFederationError:
    return OaFederationError(503, code, detail)
