from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from nex_runtime.deployment_artifacts import (
    DeploymentArtifactCatalog,
    build_default_deployment_artifact_catalog,
)
from nex_runtime.deployment_oci import (
    NODE_BASE_IMAGE,
    NODE_CONTAINERFILE,
    OCI_BUILD_DEFINITIONS_SCHEMA_VERSION,
    PYTHON_BASE_IMAGE,
    PYTHON_BUILDER_IMAGE,
    PYTHON_CONTAINERFILE,
    RUST_BUILDER_IMAGE,
    OciBuildDefinition,
    OciBuildDefinitionError,
    _excluded_context_file,
    build_default_oci_definitions,
    materialize_oci_build_context,
    oci_build_context_digest,
    oci_build_context_projection,
    validate_oci_build_definitions,
    validate_oci_containerfiles,
)


ROOT = Path(__file__).resolve().parents[1]


def test_default_oci_definitions_cover_catalog_exactly() -> None:
    catalog = build_default_deployment_artifact_catalog()
    definitions = build_default_oci_definitions(catalog)

    validate_oci_build_definitions(definitions, catalog)
    validate_oci_containerfiles(ROOT, definitions)

    assert len(definitions) == 6
    assert {item.artifact_id for item in definitions} == {
        item.artifact_id for item in catalog.artifacts
    }
    assert {item.target for item in definitions} == {
        "oa-runtime",
        "ae-runtime",
        "cx-runtime",
        "mo-runtime",
        "ag-runtime",
        "ae-web",
    }
    assert sum(item.base_image == PYTHON_BASE_IMAGE for item in definitions) == 5
    assert sum(item.base_image == NODE_BASE_IMAGE for item in definitions) == 1
    assert sum(
        item.builder_images == (PYTHON_BUILDER_IMAGE, RUST_BUILDER_IMAGE)
        for item in definitions
    ) == 5
    assert sum(not item.builder_images for item in definitions) == 1


def test_oci_definition_validation_reports_all_invalid_fields() -> None:
    catalog = build_default_deployment_artifact_catalog()
    invalid = OciBuildDefinition(
        artifact_id="unknown",
        containerfile="Dockerfile",
        target="same",
        platform="windows/amd64",
        base_image="python:latest",
        context_paths=("../secret", "../secret"),
        builder_images=("rust:latest", "rust:latest"),
    )
    empty = replace(invalid, artifact_id="nex-oa-runtime", context_paths=())

    with pytest.raises(OciBuildDefinitionError) as raised:
        validate_oci_build_definitions((invalid, invalid, empty), catalog)

    detail = str(raised.value)
    for expected in (
        "duplicate OCI artifact definition",
        "unknown OCI artifact definition",
        "duplicate OCI target",
        "unsupported OCI platform",
        "base image is not digest pinned",
        "duplicate builder image",
        "builder image is not digest pinned",
        "invalid Containerfile path",
        "duplicate OCI context path",
        "unsafe OCI context path",
        "empty OCI context",
        "artifact has no OCI definition",
    ):
        assert expected in detail


def test_oci_definition_validation_detects_catalog_without_definition() -> None:
    catalog = DeploymentArtifactCatalog(
        "deployment_artifact_catalog.v1",
        build_default_deployment_artifact_catalog().artifacts[:1],
        (),
    )
    with pytest.raises(OciBuildDefinitionError, match="has no OCI definition"):
        validate_oci_build_definitions((), catalog)


def test_oci_definition_validation_rejects_non_hex_digest() -> None:
    catalog = build_default_deployment_artifact_catalog()
    definition = replace(
        build_default_oci_definitions(catalog)[0],
        base_image=f"python:3.12@sha256:{'g' * 64}",
    )

    with pytest.raises(OciBuildDefinitionError, match="not digest pinned"):
        validate_oci_build_definitions((definition,), catalog)


def test_containerfile_validation_fails_closed(tmp_path: Path) -> None:
    definitions = build_default_oci_definitions()
    with pytest.raises(OciBuildDefinitionError, match="Containerfile is missing"):
        validate_oci_containerfiles(tmp_path, definitions)

    for relative in (PYTHON_CONTAINERFILE, NODE_CONTAINERFILE):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("FROM image:latest\nADD . /app\n", encoding="utf-8")

    with pytest.raises(OciBuildDefinitionError) as raised:
        validate_oci_containerfiles(tmp_path, definitions)

    detail = str(raised.value)
    assert "base image digest drift" in detail
    assert "builder image digest drift" in detail
    assert "OCI target is missing" in detail
    assert "non-root user is missing" in detail
    assert "ADD is prohibited" in detail
    assert "does not enforce the production lock" in detail
    assert "does not isolate runtime wheel installation" in detail
    assert "does not enforce npm ci" in detail


def test_materialized_context_is_deterministic_and_owner_scoped(tmp_path: Path) -> None:
    definition = next(
        item for item in build_default_oci_definitions() if item.artifact_id == "nex-ae-web"
    )
    first = materialize_oci_build_context(ROOT, tmp_path / "first", definition)
    second = materialize_oci_build_context(ROOT, tmp_path / "second", definition)

    assert first.schema_version == OCI_BUILD_DEFINITIONS_SCHEMA_VERSION
    assert oci_build_context_digest(first) == oci_build_context_digest(second)
    projection = oci_build_context_projection(first)
    assert projection["artifact_id"] == "nex-ae-web"
    assert projection["file_count"] > 40
    assert projection["byte_count"] > 0
    paths = {item["path"] for item in projection["files"]}
    assert "Containerfile" in paths
    assert "apps/nex-ae-web/index.html" in paths
    assert not any("node_modules" in path or "/test/" in path for path in paths)


def test_materializer_rejects_existing_destination_and_missing_source(
    tmp_path: Path,
) -> None:
    definition = build_default_oci_definitions()[0]
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(OciBuildDefinitionError, match="already exists"):
        materialize_oci_build_context(ROOT, existing, definition)

    missing = replace(definition, context_paths=("missing/source",))
    with pytest.raises(OciBuildDefinitionError, match="source is missing"):
        materialize_oci_build_context(ROOT, tmp_path / "missing", missing)


def test_materializer_rejects_empty_context(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty-context.Containerfile").mkdir()
    definition = OciBuildDefinition(
        "empty",
        "empty-context.Containerfile",
        "empty",
        "linux/amd64",
        PYTHON_BASE_IMAGE,
        ("empty",),
    )

    with pytest.raises(OciBuildDefinitionError, match="contains no files"):
        materialize_oci_build_context(tmp_path, tmp_path / "output", definition)


@pytest.mark.parametrize(
    "path",
    [
        Path("__pycache__/module.pyc"),
        Path("tests/test_module.py"),
        Path("node_modules/a/index.js"),
        Path("module.pyo"),
        Path(".DS_Store"),
    ],
)
def test_context_exclusion_policy(path: Path) -> None:
    assert _excluded_context_file(path) is True


def test_context_exclusion_policy_accepts_runtime_source() -> None:
    assert _excluded_context_file(Path("nex_oa/main.py")) is False
