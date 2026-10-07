from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from nex_runtime.deployment_artifacts import build_default_deployment_artifact_catalog
from nex_runtime.deployment_locks import build_deployment_build_inputs
from nex_runtime.deployment_oci import build_default_oci_definitions
from nex_runtime.deployment_provenance import (
    DEPLOYMENT_PROVENANCE_SCHEMA_VERSION,
    ArtifactBuildProvenance,
    DeploymentProvenanceError,
    artifact_provenance_digest,
    artifact_provenance_projection,
    collect_deployment_release_manifest,
    deployment_release_manifest_projection,
    deployment_release_set_digest,
    oci_build_definition_digest,
    validate_deployment_release_manifest,
)

import run_platform_deployment_provenance as smoke


ROOT = Path(__file__).resolve().parents[1]
REVISION = "a" * 40


def _ready_manifest():
    return collect_deployment_release_manifest(
        ROOT,
        source_revision=REVISION,
        source_tree_clean=True,
        image_references=smoke._synthetic_image_references(),
    )


def test_build_inputs_and_complete_release_set_are_distinct() -> None:
    inputs = collect_deployment_release_manifest(
        ROOT,
        source_revision=REVISION,
        source_tree_clean=False,
    )
    ready = _ready_manifest()

    assert inputs.schema_version == DEPLOYMENT_PROVENANCE_SCHEMA_VERSION
    assert inputs.status == "BUILD_INPUTS_READY"
    assert inputs.reason_codes == (
        "source_tree_dirty",
        "image_digests_not_recorded",
    )
    assert inputs.release_set_digest is None
    assert ready.status == "RELEASE_SET_READY"
    assert ready.reason_codes == ()
    assert ready.release_set_digest == deployment_release_set_digest(ready)
    assert len(ready.artifacts) == 6
    assert len({item.provenance_digest for item in ready.artifacts}) == 6


def test_projection_is_deterministic_and_metadata_only() -> None:
    first = _ready_manifest()
    second = _ready_manifest()
    projection = deployment_release_manifest_projection(first)

    assert projection == deployment_release_manifest_projection(second)
    assert projection["runtime_values_included"] is False
    assert projection["timestamps_included"] is False
    assert projection["machine_paths_included"] is False
    assert all("/home/" not in str(item) for item in projection["artifacts"])
    first_record = first.artifacts[0]
    without_digest = artifact_provenance_projection(
        first_record, include_provenance_digest=False
    )
    assert "provenance_digest" not in without_digest
    assert artifact_provenance_digest(first_record) == first_record.provenance_digest


def test_collection_rejects_partial_image_set() -> None:
    references = smoke._synthetic_image_references()
    references.pop(next(iter(references)))

    with pytest.raises(DeploymentProvenanceError, match="complete artifact set"):
        collect_deployment_release_manifest(
            ROOT,
            source_revision=REVISION,
            source_tree_clean=True,
            image_references=references,
        )


def test_validation_reports_artifact_and_release_policy_drift() -> None:
    valid = _ready_manifest()
    catalog = build_default_deployment_artifact_catalog()
    inputs = build_deployment_build_inputs(ROOT, catalog=catalog)
    first = valid.artifacts[0]
    bad = replace(
        first,
        owner="wrong",
        source_revision="b" * 40,
        dependency_lock_id="unknown",
        dependency_lock_digest="bad",
        build_definition_digest="bad",
        build_context_digest="bad",
        base_image_reference="python:latest",
        platform="windows/amd64",
        image_reference="registry.example/image:latest",
        provenance_digest="bad",
    )
    unknown = ArtifactBuildProvenance(
        "unknown",
        "unknown",
        REVISION,
        "unknown",
        "bad",
        "bad",
        "bad",
        "image:latest",
        "linux/amd64",
        "registry.example/image:latest",
        "bad",
    )
    invalid = replace(
        valid,
        schema_version="wrong",
        status="UNKNOWN",
        reason_codes=("changed",),
        source_revision="short",
        source_tree_clean=False,
        artifact_catalog_digest="bad",
        build_inputs_digest="bad",
        artifacts=(bad, bad, unknown),
        release_set_digest="bad",
        production_deployment_approved=True,
    )

    with pytest.raises(DeploymentProvenanceError) as raised:
        validate_deployment_release_manifest(
            invalid,
            catalog=catalog,
            inputs=inputs,
        )

    detail = str(raised.value)
    for expected in (
        "schema version",
        "status is invalid",
        "full Git SHA",
        "catalog digest drift",
        "build inputs digest drift",
        "owner drift",
        "source revision drift",
        "dependency lock drift",
        "definition digest is invalid",
        "context digest is invalid",
        "provenance digest is invalid",
        "base image is mutable",
        "platform drift",
        "image is mutable",
        "provenance digest drift",
        "duplicate artifact provenance",
        "unknown artifact provenance",
        "coverage must be exact",
        "partial image artifact set",
        "image references must be unique",
        "readiness decision drift",
        "set digest",
        "production deployment approval",
    ):
        assert expected in detail


def test_incomplete_manifest_cannot_claim_release_digest() -> None:
    manifest = collect_deployment_release_manifest(
        ROOT,
        source_revision=REVISION,
        source_tree_clean=True,
    )
    catalog = build_default_deployment_artifact_catalog()
    inputs = build_deployment_build_inputs(ROOT, catalog=catalog)

    with pytest.raises(DeploymentProvenanceError, match="cannot have a set digest"):
        validate_deployment_release_manifest(
            replace(manifest, release_set_digest="sha256:" + "0" * 64),
            catalog=catalog,
            inputs=inputs,
        )


def test_ready_manifest_fails_closed_when_prerequisites_are_removed() -> None:
    manifest = _ready_manifest()
    catalog = build_default_deployment_artifact_catalog()
    inputs = build_deployment_build_inputs(ROOT, catalog=catalog)
    invalid = replace(
        manifest,
        source_tree_clean=False,
        reason_codes=("source_tree_dirty",),
        artifacts=tuple(
            replace(record, image_reference=None) for record in manifest.artifacts
        ),
        release_set_digest="sha256:" + "0" * 64,
    )

    with pytest.raises(DeploymentProvenanceError) as raised:
        validate_deployment_release_manifest(
            invalid,
            catalog=catalog,
            inputs=inputs,
        )

    detail = str(raised.value)
    assert "release set requires a clean source tree" in detail
    assert "release set requires every image digest" in detail
    assert "ready release set must not have blocking reasons" in detail
    assert "release set digest drift" in detail


def test_definition_digest_rejects_missing_containerfile(tmp_path: Path) -> None:
    definition = build_default_oci_definitions()[0]
    with pytest.raises(DeploymentProvenanceError, match="build definition is missing"):
        oci_build_definition_digest(tmp_path, definition)
