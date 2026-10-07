from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any

from .deployment_artifacts import (
    DeploymentArtifactCatalog,
    build_default_deployment_artifact_catalog,
)
from .deployment_locks import (
    DeploymentBuildInputs,
    build_deployment_build_inputs,
    deployment_build_inputs_digest,
)
from .deployment_oci import (
    OciBuildDefinition,
    build_default_oci_definitions,
    materialize_oci_build_context,
    oci_build_context_digest,
    validate_oci_containerfiles,
)


DEPLOYMENT_PROVENANCE_SCHEMA_VERSION = "deployment_release_manifest.v1"
RELEASE_MANIFEST_STATUSES = ("BUILD_INPUTS_READY", "RELEASE_SET_READY")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_IMMUTABLE_IMAGE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")


class DeploymentProvenanceError(ValueError):
    pass


@dataclass(frozen=True)
class ArtifactBuildProvenance:
    artifact_id: str
    owner: str
    source_revision: str
    dependency_lock_id: str
    dependency_lock_digest: str
    build_definition_digest: str
    build_context_digest: str
    base_image_reference: str
    platform: str
    image_reference: str | None
    provenance_digest: str


@dataclass(frozen=True)
class DeploymentReleaseManifest:
    schema_version: str
    status: str
    reason_codes: tuple[str, ...]
    source_revision: str
    source_tree_clean: bool
    artifact_catalog_digest: str
    build_inputs_digest: str
    artifacts: tuple[ArtifactBuildProvenance, ...]
    release_set_digest: str | None
    production_deployment_approved: bool


def collect_deployment_release_manifest(
    root: Path,
    *,
    source_revision: str,
    source_tree_clean: bool,
    image_references: Mapping[str, str] | None = None,
) -> DeploymentReleaseManifest:
    catalog = build_default_deployment_artifact_catalog()
    inputs = build_deployment_build_inputs(root, catalog=catalog)
    definitions = build_default_oci_definitions(catalog)
    validate_oci_containerfiles(root, definitions)
    references = dict(image_references or {})
    expected_ids = {artifact.artifact_id for artifact in catalog.artifacts}
    if references and set(references) != expected_ids:
        raise DeploymentProvenanceError(
            "image references must cover the complete artifact set"
        )
    lock_by_id = {lock.lock_id: lock for lock in inputs.locks}
    definition_by_id = {
        definition.artifact_id: definition for definition in definitions
    }
    provenance = []
    with TemporaryDirectory(prefix="nex-release-context-") as temp:
        destination = Path(temp)
        for artifact in catalog.artifacts:
            definition = definition_by_id[artifact.artifact_id]
            context = materialize_oci_build_context(
                root,
                destination / artifact.artifact_id,
                definition,
            )
            lock = lock_by_id[artifact.dependency_family]
            record = ArtifactBuildProvenance(
                artifact_id=artifact.artifact_id,
                owner=artifact.owner,
                source_revision=source_revision,
                dependency_lock_id=lock.lock_id,
                dependency_lock_digest=f"sha256:{lock.sha256}",
                build_definition_digest=oci_build_definition_digest(
                    root, definition
                ),
                build_context_digest=oci_build_context_digest(context),
                base_image_reference=definition.base_image,
                platform=definition.platform,
                image_reference=references.get(artifact.artifact_id),
                provenance_digest="",
            )
            provenance.append(
                replace(record, provenance_digest=artifact_provenance_digest(record))
            )
    has_images = bool(references)
    reasons = []
    if not source_tree_clean:
        reasons.append("source_tree_dirty")
    if not has_images:
        reasons.append("image_digests_not_recorded")
    status = (
        "RELEASE_SET_READY"
        if source_tree_clean and has_images
        else "BUILD_INPUTS_READY"
    )
    manifest = DeploymentReleaseManifest(
        schema_version=DEPLOYMENT_PROVENANCE_SCHEMA_VERSION,
        status=status,
        reason_codes=tuple(reasons),
        source_revision=source_revision,
        source_tree_clean=source_tree_clean,
        artifact_catalog_digest=inputs.artifact_catalog_digest,
        build_inputs_digest=deployment_build_inputs_digest(inputs),
        artifacts=tuple(provenance),
        release_set_digest=None,
        production_deployment_approved=False,
    )
    if status == "RELEASE_SET_READY":
        manifest = replace(
            manifest,
            release_set_digest=deployment_release_set_digest(manifest),
        )
    validate_deployment_release_manifest(
        manifest,
        catalog=catalog,
        inputs=inputs,
    )
    return manifest


