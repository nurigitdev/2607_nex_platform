from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import os
import sys
from urllib.parse import urlsplit

from .runtime_profiles import (
    DATABASE_ENV_NAMES,
    TEST_DATABASE_ENV_NAMES,
    RuntimeProfileResolution,
    resolve_runtime_profile,
)
from .service_endpoints import SERVICE_ENDPOINTS, resolve_service_endpoint
from .topology import (
    PlatformRuntimeManifest,
    RuntimeEndpoint,
    RuntimeManifestError,
    RuntimeProbe,
    RuntimeProcess,
    validate_runtime_manifest,
)


AE_WEB_ENDPOINT_ENV = "NEX_AE_WEB_BASE_URL"
AE_WEB_DEFAULT_BASE_URL = "http://127.0.0.1:5173"
BACKGROUND_PROCESS_IDS = (
    "nex-ae-artifact-render-worker",
    "nex-ae-retention-daemon",
    "nex-ag-remediation-sync-worker",
    "nex-ag-dispatch-daemon",
    "nex-cx-async-generation-worker",
    "nex-cx-ingestion-worker",
    "nex-cx-remediation-worker",
)
SERVICE_DATABASE_INDEX = {
    "nex-oa": 0,
    "nex-ag": 1,
    "nex-ae-api": 2,
    "nex-cx": 3,
    "nex-mo": 4,
}


def build_platform_runtime_manifest(
    profile: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    python_executable: str | None = None,
) -> PlatformRuntimeManifest:
    env = os.environ if environ is None else environ
    resolution = resolve_runtime_profile(profile, environ=env)
    endpoints = _runtime_endpoints(env)
    endpoint_by_id = {item.service_id: item for item in endpoints}
    processes = _runtime_processes(
        resolution,
        endpoint_by_id,
        python_executable=python_executable or sys.executable,
    )
    manifest = PlatformRuntimeManifest(
        schema_version="platform_runtime_manifest.v1",
        profile=resolution.profile,
        modes=resolution.modes,
        endpoints=endpoints,
        processes=processes,
        startup_timeout_seconds=90.0,
        shutdown_timeout_seconds=15.0,
    )
    validate_runtime_manifest(manifest)
    return manifest


def validate_runtime_command_targets(
    manifest: PlatformRuntimeManifest,
    root: Path,
) -> None:
    missing = []
    for process in manifest.processes:
        target = _command_target(process)
        if target is not None and not (root / target).is_file():
            missing.append(f"{process.process_id}:{target}")
    if missing:
        raise RuntimeManifestError(
            f"runtime command target is missing: {','.join(missing)}"
        )


def _runtime_endpoints(env: Mapping[str, str]) -> tuple[RuntimeEndpoint, ...]:
    backend = tuple(
        RuntimeEndpoint(service_id, resolve_service_endpoint(service_id, environ=env).base_url)
        for service_id in SERVICE_ENDPOINTS
    )
    web_base_url = (env.get(AE_WEB_ENDPOINT_ENV) or AE_WEB_DEFAULT_BASE_URL).strip()
    return (*backend, RuntimeEndpoint("nex-ae-web", web_base_url.rstrip("/")))


def _runtime_processes(
    resolution: RuntimeProfileResolution,
    endpoints: Mapping[str, RuntimeEndpoint],
    *,
    python_executable: str,
) -> tuple[RuntimeProcess, ...]:
    api_dependencies = {
        "nex-oa": (),
        "nex-mo": ("nex-oa-api",),
        "nex-cx": ("nex-oa-api", "nex-mo-api"),
        "nex-ae-api": ("nex-oa-api", "nex-cx-api"),
        "nex-ag": ("nex-oa-api", "nex-ae-api", "nex-cx-api", "nex-mo-api"),
    }
    api_processes = tuple(
        _api_process(
            service_id,
            endpoints[service_id],
            dependencies=api_dependencies[service_id],
            resolution=resolution,
            python_executable=python_executable,
        )
        for service_id in ("nex-oa", "nex-mo", "nex-cx", "nex-ae-api", "nex-ag")
    )
    web_host, web_port = _network_address(endpoints["nex-ae-web"].base_url)
    web = RuntimeProcess(
        process_id="nex-ae-web",
        owner="nex-ae-web",
        kind="web",
        command=("node", "apps/nex-ae-web/scripts/serve.mjs"),
        host=web_host,
        port=web_port,
        dependencies=("nex-ae-api",),
        liveness_probe=RuntimeProbe("/"),
        readiness_probe=RuntimeProbe("/"),
        environment_names=(
            "NEX_PROFILE",
            "NEX_AE_API_BASE_URL",
            "NEX_AE_WEB_BASE_URL",
        ),
    )
    background = tuple(
        _background_process(
            process_id,
            resolution=resolution,
            python_executable=python_executable,
        )
        for process_id in BACKGROUND_PROCESS_IDS
    )
    return (*api_processes, web, *background)


