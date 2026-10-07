from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nex_runtime.postgres_backup import build_logical_backup_plan, execute_logical_backup
from nex_runtime.postgres_resilience import load_postgres_resilience_policy
from nex_runtime.postgres_restore import (
    PostgresRestoreError,
    build_isolated_restore_plan,
    execute_isolated_restore,
    restore_result_public_projection,
    validate_logical_archive,
)


POLICY = load_postgres_resilience_policy(Path("deployment/postgres/s145-policy.yaml"))
TARGET = POLICY.targets[0]
BACKUP_ID = "20261008T020304Z-1234abcd"
PROBES = {key: True for key in ("database_identity", "migration_head_current", "select_one", "required_extensions")}


def _backup(tmp_path: Path):
    plan = build_logical_backup_plan(
        policy=POLICY, target=TARGET, backup_id=BACKUP_ID,
        backup_root=tmp_path / "backup", pg_dump_bin=Path("/usr/bin/pg_dump"),
        service_file=tmp_path / "pg_service.conf", passfile=tmp_path / ".pgpass",
    )

    def runner(_command, **kwargs):
        kwargs["stdout"].write(b"PGDMP-restorable")
        return SimpleNamespace(returncode=0)

    execute_logical_backup(plan, runner=runner)
    return plan


def _restore(tmp_path: Path, backup=None, **overrides):
    backup = backup or _backup(tmp_path)
    values = {
        "policy": POLICY, "target": TARGET, "backup_id": BACKUP_ID,
        "archive_path": backup.archive_path, "manifest_path": backup.manifest_path,
        "pg_restore_bin": Path("/usr/bin/pg_restore"),
        "recovery_service": "nex-oa-backup-recovery", "target_class": "isolated_recovery",
        "service_file": tmp_path / "pg_service.conf", "passfile": tmp_path / ".pgpass",
        "parent_environ": {"PATH": "/usr/bin", "PGPASSWORD": "forbidden"},
    }
    values.update(overrides)
    return build_isolated_restore_plan(**values)


def _success(_command, **_kwargs):
    return SimpleNamespace(returncode=0, stdout="archive-list\n", stderr="")


def test_isolated_restore_validates_archive_commands_and_probes(tmp_path: Path) -> None:
    plan = _restore(tmp_path)
    result = execute_isolated_restore(
        plan, inspect_runner=_success, restore_runner=_success, probe=lambda _plan: PROBES,
        clock=lambda: datetime(2026, 10, 8, 2, 3, 5, tzinfo=timezone.utc),
    )
    assert result.state == "RESTORED"
    assert result.probe_count == 4
    assert result.completed_at == "2026-10-08T02:03:05Z"
    assert "--dbname=service=nex-oa-backup-recovery" in plan.restore_command
    assert "--single-transaction" in plan.restore_command
    assert "--clean" not in plan.restore_command
    projection = restore_result_public_projection(result)
    assert "recovery_service" not in projection
    assert "path" not in str(projection).lower()


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"target": replace(TARGET, service_id="unknown")}, "restore_target_not_in_policy"),
        ({"target_class": "active"}, "restore_target_class_not_isolated"),
        ({"recovery_service": "nex-oa-backup"}, "recovery_service_not_allowlisted"),
        ({"pg_restore_bin": Path("pg_restore")}, "pg_restore_path_not_absolute"),
        ({"archive_path": Path("relative")}, "archive_path_not_absolute"),
        ({"service_file": Path("relative")}, "credential_file_path_not_absolute"),
    ],
)
def test_restore_plan_rejects_unsafe_targets(tmp_path: Path, overrides: dict, code: str) -> None:
    backup = _backup(tmp_path)
    with pytest.raises(PostgresRestoreError, match=code):
        _restore(tmp_path, backup, **overrides)


@pytest.mark.parametrize("inspect_code,inspect_output,restore_code,code", [(1, "", 0, "archive_inspection_failed"), (0, "", 0, "archive_inspection_failed"), (0, "list", 1, "pg_restore_failed")])
def test_restore_command_failures_are_redacted(tmp_path: Path, inspect_code: int, inspect_output: str, restore_code: int, code: str) -> None:
    plan = _restore(tmp_path)
    inspect = lambda *_args, **_kwargs: SimpleNamespace(returncode=inspect_code, stdout=inspect_output, stderr="secret")
    restore = lambda *_args, **_kwargs: SimpleNamespace(returncode=restore_code, stdout="", stderr="secret")
    with pytest.raises(PostgresRestoreError, match=code) as caught:
        execute_isolated_restore(plan, inspect_runner=inspect, restore_runner=restore, probe=lambda _plan: PROBES)
    assert "secret" not in str(caught.value)