def validate_deployment_release_manifest(
    manifest: DeploymentReleaseManifest,
    *,
    catalog: DeploymentArtifactCatalog,
    inputs: DeploymentBuildInputs,
) -> None:
    errors: list[str] = []
    if manifest.schema_version != DEPLOYMENT_PROVENANCE_SCHEMA_VERSION:
        errors.append("deployment provenance schema version is invalid")
    if manifest.status not in RELEASE_MANIFEST_STATUSES:
        errors.append("deployment provenance status is invalid")
    if _REVISION.fullmatch(manifest.source_revision) is None:
        errors.append("source revision must be a full Git SHA")
    if manifest.artifact_catalog_digest != inputs.artifact_catalog_digest:
        errors.append("artifact catalog digest drift")
    if manifest.build_inputs_digest != deployment_build_inputs_digest(inputs):
        errors.append("build inputs digest drift")
    expected = {artifact.artifact_id: artifact for artifact in catalog.artifacts}
    observed: set[str] = set()
    image_references = []
    lock_by_id = {lock.lock_id: lock for lock in inputs.locks}
    for record in manifest.artifacts:
        if record.artifact_id in observed:
            errors.append(f"duplicate artifact provenance: {record.artifact_id}")
        observed.add(record.artifact_id)
        artifact = expected.get(record.artifact_id)
        if artifact is None:
            errors.append(f"unknown artifact provenance: {record.artifact_id}")
            continue
        if record.owner != artifact.owner:
            errors.append(f"artifact provenance owner drift: {record.artifact_id}")
        if record.source_revision != manifest.source_revision:
            errors.append(f"artifact source revision drift: {record.artifact_id}")
        lock = lock_by_id.get(record.dependency_lock_id)
        if (
            lock is None
            or record.dependency_lock_id != artifact.dependency_family
            or record.dependency_lock_digest != f"sha256:{lock.sha256}"
        ):
            errors.append(f"artifact dependency lock drift: {record.artifact_id}")
        for label, digest in (
            ("definition", record.build_definition_digest),
            ("context", record.build_context_digest),
            ("provenance", record.provenance_digest),
        ):
            if _SHA256.fullmatch(digest) is None:
                errors.append(f"artifact {label} digest is invalid: {record.artifact_id}")
        if _IMMUTABLE_IMAGE.fullmatch(record.base_image_reference) is None:
            errors.append(f"artifact base image is mutable: {record.artifact_id}")
        if record.platform != "linux/amd64":
            errors.append(f"artifact platform drift: {record.artifact_id}")
        if record.image_reference is not None:
            image_references.append(record.image_reference)
            if _IMMUTABLE_IMAGE.fullmatch(record.image_reference) is None:
                errors.append(f"artifact image is mutable: {record.artifact_id}")
        if record.provenance_digest != artifact_provenance_digest(record):
            errors.append(f"artifact provenance digest drift: {record.artifact_id}")
    if observed != set(expected):
        errors.append("artifact provenance coverage must be exact")
    if image_references and len(image_references) != len(expected):
        errors.append("partial image artifact set is prohibited")
    if len(image_references) != len(set(image_references)):
        errors.append("artifact image references must be unique")
    expected_reasons = tuple(
        reason
        for reason, present in (
            ("source_tree_dirty", not manifest.source_tree_clean),
            ("image_digests_not_recorded", not image_references),
        )
        if present
    )
    expected_status = (
        "RELEASE_SET_READY"
        if manifest.source_tree_clean and len(image_references) == len(expected)
        else "BUILD_INPUTS_READY"
    )
    if manifest.status != expected_status or manifest.reason_codes != expected_reasons:
        errors.append("release manifest readiness decision drift")
    if manifest.status == "RELEASE_SET_READY":
        if not manifest.source_tree_clean:
            errors.append("release set requires a clean source tree")
        if len(image_references) != len(expected):
            errors.append("release set requires every image digest")
        if manifest.reason_codes:
            errors.append("ready release set must not have blocking reasons")
        if manifest.release_set_digest != deployment_release_set_digest(manifest):
            errors.append("release set digest drift")
    elif manifest.release_set_digest is not None:
        errors.append("incomplete release manifest cannot have a set digest")
    if manifest.production_deployment_approved:
        errors.append("production deployment approval is not granted")
    if errors:
        raise DeploymentProvenanceError("; ".join(errors))


def deployment_release_manifest_projection(
    manifest: DeploymentReleaseManifest,
) -> dict[str, Any]:
    return {
        "schema_version": manifest.schema_version,
        "status": manifest.status,
        "reason_codes": list(manifest.reason_codes),
        "source_revision": manifest.source_revision,
        "source_tree_clean": manifest.source_tree_clean,
        "artifact_catalog_digest": manifest.artifact_catalog_digest,
        "build_inputs_digest": manifest.build_inputs_digest,
        "artifacts": [artifact_provenance_projection(item) for item in manifest.artifacts],
        "release_set_digest": manifest.release_set_digest,
        "production_deployment_approved": manifest.production_deployment_approved,
        "runtime_values_included": False,
        "timestamps_included": False,
        "machine_paths_included": False,
    }


def artifact_provenance_projection(
    record: ArtifactBuildProvenance,
    *,
    include_provenance_digest: bool = True,
) -> dict[str, Any]:
    projection = {
        "artifact_id": record.artifact_id,
        "owner": record.owner,
        "source_revision": record.source_revision,
        "dependency_lock_id": record.dependency_lock_id,
        "dependency_lock_digest": record.dependency_lock_digest,
        "build_definition_digest": record.build_definition_digest,
        "build_context_digest": record.build_context_digest,
        "base_image_reference": record.base_image_reference,
        "platform": record.platform,
        "image_reference": record.image_reference,
    }
    if include_provenance_digest:
        projection["provenance_digest"] = record.provenance_digest
    return projection


def artifact_provenance_digest(record: ArtifactBuildProvenance) -> str:
    payload = json.dumps(
        artifact_provenance_projection(record, include_provenance_digest=False),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def deployment_release_set_digest(manifest: DeploymentReleaseManifest) -> str:
    projection = deployment_release_manifest_projection(manifest)
    projection["release_set_digest"] = None
    payload = json.dumps(
        projection,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def oci_build_definition_digest(root: Path, definition: OciBuildDefinition) -> str:
    try:
        containerfile_digest = hashlib.sha256(
            (root / definition.containerfile).read_bytes()
        ).hexdigest()
    except OSError as exc:
        raise DeploymentProvenanceError(
            f"build definition is missing: {definition.artifact_id}"
        ) from exc
    payload = json.dumps(
        {
            "artifact_id": definition.artifact_id,
            "containerfile": definition.containerfile,
            "containerfile_sha256": containerfile_digest,
            "target": definition.target,
            "platform": definition.platform,
            "base_image": definition.base_image,
            "builder_images": list(definition.builder_images),
            "context_paths": list(definition.context_paths),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
