from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from .background_process import ENABLED_BACKGROUND_PROFILES
from .deployment_artifacts import (
    DeploymentArtifactCatalog,
    build_current_deployment_artifact_catalog,
    build_default_deployment_artifact_catalog,
    validate_deployment_artifact_catalog,
)
from .process_manifest import (
    CURRENT_BACKGROUND_PROCESS_IDS,
    build_current_platform_runtime_manifest,
    build_platform_runtime_manifest,
)
from .topology import (
    RUNTIME_PROFILES,
    PlatformRuntimeManifest,
    RuntimeProcess,
    validate_runtime_manifest,
)

PACKAGED_ENTRYPOINTS_SCHEMA_VERSION = "packaged_entrypoints.v1"
PACKAGED_BACKGROUND_MODULE = "nex_runtime.background_process"
PACKAGED_ENTRYPOINT_CAPABILITIES = (
    "request_serving",
    "static_serving",
    "job_claiming",
    "event_delivering",
    "outbox_publishing",
    "scheduled_maintenance",
    "lifecycle_only",
)
PACKAGED_DOMAIN_WORK_CAPABILITIES = (
    "job_claiming",
    "event_delivering",
    "outbox_publishing",
    "scheduled_maintenance",
)
PACKAGED_DOMAIN_PROCESS_CAPABILITIES = (
    ("nex-cx-ingestion-worker", "job_claiming"),
    ("nex-wa-evidence-consumer", "job_claiming"),
    ("nex-ae-agent-runtime-worker", "job_claiming"),
    ("nex-wc-event-delivery-worker", "event_delivering"),
    ("nex-eos-outbox-publisher", "outbox_publishing"),
)
_CAPABILITY_PROCESS_KINDS = {
    "request_serving": ("api",),
    "static_serving": ("web",),
    "job_claiming": ("worker",),
    "event_delivering": ("worker",),
    "outbox_publishing": ("worker",),
    "scheduled_maintenance": ("daemon",),
    "lifecycle_only": ("worker", "daemon"),
}
_API_MODULES = {
    "nex-oa-api": "nex_oa.main:app",
    "nex-mo-api": "nex_mo.main:app",
    "nex-cx-api": "nex_cx.main:app",
    "nex-ae-api": "nex_ae_api.main:app",
    "nex-ag-api": "nex_ag.main:app",
    "nex-wc-api": "nex_wc.main:app",
    "nex-eos-api": "nex_eos.main:app",
    "nex-wa-api": "nex_wa.main:app",
}
_DOMAIN_PROCESS_CAPABILITY_BY_ID = dict(PACKAGED_DOMAIN_PROCESS_CAPABILITIES)
_DIRECT_BACKGROUND_MODULES = {
    "nex-wa-evidence-consumer": "nex_wa.consumer_main",
}


class PackagedEntrypointError(ValueError):
    pass


@dataclass(frozen=True)
class PackagedEntrypointDefinition:
    process_id: str
    artifact_id: str
    entrypoint_id: str
    owner: str
    kind: str
    command: tuple[str, ...]
    capability: str
    admitted_profiles: tuple[str, ...]


def packaged_capability_enables_domain_work(capability: str) -> bool:
    if capability not in PACKAGED_ENTRYPOINT_CAPABILITIES:
        raise PackagedEntrypointError(
            f"unsupported packaged capability: {capability}"
        )
    return capability in PACKAGED_DOMAIN_WORK_CAPABILITIES


def build_packaged_runtime_manifest(
    profile: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    python_executable: str = "python",
) -> PlatformRuntimeManifest:
    return _build_packaged_runtime_manifest(
        profile,
        environ=environ,
        python_executable=python_executable,
        current=False,
    )


def build_current_packaged_runtime_manifest(
    profile: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    python_executable: str = "python",
) -> PlatformRuntimeManifest:
    return _build_packaged_runtime_manifest(
        profile,
        environ=environ,
        python_executable=python_executable,
        current=True,
    )


def _build_packaged_runtime_manifest(
    profile: str | None,
    *,
    environ: Mapping[str, str] | None,
    python_executable: str,
    current: bool,
) -> PlatformRuntimeManifest:
    manifest_builder = (
        build_current_platform_runtime_manifest
        if current
        else build_platform_runtime_manifest
    )
    catalog_builder = (
        build_current_deployment_artifact_catalog
        if current
        else build_default_deployment_artifact_catalog
    )
    source = manifest_builder(
        profile,
        environ=environ,
        python_executable=python_executable,
    )
    processes = tuple(
        replace(
            process,
            command=_packaged_command(
                process,
                profile=source.profile,
                python_executable=python_executable,
            ),
        )
        for process in source.processes
    )
    manifest = replace(source, processes=processes)
    validate_runtime_manifest(manifest)
    validate_packaged_entrypoints(
        manifest,
        catalog_builder(),
    )
    return manifest


