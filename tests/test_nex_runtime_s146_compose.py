from __future__ import annotations

from pathlib import Path
import shutil

import pytest
import yaml

import nex_runtime.s146_compose as compose_module
from nex_runtime.s146_compose import S146ComposeError, validate_s146_compose_assets


ROOT = Path(__file__).resolve().parents[1]


def _copy_assets(tmp_path: Path) -> Path:
    for relative in (
        "deployment/compose/s143-staging.compose.yaml",
        "deployment/compose/s144-staging.override.yaml",
        "deployment/compose/s146-object-storage.override.yaml",
        "deployment/compose/traefik/dynamic.yaml",
        "deployment/compose/traefik/s144-dynamic.yaml",
        "deployment/compose/traefik/s146-dynamic.yaml",
        "deployment/compose/openbao/config.hcl",
        "deployment/compose/openbao/s144-config.hcl",
        "deployment/security/production-configuration.yaml",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return tmp_path


def test_repository_s146_compose_assets_are_valid() -> None:
    result = validate_s146_compose_assets(ROOT)
    assert result == {
        "schema_version": "s146_object_storage_compose.v1",
        "state": "VALID",
        "orchestrator": "docker-compose-single-host",
        "rustfs_image": compose_module.RUSTFS_IMAGE,
        "rustfs_release": "1.0.1",
        "runtime_user": "10001:10001",
        "application_bucket_count": 2,
        "application_credential_pair_count": 2,
        "secret_reference_count": 20,
        "public_connection_count": 11,
        "tls_route_count": 1,
        "internal_network_count": 1,
        "durable_volume_count": 1,
        "console_enabled": False,
        "host_port_count": 0,
        "raw_secret_values_included": False,
    }


@pytest.mark.parametrize(
    ("relative", "old", "new", "message"),
    [
        (
            "deployment/compose/s146-object-storage.override.yaml",
            compose_module.RUSTFS_IMAGE,
            "rustfs/rustfs:latest",
            "RustFS runtime hardening drift",
        ),
        (
            "deployment/compose/s146-object-storage.override.yaml",
            'user: "10001:10001"',
            'user: "0:0"',
            "RustFS runtime hardening drift",
        ),
        (
            "deployment/compose/s146-object-storage.override.yaml",
            "RUSTFS_ACCESS_KEY_FILE:",
            "RUSTFS_ACCESS_KEY:",
            "S146 privilege or raw-secret boundary drift",
        ),
        (
            "deployment/compose/s146-object-storage.override.yaml",
            "internal: true",
            "internal: false",
            "RustFS internal network boundary drift",
        ),
        (
            "deployment/compose/traefik/s146-dynamic.yaml",
            'url: "http://rustfs:9000"',
            'url: "http://rustfs:9001"',
            "S146 Traefik object route drift",
        ),
        (
            "deployment/compose/s146-object-storage.override.yaml",
            "NEX_CX_OBJECT_STORAGE_BUCKET: nex-cx-private",
            "NEX_CX_OBJECT_STORAGE_BUCKET: nex-ae-private",
            "NEX_CX object-storage environment drift",
        ),
    ],
)
def test_s146_compose_drift_is_rejected(
    tmp_path: Path, relative: str, old: str, new: str, message: str
) -> None:
    root = _copy_assets(tmp_path)
    path = root / relative
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(S146ComposeError, match=message):
        validate_s146_compose_assets(root)


def test_s146_compose_unreadable_asset_is_rejected(tmp_path: Path) -> None:
    root = _copy_assets(tmp_path)
    (root / compose_module.S146_DYNAMIC_PATH).unlink()
    with pytest.raises(S146ComposeError, match="assets are unreadable"):
        validate_s146_compose_assets(root)


def test_s146_compose_rejects_invalid_document_and_service_coverage(tmp_path: Path) -> None:
    root = _copy_assets(tmp_path)
    override = root / compose_module.S146_OVERRIDE_PATH
    override.write_text("[]\n", encoding="utf-8")
    with pytest.raises(S146ComposeError, match="assets are invalid"):
        validate_s146_compose_assets(root)

    root = _copy_assets(tmp_path / "coverage")
    override = root / compose_module.S146_OVERRIDE_PATH
    document = yaml.safe_load(override.read_text(encoding="utf-8"))
    document["services"].pop("nex-mo")
    override.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(S146ComposeError, match="service override coverage"):
        validate_s146_compose_assets(root)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "credentials/rustfs-root.secret-key",
            "credentials/changed.secret-key",
            "root secret file boundary",
        ),
        ("rustfs-data: {}", "other-data: {}", "durable volume boundary"),
        ("RUSTFS_ADDRESS: 0.0.0.0:9000", "RUSTFS_ADDRESS: 127.0.0.1:9000", "runtime environment"),
        ("http://127.0.0.1:9000/health", "http://127.0.0.1:9000/wrong", "health boundary"),
        ("- object.nex-staging.test", "- changed.nex-staging.test", "Traefik object route override"),
        ("${NEX_S146_CX_READ_MODE:-OBJECT_ONLY}", "OBJECT_FIRST", "read-mode gate"),
        ("${NEX_S146_AE_MIGRATION_ADMITTED:-false}", "true", "admission gate"),
        ("networks: [service, control, object-storage]", "networks: [service, control]", "object-storage network"),
        ("condition: service_healthy", "condition: service_started", "RustFS readiness dependency"),
        ("NEX_AE_OBJECT_STORAGE_ENDPOINT: https://object.nex-staging.test:8443", "NEX_AE_OBJECT_STORAGE_ENDPOINT: https://changed.test", "shared object environment"),
    ],
)
def test_s146_additional_topology_drift_is_rejected(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    root = _copy_assets(tmp_path)
    path = root / compose_module.S146_OVERRIDE_PATH
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(S146ComposeError, match=message):
        validate_s146_compose_assets(root)


def test_s146_helper_shape_and_manifest_count_guards(monkeypatch) -> None:
    with pytest.raises(S146ComposeError, match="RustFS service is invalid"):
        compose_module._validate_rustfs(None)
    with pytest.raises(S146ComposeError, match="Traefik override is invalid"):
        compose_module._validate_traefik(None, {})
    with pytest.raises(S146ComposeError, match="NEX_CX object-storage override"):
        compose_module._validate_owner(None, prefix="NEX_CX", bucket="nex-cx-private")

    monkeypatch.setattr(compose_module, "PRODUCTION_SECRET_BINDING_COUNT", 0)
    with pytest.raises(S146ComposeError, match="production configuration coverage"):
        validate_s146_compose_assets(ROOT)
