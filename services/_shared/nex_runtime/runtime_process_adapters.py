from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Any, Protocol
from urllib.request import urlopen

from .runtime_profiles import runtime_profile_environment_overlay
from .service_endpoints import SERVICE_ENDPOINTS
from .topology import PlatformRuntimeManifest, RuntimeProcess


class RuntimeProcessHandle(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


class RuntimeProcessLauncher(Protocol):
    def launch(
        self,
        process: RuntimeProcess,
        *,
        environment: Mapping[str, str],
    ) -> RuntimeProcessHandle: ...


@dataclass(frozen=True)
class RuntimeProbeRequest:
    process_id: str
    mode: str
    url: str
    timeout_seconds: float


@dataclass
class SubprocessRuntimeLauncher:
    root: Path

    def launch(
        self,
        process: RuntimeProcess,
        *,
        environment: Mapping[str, str],
    ) -> RuntimeProcessHandle:
        return subprocess.Popen(
            process.command,
            cwd=self.root,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def probe_http_runtime_process(
    request: RuntimeProbeRequest,
    *,
    opener: Callable[..., Any] = urlopen,
) -> bool:
    try:
        with opener(request.url, timeout=request.timeout_seconds) as response:
            status = int(getattr(response, "status", 0))
            return 200 <= status < 400
    except (OSError, TimeoutError, ValueError):
        return False


def build_runtime_process_environment(
    manifest: PlatformRuntimeManifest,
    *,
    environ: Mapping[str, str] | None,
) -> dict[str, str]:
    environment = dict(os.environ if environ is None else environ)
    environment.update(runtime_profile_environment_overlay(manifest.profile))
    endpoint_environment_names = {
        service_id: config[0] for service_id, config in SERVICE_ENDPOINTS.items()
    }
    endpoint_environment_names["nex-ae-web"] = "NEX_AE_WEB_BASE_URL"
    for endpoint in manifest.endpoints:
        environment_name = endpoint_environment_names.get(endpoint.service_id)
        if environment_name is not None:
            environment[environment_name] = endpoint.base_url
    return environment
