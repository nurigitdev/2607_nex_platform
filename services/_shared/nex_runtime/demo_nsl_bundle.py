from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from nex_runtime.semantic_hashes import validate_hash_ref

DEMO_NSL_BUNDLE_SCHEMA_VERSION = "p8_demo_nsl_runtime_bundle.v1"


class DemoNslBundleError(ValueError):
    pass


@dataclass(frozen=True)
class DemoNslRuntimeBundle:
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
    demo_fixture_path: str
    demo_fixture_sha256: str
    base_fixture_path: str
    base_fixture_sha256: str


def load_demo_nsl_runtime_bundle(path: Path) -> DemoNslRuntimeBundle:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DemoNslBundleError("Demo NSL bundle manifest is unreadable.") from exc
    if not isinstance(value, Mapping):
        raise DemoNslBundleError("Demo NSL bundle manifest must be an object.")
    if value.get("schema_version") != DEMO_NSL_BUNDLE_SCHEMA_VERSION:
        raise DemoNslBundleError("Demo NSL bundle schema version is invalid.")
    wheel = _mapping(value.get("wheel"), "wheel")
    skill = _mapping(value.get("skill"), "skill")
    demo_fixture = _mapping(value.get("demo_fixture"), "demo_fixture")
    base_fixture = _mapping(value.get("base_fixture"), "base_fixture")
    files = _mapping(skill.get("files"), "skill.files")
    return DemoNslRuntimeBundle(
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
        demo_fixture_path=_relative(demo_fixture.get("path"), "demo_fixture.path"),
        demo_fixture_sha256=_digest(demo_fixture.get("sha256"), "demo_fixture.sha256"),
        base_fixture_path=_relative(base_fixture.get("path"), "base_fixture.path"),
        base_fixture_sha256=_digest(base_fixture.get("sha256"), "base_fixture.sha256"),
    )


def verify_demo_nsl_runtime_bundle(
    bundle: DemoNslRuntimeBundle,
    *,
    wheel_path: Path,
    skill_root: Path,
    demo_fixture_path: Path,
    base_fixture_path: Path,
) -> dict[str, Any]:
    if wheel_path.name != bundle.wheel_filename:
        raise DemoNslBundleError("Demo NSL wheel filename differs from the manifest.")
    _require_digest(wheel_path, bundle.wheel_sha256, "NSL wheel")
    for relative, expected in bundle.skill_files.items():
        candidate = _contained(skill_root, relative)
        _require_digest(candidate, expected, f"Skill artifact {relative}")
    _require_digest(demo_fixture_path, bundle.demo_fixture_sha256, "Demo fixture")
    _require_digest(base_fixture_path, bundle.base_fixture_sha256, "base fixture")
    return {
        "schema_version": "p8_demo_nsl_runtime_bundle_readiness.v1",
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
        raise DemoNslBundleError("Demo NSL bundle path escapes its root.")
    return candidate


def _require_digest(path: Path, expected: str, label: str) -> None:
    try:
        observed = sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise DemoNslBundleError(f"{label} is unavailable.") from exc
    if observed != expected:
        raise DemoNslBundleError(f"{label} digest differs from the manifest.")


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DemoNslBundleError(f"{field} must be an object.")
    return dict(value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise DemoNslBundleError(f"{field} must be a bounded non-empty string.")
    return value.strip()


def _relative(value: object, field: str) -> str:
    result = _text(value, field)
    path = Path(result)
    if path.is_absolute() or ".." in path.parts:
        raise DemoNslBundleError(f"{field} must be a contained relative path.")
    return result


def _digest(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DemoNslBundleError(f"{field} must be a lowercase SHA-256 digest.")
    return value


def _timestamp(value: object, field: str) -> str:
    result = _text(value, field)
    if not result.endswith("Z"):
        raise DemoNslBundleError(f"{field} must be a UTC RFC3339 timestamp.")
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DemoNslBundleError(f"{field} must be a UTC RFC3339 timestamp.") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise DemoNslBundleError(f"{field} must be a UTC RFC3339 timestamp.")
    return result
