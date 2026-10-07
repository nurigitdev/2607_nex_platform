#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PYTHON_BIN = ROOT / ".venv" / "bin" / "python"
for path in (ROOT / "services" / "_shared", ROOT / "scripts" / "db"):
    sys.path.insert(0, str(path))

from nex_runtime.deployment_acceptance import (  # noqa: E402
    NETWORK_PROCESS_IDS,
    build_packaged_runtime_acceptance_evidence,
    packaged_runtime_acceptance_projection,
)
from nex_runtime.deployment_artifacts import (  # noqa: E402
    build_default_deployment_artifact_catalog,
)
from nex_runtime.deployment_entrypoints import (  # noqa: E402
    build_packaged_runtime_manifest,
)
from nex_runtime.deployment_environments import (  # noqa: E402
    ARTIFACT_REFERENCE_ENVIRONMENTS,
)
from nex_runtime.deployment_lifecycle import (  # noqa: E402
    build_packaged_deployment_lifecycle_plan,
)
from nex_runtime.deployment_oci import (  # noqa: E402
    build_default_oci_definitions,
    materialize_oci_build_context,
    oci_build_context_digest,
)
from nex_runtime.process_manifest import BACKGROUND_PROCESS_IDS  # noqa: E402
from nex_runtime.runtime_process_adapters import (  # noqa: E402
    RuntimeProbeRequest,
    build_runtime_process_environment,
    probe_http_runtime_process,
)
from nex_runtime.runtime_profiles import SIGNED_TRUST_ENV_NAMES  # noqa: E402
from nex_runtime.service_endpoints import SERVICE_ENDPOINTS  # noqa: E402
from nex_runtime.topology import RuntimeProcess  # noqa: E402
from nex_runtime.topology_graph import build_runtime_startup_plan  # noqa: E402
from platform_test_migrations import (  # noqa: E402
    run_platform_test_migration_readiness,
)


SMOKE_ENV = "NEX_PLATFORM_PACKAGED_RUNTIME_ACCEPTANCE"
SCHEMA_VERSION = "platform_packaged_runtime_acceptance_evidence.v1"
READY_TIMEOUT_SECONDS = 30.0


class PackagedRuntimeSmokeError(RuntimeError):
    pass


def run_platform_packaged_runtime_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    executor: Callable[[Mapping[str, str]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "1420",
            "requirement": "S142",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if env.get("NEX_PROFILE", "test") != "test":
        return _failure("protected acceptance requires the test profile")
    try:
        evidence = dict((executor or _execute_acceptance)(env))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        return _failure(str(exc))
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1420",
        "requirement": "S142",
        "status": "PASS",
        "acceptance": evidence,
        "decision": {
            "package_context_accepted": True,
            "oci_image_execution_deferred": True,
            "production_contact_required": False,
            "production_deployment_approved": False,
            "next_slice": "1421",
        },
    }


def _execute_acceptance(environ: Mapping[str, str]) -> dict[str, Any]:
    configured = _acceptance_environment(environ)
    catalog = build_default_deployment_artifact_catalog()
    definitions = build_default_oci_definitions(catalog)
    manifest = build_packaged_runtime_manifest(
        "test",
        environ=configured,
        python_executable=str(PYTHON_BIN),
    )
    runtime_environment = build_runtime_process_environment(
        manifest,
        environ=configured,
    )
    lifecycle = build_packaged_deployment_lifecycle_plan(
        "test",
        environ=configured,
    )
    with TemporaryDirectory(prefix="nex-packaged-acceptance-") as temporary:
        contexts: dict[str, Path] = {}
        context_digests = []
        root = Path(temporary)
        for definition in definitions:
            destination = root / definition.artifact_id
            context = materialize_oci_build_context(
                ROOT,
                destination,
                definition,
            )
            contexts[definition.artifact_id] = destination
            context_digests.append(
                (definition.artifact_id, oci_build_context_digest(context))
            )
        _run_packaged_migrations(
            lifecycle.migration_steps,
            contexts=contexts,
            environment=runtime_environment,
        )
        migration = run_platform_test_migration_readiness(runtime_environment)
        _run_background_checks(
            manifest.processes,
            contexts=contexts,
            environment=runtime_environment,
            catalog=catalog,
        )
        generations = tuple(
            _run_network_generation(
                manifest.processes,
                startup_layers=build_runtime_startup_plan(manifest).layers,
                contexts=contexts,
                environment=runtime_environment,
                catalog=catalog,
            )
            for _ in range(2)
        )
    evidence = build_packaged_runtime_acceptance_evidence(
        artifact_context_digests=tuple(context_digests),
        migrated_service_ids=tuple(
            step.service_id for step in lifecycle.migration_steps
        ),
        background_check_process_ids=tuple(BACKGROUND_PROCESS_IDS),
        startup_generations=generations,
        postgres_identity_count=sum(
            item.database_identity_confirmed and item.select_one_ready
            for item in migration.services
        ),
        oci_daemon_status=_oci_daemon_status(),
    )
    return packaged_runtime_acceptance_projection(evidence)


def _acceptance_environment(
    environ: Mapping[str, str],
    *,
    port_allocator: Callable[[], int] | None = None,
) -> dict[str, str]:
    allocate = port_allocator or _free_port
    env = dict(environ)
    env["NEX_PROFILE"] = "test"
    for environment_name, _ in SERVICE_ENDPOINTS.values():
        env[environment_name] = f"http://127.0.0.1:{allocate()}"
    env["NEX_AE_WEB_BASE_URL"] = f"http://127.0.0.1:{allocate()}"
    for name in SIGNED_TRUST_ENV_NAMES:
        env.setdefault(name, "s1420-protected-test-evidence")
    for artifact_id, name in ARTIFACT_REFERENCE_ENVIRONMENTS.items():
        digest = hashlib.sha256(
            f"s1420:{artifact_id}".encode("ascii")
        ).hexdigest()
        env[name] = f"registry.invalid/nex/{artifact_id}@sha256:{digest}"
    return env


def _run_packaged_migrations(
    steps: Sequence[Any],
    *,
    contexts: Mapping[str, Path],
    environment: Mapping[str, str],
) -> None:
    for step in steps:
        _run_checked(
            _host_python_command(step.command),
            cwd=contexts[step.artifact_id],
            environment=_artifact_environment(
                contexts[step.artifact_id],
                step.artifact_id,
                environment,
            ),
            failure_code=f"packaged migration failed: {step.service_id}",
        )


def _run_background_checks(
    processes: Sequence[RuntimeProcess],
    *,
    contexts: Mapping[str, Path],
    environment: Mapping[str, str],
    catalog: Any,
) -> None:
    artifact_by_process = {
        binding.process_id: binding.artifact_id
        for binding in catalog.process_bindings
    }
    by_id = {process.process_id: process for process in processes}
    for process_id in BACKGROUND_PROCESS_IDS:
        process = by_id[process_id]
        artifact_id = artifact_by_process[process_id]
        completed = _run_checked(
            (*_host_python_command(process.command), "--check"),
            cwd=contexts[artifact_id],
            environment=_artifact_environment(
                contexts[artifact_id], artifact_id, environment
            ),
            failure_code=f"packaged background check failed: {process_id}",
        )
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise PackagedRuntimeSmokeError(
                f"packaged background evidence invalid: {process_id}"
            ) from exc
        if (
            payload.get("process_id") != process_id
            or payload.get("profile") != "test"
            or payload.get("persistence_mode") != "postgres"
        ):
            raise PackagedRuntimeSmokeError(
                f"packaged background evidence drift: {process_id}"
            )


def _run_network_generation(
    processes: Sequence[RuntimeProcess],
    *,
    startup_layers: Sequence[Sequence[str]],
    contexts: Mapping[str, Path],
    environment: Mapping[str, str],
    catalog: Any,
) -> tuple[str, ...]:
    process_by_id = {process.process_id: process for process in processes}
    artifact_by_process = {
        binding.process_id: binding.artifact_id
        for binding in catalog.process_bindings
    }
    ordered = tuple(
        process_id
        for layer in startup_layers
        for process_id in layer
        if process_id in NETWORK_PROCESS_IDS
    )
    handles: list[tuple[str, subprocess.Popen[Any]]] = []
    try:
        for process_id in ordered:
            process = process_by_id[process_id]
            artifact_id = artifact_by_process[process_id]
            command = _host_python_command(process.command)
            handle = subprocess.Popen(
                command,
                cwd=_process_working_directory(
                    contexts[artifact_id], artifact_id
                ),
                env=_artifact_environment(
                    contexts[artifact_id], artifact_id, environment
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            handles.append((process_id, handle))
            _wait_until_ready(process, handle)
        return ordered
    finally:
        for _, handle in reversed(handles):
            _stop_process(handle)


def _wait_until_ready(
    process: RuntimeProcess,
    handle: subprocess.Popen[Any],
    *,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    if process.host is None or process.port is None or process.readiness_probe is None:
        raise PackagedRuntimeSmokeError(
            f"packaged network probe missing: {process.process_id}"
        )
    deadline = clock() + READY_TIMEOUT_SECONDS
    request = RuntimeProbeRequest(
        process_id=process.process_id,
        mode="readiness",
        url=(
            f"http://{process.host}:{process.port}"
            f"{process.readiness_probe.path}"
        ),
        timeout_seconds=process.readiness_probe.timeout_seconds,
    )
    while clock() < deadline:
        if handle.poll() is not None:
            raise PackagedRuntimeSmokeError(
                f"packaged process exited before readiness: {process.process_id}"
            )
        if probe_http_runtime_process(request):
            return
        sleeper(0.1)
    raise PackagedRuntimeSmokeError(
        f"packaged process readiness timeout: {process.process_id}"
    )


def _run_checked(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    failure_code: str,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=dict(environment),
        check=False,
        capture_output=True,
        text=True,
        timeout=120.0,
    )
    if completed.returncode != 0:
        raise PackagedRuntimeSmokeError(failure_code)
    return completed


def _artifact_environment(
    context: Path,
    artifact_id: str,
    environment: Mapping[str, str],
) -> dict[str, str]:
    env = dict(environment)
    owner_path = {
        "nex-oa-runtime": "services/nex-oa",
        "nex-ae-runtime": "services/nex-ae-api",
        "nex-cx-runtime": "services/nex-cx",
        "nex-mo-runtime": "services/nex-mo",
        "nex-ag-runtime": "services/nex-ag",
    }.get(artifact_id)
    if owner_path is not None:
        env["PYTHONPATH"] = os.pathsep.join(
            (str(context / "services" / "_shared"), str(context / owner_path))
        )
    return env


def _process_working_directory(context: Path, artifact_id: str) -> Path:
    if artifact_id == "nex-ae-web":
        return context / "apps" / "nex-ae-web"
    return context


def _host_python_command(command: Sequence[str]) -> tuple[str, ...]:
    if command and command[0] == "python":
        return (str(PYTHON_BIN), *command[1:])
    return tuple(command)


def _stop_process(handle: subprocess.Popen[Any]) -> None:
    if handle.poll() is not None:
        return
    handle.terminate()
    try:
        handle.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
        handle.kill()
        handle.wait(timeout=None)


def _oci_daemon_status() -> str:
    try:
        completed = subprocess.run(
            ("docker", "version", "--format", "{{.Server.Version}}"),
            check=False,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except FileNotFoundError:
        return "UNAVAILABLE_NOT_INSTALLED"
    except (OSError, subprocess.SubprocessError):
        return "UNAVAILABLE_PERMISSION_OR_SOCKET"
    return (
        "AVAILABLE_NOT_USED"
        if completed.returncode == 0
        else "UNAVAILABLE_PERMISSION_OR_SOCKET"
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _failure(issue: str) -> dict[str, Any]:
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1420",
        "requirement": "S142",
        "status": "FAIL",
        "issues": [issue],
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return "platform_packaged_runtime_acceptance=skip"
    if result.get("status") != "PASS":
        return "platform_packaged_runtime_acceptance=fail"
    acceptance = dict(result.get("acceptance") or {})
    return (
        "platform_packaged_runtime_acceptance=pass "
        f"artifacts={len(acceptance.get('artifact_contexts') or [])} "
        f"migrations={len(acceptance.get('migrated_service_ids') or [])} "
        f"background={len(acceptance.get('background_check_process_ids') or [])} "
        f"generations={len(acceptance.get('startup_generations') or [])} "
        f"oci={acceptance.get('oci_daemon_status')} next=1421"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_packaged_runtime_acceptance()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