def build_packaged_entrypoint_definitions(
    manifest: PlatformRuntimeManifest,
    catalog: DeploymentArtifactCatalog | None = None,
) -> tuple[PackagedEntrypointDefinition, ...]:
    artifact_catalog = catalog or build_default_deployment_artifact_catalog()
    bindings = {
        binding.process_id: binding for binding in artifact_catalog.process_bindings
    }
    definitions = tuple(
        PackagedEntrypointDefinition(
            process_id=process.process_id,
            artifact_id=bindings[process.process_id].artifact_id,
            entrypoint_id=bindings[process.process_id].entrypoint_id,
            owner=process.owner,
            kind=process.kind,
            command=process.command,
            capability=_entrypoint_capability(process),
            admitted_profiles=_admitted_profiles(process),
        )
        for process in manifest.processes
    )
    validate_packaged_entrypoints(manifest, artifact_catalog, definitions)
    return definitions


def validate_packaged_entrypoints(
    manifest: PlatformRuntimeManifest,
    catalog: DeploymentArtifactCatalog,
    definitions: tuple[PackagedEntrypointDefinition, ...] | None = None,
) -> None:
    try:
        validate_runtime_manifest(manifest)
        validate_deployment_artifact_catalog(catalog, manifest)
    except ValueError as exc:
        raise PackagedEntrypointError(str(exc)) from exc
    artifact_owners = {
        artifact.artifact_id: artifact.owner for artifact in catalog.artifacts
    }
    bindings = {binding.process_id: binding for binding in catalog.process_bindings}
    entries = definitions
    if entries is None:
        entries = tuple(
            PackagedEntrypointDefinition(
                process.process_id,
                bindings[process.process_id].artifact_id,
                bindings[process.process_id].entrypoint_id,
                process.owner,
                process.kind,
                process.command,
                _entrypoint_capability(process),
                _admitted_profiles(process),
            )
            for process in manifest.processes
        )
    errors: list[str] = []
    expected_ids = {process.process_id for process in manifest.processes}
    observed_ids: set[str] = set()
    for entry in entries:
        if entry.process_id in observed_ids:
            errors.append(f"duplicate packaged entrypoint: {entry.process_id}")
        observed_ids.add(entry.process_id)
        binding = bindings.get(entry.process_id)
        if binding is None:
            errors.append(
                f"packaged entrypoint has no artifact binding: {entry.process_id}"
            )
            continue
        if entry.artifact_id != binding.artifact_id:
            errors.append(f"packaged artifact binding drift: {entry.process_id}")
        if entry.entrypoint_id != binding.entrypoint_id:
            errors.append(f"packaged semantic entrypoint drift: {entry.process_id}")
        if artifact_owners.get(entry.artifact_id) != entry.owner:
            errors.append(f"packaged entrypoint owner drift: {entry.process_id}")
        capability_known = entry.capability in PACKAGED_ENTRYPOINT_CAPABILITIES
        if not capability_known:
            errors.append(f"unsupported packaged capability: {entry.process_id}")
        else:
            allowed_kinds = _CAPABILITY_PROCESS_KINDS[entry.capability]
            if entry.kind not in allowed_kinds:
                errors.append(
                    f"packaged capability process kind drift: {entry.process_id}"
                )
            if entry.capability in PACKAGED_DOMAIN_WORK_CAPABILITIES and (
                _DOMAIN_PROCESS_CAPABILITY_BY_ID.get(entry.process_id)
                != entry.capability
            ):
                errors.append(
                    f"domain-work loop is not admitted: {entry.process_id}"
                )
        if not entry.admitted_profiles or any(
            profile not in RUNTIME_PROFILES for profile in entry.admitted_profiles
        ):
            errors.append(f"invalid packaged profile admission: {entry.process_id}")
        if any(
            argument.endswith((".py", ".mjs")) or argument.startswith("scripts/dev/")
            for argument in entry.command
        ):
            errors.append(f"source-tree packaged command: {entry.process_id}")
        process = next(
            (
                item
                for item in manifest.processes
                if item.process_id == entry.process_id
            ),
            None,
        )
        if process is None or entry.command != process.command:
            errors.append(f"packaged command drift: {entry.process_id}")
        elif entry.capability != _entrypoint_capability(process):
            errors.append(f"packaged capability binding drift: {entry.process_id}")
        if entry.kind in {"worker", "daemon"}:
            direct_module = _DIRECT_BACKGROUND_MODULES.get(entry.process_id)
            if direct_module is not None:
                valid = len(entry.command) >= 3 and entry.command[1:3] == (
                    "-m",
                    direct_module,
                )
            else:
                valid = (
                    len(entry.command) >= 4
                    and entry.command[1:3] == ("-m", PACKAGED_BACKGROUND_MODULE)
                    and entry.command[3] == entry.process_id
                )
            if not valid:
                errors.append(
                    f"invalid background packaged command: {entry.process_id}"
                )
    for missing in sorted(expected_ids - observed_ids):
        errors.append(f"process has no packaged entrypoint: {missing}")
    for unknown in sorted(observed_ids - expected_ids):
        errors.append(f"unknown packaged entrypoint: {unknown}")
    if errors:
        raise PackagedEntrypointError("; ".join(errors))


