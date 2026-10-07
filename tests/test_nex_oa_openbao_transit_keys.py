from __future__ import annotations

from copy import deepcopy

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from nex_oa.openbao_transit_keys import (
    OpenBaoTransitKeyProvisioner,
    build_openbao_transit_custody_reference,
    register_openbao_transit_key_version,
)
from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER
from nex_oa.signed_token_repository import InMemoryOaSignedTokenRepository
from nex_oa.signed_tokens import OaSignedTokenError
from nex_oa.signing_key_service import OaSigningKeyService


class ProvisioningTransport:
    def __init__(self, metadata=None, failure=None, login=None) -> None:
        self.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=3072
        )
        self.metadata = (
            _metadata(self.private_key) if metadata is None else metadata
        )
        self.failure = failure
        self.login = login or {"auth": {"client_token": "admin-token-12345678"}}
        self.requests = []

    def request(self, method, path, *, token=None, payload=None):
        self.requests.append((method, path, token, payload))
        if self.failure is not None:
            raise self.failure
        if path == "/v1/auth/approle/login":
            return self.login
        if path.endswith("/rotate"):
            next_version = int(self.metadata["latest_version"]) + 1
            next_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            self.metadata["latest_version"] = next_version
            self.metadata["keys"][str(next_version)] = {
                "public_key": _pem(next_key.public_key())
            }
            return {}
        if method == "GET":
            return {"data": deepcopy(self.metadata)}
        return {}


def _pem(public_key) -> str:
    return public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def _metadata(private_key) -> dict:
    return {
        "type": "rsa-3072",
        "supports_signing": True,
        "derived": False,
        "exportable": False,
        "allow_plaintext_backup": False,
        "latest_version": 1,
        "keys": {"1": {"public_key": _pem(private_key.public_key())}},
    }


def _provisioner(transport=None) -> tuple[OpenBaoTransitKeyProvisioner, ProvisioningTransport]:
    selected = transport or ProvisioningTransport()
    return (
        OpenBaoTransitKeyProvisioner.authenticate(
            selected,
            role_id="admin-role-12345678",
            secret_id="admin-secret-12345678",
        ),
        selected,
    )


def test_provisions_projects_and_registers_only_public_metadata() -> None:
    provisioner, transport = _provisioner()
    repository = InMemoryOaSignedTokenRepository()
    service = OaSigningKeyService(
        repository=repository,
        deployment_profile="production",
    )

    version = provisioner.provision_rsa3072("oa-signing")
    response = register_openbao_transit_key_version(
        provisioner,
        service,
        key_name="oa-signing",
        key_version=version,
        key_id="oa-key-2026-01",
        issuer=PRODUCTION_TOKEN_ISSUER,
        published_at=100,
        activate_at=430,
        sign_until=800,
        verify_until=1_130,
    )
    provisioner.close()
    provisioner.close()

    wire = response["signing_key"]
    stored = repository.get_signing_key("oa-key-2026-01")
    assert version == 1
    assert wire["state"] == "PREPUBLISHED"
    assert "private_key_ref" not in wire
    assert set(wire["public_jwk"]) == {"kty", "use", "alg", "kid", "n", "e"}
    assert stored["private_key_ref"] == (
        "vault://openbao/transit/keys/oa-signing/versions/1"
    )
    assert service.jwks(at_epoch=200)["keys"] == [wire["public_jwk"]]
    assert transport.requests[1] == (
        "POST",
        "/v1/transit/keys/oa-signing",
        "admin-token-12345678",
        {
            "type": "rsa-3072",
            "derived": False,
            "exportable": False,
            "allow_plaintext_backup": False,
        },
    )
    assert transport.requests[-1][1] == "/v1/auth/token/revoke-self"


@pytest.mark.parametrize(
    "role_id,secret_id",
    (("short", "admin-secret-12345678"), ("admin-role-12345678", "short")),
)
def test_authentication_rejects_invalid_credentials(role_id, secret_id) -> None:
    with pytest.raises(OaSignedTokenError, match="credential") as exc:
        OpenBaoTransitKeyProvisioner.authenticate(
            ProvisioningTransport(), role_id=role_id, secret_id=secret_id
        )
    assert exc.value.status_code == 503


def test_authentication_and_transport_failures_are_redacted() -> None:
    with pytest.raises(OaSignedTokenError, match="login"):
        OpenBaoTransitKeyProvisioner.authenticate(
            ProvisioningTransport(login={"auth": {}}),
            role_id="admin-role-12345678",
            secret_id="admin-secret-12345678",
        )
    with pytest.raises(OaSignedTokenError) as exc:
        OpenBaoTransitKeyProvisioner.authenticate(
            ProvisioningTransport(failure=RuntimeError("private-root-token")),
            role_id="admin-role-12345678",
            secret_id="admin-secret-12345678",
        )
    assert str(exc.value) == "OpenBao Transit provisioning request failed"
    assert "private-root-token" not in str(exc.value)


