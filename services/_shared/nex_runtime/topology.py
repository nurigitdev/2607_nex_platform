from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


RUNTIME_PROFILES = (
    "local_mock",
    "local_live",
    "test",
    "staging_live",
    "production",
)
PROCESS_KINDS = ("api", "web", "worker", "daemon")
PERSISTENCE_MODES = ("memory", "postgres")
PROVIDER_MODES = ("mock", "live")
TRUST_MODES = ("test_mock", "signed")
AG_PROJECTION_MODES = ("memory", "api", "legacy_postgres")


class RuntimeManifestError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeModes:
    persistence: str
    provider: str
    trust: str
    ag_projection: str


@dataclass(frozen=True)
class RuntimeEndpoint:
    service_id: str
    base_url: str


@dataclass(frozen=True)
class RuntimeProbe:
    path: str
    timeout_seconds: float = 2.0


@dataclass(frozen=True)
class RuntimeProcess:
    process_id: str
    owner: str
    kind: str
    command: tuple[str, ...]
    host: str | None = None
    port: int | None = None
    dependencies: tuple[str, ...] = ()
    liveness_probe: RuntimeProbe | None = None
    readiness_probe: RuntimeProbe | None = None
    environment_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlatformRuntimeManifest:
    schema_version: str
    profile: str
    modes: RuntimeModes
    endpoints: tuple[RuntimeEndpoint, ...]
    processes: tuple[RuntimeProcess, ...]
    startup_timeout_seconds: float = 60.0
    shutdown_timeout_seconds: float = 10.0


def validate_runtime_manifest(manifest: PlatformRuntimeManifest) -> None:
    errors: list[str] = []
    if manifest.schema_version != "platform_runtime_manifest.v1":
        errors.append("schema_version must be platform_runtime_manifest.v1")
    if manifest.profile not in RUNTIME_PROFILES:
        errors.append(f"unsupported runtime profile: {manifest.profile}")
    _validate_modes(manifest.modes, errors)
    if manifest.startup_timeout_seconds <= 0:
        errors.append("startup_timeout_seconds must be positive")
    if manifest.shutdown_timeout_seconds <= 0:
        errors.append("shutdown_timeout_seconds must be positive")

    endpoint_ids: set[str] = set()
    for endpoint in manifest.endpoints:
        if not endpoint.service_id:
            errors.append("endpoint service_id must not be empty")
        elif endpoint.service_id in endpoint_ids:
            errors.append(f"duplicate endpoint service_id: {endpoint.service_id}")
        endpoint_ids.add(endpoint.service_id)
        if not _is_safe_http_base_url(endpoint.base_url):
            errors.append(f"invalid endpoint base_url for {endpoint.service_id}")

    process_ids: set[str] = set()
    bound_addresses: set[tuple[str, int]] = set()
    for process in manifest.processes:
        if not process.process_id:
            errors.append("process_id must not be empty")
        elif process.process_id in process_ids:
            errors.append(f"duplicate process_id: {process.process_id}")
        process_ids.add(process.process_id)
        if not process.owner:
            errors.append(f"process owner must not be empty: {process.process_id}")
        if process.kind not in PROCESS_KINDS:
            errors.append(f"unsupported process kind for {process.process_id}")
        if not process.command or any(not item for item in process.command):
            errors.append(f"process command must not be empty: {process.process_id}")
        _validate_process_network(process, bound_addresses, errors)
        _validate_probe(process.process_id, "liveness", process.liveness_probe, errors)
        _validate_probe(process.process_id, "readiness", process.readiness_probe, errors)
        if len(set(process.environment_names)) != len(process.environment_names):
            errors.append(f"duplicate environment name: {process.process_id}")
        if any(not name.startswith("NEX_") for name in process.environment_names):
            errors.append(f"invalid environment name: {process.process_id}")

    for process in manifest.processes:
        for dependency in process.dependencies:
            if dependency == process.process_id:
                errors.append(f"self dependency: {process.process_id}")
            elif dependency not in process_ids:
                errors.append(
                    f"unknown dependency for {process.process_id}: {dependency}"
                )
        if len(set(process.dependencies)) != len(process.dependencies):
            errors.append(f"duplicate dependency: {process.process_id}")

    if errors:
        raise RuntimeManifestError("; ".join(errors))


def runtime_manifest_public_projection(
    manifest: PlatformRuntimeManifest,
) -> dict[str, Any]:
    validate_runtime_manifest(manifest)
    return {
        "schema_version": manifest.schema_version,
        "profile": manifest.profile,
        "modes": {
            "persistence": manifest.modes.persistence,
            "provider": manifest.modes.provider,
            "trust": manifest.modes.trust,
            "ag_projection": manifest.modes.ag_projection,
        },
        "endpoints": [
            {"service_id": item.service_id, "base_url": item.base_url}
            for item in manifest.endpoints
        ],
        "processes": [
            {
                "process_id": item.process_id,
                "owner": item.owner,
                "kind": item.kind,
                "host": item.host,
                "port": item.port,
                "dependencies": list(item.dependencies),
                "liveness_path": (
                    item.liveness_probe.path if item.liveness_probe else None
                ),
                "readiness_path": (
                    item.readiness_probe.path if item.readiness_probe else None
                ),
                "environment_name_count": len(item.environment_names),
            }
            for item in manifest.processes
        ],
        "startup_timeout_seconds": manifest.startup_timeout_seconds,
        "shutdown_timeout_seconds": manifest.shutdown_timeout_seconds,
    }


def _validate_modes(modes: RuntimeModes, errors: list[str]) -> None:
    for name, value, choices in (
        ("persistence", modes.persistence, PERSISTENCE_MODES),
        ("provider", modes.provider, PROVIDER_MODES),
        ("trust", modes.trust, TRUST_MODES),
        ("ag_projection", modes.ag_projection, AG_PROJECTION_MODES),
    ):
        if value not in choices:
            errors.append(f"unsupported {name} mode: {value}")


def _validate_process_network(
    process: RuntimeProcess,
    bound_addresses: set[tuple[str, int]],
    errors: list[str],
) -> None:
    if process.kind in {"api", "web"}:
        if not process.host or process.port is None:
            errors.append(f"network process requires host and port: {process.process_id}")
            return
        if not 1 <= process.port <= 65535:
            errors.append(f"invalid process port: {process.process_id}")
            return
        address = (process.host, process.port)
        if address in bound_addresses:
            errors.append(f"duplicate process address: {process.host}:{process.port}")
        bound_addresses.add(address)
    elif process.host is not None or process.port is not None:
        errors.append(f"background process must not bind a port: {process.process_id}")


def _validate_probe(
    process_id: str,
    probe_name: str,
    probe: RuntimeProbe | None,
    errors: list[str],
) -> None:
    if probe is None:
        return
    if not probe.path.startswith("/"):
        errors.append(f"invalid {probe_name} probe path: {process_id}")
    if probe.timeout_seconds <= 0:
        errors.append(f"invalid {probe_name} probe timeout: {process_id}")


def _is_safe_http_base_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )
