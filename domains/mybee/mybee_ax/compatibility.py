"""Fail-closed validation for the MyBee Platform compatibility lock."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FROZEN_AUTHORITY_PATH = Path(
    "docs/frozen/v2.1/10_PLATFORM_v2.1/05_NORMATIVE_BASELINE/"
    "NeX_Platform_v2.1_Architecture_Consistency_Closure_and_Unified_Change_Ledger_v1.0.md"
)
EXPECTED_OPENAPI_OWNERS = frozenset(
    {"nex-oa", "nex-ae-api", "nex-wc", "nex-eos", "nex-wa"}
)


class CompatibilityError(ValueError):
    """Raised when a pinned Platform compatibility invariant drifts."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class CompatibilityReport:
    baseline_commit: str
    openapi_count: int
    nsl_package_version: str


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CompatibilityError("LOCK_UNREADABLE", str(path)) from error
    if not isinstance(value, dict):
        raise CompatibilityError("LOCK_INVALID", f"object required: {path}")
    return value


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _repository_file(root: Path, raw: str) -> Path:
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise CompatibilityError("PATH_INVALID", raw)
    path = root / relative
    if not path.is_file():
        raise CompatibilityError("FILE_MISSING", raw)
    return path


def _require_hash(root: Path, raw_path: str, expected: str) -> Path:
    path = _repository_file(root, raw_path)
    actual = _sha256(path)
    if actual != expected:
        raise CompatibilityError("HASH_MISMATCH", raw_path)
    return path


def _require_ancestor(root: Path, commit: str) -> None:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise CompatibilityError("BASELINE_NOT_ANCESTOR", commit)


def validate_platform_lock(root: Path, lock_path: Path) -> CompatibilityReport:
    root = root.resolve()
    lock = _load_json(lock_path)
    if lock.get("schema_version") != "nex.mybee.platform-lock.v1":
        raise CompatibilityError("SCHEMA_UNSUPPORTED", str(lock.get("schema_version")))
    if lock.get("status") != "PINNED_FOR_PHASE1_ENTRY":
        raise CompatibilityError("STATUS_INVALID", str(lock.get("status")))

    platform = lock["platform"]
    baseline_commit = str(platform["master_baseline_commit"])
    _require_ancestor(root, baseline_commit)
    _require_hash(
        root,
        FROZEN_AUTHORITY_PATH.as_posix(),
        str(platform["frozen_authority_sha256"]),
    )

    openapi = lock["openapi"]
    if set(openapi) != EXPECTED_OPENAPI_OWNERS:
        raise CompatibilityError("OPENAPI_OWNER_SET_INVALID", ",".join(sorted(openapi)))
    for service_id, item in openapi.items():
        raw_path = str(item["path"])
        if raw_path != f"contracts/openapi/{service_id}.openapi.yaml":
            raise CompatibilityError("OPENAPI_PATH_INVALID", raw_path)
        _require_hash(root, raw_path, str(item["sha256"]))

    nsl = lock["nsl_runtime"]
    nsl_lock_path = _require_hash(
        root, str(nsl["lock_path"]), str(nsl["lock_sha256"])
    )
    admitted_nsl = _load_json(nsl_lock_path)
    for field in ("distribution", "package_version", "source_revision", "wheel_sha256"):
        if nsl.get(field) != admitted_nsl.get(field):
            raise CompatibilityError("NSL_IDENTITY_MISMATCH", field)

    return CompatibilityReport(
        baseline_commit=baseline_commit,
        openapi_count=len(openapi),
        nsl_package_version=str(nsl["package_version"]),
    )
