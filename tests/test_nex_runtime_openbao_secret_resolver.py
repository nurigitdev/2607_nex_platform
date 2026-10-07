from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from nex_runtime.openbao_secret_resolver import (
    OpenBaoSecretResolver,
    OpenBaoClientSettings,
    OpenBaoSecretResolverError,
    UrllibOpenBaoTransport,
    build_openbao_secret_resolver,
    load_openbao_client_settings,
)
from nex_runtime.production_secret_materialization import SecretResolutionContext


class Transport:
    def __init__(self, responses=None) -> None:
        self.responses = list(
            responses
            or (
                {"auth": {"client_token": "token-12345678"}},
                {"data": {"data": {"value": "private-value"}}},
                {},
            )
        )
        self.requests = []

    def request(self, method, path, *, token=None, payload=None):
        self.requests.append((method, path, token, payload))
        return self.responses.pop(0)


def _context(owner="nex-oa", target="NEX_OA_DATABASE_URL", version="v1"):
    return SecretResolutionContext(
        owner=owner,
        target_environment_name=target,
        secret_generation="secret:staging.1",
        reference_version=version,
    )


def test_approle_kv_v2_resolution_and_token_revocation() -> None:
    transport = Transport()
    resolver = OpenBaoSecretResolver.authenticate(
        transport,
        role_id="role-id-12345678",
        secret_id="secret-id-12345678",
    )
    secret = resolver.resolve(
        "secret://openbao/nex-platform/staging/nex-oa/NEX_OA_DATABASE_URL@v1",
        context=_context(),
    )
    resolver.revoke()
    resolver.revoke()

    assert secret.value == "private-value"
    assert secret.provider_id == "openbao"
    assert transport.requests[0][1] == "/v1/auth/approle/login"
    assert transport.requests[1][1].endswith("NEX_OA_DATABASE_URL?version=1")
    assert transport.requests[1][2] == "token-12345678"
    assert transport.requests[2][1] == "/v1/auth/token/revoke-self"
    with pytest.raises(OpenBaoSecretResolverError, match="closed"):
        resolver.resolve(
            "secret://openbao/nex-platform/staging/nex-oa/NEX_OA_DATABASE_URL@v1",
            context=_context(),
        )


@pytest.mark.parametrize(
    "reference",
    [
        "http://openbao/nex-platform/staging/nex-oa/NEX_OA_DATABASE_URL@v1",
        "secret://other/nex-platform/staging/nex-oa/NEX_OA_DATABASE_URL@v1",
        "secret://user:pass@openbao/nex-platform/staging/nex-oa/NEX_OA_DATABASE_URL@v1",
        "secret://openbao:8200/nex-platform/staging/nex-oa/NEX_OA_DATABASE_URL@v1",
        "secret://openbao/nex-platform/staging/nex-oa/NEX_OA_DATABASE_URL@v1?q=1",
        "secret://openbao/wrong@v1",
    ],
)
def test_rejects_invalid_openbao_references(reference) -> None:
    resolver = OpenBaoSecretResolver(Transport(), "token-12345678")
    with pytest.raises(OpenBaoSecretResolverError, match="reference"):
        resolver.resolve(reference, context=_context())


def test_rejects_scope_version_and_response_drift() -> None:
    resolver = OpenBaoSecretResolver(Transport(), "token-12345678")
    with pytest.raises(OpenBaoSecretResolverError, match="scope"):
        resolver.resolve(
            "secret://openbao/nex-platform/staging/nex-mo/NEX_MO_DATABASE_URL@v1",
            context=_context(),
        )
    resolver = OpenBaoSecretResolver(Transport(), "token-12345678")
    with pytest.raises(OpenBaoSecretResolverError, match="scope"):
        resolver.resolve(
            "secret://openbao/nex-platform/staging/nex-oa/NEX_OA_DATABASE_URL@v2",
            context=_context(),
        )
    resolver = OpenBaoSecretResolver(
        Transport(({"data": {"data": {}}},)), "token-12345678"
    )
    with pytest.raises(OpenBaoSecretResolverError, match="response"):
        resolver.resolve(
            "secret://openbao/nex-platform/staging/nex-oa/NEX_OA_DATABASE_URL@v1",
            context=_context(),
        )


@pytest.mark.parametrize(
    ("role_id", "secret_id", "response"),
    [
        ("short", "secret-id-12345678", {"auth": {"client_token": "token-12345678"}}),
        ("role-id-12345678", "short", {"auth": {"client_token": "token-12345678"}}),
        ("role-id-12345678", "secret-id-12345678", {"auth": {}}),
    ],
)
def test_approle_authentication_is_fail_closed(role_id, secret_id, response) -> None:
    with pytest.raises(OpenBaoSecretResolverError):
        OpenBaoSecretResolver.authenticate(
            Transport((response,)), role_id=role_id, secret_id=secret_id
        )
    with pytest.raises(OpenBaoSecretResolverError, match="token"):
        OpenBaoSecretResolver(Transport(), "short")


