#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p5_s5_postgres_smoke as p5_s5
import run_p5_s7_postgres_smoke as p5_s7
from nex_ae_api.agent_results import AgentResultError, SqlAlchemyAgentResultRepository
from nex_ae_api.plan_finalization import (
    P5PlanFinalizationError,
    SqlAlchemyP5PlanFinalizationService,
)
from nex_runtime import load_env_file, redact_database_url
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p5_s8_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P5_S8_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2106_ae_step_result"


def run_p5_s8_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P5-S8",
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
        evidence = p5_s5._execute_postgres_smoke(
            database_url,
            verifier=lambda fixture: p5_s7._verify_executor_runtime(
                fixture, finalizer=_verify_plan_finalization
            ),
        )
        migration_current = REQUIRED_MIGRATION in migration.planned and len(
            migration.planned
        ) == len(migration.applied) + len(migration.skipped)
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P5-S8",
                "profile": "test",
                "database_env": DATABASE_ENV,
                "redacted_database_url": redact_database_url(database_url),
                "migration": {
                    "planned_count": len(migration.planned),
                    "applied_count": len(migration.applied),
                    "skipped_count": len(migration.skipped),
                    "latest_version": (
                        migration.planned[-1] if migration.planned else None
                    ),
                },
            }
        )
        evidence["checks"] = {
            "migration_current": migration_current,
            **evidence["checks"],
        }
        evidence["status"] = "PASS" if all(evidence["checks"].values()) else "FAIL"
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "p5_s8_postgres_smoke_failed"
        return evidence
    except (
        AgentResultError,
        MigrationError,
        OSError,
        P5PlanFinalizationError,
        RuntimeError,
        ValueError,
        p5_s5.AgentContextError,
        p5_s5.AgentExecutionError,
        p5_s5.AgentIdentityRepositoryError,
        p5_s5.AgentPlanError,
        p5_s5.CapabilitySnapshotError,
        p5_s5.ExecutablePlanError,
        p5_s5.PlanValidationError,
        p5_s5.RuntimePolicyError,
        p5_s5.SQLAlchemyError,
        p5_s5.WorkIntentError,
    ) as exc:
        return _failure(
            "execution_failed",
            p5_s5._redact_detail(str(exc), database_url=database_url),
        )


def _verify_plan_finalization(fixture: Mapping[str, Any]) -> dict[str, Any]:
    factory = fixture["factory"]
    tenant_id = str(fixture["tenant_id"])
    execution = dict(fixture["execution"])
    now = str(fixture["now"])
    report = fixture["report_execution"]
    service = SqlAlchemyP5PlanFinalizationService(factory)

    aggregate = service.finalize(
        tenant_id=tenant_id,
        execution_id=execution["agent_execution_id"],
        created_at=now,
    )
    replayed = service.finalize(
        tenant_id=tenant_id,
        execution_id=execution["agent_execution_id"],
        created_at=now,
    )
    loaded = SqlAlchemyAgentResultRepository(factory).get(
        tenant_id, aggregate.result["result_id"]
    )
    output = aggregate.result["structured_result"]["output_step_results"]
    serialized = json.dumps(aggregate.result, ensure_ascii=False, sort_keys=True)
    with factory() as session:
        result_count = _tenant_count(session, "ae_agent_result", tenant_id)
        delivery_count = _tenant_count(session, "ae_result_delivery", tenant_id)

    checks = {
        "required_step_results_verified": aggregate.result["control_summary"]
        == {
            "completion_status": "VERIFIED",
            "required_criteria_count": 1,
            "step_result_count": 2,
        },
        "plan_result_reference_only": len(output) == 1
        and output[0]["compiled_step_key"] == "E2"
        and output[0]["step_result_ref"]
        == f"AE:STEP_RESULT:{report.step_result['step_result_id']}"
        and "result_payload" not in serialized,
        "agent_result_immutable_replay": aggregate == replayed == loaded
        and result_count == 1,
        "workspace_delivery_pending": delivery_count == 1
        and aggregate.delivery["target_type"] == "WORKSPACE_RESULT"
        and aggregate.delivery["required"] is True
        and aggregate.delivery["state"] == "PENDING",
        "execution_waits_for_ack": aggregate.execution["state"] == "RUNNING"
        and aggregate.execution["phase"] == "RESULT_PUBLISH"
        and aggregate.execution["result_id"] == aggregate.result["result_id"],
        "zero_nsl_write_identity": "business_operation_id" not in serialized
        and "operation_fingerprint" not in serialized
        and "NSLExecutionId" not in serialized,
    }
    cleanup = _cleanup_finalization_rows(factory, tenant_id)
    checks["finalization_cleanup_complete"] = cleanup["finalization_remaining"] == 0
    return {
        "checks": checks,
        "row_counts": {
            "agent_result": result_count,
            "result_delivery": delivery_count,
        },
        "cleanup_counts": cleanup,
    }


def _cleanup_finalization_rows(factory, tenant_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with factory.begin() as session:
        for table in ("ae_result_delivery", "ae_agent_result"):
            counts[table] = int(
                session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
    with factory() as session:
        counts["finalization_remaining"] = sum(
            _tenant_count(session, table, tenant_id)
            for table in ("ae_result_delivery", "ae_agent_result")
        )
    return counts


def _tenant_count(connection, table: str, tenant_id: str) -> int:
    return int(
        connection.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).scalar_one()
    )


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P5-S8",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    migration = evidence.get("migration") or {}
    rows = evidence.get("row_counts") or {}
    return (
        "p5_s8_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"execution={str(evidence.get('execution_state') or 'not-run').lower()} "
        f"database={evidence.get('database', 'not-run')} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"results={rows.get('step_result', 0)}/{rows.get('agent_result', 0)} "
        f"deliveries={rows.get('result_delivery', 0)} "
        f"cleanup={(evidence.get('cleanup_counts') or {}).get('remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p5_s8_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
