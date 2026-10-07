from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import nex_runtime.postgres_operator as operator_module
from nex_runtime.postgres_operator import (
    PostgresOperatorError,
    check_postgres_operator_runtime,
    postgres_operator_public_projection,
)


def _environment(tmp_path: Path) -> dict[str, str]:
    backup = tmp_path / "backup"
    state = tmp_path / "state"
    secrets = tmp_path / "secrets"
    for path in (backup, state, secrets):
        path.mkdir(parents=True)
    service = secrets / "pg_service.conf"
    passfile = secrets / "pgpass"
    service.write_text("service", encoding="utf-8")
    passfile.write_text("pass", encoding="utf-8")
    return {
        "NEX_POSTGRES_BACKUP_ROOT": str(backup),
        "NEX_POSTGRES_BACKUP_STATE_ROOT": str(state),
        "NEX_POSTGRES_WAL_ARCHIVE_ROOT": str(backup / "wal"),
        "NEX_POSTGRES_SERVICE_FILE_SOURCE": str(service),
        "NEX_POSTGRES_PASSFILE_SOURCE": str(passfile),
        "NEX_POSTGRES_SEPARATE_MOUNT_VERIFIED": "1",
    }


def _runner(_command, **_kwargs):
    return SimpleNamespace(returncode=0, stdout="pg_dump (PostgreSQL) 16.9")


def _check(tmp_path: Path, **overrides):
    values = {
        "environment": _environment(tmp_path),
        "runner": _runner,
        "executable_lookup": lambda tool: f"/usr/bin/{tool}",
        "effective_uid": 65532,
    }
    values.update(overrides)
    return check_postgres_operator_runtime(**values)


def test_operator_check_accepts_non_root_postgres_16_runtime(tmp_path: Path) -> None:
    checked = _check(tmp_path)
    assert postgres_operator_public_projection(checked) == {
        "schema_version": "postgres_operator_check.v1",
        "state": "READY",
        "postgres_major": 16,
        "tool_count": 3,
        "non_root": True,
        "separate_mount_attested": True,
        "credential_source_count": 2,
    }


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda env: env.pop("NEX_POSTGRES_BACKUP_ROOT"), "environment_incomplete"),
        (lambda env: env.update(NEX_POSTGRES_BACKUP_ROOT="relative"), "path_not_absolute"),
        (lambda env: env.update(NEX_POSTGRES_BACKUP_STATE_ROOT=env["NEX_POSTGRES_BACKUP_ROOT"]), "storage_boundary_invalid"),
        (lambda env: env.update(NEX_POSTGRES_WAL_ARCHIVE_ROOT=str(Path(env["NEX_POSTGRES_BACKUP_STATE_ROOT"]) / "wal")), "storage_boundary_invalid"),
        (lambda env: env.update(NEX_POSTGRES_SEPARATE_MOUNT_VERIFIED="0"), "separate_mount_unverified"),
        (lambda env: env.update(NEX_POSTGRES_PASSFILE_SOURCE=env["NEX_POSTGRES_SERVICE_FILE_SOURCE"]), "credential_sources_invalid"),
    ],
)
def test_operator_check_rejects_environment_drift(tmp_path: Path, mutate, code: str) -> None:
    environment = _environment(tmp_path)
    mutate(environment)
    with pytest.raises(PostgresOperatorError, match=code):
        _check(tmp_path / "run", environment=environment)


def test_operator_check_rejects_directory_and_credential_symlinks(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    linked = tmp_path / "linked"
    linked.symlink_to(Path(environment["NEX_POSTGRES_BACKUP_ROOT"]), target_is_directory=True)
    environment["NEX_POSTGRES_BACKUP_ROOT"] = str(linked)
    environment["NEX_POSTGRES_WAL_ARCHIVE_ROOT"] = str(linked / "wal")
    with pytest.raises(PostgresOperatorError, match="directory_invalid"):
        _check(tmp_path / "run", environment=environment)

    environment = _environment(tmp_path / "credential")
    source = Path(environment["NEX_POSTGRES_SERVICE_FILE_SOURCE"])
    real = source.with_suffix(".real")
    source.replace(real)
    source.symlink_to(real)
    with pytest.raises(PostgresOperatorError, match="credential_source_invalid"):
        _check(tmp_path / "run2", environment=environment)


def test_operator_check_rejects_non_writable_directory(tmp_path: Path, monkeypatch) -> None:
    environment = _environment(tmp_path)
    monkeypatch.setattr(operator_module.os, "access", lambda *_args: False)
    with pytest.raises(PostgresOperatorError, match="directory_invalid"):
        _check(tmp_path / "run", environment=environment)


def test_operator_check_rejects_root_and_tool_drift(tmp_path: Path) -> None:
    with pytest.raises(PostgresOperatorError, match="root_forbidden"):
        _check(tmp_path / "root", effective_uid=0)
    with pytest.raises(PostgresOperatorError, match="tool_missing"):
        _check(tmp_path / "missing", executable_lookup=lambda _tool: None)
    with pytest.raises(PostgresOperatorError, match="tool_missing"):
        _check(tmp_path / "relative", executable_lookup=lambda tool: tool)


@pytest.mark.parametrize(
    ("completed", "code"),
    [
        (SimpleNamespace(returncode=1, stdout=""), "tool_probe_failed"),
        (SimpleNamespace(returncode=0, stdout="unknown"), "tool_version_invalid"),
        (SimpleNamespace(returncode=0, stdout="pg_dump (PostgreSQL) 15.4"), "major_version_mismatch"),
    ],
)
def test_operator_check_rejects_tool_probe_failure(tmp_path: Path, completed, code: str) -> None:
    with pytest.raises(PostgresOperatorError, match=code):
        _check(tmp_path, runner=lambda *_args, **_kwargs: completed)


def test_operator_check_uses_process_uid_when_not_injected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(operator_module.os, "geteuid", lambda: 65532)
    assert _check(tmp_path, effective_uid=None).state == "READY"
