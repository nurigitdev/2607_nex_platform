from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .deployment_artifacts import (
    DeploymentArtifactCatalog,
    build_default_deployment_artifact_catalog,
    deployment_artifact_catalog_digest,
)


DEPLOYMENT_BUILD_INPUTS_SCHEMA_VERSION = "deployment_build_inputs.v1"
PYTHON_LOCK_PATH = "deployment/locks/python-production.lock"
NODE_LOCK_PATH = "apps/nex-ae-web/package-lock.json"
PYTHON_LOCK_COMMAND = "scripts/deployment/compile_python_lock.sh"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PYTHON_PACKAGE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s\\]+)(?:\s+\\)?$"
)
_PYTHON_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})")
_RUNTIME_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}$")


class DeploymentLockError(ValueError):
    pass


@dataclass(frozen=True)
class DependencyLockRecord:
    lock_id: str
    ecosystem: str
    path: str
    sha256: str
    package_count: int
    integrity_count: int


@dataclass(frozen=True)
class DeploymentBuildInputs:
    schema_version: str
    python_runtime: str
    node_runtime: str
    artifact_catalog_digest: str
    locks: tuple[DependencyLockRecord, ...]


def build_deployment_build_inputs(
    root: Path,
    *,
    catalog: DeploymentArtifactCatalog | None = None,
) -> DeploymentBuildInputs:
    artifact_catalog = catalog or build_default_deployment_artifact_catalog()
    python_runtime = _read_required_text(root / ".python-version")
    node_runtime = _read_required_text(root / ".nvmrc")
    python_lock = _python_lock_record(root / PYTHON_LOCK_PATH)
    node_lock = _node_lock_record(root / NODE_LOCK_PATH)
    inputs = DeploymentBuildInputs(
        schema_version=DEPLOYMENT_BUILD_INPUTS_SCHEMA_VERSION,
        python_runtime=python_runtime,
        node_runtime=node_runtime,
        artifact_catalog_digest=deployment_artifact_catalog_digest(
            artifact_catalog
        ),
        locks=(python_lock, node_lock),
    )
    validate_deployment_build_inputs(inputs, artifact_catalog)
    return inputs


def validate_deployment_build_inputs(
    inputs: DeploymentBuildInputs,
    catalog: DeploymentArtifactCatalog,
) -> None:
    errors: list[str] = []
    if inputs.schema_version != DEPLOYMENT_BUILD_INPUTS_SCHEMA_VERSION:
        errors.append("unsupported deployment build inputs schema_version")
    if not _RUNTIME_VERSION.fullmatch(inputs.python_runtime):
        errors.append("invalid Python runtime constraint")
    if not _RUNTIME_VERSION.fullmatch(inputs.node_runtime):
        errors.append("invalid Node runtime constraint")
    if not inputs.artifact_catalog_digest.startswith("sha256:") or not _SHA256.fullmatch(
        inputs.artifact_catalog_digest.removeprefix("sha256:")
    ):
        errors.append("invalid artifact catalog digest")

    lock_ids: set[str] = set()
    for lock in inputs.locks:
        if lock.lock_id in lock_ids:
            errors.append(f"duplicate dependency lock: {lock.lock_id}")
        lock_ids.add(lock.lock_id)
        if lock.ecosystem not in {"python", "node"}:
            errors.append(f"unsupported lock ecosystem: {lock.lock_id}")
        if not lock.path or Path(lock.path).is_absolute() or ".." in Path(lock.path).parts:
            errors.append(f"invalid dependency lock path: {lock.lock_id}")
        if not _SHA256.fullmatch(lock.sha256):
            errors.append(f"invalid dependency lock digest: {lock.lock_id}")
        if lock.package_count <= 0:
            errors.append(f"empty dependency lock: {lock.lock_id}")
        if lock.integrity_count < lock.package_count:
            errors.append(f"incomplete dependency integrity: {lock.lock_id}")

    dependency_families = {artifact.dependency_family for artifact in catalog.artifacts}
    for dependency_family in sorted(dependency_families - lock_ids):
        errors.append(f"artifact dependency family is unlocked: {dependency_family}")
    for lock_id in sorted(lock_ids - dependency_families):
        errors.append(f"unused dependency lock: {lock_id}")
    if inputs.artifact_catalog_digest != deployment_artifact_catalog_digest(catalog):
        errors.append("artifact catalog digest mismatch")
    if errors:
        raise DeploymentLockError("; ".join(errors))


