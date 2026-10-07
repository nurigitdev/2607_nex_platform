from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from nex_runtime.deployment_artifacts import build_default_deployment_artifact_catalog
from nex_runtime.deployment_entrypoints import (
    build_packaged_entrypoint_definitions,
    build_packaged_runtime_manifest,
)
from nex_runtime.deployment_image_build import (
    BackgroundContainerCheck,
    OCI_BUILD_LABEL_KEYS,
    OCI_IMAGE_BUILD_EVIDENCE_SCHEMA_VERSION,
    OciImageBuildEvidence,
    OciImageBuildEvidenceError,
    OciImageBuildRecord,
    build_oci_image_build_evidence,
    oci_image_build_evidence_projection,
    validate_oci_image_build_evidence,
)
from nex_runtime.deployment_locks import (
    build_deployment_build_inputs,
    deployment_build_inputs_digest,
)
from nex_runtime.deployment_oci import build_default_oci_definitions
from nex_runtime.process_manifest import BACKGROUND_PROCESS_IDS


ROOT = Path(__file__).resolve().parents[1]
REVISION = "a" * 40


def _evidence() -> OciImageBuildEvidence:
    catalog = build_default_deployment_artifact_catalog()
    inputs = build_deployment_build_inputs(ROOT, catalog=catalog)
    definitions = build_default_oci_definitions(catalog)
    locks = {lock.lock_id: lock for lock in inputs.locks}
    artifacts = {item.artifact_id: item for item in catalog.artifacts}
    manifest = build_packaged_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    entrypoints = build_packaged_entrypoint_definitions(manifest, catalog)
    default_commands = {
        entry.artifact_id: entry.command
        for entry in entrypoints
        if entry.kind in {"api", "web"}
    }
    records = []
    for index, definition in enumerate(definitions, start=1):
        artifact = artifacts[definition.artifact_id]
        lock = locks[artifact.dependency_family]
        manifest_digest = f"sha256:{index + 100:064x}"
        records.append(
            OciImageBuildRecord(
                artifact_id=definition.artifact_id,
                owner=artifact.owner,
                target=definition.target,
                local_tag=f"nex-platform-local/{definition.artifact_id}:aaaaaaaaaaaa",
                image_id=f"sha256:{index:064x}",
                manifest_digest=manifest_digest,
                image_reference=(
                    f"nex-platform-local/{definition.artifact_id}@{manifest_digest}"
                ),
                base_image_reference=definition.base_image,
                source_revision=REVISION,
                dependency_lock_id=lock.lock_id,
                dependency_lock_digest=f"sha256:{lock.sha256}",
                build_definition_digest=f"sha256:{index + 200:064x}",
                build_context_digest=f"sha256:{index + 300:064x}",
                platform=definition.platform,
                runtime_user="node" if artifact.kind == "node-web" else "65532:65532",
                entrypoint=(),
                command=default_commands[definition.artifact_id],
                labels=tuple(
                    (
                        key,
                        {
                            "org.opencontainers.image.version": REVISION[:12],
                            "org.opencontainers.image.revision": REVISION,
                            "io.nex-platform.build-inputs-digest": (
                                deployment_build_inputs_digest(inputs)
                            ),
                        }[key],
                    )
                    for key in OCI_BUILD_LABEL_KEYS
                ),
            )
        )
    background = tuple(
        BackgroundContainerCheck(
            process_id=entry.process_id,
            artifact_id=entry.artifact_id,
            command=(*entry.command, "--check"),
            profile="local_mock",
            persistence_mode="memory",
            lifecycle_ready=True,
            work_claiming_enabled=False,
        )
        for process_id in BACKGROUND_PROCESS_IDS
        for entry in entrypoints
        if entry.process_id == process_id
    )
    return build_oci_image_build_evidence(
        root=ROOT,
        source_revision=REVISION,
        source_tree_clean=True,
        artifacts=tuple(records),
        background_checks=background,
        release_set_digest="sha256:" + "f" * 64,
    )


def test_complete_image_set_is_private_non_root_and_deterministic() -> None:
    evidence = _evidence()
    projection = oci_image_build_evidence_projection(evidence)

    assert evidence.schema_version == OCI_IMAGE_BUILD_EVIDENCE_SCHEMA_VERSION
    assert projection["status"] == "RELEASE_SET_BUILT"
    assert len(projection["artifacts"]) == 6
    assert len(projection["background_checks"]) == 7
    assert len({item["image_id"] for item in projection["artifacts"]}) == 6
    assert len({item["manifest_digest"] for item in projection["artifacts"]}) == 6
    assert all(item["runtime_user"] not in {"", "0", "root"} for item in projection["artifacts"])
    assert projection["registry_push_performed"] is False
    assert projection["production_contacted"] is False
    assert projection["credentials_included"] is False
    assert projection["machine_paths_included"] is False
    assert projection["runtime_values_included"] is False


def test_validation_requires_explicit_build_inputs() -> None:
    with pytest.raises(OciImageBuildEvidenceError, match="build inputs are required"):
        validate_oci_image_build_evidence(_evidence())


