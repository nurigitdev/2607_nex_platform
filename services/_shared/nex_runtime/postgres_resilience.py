from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


POLICY_SCHEMA_VERSION = "postgres_resilience_policy.v1"
EXPECTED_SERVICE_IDS = (
    "nex-oa",
    "nex-ag",
    "nex-ae-api",
    "nex-cx",
    "nex-mo",
)


class PostgresResiliencePolicyError(ValueError):
    pass


@dataclass(frozen=True)
class PostgresBackupTarget:
    service_id: str
    database_env: str
    libpq_service: str
    required_extensions: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PostgresResiliencePolicy:
    topology_mode: str
    high_availability: bool
    automatic_failover: bool
    operator_cutover_required: bool
    targets: tuple[PostgresBackupTarget, ...]
    backup_format: str
    compression: str
    interval_hours: int
    service_restore_rto_minutes: int
    retention_restore_points: int
    retention_days: int
    minimum_verified_points: int
    cluster_recovery_method: str
    cluster_libpq_service: str
    wal_archive_root_env: str
    archive_timeout_seconds: int
    cluster_rto_minutes: int
    retained_base_generations: int
    production_storage_class: str
    rehearsal_storage_class: str
    forbid_postgres_data_volume: bool
    atomic_publish_required: bool
    credential_transport: str
    password_in_process_args: bool
    distinct_backup_role_required: bool
    postgres_major: int
    pg_dump_major: int
    pg_restore_major: int


def load_postgres_resilience_policy(path: Path) -> PostgresResiliencePolicy:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PostgresResiliencePolicyError("policy_unreadable") from exc
    if not isinstance(document, Mapping):
        raise PostgresResiliencePolicyError("policy_document_invalid")
    return validate_postgres_resilience_policy(document)


def validate_postgres_resilience_policy(
    document: Mapping[str, Any],
) -> PostgresResiliencePolicy:
    if document.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise PostgresResiliencePolicyError("policy_schema_version_invalid")
    topology = _mapping(document, "topology")
    logical = _mapping(document, "logical_backup")
    cluster = _mapping(document, "cluster_recovery")
    storage = _mapping(document, "storage")
    credentials = _mapping(document, "credentials")
    compatibility = _mapping(document, "compatibility")
    targets = _targets(document.get("services"))

    policy = PostgresResiliencePolicy(
        topology_mode=_text(topology, "mode"),
        high_availability=_boolean(topology, "high_availability"),
        automatic_failover=_boolean(topology, "automatic_failover"),
        operator_cutover_required=_boolean(topology, "operator_cutover_required"),
        targets=targets,
        backup_format=_text(logical, "format"),
        compression=_text(logical, "compression"),
        interval_hours=_integer(logical, "interval_hours"),
        service_restore_rto_minutes=_integer(logical, "service_restore_rto_minutes"),
        retention_restore_points=_integer(logical, "retention_restore_points"),
        retention_days=_integer(logical, "retention_days"),
        minimum_verified_points=_integer(logical, "minimum_verified_points"),
        cluster_recovery_method=_text(cluster, "method"),
        cluster_libpq_service=_text(cluster, "libpq_service"),
        wal_archive_root_env=_text(cluster, "wal_archive_root_env"),
        archive_timeout_seconds=_integer(cluster, "archive_timeout_seconds"),
        cluster_rto_minutes=_integer(cluster, "cluster_rto_minutes"),
        retained_base_generations=_integer(cluster, "retained_base_generations"),
        production_storage_class=_text(storage, "production_class"),
        rehearsal_storage_class=_text(storage, "rehearsal_class"),
        forbid_postgres_data_volume=_boolean(storage, "forbid_postgres_data_volume"),
        atomic_publish_required=_boolean(storage, "atomic_publish_required"),
        credential_transport=_text(credentials, "transport"),
        password_in_process_args=_boolean(credentials, "password_in_process_args"),
        distinct_backup_role_required=_boolean(credentials, "distinct_backup_role_required"),
        postgres_major=_integer(compatibility, "postgres_major"),
        pg_dump_major=_integer(compatibility, "pg_dump_major"),
        pg_restore_major=_integer(compatibility, "pg_restore_major"),
    )
    _validate_invariants(policy)
    return policy


def policy_public_projection(policy: PostgresResiliencePolicy) -> dict[str, Any]:
    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "topology_mode": policy.topology_mode,
        "high_availability": policy.high_availability,
        "automatic_failover": policy.automatic_failover,
        "operator_cutover_required": policy.operator_cutover_required,
        "database_count": len(policy.targets),
        "service_ids": [target.service_id for target in policy.targets],
        "backup_format": policy.backup_format,
        "compression": policy.compression,
        "interval_hours": policy.interval_hours,
        "service_restore_rto_minutes": policy.service_restore_rto_minutes,
        "retention_restore_points": policy.retention_restore_points,
        "retention_days": policy.retention_days,
        "minimum_verified_points": policy.minimum_verified_points,
        "cluster_recovery_method": policy.cluster_recovery_method,
        "cluster_libpq_service": policy.cluster_libpq_service,
        "wal_archive_root_env": policy.wal_archive_root_env,
        "archive_timeout_seconds": policy.archive_timeout_seconds,
        "cluster_rto_minutes": policy.cluster_rto_minutes,
        "retained_base_generations": policy.retained_base_generations,
        "production_storage_class": policy.production_storage_class,
        "credential_transport": policy.credential_transport,
        "postgres_major": policy.postgres_major,
        "extension_target_count": sum(bool(target.required_extensions) for target in policy.targets),
    }