def packaged_entrypoints_projection(
    definitions: tuple[PackagedEntrypointDefinition, ...],
) -> dict[str, Any]:
    return {
        "schema_version": PACKAGED_ENTRYPOINTS_SCHEMA_VERSION,
        "entrypoints": [
            {
                "process_id": entry.process_id,
                "artifact_id": entry.artifact_id,
                "entrypoint_id": entry.entrypoint_id,
                "owner": entry.owner,
                "kind": entry.kind,
                "command": list(entry.command),
                "capability": entry.capability,
                "domain_work_enabled": packaged_capability_enables_domain_work(
                    entry.capability
                ),
                "admitted_profiles": list(entry.admitted_profiles),
            }
            for entry in definitions
        ],
        "entrypoint_count": len(definitions),
        "background_entrypoint_count": sum(
            entry.kind in {"worker", "daemon"} for entry in definitions
        ),
        "job_claiming_background_count": sum(
            entry.capability == "job_claiming" for entry in definitions
        ),
        "event_delivering_background_count": sum(
            entry.capability == "event_delivering" for entry in definitions
        ),
        "outbox_publishing_background_count": sum(
            entry.capability == "outbox_publishing" for entry in definitions
        ),
        "scheduled_maintenance_background_count": sum(
            entry.capability == "scheduled_maintenance" for entry in definitions
        ),
        "domain_work_background_count": sum(
            entry.kind in {"worker", "daemon"}
            and packaged_capability_enables_domain_work(entry.capability)
            for entry in definitions
        ),
        "lifecycle_only_background_count": sum(
            entry.capability == "lifecycle_only" for entry in definitions
        ),
        "capability_counts": {
            capability: sum(
                entry.capability == capability for entry in definitions
            )
            for capability in PACKAGED_ENTRYPOINT_CAPABILITIES
        },
    }


def _packaged_command(
    process: RuntimeProcess,
    *,
    profile: str,
    python_executable: str,
) -> tuple[str, ...]:
    if process.kind == "api":
        return (
            python_executable,
            "-m",
            "uvicorn",
            _API_MODULES[process.process_id],
            "--host",
            str(process.host),
            "--port",
            str(process.port),
        )
    if process.kind == "web":
        return ("npm", "start", "--silent")
    direct_module = _DIRECT_BACKGROUND_MODULES.get(process.process_id)
    if direct_module is not None:
        return (python_executable, "-m", direct_module)
    if process.process_id in CURRENT_BACKGROUND_PROCESS_IDS:
        return (
            python_executable,
            "-m",
            PACKAGED_BACKGROUND_MODULE,
            process.process_id,
            "--profile",
            profile,
        )
    raise PackagedEntrypointError(
        f"unsupported packaged process command: {process.process_id}"
    )


def _entrypoint_capability(process: RuntimeProcess) -> str:
    if process.kind == "api":
        return "request_serving"
    if process.kind == "web":
        return "static_serving"
    domain_capability = _DOMAIN_PROCESS_CAPABILITY_BY_ID.get(process.process_id)
    if domain_capability is not None:
        return domain_capability
    return "lifecycle_only"


def _admitted_profiles(process: RuntimeProcess) -> tuple[str, ...]:
    if process.kind in {"worker", "daemon"}:
        return ENABLED_BACKGROUND_PROFILES
    return RUNTIME_PROFILES
