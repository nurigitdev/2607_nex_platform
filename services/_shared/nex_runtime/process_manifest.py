from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from .runtime_profiles import (
    CURRENT_DATABASE_ENV_NAMES,
    CURRENT_TEST_DATABASE_ENV_NAMES,
    DATABASE_ENV_NAMES,
    TEST_DATABASE_ENV_NAMES,
    RuntimeProfileResolution,
    resolve_current_runtime_profile,
    resolve_runtime_profile,
)
from .service_endpoints import CURRENT_SERVICE_ENDPOINTS, resolve_service_endpoint
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
CURRENT_BACKGROUND_PROCESS_IDS = (
    *BACKGROUND_PROCESS_IDS,
    "nex-wa-evidence-consumer",
    "nex-ae-agent-runtime-worker",
    "nex-wc-event-delivery-worker",
)
HISTORICAL_SERVICE_IDS = (
    "nex-oa",
    "nex-mo",
    "nex-cx",
    "nex-ae-api",
    "nex-ag",
)
CURRENT_SERVICE_IDS = (
    *HISTORICAL_SERVICE_IDS,
    "nex-wc",
    "nex-eos",
    "nex-wa",
)
SERVICE_DATABASE_INDEX = {
    "nex-oa": 0,
    "nex-ag": 1,
    "nex-ae-api": 2,
    "nex-cx": 3,
    "nex-mo": 4,
    "nex-wc": 5,
    "nex-eos": 6,
    "nex-wa": 7,
}


def build_platform_runtime_manifest(
    profile: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    python_executable: str | None = None,
) -> PlatformRuntimeManifest:
    return _build_runtime_manifest(
        profile,
        environ=environ,
        python_executable=python_executable,
        current=False,
    )


def build_current_platform_runtime_manifest(
    profile: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    python_executable: str | None = None,
) -> PlatformRuntimeManifest:
    """Build the P9 topology: promoted P8-Demo services plus NeX-WA."""
    return _build_runtime_manifest(
        profile,
        environ=environ,
        python_executable=python_executable,
        current=True,
    )


def _build_runtime_manifest(
    profile: str | None,
    *,
    environ: Mapping[str, str] | None,
    python_executable: str | None,
    current: bool,
) -> PlatformRuntimeManifest:
    env = os.environ if environ is None else environ
    resolver = resolve_current_runtime_profile if current else resolve_runtime_profile
    resolution = resolver(profile, environ=env)
    service_ids = CURRENT_SERVICE_IDS if current else HISTORICAL_SERVICE_IDS
    background_ids = (
        CURRENT_BACKGROUND_PROCESS_IDS if current else BACKGROUND_PROCESS_IDS
    )
    endpoints = _runtime_endpoints(env, service_ids=service_ids)
    endpoint_by_id = {item.service_id: item for item in endpoints}
    processes = _runtime_processes(
        resolution,
        endpoint_by_id,
        python_executable=python_executable or sys.executable,
        service_ids=service_ids,
        background_process_ids=background_ids,
        current=current,
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


def _runtime_endpoints(
    env: Mapping[str, str],
    *,
    service_ids: tuple[str, ...] = HISTORICAL_SERVICE_IDS,
) -> tuple[RuntimeEndpoint, ...]:
    backend = tuple(
        RuntimeEndpoint(
            service_id, resolve_service_endpoint(service_id, environ=env).base_url
        )
        for service_id in service_ids
    )
    web_base_url = (env.get(AE_WEB_ENDPOINT_ENV) or AE_WEB_DEFAULT_BASE_URL).strip()
    return (*backend, RuntimeEndpoint("nex-ae-web", web_base_url.rstrip("/")))


def _runtime_processes(
    resolution: RuntimeProfileResolution,
    endpoints: Mapping[str, RuntimeEndpoint],
    *,
    python_executable: str,
    service_ids: tuple[str, ...] = HISTORICAL_SERVICE_IDS,
    background_process_ids: tuple[str, ...] = BACKGROUND_PROCESS_IDS,
    current: bool = False,
) -> tuple[RuntimeProcess, ...]:
    api_dependencies = {
        "nex-oa": (),
        "nex-mo": ("nex-oa-api",),
        "nex-cx": ("nex-oa-api", "nex-mo-api"),
        "nex-ae-api": ("nex-oa-api", "nex-cx-api"),
        "nex-ag": ("nex-oa-api", "nex-ae-api", "nex-cx-api", "nex-mo-api"),
        "nex-wc": ("nex-oa-api", "nex-ae-api"),
        "nex-eos": ("nex-oa-api", "nex-ae-api", "nex-wc-api"),
        "nex-wa": (
            "nex-oa-api",
            "nex-ae-api",
            "nex-wc-api",
            "nex-eos-api",
        ),
    }
    api_processes = tuple(
        _api_process(
            service_id,
            endpoints[service_id],
            dependencies=api_dependencies[service_id],
            resolution=resolution,
            python_executable=python_executable,
            current=current,
        )
        for service_id in service_ids
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
            current=current,
        )
        for process_id in background_process_ids
    )
    return (*api_processes, web, *background)


def _api_process(
    service_id: str,
    endpoint: RuntimeEndpoint,
    *,
    dependencies: tuple[str, ...],
    resolution: RuntimeProfileResolution,
    python_executable: str,
    current: bool = False,
) -> RuntimeProcess:
    host, port = _network_address(endpoint.base_url)
    endpoint_environment = CURRENT_SERVICE_ENDPOINTS[service_id][0]
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
            _database_environment(service_id, resolution.profile, current=current),
        ),
    )


def _background_process(
    process_id: str,
    *,
    resolution: RuntimeProfileResolution,
    python_executable: str,
    current: bool = False,
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
        "nex-wa-evidence-consumer": (
            "nex-wa",
            "worker",
            (
                "nex-wa-api",
                "nex-oa-api",
                "nex-ae-api",
                "nex-wc-api",
                "nex-eos-api",
            ),
        ),
        "nex-ae-agent-runtime-worker": (
            "nex-ae-api",
            "worker",
            (
                "nex-ae-api",
                "nex-oa-api",
                "nex-cx-api",
                "nex-mo-api",
                "nex-wc-api",
                "nex-eos-api",
            ),
        ),
        "nex-wc-event-delivery-worker": (
            "nex-wc",
            "worker",
            (
                "nex-wc-api",
                "nex-ae-api",
                "nex-oa-api",
            ),
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
            _database_environment(owner, resolution.profile, current=current),
        ),
    )


def _database_environment(
    service_id: str,
    profile: str,
    *,
    current: bool = False,
) -> str:
    if current:
        names = (
            CURRENT_TEST_DATABASE_ENV_NAMES
            if profile == "test"
            else CURRENT_DATABASE_ENV_NAMES
        )
    else:
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