@pytest.mark.parametrize(
    ("change", "message"),
    (
        (lambda value: replace(value, schema_version="wrong"), "schema version"),
        (lambda value: replace(value, status="wrong"), "status drift"),
        (lambda value: replace(value, source_revision="short"), "revision is invalid"),
        (lambda value: replace(value, source_tree_clean=False), "clean source tree"),
        (lambda value: replace(value, build_inputs_digest="bad"), "inputs digest"),
        (lambda value: replace(value, release_set_digest="bad"), "set digest"),
        (lambda value: replace(value, artifacts=()), "artifact coverage"),
        (lambda value: replace(value, background_checks=()), "background check coverage"),
        (lambda value: replace(value, registry_push_performed=True), "must not push"),
        (lambda value: replace(value, production_contacted=True), "must not contact"),
    ),
)
def test_top_level_evidence_drift_fails_closed(change, message: str) -> None:
    evidence = change(_evidence())
    inputs = build_deployment_build_inputs(ROOT)

    with pytest.raises(OciImageBuildEvidenceError, match=message):
        validate_oci_image_build_evidence(evidence, inputs=inputs)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"owner": "wrong"}, "owner drift"),
        ({"target": "wrong"}, "target drift"),
        ({"local_tag": "bad@sha256"}, "local image tag"),
        ({"image_id": "bad"}, "image ID"),
        ({"manifest_digest": "bad"}, "manifest digest"),
        ({"image_reference": "mutable:latest"}, "immutable image reference"),
        ({"base_image_reference": "python:latest"}, "base image digest"),
        ({"source_revision": "b" * 40}, "source revision drift"),
        ({"dependency_lock_id": "wrong"}, "dependency lock drift"),
        ({"build_definition_digest": "bad"}, "definition digest"),
        ({"build_context_digest": "bad"}, "context digest"),
        ({"platform": "windows/amd64"}, "platform drift"),
        ({"runtime_user": "root"}, "runtime user is privileged"),
        ({"runtime_user": "0:0"}, "runtime user is privileged"),
        ({"entrypoint": ("python",)}, "entrypoint drift"),
        ({"command": ("wrong",)}, "packaged command drift"),
        ({"labels": ()}, "label drift"),
    ),
)
def test_image_record_drift_fails_closed(changes, message: str) -> None:
    evidence = _evidence()
    records = list(evidence.artifacts)
    records[0] = replace(records[0], **changes)
    inputs = build_deployment_build_inputs(ROOT)

    with pytest.raises(OciImageBuildEvidenceError, match=message):
        validate_oci_image_build_evidence(
            replace(evidence, artifacts=tuple(records)), inputs=inputs
        )


def test_duplicate_image_and_manifest_digests_fail_closed() -> None:
    evidence = _evidence()
    records = list(evidence.artifacts)
    records[1] = replace(
        records[1],
        image_id=records[0].image_id,
        manifest_digest=records[0].manifest_digest,
        image_reference=(
            f"nex-platform-local/{records[1].artifact_id}"
            f"@{records[0].manifest_digest}"
        ),
    )

    with pytest.raises(OciImageBuildEvidenceError) as raised:
        validate_oci_image_build_evidence(
            replace(evidence, artifacts=tuple(records)),
            inputs=build_deployment_build_inputs(ROOT),
        )

    assert "manifest digests must be unique" in str(raised.value)
    assert "image IDs must be unique" in str(raised.value)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"artifact_id": "wrong"}, "background artifact drift"),
        ({"command": ("wrong",)}, "background command drift"),
        ({"profile": "test"}, "background profile drift"),
        ({"persistence_mode": "postgres"}, "background persistence drift"),
        ({"lifecycle_ready": False}, "lifecycle is not ready"),
        ({"work_claiming_enabled": True}, "claimed work"),
    ),
)
def test_background_check_drift_fails_closed(changes, message: str) -> None:
    evidence = _evidence()
    checks = list(evidence.background_checks)
    checks[0] = replace(checks[0], **changes)

    with pytest.raises(OciImageBuildEvidenceError, match=message):
        validate_oci_image_build_evidence(
            replace(evidence, background_checks=tuple(checks)),
            inputs=build_deployment_build_inputs(ROOT),
        )


def test_unknown_artifact_and_background_process_fail_closed() -> None:
    evidence = _evidence()
    records = list(evidence.artifacts)
    records[0] = replace(records[0], artifact_id="unknown")
    checks = list(evidence.background_checks)
    checks[0] = replace(checks[0], process_id="unknown")

    with pytest.raises(OciImageBuildEvidenceError) as raised:
        validate_oci_image_build_evidence(
            replace(
                evidence,
                artifacts=tuple(records),
                background_checks=tuple(checks),
            ),
            inputs=build_deployment_build_inputs(ROOT),
        )

    assert "unknown OCI image artifact" in str(raised.value)
    assert "unknown OCI background check" in str(raised.value)