def _api_process(
    service_id: str,
    endpoint: RuntimeEndpoint,
    *,
    dependencies: tuple[str, ...],
    resolution: RuntimeProfileResolution,
    python_executable: str,
) -> RuntimeProcess:
    host, port = _network_address(endpoint.base_url)
    endpoint_environment = SERVICE_ENDPOINTS[service_id][0]
    return RuntimeProcess(
        process_id=f"{service_id}-api" if service_id != "nex-ae-api" else service_id,
        owner=service_id,
        kind="api",
        command=(
            python_executable,
            "scripts/dev/run_service.py",
            service_id,
            "--host",
            host,
            "--port",
            str(port),
        ),
        host=host,
        port=port,
        dependencies=dependencies,
        liveness_probe=RuntimeProbe("/health"),
        readiness_probe=RuntimeProbe("/ready"),
        environment_names=(
            "NEX_PROFILE",
            endpoint_environment,
            _database_environment(service_id, resolution.profile),
        ),
    )


def _background_process(
    process_id: str,
    *,
    resolution: RuntimeProfileResolution,
    python_executable: str,
) -> RuntimeProcess:
    owner, kind, dependencies = {
        "nex-ae-artifact-render-worker": (
            "nex-ae-api",
            "worker",
            ("nex-ae-api", "nex-cx-api"),
        ),
        "nex-ae-retention-daemon": (
            "nex-ae-api",
            "daemon",
            ("nex-ae-api",),
        ),
        "nex-ag-remediation-sync-worker": (
            "nex-ag",
            "worker",
            ("nex-ag-api", "nex-cx-api"),
        ),
        "nex-ag-dispatch-daemon": (
            "nex-ag",
            "daemon",
            ("nex-ag-api",),
        ),
        "nex-cx-async-generation-worker": (
            "nex-cx",
            "worker",
            ("nex-cx-api", "nex-mo-api"),
        ),
        "nex-cx-ingestion-worker": (
            "nex-cx",
            "worker",
            ("nex-cx-api", "nex-mo-api"),
        ),
        "nex-cx-remediation-worker": (
            "nex-cx",
            "worker",
            ("nex-cx-api", "nex-mo-api"),
        ),
    }[process_id]
    return RuntimeProcess(
        process_id=process_id,
        owner=owner,
        kind=kind,
        command=(
            python_executable,
            "scripts/dev/run_background_process.py",
            process_id,
            "--profile",
            resolution.profile,
        ),
        dependencies=dependencies,
        environment_names=(
            "NEX_PROFILE",
            _database_environment(owner, resolution.profile),
        ),
    )


def _database_environment(service_id: str, profile: str) -> str:
    names = TEST_DATABASE_ENV_NAMES if profile == "test" else DATABASE_ENV_NAMES
    return names[SERVICE_DATABASE_INDEX[service_id]]


def _network_address(base_url: str) -> tuple[str, int]:
    parsed = urlsplit(base_url)
    if not parsed.hostname:
        raise RuntimeManifestError("runtime endpoint host is missing")
    return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def _command_target(process: RuntimeProcess) -> str | None:
    for item in process.command[1:]:
        if item.endswith((".py", ".mjs")):
            return item
    return None
