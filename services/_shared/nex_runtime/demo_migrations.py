from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .demo_database import (
    DEMO_DATABASE_TARGETS,
    DemoDatabaseGuardError,
    DemoDatabaseInspection,
    ResolvedDemoDatabaseTarget,
    inspect_demo_database_targets,
    validate_demo_backup_set_manifest,
)
from .semantic_hashes import semantic_sha256_hash_ref

DEMO_MIGRATION_SCHEMA_VERSION = "p8_demo_migration_execution.v1"
DEMO_MIGRATION_CONFIRMATION = "MIGRATE_P8_DEMO_DEV_DATABASES"


@dataclass(frozen=True)
class DemoServiceMigrationResult:
    service_id: str
    planned: tuple[str, ...]
    applied: tuple[str, ...]
    skipped: tuple[str, ...]


def execute_demo_migration_closure(
    targets: Sequence[ResolvedDemoDatabaseTarget],
    inspections: Sequence[DemoDatabaseInspection],
    backup_manifest: Mapping[str, Any],
    *,
    confirmation: str,
    database_root: Path,
    migration_runner: Callable[..., Any],
    connect: Callable[..., Any],
    inspector: Callable[..., Sequence[DemoDatabaseInspection]] = (
        inspect_demo_database_targets
    ),
) -> dict[str, Any]:
    records = _admit_migration_execution(
        targets,
        inspections,
        backup_manifest,
        confirmation=confirmation,
    )
    results: list[DemoServiceMigrationResult] = []
    for target in targets:
        result = migration_runner(
            target.target.service_id,
            database_url=target.database_url,
            database_root=database_root,
            profile="dev",
        )
        if bool(getattr(result, "dry_run", False)):
            raise DemoDatabaseGuardError("demo_migration_dry_run_not_admitted")
        results.append(
            DemoServiceMigrationResult(
                service_id=target.target.service_id,
                planned=tuple(getattr(result, "planned", ())),
                applied=tuple(getattr(result, "applied", ())),
                skipped=tuple(getattr(result, "skipped", ())),
            )
        )

    post_inspections = tuple(inspector(
        targets,
        database_root=database_root,
        connect=connect,
    ))
    if any(item.migration_state != "CURRENT" for item in post_inspections):
        raise DemoDatabaseGuardError("demo_migration_post_state_not_current")

    report_without_hash = {
        "schema_version": DEMO_MIGRATION_SCHEMA_VERSION,
        "status": "PASS",
        "profile": "dev",
        "actual_postgres": True,
        "migration_executed": True,
        "backup_id": records["backup_id"],
        "backup_set_hash": records["set_hash"],
        "service_count": len(results),
        "migration_current_count": len(post_inspections),
        "resumed_service_count": sum(
            tuple(item.get("applied_migrations", ())) != inspection.applied_migrations
            for item, inspection in zip(
                records["targets"], inspections, strict=True
            )
        ),
        "services": [
            {
                **asdict(result),
                "expected_migration_count": len(post.expected_migrations),
                "applied_migration_count": len(post.applied_migrations),
                "migration_state": post.migration_state,
                "source_inventory_hash": post.source_inventory_hash,
            }
            for result, post in zip(results, post_inspections, strict=True)
        ],
        "database_urls_exposed": False,
        "confirmation_exposed": False,
    }
    return {
        **report_without_hash,
        "evidence_hash": semantic_sha256_hash_ref(report_without_hash),
    }


def _admit_migration_execution(
    targets: Sequence[ResolvedDemoDatabaseTarget],
    inspections: Sequence[DemoDatabaseInspection],
    backup_manifest: Mapping[str, Any],
    *,
    confirmation: str,
) -> dict[str, Any]:
    if confirmation != DEMO_MIGRATION_CONFIRMATION:
        raise DemoDatabaseGuardError("demo_migration_confirmation_invalid")
    expected = tuple(target.service_id for target in DEMO_DATABASE_TARGETS)
    if tuple(item.target.service_id for item in targets) != expected:
        raise DemoDatabaseGuardError("demo_migration_database_set_incomplete")
    if tuple(item.service_id for item in inspections) != expected:
        raise DemoDatabaseGuardError("demo_migration_inspection_set_incomplete")
    if any(item.identity_state != "ADMITTED" for item in inspections):
        raise DemoDatabaseGuardError("demo_migration_identity_not_admitted")
    if any(item.extra_migrations for item in inspections):
        raise DemoDatabaseGuardError("demo_migration_drift_not_admitted")

    manifest = validate_demo_backup_set_manifest(backup_manifest)
    manifest_targets = {item["service_id"]: item for item in manifest["targets"]}
    for inspection in inspections:
        backed_up = manifest_targets[inspection.service_id]
        if (
            backed_up.get("database_name") != inspection.database_name
            or backed_up.get("role_name") != inspection.role_name
        ):
            raise DemoDatabaseGuardError("demo_migration_backup_identity_mismatch")
        if backed_up.get("source_inventory_hash") != inspection.source_inventory_hash:
            raise DemoDatabaseGuardError("demo_migration_source_inventory_changed")
        backed_up_applied = tuple(backed_up.get("applied_migrations", ()))
        if inspection.applied_migrations[: len(backed_up_applied)] != backed_up_applied:
            raise DemoDatabaseGuardError("demo_migration_database_changed_after_backup")
    return manifest
