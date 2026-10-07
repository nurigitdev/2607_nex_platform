from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any


POSTGRES_OPERATOR_CHECK_SCHEMA_VERSION = "postgres_operator_check.v1"
EXPECTED_TOOLS = ("pg_dump", "pg_restore", "pg_basebackup")
VERSION_PATTERN = re.compile(r"\(PostgreSQL\)\s+([0-9]+)(?:\.[0-9]+)?")


class PostgresOperatorError(RuntimeError):
    pass


@dataclass(frozen=True)
class PostgresOperatorCheck:
    schema_version: str
    state: str
    postgres_major: int
    tool_count: int
    non_root: bool
    separate_mount_attested: bool
    credential_source_count: int


Runner = Callable[..., Any]


def check_postgres_operator_runtime(
    environment: Mapping[str, str],
    *,
    runner: Runner = subprocess.run,
    executable_lookup: Callable[[str], str | None] = shutil.which,
    effective_uid: int | None = None,
) -> PostgresOperatorCheck:
    backup_root = _absolute_directory(environment, "NEX_POSTGRES_BACKUP_ROOT")
    state_root = _absolute_directory(environment, "NEX_POSTGRES_BACKUP_STATE_ROOT")
    wal_root = _absolute_path(environment, "NEX_POSTGRES_WAL_ARCHIVE_ROOT")
    if backup_root == state_root or wal_root.parent != backup_root:
        raise PostgresOperatorError("postgres_operator_storage_boundary_invalid")
    if environment.get("NEX_POSTGRES_SEPARATE_MOUNT_VERIFIED") != "1":
        raise PostgresOperatorError("postgres_operator_separate_mount_unverified")
    credential_sources = tuple(
        _regular_secret_file(environment, name)
        for name in (
            "NEX_POSTGRES_SERVICE_FILE_SOURCE",
            "NEX_POSTGRES_PASSFILE_SOURCE",
        )
    )
    if len(set(credential_sources)) != 2:
        raise PostgresOperatorError("postgres_operator_credential_sources_invalid")
    uid = os.geteuid() if effective_uid is None else effective_uid
    if uid == 0:
        raise PostgresOperatorError("postgres_operator_root_forbidden")

    majors: set[int] = set()
    for tool in EXPECTED_TOOLS:
        executable = executable_lookup(tool)
        if not executable or not Path(executable).is_absolute():
            raise PostgresOperatorError("postgres_operator_tool_missing")
        completed = runner(
            (executable, "--version"),
            check=False,
            capture_output=True,
            text=True,
        )
        if int(completed.returncode) != 0:
            raise PostgresOperatorError("postgres_operator_tool_probe_failed")
        match = VERSION_PATTERN.search(str(completed.stdout))
        if not match:
            raise PostgresOperatorError("postgres_operator_tool_version_invalid")
        majors.add(int(match.group(1)))
    if majors != {16}:
        raise PostgresOperatorError("postgres_operator_major_version_mismatch")
    return PostgresOperatorCheck(
        schema_version=POSTGRES_OPERATOR_CHECK_SCHEMA_VERSION,
        state="READY",
        postgres_major=16,
        tool_count=len(EXPECTED_TOOLS),
        non_root=True,
        separate_mount_attested=True,
        credential_source_count=len(credential_sources),
    )


def postgres_operator_public_projection(check: PostgresOperatorCheck) -> dict[str, Any]:
    return {
        "schema_version": check.schema_version,
        "state": check.state,
        "postgres_major": check.postgres_major,
        "tool_count": check.tool_count,
        "non_root": check.non_root,
        "separate_mount_attested": check.separate_mount_attested,
        "credential_source_count": check.credential_source_count,
    }


def _absolute_directory(environment: Mapping[str, str], name: str) -> Path:
    path = _absolute_path(environment, name)
    if not path.is_dir() or path.is_symlink() or not os.access(path, os.W_OK | os.X_OK):
        raise PostgresOperatorError("postgres_operator_directory_invalid")
    return path


def _absolute_path(environment: Mapping[str, str], name: str) -> Path:
    raw = environment.get(name)
    if not raw:
        raise PostgresOperatorError("postgres_operator_environment_incomplete")
    path = Path(raw)
    if not path.is_absolute():
        raise PostgresOperatorError("postgres_operator_path_not_absolute")
    return path


def _regular_secret_file(environment: Mapping[str, str], name: str) -> Path:
    path = _absolute_path(environment, name)
    if not path.is_file() or path.is_symlink():
        raise PostgresOperatorError("postgres_operator_credential_source_invalid")
    return path
