from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
import json
from time import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from nex_oa.production_token_profiles import (
    MAX_CLOCK_SKEW_SECONDS,
    PRODUCTION_TOKEN_ISSUER,
    TOKEN_AUDIENCES,
    validate_production_token_shape,
)
from nex_oa.service_principal_service import OaServicePrincipalService
from nex_oa.service_principals import OaServicePrincipalError
from nex_oa.signed_tokens import OaSignedTokenError
from nex_oa.signing_key_policy import MINIMUM_RSA_MODULUS_BITS, PRIVATE_JWK_MEMBERS
from nex_oa.signing_key_service import OaSigningKeyService


OA_TOKEN_INTROSPECTION_SCHEMA_VERSION = "oa_token_introspection.v1"


class OaSignedTokenValidationService:
    def __init__(
        self,
        *,
        signing_key_service: OaSigningKeyService,
        principal_service: OaServicePrincipalService,
    ) -> None:
        self.signing_key_service = signing_key_service
        self.principal_service = principal_service

    def validate(
        self,
        token: object,
        *,
        expected_audience: object,
        required_scopes: Sequence[str] = (),
        now_epoch: int | None = None,
    ) -> dict[str, Any]:
        now = int(time()) if now_epoch is None else _nonnegative_integer(now_epoch)
        audience = _expected_audience(expected_audience)
        scopes = _required_scopes(required_scopes)
        decoded = decode_and_verify_service_token(
            token,
            jwks=self.signing_key_service.jwks(at_epoch=now),
        )
        claims = decoded["claims"]
        _validate_runtime_claims(
            claims,
            expected_audience=audience,
            required_scopes=scopes,
            now_epoch=now,
        )
        if self.signing_key_service.is_jti_revoked(claims["jti"], at_epoch=now):
            raise _unauthorized("oa.token_revoked", "access token is revoked")
        try:
            lineage = self.principal_service.resolve_token_credential(
                claims["credential_id"],
                now_epoch=now,
            )
        except OaServicePrincipalError as exc:
            raise _unauthorized(
                "oa.token_credential_inactive",
                "access token credential is inactive",
            ) from exc
        _validate_lineage(claims, lineage)
        return dict(claims)

    def introspect(
        self,
        token: object,
        *,
        expected_audience: object,
        required_scopes: Sequence[str] = (),
        now_epoch: int | None = None,
    ) -> dict[str, Any]:
        try:
            claims = self.validate(
                token,
                expected_audience=expected_audience,
                required_scopes=required_scopes,
                now_epoch=now_epoch,
            )
        except (OaSignedTokenError, OaServicePrincipalError) as exc:
            code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
            return {
                "introspection_schema_version": OA_TOKEN_INTROSPECTION_SCHEMA_VERSION,
                "active": False,
                "reason_code": code or "oa.token_inactive",
            }
        return {
            "introspection_schema_version": OA_TOKEN_INTROSPECTION_SCHEMA_VERSION,
            "active": True,
            "token_use": claims["token_use"],
            "sub": claims["sub"],
            "aud": claims["aud"],
            "scope": claims["scope"],
            "service_id": claims["service_id"],
            "credential_id": claims["credential_id"],
            "credential_revision": claims["credential_revision"],
            "iat": claims["iat"],
            "exp": claims["exp"],
        }


