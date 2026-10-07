from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .deployment_artifacts import (
    DeploymentArtifactCatalog,
    build_default_deployment_artifact_catalog,
)
from .deployment_entrypoints import (
    PackagedEntrypointDefinition,
    build_packaged_entrypoint_definitions,
    build_packaged_runtime_manifest,
)
from .deployment_environments import (
    EnvironmentCompositionResolution,
    resolve_environment_composition,
)
from .postgres_orchestration import POSTGRES_SERVICE_ORDER
from .topology import PlatformRuntimeManifest, RuntimeProcess
from .topology_graph import build_runtime_startup_plan


PACKAGED_LIFECYCLE_SCHEMA_VERSION = "packaged_deployment_lifecycle.v1"
RESTART_PHASES = ("STOP", "MIGRATE", "START", "READINESS")
ROLLBACK_PHASES = (
    "STOP",
    "SELECT_PREVIOUS_COMPLETE_SET",
    "VERIFY_SCHEMA_COMPATIBILITY",
    "START",
    "READINESS",
)
_DATABASE_ENVIRONMENTS = {
    "nex-oa": ("NEX_OA_DATABASE_URL", "NEX_OA_TEST_DATABASE_URL"),
    "nex-mo": ("NEX_MO_DATABASE_URL", "NEX_MO_TEST_DATABASE_URL"),
    "nex-cx": ("NEX_CX_DATABASE_URL", "NEX_CX_TEST_DATABASE_URL"),
    "nex-ae-api": ("NEX_AE_DATABASE_URL", "NEX_AE_TEST_DATABASE_URL"),
    "nex-ag": ("NEX_AG_DATABASE_URL", "NEX_AG_TEST_DATABASE_URL"),
}


class PackagedDeploymentLifecycleError(ValueError):
    pass


@dataclass(frozen=True)
class PackagedMigrationStep:
    order: int
    service_id: str
    artifact_id: str
    database_environment_name: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class PackagedProcessStep:
    process_id: str
    artifact_id: str
    owner: str
    kind: str
    start_layer: int
    command: tuple[str, ...]
    probe_mode: str
    probe_path: str | None
    probe_timeout_seconds: float | None


@dataclass(frozen=True)
class PackagedDeploymentLifecyclePlan:
    profile: str
    environment_class: str
    status: str
    reason_codes: tuple[str, ...]
    migration_steps: tuple[PackagedMigrationStep, ...]
    start_layers: tuple[tuple[str, ...], ...]
    process_steps: tuple[PackagedProcessStep, ...]
    stop_order: tuple[str, ...]
    restart_phases: tuple[str, ...]
    rollback_phases: tuple[str, ...]
    complete_artifact_set: tuple[str, ...]
    immutable_artifact_reference_count: int
    mixed_artifact_set_allowed: bool
    database_downgrade_allowed: bool
    production_contact_allowed: bool


def build_packaged_deployment_lifecycle_plan(
    profile: str,
    *,
    environ: Mapping[str, str],
) -> PackagedDeploymentLifecyclePlan:
    composition = resolve_environment_composition(profile, environ=environ)
    manifest = build_packaged_runtime_manifest(profile, environ=environ)
    catalog = build_default_deployment_artifact_catalog()
    entrypoints = build_packaged_entrypoint_definitions(manifest, catalog)
    startup = build_runtime_startup_plan(manifest)
    artifact_by_owner = {
        artifact.owner: artifact.artifact_id for artifact in catalog.artifacts
    }
    entrypoint_by_process = {item.process_id: item for item in entrypoints}
    layer_by_process = {
        process_id: layer_index
        for layer_index, layer in enumerate(startup.layers, start=1)
        for process_id in layer
    }
    plan = PackagedDeploymentLifecyclePlan(
        profile=profile,
        environment_class=composition.environment_class,
        status=composition.status,
        reason_codes=composition.reason_codes,
        migration_steps=_migration_steps(
            profile,
            artifact_by_owner=artifact_by_owner,
        ),
        start_layers=startup.layers,
        process_steps=tuple(
            _process_step(
                process,
                entrypoint=entrypoint_by_process[process.process_id],
                layer=layer_by_process[process.process_id],
                profile=profile,
            )
            for process in manifest.processes
        ),
        stop_order=tuple(reversed(startup.ordered_process_ids)),
        restart_phases=RESTART_PHASES,
        rollback_phases=ROLLBACK_PHASES,
        complete_artifact_set=tuple(
            artifact.artifact_id for artifact in catalog.artifacts
        ),
        immutable_artifact_reference_count=len(composition.artifact_references),
        mixed_artifact_set_allowed=False,
        database_downgrade_allowed=False,
        production_contact_allowed=False,
    )
    validate_packaged_deployment_lifecycle_plan(
        plan,
        manifest=manifest,
        catalog=catalog,
        composition=composition,
    )
    return plan