def deployment_build_inputs_projection(
    inputs: DeploymentBuildInputs,
) -> dict[str, Any]:
    return {
        "schema_version": inputs.schema_version,
        "python_runtime": inputs.python_runtime,
        "node_runtime": inputs.node_runtime,
        "artifact_catalog_digest": inputs.artifact_catalog_digest,
        "locks": [
            {
                "lock_id": lock.lock_id,
                "ecosystem": lock.ecosystem,
                "path": lock.path,
                "sha256": lock.sha256,
                "package_count": lock.package_count,
                "integrity_count": lock.integrity_count,
            }
            for lock in sorted(inputs.locks, key=lambda item: item.lock_id)
        ],
    }


def canonical_deployment_build_inputs(inputs: DeploymentBuildInputs) -> bytes:
    return json.dumps(
        deployment_build_inputs_projection(inputs),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def deployment_build_inputs_digest(inputs: DeploymentBuildInputs) -> str:
    payload = canonical_deployment_build_inputs(inputs)
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _python_lock_record(path: Path) -> DependencyLockRecord:
    text = _read_required_text(path, strip=False)
    if PYTHON_LOCK_COMMAND not in text:
        raise DeploymentLockError("Python lock compile command is missing")
    if any(
        line.lstrip().startswith(("-e ", "--index-url", "--extra-index-url"))
        for line in text.splitlines()
    ):
        raise DeploymentLockError("Python lock contains a forbidden source")

    packages: list[str] = []
    package_hash_counts: list[int] = []
    current_hash_count = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = _PYTHON_PACKAGE.fullmatch(line)
        if match:
            if packages:
                package_hash_counts.append(current_hash_count)
            packages.append(match.group(1).lower().replace("_", "-"))
            current_hash_count = len(_PYTHON_HASH.findall(line))
        elif packages:
            current_hash_count += len(_PYTHON_HASH.findall(line))
    if packages:
        package_hash_counts.append(current_hash_count)
    if not packages:
        raise DeploymentLockError("Python lock contains no exact packages")
    if len(set(packages)) != len(packages):
        raise DeploymentLockError("Python lock contains duplicate packages")
    if any(count == 0 for count in package_hash_counts):
        raise DeploymentLockError("Python lock package is missing a SHA-256 hash")
    return DependencyLockRecord(
        lock_id="python-production",
        ecosystem="python",
        path=PYTHON_LOCK_PATH,
        sha256=_file_sha256(path),
        package_count=len(packages),
        integrity_count=sum(package_hash_counts),
    )


def _node_lock_record(path: Path) -> DependencyLockRecord:
    text = _read_required_text(path, strip=False)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeploymentLockError("Node lock is not valid JSON") from exc
    if payload.get("lockfileVersion") != 3:
        raise DeploymentLockError("Node lockfileVersion must be 3")
    packages = payload.get("packages")
    if not isinstance(packages, dict):
        raise DeploymentLockError("Node lock packages are missing")
    resolved_packages = [
        value
        for key, value in packages.items()
        if key and isinstance(value, dict)
    ]
    if not resolved_packages:
        raise DeploymentLockError("Node lock contains no resolved packages")
    for package in resolved_packages:
        version = package.get("version")
        resolved = package.get("resolved")
        integrity = package.get("integrity")
        if not isinstance(version, str) or not version or any(
            marker in version for marker in ("*", "^", "~", ">", "<")
        ):
            raise DeploymentLockError("Node lock package version is not exact")
        if not isinstance(resolved, str) or not resolved.startswith("https://"):
            raise DeploymentLockError("Node lock package source is not HTTPS")
        if not isinstance(integrity, str) or not integrity.startswith("sha512-"):
            raise DeploymentLockError("Node lock package integrity is missing")
    return DependencyLockRecord(
        lock_id="node-production",
        ecosystem="node",
        path=NODE_LOCK_PATH,
        sha256=_file_sha256(path),
        package_count=len(resolved_packages),
        integrity_count=len(resolved_packages),
    )


def _read_required_text(path: Path, *, strip: bool = True) -> str:
    try:
        value = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeploymentLockError(f"required build input is missing: {path.name}") from exc
    return value.strip() if strip else value


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise DeploymentLockError(f"required build input is missing: {path.name}") from exc

