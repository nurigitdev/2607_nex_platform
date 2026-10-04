from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from nex_runtime.postgres_orchestration import (
    POSTGRES_SERVICE_ORDER,
    PlatformPostgresRestartEvidence,
    build_platform_postgres_restart_evidence,
    build_postgres_phase_evidence,
)
from nex_runtime.postgres_targets import (
    PostgresTargetConfigError,
    ResolvedPostgresTestTarget,
    resolve_postgres_test_targets,
)
from nex_runtime.database import psycopg_database_url
from run_migrations import (
    DATABASE_ROOT,
    MigrationRunResult,
    run_service_migrations,
)


MigrationRunner = Callable[..., MigrationRunResult]
ConnectFactory = Callable[..., Any]


class PlatformMigrationReadinessError(RuntimeError):
    def __init__(self, failure_code: str, service_id: str | None = None) -> None:
        self.failure_code = failure_code
        self.service_id = service_id
        super().__init__(failure_code)


@dataclass(frozen=True)
class ServiceMigrationReadiness:
    service_id: str
    migration_count: int
    applied_count: int
    skipped_count: int
    head_version: str
    database_identity_confirmed: bool
    select_one_ready: bool


@dataclass(frozen=True)
class PlatformMigrationReadinessResult:
    services: tuple[ServiceMigrationReadiness, ...]
    evidence: PlatformPostgresRestartEvidence

    def to_public_projection(self) -> dict[str, Any]:
        return {
            "schema_version": "platform_test_migration_readiness.v1",
            "profile": "test",
            "status": "PASS",
            "startup_allowed": True,
            "service_count": len(self.services),
            "migration_count": sum(item.migration_count for item in self.services),
            "applied_count": sum(item.applied_count for item in self.services),
            "skipped_count": sum(item.skipped_count for item in self.services),
            "services": [
                {
                    "service_id": item.service_id,
                    "migration_count": item.migration_count,
                    "applied_count": item.applied_count,
                    "skipped_count": item.skipped_count,
                    "head_version": item.head_version,
                    "database_identity_confirmed": item.database_identity_confirmed,
                    "select_one_ready": item.select_one_ready,
                }
                for item in self.services
            ],
            "evidence": self.evidence.to_public_projection(),
        }


def run_platform_test_migration_readiness(
    environ: Mapping[str, str],
    *,
    migration_runner: MigrationRunner = run_service_migrations,
    connect: ConnectFactory = psycopg.connect,
    database_root: Path = DATABASE_ROOT,
) -> PlatformMigrationReadinessResult:
    try:
        targets = resolve_postgres_test_targets(
            environ, service_ids=POSTGRES_SERVICE_ORDER
        )
    except PostgresTargetConfigError as exc:
        raise PlatformMigrationReadinessError("configuration_invalid") from exc

    records: list[ServiceMigrationReadiness] = []
    evidence = []
    for target in targets:
        service_id = target.target.service_id
        try:
            migration = migration_runner(
                service_id,
                database_url=target.database_url,
                database_root=database_root,
                dry_run=False,
                profile="test",
            )
            _validate_migration_result(migration, service_id=service_id)
        except Exception as exc:
            raise PlatformMigrationReadinessError(
                "migration_failed", service_id
            ) from exc

        try:
            readiness = _inspect_database(
                target,
                planned=migration.planned,
                connect=connect,
            )
        except PlatformMigrationReadinessError:
            raise
        except Exception as exc:
            raise PlatformMigrationReadinessError(
                "database_readiness_failed", service_id
            ) from exc

        records.append(
            ServiceMigrationReadiness(
                service_id=service_id,
                migration_count=len(migration.planned),
                applied_count=len(migration.applied),
                skipped_count=len(migration.skipped),
                head_version=migration.planned[-1],
                database_identity_confirmed=readiness["identity"],
                select_one_ready=readiness["select_one"],
            )
        )
        evidence.extend(
            (
                build_postgres_phase_evidence(
                    service_id=service_id,
                    phase="MIGRATION",
                    status="PASSED",
                    evidence_codes=("migration_head_current",),
                ),
                build_postgres_phase_evidence(
                    service_id=service_id,
                    phase="POOL_READINESS",
                    status="PASSED",
                    evidence_codes=(
                        "database_identity_confirmed",
                        "select_one_ready",
                    ),
                ),
            )
        )
    return PlatformMigrationReadinessResult(
        services=tuple(records),
        evidence=build_platform_postgres_restart_evidence(
            run_id="s133-migration-readiness",
            state="PASSED",
            records=evidence,
        ),
    )


def _validate_migration_result(
    result: MigrationRunResult,
    *,
    service_id: str,
) -> None:
    if result.service_id != service_id:
        raise ValueError("migration_service_mismatch")
    if result.profile != "test" or result.dry_run:
        raise ValueError("migration_profile_invalid")
    if not result.planned:
        raise ValueError("migration_plan_empty")
    if len(result.applied) + len(result.skipped) != len(result.planned):
        raise ValueError("migration_result_incomplete")


def _inspect_database(
    target: ResolvedPostgresTestTarget,
    *,
    planned: tuple[str, ...],
    connect: ConnectFactory,
) -> dict[str, bool]:
    service_id = target.target.service_id
    with connect(
        psycopg_database_url(target.database_url), autocommit=True
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            identity = cursor.fetchone()
            if identity != (
                target.target.expected_database_name,
                target.target.expected_role_name,
            ):
                raise PlatformMigrationReadinessError(
                    "database_identity_mismatch", service_id
                )
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                raise PlatformMigrationReadinessError(
                    "database_select_one_failed", service_id
                )
            cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
            applied = tuple(row[0] for row in cursor.fetchall())
    if applied != tuple(sorted(planned)):
        raise PlatformMigrationReadinessError(
            "migration_head_not_current", service_id
        )
    return {"identity": True, "select_one": True}
