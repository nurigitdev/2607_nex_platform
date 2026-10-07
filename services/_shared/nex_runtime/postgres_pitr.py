from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .postgres_backup import build_libpq_file_environment
from .postgres_resilience import PostgresResiliencePolicy


PITR_PLAN_SCHEMA_VERSION = "postgres_pitr_plan.v1"


class PostgresPitrError(ValueError):
    pass


@dataclass(frozen=True)
class PostgresPitrPlan:
    schema_version: str
    recovery_id: str
    basebackup_command: tuple[str, ...]
    environment: dict[str, str]
    basebackup_directory: Path
    archive_settings: tuple[tuple[str, str], ...]
    recovery_settings: tuple[tuple[str, str], ...]
    recovery_target_time: str
    operator_cutover_required: bool
    automatic_promotion: bool


def build_postgres_pitr_plan(
    *,
    policy: PostgresResiliencePolicy,
    recovery_id: str,
    backup_root: Path,
    pg_basebackup_bin: Path,
    service_file: Path,
    passfile: Path,
    recovery_target_time: datetime,
    parent_environ: Mapping[str, str] | None = None,
    production: bool = False,
    separate_mount_verified: bool = False,
) -> PostgresPitrPlan:
    if not recovery_id.startswith("pitr-") or not recovery_id[5:].replace("-", "").isalnum():
        raise PostgresPitrError("recovery_id_invalid")
    if not pg_basebackup_bin.is_absolute():
        raise PostgresPitrError("pg_basebackup_path_not_absolute")
    if not service_file.is_absolute() or not passfile.is_absolute():
        raise PostgresPitrError("credential_file_path_not_absolute")
    if production and (not backup_root.is_absolute() or not separate_mount_verified):
        raise PostgresPitrError("production_backup_mount_not_verified")
    target = _timestamp(recovery_target_time)
    basebackup_directory = backup_root / "base" / recovery_id
    environment = build_libpq_file_environment(
        parent_environ or {}, service_file=service_file, passfile=passfile
    )
    command = (
        str(pg_basebackup_bin),
        f"--dbname=service={policy.cluster_libpq_service}",
        f"--pgdata={basebackup_directory}",
        "--format=plain",
        "--wal-method=stream",
        "--checkpoint=fast",
        "--manifest-checksums=SHA256",
        "--progress",
        "--verbose",
    )
    archive_settings = (
        ("archive_mode", "on"),
        ("archive_timeout", f"{policy.archive_timeout_seconds}s"),
        ("archive_command", "python scripts/db/archive_postgres_wal.py %p %f"),
    )
    recovery_settings = (
        ("restore_command", "python scripts/db/restore_postgres_wal.py %f %p"),
        ("recovery_target_time", target),
        ("recovery_target_timeline", "latest"),
        ("recovery_target_action", "pause"),
    )
    return PostgresPitrPlan(
        schema_version=PITR_PLAN_SCHEMA_VERSION,
        recovery_id=recovery_id,
        basebackup_command=command,
        environment=environment,
        basebackup_directory=basebackup_directory,
        archive_settings=archive_settings,
        recovery_settings=recovery_settings,
        recovery_target_time=target,
        operator_cutover_required=True,
        automatic_promotion=False,
    )


def pitr_plan_public_projection(plan: PostgresPitrPlan) -> dict[str, Any]:
    return {
        "schema_version": plan.schema_version,
        "recovery_id": plan.recovery_id,
        "recovery_target_time": plan.recovery_target_time,
        "basebackup_format": "plain",
        "wal_method": "stream",
        "manifest_checksum": "SHA256",
        "archive_mode": dict(plan.archive_settings)["archive_mode"],
        "archive_timeout": dict(plan.archive_settings)["archive_timeout"],
        "recovery_target_timeline": dict(plan.recovery_settings)["recovery_target_timeline"],
        "recovery_target_action": dict(plan.recovery_settings)["recovery_target_action"],
        "operator_cutover_required": plan.operator_cutover_required,
        "automatic_promotion": plan.automatic_promotion,
    }


def validate_pitr_cutover(
    *,
    recovery_paused: bool,
    timeline_verified: bool,
    five_databases_verified: bool,
    migration_heads_verified: bool,
    operator_approved: bool,
) -> str:
    if not all(
        (
            recovery_paused,
            timeline_verified,
            five_databases_verified,
            migration_heads_verified,
        )
    ):
        raise PostgresPitrError("pitr_recovery_validation_failed")
    return "CUTOVER_APPROVED" if operator_approved else "PAUSED_AWAITING_OPERATOR"


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PostgresPitrError("recovery_target_not_timezone_aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
