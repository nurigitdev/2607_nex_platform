from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from urllib.error import URLError

from cryptography import x509
import pytest
import yaml

from nex_runtime.production_configuration import (
    load_production_configuration_manifest,
)
from nex_runtime.s143_staging import (
    OWNERS,
    OpenBaoAdminClient,
    S143StagingError,
    configure_openbao_staging,
    _wait_for_openbao_uninitialized,
    _wait_for_openbao_active,
    initialize_openbao,
    prepare_staging_runtime_directory,
    refresh_openbao_approle_credentials,
    validate_s143_compose_assets,
    write_openbao_secret_generation,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeClient:
    def __init__(self) -> None:
        self.requests = []
        self.kv_version = 1

    def request(self, method, path, *, token=None, payload=None):
        self.requests.append((method, path, token, payload))
        if path == "/v1/sys/init" and method == "GET":
            return {"initialized": False}
        if path == "/v1/sys/init":
            return {
                "root_token": "root-token-12345678",
                "keys_base64": ["unseal-key-12345678"],
            }
        if path == "/v1/sys/leader":
            return {"ha_enabled": True, "is_self": True}
        if path.endswith("/role-id"):
            owner = path.split("/")[-2].removesuffix("-staging")
            return {"data": {"role_id": f"role-id-{owner}-12345678"}}
        if path.endswith("/secret-id"):
            owner = path.split("/")[-2].removesuffix("-staging")
            return {"data": {"secret_id": f"secret-id-{owner}-12345678"}}
        if "/v1/kv/data/" in path:
            return {"data": {"version": self.kv_version}}
        if path == "/v1/pki/root/generate/internal":
            return {"data": {"certificate": "-----BEGIN CERTIFICATE-----\nca"}}
        if path == "/v1/pki/issue/nex-platform-staging":
            return {
                "data": {
                    "certificate": "-----BEGIN CERTIFICATE-----\nleaf",
                    "private_key": "-----BEGIN PRIVATE KEY-----\nkey",
                    "issuing_ca": "-----BEGIN CERTIFICATE-----\nca",
                    "serial_number": "01:23",
                }
            }
        return {}


def _secret_values() -> dict[str, str]:
    manifest = load_production_configuration_manifest(ROOT)
    return {
        binding.target_environment_name: f"private-{binding.target_environment_name}"
        for binding in manifest.bindings
        if binding.input_kind == "external_secret_reference"
    }


def test_compose_contract_is_digest_pinned_and_value_free() -> None:
    result = validate_s143_compose_assets(ROOT)

    assert result["status"] == "VALID"
    assert result["service_count"] == 9
    assert result["runtime_service_count"] == 8
    assert result["initializer_service_count"] == 1
    assert result["secret_reference_count"] == 20
    assert result["tls_route_count"] == 9
    assert result["host_software_install_required"] is False
    assert result["raw_secret_values_included"] is False


def _copied_compose_root(tmp_path: Path) -> Path:
    target = tmp_path / "root/deployment/compose"
    target.parent.mkdir(parents=True)
    shutil.copytree(ROOT / "deployment/compose", target)
    return tmp_path / "root"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda doc: [], "document"),
        (lambda doc: {**doc, "services": []}, "services"),
        (
            lambda doc: {
                **doc,
                "services": {k: v for k, v in doc["services"].items() if k != "nex-mo"},
            },
            "coverage",
        ),
        (
            lambda doc: {
                **doc,
                "services": {
                    **doc["services"],
                    "openbao-data-init": {
                        **doc["services"]["openbao-data-init"],
                        "image": "latest",
                    },
                },
            },
            "initializer image",
        ),
        (
            lambda doc: {
                **doc,
                "services": {
                    **doc["services"],
                    "openbao": {**doc["services"]["openbao"], "image": "latest"},
                },
            },
            "OpenBao",
        ),
        (
            lambda doc: {
                **doc,
                "services": {
                    **doc["services"],
                    "openbao-data-init": {
                        **doc["services"]["openbao-data-init"],
                        "cap_add": [],
                    },
                },
            },
            "initializer",
        ),
        (
            lambda doc: {
                **doc,
                "networks": {
                    **doc["networks"],
                    "control": {"internal": False},
                },
            },
            "network",
        ),
        (
            lambda doc: {
                **doc,
                "services": {
                    **doc["services"],
                    "traefik": {**doc["services"]["traefik"], "image": "latest"},
                },
            },
            "Traefik",
        ),
        (
            lambda doc: {
                **doc,
                "services": {
                    **doc["services"],
                    "nex-oa": {**doc["services"]["nex-oa"], "image": "latest"},
                },
            },
            "immutable",
        ),
    ],
)
def test_compose_contract_rejects_structural_drift(tmp_path, mutation, message) -> None:
    root = _copied_compose_root(tmp_path)
    compose_path = root / "deployment/compose/s143-staging.compose.yaml"
    document = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    compose_path.write_text(yaml.safe_dump(mutation(document)), encoding="utf-8")
    with pytest.raises(S143StagingError, match=message):
        validate_s143_compose_assets(root)


