from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from mybee_ax.compatibility import CompatibilityError, validate_platform_lock


ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "domains/mybee/compatibility/platform.lock.json"
CHECKER = ROOT / "domains/mybee/compatibility/check_lock.py"


def _lock() -> dict:
    return json.loads(LOCK.read_text(encoding="utf-8"))


def _write_lock(tmp_path: Path, value: object) -> Path:
    path = tmp_path / "platform.lock.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_mb0_02_exact_platform_lock_is_admitted() -> None:
    report = validate_platform_lock(ROOT, LOCK)

    assert report.openapi_count == 5
    assert report.nsl_package_version == "0.2.1"
    assert report.baseline_commit == "9fe6ddb151bd121c8fb66fbde62cc24cca29eddb"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("schema_version", "unknown", "SCHEMA_UNSUPPORTED"),
        ("status", "DRAFT", "STATUS_INVALID"),
    ),
)
def test_mb0_02_schema_and_status_drift_fail_closed(
    tmp_path: Path, field: str, value: str, code: str
) -> None:
    lock = _lock()
    lock[field] = value

    with pytest.raises(CompatibilityError) as error:
        validate_platform_lock(ROOT, _write_lock(tmp_path, lock))
    assert error.value.code == code


def test_mb0_02_missing_or_invalid_paths_fail_closed(tmp_path: Path) -> None:
    lock = _lock()
    lock["openapi"]["nex-eos"]["path"] = "contracts/openapi/missing.yaml"
    with pytest.raises(CompatibilityError) as invalid:
        validate_platform_lock(ROOT, _write_lock(tmp_path, lock))
    assert invalid.value.code == "OPENAPI_PATH_INVALID"

    lock = _lock()
    lock["nsl_runtime"]["lock_path"] = "deployment/locks/missing.json"
    with pytest.raises(CompatibilityError) as missing:
        validate_platform_lock(ROOT, _write_lock(tmp_path, lock))
    assert missing.value.code == "FILE_MISSING"

    lock = _lock()
    lock["nsl_runtime"]["lock_path"] = "../outside.json"
    with pytest.raises(CompatibilityError) as traversal:
        validate_platform_lock(ROOT, _write_lock(tmp_path, lock))
    assert traversal.value.code == "PATH_INVALID"


def test_mb0_02_hash_and_nsl_identity_drift_fail_closed(tmp_path: Path) -> None:
    lock = _lock()
    lock["openapi"]["nex-eos"]["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(CompatibilityError) as mismatch:
        validate_platform_lock(ROOT, _write_lock(tmp_path, lock))
    assert mismatch.value.code == "HASH_MISMATCH"

    lock = _lock()
    lock["nsl_runtime"]["package_version"] = "0.2.0"
    with pytest.raises(CompatibilityError) as nsl:
        validate_platform_lock(ROOT, _write_lock(tmp_path, lock))
    assert nsl.value.code == "NSL_IDENTITY_MISMATCH"


def test_mb0_02_owner_set_and_git_baseline_drift_fail_closed(tmp_path: Path) -> None:
    lock = _lock()
    lock["openapi"].pop("nex-wa")
    with pytest.raises(CompatibilityError) as owners:
        validate_platform_lock(ROOT, _write_lock(tmp_path, lock))
    assert owners.value.code == "OPENAPI_OWNER_SET_INVALID"

    lock = _lock()
    lock["platform"]["master_baseline_commit"] = "0" * 40
    with pytest.raises(CompatibilityError) as baseline:
        validate_platform_lock(ROOT, _write_lock(tmp_path, lock))
    assert baseline.value.code == "BASELINE_NOT_ANCESTOR"


def test_mb0_02_unreadable_and_non_object_locks_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(CompatibilityError) as missing:
        validate_platform_lock(ROOT, tmp_path / "missing.json")
    assert missing.value.code == "LOCK_UNREADABLE"

    with pytest.raises(CompatibilityError) as invalid:
        validate_platform_lock(ROOT, _write_lock(tmp_path, []))
    assert invalid.value.code == "LOCK_INVALID"


def test_mb0_02_cli_reports_redacted_pass_and_typed_failure(tmp_path: Path) -> None:
    passed = subprocess.run(
        [str(CHECKER), "--root", str(ROOT), "--summary"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert passed.returncode == 0
    assert passed.stdout.startswith("mybee_platform_lock=pass openapi=5 nsl=0.2.1")

    failed = subprocess.run(
        [
            str(CHECKER),
            "--root",
            str(ROOT),
            "--lock",
            str(tmp_path / "missing.json"),
            "--summary",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed.returncode == 2
    assert failed.stdout == "mybee_platform_lock=fail code=LOCK_UNREADABLE\n"