def validate_packaged_deployment_lifecycle_plan(
    plan: PackagedDeploymentLifecyclePlan,
    *,
    manifest: PlatformRuntimeManifest,
    catalog: DeploymentArtifactCatalog,
    composition: EnvironmentCompositionResolution,
) -> None:
    errors: list[str] = []
    process_ids = tuple(process.process_id for process in manifest.processes)
    ordered = tuple(item for layer in plan.start_layers for item in layer)
    if plan.profile != manifest.profile or plan.profile != composition.profile:
        errors.append("lifecycle profile drift")
    if plan.environment_class != composition.environment_class:
        errors.append("lifecycle environment class drift")
    if plan.status != composition.status or plan.reason_codes != composition.reason_codes:
        errors.append("lifecycle composition admission drift")
    if len(ordered) != len(set(ordered)) or set(ordered) != set(process_ids):
        errors.append("lifecycle process coverage must be exact")
    if plan.stop_order != tuple(reversed(ordered)):
        errors.append("lifecycle stop order must reverse startup order")
    if plan.restart_phases != RESTART_PHASES:
        errors.append("lifecycle restart phases drift")
    if plan.rollback_phases != ROLLBACK_PHASES:
        errors.append("lifecycle rollback phases drift")
    expected_artifacts = tuple(artifact.artifact_id for artifact in catalog.artifacts)
    if plan.complete_artifact_set != expected_artifacts:
        errors.append("lifecycle artifact set coverage must be exact")
    if plan.mixed_artifact_set_allowed:
        errors.append("mixed artifact set rollback is prohibited")
    if plan.database_downgrade_allowed:
        errors.append("automatic database downgrade is prohibited")
    if plan.production_contact_allowed:
        errors.append("production contact is not approved")
    if plan.immutable_artifact_reference_count != len(
        composition.artifact_references
    ):
        errors.append("immutable artifact reference count drift")
    if plan.profile == "production" and plan.status != "BLOCKED":
        errors.append("production lifecycle must remain blocked")
    _validate_migrations(plan, catalog, errors)
    _validate_process_steps(plan, manifest, catalog, errors)
    if errors:
        raise PackagedDeploymentLifecycleError("; ".join(errors))


def packaged_deployment_lifecycle_projection(
    plan: PackagedDeploymentLifecyclePlan,
) -> dict[str, Any]:
    return {
        "schema_version": PACKAGED_LIFECYCLE_SCHEMA_VERSION,
        "profile": plan.profile,
        "environment_class": plan.environment_class,
        "status": plan.status,
        "reason_codes": list(plan.reason_codes),
        "migration_steps": [
            {
                "order": step.order,
                "service_id": step.service_id,
                "artifact_id": step.artifact_id,
                "database_environment_name": step.database_environment_name,
                "command": list(step.command),
            }
            for step in plan.migration_steps
        ],
        "start_layers": [list(layer) for layer in plan.start_layers],
        "process_steps": [
            {
                "process_id": step.process_id,
                "artifact_id": step.artifact_id,
                "owner": step.owner,
                "kind": step.kind,
                "start_layer": step.start_layer,
                "command": list(step.command),
                "probe_mode": step.probe_mode,
                "probe_path": step.probe_path,
                "probe_timeout_seconds": step.probe_timeout_seconds,
            }
            for step in plan.process_steps
        ],
        "stop_order": list(plan.stop_order),
        "restart_phases": list(plan.restart_phases),
        "rollback_phases": list(plan.rollback_phases),
        "complete_artifact_set": list(plan.complete_artifact_set),
        "immutable_artifact_reference_count": (
            plan.immutable_artifact_reference_count
        ),
        "mixed_artifact_set_allowed": plan.mixed_artifact_set_allowed,
        "database_downgrade_allowed": plan.database_downgrade_allowed,
        "production_contact_allowed": plan.production_contact_allowed,
        "runtime_values_included": False,
    }


def _migration_steps(
    profile: str,
    *,
    artifact_by_owner: Mapping[str, str],
) -> tuple[PackagedMigrationStep, ...]:
    if profile == "local_mock":
        return ()
    database_profile = "test" if profile == "test" else "dev"
    environment_index = 1 if profile == "test" else 0
    return tuple(
        PackagedMigrationStep(
            order=order,
            service_id=service_id,
            artifact_id=artifact_by_owner[service_id],
            database_environment_name=_DATABASE_ENVIRONMENTS[service_id][
                environment_index
            ],
            command=(
                "python",
                "-m",
                "scripts.db.run_migrations",
                "--service",
                service_id,
                "--profile",
                database_profile,
            ),
        )
        for order, service_id in enumerate(POSTGRES_SERVICE_ORDER, start=1)
    )