@pytest.mark.parametrize(
    ("path", "old", "new", "message"),
    [
        (
            "deployment/compose/s143-staging.compose.yaml",
            "name: nex-platform-s143",
            "name: nex-platform-s143\nprivileged: true",
            "privilege",
        ),
        (
            "deployment/compose/s143-staging.compose.yaml",
            "127.0.0.1:8200:8200",
            "8200:8200",
            "loopback",
        ),
        (
            "deployment/compose/s143-staging.compose.yaml",
            "NEX_MO_VLLM_BASE_URL: https://generation.nex-staging.test:8443",
            "NEX_MO_VLLM_BASE_URL: https://generation.nex-staging.test:8443/v1",
            "generation provider",
        ),
        (
            "deployment/compose/openbao/config.hcl",
            'storage "raft"',
            'storage "file"',
            "durable",
        ),
        (
            "deployment/compose/traefik/dynamic.yaml",
            "Host(`oa.nex-staging.test`)",
            "Host(`missing.nex-staging.test`)",
            "route",
        ),
        (
            "deployment/compose/s143-staging.compose.yaml",
            "secret://openbao/nex-platform/staging/nex-oa/NEX_OA_DATABASE_URL@",
            "secret://other/nex-platform/staging/nex-oa/NEX_OA_DATABASE_URL@",
            "reference",
        ),
    ],
)
def test_compose_contract_rejects_textual_boundary_drift(
    tmp_path, path, old, new, message
) -> None:
    root = _copied_compose_root(tmp_path)
    target = root / path
    text = target.read_text(encoding="utf-8")
    assert old in text
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(S143StagingError, match=message):
        validate_s143_compose_assets(root)


def test_runtime_directory_contains_short_lived_openbao_bootstrap_pki(tmp_path) -> None:
    runtime = tmp_path / "runtime"
    projection = prepare_staging_runtime_directory(
        runtime,
        now=datetime(2026, 10, 7, tzinfo=UTC),
    )
    certificate = x509.load_pem_x509_certificate(
        (runtime / "tls/openbao.crt").read_bytes()
    )

    assert projection["status"] == "PREPARED"
    assert {name.value for name in certificate.subject} == {"openbao"}
    assert len(tuple((runtime / "credentials").iterdir())) == len(OWNERS) * 2
    assert (runtime / "tls/openbao.key").stat().st_mode & 0o777 == 0o644
    with pytest.raises(S143StagingError, match="empty"):
        prepare_staging_runtime_directory(runtime)
    with pytest.raises(S143StagingError, match="absolute"):
        prepare_staging_runtime_directory(Path("relative"))


def test_openbao_initialization_configuration_and_credentials_are_metadata_only(
    tmp_path,
) -> None:
    runtime = tmp_path / "runtime"
    prepare_staging_runtime_directory(runtime)
    client = FakeClient()
    bootstrap = initialize_openbao(client, runtime)
    result = configure_openbao_staging(
        client,
        root_token=bootstrap.root_token,
        root=ROOT,
        runtime_dir=runtime,
        secret_values=_secret_values(),
    )

    assert result == {
        "schema_version": "s143_external_staging.v1",
        "status": "CONFIGURED",
        "secret_count": 20,
        "owner_count": 5,
        "secret_versions": [1],
        "certificate_serial": "01:23",
        "raw_secret_values_included": False,
    }
    assert (runtime / "admin/root-token").stat().st_mode & 0o777 == 0o600
    assert (runtime / "tls/platform.key").stat().st_mode & 0o777 == 0o644
    assert all(
        (runtime / f"credentials/{owner}.secret-id").read_text().startswith(
            "secret-id-"
        )
        for owner in OWNERS
    )
    assert not any(value in str(result) for value in _secret_values().values())


