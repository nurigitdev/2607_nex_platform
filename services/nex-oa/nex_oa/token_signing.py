from __future__ import annotations

import base64
from collections.abc import Mapping
from json import dumps
from typing import Any, Protocol

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from nex_oa.signed_tokens import OaSignedTokenError
from nex_oa.signing_key_policy import MINIMUM_RSA_MODULUS_BITS


class OaRsaSigningProvider(Protocol):
    def sign_rs256(self, private_key_ref: str, signing_input: bytes) -> bytes: ...


class UnavailableOaRsaSigningProvider:
    def sign_rs256(self, private_key_ref: str, signing_input: bytes) -> bytes:
        raise OaSignedTokenError(
            "oa.signing_key_custody_unavailable",
            "external private signing key custody is not configured",
            503,
        )


class InMemoryOaRsaSigningProvider:
    """Test/development custody that never serializes private keys."""

    def __init__(self) -> None:
        self._keys: dict[str, rsa.RSAPrivateKey] = {}

    def generate_key(
        self,
        private_key_ref: str,
        *,
        key_size: int = MINIMUM_RSA_MODULUS_BITS,
    ) -> dict[str, str]:
        if not isinstance(private_key_ref, str) or not private_key_ref:
            raise _signing_error("private key reference is required")
        if key_size < MINIMUM_RSA_MODULUS_BITS:
            raise _signing_error("RSA signing key is too small")
        key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
        self._keys[private_key_ref] = key
        return public_jwk_from_key(key, key_id=_key_id_from_reference(private_key_ref))

    def add_key(
        self,
        private_key_ref: str,
        private_key: rsa.RSAPrivateKey,
    ) -> None:
        if private_key.key_size < MINIMUM_RSA_MODULUS_BITS:
            raise _signing_error("RSA signing key is too small")
        self._keys[private_key_ref] = private_key

    def public_jwk(self, private_key_ref: str, *, key_id: str) -> dict[str, str]:
        return public_jwk_from_key(self._load(private_key_ref), key_id=key_id)

    def sign_rs256(self, private_key_ref: str, signing_input: bytes) -> bytes:
        if not isinstance(signing_input, bytes) or not signing_input:
            raise _signing_error("signing input is required")
        return self._load(private_key_ref).sign(
            signing_input,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )

    def _load(self, private_key_ref: str) -> rsa.RSAPrivateKey:
        try:
            return self._keys[private_key_ref]
        except (KeyError, TypeError) as exc:
            raise OaSignedTokenError(
                "oa.signing_key_custody_unavailable",
                "private signing key custody is unavailable",
                503,
            ) from exc


def encode_signed_jwt(
    *,
    headers: Mapping[str, Any],
    claims: Mapping[str, Any],
    private_key_ref: str,
    signing_provider: OaRsaSigningProvider,
) -> str:
    encoded_header = _base64url(_json_bytes(headers))
    encoded_claims = _base64url(_json_bytes(claims))
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    signature = signing_provider.sign_rs256(private_key_ref, signing_input)
    if not signature:
        raise _signing_error("signing provider returned an empty signature")
    return f"{signing_input.decode('ascii')}.{_base64url(signature)}"


def public_jwk_from_key(
    private_key: rsa.RSAPrivateKey,
    *,
    key_id: str,
) -> dict[str, str]:
    if private_key.key_size < MINIMUM_RSA_MODULUS_BITS:
        raise _signing_error("RSA signing key is too small")
    numbers = private_key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": key_id,
        "n": _base64url(_integer_bytes(numbers.n)),
        "e": _base64url(_integer_bytes(numbers.e)),
    }


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return dumps(
            dict(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise _signing_error("JWT value is not JSON serializable") from exc


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _integer_bytes(value: int) -> bytes:
    return value.to_bytes((value.bit_length() + 7) // 8, "big")


def _key_id_from_reference(private_key_ref: str) -> str:
    candidate = private_key_ref.rstrip("/").rsplit("/", 1)[-1]
    return candidate or "oa-generated-key"


def _signing_error(message: str) -> OaSignedTokenError:
    return OaSignedTokenError("oa.token_signing_invalid", message, 400)