def _process_step(
    process: RuntimeProcess,
    *,
    entrypoint: PackagedEntrypointDefinition,
    layer: int,
    profile: str,
) -> PackagedProcessStep:
    probe_mode = "liveness" if profile == "local_mock" else "readiness"
    if process.kind in {"api", "web"}:
        probe = (
            process.liveness_probe
            if probe_mode == "liveness"
            else process.readiness_probe
        )
        probe_path = probe.path if probe is not None else None
        probe_timeout = probe.timeout_seconds if probe is not None else None
    else:
        probe_mode = "process_alive_twice"
        probe_path = None
        probe_timeout = None
    return PackagedProcessStep(
        process_id=process.process_id,
        artifact_id=entrypoint.artifact_id,
        owner=process.owner,
        kind=process.kind,
        start_layer=layer,
        command=entrypoint.command,
        probe_mode=probe_mode,
        probe_path=probe_path,
        probe_timeout_seconds=probe_timeout,
    )


def _validate_migrations(
    plan: PackagedDeploymentLifecyclePlan,
    catalog: DeploymentArtifactCatalog,
    errors: list[str],
) -> None:
    if plan.profile == "local_mock":
        if plan.migration_steps:
            errors.append("local mock lifecycle must not run migrations")
        return
    if tuple(step.service_id for step in plan.migration_steps) != tuple(
        POSTGRES_SERVICE_ORDER
    ):
        errors.append("lifecycle migration order drift")
    owner_artifacts = {
        artifact.owner: artifact.artifact_id for artifact in catalog.artifacts
    }
    for expected_order, step in enumerate(plan.migration_steps, start=1):
        if step.order != expected_order:
            errors.append(f"migration step order drift: {step.service_id}")
        if owner_artifacts.get(step.service_id) != step.artifact_id:
            errors.append(f"migration artifact owner drift: {step.service_id}")
        if step.database_environment_name not in _DATABASE_ENVIRONMENTS.get(
            step.service_id, ()
        ):
            errors.append(f"migration database environment drift: {step.service_id}")
        if step.command[:3] != (
            "python",
            "-m",
            "scripts.db.run_migrations",
        ):
            errors.append(f"migration command is not package relative: {step.service_id}")


def _validate_process_steps(
    plan: PackagedDeploymentLifecyclePlan,
    manifest: PlatformRuntimeManifest,
    catalog: DeploymentArtifactCatalog,
    errors: list[str],
) -> None:
    process_by_id = {process.process_id: process for process in manifest.processes}
    artifact_by_process = {
        binding.process_id: binding.artifact_id
        for binding in catalog.process_bindings
    }
    if len(plan.process_steps) != len(process_by_id):
        errors.append("lifecycle process step count drift")
    observed: set[str] = set()
    for step in plan.process_steps:
        if step.process_id in observed:
            errors.append(f"duplicate lifecycle process step: {step.process_id}")
        observed.add(step.process_id)
        process = process_by_id.get(step.process_id)
        if process is None:
            errors.append(f"unknown lifecycle process step: {step.process_id}")
            continue
        if artifact_by_process.get(step.process_id) != step.artifact_id:
            errors.append(f"lifecycle process artifact drift: {step.process_id}")
        if step.command != process.command:
            errors.append(f"lifecycle process command drift: {step.process_id}")
        if (
            step.start_layer < 1
            or step.start_layer > len(plan.start_layers)
            or step.process_id not in plan.start_layers[step.start_layer - 1]
        ):
            errors.append(f"lifecycle process layer drift: {step.process_id}")
        if process.kind in {"api", "web"}:
            expected_mode = (
                "liveness" if plan.profile == "local_mock" else "readiness"
            )
            expected_probe = (
                process.liveness_probe
                if expected_mode == "liveness"
                else process.readiness_probe
            )
            if (
                expected_probe is None
                or step.probe_mode != expected_mode
                or step.probe_path != expected_probe.path
                or step.probe_timeout_seconds != expected_probe.timeout_seconds
            ):
                errors.append(f"lifecycle HTTP probe drift: {step.process_id}")
        elif (
            step.probe_mode != "process_alive_twice"
            or step.probe_path is not None
            or step.probe_timeout_seconds is not None
        ):
            errors.append(f"lifecycle background probe drift: {step.process_id}")
    if observed != set(process_by_id):
        errors.append("lifecycle process step coverage must be exact")
