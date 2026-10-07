from __future__ import annotations

from dataclasses import replace
import json

import pytest

from nex_runtime.deployment_artifacts import (
    DEFAULT_DEPLOYMENT_ARTIFACTS,
    DEFAULT_PROCESS_ARTIFACT_BINDINGS,
    DeploymentArtifactCatalog,
    DeploymentArtifactDefinition,
    DeploymentArtifactError,
    ProcessArtifactBinding,
    build_default_deployment_artifact_catalog,
    canonical_deployment_artifact_catalog,
    deployment_artifact_catalog_digest,
    deployment_artifact_catalog_projection,
    immutable_image_reference,
    validate_deployment_artifact_catalog,
)
from nex_runtime.process_manifest import build_platform_runtime_manifest


def catalog() -> DeploymentArtifactCatalog:
    return build_default_deployment_artifact_catalog()


def test_default_catalog_covers_runtime_manifest_exactly() -> None:
    value = catalog()
    runtime = build_platform_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )

    validate_deployment_artifact_catalog(value, runtime)
    projection = deployment_artifact_catalog_projection(value)

    assert len(projection["artifacts"]) == 6
    assert len(projection["process_bindings"]) == 13
    assert {item["kind"] for item in projection["artifacts"]} == {
        "python-service",
        "node-web",
    }
    assert projection["artifacts"][0]["artifact_id"] == "nex-ae-runtime"
    assert projection["process_bindings"][0]["process_id"] == "nex-ae-api"


def test_catalog_serialization_and_digest_are_order_independent() -> None:
    value = catalog()
    reversed_value = replace(
        value,
        artifacts=tuple(reversed(value.artifacts)),
        process_bindings=tuple(reversed(value.process_bindings)),
    )

    payload = canonical_deployment_artifact_catalog(value)

    assert payload == canonical_deployment_artifact_catalog(reversed_value)
    assert json.loads(payload)["schema_version"] == "deployment_artifact_catalog.v1"
    assert deployment_artifact_catalog_digest(value) == (
        deployment_artifact_catalog_digest(reversed_value)
    )
    assert deployment_artifact_catalog_digest(value).startswith("sha256:")
    assert len(deployment_artifact_catalog_digest(value)) == 71


@pytest.mark.parametrize(
    ("artifact", "message"),
    [
        (
            DeploymentArtifactDefinition(
                "Bad_id", "", "binary", "bad target", "", ()
            ),
            "invalid artifact_id",
        ),
        (
            replace(DEFAULT_DEPLOYMENT_ARTIFACTS[0], source_roots=()),
            "source roots are empty",
        ),
        (
            replace(
                DEFAULT_DEPLOYMENT_ARTIFACTS[0],
                source_roots=("services/nex-oa", "services/nex-oa"),
            ),
            "duplicate source root",
        ),
        (
            replace(DEFAULT_DEPLOYMENT_ARTIFACTS[0], source_roots=("../secret",)),
            "invalid source root",
        ),
        (
            replace(DEFAULT_DEPLOYMENT_ARTIFACTS[0], source_roots=("bad\\path",)),
            "invalid source root",
        ),
    ],
)
def test_catalog_rejects_invalid_artifact_fields(artifact, message) -> None:
    value = DeploymentArtifactCatalog(
        "wrong.v1",
        (artifact, artifact),
        (ProcessArtifactBinding("bad process", "missing", "bad entry"),),
    )

    with pytest.raises(DeploymentArtifactError) as raised:
        validate_deployment_artifact_catalog(value)

    detail = str(raised.value)
    assert "schema_version" in detail
    assert message in detail
    assert "duplicate artifact_id" in detail
    assert "invalid process_id" in detail
    assert "unknown artifact binding" in detail
    assert "invalid entrypoint_id" in detail


def test_catalog_rejects_duplicate_build_target_and_unbound_artifact() -> None:
    duplicate_target = replace(
        DEFAULT_DEPLOYMENT_ARTIFACTS[1],
        build_target=DEFAULT_DEPLOYMENT_ARTIFACTS[0].build_target,
    )
    value = DeploymentArtifactCatalog(
        "deployment_artifact_catalog.v1",
        (DEFAULT_DEPLOYMENT_ARTIFACTS[0], duplicate_target),
        (DEFAULT_PROCESS_ARTIFACT_BINDINGS[0],),
    )

    with pytest.raises(DeploymentArtifactError) as raised:
        validate_deployment_artifact_catalog(value)

    assert "duplicate build target" in str(raised.value)
    assert "artifact has no process binding: nex-ae-runtime" in str(raised.value)


def test_catalog_rejects_duplicate_binding_and_runtime_drift() -> None:
    runtime = build_platform_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    wrong_owner = replace(DEFAULT_DEPLOYMENT_ARTIFACTS[0], owner="nex-cx")
    bindings = (
        DEFAULT_PROCESS_ARTIFACT_BINDINGS[0],
        DEFAULT_PROCESS_ARTIFACT_BINDINGS[0],
        ProcessArtifactBinding("extra-process", "nex-oa-runtime", "worker"),
    )
    value = DeploymentArtifactCatalog(
        "deployment_artifact_catalog.v1", (wrong_owner,), bindings
    )

    with pytest.raises(DeploymentArtifactError) as raised:
        validate_deployment_artifact_catalog(value, runtime)

    detail = str(raised.value)
    assert "duplicate process binding" in detail
    assert "runtime process is not bound" in detail
    assert "bound process is not in runtime manifest" in detail
    assert "process owner mismatch" in detail


@pytest.mark.parametrize(
    ("repository", "digest", "message"),
    [
        ("Registry.EXAMPLE/nex-oa", "sha256:" + "a" * 64, "repository"),
        ("nex-platform/nex-oa", "sha256:ABC", "content digest"),
        ("nex-platform/nex-oa:latest", "sha256:" + "a" * 64, "repository"),
    ],
)
def test_immutable_image_reference_rejects_mutable_or_invalid_values(
    repository, digest, message
) -> None:
    with pytest.raises(DeploymentArtifactError, match=message):
        immutable_image_reference(repository, digest)


def test_immutable_image_reference_uses_digest_not_tag() -> None:
    digest = "sha256:" + "f" * 64
    assert immutable_image_reference("registry.example/nex/nex-oa", digest) == (
        f"registry.example/nex/nex-oa@{digest}"
    )

