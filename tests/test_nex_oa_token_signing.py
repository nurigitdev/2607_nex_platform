from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from nex_oa.signed_tokens import OaSignedTokenError
from nex_oa.token_signing import (
    InMemoryOaRsaSigningProvider,
    UnavailableOaRsaSigningProvider,
    encode_signed_jwt,
    public_jwk_from_key,
)


def test_in_memory_provider_generates_public_jwk_and_signs_compact_jwt() -> None:
    provider = InMemoryOaRsaSigningProvider()
    reference = "file:///tmp/oa-key-token"
    generated = provider.generate_key(reference)
    public = provider.public_jwk(reference, key_id="oa-key-token")

    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": "oa-key-token"},
        claims={"sub": "service:nex-ae-api", "serializable": True},
        private_key_ref=reference,
        signing_provider=provider,
    )

    assert token.count(".") == 2
    assert generated["kid"] == "oa-key-token"
    assert public["kty"] == "RSA"
    assert set(public) == {"kty", "use", "alg", "kid", "n", "e"}
    header = json.loads(_decode(token.split(".")[0]))
    assert header["kid"] == "oa-key-token"


def test_provider_accepts_injected_3072_bit_key() -> None:
    provider = InMemoryOaRsaSigningProvider()
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    provider.add_key("kms://oa/key-1", key)

    assert provider.public_jwk("kms://oa/key-1", key_id="key-1")["e"] == "AQAB"


@pytest.mark.parametrize(
    ("action", "message"),
    [
        (lambda p: p.generate_key(""), "reference"),
        (lambda p: p.generate_key("file:///tmp/small", key_size=2048), "too small"),
        (lambda p: p.sign_rs256("missing", b"value"), "custody"),
        (lambda p: p.sign_rs256("missing", b""), "input"),
    ],
)
def test_provider_rejects_unsafe_or_unavailable_signing(
    action: object, message: str
) -> None:
    provider = InMemoryOaRsaSigningProvider()
    with pytest.raises(OaSignedTokenError, match=message):
        action(provider)  # type: ignore[operator]


def test_provider_rejects_small_injected_and_projected_keys() -> None:
    provider = InMemoryOaRsaSigningProvider()
    small = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(OaSignedTokenError, match="too small"):
        provider.add_key("file:///tmp/small", small)
    with pytest.raises(OaSignedTokenError, match="too small"):
        public_jwk_from_key(small, key_id="small")


def test_encode_rejects_unserializable_claims_and_empty_signature() -> None:
    provider = InMemoryOaRsaSigningProvider()
    provider.generate_key("file:///tmp/serialize")
    with pytest.raises(OaSignedTokenError, match="serializable"):
        encode_signed_jwt(
            headers={"alg": "RS256"},
            claims={"bad": object()},
            private_key_ref="file:///tmp/serialize",
            signing_provider=provider,
        )

    class EmptySigner:
        def sign_rs256(self, private_key_ref: str, signing_input: bytes) -> bytes:
            return b""

    with pytest.raises(OaSignedTokenError, match="empty signature"):
        encode_signed_jwt(
            headers={"alg": "RS256"},
            claims={"sub": "service:nex-oa"},
            private_key_ref="kms://oa/empty",
            signing_provider=EmptySigner(),
        )


def test_generated_key_reference_fallback_is_bounded() -> None:
    provider = InMemoryOaRsaSigningProvider()
    assert provider.generate_key("/")["kid"] == "oa-generated-key"


def test_unavailable_external_custody_fails_closed() -> None:
    with pytest.raises(OaSignedTokenError) as exc:
        UnavailableOaRsaSigningProvider().sign_rs256("kms://oa/key", b"payload")
    assert exc.value.code == "oa.signing_key_custody_unavailable"
    assert exc.value.status_code == 503


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
