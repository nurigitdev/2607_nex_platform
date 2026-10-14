#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

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

from nex_ae_api.agent_runtime_dispatcher import (
    AgentRuntimeDispatcherConfig,
    AgentRuntimeDispatcherError,
    SqlAlchemyAgentRuntimeDispatcher,
)
from nex_ae_api.agent_runtime_operations import (
    SqlAlchemyAgentRuntimeOperationsSource,
)
from nex_ae_api.runtime_jobs import RuntimeJobError, SqlAlchemyRuntimeJobQueue
from nex_runtime import load_env_file, redact_database_url
from run_migrations import MigrationError, run_service_migrations
from run_p5_s5_postgres_smoke import _execute_postgres_smoke as _execute_p5_fixture

SCHEMA_VERSION = "p6_s1_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P6_S1_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2200_ae_runtime_dispatch"
TEST_BACKEND = "P6_S1_TEST_BACKEND"


def run_p6_s1_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-S1",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    database_url = env.get(DATABASE_ENV, "")
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    if not _target_url_allowed(database_url):
        return _failure(
            "target_not_allowed",
            f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
        )
    try:
        migration = run_service_migrations(
            "nex-ae-api", database_url=database_url, profile="test"
        )
        evidence = _execute_p5_fixture(database_url, verifier=_verify_dispatcher)
        migration_current = REQUIRED_MIGRATION in migration.planned and len(
            migration.planned
        ) == len(migration.applied) + len(migration.skipped)
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P6-S1",
                "profile": "test",
                "database_env": DATABASE_ENV,
                "redacted_database_url": redact_database_url(database_url),
                "migration": {
                    "planned_count": len(migration.planned),
                    "applied_count": len(migration.applied),
                    "skipped_count": len(migration.skipped),
                    "latest_version": migration.planned[-1]
                    if migration.planned
                    else None,
                },
            }
        )
        evidence["checks"] = {
            "migration_current": migration_current,
            **evidence["checks"],
        }
        evidence["status"] = "PASS" if all(evidence["checks"].values()) else "FAIL"
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "p6_s1_postgres_smoke_failed"
        return evidence
    except (
        AgentRuntimeDispatcherError,
        MigrationError,
        OSError,
        RuntimeError,
        RuntimeJobError,
        SQLAlchemyError,
        ValueError,
    ) as exc:
        return _failure(
            "execution_failed", _redact_detail(str(exc), database_url=database_url)
        )


