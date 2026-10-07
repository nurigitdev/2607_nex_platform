from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any

from .topology import PlatformRuntimeManifest


DEPLOYMENT_ARTIFACT_CATALOG_SCHEMA_VERSION = "deployment_artifact_catalog.v1"
ARTIFACT_KINDS = ("python-service", "node-web")
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_IMAGE_REPOSITORY = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$"
)
_OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class DeploymentArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class DeploymentArtifactDefinition:
    artifact_id: str
    owner: str
    kind: str
    build_target: str
    dependency_family: str
    source_roots: tuple[str, ...]


@dataclass(frozen=True)
class ProcessArtifactBinding:
    process_id: str
    artifact_id: str
    entrypoint_id: str


@dataclass(frozen=True)
class DeploymentArtifactCatalog:
    schema_version: str
    artifacts: tuple[DeploymentArtifactDefinition, ...]
    process_bindings: tuple[ProcessArtifactBinding, ...]


DEFAULT_DEPLOYMENT_ARTIFACTS = (
    DeploymentArtifactDefinition(
        "nex-oa-runtime",
        "nex-oa",
        "python-service",
        "oa-runtime",
        "python-production",
        ("services/_shared/nex_runtime", "services/nex-oa/nex_oa"),
    ),
    DeploymentArtifactDefinition(
        "nex-ae-runtime",
        "nex-ae-api",
        "python-service",
        "ae-runtime",
        "python-production",
        ("services/_shared/nex_runtime", "services/nex-ae-api/nex_ae_api"),
    ),
    DeploymentArtifactDefinition(
        "nex-cx-runtime",
        "nex-cx",
        "python-service",
        "cx-runtime",
        "python-production",
        ("services/_shared/nex_runtime", "services/nex-cx/nex_cx"),
    ),
    DeploymentArtifactDefinition(
        "nex-mo-runtime",
        "nex-mo",
        "python-service",
        "mo-runtime",
        "python-production",
        ("services/_shared/nex_runtime", "services/nex-mo/nex_mo"),
    ),
    DeploymentArtifactDefinition(
        "nex-ag-runtime",
        "nex-ag",
        "python-service",
        "ag-runtime",
        "python-production",
        ("services/_shared/nex_runtime", "services/nex-ag/nex_ag"),
    ),
    DeploymentArtifactDefinition(
        "nex-ae-web",
        "nex-ae-web",
        "node-web",
        "ae-web",
        "node-production",
        ("apps/nex-ae-web",),
    ),
)

DEFAULT_PROCESS_ARTIFACT_BINDINGS = (
    ProcessArtifactBinding("nex-oa-api", "nex-oa-runtime", "api"),
    ProcessArtifactBinding("nex-mo-api", "nex-mo-runtime", "api"),
    ProcessArtifactBinding("nex-cx-api", "nex-cx-runtime", "api"),
    ProcessArtifactBinding("nex-ae-api", "nex-ae-runtime", "api"),
    ProcessArtifactBinding("nex-ag-api", "nex-ag-runtime", "api"),
    ProcessArtifactBinding("nex-ae-web", "nex-ae-web", "web"),
    ProcessArtifactBinding(
        "nex-ae-artifact-render-worker",
        "nex-ae-runtime",
        "artifact-render-worker",
    ),
    ProcessArtifactBinding(
        "nex-ae-retention-daemon", "nex-ae-runtime", "retention-daemon"
    ),
    ProcessArtifactBinding(
        "nex-ag-remediation-sync-worker",
        "nex-ag-runtime",
        "remediation-sync-worker",
    ),
    ProcessArtifactBinding(
        "nex-ag-dispatch-daemon", "nex-ag-runtime", "dispatch-daemon"
    ),
    ProcessArtifactBinding(
        "nex-cx-async-generation-worker",
        "nex-cx-runtime",
        "async-generation-worker",
    ),
    ProcessArtifactBinding(
        "nex-cx-ingestion-worker", "nex-cx-runtime", "ingestion-worker"
    ),
    ProcessArtifactBinding(
        "nex-cx-remediation-worker", "nex-cx-runtime", "remediation-worker"
    ),
)


def build_default_deployment_artifact_catalog() -> DeploymentArtifactCatalog:
    catalog = DeploymentArtifactCatalog(
        schema_version=DEPLOYMENT_ARTIFACT_CATALOG_SCHEMA_VERSION,
        artifacts=DEFAULT_DEPLOYMENT_ARTIFACTS,
        process_bindings=DEFAULT_PROCESS_ARTIFACT_BINDINGS,
    )
    validate_deployment_artifact_catalog(catalog)
    return catalog