def test_openbao_active_wait_handles_election_and_fails_closed(monkeypatch) -> None:
    class ElectionClient(FakeClient):
        def __init__(self, leaders):
            super().__init__()
            self.leaders = iter(leaders)

        def request(self, method, path, *, token=None, payload=None):
            if path == "/v1/sys/leader":
                return next(self.leaders)
            return super().request(method, path, token=token, payload=payload)

    sleeps = []
    monkeypatch.setattr("nex_runtime.s143_staging.time.sleep", sleeps.append)
    result = _wait_for_openbao_active(
        ElectionClient(
            [
                {"ha_enabled": True, "is_self": False},
                {"ha_enabled": True, "is_self": True},
            ]
        ),
        root_token="root-token-12345678",
        attempts=2,
        interval_seconds=0.25,
    )

    assert result == {"status": "ACTIVE", "attempts": 2}
    assert sleeps == [0.25]
    with pytest.raises(S143StagingError, match="writable active"):
        _wait_for_openbao_active(
            ElectionClient([{"ha_enabled": True, "is_self": False}]),
            root_token="root-token-12345678",
            attempts=1,
            interval_seconds=0,
        )
    with pytest.raises(S143StagingError, match="policy"):
        _wait_for_openbao_active(
            FakeClient(),
            root_token="root-token-12345678",
            attempts=0,
        )


def test_openbao_initialization_wait_handles_transport_race(monkeypatch) -> None:
    class StartupClient(FakeClient):
        def __init__(self, statuses):
            super().__init__()
            self.statuses = iter(statuses)

        def request(self, method, path, *, token=None, payload=None):
            if path == "/v1/sys/init" and method == "GET":
                status = next(self.statuses)
                if isinstance(status, Exception):
                    raise status
                return status
            return super().request(method, path, token=token, payload=payload)

    sleeps = []
    monkeypatch.setattr("nex_runtime.s143_staging.time.sleep", sleeps.append)
    result = _wait_for_openbao_uninitialized(
        StartupClient(
            [
                S143StagingError("transport"),
                {"initialized": False},
            ]
        ),
        attempts=2,
        interval_seconds=0.2,
    )

    assert result == {"status": "UNINITIALIZED", "attempts": 2}
    assert sleeps == [0.2]
    with pytest.raises(S143StagingError, match="already"):
        _wait_for_openbao_uninitialized(
            StartupClient([{"initialized": True}]),
            attempts=1,
            interval_seconds=0,
        )
    with pytest.raises(S143StagingError, match="did not become ready"):
        _wait_for_openbao_uninitialized(
            StartupClient([{}]),
            attempts=1,
            interval_seconds=0,
        )
    with pytest.raises(S143StagingError, match="policy"):
        _wait_for_openbao_uninitialized(FakeClient(), attempts=0)


def test_configuration_rejects_secret_coverage_and_invalid_approle_response(
    tmp_path,
) -> None:
    runtime = tmp_path / "runtime"
    prepare_staging_runtime_directory(runtime)
    client = FakeClient()
    with pytest.raises(S143StagingError, match="coverage"):
        configure_openbao_staging(
            client,
            root_token="root-token-12345678",
            root=ROOT,
            runtime_dir=runtime,
            secret_values={},
        )

    class InvalidClient(FakeClient):
        def request(self, method, path, *, token=None, payload=None):
            if path.endswith("/role-id"):
                return {"data": {}}
            return super().request(method, path, token=token, payload=payload)

    with pytest.raises(S143StagingError, match="AppRole"):
        refresh_openbao_approle_credentials(
            InvalidClient(),
            root_token="root-token-12345678",
            runtime_dir=runtime,
        )


def test_secret_generation_rejects_invalid_kv_version() -> None:
    bindings = tuple(
        binding
        for binding in load_production_configuration_manifest(ROOT).bindings
        if binding.input_kind == "external_secret_reference"
    )

    class InvalidClient(FakeClient):
        def request(self, method, path, *, token=None, payload=None):
            return {"data": {"version": 0}}

    with pytest.raises(S143StagingError, match="version"):
        write_openbao_secret_generation(
            InvalidClient(),
            root_token="root-token-12345678",
            bindings=bindings,
            secret_values=_secret_values(),
        )


