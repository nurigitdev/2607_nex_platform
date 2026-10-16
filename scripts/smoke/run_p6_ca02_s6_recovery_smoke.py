#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
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
import run_p6_s5_postgres_smoke as p6_s5
from nex_ae_api.multi_step_engine import (
    MultiStepEngineError,
    SqlAlchemyMultiStepEngine,
    StepTerminalOutcome,
)
from nex_ae_api.nsl_read_backends import V01InProcessReadBackendAdapter
from nex_ae_api.runtime_jobs import RuntimeJobError, SqlAlchemyRuntimeJobQueue
from nex_runtime import load_env_file, redact_database_url
from nsl.process_isolation import ProcessIsolatedRuntime
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p6_ca02_s6_recovery_smoke.v1"
SMOKE_ENV = "NEX_AE_P6_CA02_S6_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2205_ae_nsl_dual_profile"


def run_p6_ca02_s6_recovery_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-CA02-S6",
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
            database_url, verifier=_verify_lease_recovery
        )
        timeout = ProcessIsolatedRuntime(
            p6_s5._sleep_target, timeout_ms=20, max_payload_bytes=1024
        ).execute(b"timeout")
        crash = ProcessIsolatedRuntime(
            p6_s5._crash_target, timeout_ms=10_000, max_payload_bytes=1024
        ).execute(b"crash")
        evidence["checks"] = {
            "migration_current": (
                REQUIRED_MIGRATION in migration.planned
                and migration.planned[-1] == REQUIRED_MIGRATION
                and len(migration.planned)
                == len(migration.applied) + len(migration.skipped)
            ),
            **evidence["checks"],
            "in_process_timeout_is_cooperative": (
                V01InProcessReadBackendAdapter.timeout_semantics
                == "NSL_COOPERATIVE_DEADLINE"
            ),
            "isolated_hard_timeout_contained": timeout.status == "TIMED_OUT",
            "isolated_crash_contained": crash.status == "CRASHED",
        }
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P6-CA02-S6",
                "status": ("PASS" if all(evidence["checks"].values()) else "FAIL"),
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
                "isolation_evidence": {
                    "timeout_status": timeout.status,
                    "crash_status": crash.status,
                },
            }
        )
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "p6_ca02_s6_recovery_smoke_failed"
        return evidence
    except (
        MigrationError,
        MultiStepEngineError,
        OSError,
        RuntimeError,
        RuntimeJobError,
        SQLAlchemyError,
        ValueError,
    ) as exc:
        return _failure(
            "execution_failed",
            p5_s5._redact_detail(str(exc), database_url=database_url),
        )


def _verify_lease_recovery(context: Mapping[str, Any]) -> dict[str, Any]:
    factory = context["factory"]
    tenant_id = str(context["tenant_id"])
    execution = context["execution"]
    executable_plan = context["executable_plan"]
    base_time = str(context["now"])
    execution_id = str(execution["agent_execution_id"])
    first_step = executable_plan["steps"][0]
    queue = SqlAlchemyRuntimeJobQueue(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue)
    job = engine.schedule_next(
        tenant_id=tenant_id, execution_id=execution_id, now=base_time
    )
    if job is None:
        raise RuntimeError("P6-CA02-S6 smoke did not schedule a RuntimeJob")
    job_id = str(job["runtime_job_id"])
    try:
        evidence = _exercise_lease_recovery(
            factory=factory,
            tenant_id=tenant_id,
            base_time=base_time,
            first_step=first_step,
            job=job,
            queue=queue,
            engine=engine,
        )
    finally:
        cleanup = _cleanup_recovery_rows(
            factory,
            tenant_id=tenant_id,
            runtime_job_id=job_id,
            executable_step_id=str(first_step["executable_step_id"]),
        )
    evidence["checks"]["recovery_zero_residue"] = cleanup["remaining"] == 0
    evidence["cleanup_counts"] = cleanup
    return evidence


