#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services/nex-ae-api",
    ROOT / "services/_shared",
    ROOT / "scripts/db",
    ROOT / "scripts/smoke",
):
    sys.path.insert(0, str(path))

import run_p5_s5_postgres_smoke as p5_s5
from nex_ae_api.agent_runtime_process import (
    PROCESS_ID,
    build_installed_agent_runtime_process,
)
from nex_ae_api.multi_step_engine import SqlAlchemyMultiStepEngine
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_ae_api.step_executors import (
    P5StepExecutionWorker,
    default_p5_executor_registry,
)
from nex_runtime import (
    SqlAlchemyWorkerHeartbeatStore,
    load_env_file,
    redact_database_url,
)
from run_migrations import run_service_migrations

SCHEMA_VERSION = "gb2_ca00_s05_ae_worker_acceptance.v1"
SMOKE_ENV = "NEX_AE_GB2_S05_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"


def run_gb2_ca00_s05_ae_agent_runtime_worker(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "GB2-CA00-S05",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    database_url = str(env.get(DATABASE_ENV) or "")
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
        evidence = _execute_protected_component(database_url)
        migration_current = len(migration.planned) == (
            len(migration.applied) + len(migration.skipped)
        )
        evidence.update(
            {
                "evidence_schema_version": SCHEMA_VERSION,
                "slice": "GB2-CA00-S05",
                "evidence_classification": "PROTECTED_COMPONENT",
                "profile": "test",
                "database_environment": DATABASE_ENV,
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
            **dict(evidence["checks"]),
        }
        evidence["status"] = (
            "PASS" if all(evidence["checks"].values()) else "FAIL"
        )
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "gb2_s05_protected_acceptance_failed"
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected process boundary.
        return _failure(
            "execution_failed",
            p5_s5._redact_detail(str(exc), database_url=database_url),
        )


def _execute_protected_component(database_url: str) -> dict[str, Any]:
    return p5_s5._execute_postgres_smoke(
        database_url,
        verifier=lambda fixture: _verify_canonical_worker(
            fixture, database_url=database_url
        ),
    )


def _verify_canonical_worker(
    fixture: Mapping[str, Any],
    *,
    database_url: str,
) -> dict[str, Any]:
    factory = fixture["factory"]
    tenant_id = str(fixture["tenant_id"])
    execution = dict(fixture["execution"])
    executable_plan = dict(fixture["executable_plan"])
    now = str(fixture["now"])
    interaction_id = str(execution["legacy_interaction_id"])
    worker_id = f"ae-gb2-s05-{uuid4().hex[:12]}"
    dispatcher_id = f"dispatcher-{worker_id}"
    queue_name = f"ae-runtime-gb2-s05-{uuid4().hex[:12]}"
    cleanup_counts: dict[str, int] = {}
    installed = None
    restarted = None
    replayed = None
    try:
        _install_report_binding(
            factory,
            tenant_id=tenant_id,
            executable_plan_id=str(executable_plan["executable_plan_id"]),
        )
        queue = SqlAlchemyRuntimeJobQueue(factory)
        engine = SqlAlchemyMultiStepEngine(factory, queue)
        preparation_worker = P5StepExecutionWorker(
            engine=engine,
            jobs=queue,
            executors=default_p5_executor_registry(
                lambda _context: _compatibility_result(interaction_id)
            ),
            clock=lambda: datetime.fromisoformat(now.replace("Z", "+00:00")),
        )
        first_job = engine.schedule_next(
            tenant_id=tenant_id,
            execution_id=str(execution["agent_execution_id"]),
            now=now,
        )
        first_claim = queue.claim(
            tenant_id=tenant_id,
            worker_id=f"{worker_id}-admission",
            lease_seconds=60,
            now=now,
        )
        if first_job is None or first_claim is None:
            raise RuntimeError("admitted compatibility setup was not claimable")
        dependency = preparation_worker.run_claim(
            tenant_id=tenant_id,
            claim=first_claim,
        )
        second_job = engine.schedule_next(
            tenant_id=tenant_id,
            execution_id=str(execution["agent_execution_id"]),
            now=now,
        )
        if second_job is None:
            raise RuntimeError("deterministic component job was not scheduled")
        pending_job = queue.get(tenant_id, str(second_job["runtime_job_id"]))
        with factory() as session:
            pending_result_count = int(
                session.execute(
                    text(
                        "SELECT count(*) FROM ae_step_result "
                        "WHERE tenant_id = :tenant_id "
                        "AND executable_step_id = :step_id"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "step_id": second_job["executable_step_id"],
                    },
                ).scalar_one()
            )

        runtime_env = {
            DATABASE_ENV: database_url,
            "NEX_AE_AGENT_WORKER_ID": worker_id,
            "NEX_AE_AGENT_DISPATCHER_ID": dispatcher_id,
            "NEX_AE_AGENT_DISPATCHER_QUEUE": queue_name,
            "NEX_AE_AGENT_DISPATCHER_TENANT_SNAPSHOT": "1",
            "NEX_AE_AGENT_DISPATCHER_BATCH_SIZE": "1",
            "NEX_AE_AGENT_DISPATCHER_GLOBAL_ACTIVE_CAP": "1",
            "NEX_AE_AGENT_DISPATCHER_TENANT_ACTIVE_CAP": "1",
            "NEX_AE_AGENT_WORKER_POLL_INTERVAL_SECONDS": "0",
        }
        installed = build_installed_agent_runtime_process(
            "test", environ=runtime_env
        )
        readiness = installed.readiness()
        installed.close()
        installed = None

        restarted = build_installed_agent_runtime_process(
            "test", environ=runtime_env
        )
        restart_readiness = restarted.readiness()
        first_run = restarted.run_once()
        restarted.close()
        restarted = None

        replayed = build_installed_agent_runtime_process(
            "test", environ=runtime_env
        )
        restart_run = replayed.run_once()
        replayed.close()
        replayed = None

        heartbeat = SqlAlchemyWorkerHeartbeatStore(factory).get_heartbeat(
            "nex-ae-api", worker_id
        )
        with factory() as session:
            jobs = tuple(
                session.execute(
                    text(
                        "SELECT runtime_job_id, state FROM ae_runtime_job "
                        "WHERE tenant_id = :tenant_id ORDER BY created_at"
                    ),
                    {"tenant_id": tenant_id},
                ).mappings()
            )
            attempts = tuple(
                session.execute(
                    text(
                        "SELECT runtime_job_id, outcome FROM ae_runtime_job_attempt "
                        "WHERE tenant_id = :tenant_id ORDER BY attempt_no"
                    ),
                    {"tenant_id": tenant_id},
                ).mappings()
            )
        checks = {
            "actual_database_identity": readiness["database"]["database_name"]
            == EXPECTED_DATABASE
            and readiness["database"]["database_user"] == EXPECTED_ROLE,
            "readiness_truthful": readiness["readiness_status"] == "READY"
            and restart_readiness["readiness_status"] == "READY"
            and all(readiness["checks"].values()),
            "normal_admitted_setup": dependency.disposition == "TERMINAL"
            and executable_plan["steps"][1]["executor_kind"]
            == "DETERMINISTIC_REPORT",
            "worker_unavailable_preserved_pending_job": pending_job is not None
            and pending_job["state"] == "QUEUED"
            and int(pending_job["attempt_no"]) == 0
            and pending_result_count == 0,
            "canonical_worker_claimed_assignment": first_run["execution_count"] == 1
            and first_run["succeeded_count"] == 1
            and first_run["failed_count"] == 0,
            "runtime_jobs_settled": len(jobs) == 2
            and all(row["state"] == "DONE" for row in jobs),
            "attempts_exactly_once": len(attempts) == 2
            and all(row["outcome"] == "DONE" for row in attempts)
            and len({row["runtime_job_id"] for row in attempts}) == 2,
            "heartbeat_persisted": heartbeat is not None
            and heartbeat["status"] == "STOPPED"
            and heartbeat["metadata"].get("process_id") == PROCESS_ID,
            "restart_did_not_double_execute": restart_run["execution_count"] == 0
            and len(attempts) == 2,
            "canonical_command_has_no_demo_dependency": (
                installed is None and restarted is None and replayed is None
            ),
            "component_scope_only": True,
        }
        row_counts = {
            "runtime_job": len(jobs),
            "runtime_job_attempt": len(attempts),
            "heartbeat": 1 if heartbeat is not None else 0,
        }
        return {
            "checks": checks,
            "row_counts": row_counts,
            "cleanup_counts": cleanup_counts,
            "process": {
                "process_id": PROCESS_ID,
                "worker_id": worker_id,
                "first_execution_count": first_run["execution_count"],
                "restart_execution_count": restart_run["execution_count"],
            },
        }
    finally:
        if installed is not None:
            installed.close()
        if restarted is not None:
            restarted.close()
        if replayed is not None:
            replayed.close()
        cleanup_counts.update(
            _cleanup_component_rows(
                factory,
                tenant_id=tenant_id,
                worker_id=worker_id,
                queue_name=queue_name,
            )
        )


def _install_report_binding(
    factory: Any,
    *,
    tenant_id: str,
    executable_plan_id: str,
) -> None:
    bindings = json.dumps(
        [
            {
                "target_name": "source_result",
                "binding_type": "COMPILED_STEP_OUTPUT",
                "source_ref": "E1:$",
            }
        ],
        separators=(",", ":"),
        sort_keys=True,
    )
    with factory.begin() as session:
        dialect = session.get_bind().dialect.name
        expression = "CAST(:bindings AS jsonb)" if dialect == "postgresql" else ":bindings"
        session.execute(
            text(
                "UPDATE ae_executable_step SET input_binding_json = "
                f"{expression} WHERE tenant_id = :tenant_id "
                "AND executable_plan_id = :plan_id AND compiled_step_key = 'E2'"
            ),
            {
                "bindings": bindings,
                "tenant_id": tenant_id,
                "plan_id": executable_plan_id,
            },
        )


def _compatibility_result(interaction_id: str) -> dict[str, Any]:
    return {
        "interaction_id": interaction_id,
        "status": "COMPLETED",
        "retrieval": None,
        "cx_generation_id": "gb2-s05-component-generation",
        "generation": {
            "generated_response_ref": {
                "generated_response_id": "gb2-s05-component-response"
            }
        },
        "artifact_refs": [],
    }


def _cleanup_component_rows(
    factory: Any,
    *,
    tenant_id: str,
    worker_id: str,
    queue_name: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    with factory.begin() as session:
        for table in (
            "ae_result_delivery",
            "ae_agent_result",
            "ae_step_result",
            "ae_runtime_job_attempt",
            "ae_runtime_job",
        ):
            counts[table] = int(
                session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
        counts["dispatcher_lease"] = int(
            session.execute(
                text("DELETE FROM ae_rt_dispatch_lease WHERE queue_name = :queue"),
                {"queue": queue_name},
            ).rowcount
            or 0
        )
        counts["heartbeat"] = int(
            session.execute(
                text(
                    "DELETE FROM service_worker_heartbeats "
                    "WHERE service_id = 'nex-ae-api' AND worker_id = :worker_id"
                ),
                {"worker_id": worker_id},
            ).rowcount
            or 0
        )
    with factory() as session:
        counts["component_remaining"] = sum(
            int(
                session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for table in (
                "ae_result_delivery",
                "ae_agent_result",
                "ae_step_result",
                "ae_runtime_job_attempt",
                "ae_runtime_job",
            )
        )
    return counts


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        parsed.scheme.startswith("postgresql")
        and unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "GB2-CA00-S05",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
        "secret_included": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    rows = evidence.get("row_counts") or {}
    cleanup = evidence.get("cleanup_counts") or {}
    return (
        "gb2_ca00_s05_ae_worker="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"classification={evidence.get('evidence_classification', 'none')} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"jobs={rows.get('runtime_job', 0)} "
        f"attempts={rows.get('runtime_job_attempt', 0)} "
        f"remaining={cleanup.get('component_remaining', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run GB2-S05 protected AE Agent Runtime worker acceptance"
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    env = dict(os.environ)
    env.update(load_env_file(ROOT / args.env_file) or {})
    evidence = run_gb2_ca00_s05_ae_agent_runtime_worker(env)
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