def test_admin_transport_accepts_empty_and_json_responses(tmp_path, monkeypatch) -> None:
    ca = tmp_path / "ca.crt"
    ca.write_text(
        (ROOT / "tests/fixtures/certs/test-ca.pem").read_text(encoding="utf-8")
        if (ROOT / "tests/fixtures/certs/test-ca.pem").exists()
        else "invalid",
        encoding="utf-8",
    )
    client = object.__new__(OpenBaoAdminClient)
    client._address = "https://openbao:8200"
    client._context = object()
    client._timeout_seconds = 1

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            return self.body

    monkeypatch.setattr(
        "nex_runtime.s143_staging.urlopen",
        lambda *args, **kwargs: Response(json.dumps({"ok": True}).encode()),
    )
    assert client.request("GET", "/v1/sys/health") == {"ok": True}
    monkeypatch.setattr(
        "nex_runtime.s143_staging.urlopen",
        lambda *args, **kwargs: Response(b""),
    )
    assert client.request("POST", "/v1/test", payload={}) == {}
    with pytest.raises(S143StagingError, match="path"):
        client.request("GET", "/wrong")


def test_admin_client_constructor_and_transport_fail_closed(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    prepare_staging_runtime_directory(runtime)
    ca_file = runtime / "tls/openbao-ca.crt"
    assert isinstance(
        OpenBaoAdminClient(
            "https://openbao:8200",
            ca_certificate_file=ca_file,
        ),
        OpenBaoAdminClient,
    )
    with pytest.raises(S143StagingError, match="endpoint"):
        OpenBaoAdminClient("http://openbao:8200", ca_certificate_file=ca_file)
    with pytest.raises(S143StagingError, match="endpoint"):
        OpenBaoAdminClient(
            "https://openbao:8200",
            ca_certificate_file=ca_file,
            timeout_seconds=0,
        )
    with pytest.raises(S143StagingError, match="CA"):
        OpenBaoAdminClient(
            "https://openbao:8200",
            ca_certificate_file=tmp_path / "missing",
        )

    client = object.__new__(OpenBaoAdminClient)
    client._address = "https://openbao:8200"
    client._context = object()
    client._timeout_seconds = 1
    monkeypatch.setattr(
        "nex_runtime.s143_staging.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("private")),
    )
    with pytest.raises(S143StagingError, match="request failed"):
        client.request("GET", "/v1/test")


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"x" * 2_097_153, "too large"),
        (b"{", "response is invalid"),
        (b"[]", "response is invalid"),
    ],
)
def test_admin_transport_rejects_invalid_responses(body, message, monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            return body

    client = object.__new__(OpenBaoAdminClient)
    client._address = "https://openbao:8200"
    client._context = object()
    client._timeout_seconds = 1
    monkeypatch.setattr(
        "nex_runtime.s143_staging.urlopen",
        lambda *args, **kwargs: Response(),
    )
    with pytest.raises(S143StagingError, match=message):
        client.request("GET", "/v1/test")


def test_openbao_initialization_and_pki_fail_closed(tmp_path) -> None:
    runtime = tmp_path / "runtime"
    prepare_staging_runtime_directory(runtime)

    class InvalidInitialization(FakeClient):
        def request(self, method, path, *, token=None, payload=None):
            if path == "/v1/sys/init" and method == "PUT":
                return {"root_token": "short", "keys_base64": []}
            return super().request(method, path, token=token, payload=payload)

    with pytest.raises(S143StagingError, match="initialization"):
        initialize_openbao(InvalidInitialization(), runtime)

    class InvalidPki(FakeClient):
        def request(self, method, path, *, token=None, payload=None):
            if path == "/v1/pki/issue/nex-platform-staging":
                return {"data": {"certificate": "invalid"}}
            return super().request(method, path, token=token, payload=payload)

    from nex_runtime.s143_staging import issue_openbao_platform_certificate

    with pytest.raises(S143StagingError, match="PKI issue"):
        issue_openbao_platform_certificate(
            InvalidPki(),
            root_token="root-token-12345678",
            runtime_dir=runtime,
        )
    with pytest.raises(S143StagingError, match="subject alternative names"):
        issue_openbao_platform_certificate(
            FakeClient(),
            root_token="root-token-12345678",
            runtime_dir=runtime,
            subject_alt_names=("invalid,hostname",),
        )
    client = FakeClient()
    issue_openbao_platform_certificate(
        client,
        root_token="root-token-12345678",
        runtime_dir=runtime,
        subject_alt_names=("oa.nex-staging.test", "id.nex-staging.test"),
    )
    assert client.requests[-1][3]["alt_names"] == (
        "oa.nex-staging.test,id.nex-staging.test"
    )
