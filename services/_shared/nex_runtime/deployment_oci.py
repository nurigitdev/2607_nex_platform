from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

from .deployment_artifacts import (
    DeploymentArtifactCatalog,
    build_default_deployment_artifact_catalog,
)


OCI_BUILD_DEFINITIONS_SCHEMA_VERSION = "oci_build_definitions.v1"
PYTHON_BASE_IMAGE = (
    "python:3.12.13-slim-bookworm@"
    "sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2"
)
NODE_BASE_IMAGE = (
    "node:22-bookworm-slim@"
    "sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392"
)
PYTHON_CONTAINERFILE = "deployment/oci/python-service.Containerfile"
NODE_CONTAINERFILE = "deployment/oci/ae-web.Containerfile"
_EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", "node_modules", "test", "tests"}
_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


class OciBuildDefinitionError(ValueError):
    pass


@dataclass(frozen=True)
class OciBuildDefinition:
    artifact_id: str
    containerfile: str
    target: str
    platform: str
    base_image: str
    context_paths: tuple[str, ...]


@dataclass(frozen=True)
class OciContextFile:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class OciBuildContextManifest:
    schema_version: str
    artifact_id: str
    target: str
    files: tuple[OciContextFile, ...]


def build_default_oci_definitions(
    catalog: DeploymentArtifactCatalog | None = None,
) -> tuple[OciBuildDefinition, ...]:
    artifact_catalog = catalog or build_default_deployment_artifact_catalog()
    definitions = []
    for artifact in artifact_catalog.artifacts:
        if artifact.kind == "python-service":
            service_id = artifact.owner
            context_paths = (
                *artifact.source_roots,
                f"database/{service_id}",
                "scripts/db",
                "deployment/locks/python-production.lock",
            )
            containerfile = PYTHON_CONTAINERFILE
            base_image = PYTHON_BASE_IMAGE
        else:
            context_paths = (
                "apps/nex-ae-web/package.json",
                "apps/nex-ae-web/package-lock.json",
                "apps/nex-ae-web/index.html",
                "apps/nex-ae-web/src",
                "apps/nex-ae-web/scripts/serve.mjs",
            )
            containerfile = NODE_CONTAINERFILE
            base_image = NODE_BASE_IMAGE
        definitions.append(
            OciBuildDefinition(
                artifact_id=artifact.artifact_id,
                containerfile=containerfile,
                target=artifact.build_target,
                platform="linux/amd64",
                base_image=base_image,
                context_paths=context_paths,
            )
        )
    result = tuple(definitions)
    validate_oci_build_definitions(result, artifact_catalog)
    return result


def validate_oci_build_definitions(
    definitions: tuple[OciBuildDefinition, ...],
    catalog: DeploymentArtifactCatalog,
) -> None:
    errors: list[str] = []
    artifact_ids = {artifact.artifact_id for artifact in catalog.artifacts}
    definition_ids: set[str] = set()
    targets: set[str] = set()
    for definition in definitions:
        if definition.artifact_id in definition_ids:
            errors.append(f"duplicate OCI artifact definition: {definition.artifact_id}")
        definition_ids.add(definition.artifact_id)
        if definition.artifact_id not in artifact_ids:
            errors.append(f"unknown OCI artifact definition: {definition.artifact_id}")
        if definition.target in targets:
            errors.append(f"duplicate OCI target: {definition.target}")
        targets.add(definition.target)
        if definition.platform != "linux/amd64":
            errors.append(f"unsupported OCI platform: {definition.artifact_id}")
        if re.fullmatch(r"[^@]+@sha256:[0-9a-f]{64}", definition.base_image) is None:
            errors.append(f"base image is not digest pinned: {definition.artifact_id}")
        if not definition.containerfile.endswith(".Containerfile"):
            errors.append(f"invalid Containerfile path: {definition.artifact_id}")
        if not definition.context_paths:
            errors.append(f"empty OCI context: {definition.artifact_id}")
        if len(set(definition.context_paths)) != len(definition.context_paths):
            errors.append(f"duplicate OCI context path: {definition.artifact_id}")
        for context_path in definition.context_paths:
            path = Path(context_path)
            if path.is_absolute() or ".." in path.parts:
                errors.append(f"unsafe OCI context path: {definition.artifact_id}")
    for missing in sorted(artifact_ids - definition_ids):
        errors.append(f"artifact has no OCI definition: {missing}")
    if errors:
        raise OciBuildDefinitionError("; ".join(errors))


