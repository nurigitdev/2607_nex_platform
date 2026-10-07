from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from .postgres_backup import (
    BACKUP_MANIFEST_SCHEMA_VERSION,
    PostgresBackupError,
    build_libpq_file_environment,
)
from .postgres_resilience import PostgresBackupTarget, PostgresResiliencePolicy


RESTORE_EVIDENCE_SCHEMA_VERSION = "postgres_isolated_restore_evidence.v1"
REQUIRED_PROBE_KEYS = (
    "database_identity",
    "migration_head_current",
    "select_one",
    "required_extensions",
)


class PostgresRestoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class IsolatedRestorePlan:
    service_id: str
    backup_id: str
    archive_path: Path
    manifest_path: Path
    inspect_command: tuple[str, ...]
    restore_command: tuple[str, ...]
    environment: dict[str, str]
    target_class: str
    recovery_service: str


@dataclass(frozen=True)
class IsolatedRestoreResult:
    schema_version: str
    backup_id: str
    service_id: str
    state: str
    target_class: str
    archive_sha256: str
    probe_count: int
    completed_at: str


Runner = Callable[..., Any]
Probe = Callable[[IsolatedRestorePlan], Mapping[str, bool]]
Clock = Callable[[], datetime]


def build_isolated_restore_plan(
    *,
    policy: PostgresResiliencePolicy,
    target: PostgresBackupTarget,
    backup_id: str,
    archive_path: Path,
    manifest_path: Path,
    pg_restore_bin: Path,
    recovery_service: str,
    target_class: str,
    service_file: Path,
    passfile: Path,
    parent_environ: Mapping[str, str] | None = None,
) -> IsolatedRestorePlan:
    if target not in policy.targets:
        raise PostgresRestoreError("restore_target_not_in_policy")
    if target_class != "isolated_recovery":
        raise PostgresRestoreError("restore_target_class_not_isolated")
    expected_service = f"{target.libpq_service}-recovery"
    if recovery_service != expected_service or recovery_service == target.libpq_service:
        raise PostgresRestoreError("recovery_service_not_allowlisted")
    if not pg_restore_bin.is_absolute():
        raise PostgresRestoreError("pg_restore_path_not_absolute")
    if not archive_path.is_absolute() or not manifest_path.is_absolute():
        raise PostgresRestoreError("archive_path_not_absolute")
    if not service_file.is_absolute() or not passfile.is_absolute():
        raise PostgresRestoreError("credential_file_path_not_absolute")
    environment = build_libpq_file_environment(
        parent_environ or {}, service_file=service_file, passfile=passfile
    )
    common = (
        str(pg_restore_bin),
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--exit-on-error",
    )
    return IsolatedRestorePlan(
        service_id=target.service_id,
        backup_id=backup_id,
        archive_path=archive_path,
        manifest_path=manifest_path,
        inspect_command=(str(pg_restore_bin), "--list", str(archive_path)),
        restore_command=(
            *common,
            "--single-transaction",
            f"--dbname=service={recovery_service}",
            str(archive_path),
        ),
        environment=environment,
        target_class=target_class,
        recovery_service=recovery_service,
    )


def execute_isolated_restore(
    plan: IsolatedRestorePlan,
    *,
    inspect_runner: Runner = subprocess.run,
    restore_runner: Runner = subprocess.run,
    probe: Probe,
    clock: Clock | None = None,
) -> IsolatedRestoreResult:
    manifest = validate_logical_archive(plan)
    inspected = inspect_runner(
        plan.inspect_command,
        env=dict(plan.environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if int(inspected.returncode) != 0 or not str(inspected.stdout).strip():
        raise PostgresRestoreError("archive_inspection_failed")
    restored = restore_runner(
        plan.restore_command,
        env=dict(plan.environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if int(restored.returncode) != 0:
        raise PostgresRestoreError("pg_restore_failed")
    probes = dict(probe(plan))
    if tuple(probes) != REQUIRED_PROBE_KEYS or not all(probes.values()):
        raise PostgresRestoreError("restore_probe_failed")
    now = clock or (lambda: datetime.now(timezone.utc))
    return IsolatedRestoreResult(
        schema_version=RESTORE_EVIDENCE_SCHEMA_VERSION,
        backup_id=plan.backup_id,
        service_id=plan.service_id,
        state="RESTORED",
        target_class=plan.target_class,
        archive_sha256=str(manifest["archive_sha256"]),
        probe_count=len(probes),
        completed_at=_timestamp(now()),
    )


def validate_logical_archive(plan: IsolatedRestorePlan) -> dict[str, Any]:
    if plan.archive_path.is_symlink() or plan.manifest_path.is_symlink():
        raise PostgresRestoreError("restore_input_symlink")
    try:
        manifest = json.loads(plan.manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PostgresRestoreError("backup_manifest_unreadable") from exc
    if not isinstance(manifest, Mapping):
        raise PostgresRestoreError("backup_manifest_invalid")
    required = {
        "schema_version", "backup_id", "service_id", "state", "archive_name",
        "archive_sha256", "archive_bytes", "backup_format", "compression",
        "postgres_major", "started_at", "completed_at",
    }
    if set(manifest) != required:
        raise PostgresRestoreError("backup_manifest_shape_invalid")
    if (
        manifest["schema_version"] != BACKUP_MANIFEST_SCHEMA_VERSION
        or manifest["backup_id"] != plan.backup_id
        or manifest["service_id"] != plan.service_id
        or manifest["state"] not in {"CREATED", "VERIFIED"}
        or manifest["archive_name"] != plan.archive_path.name
        or manifest["backup_format"] != "custom"
    ):
        raise PostgresRestoreError("backup_manifest_binding_invalid")
    try:
        archive_bytes = plan.archive_path.stat().st_size
    except OSError as exc:
        raise PostgresRestoreError("backup_archive_unreadable") from exc
    if archive_bytes != manifest["archive_bytes"] or archive_bytes <= 0:
        raise PostgresRestoreError("backup_archive_size_mismatch")
    if _sha256_file(plan.archive_path) != manifest["archive_sha256"]:
        raise PostgresRestoreError("backup_archive_hash_mismatch")
    return dict(manifest)


def restore_result_public_projection(result: IsolatedRestoreResult) -> dict[str, Any]:
    return {
        "schema_version": result.schema_version,
        "backup_id": result.backup_id,
        "service_id": result.service_id,
        "state": result.state,
        "target_class": result.target_class,
        "archive_sha256": result.archive_sha256,
        "probe_count": result.probe_count,
        "completed_at": result.completed_at,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise PostgresRestoreError("backup_archive_unreadable") from exc
    return digest.hexdigest()


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PostgresRestoreError("clock_timestamp_not_timezone_aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