def _verify_dispatcher(context: Mapping[str, Any]) -> dict[str, Any]:
    factory = context["factory"]
    tenant_id = str(context["tenant_id"])
    execution = context["execution"]
    executable_plan = context["executable_plan"]
    base_time = str(context["now"])
    execution_id = str(execution["agent_execution_id"])
    steps = list(executable_plan["steps"])
    if len(steps) < 2:
        raise RuntimeError("P6-S1 smoke requires two P5 executable steps")
    executor_kinds = tuple(str(step["executor_kind"]) for step in steps[:2])
    queue_name = f"ae-runtime-p6-s1-{tenant_id[-12:]}"
    leader_config = AgentRuntimeDispatcherConfig(
        dispatcher_id=f"leader-a-{tenant_id[-12:]}",
        queue_name=queue_name,
        leadership_lease_seconds=2,
        tenant_snapshot_limit=4,
        dispatch_batch_size=2,
        global_active_claim_cap=2,
        per_tenant_active_claim_cap=2,
        max_runnable_depth=20,
        malformed_reconcile_batch=4,
    )
    standby_config = AgentRuntimeDispatcherConfig(
        dispatcher_id=f"leader-b-{tenant_id[-12:]}",
        queue_name=queue_name,
        leadership_lease_seconds=2,
        tenant_snapshot_limit=4,
        dispatch_batch_size=2,
        global_active_claim_cap=2,
        per_tenant_active_claim_cap=2,
        max_runnable_depth=20,
        malformed_reconcile_batch=4,
    )
    executor_backends = {kind: TEST_BACKEND for kind in executor_kinds}
    queue = SqlAlchemyRuntimeJobQueue(factory)
    leader = SqlAlchemyAgentRuntimeDispatcher(
        factory,
        config=leader_config,
        queue=queue,
        executor_backends=executor_backends,
    )
    standby = SqlAlchemyAgentRuntimeDispatcher(
        factory,
        config=standby_config,
        queue=queue,
        executor_backends=executor_backends,
    )
    job_ids: list[str] = []
    cleanup: dict[str, int] = {}

    def enqueue(suffix: str, step_id: str | None) -> dict[str, Any]:
        job_id = f"p6-s1-{suffix}-{tenant_id[-12:]}"
        job_ids.append(job_id)
        return queue.enqueue_unique(
            tenant_id=tenant_id,
            runtime_job_id=job_id,
            job_type="START_EXECUTION",
            execution_id=execution_id,
            executable_step_id=step_id,
            dedup_key=f"p6-s1:{suffix}:{execution_id}",
            run_after=base_time,
            correlation_id=f"p6-s1:{execution_id}",
            now=base_time,
            payload={"fixture_ref": f"P6-S1:{suffix}"},
        )

    first_job = enqueue("first", str(steps[0]["executable_step_id"]))
    second_job = enqueue("second", str(steps[1]["executable_step_id"]))

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            leadership_results = list(
                executor.map(
                    lambda dispatcher: dispatcher.acquire_leadership(
                        observed_at=base_time
                    ),
                    (leader, standby),
                )
            )
        winners = [item for item in leadership_results if item is not None]
        if len(winners) != 1:
            raise RuntimeError("dispatcher leadership was not exclusive")
        active_dispatcher = leader if leadership_results[0] is not None else standby
        standby_dispatcher = standby if active_dispatcher is leader else leader
        active_lease = winners[0]

        first_round = active_dispatcher.dispatch_round(
            worker_id="p6-s1-worker-a",
            supported_executor_kinds=(executor_kinds[0],),
            supported_backend_profiles=(TEST_BACKEND,),
            lease_seconds=30,
            observed_at=_at(base_time, 0.1),
        )
        first_assignment = first_round["assignments"][0]
        queue.complete(
            tenant_id=tenant_id,
            runtime_job_id=first_assignment.runtime_job_id,
            worker_id="p6-s1-worker-a",
            lease_token=str(first_assignment.claim.job["lease_token"]),
            now=_at(base_time, 0.2),
        )
        second_round = active_dispatcher.dispatch_round(
            worker_id="p6-s1-worker-a",
            supported_executor_kinds=executor_kinds,
            supported_backend_profiles=(TEST_BACKEND,),
            lease_seconds=30,
            observed_at=_at(base_time, 1),
        )
        second_assignment = second_round["assignments"][0]
        queue.complete(
            tenant_id=tenant_id,
            runtime_job_id=second_assignment.runtime_job_id,
            worker_id="p6-s1-worker-a",
            lease_token=str(second_assignment.claim.job["lease_token"]),
            now=_at(base_time, 1.1),
        )

        third_job = enqueue("third", str(steps[0]["executable_step_id"]))
        takeover_time = _at(base_time, 3)
        takeover = standby_dispatcher.acquire_leadership(observed_at=takeover_time)
        if takeover is None:
            raise RuntimeError("expired dispatcher leadership was not reclaimed")
        stale_claim = queue.claim_capability_aware(
            tenant_id=tenant_id,
            worker_id="stale-worker",
            supported_executor_kinds=executor_kinds,
            lease_seconds=30,
            now=takeover_time,
            queue_name=queue_name,
            dispatcher_id=str(active_lease["owner_id"]),
            fencing_token=int(active_lease["fencing_token"]),
        )
        takeover_round = standby_dispatcher.dispatch_round(
            worker_id="p6-s1-worker-b",
            supported_executor_kinds=executor_kinds,
            supported_backend_profiles=(TEST_BACKEND,),
            lease_seconds=1,
            observed_at=_at(base_time, 3.1),
        )
        reclaimed_round = standby_dispatcher.dispatch_round(
            worker_id="p6-s1-worker-b",
            supported_executor_kinds=executor_kinds,
            supported_backend_profiles=(TEST_BACKEND,),
            lease_seconds=30,
            observed_at=_at(base_time, 5.2),
        )
        reclaimed = reclaimed_round["assignments"][0]
        queue.complete(
            tenant_id=tenant_id,
            runtime_job_id=reclaimed.runtime_job_id,
            worker_id="p6-s1-worker-b",
            lease_token=str(reclaimed.claim.job["lease_token"]),
            now=_at(base_time, 5.3),
        )

        malformed_job = enqueue("malformed", None)
        reconciliation = standby_dispatcher.reconcile_malformed_jobs(
            supported_executor_kinds=executor_kinds,
            observed_at=_at(base_time, 5.4),
        )
        snapshot = SqlAlchemyAgentRuntimeOperationsSource(
            factory, queue_name=queue_name
        ).snapshot(observed_at=_at(base_time, 5.5))
        attempts = queue.list_attempts(tenant_id, third_job["runtime_job_id"])

        with factory() as session:
            explain = session.execute(
                text(
                    "EXPLAIN (FORMAT JSON) SELECT job.tenant_id "
                    "FROM ae_runtime_job AS job "
                    "JOIN ae_executable_step AS step "
                    "ON step.tenant_id = job.tenant_id "
                    "AND step.executable_step_id = job.executable_step_id "
                    "WHERE job.state = 'QUEUED' AND job.run_after <= :now "
                    "AND step.executor_kind = :kind "
                    "ORDER BY job.run_after, job.tenant_id LIMIT 4"
                ),
                {"now": _at(base_time, 5.5), "kind": executor_kinds[0]},
            ).scalar_one()
            explain_text = json.dumps(explain, sort_keys=True)

        checks = {
            "leader_exclusive": len(winners) == 1,
            "capability_filtered": first_assignment.executor_kind == executor_kinds[0]
            and queue.get(tenant_id, second_job["runtime_job_id"])["state"] == "DONE",
            "atomic_claims_completed": queue.get(
                tenant_id, first_job["runtime_job_id"]
            )["state"]
            == "DONE"
            and queue.get(tenant_id, second_job["runtime_job_id"])["state"] == "DONE",
            "leader_failover_fenced": int(takeover["fencing_token"])
            > int(active_lease["fencing_token"])
            and stale_claim is None,
            "lease_reclaimed": len(attempts) == 2
            and attempts[0]["outcome"] == "LEASE_EXPIRED"
            and attempts[1]["outcome"] == "DONE"
            and takeover_round["metrics"]["claimed_count"] == 1,
            "malformed_dead_lettered": reconciliation["reconciled_count"] == 1
            and queue.get(tenant_id, malformed_job["runtime_job_id"])["state"]
            == "DEAD_LETTER",
            "operations_read_only": snapshot["mutation_authority"] is False
            and snapshot["privacy"]["runtime_job_ids_included"] is False,
            "postgres_plan_observed": "Plan" in explain_text,
        }
        row_counts = {
            "runtime_jobs": len(job_ids),
            "third_job_attempts": len(attempts),
            "issues": snapshot["issues"]["open_count"],
            "leader_rows": 1,
        }
    finally:
        with factory.begin() as session:
            cleanup["issues"] = int(
                session.execute(
                    text("DELETE FROM ae_rt_job_issue WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
            cleanup["attempts"] = int(
                session.execute(
                    text(
                        "DELETE FROM ae_runtime_job_attempt WHERE tenant_id = :tenant_id "
                        "AND runtime_job_id = ANY(:job_ids)"
                    ),
                    {"tenant_id": tenant_id, "job_ids": job_ids},
                ).rowcount
                or 0
            )
            cleanup["jobs"] = int(
                session.execute(
                    text(
                        "DELETE FROM ae_runtime_job WHERE tenant_id = :tenant_id "
                        "AND runtime_job_id = ANY(:job_ids)"
                    ),
                    {"tenant_id": tenant_id, "job_ids": job_ids},
                ).rowcount
                or 0
            )
            cleanup["leadership"] = int(
                session.execute(
                    text(
                        "DELETE FROM ae_rt_dispatch_lease WHERE queue_name = :queue_name"
                    ),
                    {"queue_name": queue_name},
                ).rowcount
                or 0
            )
            cleanup["remaining"] = int(
                session.execute(
                    text(
                        "SELECT count(*) FROM ae_runtime_job WHERE tenant_id = :tenant_id "
                        "AND runtime_job_id = ANY(:job_ids)"
                    ),
                    {"tenant_id": tenant_id, "job_ids": job_ids},
                ).scalar_one()
            )
    checks["zero_residue"] = cleanup["remaining"] == 0
    return {
        "checks": checks,
        "row_counts": row_counts,
        "cleanup_counts": cleanup,
    }


def _at(value: str, seconds: float) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    return (parsed + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        parsed.scheme.startswith("postgresql")
        and unquote(parsed.username or "") == EXPECTED_ROLE
        and parsed.path.removeprefix("/") == EXPECTED_DATABASE
    )


def _redact_detail(detail: str, *, database_url: str) -> str:
    redacted = detail.replace(database_url, redact_database_url(database_url))
    password = urlsplit(database_url).password
    return redacted.replace(unquote(password), "***") if password else redacted


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6-S1",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    rows = evidence.get("row_counts") or {}
    cleanup = evidence.get("cleanup_counts") or {}
    return (
        f"p6_s1_postgres={str(evidence.get('status', 'FAIL')).lower()} "
        f"actual_postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"jobs={rows.get('runtime_jobs', 0)} attempts={rows.get('third_job_attempts', 0)} "
        f"issues={rows.get('issues', 0)} remaining={cleanup.get('remaining', 0)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run protected P6-S1 PostgreSQL smoke")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()
    env = dict(os.environ)
    env.update(load_env_file(Path(args.env_file)) or {})
    evidence = run_p6_s1_postgres_smoke(env)
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    if evidence["status"] == "SKIPPED":
        return 0
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