def _targets(value: Any) -> tuple[PostgresBackupTarget, ...]:
    if not isinstance(value, list):
        raise PostgresResiliencePolicyError("services_invalid")
    targets = []
    for item in value:
        if not isinstance(item, Mapping):
            raise PostgresResiliencePolicyError("service_target_invalid")
        extensions = item.get("required_extensions")
        if not isinstance(extensions, Mapping):
            raise PostgresResiliencePolicyError("required_extensions_invalid")
        targets.append(
            PostgresBackupTarget(
                service_id=_text(item, "service_id"),
                database_env=_text(item, "database_env"),
                libpq_service=_text(item, "libpq_service"),
                required_extensions=tuple(
                    sorted((str(name), str(version)) for name, version in extensions.items())
                ),
            )
        )
    return tuple(targets)


def _validate_invariants(policy: PostgresResiliencePolicy) -> None:
    service_ids = tuple(target.service_id for target in policy.targets)
    if service_ids != EXPECTED_SERVICE_IDS or len(set(service_ids)) != len(service_ids):
        raise PostgresResiliencePolicyError("service_ownership_incomplete")
    if policy.topology_mode != "single_host_cold_recovery":
        raise PostgresResiliencePolicyError("topology_mode_invalid")
    if policy.high_availability or policy.automatic_failover:
        raise PostgresResiliencePolicyError("high_availability_not_admitted")
    if not policy.operator_cutover_required:
        raise PostgresResiliencePolicyError("operator_cutover_required")
    if policy.backup_format != "custom" or not policy.compression.startswith("gzip:"):
        raise PostgresResiliencePolicyError("logical_backup_format_invalid")
    if policy.interval_hours > 6 or policy.service_restore_rto_minutes > 30:
        raise PostgresResiliencePolicyError("service_recovery_objective_too_weak")
    if policy.retention_restore_points < 28 or policy.retention_days < 7:
        raise PostgresResiliencePolicyError("logical_retention_too_short")
    if policy.cluster_recovery_method != "basebackup_wal_pitr":
        raise PostgresResiliencePolicyError("cluster_recovery_method_invalid")
    if policy.cluster_libpq_service != "nex-platform-cluster-backup":
        raise PostgresResiliencePolicyError("cluster_libpq_service_invalid")
    if policy.wal_archive_root_env != "NEX_POSTGRES_WAL_ARCHIVE_ROOT":
        raise PostgresResiliencePolicyError("wal_archive_root_env_invalid")
    if policy.archive_timeout_seconds > 300 or policy.cluster_rto_minutes > 60:
        raise PostgresResiliencePolicyError("cluster_recovery_objective_too_weak")
    if policy.retained_base_generations < 2:
        raise PostgresResiliencePolicyError("base_backup_retention_too_short")
    if policy.production_storage_class != "separate_mount":
        raise PostgresResiliencePolicyError("production_storage_not_separate")
    if not policy.forbid_postgres_data_volume or not policy.atomic_publish_required:
        raise PostgresResiliencePolicyError("storage_safety_invalid")
    if policy.credential_transport != "libpq_service_passfile":
        raise PostgresResiliencePolicyError("credential_transport_invalid")
    if policy.password_in_process_args or not policy.distinct_backup_role_required:
        raise PostgresResiliencePolicyError("credential_safety_invalid")
    if {policy.postgres_major, policy.pg_dump_major, policy.pg_restore_major} != {16}:
        raise PostgresResiliencePolicyError("postgres_major_mismatch")
    envs = [target.database_env for target in policy.targets]
    services = [target.libpq_service for target in policy.targets]
    if len(set(envs)) != 5 or len(set(services)) != 5:
        raise PostgresResiliencePolicyError("backup_target_binding_duplicate")


def _mapping(document: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise PostgresResiliencePolicyError(f"{key}_invalid")
    return value


def _text(document: Mapping[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PostgresResiliencePolicyError(f"{key}_invalid")
    return value.strip()


def _integer(document: Mapping[str, Any], key: str) -> int:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PostgresResiliencePolicyError(f"{key}_invalid")
    return value


def _boolean(document: Mapping[str, Any], key: str) -> bool:
    value = document.get(key)
    if not isinstance(value, bool):
        raise PostgresResiliencePolicyError(f"{key}_invalid")
    return value
