from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from .deployment_artifacts import (
    DeploymentArtifactCatalog,
    build_default_deployment_artifact_catalog,
)
from .deployment_entrypoints import (
    build_packaged_entrypoint_definitions,
    build_packaged_runtime_manifest,
)
from .deployment_locks import (
    DeploymentBuildInputs,
    build_deployment_build_inputs,
    deployment_build_inputs_digest,
)
from .deployment_oci import (
    OciBuildDefinition,
    build_default_oci_definitions,
)
from .process_manifest import BACKGROUND_PROCESS_IDS


OCI_IMAGE_BUILD_EVIDENCE_SCHEMA_VERSION = "oci_image_build_evidence.v1"
OCI_IMAGE_BUILD_STATUS = "RELEASE_SET_BUILT"
OCI_BUILD_LABEL_KEYS = (
    "org.opencontainers.image.version",
    "org.opencontainers.image.revision",
    "io.nex-platform.build-inputs-digest",
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_IMMUTABLE_IMAGE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")


class OciImageBuildEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class OciImageBuildRecord:
    artifact_id: str
    owner: str
    target: str
    local_tag: str
    image_id: str
    manifest_digest: str
    image_reference: str
    base_image_reference: str
    source_revision: str
    dependency_lock_id: str
    dependency_lock_digest: str
    build_definition_digest: str
    build_context_digest: str
    platform: str
    runtime_user: str
    entrypoint: tuple[str, ...]
    command: tuple[str, ...]
    labels: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class BackgroundContainerCheck:
    process_id: str
    artifact_id: str
    command: tuple[str, ...]
    profile: str
    persistence_mode: str
    lifecycle_ready: bool
    work_claiming_enabled: bool


@dataclass(frozen=True)
class OciImageBuildEvidence:
    schema_version: str
    status: str
    source_revision: str
    source_tree_clean: bool
    build_inputs_digest: str
    artifacts: tuple[OciImageBuildRecord, ...]
    background_checks: tuple[BackgroundContainerCheck, ...]
    release_set_digest: str
    registry_push_performed: bool
    production_contacted: bool


def build_oci_image_build_evidence(
    *,
    root: Path,
    source_revision: str,
    source_tree_clean: bool,
    artifacts: tuple[OciImageBuildRecord, ...],
    background_checks: tuple[BackgroundContainerCheck, ...],
    release_set_digest: str,
) -> OciImageBuildEvidence:
    inputs = build_deployment_build_inputs(root)
    evidence = OciImageBuildEvidence(
        schema_version=OCI_IMAGE_BUILD_EVIDENCE_SCHEMA_VERSION,
        status=OCI_IMAGE_BUILD_STATUS,
        source_revision=source_revision,
        source_tree_clean=source_tree_clean,
        build_inputs_digest=deployment_build_inputs_digest(inputs),
        artifacts=artifacts,
        background_checks=background_checks,
        release_set_digest=release_set_digest,
        registry_push_performed=False,
        production_contacted=False,
    )
    validate_oci_image_build_evidence(evidence, inputs=inputs)
    return evidence


def validate_oci_image_build_evidence(
    evidence: OciImageBuildEvidence,
    *,
    catalog: DeploymentArtifactCatalog | None = None,
    inputs: DeploymentBuildInputs | None = None,
    definitions: tuple[OciBuildDefinition, ...] | None = None,
) -> None:
    artifact_catalog = catalog or build_default_deployment_artifact_catalog()
    build_inputs = inputs
    if build_inputs is None:
        raise OciImageBuildEvidenceError("deployment build inputs are required")
    build_definitions = definitions or build_default_oci_definitions(artifact_catalog)
    expected_artifacts = tuple(
        artifact.artifact_id for artifact in artifact_catalog.artifacts
    )
    artifacts_by_id = {
        artifact.artifact_id: artifact for artifact in artifact_catalog.artifacts
    }
    definitions_by_id = {
        definition.artifact_id: definition for definition in build_definitions
    }
    locks_by_id = {lock.lock_id: lock for lock in build_inputs.locks}
    manifest = build_packaged_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    entrypoints = build_packaged_entrypoint_definitions(manifest, artifact_catalog)
    default_commands = {
        entry.artifact_id: entry.command
        for entry in entrypoints
        if entry.kind in {"api", "web"}
    }
    background_entries = {
        entry.process_id: entry
        for entry in entrypoints
        if entry.kind in {"worker", "daemon"}
    }

    errors: list[str] = []
    if evidence.schema_version != OCI_IMAGE_BUILD_EVIDENCE_SCHEMA_VERSION:
        errors.append("OCI image build evidence schema version drift")
    if evidence.status != OCI_IMAGE_BUILD_STATUS:
        errors.append("OCI image build evidence status drift")
    if _REVISION.fullmatch(evidence.source_revision) is None:
        errors.append("OCI image build source revision is invalid")
    if not evidence.source_tree_clean:
        errors.append("OCI image release set requires a clean source tree")
    if evidence.build_inputs_digest != deployment_build_inputs_digest(build_inputs):
        errors.append("OCI image build inputs digest drift")
    if _SHA256.fullmatch(evidence.release_set_digest) is None:
        errors.append("OCI image release set digest is invalid")

    observed_artifacts = tuple(item.artifact_id for item in evidence.artifacts)
    if observed_artifacts != expected_artifacts:
        errors.append("OCI image artifact coverage or order drift")
    manifest_digests: list[str] = []
    image_ids: list[str] = []
    for record in evidence.artifacts:
        artifact = artifacts_by_id.get(record.artifact_id)
        definition = definitions_by_id.get(record.artifact_id)
        if artifact is None or definition is None:
            errors.append(f"unknown OCI image artifact: {record.artifact_id}")
            continue
        lock = locks_by_id.get(artifact.dependency_family)
        if record.owner != artifact.owner:
            errors.append(f"OCI image owner drift: {record.artifact_id}")
        if record.target != definition.target:
            errors.append(f"OCI image target drift: {record.artifact_id}")
        if not record.local_tag or "@" in record.local_tag:
            errors.append(f"OCI local image tag is invalid: {record.artifact_id}")
        if _SHA256.fullmatch(record.image_id) is None:
            errors.append(f"OCI image ID is invalid: {record.artifact_id}")
        else:
            image_ids.append(record.image_id)
        if _SHA256.fullmatch(record.manifest_digest) is None:
            errors.append(f"OCI manifest digest is invalid: {record.artifact_id}")
        else:
            manifest_digests.append(record.manifest_digest)
        if (
            _IMMUTABLE_IMAGE.fullmatch(record.image_reference) is None
            or not record.image_reference.endswith(f"@{record.manifest_digest}")
        ):
            errors.append(f"OCI immutable image reference drift: {record.artifact_id}")
        if record.base_image_reference != definition.base_image:
            errors.append(f"OCI base image digest drift: {record.artifact_id}")
        if record.source_revision != evidence.source_revision:
            errors.append(f"OCI image source revision drift: {record.artifact_id}")
        if (
            lock is None
            or record.dependency_lock_id != artifact.dependency_family
            or record.dependency_lock_digest != f"sha256:{lock.sha256}"
        ):
            errors.append(f"OCI image dependency lock drift: {record.artifact_id}")
        for label, digest in (
            ("definition", record.build_definition_digest),
            ("context", record.build_context_digest),
        ):
            if _SHA256.fullmatch(digest) is None:
                errors.append(
                    f"OCI image {label} digest is invalid: {record.artifact_id}"
                )
        if record.platform != definition.platform:
            errors.append(f"OCI image platform drift: {record.artifact_id}")
        if not _non_root_user(record.runtime_user):
            errors.append(f"OCI image runtime user is privileged: {record.artifact_id}")
        if record.entrypoint:
            errors.append(f"OCI image entrypoint drift: {record.artifact_id}")
        if record.command != default_commands.get(record.artifact_id):
            errors.append(f"OCI image packaged command drift: {record.artifact_id}")
        labels = dict(record.labels)
        expected_labels = {
            "org.opencontainers.image.version": evidence.source_revision[:12],
            "org.opencontainers.image.revision": evidence.source_revision,
            "io.nex-platform.build-inputs-digest": evidence.build_inputs_digest,
        }
        if labels != expected_labels:
            errors.append(f"OCI image label drift: {record.artifact_id}")
    if len(manifest_digests) != len(set(manifest_digests)):
        errors.append("OCI manifest digests must be unique")
    if len(image_ids) != len(set(image_ids)):
        errors.append("OCI image IDs must be unique")

    observed_background = tuple(
        item.process_id for item in evidence.background_checks
    )
    if observed_background != tuple(BACKGROUND_PROCESS_IDS):
        errors.append("OCI background check coverage or order drift")
    for check in evidence.background_checks:
        entry = background_entries.get(check.process_id)
        if entry is None:
            errors.append(f"unknown OCI background check: {check.process_id}")
            continue
        if check.artifact_id != entry.artifact_id:
            errors.append(f"OCI background artifact drift: {check.process_id}")
        if check.command != (*entry.command, "--check"):
            errors.append(f"OCI background command drift: {check.process_id}")
        if check.profile != "local_mock":
            errors.append(f"OCI background profile drift: {check.process_id}")
        if check.persistence_mode != "memory":
            errors.append(f"OCI background persistence drift: {check.process_id}")
        if not check.lifecycle_ready:
            errors.append(f"OCI background lifecycle is not ready: {check.process_id}")
        if check.work_claiming_enabled:
            errors.append(f"OCI background check claimed work: {check.process_id}")
    if evidence.registry_push_performed:
        errors.append("OCI image acceptance must not push to a registry")
    if evidence.production_contacted:
        errors.append("OCI image acceptance must not contact production")
    if errors:
        raise OciImageBuildEvidenceError("; ".join(errors))


def oci_image_build_evidence_projection(
    evidence: OciImageBuildEvidence,
) -> dict[str, Any]:
    return {
        "schema_version": evidence.schema_version,
        "status": evidence.status,
        "source_revision": evidence.source_revision,
        "source_tree_clean": evidence.source_tree_clean,
        "build_inputs_digest": evidence.build_inputs_digest,
        "artifacts": [
            {
                "artifact_id": record.artifact_id,
                "owner": record.owner,
                "target": record.target,
                "local_tag": record.local_tag,
                "image_id": record.image_id,
                "manifest_digest": record.manifest_digest,
                "image_reference": record.image_reference,
                "base_image_reference": record.base_image_reference,
                "source_revision": record.source_revision,
                "dependency_lock_id": record.dependency_lock_id,
                "dependency_lock_digest": record.dependency_lock_digest,
                "build_definition_digest": record.build_definition_digest,
                "build_context_digest": record.build_context_digest,
                "platform": record.platform,
                "runtime_user": record.runtime_user,
                "entrypoint": list(record.entrypoint),
                "command": list(record.command),
                "labels": dict(record.labels),
            }
            for record in evidence.artifacts
        ],
        "background_checks": [
            {
                "process_id": check.process_id,
                "artifact_id": check.artifact_id,
                "command": list(check.command),
                "profile": check.profile,
                "persistence_mode": check.persistence_mode,
                "lifecycle_ready": check.lifecycle_ready,
                "work_claiming_enabled": check.work_claiming_enabled,
            }
            for check in evidence.background_checks
        ],
        "release_set_digest": evidence.release_set_digest,
        "registry_push_performed": evidence.registry_push_performed,
        "production_contacted": evidence.production_contacted,
        "credentials_included": False,
        "machine_paths_included": False,
        "runtime_values_included": False,
    }


def _non_root_user(value: str) -> bool:
    normalized = value.strip().lower()
    return bool(
        normalized
        and normalized not in {"0", "root"}
        and not normalized.startswith("0:")
        and not normalized.startswith("root:")
    )
