from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import rsa

from nex_oa.signed_tokens import OaSignedTokenError
from nex_oa.token_signing import (
    InMemoryOaRsaSigningProvider,
    TestFileOaRsaSigningProvider as FileSigningProvider,
    UnavailableOaRsaSigningProvider,
    build_oa_signing_provider,
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


def _write_private_key(path: Path, key: object, *, mode: int = 0o600) -> str:
    material = key.private_bytes(  # type: ignore[union-attr]
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(material)
    path.chmod(mode)
    return path.as_uri()


def test_test_file_provider_signs_restricted_rsa_key(tmp_path: Path) -> None:
    reference = _write_private_key(
        tmp_path / "oa.pem",
        rsa.generate_private_key(public_exponent=65537, key_size=3072),
    )
    provider = FileSigningProvider(tmp_path)

    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": "test"},
        claims={"sub": "service:nex-ae-api"},
        private_key_ref=reference,
        signing_provider=provider,
    )

    assert token.count(".") == 2


def test_signing_provider_builder_is_explicit_and_test_only(tmp_path: Path) -> None:
    assert isinstance(build_oa_signing_provider({}), UnavailableOaRsaSigningProvider)
    provider = build_oa_signing_provider(
        {
            "NEX_PROFILE": "test",
            "NEX_OA_SIGNING_PROVIDER": "test_file",
            "NEX_OA_SIGNING_KEY_ROOT": str(tmp_path),
        }
    )
    assert isinstance(provider, FileSigningProvider)

    invalid = (
        {"NEX_OA_SIGNING_PROVIDER": "unknown"},
        {"NEX_OA_SIGNING_PROVIDER": "test_file", "NEX_PROFILE": "production"},
        {"NEX_OA_SIGNING_PROVIDER": "test_file", "NEX_PROFILE": "test"},
        {
            "NEX_OA_SIGNING_PROVIDER": "test_file",
            "NEX_PROFILE": "test",
            "NEX_OA_SIGNING_KEY_ROOT": str(tmp_path / "missing"),
        },
    )
    for environ in invalid:
        with pytest.raises(OaSignedTokenError) as exc:
            build_oa_signing_provider(environ)
        assert exc.value.code == "oa.signing_key_custody_unavailable"


def test_test_file_provider_rejects_unsafe_references_and_permissions(
    tmp_path: Path,
) -> None:
    root = tmp_path / "keys"
    root.mkdir()
    outside = tmp_path / "outside.pem"
    outside_ref = _write_private_key(
        outside,
        rsa.generate_private_key(public_exponent=65537, key_size=3072),
    )
    broad = root / "broad.pem"
    broad_ref = _write_private_key(
        broad,
        rsa.generate_private_key(public_exponent=65537, key_size=3072),
        mode=0o644,
    )
    link = root / "link.pem"
    link.symlink_to(outside)
    provider = FileSigningProvider(root)

    for reference in (
        "",
        "kms://oa/key",
        "file://remote/key.pem",
        "file:///missing.pem?secret=yes",
        "relative.pem",
        outside_ref,
        broad_ref,
        link.as_uri(),
        root.as_uri(),
        (root / "missing.pem").as_uri(),
    ):
        with pytest.raises(OaSignedTokenError):
            provider.sign_rs256(reference, b"payload")
    with pytest.raises(OaSignedTokenError, match="signing input"):
        provider.sign_rs256(broad_ref, b"")


@pytest.mark.parametrize("material_kind", ["invalid", "empty", "ec", "small", "large"])
def test_test_file_provider_rejects_invalid_key_material(
    tmp_path: Path,
    material_kind: str,
) -> None:
    path = tmp_path / "key.pem"
    if material_kind == "invalid":
        path.write_bytes(b"not-a-key")
    elif material_kind == "empty":
        path.write_bytes(b"")
    elif material_kind == "ec":
        _write_private_key(path, ec.generate_private_key(ec.SECP256R1()))
    elif material_kind == "small":
        _write_private_key(
            path, rsa.generate_private_key(public_exponent=65537, key_size=2048)
        )
    else:
        path.write_bytes(b"x" * 65_537)
    path.chmod(0o600)
    provider = FileSigningProvider(tmp_path)

    with pytest.raises(OaSignedTokenError):
        provider.sign_rs256(path.as_uri(), b"payload")


def test_test_file_provider_rejects_non_directory_root(tmp_path: Path) -> None:
    key = tmp_path / "root.pem"
    key.write_text("not a directory", encoding="utf-8")
    with pytest.raises(OaSignedTokenError, match="directory"):
        FileSigningProvider(key)


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