def validate_deployment_artifact_catalog(
    catalog: DeploymentArtifactCatalog,
    runtime_manifest: PlatformRuntimeManifest | None = None,
) -> None:
    errors: list[str] = []
    if catalog.schema_version != DEPLOYMENT_ARTIFACT_CATALOG_SCHEMA_VERSION:
        errors.append("unsupported deployment artifact catalog schema_version")

    artifact_ids: set[str] = set()
    artifact_owners: dict[str, str] = {}
    build_targets: set[str] = set()
    for artifact in catalog.artifacts:
        if not _valid_identifier(artifact.artifact_id):
            errors.append(f"invalid artifact_id: {artifact.artifact_id}")
        if artifact.artifact_id in artifact_ids:
            errors.append(f"duplicate artifact_id: {artifact.artifact_id}")
        artifact_ids.add(artifact.artifact_id)
        artifact_owners[artifact.artifact_id] = artifact.owner
        if not _valid_identifier(artifact.owner):
            errors.append(f"invalid artifact owner: {artifact.artifact_id}")
        if artifact.kind not in ARTIFACT_KINDS:
            errors.append(f"invalid artifact kind: {artifact.artifact_id}")
        if not _valid_identifier(artifact.build_target):
            errors.append(f"invalid build target: {artifact.artifact_id}")
        elif artifact.build_target in build_targets:
            errors.append(f"duplicate build target: {artifact.build_target}")
        build_targets.add(artifact.build_target)
        if not _valid_identifier(artifact.dependency_family):
            errors.append(f"invalid dependency family: {artifact.artifact_id}")
        if not artifact.source_roots:
            errors.append(f"source roots are empty: {artifact.artifact_id}")
        elif len(set(artifact.source_roots)) != len(artifact.source_roots):
            errors.append(f"duplicate source root: {artifact.artifact_id}")
        for source_root in artifact.source_roots:
            if not _safe_relative_path(source_root):
                errors.append(f"invalid source root: {artifact.artifact_id}")

    process_ids: set[str] = set()
    bound_artifact_ids: set[str] = set()
    for binding in catalog.process_bindings:
        if not _valid_identifier(binding.process_id):
            errors.append(f"invalid process_id: {binding.process_id}")
        if binding.process_id in process_ids:
            errors.append(f"duplicate process binding: {binding.process_id}")
        process_ids.add(binding.process_id)
        if binding.artifact_id not in artifact_ids:
            errors.append(f"unknown artifact binding: {binding.process_id}")
        else:
            bound_artifact_ids.add(binding.artifact_id)
        if not _valid_identifier(binding.entrypoint_id):
            errors.append(f"invalid entrypoint_id: {binding.process_id}")

    for artifact_id in sorted(artifact_ids - bound_artifact_ids):
        errors.append(f"artifact has no process binding: {artifact_id}")

    if runtime_manifest is not None:
        runtime_processes = {
            process.process_id: process for process in runtime_manifest.processes
        }
        for process_id in sorted(set(runtime_processes) - process_ids):
            errors.append(f"runtime process is not bound: {process_id}")
        for process_id in sorted(process_ids - set(runtime_processes)):
            errors.append(f"bound process is not in runtime manifest: {process_id}")
        for binding in catalog.process_bindings:
            process = runtime_processes.get(binding.process_id)
            owner = artifact_owners.get(binding.artifact_id)
            if process is not None and owner is not None and process.owner != owner:
                errors.append(f"process owner mismatch: {binding.process_id}")

    if errors:
        raise DeploymentArtifactError("; ".join(errors))


def deployment_artifact_catalog_projection(
    catalog: DeploymentArtifactCatalog,
) -> dict[str, Any]:
    validate_deployment_artifact_catalog(catalog)
    return {
        "schema_version": catalog.schema_version,
        "artifacts": [
            {
                "artifact_id": artifact.artifact_id,
                "owner": artifact.owner,
                "kind": artifact.kind,
                "build_target": artifact.build_target,
                "dependency_family": artifact.dependency_family,
                "source_roots": sorted(artifact.source_roots),
            }
            for artifact in sorted(catalog.artifacts, key=lambda item: item.artifact_id)
        ],
        "process_bindings": [
            {
                "process_id": binding.process_id,
                "artifact_id": binding.artifact_id,
                "entrypoint_id": binding.entrypoint_id,
            }
            for binding in sorted(
                catalog.process_bindings, key=lambda item: item.process_id
            )
        ],
    }


def canonical_deployment_artifact_catalog(
    catalog: DeploymentArtifactCatalog,
) -> bytes:
    return json.dumps(
        deployment_artifact_catalog_projection(catalog),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def deployment_artifact_catalog_digest(
    catalog: DeploymentArtifactCatalog,
) -> str:
    payload = canonical_deployment_artifact_catalog(catalog)
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def immutable_image_reference(repository: str, content_digest: str) -> str:
    if not _IMAGE_REPOSITORY.fullmatch(repository):
        raise DeploymentArtifactError("invalid image repository")
    if not _OCI_DIGEST.fullmatch(content_digest):
        raise DeploymentArtifactError("invalid OCI content digest")
    return f"{repository}@{content_digest}"


def _valid_identifier(value: str) -> bool:
    return bool(_IDENTIFIER.fullmatch(value))


def _safe_relative_path(value: str) -> bool:
    if not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
        and str(path) == value
    )
