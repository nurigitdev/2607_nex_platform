from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from time import time
from typing import Any, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


SIGNED_TOKEN_ISSUER = "urn:nex-platform:oa"
SIGNED_TOKEN_TYPE = "at+jwt"
SIGNED_TOKEN_ALGORITHM = "RS256"
SERVICE_ACCESS_TOKEN_USE = "service_access"
SIGNED_TOKEN_AUDIENCES = frozenset(
    {"nex-oa", "nex-ag", "nex-ae-api", "nex-cx", "nex-mo"}
)
JWKS_CACHE_TTL_SECONDS = 300
MAX_JWKS_CACHE_TTL_SECONDS = 900
MAX_JWKS_KEYS = 16
MAX_SIGNED_TOKEN_BYTES = 16_384
MAX_TOKEN_TTL_SECONDS = 300
MAX_CLOCK_SKEW_SECONDS = 30
MINIMUM_RSA_MODULUS_BITS = 3072
PRIVATE_JWK_MEMBERS = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth"})
FORBIDDEN_JWT_HEADERS = frozenset({"jku", "x5u", "x5c", "crit"})
SENSITIVE_CLAIMS = frozenset(
    {
        "password",
        "client_secret",
        "credential_secret",
        "private_key",
        "session_token",
        "tenant_id",
        "user_id",
        "session_ref",
        "authorization_revision",
        "azp",
    }
)


@dataclass
class SignedTokenVerificationError(Exception):
    code: str
    message: str
    status_code: int = 401

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class VerifiedServiceTokenClaims:
    issuer: str
    subject: str
    audience: str
    service_id: str
    scopes: tuple[str, ...]
    issued_at: int
    not_before: int
    expires_at: int
    credential_id: str
    credential_revision: int
    key_id: str
    token_id_digest: str

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


class JwksSource(Protocol):
    def fetch_jwks(self) -> Mapping[str, Any]: ...


