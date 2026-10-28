from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .semantic_hashes import validate_hash_ref

NSL_RUNTIME_BUNDLE_SCHEMA_VERSION = "nex_nsl_runtime_bundle.v1"


class NslRuntimeBundleError(ValueError):
    pass


@dataclass(frozen=True)
class NslRuntimeBundle:
    bundle_id: str
    admitted_at: str
    wheel_filename: str
    wheel_sha256: str
    admission_lock: str
    skill_id: str
    skill_version: str
    skill_semantic_hash: str
    skill_source_directory: str
    skill_files: Mapping[str, str]


def load_nsl_runtime_bundle(path: Path) -> NslRuntimeBundle:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NslRuntimeBundleError("NSL bundle manifest is unreadable.") from exc
    if not isinstance(value, Mapping):
        raise NslRuntimeBundleError("NSL bundle manifest must be an object.")
    if set(value) != {"schema_version", "bundle_id", "admitted_at", "wheel", "skill"}:
        raise NslRuntimeBundleError("NSL bundle manifest fields are invalid.")
    if value.get("schema_version") != NSL_RUNTIME_BUNDLE_SCHEMA_VERSION:
        raise NslRuntimeBundleError("NSL bundle schema version is invalid.")
    wheel = _mapping(value.get("wheel"), "wheel")
    skill = _mapping(value.get("skill"), "skill")
    files = _mapping(skill.get("files"), "skill.files")
    return NslRuntimeBundle(
        bundle_id=_text(value.get("bundle_id"), "bundle_id"),
        admitted_at=_timestamp(value.get("admitted_at"), "admitted_at"),
        wheel_filename=_relative(wheel.get("filename"), "wheel.filename"),
        wheel_sha256=_digest(wheel.get("sha256"), "wheel.sha256"),
        admission_lock=_relative(wheel.get("admission_lock"), "wheel.admission_lock"),
        skill_id=_text(skill.get("skill_id"), "skill.skill_id"),
        skill_version=_text(skill.get("skill_version"), "skill.skill_version"),
        skill_semantic_hash=validate_hash_ref(skill.get("semantic_hash")),
        skill_source_directory=_relative(
            skill.get("source_directory"), "skill.source_directory"
        ),
        skill_files={
            _relative(name, "skill.files key"): _digest(digest, "skill.files digest")
            for name, digest in files.items()
        },
    )


def verify_nsl_runtime_bundle(
    bundle: NslRuntimeBundle,
    *,
    wheel_path: Path,
    skill_root: Path,
) -> dict[str, Any]:
    if wheel_path.name != bundle.wheel_filename:
        raise NslRuntimeBundleError("NSL wheel filename differs from the manifest.")
    _require_digest(wheel_path, bundle.wheel_sha256, "NSL wheel")
    for relative, expected in bundle.skill_files.items():
        _require_digest(
            _contained(skill_root, relative), expected, f"Skill artifact {relative}"
        )
    return {
        "schema_version": "nex_nsl_runtime_bundle_readiness.v1",
        "status": "PASS",
        "bundle_id": bundle.bundle_id,
        "wheel_sha256": bundle.wheel_sha256,
        "skill_id": bundle.skill_id,
        "skill_version": bundle.skill_version,
        "skill_semantic_hash": bundle.skill_semantic_hash,
        "skill_file_count": len(bundle.skill_files),
        "secret_included": False,
    }


def _contained(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise NslRuntimeBundleError("NSL bundle path escapes its root.")
    return candidate


def _require_digest(path: Path, expected: str, label: str) -> None:
    try:
        observed = sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise NslRuntimeBundleError(f"{label} is unavailable.") from exc
    if observed != expected:
        raise NslRuntimeBundleError(f"{label} digest differs from the manifest.")


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise NslRuntimeBundleError(f"{field} must be an object.")
    return dict(value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise NslRuntimeBundleError(f"{field} must be a bounded non-empty string.")
    return value.strip()


def _relative(value: object, field: str) -> str:
    result = _text(value, field)
    path = Path(result)
    if path.is_absolute() or ".." in path.parts:
        raise NslRuntimeBundleError(f"{field} must be a contained relative path.")
    return result


def _digest(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise NslRuntimeBundleError(f"{field} must be a lowercase SHA-256 digest.")
    return value


def _timestamp(value: object, field: str) -> str:
    result = _text(value, field)
    if not result.endswith("Z"):
        raise NslRuntimeBundleError(f"{field} must be a UTC RFC3339 timestamp.")
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NslRuntimeBundleError(f"{field} must be a UTC RFC3339 timestamp.") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise NslRuntimeBundleError(f"{field} must be a UTC RFC3339 timestamp.")
    return result
