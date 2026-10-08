from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

import yaml

from .production_configuration import (
    PRODUCTION_PUBLIC_CONNECTION_COUNT,
    PRODUCTION_SECRET_BINDING_COUNT,
    load_production_configuration_manifest,
)
from .s144_staging import validate_s144_compose_assets


S146_COMPOSE_SCHEMA_VERSION = "s146_object_storage_compose.v1"
S146_OVERRIDE_PATH = "deployment/compose/s146-object-storage.override.yaml"
S146_DYNAMIC_PATH = "deployment/compose/traefik/s146-dynamic.yaml"
RUSTFS_IMAGE = (
    "rustfs/rustfs:1.0.1@"
    "sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c"
)
RUSTFS_RUNTIME_USER = "10001:10001"
OBJECT_STORAGE_HOST = "object.nex-staging.test"


class S146ComposeError(ValueError):
    pass


def validate_s146_compose_assets(root: Path) -> dict[str, Any]:
    validate_s144_compose_assets(root)
    try:
        override_text = (root / S146_OVERRIDE_PATH).read_text(encoding="utf-8")
        override = yaml.safe_load(override_text)
        dynamic_text = (root / S146_DYNAMIC_PATH).read_text(encoding="utf-8")
        dynamic = yaml.safe_load(dynamic_text)
        manifest = load_production_configuration_manifest(root)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise S146ComposeError("S146 Compose assets are unreadable") from exc
    if not isinstance(override, Mapping) or not isinstance(dynamic, Mapping):
        raise S146ComposeError("S146 Compose assets are invalid")
    services = override.get("services")
    if not isinstance(services, Mapping) or set(services) != {
        "traefik",
        "rustfs",
        "nex-ae-api",
        "nex-cx",
        "nex-oa",
        "nex-ag",
        "nex-mo",
    }:
        raise S146ComposeError("S146 service override coverage drift")
    forbidden = (
        "/var/run/docker.sock",
        "privileged: true",
        "network_mode: host",
        "RUSTFS_ACCESS_KEY:",
        "RUSTFS_SECRET_KEY:",
    )
    if any(marker in override_text for marker in forbidden):
        raise S146ComposeError("S146 privilege or raw-secret boundary drift")
    _validate_rustfs(services["rustfs"])
    _validate_traefik(services["traefik"], dynamic)
    _validate_owner(services["nex-cx"], prefix="NEX_CX", bucket="nex-cx-private")
    _validate_owner(
        services["nex-ae-api"], prefix="NEX_AE", bucket="nex-ae-private"
    )
    _validate_shared_object_environment(services)
    secrets = override.get("secrets")
    expected_secret_files = {
        "rustfs_root_access_key": (
            "${NEX_S143_RUNTIME_DIR:?runtime directory is required}/"
            "credentials/rustfs-root.access-key"
        ),
        "rustfs_root_secret_key": (
            "${NEX_S143_RUNTIME_DIR:?runtime directory is required}/"
            "credentials/rustfs-root.secret-key"
        ),
    }
    if not isinstance(secrets, Mapping) or {
        name: item.get("file") if isinstance(item, Mapping) else None
        for name, item in secrets.items()
    } != expected_secret_files:
        raise S146ComposeError("RustFS root secret file boundary drift")
    if override.get("networks") != {"object-storage": {"internal": True}}:
        raise S146ComposeError("RustFS internal network boundary drift")
    if override.get("volumes") != {"rustfs-data": {}}:
        raise S146ComposeError("RustFS durable volume boundary drift")
    secret_count = sum(
        binding.input_kind == "external_secret_reference"
        for binding in manifest.bindings
    )
    connection_count = sum(
        binding.input_kind == "public_connection" for binding in manifest.bindings
    )
    if (
        secret_count != PRODUCTION_SECRET_BINDING_COUNT
        or connection_count != PRODUCTION_PUBLIC_CONNECTION_COUNT
    ):
        raise S146ComposeError("S146 production configuration coverage drift")
    return {
        "schema_version": S146_COMPOSE_SCHEMA_VERSION,
        "state": "VALID",
        "orchestrator": "docker-compose-single-host",
        "rustfs_image": RUSTFS_IMAGE,
        "rustfs_release": "1.0.1",
        "runtime_user": RUSTFS_RUNTIME_USER,
        "application_bucket_count": 2,
        "application_credential_pair_count": 2,
        "secret_reference_count": secret_count,
        "public_connection_count": connection_count,
        "tls_route_count": 1,
        "internal_network_count": 1,
        "durable_volume_count": 1,
        "console_enabled": False,
        "host_port_count": 0,
        "raw_secret_values_included": False,
    }