def test_environment_factory_reads_only_absolute_credential_files(tmp_path, monkeypatch) -> None:
    role = tmp_path / "role"
    secret = tmp_path / "secret"
    ca = tmp_path / "ca.pem"
    role.write_text("role-id-12345678", encoding="utf-8")
    secret.write_text("secret-id-12345678", encoding="utf-8")
    ca.write_text("certificate", encoding="utf-8")
    captured = {}

    class FakeTransport(Transport):
        def __init__(self, address, *, ca_certificate_file, timeout_seconds):
            super().__init__(({"auth": {"client_token": "token-12345678"}},))
            captured.update(
                address=address,
                ca=ca_certificate_file,
                timeout=timeout_seconds,
            )

    monkeypatch.setattr(
        "nex_runtime.openbao_secret_resolver.UrllibOpenBaoTransport", FakeTransport
    )
    resolver = build_openbao_secret_resolver(
        {
            "NEX_OPENBAO_ADDR": "https://openbao:8200",
            "NEX_OPENBAO_CA_CERT_FILE": str(ca),
            "NEX_OPENBAO_ROLE_ID_FILE": str(role),
            "NEX_OPENBAO_SECRET_ID_FILE": str(secret),
            "NEX_OPENBAO_SECRET_NAMESPACE": "staging",
            "NEX_OPENBAO_TIMEOUT_SECONDS": "7.5",
        }
    )
    assert isinstance(resolver, OpenBaoSecretResolver)
    assert captured == {
        "address": "https://openbao:8200",
        "ca": ca,
        "timeout": 7.5,
    }
    assert load_openbao_client_settings(
        {
            "NEX_OPENBAO_ADDR": "https://openbao:8200",
            "NEX_OPENBAO_CA_CERT_FILE": str(ca),
            "NEX_OPENBAO_ROLE_ID_FILE": str(role),
            "NEX_OPENBAO_SECRET_ID_FILE": str(secret),
            "NEX_OPENBAO_TIMEOUT_SECONDS": "7.5",
        }
    ) == OpenBaoClientSettings(
        address="https://openbao:8200",
        ca_certificate_file=ca,
        role_id="role-id-12345678",
        secret_id="secret-id-12345678",
        timeout_seconds=7.5,
    )

    for values in (
        {},
        {"NEX_OPENBAO_CA_CERT_FILE": "relative"},
        {
            "NEX_OPENBAO_CA_CERT_FILE": str(ca),
            "NEX_OPENBAO_ROLE_ID_FILE": str(role),
            "NEX_OPENBAO_SECRET_ID_FILE": str(secret),
            "NEX_OPENBAO_SECRET_NAMESPACE": "staging",
            "NEX_OPENBAO_TIMEOUT_SECONDS": "invalid",
        },
    ):
        with pytest.raises(OpenBaoSecretResolverError):
            build_openbao_secret_resolver(values)


def test_credential_file_and_transport_negative_paths(tmp_path, monkeypatch) -> None:
    role = tmp_path / "role"
    secret = tmp_path / "secret"
    ca = tmp_path / "ca.pem"
    role.write_text("x" * 4097, encoding="utf-8")
    secret.write_text("secret-id-12345678", encoding="utf-8")
    ca.write_text("certificate", encoding="utf-8")
    environment = {
        "NEX_OPENBAO_ADDR": "https://openbao:8200",
        "NEX_OPENBAO_CA_CERT_FILE": str(ca),
        "NEX_OPENBAO_ROLE_ID_FILE": str(role),
        "NEX_OPENBAO_SECRET_ID_FILE": str(secret),
        "NEX_OPENBAO_SECRET_NAMESPACE": "staging",
    }
    with pytest.raises(OpenBaoSecretResolverError, match="role ID"):
        build_openbao_secret_resolver(environment)
    with pytest.raises(OpenBaoSecretResolverError, match="HTTPS origin"):
        UrllibOpenBaoTransport("http://openbao:8200", ca_certificate_file=ca)
    with pytest.raises(OpenBaoSecretResolverError, match="positive"):
        UrllibOpenBaoTransport(
            "https://openbao:8200",
            ca_certificate_file=ca,
            timeout_seconds=0,
        )
    with pytest.raises(OpenBaoSecretResolverError, match="CA certificate"):
        UrllibOpenBaoTransport(
            "https://openbao:8200", ca_certificate_file=tmp_path / "missing"
        )
    with pytest.raises(OpenBaoSecretResolverError, match="namespace"):
        OpenBaoSecretResolver(Transport(), "token-12345678", namespace="other")

    role.write_text("bad credential", encoding="utf-8")
    with pytest.raises(OpenBaoSecretResolverError, match="role ID"):
        build_openbao_secret_resolver(environment)
    role.unlink()
    role.mkdir()
    with pytest.raises(OpenBaoSecretResolverError, match="unavailable"):
        build_openbao_secret_resolver(environment)

    transport = object.__new__(UrllibOpenBaoTransport)
    transport._address = "https://openbao:8200"
    transport._context = object()
    transport._timeout_seconds = 1
    monkeypatch.setattr(
        "nex_runtime.openbao_secret_resolver.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("private")),
    )
    with pytest.raises(OpenBaoSecretResolverError, match="request failed"):
        transport.request("GET", "/v1/secret")
    with pytest.raises(OpenBaoSecretResolverError, match="path"):
        transport.request("GET", "/wrong")


