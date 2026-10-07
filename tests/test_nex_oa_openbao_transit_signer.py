from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from nex_oa.openbao_transit_signer import (
    MAX_SIGNING_INPUT_BYTES,
    OpenBaoTransitOaRsaSigningProvider,
    build_openbao_transit_signing_provider,
    parse_openbao_transit_key_reference,
)
from nex_oa.signed_tokens import OaSignedTokenError


REFERENCE = "vault://openbao/transit/keys/oa-signing/versions/2"


class TransitTransport:
    def __init__(self, key=None, responses=None, failure=None) -> None:
        self.key = key or rsa.generate_private_key(public_exponent=65537, key_size=3072)
        self.responses = list(responses or ())
        self.failure = failure
        self.requests = []

    def request(self, method, path, *, token=None, payload=None):
        self.requests.append((method, path, token, payload))
        if self.failure is not None:
            raise self.failure
        if self.responses:
            return self.responses.pop(0)
        if path == "/v1/auth/approle/login":
            return {"auth": {"client_token": "transit-token-12345678"}}
        if path == "/v1/auth/token/revoke-self":
            return {}
        signature = self.key.sign(
            base64.b64decode(payload["input"]),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return {
            "data": {
                "signature": "vault:v2:" + base64.b64encode(signature).decode("ascii")
            }
        }


def test_approle_transit_rs256_signing_and_close() -> None:
    transport = TransitTransport()
    provider = OpenBaoTransitOaRsaSigningProvider.authenticate(
        transport,
        role_id="role-id-12345678",
        secret_id="secret-id-12345678",
    )
    signing_input = b"header.payload"
    signature = provider.sign_rs256(REFERENCE, signing_input)
    provider.close()
    provider.close()

    transport.key.public_key().verify(
        signature,
        signing_input,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    assert transport.requests[0][1] == "/v1/auth/approle/login"
    assert transport.requests[1] == (
        "POST",
        "/v1/transit/sign/oa-signing/sha2-256",
        "transit-token-12345678",
        {
            "input": base64.b64encode(signing_input).decode("ascii"),
            "key_version": 2,
            "prehashed": False,
            "signature_algorithm": "pkcs1v15",
        },
    )
    assert transport.requests[2][1] == "/v1/auth/token/revoke-self"
    with pytest.raises(OaSignedTokenError, match="closed"):
        provider.sign_rs256(REFERENCE, signing_input)


@pytest.mark.parametrize(
    "reference",
    (
        "",
        "file:///transit/keys/oa-signing/versions/2",
        "vault://other/transit/keys/oa-signing/versions/2",
        "vault://user:pass@openbao/transit/keys/oa-signing/versions/2",
        "vault://openbao:8200/transit/keys/oa-signing/versions/2",
        "vault://openbao/transit/keys/UPPER/versions/2",
        "vault://openbao/transit/keys/oa-signing/versions/0",
        "vault://openbao/transit/keys/oa-signing/versions/2?token=private",
        "vault://openbao/transit/keys/oa-signing/versions/2#fragment",
        "vault://openbao:bad/transit/keys/oa-signing/versions/2",
    ),
)
def test_transit_reference_rejects_unsafe_shapes(reference: str) -> None:
    with pytest.raises(OaSignedTokenError, match="reference"):
        parse_openbao_transit_key_reference(reference)


def test_transit_reference_projection_is_bounded() -> None:
    parsed = parse_openbao_transit_key_reference(REFERENCE)

    assert parsed.key_name == "oa-signing"
    assert parsed.key_version == 2


@pytest.mark.parametrize("signing_input", (b"", b"x" * (MAX_SIGNING_INPUT_BYTES + 1), "text"))
def test_signing_input_is_bounded(signing_input) -> None:
    provider = OpenBaoTransitOaRsaSigningProvider(
        TransitTransport(), "transit-token-12345678"
    )
    with pytest.raises(OaSignedTokenError) as exc:
        provider.sign_rs256(REFERENCE, signing_input)
    assert exc.value.code == "oa.token_signing_invalid"
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "response",
    (
        {},
        {"data": {}},
        {"data": {"signature": "private"}},
        {"data": {"signature": "vault:v1:" + base64.b64encode(b"x" * 384).decode()}},
        {"data": {"signature": "vault:v2:not/base64="}},
        {"data": {"signature": "vault:v2:" + base64.b64encode(b"short").decode()}},
    ),
)
def test_signature_response_fails_closed(response) -> None:
    provider = OpenBaoTransitOaRsaSigningProvider(
        TransitTransport(responses=(response,)), "transit-token-12345678"
    )
    with pytest.raises(OaSignedTokenError) as exc:
        provider.sign_rs256(REFERENCE, b"header.payload")
    assert exc.value.code == "oa.signing_key_custody_unavailable"
    assert exc.value.status_code == 503


def test_authentication_and_transport_failures_are_redacted() -> None:
    for role_id, secret_id in (
        ("short", "secret-id-12345678"),
        ("role-id-12345678", "short"),
    ):
        with pytest.raises(OaSignedTokenError, match="credential"):
            OpenBaoTransitOaRsaSigningProvider.authenticate(
                TransitTransport(), role_id=role_id, secret_id=secret_id
            )
    with pytest.raises(OaSignedTokenError, match="login"):
        OpenBaoTransitOaRsaSigningProvider.authenticate(
            TransitTransport(responses=({"auth": {}},)),
            role_id="role-id-12345678",
            secret_id="secret-id-12345678",
        )
    with pytest.raises(OaSignedTokenError) as exc:
        OpenBaoTransitOaRsaSigningProvider.authenticate(
            TransitTransport(failure=RuntimeError("private-token-value")),
            role_id="role-id-12345678",
            secret_id="secret-id-12345678",
        )
    assert str(exc.value) == "OpenBao Transit request failed"
    assert "private" not in str(exc.value)


def test_sign_and_close_transport_failures_are_redacted() -> None:
    provider = OpenBaoTransitOaRsaSigningProvider(
        TransitTransport(failure=RuntimeError("private-token-value")),
        "transit-token-12345678",
    )
    with pytest.raises(OaSignedTokenError, match="request failed"):
        provider.sign_rs256(REFERENCE, b"header.payload")
    with pytest.raises(OaSignedTokenError, match="request failed"):
        provider.close()


def test_explicit_signing_error_is_preserved() -> None:
    expected = OaSignedTokenError("oa.test", "explicit failure", 409)
    provider = OpenBaoTransitOaRsaSigningProvider(
        TransitTransport(failure=expected),
        "transit-token-12345678",
    )

    with pytest.raises(OaSignedTokenError) as exc:
        provider.sign_rs256(REFERENCE, b"header.payload")
    assert exc.value is expected


def test_constructor_rejects_invalid_client_token() -> None:
    with pytest.raises(OaSignedTokenError, match="client token"):
        OpenBaoTransitOaRsaSigningProvider(TransitTransport(), "short")


def test_runtime_builder_uses_shared_tls_approle_settings(tmp_path) -> None:
    ca = tmp_path / "ca.pem"
    role = tmp_path / "role-id"
    secret = tmp_path / "secret-id"
    ca.write_text("test-ca", encoding="utf-8")
    role.write_text("role-id-12345678", encoding="utf-8")
    secret.write_text("secret-id-12345678", encoding="utf-8")
    captured = {}

    def factory(address, *, ca_certificate_file, timeout_seconds):
        captured.update(
            address=address,
            ca=ca_certificate_file,
            timeout=timeout_seconds,
        )
        return TransitTransport()

    provider = build_openbao_transit_signing_provider(
        {
            "NEX_PROFILE": "staging_live",
            "NEX_OPENBAO_ADDR": "https://openbao:8200",
            "NEX_OPENBAO_CA_CERT_FILE": str(ca),
            "NEX_OPENBAO_ROLE_ID_FILE": str(role),
            "NEX_OPENBAO_SECRET_ID_FILE": str(secret),
            "NEX_OPENBAO_TIMEOUT_SECONDS": "8.5",
        },
        transport_factory=factory,
    )

    assert isinstance(provider, OpenBaoTransitOaRsaSigningProvider)
    assert captured == {
        "address": "https://openbao:8200",
        "ca": ca,
        "timeout": 8.5,
    }


def test_runtime_builder_rejects_non_production_profile_and_bad_settings(tmp_path) -> None:
    with pytest.raises(OaSignedTokenError, match="production-shaped"):
        build_openbao_transit_signing_provider({"NEX_PROFILE": "test"})
    with pytest.raises(OaSignedTokenError, match="configuration"):
        build_openbao_transit_signing_provider({"NEX_PROFILE": "production"})

    ca = tmp_path / "ca.pem"
    role = tmp_path / "role-id"
    secret = tmp_path / "secret-id"
    for path, value in (
        (ca, "test-ca"),
        (role, "role-id-12345678"),
        (secret, "secret-id-12345678"),
    ):
        path.write_text(value, encoding="utf-8")
    environment = {
        "NEX_PROFILE": "production",
        "NEX_OPENBAO_ADDR": "https://openbao:8200",
        "NEX_OPENBAO_CA_CERT_FILE": str(ca),
        "NEX_OPENBAO_ROLE_ID_FILE": str(role),
        "NEX_OPENBAO_SECRET_ID_FILE": str(secret),
    }

    def invalid_factory(*args, **kwargs):
        raise TypeError("private configuration detail")

    with pytest.raises(OaSignedTokenError, match="configuration") as exc:
        build_openbao_transit_signing_provider(
            environment,
            transport_factory=invalid_factory,
        )
    assert "private" not in str(exc.value)