def _validate_rustfs(service: Any) -> None:
    if not isinstance(service, Mapping):
        raise S146ComposeError("RustFS service is invalid")
    health = service.get("healthcheck")
    environment = service.get("environment")
    runtime_snapshot = {
        "image": service.get("image"),
        "user": service.get("user"),
        "restart": service.get("restart"),
        "read_only": service.get("read_only"),
        "cap_drop": service.get("cap_drop"),
        "security_opt": service.get("security_opt"),
        "tmpfs": service.get("tmpfs"),
        "volumes": service.get("volumes"),
        "secrets": service.get("secrets"),
        "networks": service.get("networks"),
        "host_ports_present": "ports" in service,
    }
    expected_runtime = {
        "image": RUSTFS_IMAGE,
        "user": RUSTFS_RUNTIME_USER,
        "restart": "no",
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "tmpfs": ["/tmp", "/logs"],
        "volumes": ["rustfs-data:/data"],
        "secrets": ["rustfs_root_access_key", "rustfs_root_secret_key"],
        "networks": ["object-storage"],
        "host_ports_present": False,
    }
    if runtime_snapshot != expected_runtime:
        raise S146ComposeError("RustFS runtime hardening drift")
    required_environment = {
        "RUSTFS_VOLUMES": "/data",
        "RUSTFS_ADDRESS": "0.0.0.0:9000",
        "RUSTFS_CONSOLE_ENABLE": "false",
        "RUSTFS_ACCESS_KEY_FILE": "/run/secrets/rustfs_root_access_key",
        "RUSTFS_SECRET_KEY_FILE": "/run/secrets/rustfs_root_secret_key",
        "RUSTFS_OBS_LOGGER_LEVEL": "warn",
    }
    if not isinstance(environment, Mapping) or dict(environment) != required_environment:
        raise S146ComposeError("RustFS runtime environment drift")
    health_snapshot = (
        {"test": health.get("test"), "start_period": health.get("start_period")}
        if isinstance(health, Mapping)
        else None
    )
    if health_snapshot != {
        "test": ["CMD", "curl", "-fsS", "http://127.0.0.1:9000/health"],
        "start_period": "10s",
    }:
        raise S146ComposeError("RustFS health boundary drift")


def _validate_traefik(service: Any, dynamic: Mapping[str, Any]) -> None:
    if not isinstance(service, Mapping):
        raise S146ComposeError("S146 Traefik override is invalid")
    aliases = service.get("networks", {}).get("service", {}).get("aliases", ())
    route_override = {
        "volumes": service.get("volumes"),
        "object_alias_present": OBJECT_STORAGE_HOST in aliases,
        "object_network": service.get("networks", {}).get("object-storage"),
    }
    if route_override != {
        "volumes": [
            "../compose/traefik/s146-dynamic.yaml:/etc/traefik/dynamic.yaml:ro"
        ],
        "object_alias_present": True,
        "object_network": {},
    }:
        raise S146ComposeError("S146 Traefik object route override drift")
    http = dynamic.get("http")
    router = http.get("routers", {}).get("object-storage", {}) if isinstance(http, Mapping) else {}
    upstream = http.get("services", {}).get("object-storage", {}) if isinstance(http, Mapping) else {}
    rendered = str(router)
    route_snapshot = {
        "host_rule_present": f"Host(`{OBJECT_STORAGE_HOST}`)" in rendered,
        "entry_points": router.get("entryPoints"),
        "tls": router.get("tls"),
        "servers": upstream.get("loadBalancer", {}).get("servers"),
        "console_route_present": bool(re.search(r"https?://rustfs:9001", str(dynamic))),
    }
    if route_snapshot != {
        "host_rule_present": True,
        "entry_points": ["websecure"],
        "tls": {},
        "servers": [{"url": "http://rustfs:9000"}],
        "console_route_present": False,
    }:
        raise S146ComposeError("S146 Traefik object route drift")