@pytest.mark.parametrize(
    "change",
    (
        {"type": "rsa-4096"},
        {"supports_signing": False},
        {"derived": True},
        {"exportable": True},
        {"allow_plaintext_backup": True},
    ),
)
def test_key_policy_must_be_rsa3072_non_exportable(change) -> None:
    transport = ProvisioningTransport()
    transport.metadata.update(change)
    provisioner, _ = _provisioner(transport)
    with pytest.raises(OaSignedTokenError, match="policy"):
        provisioner.provision_rsa3072("oa-signing")


def test_projection_rejects_missing_or_invalid_public_keys() -> None:
    cases = []
    base = _metadata(
        rsa.generate_private_key(public_exponent=65537, key_size=3072)
    )
    cases.append("not-a-mapping")
    cases.append({})
    cases.append({**base, "latest_version": 0})
    cases.append({**base, "keys": {}})
    cases.append({**base, "keys": {"1": {"public_key": "not-pem"}}})
    ec_public = _pem(ec.generate_private_key(ec.SECP256R1()).public_key())
    cases.append({**base, "keys": {"1": {"public_key": ec_public}}})
    small_public = _pem(
        rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    )
    cases.append({**base, "keys": {"1": {"public_key": small_public}}})

    for metadata in cases:
        provisioner, _ = _provisioner(ProvisioningTransport(metadata=metadata))
        with pytest.raises(OaSignedTokenError):
            provisioner.project_key_version(
                "oa-signing", key_version=1, key_id="oa-key-2026-01"
            )


def test_projection_rejects_unavailable_version_and_bad_inputs() -> None:
    provisioner, _ = _provisioner()
    with pytest.raises(OaSignedTokenError, match="unavailable"):
        provisioner.project_key_version(
            "oa-signing", key_version=2, key_id="oa-key-2026-02"
        )
    for key_name, version, key_id in (
        ("UPPER", 1, "oa-key"),
        ("oa-signing", 0, "oa-key"),
        ("oa-signing", True, "oa-key"),
        ("oa-signing", 1, ""),
        ("oa-signing", 1, " spaced "),
    ):
        with pytest.raises(OaSignedTokenError) as exc:
            provisioner.project_key_version(
                key_name, key_version=version, key_id=key_id
            )
        assert exc.value.status_code == 400


def test_reference_and_closed_provisioner_fail_closed() -> None:
    assert build_openbao_transit_custody_reference("oa-signing", 3) == (
        "vault://openbao/transit/keys/oa-signing/versions/3"
    )
    with pytest.raises(OaSignedTokenError):
        build_openbao_transit_custody_reference("bad/name", 1)
    with pytest.raises(OaSignedTokenError):
        OpenBaoTransitKeyProvisioner(ProvisioningTransport(), "short")

    provisioner, _ = _provisioner()
    provisioner.close()
    with pytest.raises(OaSignedTokenError, match="closed"):
        provisioner.provision_rsa3072("oa-signing")
    with pytest.raises(OaSignedTokenError, match="closed"):
        provisioner.project_key_version(
            "oa-signing", key_version=1, key_id="oa-key-2026-01"
        )


def test_rotation_requires_exact_current_version_and_one_step_result() -> None:
    provisioner, transport = _provisioner()

    with pytest.raises(OaSignedTokenError) as conflict:
        provisioner.rotate_rsa3072(
            "oa-signing", expected_current_version=2
        )
    assert conflict.value.code == "oa.signing_key_version_conflict"

    assert provisioner.rotate_rsa3072(
        "oa-signing", expected_current_version=1
    ) == 2
    assert transport.requests[-2][1] == "/v1/transit/keys/oa-signing/rotate"
    projection = provisioner.project_key_version(
        "oa-signing", key_version=2, key_id="oa-key-2026-02"
    )
    assert projection.key_version == 2
    assert projection.public_jwk["kid"] == "oa-key-2026-02"


def test_rotation_rejects_non_incrementing_provider_result() -> None:
    class NonRotatingTransport(ProvisioningTransport):
        def request(self, method, path, *, token=None, payload=None):
            if path.endswith("/rotate"):
                self.requests.append((method, path, token, payload))
                return {}
            return super().request(method, path, token=token, payload=payload)

    provisioner, _ = _provisioner(NonRotatingTransport())
    with pytest.raises(OaSignedTokenError, match="result is invalid"):
        provisioner.rotate_rsa3072(
            "oa-signing", expected_current_version=1
        )


def test_explicit_provisioning_error_is_preserved() -> None:
    expected = OaSignedTokenError("oa.test", "explicit", 409)
    with pytest.raises(OaSignedTokenError) as exc:
        OpenBaoTransitKeyProvisioner.authenticate(
            ProvisioningTransport(failure=expected),
            role_id="admin-role-12345678",
            secret_id="admin-secret-12345678",
        )
    assert exc.value is expected
