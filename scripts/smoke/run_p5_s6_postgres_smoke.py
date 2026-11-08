#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

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
from nex_ae_api.multi_step_engine import (
    MultiStepEngineError,
    SqlAlchemyMultiStepEngine,
    StepTerminalOutcome,
)
from nex_ae_api.runtime_jobs import RuntimeJobError, SqlAlchemyRuntimeJobQueue
from nex_ae_api.step_results import SqlAlchemyStepResultRepository, StepResultError
from nex_runtime import load_env_file, redact_database_url
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p5_s6_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P5_S6_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2106_ae_step_result"


def run_p5_s6_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P5-S6",
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
            database_url, verifier=_verify_multi_step_runtime
        )
        migration_current = REQUIRED_MIGRATION in migration.planned and len(
            migration.planned
        ) == len(migration.applied) + len(migration.skipped)
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P5-S6",
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
            evidence["failure_code"] = "p5_s6_postgres_smoke_failed"
        return evidence
    except (
        MigrationError,
        MultiStepEngineError,
        OSError,
        RuntimeError,
        RuntimeJobError,
        StepResultError,
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


def _verify_multi_step_runtime(fixture: Mapping[str, Any]) -> dict[str, Any]:
    factory = fixture["factory"]
    tenant_id = str(fixture["tenant_id"])
    execution = dict(fixture["execution"])
    plan = dict(fixture["executable_plan"])
    now = str(fixture["now"])
    queue = SqlAlchemyRuntimeJobQueue(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue)

    first_job = engine.schedule_next(
        tenant_id=tenant_id,
        execution_id=execution["agent_execution_id"],
        now=now,
    )
    deduplicated = engine.schedule_next(
        tenant_id=tenant_id,
        execution_id=execution["agent_execution_id"],
        now=now,
    )
    first_claim = queue.claim(
        tenant_id=tenant_id,
        worker_id="p5-s6-smoke-worker",
        lease_seconds=60,
        now=now,
    )
    if first_claim is None:
        raise RuntimeError("P5-S6 START RuntimeJob was not claimable")
    first_context = engine.begin_claim(tenant_id=tenant_id, claim=first_claim, now=now)
    first_outcome = StepTerminalOutcome(
        status="SUCCEEDED",
        result_contract_ref=first_context.step["output_contract_ref"],
        result_payload={"result_ref": f"AE:SMOKE:{uuid4()}"},
        started_at=now,
        completed_at=now,
        evidence_refs=("AE:P5-S6:SMOKE:E1",),
    )
    first_result = engine.record_outcome(
        tenant_id=tenant_id,
        claim=first_claim,
        outcome=first_outcome,
    )
    replayed_result = engine.record_outcome(
        tenant_id=tenant_id,
        claim=first_claim,
        outcome=first_outcome,
    )
    queue.complete(
        tenant_id=tenant_id,
        runtime_job_id=first_claim.job["runtime_job_id"],
        worker_id="p5-s6-smoke-worker",
        lease_token=first_claim.job["lease_token"],
        now=now,
    )

    second_job = engine.schedule_next(
        tenant_id=tenant_id,
        execution_id=execution["agent_execution_id"],
        now=now,
    )
    second_claim = queue.claim(
        tenant_id=tenant_id,
        worker_id="p5-s6-smoke-worker",
        lease_seconds=60,
        now=now,
    )
    if second_claim is None:
        raise RuntimeError("P5-S6 CONTINUE RuntimeJob was not claimable")
    second_context = engine.begin_claim(
        tenant_id=tenant_id, claim=second_claim, now=now
    )
    second_result = engine.record_outcome(
        tenant_id=tenant_id,
        claim=second_claim,
        outcome=StepTerminalOutcome(
            status="SUCCEEDED",
            result_contract_ref=second_context.step["output_contract_ref"],
            result_payload={"result_ref": f"AE:SMOKE:{uuid4()}"},
            started_at=now,
            completed_at=now,
            evidence_refs=("AE:P5-S6:SMOKE:E2",),
        ),
    )
    queue.complete(
        tenant_id=tenant_id,
        runtime_job_id=second_claim.job["runtime_job_id"],
        worker_id="p5-s6-smoke-worker",
        lease_token=second_claim.job["lease_token"],
        now=now,
    )

    restarted = SqlAlchemyMultiStepEngine(factory, SqlAlchemyRuntimeJobQueue(factory))
    no_more_work = restarted.schedule_next(
        tenant_id=tenant_id,
        execution_id=execution["agent_execution_id"],
        now=now,
    )
    results = SqlAlchemyStepResultRepository(factory).list_for_plan(
        tenant_id=tenant_id,
        executable_plan_id=plan["executable_plan_id"],
    )
    with factory() as session:
        phase = session.execute(
            text(
                "SELECT phase FROM ae_agent_execution "
                "WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id"
            ),
            {
                "tenant_id": tenant_id,
                "execution_id": execution["agent_execution_id"],
            },
        ).scalar_one()
        result_count = _tenant_count(session, "ae_step_result", tenant_id)
        job_count = _tenant_count(session, "ae_runtime_job", tenant_id)
        attempt_count = _tenant_count(session, "ae_runtime_job_attempt", tenant_id)

    checks = {
        "start_continue_job_order": first_job is not None
        and second_job is not None
        and first_job["job_type"] == "START_EXECUTION"
        and second_job["job_type"] == "CONTINUE_EXECUTION",
        "runtime_job_deduplicated": first_job == deduplicated,
        "dependency_result_handoff": second_context.dependency_results
        == (first_result,),
        "immutable_result_replay": replayed_result == first_result,
        "terminal_results_persisted": result_count == 2
        and [item["compiled_step_key"] for item in results] == ["E1", "E2"]
        and results[-1] == second_result,
        "write_identity_null": all(
            item["business_operation_id"] is None
            and item["operation_fingerprint"] is None
            for item in results
        ),
        "restart_does_not_reexecute": no_more_work is None
        and phase == "RESULT_VERIFY"
        and job_count == 2
        and attempt_count == 2,
    }
    cleanup = _cleanup_runtime_rows(factory, tenant_id)
    checks["runtime_cleanup_complete"] = cleanup["runtime_remaining"] == 0
    return {
        "checks": checks,
        "row_counts": {
            "step_result": result_count,
            "runtime_job": job_count,
            "runtime_job_attempt": attempt_count,
        },
        "cleanup_counts": cleanup,
    }


def _cleanup_runtime_rows(factory, tenant_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    tables = ("ae_step_result", "ae_runtime_job_attempt", "ae_runtime_job")
    with factory.begin() as session:
        for table in tables:
            counts[table] = int(
                session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
    with factory() as session:
        counts["runtime_remaining"] = sum(
            _tenant_count(session, table, tenant_id) for table in tables
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
        "slice": "P5-S6",
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
        "p5_s6_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"execution={str(evidence.get('execution_state') or 'not-run').lower()} "
        f"database={evidence.get('database', 'not-run')} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"results={rows.get('step_result', 0)} "
        f"jobs={rows.get('runtime_job', 0)} "
        f"cleanup={(evidence.get('cleanup_counts') or {}).get('remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p5_s6_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