def validate_oci_containerfiles(
    root: Path,
    definitions: tuple[OciBuildDefinition, ...],
) -> None:
    errors: list[str] = []
    by_path: dict[str, str] = {}
    for definition in definitions:
        path = root / definition.containerfile
        try:
            text = by_path.setdefault(
                definition.containerfile, path.read_text(encoding="utf-8")
            )
        except OSError:
            errors.append(f"Containerfile is missing: {definition.containerfile}")
            continue
        if definition.base_image not in text:
            errors.append(f"base image digest drift: {definition.artifact_id}")
        if f" AS {definition.target}" not in text:
            errors.append(f"OCI target is missing: {definition.artifact_id}")
        if "USER " not in text:
            errors.append(f"non-root user is missing: {definition.artifact_id}")
        if "ADD " in text:
            errors.append(f"ADD is prohibited: {definition.artifact_id}")
    python_text = by_path.get(PYTHON_CONTAINERFILE, "")
    if "--no-deps --require-hashes" not in python_text:
        errors.append("Python Containerfile does not enforce the production lock")
    node_text = by_path.get(NODE_CONTAINERFILE, "")
    if "npm ci --omit=dev --ignore-scripts" not in node_text:
        errors.append("Node Containerfile does not enforce npm ci")
    if errors:
        raise OciBuildDefinitionError("; ".join(errors))


def materialize_oci_build_context(
    root: Path,
    destination: Path,
    definition: OciBuildDefinition,
) -> OciBuildContextManifest:
    if destination.exists():
        raise OciBuildDefinitionError("OCI context destination already exists")
    destination.mkdir(parents=True)
    _copy_path(root, destination, definition.containerfile, "Containerfile")
    for context_path in definition.context_paths:
        _copy_path(root, destination, context_path, context_path)
    files = tuple(
        OciContextFile(
            path=path.relative_to(destination).as_posix(),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            size=path.stat().st_size,
        )
        for path in sorted(item for item in destination.rglob("*") if item.is_file())
    )
    manifest = OciBuildContextManifest(
        schema_version=OCI_BUILD_DEFINITIONS_SCHEMA_VERSION,
        artifact_id=definition.artifact_id,
        target=definition.target,
        files=files,
    )
    if not files:
        raise OciBuildDefinitionError("OCI context contains no files")
    return manifest


def oci_build_context_projection(
    manifest: OciBuildContextManifest,
) -> dict[str, Any]:
    return {
        "schema_version": manifest.schema_version,
        "artifact_id": manifest.artifact_id,
        "target": manifest.target,
        "files": [
            {"path": item.path, "sha256": item.sha256, "size": item.size}
            for item in manifest.files
        ],
        "file_count": len(manifest.files),
        "byte_count": sum(item.size for item in manifest.files),
    }


def oci_build_context_digest(manifest: OciBuildContextManifest) -> str:
    payload = json.dumps(
        oci_build_context_projection(manifest),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _copy_path(root: Path, destination: Path, source_value: str, target_value: str) -> None:
    source = root / source_value
    target = destination / target_value
    if not source.exists():
        raise OciBuildDefinitionError(f"OCI context source is missing: {source_value}")
    if source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        relative = path.relative_to(source)
        if _excluded_context_file(relative):
            continue
        output = target / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, output)


def _excluded_context_file(path: Path) -> bool:
    return bool(
        _EXCLUDED_PARTS.intersection(path.parts)
        or path.suffix in _EXCLUDED_SUFFIXES
        or path.name == ".DS_Store"
    )