def test_reference_namespace_and_malformed_port_are_rejected() -> None:
    resolver = OpenBaoSecretResolver(
        Transport(), "token-12345678", namespace="production"
    )
    with pytest.raises(OpenBaoSecretResolverError, match="scope"):
        resolver.resolve(
            "secret://openbao/nex-platform/staging/nex-oa/NEX_OA_DATABASE_URL@v1",
            context=_context(),
        )
    with pytest.raises(OpenBaoSecretResolverError, match="reference"):
        resolver.resolve(
            "secret://openbao:bad/nex-platform/production/nex-oa/"
            "NEX_OA_DATABASE_URL@v1",
            context=_context(),
        )


def test_transport_json_paths(monkeypatch) -> None:
    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            return self.body

    transport = object.__new__(UrllibOpenBaoTransport)
    transport._address = "https://openbao:8200"
    transport._context = object()
    transport._timeout_seconds = 1
    monkeypatch.setattr(
        "nex_runtime.openbao_secret_resolver.urlopen",
        lambda *args, **kwargs: Response(json.dumps({"ok": True}).encode()),
    )
    assert transport.request(
        "POST", "/v1/test", token="token-12345678", payload={"x": 1}
    ) == {"ok": True}
    monkeypatch.setattr(
        "nex_runtime.openbao_secret_resolver.urlopen",
        lambda *args, **kwargs: Response(b""),
    )
    assert transport.request("POST", "/v1/auth/token/revoke-self") == {}
    monkeypatch.setattr(
        "nex_runtime.openbao_secret_resolver.urlopen",
        lambda *args, **kwargs: Response(b"[]"),
    )
    with pytest.raises(OpenBaoSecretResolverError, match="response is invalid"):
        transport.request("GET", "/v1/test")
    monkeypatch.setattr(
        "nex_runtime.openbao_secret_resolver.urlopen",
        lambda *args, **kwargs: Response(b"{"),
    )
    with pytest.raises(OpenBaoSecretResolverError, match="response is invalid"):
        transport.request("GET", "/v1/test")
    monkeypatch.setattr(
        "nex_runtime.openbao_secret_resolver.urlopen",
        lambda *args, **kwargs: Response(b"x" * 1_048_577),
    )
    with pytest.raises(OpenBaoSecretResolverError, match="too large"):
        transport.request("GET", "/v1/test")


def test_transport_constructor_accepts_https_origin(monkeypatch, tmp_path) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_text("certificate", encoding="utf-8")
    context = object()
    monkeypatch.setattr(
        "nex_runtime.openbao_secret_resolver.ssl.create_default_context",
        lambda **kwargs: context,
    )
    transport = UrllibOpenBaoTransport(
        "https://openbao:8200/",
        ca_certificate_file=ca,
        timeout_seconds=2,
    )
    assert transport._address == "https://openbao:8200"
    assert transport._context is context


def test_factory_rejects_missing_namespace(tmp_path) -> None:
    role = tmp_path / "role"
    secret = tmp_path / "secret"
    ca = tmp_path / "ca.pem"
    role.write_text("role-id-12345678", encoding="utf-8")
    secret.write_text("secret-id-12345678", encoding="utf-8")
    ca.write_text("certificate", encoding="utf-8")
    with pytest.raises(OpenBaoSecretResolverError, match="namespace"):
        build_openbao_secret_resolver(
            {
                "NEX_OPENBAO_ADDR": "https://openbao:8200",
                "NEX_OPENBAO_CA_CERT_FILE": str(ca),
                "NEX_OPENBAO_ROLE_ID_FILE": str(role),
                "NEX_OPENBAO_SECRET_ID_FILE": str(secret),
            }
        )