class StaticJwksSource:
    """Deterministic JWKS source for tests and explicit local wiring."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        self._document = dict(document)
        self.fetch_count = 0

    def replace(self, document: Mapping[str, Any]) -> None:
        self._document = dict(document)

    def fetch_jwks(self) -> Mapping[str, Any]:
        self.fetch_count += 1
        return self._document


class BoundedJwksCache:
    def __init__(
        self,
        source: JwksSource | Callable[[], Mapping[str, Any]],
        *,
        ttl_seconds: int = JWKS_CACHE_TTL_SECONDS,
        max_keys: int = MAX_JWKS_KEYS,
        clock: Callable[[], float] = time,
    ) -> None:
        if not _positive_integer(ttl_seconds) or ttl_seconds > MAX_JWKS_CACHE_TTL_SECONDS:
            raise ValueError("JWKS cache TTL is outside the supported range")
        if not _positive_integer(max_keys) or max_keys > MAX_JWKS_KEYS:
            raise ValueError("JWKS cache key limit is outside the supported range")
        if not callable(source) and not callable(getattr(source, "fetch_jwks", None)):
            raise TypeError("JWKS source must be callable or implement fetch_jwks")
        if not callable(clock):
            raise TypeError("JWKS cache clock must be callable")
        self._source = source
        self._ttl_seconds = ttl_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._keys: dict[str, rsa.RSAPublicKey] = {}
        self._refreshed_at: int | None = None

    @property
    def refreshed_at(self) -> int | None:
        return self._refreshed_at

    @property
    def key_count(self) -> int:
        return len(self._keys)

    def key_for(self, key_id: object, *, now_epoch: int | None = None) -> rsa.RSAPublicKey:
        kid = _nonempty_string(key_id, "kid")
        now = self._now(now_epoch)
        if self._refreshed_at is None or now - self._refreshed_at >= self._ttl_seconds:
            self.refresh(now_epoch=now)
        key = self._keys.get(kid)
        if key is None:
            self.refresh(now_epoch=now)
            key = self._keys.get(kid)
        if key is None:
            raise _unauthorized(
                "nex.token_key_unavailable",
                "access token signing key is unavailable",
            )
        return key

    def refresh(self, *, now_epoch: int | None = None) -> int:
        now = self._now(now_epoch)
        try:
            raw = (
                self._source()
                if callable(self._source)
                else self._source.fetch_jwks()
            )
        except Exception as exc:
            raise _unavailable(
                "nex.jwks_unavailable", "JWKS source is unavailable"
            ) from exc
        keys = _validated_jwks(raw, max_keys=self._max_keys)
        self._keys = keys
        self._refreshed_at = now
        return len(keys)

    def _now(self, now_epoch: int | None) -> int:
        if now_epoch is None:
            value = int(self._clock())
        else:
            value = now_epoch
        if not _nonnegative_integer(value):
            raise ValueError("JWKS cache clock must return a non-negative integer")
        return int(value)


class SignedServiceTokenVerifier:
    def __init__(
        self,
        cache: BoundedJwksCache,
        *,
        issuer: str = SIGNED_TOKEN_ISSUER,
        clock: Callable[[], float] = time,
    ) -> None:
        self._cache = cache
        self._issuer = _nonempty_string(issuer, "issuer")
        if not callable(clock):
            raise TypeError("token verifier clock must be callable")
        self._clock = clock

    def verify_authorization_header(
        self,
        authorization: object,
        *,
        expected_audience: object,
        required_scopes: Sequence[str] = (),
        now_epoch: int | None = None,
    ) -> VerifiedServiceTokenClaims:
        if not isinstance(authorization, str) or not authorization:
            raise _unauthorized("nex.authorization_missing", "authorization is required")
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token or token != token.strip():
            raise _unauthorized(
                "nex.authorization_invalid", "authorization must use the Bearer scheme"
            )
        return self.verify(
            token,
            expected_audience=expected_audience,
            required_scopes=required_scopes,
            now_epoch=now_epoch,
        )

    def verify(
        self,
        token: object,
        *,
        expected_audience: object,
        required_scopes: Sequence[str] = (),
        now_epoch: int | None = None,
    ) -> VerifiedServiceTokenClaims:
        compact = _nonempty_string(token, "token")
        if len(compact.encode("utf-8")) > MAX_SIGNED_TOKEN_BYTES:
            raise _unauthorized("nex.token_oversized", "access token is too large")
        audience = _expected_audience(expected_audience)
        scopes = _required_scopes(required_scopes)
        now = self._now(now_epoch)
        parts = compact.split(".")
        if len(parts) != 3 or any(not part for part in parts):
            raise _unauthorized("nex.token_malformed", "access token is malformed")
        headers = _json_object(parts[0], "header")
        claims = _json_object(parts[1], "claims")
        signature = _decode_segment(parts[2], "signature")
        key_id = _validate_headers(headers)
        public_key = self._cache.key_for(key_id, now_epoch=now)
        try:
            public_key.verify(
                signature,
                f"{parts[0]}.{parts[1]}".encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, ValueError) as exc:
            raise _unauthorized(
                "nex.token_signature_invalid", "access token signature is invalid"
            ) from exc
        return _validated_service_claims(
            claims,
            key_id=key_id,
            expected_issuer=self._issuer,
            expected_audience=audience,
            required_scopes=scopes,
            now_epoch=now,
        )

    def _now(self, now_epoch: int | None) -> int:
        if now_epoch is None:
            value = int(self._clock())
        else:
            value = now_epoch
        if not _nonnegative_integer(value):
            raise _unauthorized("nex.token_clock_invalid", "validation clock is invalid")
        return int(value)


def _validated_jwks(
    document: object, *, max_keys: int
) -> dict[str, rsa.RSAPublicKey]:
    if not isinstance(document, Mapping):
        raise _unavailable("nex.jwks_invalid", "JWKS document is invalid")
    if document.get("issuer") != SIGNED_TOKEN_ISSUER:
        raise _unavailable("nex.jwks_issuer_invalid", "JWKS issuer is invalid")
    items = document.get("keys")
    if not isinstance(items, list) or len(items) > max_keys:
        raise _unavailable("nex.jwks_invalid", "JWKS key set is invalid")
    keys: dict[str, rsa.RSAPublicKey] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise _unavailable("nex.jwks_invalid", "JWKS key is invalid")
        kid = _nonempty_string(item.get("kid"), "kid", unavailable=True)
        if kid in keys:
            raise _unavailable("nex.jwks_duplicate_kid", "JWKS contains duplicate key ids")
        keys[kid] = _public_key(item)
    return keys


def _public_key(jwk: Mapping[str, Any]) -> rsa.RSAPublicKey:
    if PRIVATE_JWK_MEMBERS.intersection(jwk):
        raise _unavailable(
            "nex.jwk_private_material", "public JWK contains private material"
        )
    expected = {"kty": "RSA", "use": "sig", "alg": SIGNED_TOKEN_ALGORITHM}
    if any(jwk.get(name) != value for name, value in expected.items()):
        raise _unavailable("nex.jwk_metadata_invalid", "public JWK metadata is invalid")
    modulus = _jwk_integer(jwk.get("n"), "n")
    exponent = _jwk_integer(jwk.get("e"), "e")
    if modulus.bit_length() < MINIMUM_RSA_MODULUS_BITS:
        raise _unavailable("nex.jwk_modulus_invalid", "public JWK modulus is too small")
    if exponent < 3 or exponent % 2 == 0:
        raise _unavailable("nex.jwk_exponent_invalid", "public JWK exponent is invalid")
    try:
        return rsa.RSAPublicNumbers(e=exponent, n=modulus).public_key()
    except ValueError as exc:
        raise _unavailable("nex.jwk_invalid", "public JWK is invalid") from exc


def _validate_headers(headers: Mapping[str, Any]) -> str:
    if headers.get("alg") != SIGNED_TOKEN_ALGORITHM:
        raise _unauthorized("nex.token_algorithm_invalid", "access token algorithm is invalid")
    if headers.get("typ") != SIGNED_TOKEN_TYPE:
        raise _unauthorized("nex.token_type_invalid", "access token type is invalid")
    if FORBIDDEN_JWT_HEADERS.intersection(headers):
        raise _unauthorized("nex.token_header_forbidden", "access token header is forbidden")
    return _nonempty_string(headers.get("kid"), "kid")


def _validated_service_claims(
    claims: Mapping[str, Any],
    *,
    key_id: str,
    expected_issuer: str,
    expected_audience: str,
    required_scopes: tuple[str, ...],
    now_epoch: int,
) -> VerifiedServiceTokenClaims:
    required = (
        "iss",
        "sub",
        "aud",
        "iat",
        "nbf",
        "exp",
        "jti",
        "token_use",
        "scope",
        "service_id",
        "credential_id",
        "credential_revision",
    )
    if any(name not in claims for name in required):
        raise _unauthorized("nex.token_claim_missing", "access token claims are incomplete")
    if SENSITIVE_CLAIMS.intersection(claims):
        raise _unauthorized("nex.token_claim_forbidden", "access token contains forbidden claims")
    issuer = _nonempty_string(claims["iss"], "iss")
    subject = _nonempty_string(claims["sub"], "sub")
    audience = _nonempty_string(claims["aud"], "aud")
    token_use = _nonempty_string(claims["token_use"], "token_use")
    service_id = _nonempty_string(claims["service_id"], "service_id")
    credential_id = _nonempty_string(claims["credential_id"], "credential_id")
    token_id = _nonempty_string(claims["jti"], "jti")
    if issuer != expected_issuer:
        raise _unauthorized("nex.token_issuer_invalid", "access token issuer is invalid")
    if audience != expected_audience:
        raise _forbidden("nex.token_audience_forbidden", "access token audience is forbidden")
    if token_use != SERVICE_ACCESS_TOKEN_USE:
        raise _unauthorized("nex.token_use_invalid", "access token use is invalid")
    if service_id not in SIGNED_TOKEN_AUDIENCES or subject != f"service:{service_id}":
        raise _unauthorized("nex.token_subject_invalid", "access token subject is invalid")
    issued_at = _integer_claim(claims["iat"], "iat")
    not_before = _integer_claim(claims["nbf"], "nbf")
    expires_at = _integer_claim(claims["exp"], "exp")
    revision = _integer_claim(claims["credential_revision"], "credential_revision")
    if revision <= 0:
        raise _unauthorized(
            "nex.token_credential_revision_invalid",
            "access token credential revision is invalid",
        )
    if not_before > issued_at or issued_at >= expires_at:
        raise _unauthorized("nex.token_time_invalid", "access token time claims are invalid")
    if issued_at - not_before > MAX_CLOCK_SKEW_SECONDS:
        raise _unauthorized("nex.token_time_invalid", "access token time claims are invalid")
    if expires_at - issued_at > MAX_TOKEN_TTL_SECONDS:
        raise _unauthorized("nex.token_ttl_invalid", "access token lifetime is invalid")
    if not_before > now_epoch + MAX_CLOCK_SKEW_SECONDS:
        raise _unauthorized("nex.token_not_yet_valid", "access token is not yet valid")
    if issued_at > now_epoch + MAX_CLOCK_SKEW_SECONDS:
        raise _unauthorized("nex.token_issued_in_future", "access token issuance time is invalid")
    if expires_at + MAX_CLOCK_SKEW_SECONDS <= now_epoch:
        raise _unauthorized("nex.token_expired", "access token is expired")
    granted_scopes = _token_scopes(claims["scope"])
    if not set(required_scopes).issubset(granted_scopes):
        raise _forbidden("nex.token_scope_forbidden", "access token scope is forbidden")
    return VerifiedServiceTokenClaims(
        issuer=issuer,
        subject=subject,
        audience=audience,
        service_id=service_id,
        scopes=granted_scopes,
        issued_at=issued_at,
        not_before=not_before,
        expires_at=expires_at,
        credential_id=credential_id,
        credential_revision=revision,
        key_id=key_id,
        token_id_digest=sha256(token_id.encode("utf-8")).hexdigest(),
    )


def _token_scopes(value: object) -> tuple[str, ...]:
    raw = _nonempty_string(value, "scope")
    scopes = tuple(raw.split(" "))
    if any(not scope or scope != scope.strip() for scope in scopes) or len(scopes) != len(set(scopes)):
        raise _unauthorized("nex.token_scope_invalid", "access token scope is invalid")
    return scopes


def _required_scopes(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise _forbidden("nex.token_scope_invalid", "required scopes must be a sequence")
    scopes = tuple(_nonempty_string(item, "required_scope") for item in value)
    if len(scopes) != len(set(scopes)):
        raise _forbidden("nex.token_scope_invalid", "required scopes must be unique")
    return scopes


def _expected_audience(value: object) -> str:
    audience = _nonempty_string(value, "expected_audience")
    if audience not in SIGNED_TOKEN_AUDIENCES:
        raise _forbidden("nex.token_audience_unknown", "expected audience is unknown")
    return audience


def _json_object(value: str, field: str) -> dict[str, Any]:
    raw = _decode_segment(value, field)

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, item in items:
            if name in result:
                raise ValueError("duplicate JSON member")
            result[name] = item
        return result

    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _unauthorized("nex.token_json_invalid", f"access token {field} is invalid") from exc
    if not isinstance(parsed, dict):
        raise _unauthorized("nex.token_json_invalid", f"access token {field} must be an object")
    return parsed


def _decode_segment(value: object, field: str) -> bytes:
    encoded = _nonempty_string(value, field)
    try:
        return base64.b64decode(
            encoded + "=" * (-len(encoded) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError, TypeError) as exc:
        raise _unauthorized(
            "nex.token_encoding_invalid", f"access token {field} encoding is invalid"
        ) from exc


def _jwk_integer(value: object, field: str) -> int:
    try:
        raw = _decode_segment(value, field)
    except SignedTokenVerificationError as exc:
        raise _unavailable("nex.jwk_encoding_invalid", "public JWK encoding is invalid") from exc
    return int.from_bytes(raw, "big")


def _integer_claim(value: object, field: str) -> int:
    if not _nonnegative_integer(value):
        raise _unauthorized("nex.token_claim_invalid", f"access token {field} claim is invalid")
    return int(value)


def _nonempty_string(value: object, field: str, *, unavailable: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        factory = _unavailable if unavailable else _unauthorized
        raise factory(
            "nex.jwks_invalid" if unavailable else "nex.token_value_invalid",
            f"{field} must be a non-empty string",
        )
    return value


def _nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_integer(value: object) -> bool:
    return _nonnegative_integer(value) and value > 0


def _unauthorized(code: str, message: str) -> SignedTokenVerificationError:
    return SignedTokenVerificationError(code, message, 401)


def _forbidden(code: str, message: str) -> SignedTokenVerificationError:
    return SignedTokenVerificationError(code, message, 403)


def _unavailable(code: str, message: str) -> SignedTokenVerificationError:
    return SignedTokenVerificationError(code, message, 503)
