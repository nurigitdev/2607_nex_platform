#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import datetime
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
import run_p5_s6_postgres_smoke as p5_s6
from nex_ae_api.multi_step_engine import MultiStepEngineError, SqlAlchemyMultiStepEngine
from nex_ae_api.runtime_jobs import RuntimeJobError, SqlAlchemyRuntimeJobQueue
from nex_ae_api.step_executors import (
    P5StepExecutionWorker,
    default_p5_executor_registry,
)
from nex_ae_api.step_results import SqlAlchemyStepResultRepository, StepResultError
from nex_runtime import load_env_file, redact_database_url
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p5_s7_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P5_S7_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2106_ae_step_result"


def run_p5_s7_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P5-S7",
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
            database_url, verifier=_verify_executor_runtime
        )
        migration_current = REQUIRED_MIGRATION in migration.planned and len(
            migration.planned
        ) == len(migration.applied) + len(migration.skipped)
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P5-S7",
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
            evidence["failure_code"] = "p5_s7_postgres_smoke_failed"
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


def _verify_executor_runtime(
    fixture: Mapping[str, Any],
    *,
    finalizer: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    factory = fixture["factory"]
    tenant_id = str(fixture["tenant_id"])
    execution = dict(fixture["execution"])
    plan = dict(fixture["executable_plan"])
    now = str(fixture["now"])
    clock_value = datetime.fromisoformat(now.replace("Z", "+00:00"))
    interaction_id = str(execution["legacy_interaction_id"])
    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET input_binding_json = "
                "CAST(:bindings AS jsonb) WHERE tenant_id = :tenant_id "
                "AND executable_plan_id = :plan_id AND compiled_step_key = 'E2'"
            ),
            {
                "bindings": json.dumps(
                    [
                        {
                            "target_name": "source_result",
                            "binding_type": "COMPILED_STEP_OUTPUT",
                            "source_ref": "E1:$",
                        }
                    ],
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "tenant_id": tenant_id,
                "plan_id": plan["executable_plan_id"],
            },
        )

    callback_count = 0

    def callback(_context):
        nonlocal callback_count
        callback_count += 1
        return {
            "interaction_id": interaction_id,
            "status": "PENDING",
            "cx_generation_id": "p5-s7-generation",
            "generation": {
                "async_generation": {
                    "job_id": "p5-s7-cx-job",
                    "cx_generation_id": "p5-s7-generation",
                }
            },
            "retrieval": None,
            "artifact_refs": [],
        }

    queue = SqlAlchemyRuntimeJobQueue(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue)
    worker = P5StepExecutionWorker(
        engine=engine,
        jobs=queue,
        executors=default_p5_executor_registry(callback),
        clock=lambda: clock_value,
    )
    engine.schedule_next(
        tenant_id=tenant_id,
        execution_id=execution["agent_execution_id"],
        now=now,
    )
    start_claim = _claim(queue, tenant_id, now)
    waiting = worker.run_claim(tenant_id=tenant_id, claim=start_claim)
    continuation_job = engine.enqueue_waiting_continuation(
        tenant_id=tenant_id,
        execution_id=execution["agent_execution_id"],
        executable_step_id=waiting.step["executable_step_id"],
        continuation_refs={
            "cx_job_ref": "p5-s7-cx-job",
            "cx_generation_ref": "p5-s7-generation",
            "generated_response_ref": "p5-s7-response",
            "status": "COMPLETED",
        },
        now=now,
    )
    continue_claim = _claim(queue, tenant_id, now)
    compatibility = worker.run_claim(
        tenant_id=tenant_id,
        claim=continue_claim,
        continuation_result={
            "interaction_id": interaction_id,
            "status": "COMPLETED",
            "cx_generation_id": "p5-s7-generation",
            "generation": {
                "async_generation": {"job_id": "p5-s7-cx-job"},
                "generated_response_id": "p5-s7-response",
            },
            "retrieval": None,
            "artifact_refs": [],
        },
    )
    report_job = engine.schedule_next(
        tenant_id=tenant_id,
        execution_id=execution["agent_execution_id"],
        now=now,
    )
    report_claim = _claim(queue, tenant_id, now)
    report = worker.run_claim(tenant_id=tenant_id, claim=report_claim)

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
    source = report.step_result["result_payload"]["bindings"]["source_result"]
    with factory() as session:
        phase = session.execute(
            text(
                "SELECT phase FROM ae_agent_execution WHERE tenant_id = :tenant_id "
                "AND agent_execution_id = :execution_id"
            ),
            {
                "tenant_id": tenant_id,
                "execution_id": execution["agent_execution_id"],
            },
        ).scalar_one()
        result_count = p5_s6._tenant_count(session, "ae_step_result", tenant_id)
        job_count = p5_s6._tenant_count(session, "ae_runtime_job", tenant_id)
        attempt_count = p5_s6._tenant_count(
            session, "ae_runtime_job_attempt", tenant_id
        )
    finalization = (
        dict(
            finalizer(
                {
                    **fixture,
                    "compatibility_execution": compatibility,
                    "report_execution": report,
                }
            )
        )
        if finalizer is not None
        else {}
    )

    checks = {
        "compatibility_waited": waiting.disposition == "WAITING"
        and waiting.step_result is None
        and waiting.step["cx_job_id"] == "p5-s7-cx-job",
        "continuation_reference_only": continuation_job["job_type"]
        == "CONTINUE_EXECUTION"
        and continuation_job["payload"]
        == {
            "continuation_refs": {
                "cx_job_ref": "p5-s7-cx-job",
                "cx_generation_ref": "p5-s7-generation",
                "generated_response_ref": "p5-s7-response",
                "status": "COMPLETED",
            }
        },
        "chat_invoked_once": callback_count == 1,
        "compatibility_result_persisted": compatibility.disposition == "TERMINAL"
        and compatibility.step_result["status"] == "SUCCEEDED",
        "deterministic_report_executed": report_job is not None
        and report.disposition == "TERMINAL"
        and report.step_result["result_payload"]["projection_kind"] == "REPORT",
        "report_uses_step_result_reference": source["source_step_result_ref"]
        == f"AE:STEP_RESULT:{compatibility.step_result['step_result_id']}"
        and source["source_result_hash"] == compatibility.step_result["result_hash"],
        "terminal_results_persisted": result_count == 2
        and [item["compiled_step_key"] for item in results] == ["E1", "E2"],
        "runtime_jobs_terminal": job_count == 3
        and attempt_count == 3
        and all(
            item.runtime_job["state"] == "DONE"
            for item in (waiting, compatibility, report)
        ),
        "restart_does_not_reexecute": no_more_work is None and phase == "RESULT_VERIFY",
        **dict(finalization.get("checks") or {}),
    }
    cleanup = p5_s6._cleanup_runtime_rows(factory, tenant_id)
    checks["runtime_cleanup_complete"] = cleanup["runtime_remaining"] == 0
    return {
        "checks": checks,
        "row_counts": {
            "step_result": result_count,
            "runtime_job": job_count,
            "runtime_job_attempt": attempt_count,
            **dict(finalization.get("row_counts") or {}),
        },
        "cleanup_counts": {
            **dict(finalization.get("cleanup_counts") or {}),
            **cleanup,
        },
    }


def _claim(queue, tenant_id: str, now: str):
    claim = queue.claim(
        tenant_id=tenant_id,
        worker_id="p5-s7-smoke-worker",
        lease_seconds=60,
        now=now,
    )
    if claim is None:
        raise RuntimeError("P5-S7 RuntimeJob was not claimable")
    return claim


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P5-S7",
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
        "p5_s7_postgres="
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
    evidence = run_p5_s7_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