def _exercise_lease_recovery(
    *,
    factory: Any,
    tenant_id: str,
    base_time: str,
    first_step: Mapping[str, Any],
    job: Mapping[str, Any],
    queue: SqlAlchemyRuntimeJobQueue,
    engine: SqlAlchemyMultiStepEngine,
) -> dict[str, Any]:
    first = queue.claim(
        tenant_id=tenant_id,
        worker_id="p6-ca02-s6-stale",
        lease_seconds=1,
        now=base_time,
    )
    if first is None:
        raise RuntimeError("P6-CA02-S6 smoke did not claim the first attempt")
    engine.begin_claim(tenant_id=tenant_id, claim=first, now=base_time)
    reclaim_time = _at(base_time, 2)
    second = queue.claim(
        tenant_id=tenant_id,
        worker_id="p6-ca02-s6-recovered",
        lease_seconds=30,
        now=reclaim_time,
    )
    if second is None:
        raise RuntimeError("P6-CA02-S6 smoke did not reclaim the expired attempt")

    stale_fenced = False
    try:
        engine.record_outcome(
            tenant_id=tenant_id,
            claim=first,
            outcome=_outcome(first_step, base_time, reclaim_time, "stale"),
            observed_at=reclaim_time,
        )
    except MultiStepEngineError as exc:
        stale_fenced = exc.error_code == "ae.multi_step_stale_runtime_job_lease"

    with factory() as session:
        stale_result_count = int(
            session.execute(
                text(
                    "SELECT count(*) FROM ae_step_result "
                    "WHERE tenant_id = :tenant_id AND executable_step_id = :step_id"
                ),
                {
                    "tenant_id": tenant_id,
                    "step_id": first_step["executable_step_id"],
                },
            ).scalar_one()
        )
        synthetic_backend_runs = int(
            session.execute(
                text(
                    "SELECT count(*) FROM ae_nsl_backend_run "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )

    engine.begin_claim(tenant_id=tenant_id, claim=second, now=reclaim_time)
    settlement_time = _at(base_time, 3)
    result = engine.record_outcome(
        tenant_id=tenant_id,
        claim=second,
        outcome=_outcome(first_step, reclaim_time, settlement_time, "recovered"),
        observed_at=settlement_time,
    )
    done = queue.complete(
        tenant_id=tenant_id,
        runtime_job_id=str(job["runtime_job_id"]),
        worker_id="p6-ca02-s6-recovered",
        lease_token=str(second.job["lease_token"]),
        now=settlement_time,
    )
    attempts = queue.list_attempts(tenant_id, str(job["runtime_job_id"]))
    checks = {
        "expired_attempt_reclaimed": (
            len(attempts) == 2
            and attempts[0]["outcome"] == "LEASE_EXPIRED"
            and attempts[1]["outcome"] == "DONE"
        ),
        "stale_attempt_fenced": stale_fenced,
        "stale_result_absent": stale_result_count == 0,
        "no_synthetic_backend_evidence": synthetic_backend_runs == 0,
        "recovered_attempt_terminalized": (
            result["attempt_no"] == 2 and done["state"] == "DONE"
        ),
    }
    return {
        "checks": checks,
        "row_counts": {
            "runtime_job_attempts": len(attempts),
            "stale_step_results": stale_result_count,
            "synthetic_backend_runs": synthetic_backend_runs,
        },
        "recovery_evidence": {
            "runtime_job_id": str(job["runtime_job_id"]),
            "attempt_outcomes": [item["outcome"] for item in attempts],
            "step_result_attempt_no": result["attempt_no"],
        },
    }


def _cleanup_recovery_rows(
    factory: Any,
    *,
    tenant_id: str,
    runtime_job_id: str,
    executable_step_id: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    with factory.begin() as session:
        counts["step_results"] = int(
            session.execute(
                text(
                    "DELETE FROM ae_step_result WHERE tenant_id = :tenant_id "
                    "AND executable_step_id = :step_id"
                ),
                {"tenant_id": tenant_id, "step_id": executable_step_id},
            ).rowcount
            or 0
        )
        counts["attempts"] = int(
            session.execute(
                text(
                    "DELETE FROM ae_runtime_job_attempt "
                    "WHERE tenant_id = :tenant_id AND runtime_job_id = :job_id"
                ),
                {"tenant_id": tenant_id, "job_id": runtime_job_id},
            ).rowcount
            or 0
        )
        counts["jobs"] = int(
            session.execute(
                text(
                    "DELETE FROM ae_runtime_job "
                    "WHERE tenant_id = :tenant_id AND runtime_job_id = :job_id"
                ),
                {"tenant_id": tenant_id, "job_id": runtime_job_id},
            ).rowcount
            or 0
        )
    with factory() as session:
        counts["remaining"] = int(
            session.execute(
                text(
                    "SELECT count(*) FROM ae_runtime_job "
                    "WHERE tenant_id = :tenant_id AND runtime_job_id = :job_id"
                ),
                {"tenant_id": tenant_id, "job_id": runtime_job_id},
            ).scalar_one()
        ) + int(
            session.execute(
                text(
                    "SELECT count(*) FROM ae_step_result "
                    "WHERE tenant_id = :tenant_id AND executable_step_id = :step_id"
                ),
                {"tenant_id": tenant_id, "step_id": executable_step_id},
            ).scalar_one()
        )
    return counts


def _outcome(
    step: Mapping[str, Any], started_at: str, completed_at: str, value: str
) -> StepTerminalOutcome:
    return StepTerminalOutcome(
        status="SUCCEEDED",
        result_contract_ref=str(step["output_contract_ref"]),
        result_payload={"result_ref": value},
        started_at=started_at,
        completed_at=completed_at,
    )


def _at(value: str, seconds: int) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    return (parsed + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6-CA02-S6",
        "status": "FAIL",
        "failure_code": code,
        "failure_detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    migration = evidence.get("migration") or {}
    cleanup = evidence.get("cleanup_counts") or {}
    failed_checks = ",".join(
        str(key) for key, value in checks.items() if not bool(value)
    )
    return (
        "p6_ca02_s6_recovery="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"failed={failed_checks or 'none'} "
        f"migration={migration.get('latest_version', 'not-run')} "
        f"cleanup={cleanup.get('remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run protected P6-CA02-S6 timeout/crash/lease recovery smoke."
    )
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    env = dict(os.environ)
    if args.env_file:
        env.update(load_env_file(Path(args.env_file)) or {})
    result = run_p6_ca02_s6_recovery_smoke(env)
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