def decode_and_verify_service_token(
    token: object,
    *,
    jwks: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    compact = _nonempty_string(token, "token")
    parts = compact.split(".")
    if len(parts) != 3 or any(not part for part in parts):
        raise _unauthorized("oa.token_malformed", "access token is malformed")
    headers = _json_object(parts[0], "header")
    claims = _json_object(parts[1], "claims")
    signature = _decode_segment(parts[2], "signature")
    if headers.get("alg") != "RS256":
        raise _unauthorized("oa.token_algorithm_invalid", "access token algorithm is invalid")
    key = _select_jwk(jwks, headers.get("kid"))
    public_key = _public_key(key)
    try:
        public_key.verify(
            signature,
            f"{parts[0]}.{parts[1]}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise _unauthorized("oa.token_signature_invalid", "access token signature is invalid") from exc
    shape_errors = validate_production_token_shape(
        "service_access",
        headers=headers,
        claims=claims,
    )
    if shape_errors:
        raise _unauthorized(
            "oa.token_shape_invalid",
            f"access token shape is invalid: {', '.join(shape_errors)}",
        )
    return {"headers": headers, "claims": claims}


def _validate_runtime_claims(
    claims: Mapping[str, Any],
    *,
    expected_audience: str,
    required_scopes: tuple[str, ...],
    now_epoch: int,
) -> None:
    if claims["aud"] != expected_audience:
        raise _forbidden("oa.token_audience_forbidden", "access token audience is forbidden")
    if int(claims["iat"]) > now_epoch + MAX_CLOCK_SKEW_SECONDS:
        raise _unauthorized("oa.token_issued_in_future", "access token issuance time is invalid")
    if int(claims["exp"]) + MAX_CLOCK_SKEW_SECONDS <= now_epoch:
        raise _unauthorized("oa.token_expired", "access token is expired")
    granted = frozenset(str(claims["scope"]).split(" "))
    if not set(required_scopes).issubset(granted):
        raise _forbidden("oa.token_scope_forbidden", "access token scope is forbidden")


def _validate_lineage(
    claims: Mapping[str, Any], lineage: Mapping[str, Any]
) -> None:
    if claims["service_id"] != lineage["service_id"]:
        raise _unauthorized("oa.token_principal_mismatch", "access token principal lineage is invalid")
    if int(claims["credential_revision"]) != int(lineage["credential_revision"]):
        raise _unauthorized("oa.token_credential_stale", "access token credential revision is stale")
    if claims["aud"] not in lineage["allowed_audiences"]:
        raise _forbidden("oa.token_audience_revoked", "access token audience permission was revoked")
    granted = set(str(claims["scope"]).split(" "))
    if not granted.issubset(lineage["allowed_scopes"]):
        raise _forbidden("oa.token_scope_revoked", "access token scope permission was revoked")


def _select_jwk(jwks: Mapping[str, Any], key_id: object) -> Mapping[str, Any]:
    kid = _nonempty_string(key_id, "kid")
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        raise _unauthorized("oa.jwks_invalid", "JWKS document is invalid")
    matches = [item for item in keys if isinstance(item, Mapping) and item.get("kid") == kid]
    if len(matches) != 1:
        raise _unauthorized("oa.token_key_unavailable", "access token signing key is unavailable")
    return matches[0]


def _public_key(jwk: Mapping[str, Any]) -> rsa.RSAPublicKey:
    if PRIVATE_JWK_MEMBERS.intersection(jwk):
        raise _unauthorized("oa.jwk_private_material", "public JWK contains private material")
    if any(jwk.get(name) != value for name, value in {"kty": "RSA", "use": "sig", "alg": "RS256"}.items()):
        raise _unauthorized("oa.jwk_metadata_invalid", "public JWK metadata is invalid")
    modulus = _integer_segment(jwk.get("n"), "n")
    exponent = _integer_segment(jwk.get("e"), "e")
    if modulus.bit_length() < MINIMUM_RSA_MODULUS_BITS:
        raise _unauthorized("oa.jwk_modulus_invalid", "public JWK modulus is too small")
    if exponent < 3 or exponent % 2 == 0:
        raise _unauthorized("oa.jwk_exponent_invalid", "public JWK exponent is invalid")
    try:
        return rsa.RSAPublicNumbers(e=exponent, n=modulus).public_key()
    except ValueError as exc:
        raise _unauthorized("oa.jwk_invalid", "public JWK is invalid") from exc


def _json_object(value: str, field: str) -> dict[str, Any]:
    raw = _decode_segment(value, field)

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, item in values:
            if name in result:
                raise ValueError("duplicate JSON member")
            result[name] = item
        return result

    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _unauthorized("oa.token_json_invalid", f"access token {field} is invalid") from exc
    if not isinstance(parsed, dict):
        raise _unauthorized("oa.token_json_invalid", f"access token {field} must be an object")
    return parsed


def _decode_segment(value: object, field: str) -> bytes:
    encoded = _nonempty_string(value, field)
    try:
        return base64.b64decode(
            encoded + "=" * (-len(encoded) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise _unauthorized("oa.token_encoding_invalid", f"access token {field} encoding is invalid") from exc


def _integer_segment(value: object, field: str) -> int:
    raw = _decode_segment(value, field)
    return int.from_bytes(raw, "big")


def _expected_audience(value: object) -> str:
    audience = _nonempty_string(value, "expected_audience")
    if audience not in TOKEN_AUDIENCES:
        raise _forbidden("oa.token_audience_unknown", "expected audience is unknown")
    return audience


def _required_scopes(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise _forbidden("oa.token_scope_invalid", "required scopes must be a sequence")
    scopes = tuple(_nonempty_string(item, "required_scope") for item in value)
    if len(scopes) != len(set(scopes)):
        raise _forbidden("oa.token_scope_invalid", "required scopes must be unique")
    return scopes


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _unauthorized("oa.token_value_invalid", f"{field} must be a non-empty string")
    return value


def _nonnegative_integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _unauthorized("oa.token_clock_invalid", "validation clock is invalid")
    return value


def _unauthorized(code: str, message: str) -> OaSignedTokenError:
    return OaSignedTokenError(code, message, 401)


def _forbidden(code: str, message: str) -> OaSignedTokenError:
    return OaSignedTokenError(code, message, 403)
