from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from .postgres_resilience import PostgresBackupTarget, PostgresResiliencePolicy


BACKUP_MANIFEST_SCHEMA_VERSION = "postgres_logical_backup_manifest.v1"
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SAFE_BACKUP_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8,32}$")
SAFE_PARENT_ENV_NAMES = (
    "PATH",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "PGSSLMODE",
    "PGSSLROOTCERT",
    "PGSSLCERT",
    "PGSSLKEY",
)


class PostgresBackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class LogicalBackupPlan:
    service_id: str
    backup_id: str
    command: tuple[str, ...]
    environment: dict[str, str]
    service_directory: Path
    partial_path: Path
    archive_path: Path
    manifest_path: Path
    compression: str
    postgres_major: int


@dataclass(frozen=True)
class LogicalBackupResult:
    schema_version: str
    backup_id: str
    service_id: str
    state: str
    archive_name: str
    archive_sha256: str
    archive_bytes: int
    backup_format: str
    compression: str
    postgres_major: int
    started_at: str
    completed_at: str


Runner = Callable[..., Any]
Clock = Callable[[], datetime]


def build_logical_backup_plan(
    *,
    policy: PostgresResiliencePolicy,
    target: PostgresBackupTarget,
    backup_id: str,
    backup_root: Path,
    pg_dump_bin: Path,
    service_file: Path,
    passfile: Path,
    parent_environ: Mapping[str, str] | None = None,
    production: bool = False,
    separate_mount_verified: bool = False,
) -> LogicalBackupPlan:
    _validate_target(policy, target)
    if not SAFE_BACKUP_ID.fullmatch(backup_id):
        raise PostgresBackupError("backup_id_invalid")
    if not pg_dump_bin.is_absolute():
        raise PostgresBackupError("pg_dump_path_not_absolute")
    if not service_file.is_absolute() or not passfile.is_absolute():
        raise PostgresBackupError("credential_file_path_not_absolute")
    if production and (not backup_root.is_absolute() or not separate_mount_verified):
        raise PostgresBackupError("production_backup_mount_not_verified")
    if target.libpq_service.startswith("service=") or not SAFE_ID.fullmatch(
        target.libpq_service
    ):
        raise PostgresBackupError("libpq_service_invalid")

    service_directory = backup_root / target.service_id
    archive_name = f"{backup_id}.dump"
    environment = _safe_subprocess_environment(
        parent_environ or os.environ,
        service_file=service_file,
        passfile=passfile,
    )
    command = (
        str(pg_dump_bin),
        f"--dbname=service={target.libpq_service}",
        "--format=custom",
        f"--compress={policy.compression}",
        "--no-owner",
        "--no-privileges",
        "--serializable-deferrable",
        "--lock-wait-timeout=30000",
    )
    return LogicalBackupPlan(
        service_id=target.service_id,
        backup_id=backup_id,
        command=command,
        environment=environment,
        service_directory=service_directory,
        partial_path=service_directory / f".{archive_name}.partial",
        archive_path=service_directory / archive_name,
        manifest_path=service_directory / f"{backup_id}.manifest.json",
        compression=policy.compression,
        postgres_major=policy.postgres_major,
    )


def execute_logical_backup(
    plan: LogicalBackupPlan,
    *,
    runner: Runner = subprocess.run,
    clock: Clock | None = None,
) -> LogicalBackupResult:
    now = clock or (lambda: datetime.now(timezone.utc))
    started_at = _timestamp(now())
    _prepare_destination(plan)
    try:
        with plan.partial_path.open("xb") as output:
            os.chmod(plan.partial_path, 0o600)
            completed = runner(
                plan.command,
                env=dict(plan.environment),
                stdout=output,
                stderr=subprocess.PIPE,
                check=False,
            )
            output.flush()
            os.fsync(output.fileno())
        if int(completed.returncode) != 0:
            raise PostgresBackupError("pg_dump_failed")
        archive_bytes = plan.partial_path.stat().st_size
        if archive_bytes <= 0:
            raise PostgresBackupError("pg_dump_archive_empty")
        digest = _sha256_file(plan.partial_path)
        os.replace(plan.partial_path, plan.archive_path)
        result = LogicalBackupResult(
            schema_version=BACKUP_MANIFEST_SCHEMA_VERSION,
            backup_id=plan.backup_id,
            service_id=plan.service_id,
            state="CREATED",
            archive_name=plan.archive_path.name,
            archive_sha256=digest,
            archive_bytes=archive_bytes,
            backup_format="custom",
            compression=plan.compression,
            postgres_major=plan.postgres_major,
            started_at=started_at,
            completed_at=_timestamp(now()),
        )
        _write_manifest_atomic(plan.manifest_path, asdict(result))
        return result
    except BaseException:
        plan.partial_path.unlink(missing_ok=True)
        raise


def backup_result_public_projection(result: LogicalBackupResult) -> dict[str, Any]:
    return {
        "schema_version": result.schema_version,
        "backup_id": result.backup_id,
        "service_id": result.service_id,
        "state": result.state,
        "archive_sha256": result.archive_sha256,
        "archive_bytes": result.archive_bytes,
        "backup_format": result.backup_format,
        "compression": result.compression,
        "postgres_major": result.postgres_major,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
    }


def _validate_target(
    policy: PostgresResiliencePolicy, target: PostgresBackupTarget
) -> None:
    matches = [item for item in policy.targets if item.service_id == target.service_id]
    if len(matches) != 1 or matches[0] != target:
        raise PostgresBackupError("backup_target_not_in_policy")


def _safe_subprocess_environment(
    parent: Mapping[str, str], *, service_file: Path, passfile: Path
) -> dict[str, str]:
    environment = {
        name: value
        for name in SAFE_PARENT_ENV_NAMES
        if (value := parent.get(name))
    }
    environment.update(
        {
            "PGSERVICEFILE": str(service_file),
            "PGPASSFILE": str(passfile),
            "PGCONNECT_TIMEOUT": "10",
        }
    )
    return environment


def _prepare_destination(plan: LogicalBackupPlan) -> None:
    if plan.service_directory.parent.is_symlink():
        raise PostgresBackupError("backup_service_directory_symlink")
    plan.service_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if plan.service_directory.is_symlink():
        raise PostgresBackupError("backup_service_directory_symlink")
    os.chmod(plan.service_directory, 0o700)
    if any(
        path.exists()
        for path in (plan.partial_path, plan.archive_path, plan.manifest_path)
    ):
        raise PostgresBackupError("backup_id_already_exists")


def _write_manifest_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    partial = path.with_name(f".{path.name}.partial")
    if partial.exists():
        raise PostgresBackupError("manifest_partial_exists")
    try:
        with partial.open("x", encoding="utf-8") as output:
            os.chmod(partial, 0o600)
            json.dump(dict(payload), output, ensure_ascii=True, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(partial, path)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PostgresBackupError("clock_timestamp_not_timezone_aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