def test_restore_rejects_incomplete_or_failed_probes(tmp_path: Path) -> None:
    plan = _restore(tmp_path)
    for probes in ({"database_identity": True}, {**PROBES, "select_one": False}):
        with pytest.raises(PostgresRestoreError, match="restore_probe_failed"):
            execute_isolated_restore(plan, inspect_runner=_success, restore_runner=_success, probe=lambda _plan, p=probes: p)


def test_archive_validation_rejects_tampering_and_symlinks(tmp_path: Path) -> None:
    backup = _backup(tmp_path)
    plan = _restore(tmp_path, backup)
    backup.archive_path.write_bytes(b"tampered")
    with pytest.raises(PostgresRestoreError, match="backup_archive_size_mismatch|backup_archive_hash_mismatch"):
        validate_logical_archive(plan)

    other = _backup(tmp_path / "other")
    other.archive_path.unlink()
    other.archive_path.symlink_to(backup.archive_path)
    with pytest.raises(PostgresRestoreError, match="restore_input_symlink"):
        validate_logical_archive(_restore(tmp_path / "other", other))

    manifest_link = _backup(tmp_path / "manifest-link")
    original_manifest = manifest_link.manifest_path.with_suffix(".original")
    manifest_link.manifest_path.replace(original_manifest)
    manifest_link.manifest_path.symlink_to(original_manifest)
    with pytest.raises(PostgresRestoreError, match="restore_input_symlink"):
        validate_logical_archive(_restore(tmp_path / "manifest-link", manifest_link))


def test_archive_validation_rejects_bad_manifest_and_clock(tmp_path: Path) -> None:
    backup = _backup(tmp_path)
    plan = _restore(tmp_path, backup)
    backup.manifest_path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(PostgresRestoreError, match="backup_manifest_invalid"):
        validate_logical_archive(plan)

    backup = _backup(tmp_path / "fresh")
    plan = _restore(tmp_path / "fresh", backup)
    with pytest.raises(PostgresRestoreError, match="clock_timestamp_not_timezone_aware"):
        execute_isolated_restore(plan, inspect_runner=_success, restore_runner=_success, probe=lambda _plan: PROBES, clock=lambda: datetime(2026, 1, 1))


def test_archive_validation_rejects_unreadable_shape_binding_and_hash(tmp_path: Path) -> None:
    missing = _backup(tmp_path / "missing")
    missing.manifest_path.unlink()
    with pytest.raises(PostgresRestoreError, match="backup_manifest_unreadable"):
        validate_logical_archive(_restore(tmp_path / "missing", missing))

    shaped = _backup(tmp_path / "shape")
    payload = json.loads(shaped.manifest_path.read_text(encoding="utf-8"))
    payload["extra"] = True
    shaped.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PostgresRestoreError, match="backup_manifest_shape_invalid"):
        validate_logical_archive(_restore(tmp_path / "shape", shaped))

    hashed = _backup(tmp_path / "hash")
    hashed.archive_path.write_bytes(b"X" * hashed.archive_path.stat().st_size)
    with pytest.raises(PostgresRestoreError, match="backup_archive_hash_mismatch"):
        validate_logical_archive(_restore(tmp_path / "hash", hashed))

    absent = _backup(tmp_path / "archive-absent")
    absent.archive_path.unlink()
    with pytest.raises(PostgresRestoreError, match="backup_archive_unreadable"):
        validate_logical_archive(_restore(tmp_path / "archive-absent", absent))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "wrong"),
        ("backup_id", "20261008T020304Z-deadbeef"),
        ("service_id", "nex-ag"),
        ("state", "FAILED"),
        ("archive_name", "other.dump"),
        ("backup_format", "plain"),
    ],
)
def test_archive_validation_rejects_binding_drift(tmp_path: Path, field: str, value: str) -> None:
    backup = _backup(tmp_path)
    payload = json.loads(backup.manifest_path.read_text(encoding="utf-8"))
    payload[field] = value
    backup.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PostgresRestoreError, match="backup_manifest_binding_invalid"):
        validate_logical_archive(_restore(tmp_path, backup))


def test_archive_validation_redacts_open_failure_after_stat(tmp_path: Path) -> None:
    backup = _backup(tmp_path)
    payload = json.loads(backup.manifest_path.read_text(encoding="utf-8"))
    backup.archive_path.unlink()
    backup.archive_path.mkdir()
    payload["archive_bytes"] = backup.archive_path.stat().st_size
    backup.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PostgresRestoreError, match="backup_archive_unreadable"):
        validate_logical_archive(_restore(tmp_path, backup))
