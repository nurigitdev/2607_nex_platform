from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from nex_runtime.postgres_backup import (
    PostgresBackupError,
    backup_result_public_projection,
    build_logical_backup_plan,
    execute_logical_backup,
)
from nex_runtime.postgres_resilience import load_postgres_resilience_policy


POLICY = load_postgres_resilience_policy(Path("deployment/postgres/s145-policy.yaml"))
TARGET = POLICY.targets[0]
BACKUP_ID = "20261008T010203Z-1234abcd"


def _plan(tmp_path: Path, **overrides):
    values = {
        "policy": POLICY,
        "target": TARGET,
        "backup_id": BACKUP_ID,
        "backup_root": tmp_path / "backups",
        "pg_dump_bin": Path("/usr/bin/pg_dump"),
        "service_file": tmp_path / "pg_service.conf",
        "passfile": tmp_path / ".pgpass",
        "parent_environ": {"PATH": "/usr/bin", "PGPASSWORD": "secret", "NEX_OA_DATABASE_URL": "secret"},
    }
    values.update(overrides)
    return build_logical_backup_plan(**values)


def test_plan_and_execution_publish_atomic_archive_and_manifest(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        kwargs["stdout"].write(b"PGDMP-test-archive")
        return SimpleNamespace(returncode=0)

    values = iter((datetime(2026, 10, 8, 1, 2, 3, tzinfo=timezone.utc), datetime(2026, 10, 8, 1, 2, 4, tzinfo=timezone.utc)))
    result = execute_logical_backup(plan, runner=runner, clock=lambda: next(values))

    assert plan.archive_path.read_bytes() == b"PGDMP-test-archive"
    assert not plan.partial_path.exists()
    assert json.loads(plan.manifest_path.read_text(encoding="utf-8")) == result.__dict__
    assert result.archive_sha256 == hashlib.sha256(b"PGDMP-test-archive").hexdigest()
    assert result.started_at == "2026-10-08T01:02:03Z"
    assert result.completed_at == "2026-10-08T01:02:04Z"
    assert oct(plan.archive_path.stat().st_mode & 0o777) == "0o600"
    command, kwargs = calls[0]
    assert "--dbname=service=nex-oa-backup" in command
    assert not any("secret" in value for value in command)
    assert kwargs["env"] == {
        "PATH": "/usr/bin", "PGSERVICEFILE": str(tmp_path / "pg_service.conf"),
        "PGPASSFILE": str(tmp_path / ".pgpass"), "PGCONNECT_TIMEOUT": "10",
    }
    projection = backup_result_public_projection(result)
    assert "archive_name" not in projection
    assert projection["state"] == "CREATED"


@pytest.mark.parametrize("returncode,payload,code", [(2, b"partial", "pg_dump_failed"), (0, b"", "pg_dump_archive_empty")])
def test_execution_removes_partial_file_on_failure(tmp_path: Path, returncode: int, payload: bytes, code: str) -> None:
    plan = _plan(tmp_path)

    def runner(_command, **kwargs):
        kwargs["stdout"].write(payload)
        return SimpleNamespace(returncode=returncode)

    with pytest.raises(PostgresBackupError, match=code):
        execute_logical_backup(plan, runner=runner)
    assert not plan.partial_path.exists()
    assert not plan.archive_path.exists()
    assert not plan.manifest_path.exists()


def test_execution_rejects_duplicate_or_symlink_destination(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    plan.service_directory.mkdir(parents=True)
    plan.archive_path.write_bytes(b"existing")
    with pytest.raises(PostgresBackupError, match="backup_id_already_exists"):
        execute_logical_backup(plan)

    symlink_root = tmp_path / "link-root"
    target = tmp_path / "real"
    target.mkdir()
    symlink_root.symlink_to(target, target_is_directory=True)
    linked_plan = _plan(tmp_path, backup_root=symlink_root)
    with pytest.raises(PostgresBackupError, match="backup_service_directory_symlink"):
        execute_logical_backup(linked_plan)

    direct_root = tmp_path / "direct-root"
    direct_target = tmp_path / "direct-real"
    direct_root.mkdir()
    direct_target.mkdir()
    (direct_root / TARGET.service_id).symlink_to(direct_target, target_is_directory=True)
    direct_plan = _plan(tmp_path, backup_root=direct_root)
    with pytest.raises(PostgresBackupError, match="backup_service_directory_symlink"):
        execute_logical_backup(direct_plan)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"backup_id": "bad"}, "backup_id_invalid"),
        ({"pg_dump_bin": Path("pg_dump")}, "pg_dump_path_not_absolute"),
        ({"service_file": Path("relative")}, "credential_file_path_not_absolute"),
        ({"passfile": Path("relative")}, "credential_file_path_not_absolute"),
        ({"production": True}, "production_backup_mount_not_verified"),
        ({"production": True, "separate_mount_verified": True, "backup_root": Path("relative")}, "production_backup_mount_not_verified"),
    ],
)
def test_plan_rejects_unsafe_configuration(tmp_path: Path, overrides: dict, code: str) -> None:
    with pytest.raises(PostgresBackupError, match=code):
        _plan(tmp_path, **overrides)


def test_plan_rejects_unknown_or_invalid_libpq_target(tmp_path: Path) -> None:
    unknown = POLICY.targets[1]
    altered = unknown.__class__(unknown.service_id, unknown.database_env, "service=bad", unknown.required_extensions)
    with pytest.raises(PostgresBackupError, match="backup_target_not_in_policy"):
        _plan(tmp_path, target=altered)

    invalid = replace(TARGET, libpq_service="service=bad")
    invalid_policy = replace(POLICY, targets=(invalid, *POLICY.targets[1:]))
    with pytest.raises(PostgresBackupError, match="libpq_service_invalid"):
        _plan(tmp_path, policy=invalid_policy, target=invalid)


def test_manifest_partial_and_naive_clock_fail_closed(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    def runner(_command, **kwargs):
        kwargs["stdout"].write(b"archive")
        return SimpleNamespace(returncode=0)

    plan.service_directory.mkdir(parents=True)
    manifest_partial = plan.manifest_path.with_name(f".{plan.manifest_path.name}.partial")
    manifest_partial.write_text("stale", encoding="utf-8")
    with pytest.raises(PostgresBackupError, match="manifest_partial_exists"):
        execute_logical_backup(plan, runner=runner)
    assert plan.archive_path.exists()
    assert manifest_partial.exists()

    another = _plan(tmp_path, backup_id="20261008T010204Z-1234abcd")
    with pytest.raises(PostgresBackupError, match="clock_timestamp_not_timezone_aware"):
        execute_logical_backup(another, runner=runner, clock=lambda: datetime(2026, 1, 1))


def test_manifest_write_failure_removes_manifest_partial(tmp_path: Path, monkeypatch) -> None:
    plan = _plan(tmp_path)

    def runner(_command, **kwargs):
        kwargs["stdout"].write(b"archive")
        return SimpleNamespace(returncode=0)

    def fail_dump(*_args, **_kwargs):
        raise OSError("simulated")

    monkeypatch.setattr("nex_runtime.postgres_backup.json.dump", fail_dump)
    with pytest.raises(OSError, match="simulated"):
        execute_logical_backup(plan, runner=runner)
    assert plan.archive_path.exists()
    assert not plan.manifest_path.exists()
    assert not plan.manifest_path.with_name(f".{plan.manifest_path.name}.partial").exists()
