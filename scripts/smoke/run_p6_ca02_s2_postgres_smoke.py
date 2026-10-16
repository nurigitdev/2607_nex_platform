#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p5_s5_postgres_smoke as p5_s5
import run_p6_s3_postgres_smoke as p6_s3
from nex_ae_api.nsl_backend_profiles import (
    NSL_V01_IN_PROCESS_BACKEND,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
)
from nex_runtime import load_env_file, redact_database_url
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p6_ca02_s2_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P6_CA02_S2_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2205_ae_nsl_dual_profile"


def run_p6_ca02_s2_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-CA02-S2",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    database_url = env.get(DATABASE_ENV, "")
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    if not p5_s5._target_url_allowed(database_url):
        return _failure(
            "target_not_allowed",
            f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
        )
    try:
        migration = run_service_migrations(
            "nex-ae-api", database_url=database_url, profile="test"
        )
        historical = p5_s5._execute_postgres_smoke(
            database_url,
            verifier=partial(
                p6_s3._verify_nsl_binding,
                backend_profile=NSL_V01_PROCESS_ISOLATED_BACKEND,
                activate_executor=True,
            ),
        )
        current = p5_s5._execute_postgres_smoke(
            database_url,
            verifier=partial(
                p6_s3._verify_nsl_binding,
                backend_profile=NSL_V01_IN_PROCESS_BACKEND,
                activate_executor=True,
            ),
        )
        database_checks = _database_checks(database_url)
        checks = {
            "migration_current": (
                REQUIRED_MIGRATION in migration.planned
                and migration.planned[-1] == REQUIRED_MIGRATION
                and len(migration.planned)
                == len(migration.applied) + len(migration.skipped)
            ),
            "historical_profile_round_trip": historical["status"] == "PASS",
            "in_process_profile_round_trip": current["status"] == "PASS",
            "historical_cleanup_complete": (
                historical["cleanup_counts"].get("remaining") == 0
            ),
            "in_process_cleanup_complete": (
                current["cleanup_counts"].get("remaining") == 0
            ),
            **database_checks,
        }
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-CA02-S2",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "actual_postgres": True,
            "profile": "test",
            "database_env": DATABASE_ENV,
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "planned_count": len(migration.planned),
                "applied_count": len(migration.applied),
                "skipped_count": len(migration.skipped),
                "latest_version": migration.planned[-1],
            },
            "checks": checks,
            "profile_evidence": {
                NSL_V01_PROCESS_ISOLATED_BACKEND: historical["checks"],
                NSL_V01_IN_PROCESS_BACKEND: current["checks"],
            },
        }
    except (
        MigrationError,
        SQLAlchemyError,
        OSError,
        RuntimeError,
        ValueError,
        p6_s3.NSLStepExecutionError,
        p6_s3.SkillArtifactGatewayError,
        p5_s5.AgentContextError,
        p5_s5.AgentExecutionError,
        p5_s5.AgentIdentityRepositoryError,
        p5_s5.AgentPlanError,
        p5_s5.CapabilitySnapshotError,
        p5_s5.ExecutablePlanError,
        p5_s5.PlanValidationError,
        p5_s5.RuntimePolicyError,
        p5_s5.WorkIntentError,
    ) as exc:
        return _failure(
            "execution_failed",
            p5_s5._redact_detail(str(exc), database_url=database_url),
        )


def _database_checks(database_url: str) -> dict[str, bool]:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            database, role = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            migration_recorded = bool(
                connection.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM schema_migrations "
                        "WHERE version = :version)"
                    ),
                    {"version": REQUIRED_MIGRATION},
                ).scalar_one()
            )
            constraint = str(
                connection.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid = 'ae_nsl_step_execution'::regclass "
                        "AND conname = 'ck_ae_nsl_step_profile'"
                    )
                ).scalar_one()
            )
        return {
            "actual_test_database": database == EXPECTED_DATABASE,
            "actual_test_role": role == EXPECTED_ROLE,
            "migration_recorded": migration_recorded,
            "dual_profile_constraint": (
                NSL_V01_IN_PROCESS_BACKEND in constraint
                and NSL_V01_PROCESS_ISOLATED_BACKEND in constraint
            ),
        }
    finally:
        engine.dispose()


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6-CA02-S2",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    migration = evidence.get("migration") or {}
    return (
        "p6_ca02_s2_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"actual_postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"latest={migration.get('latest_version', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p6_ca02_s2_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