def _validate_owner(service: Any, *, prefix: str, bucket: str) -> None:
    if not isinstance(service, Mapping):
        raise S146ComposeError(f"{prefix} object-storage override is invalid")
    environment = service.get("environment")
    expected = {
        "NEX_CONFIG_GENERATION": "config:s146-staging.1",
        f"{prefix.replace('NEX_', 'NEX_')}_PRIVATE_STORAGE_MODE": "S3",
        f"{prefix}_OBJECT_STORAGE_BACKEND": "S3",
        f"{prefix}_OBJECT_STORAGE_BUCKET": bucket,
        f"{prefix}_OBJECT_STORAGE_REGION": "us-east-1",
        f"{prefix}_OBJECT_STORAGE_CA_BUNDLE": "/run/secrets/platform_ca",
        f"{prefix}_OBJECT_STORAGE_ALLOW_INSECURE": "false",
    }
    configured = (
        {name: environment.get(name) for name in expected}
        if isinstance(environment, Mapping)
        else None
    )
    if configured != expected:
        raise S146ComposeError(f"{prefix} object-storage environment drift")
    read_mode = str(environment.get(f"{prefix}_OBJECT_STORAGE_READ_MODE") or "")
    if read_mode != f"${{NEX_S146_{prefix.removeprefix('NEX_')}_READ_MODE:-OBJECT_ONLY}}":
        raise S146ComposeError(f"{prefix} object-storage read-mode gate drift")
    owner = prefix.removeprefix("NEX_")
    admission = {
        "migration": environment.get(f"{prefix}_OBJECT_STORAGE_MIGRATION_ADMITTED"),
        "rollback": environment.get(f"{prefix}_OBJECT_STORAGE_ROLLBACK_ADMITTED"),
    }
    if admission != {
        "migration": f"${{NEX_S146_{owner}_MIGRATION_ADMITTED:-false}}",
        "rollback": f"${{NEX_S146_{owner}_ROLLBACK_ADMITTED:-false}}",
    }:
        raise S146ComposeError(f"{prefix} object-storage admission gate drift")
    if service.get("networks") != ["service", "control", "object-storage"]:
        raise S146ComposeError(f"{prefix} object-storage network drift")
    if service.get("depends_on") != {"rustfs": {"condition": "service_healthy"}}:
        raise S146ComposeError(f"{prefix} RustFS readiness dependency drift")


def _validate_shared_object_environment(services: Mapping[str, Any]) -> None:
    required = {
        "NEX_CX_OBJECT_STORAGE_ACCESS_KEY_REF": (
            "secret://openbao/nex-platform/staging/nex-cx/"
            "NEX_CX_OBJECT_STORAGE_ACCESS_KEY@${NEX_S143_SECRET_VERSION:-v1}"
        ),
        "NEX_CX_OBJECT_STORAGE_SECRET_KEY_REF": (
            "secret://openbao/nex-platform/staging/nex-cx/"
            "NEX_CX_OBJECT_STORAGE_SECRET_KEY@${NEX_S143_SECRET_VERSION:-v1}"
        ),
        "NEX_AE_OBJECT_STORAGE_ACCESS_KEY_REF": (
            "secret://openbao/nex-platform/staging/nex-ae-api/"
            "NEX_AE_OBJECT_STORAGE_ACCESS_KEY@${NEX_S143_SECRET_VERSION:-v1}"
        ),
        "NEX_AE_OBJECT_STORAGE_SECRET_KEY_REF": (
            "secret://openbao/nex-platform/staging/nex-ae-api/"
            "NEX_AE_OBJECT_STORAGE_SECRET_KEY@${NEX_S143_SECRET_VERSION:-v1}"
        ),
        "NEX_CX_OBJECT_STORAGE_ENDPOINT": "https://object.nex-staging.test:8443",
        "NEX_AE_OBJECT_STORAGE_ENDPOINT": "https://object.nex-staging.test:8443",
    }
    for service_id in ("nex-oa", "nex-ag", "nex-ae-api", "nex-cx", "nex-mo"):
        environment = services[service_id].get("environment")
        configured = (
            {name: environment.get(name) for name in required}
            if isinstance(environment, Mapping)
            else None
        )
        if configured != required:
            raise S146ComposeError("S146 shared object environment drift")
