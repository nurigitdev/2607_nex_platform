#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
):
    sys.path.insert(0, str(path))

from nex_ae_api.agent_runtime_worker import (
    AE_AGENT_RUNTIME_WORKER_TYPE,
    LOCAL_SKILL_EXECUTOR,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
    AgentRuntimeAssignment,
    AgentRuntimeWorkerConfig,
    AgentRuntimeWorkerError,
    AgentRuntimeWorkerLifecycle,
    build_agent_runtime_worker_profile,
    run_bounded_agent_runtime_worker,
)
from nex_ae_api.runtime_jobs import RuntimeJobError, SqlAlchemyRuntimeJobQueue
from nex_runtime import (
    SqlAlchemyWorkerHeartbeatStore,
    WorkerHeartbeatEmitter,
    load_env_file,
    redact_database_url,
    sqlalchemy_database_url,
)
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p6_s0_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P6_S0_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATIONS = frozenset(
    {
        "0112_service_worker_heartbeat_foundation",
        "2004_ae_runtime_job",
        "2106_ae_step_result",
    }
)


class _PostgresSmokeAssignmentSource:
    def __init__(self, queue: SqlAlchemyRuntimeJobQueue, tenant_id: str) -> None:
        self._queue = queue
        self._tenant_id = tenant_id

    def claim_next(
        self,
        *,
        worker_id: str,
        supported_executor_kinds: Sequence[str],
        supported_backend_profiles: Sequence[str],
        lease_seconds: int,
        observed_at: str,
    ) -> AgentRuntimeAssignment | None:
        if LOCAL_SKILL_EXECUTOR not in supported_executor_kinds:
            raise RuntimeError("P6-S0 smoke executor capability is missing")
        if NSL_V01_PROCESS_ISOLATED_BACKEND not in supported_backend_profiles:
            raise RuntimeError("P6-S0 smoke backend capability is missing")
        claim = self._queue.claim(
            tenant_id=self._tenant_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            now=observed_at,
        )
        if claim is None:
            return None
        return AgentRuntimeAssignment(
            tenant_id=self._tenant_id,
            executor_kind=LOCAL_SKILL_EXECUTOR,
            backend_profile=NSL_V01_PROCESS_ISOLATED_BACKEND,
            claim=claim,
        )


def run_p6_s0_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-S0",
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
        evidence = _execute_postgres_smoke(database_url)
        migration_current = REQUIRED_MIGRATIONS.issubset(set(migration.planned)) and (
            len(migration.planned) == len(migration.applied) + len(migration.skipped)
        )
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P6-S0",
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
        evidence["status"] = (
            "PASS" if all(evidence["checks"].values()) else "FAIL"
        )
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "p6_s0_postgres_smoke_failed"
        return evidence
    except (
        AgentRuntimeWorkerError,
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


def _execute_postgres_smoke(database_url: str) -> dict[str, Any]:
    engine = create_engine(
        sqlalchemy_database_url(database_url), future=True, pool_pre_ping=True
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    token = uuid4().hex
    tenant_id = f"tenant-p6-s0-{token[:12]}"
    principal_id = f"user-p6-s0-{token[:12]}"
    worker_id = f"ae-p6-s0-{token[:12]}"
    agent_id = str(uuid4())
    execution_id = str(uuid4())
    trigger_id = str(uuid4())
    runtime_job_id = str(uuid4())
    now = _utc_now()
    queue = SqlAlchemyRuntimeJobQueue(factory)
    heartbeat_store = SqlAlchemyWorkerHeartbeatStore(factory)
    profile = build_agent_runtime_worker_profile(
        worker_id=worker_id,
        declared_at=now,
    )
    config = AgentRuntimeWorkerConfig(
        mode="enabled",
        profile=profile,
        lease_seconds=60,
        poll_interval_seconds=0,
        heartbeat_stale_after_seconds=60,
    )
    cleanup_counts: dict[str, int] = {}
    database = ""
    role = ""

    try:
        with engine.begin() as connection:
            database = str(connection.execute(text("SELECT current_database()" )).scalar_one())
            role = str(connection.execute(text("SELECT current_user" )).scalar_one())
            connection.execute(
                text(
                    """
                    INSERT INTO ae_agent_identity (
                        tenant_id, agent_id, agent_type, profile_ref, status,
                        project_id, created_at, version
                    ) VALUES (
                        :tenant_id, :agent_id, 'IA', :profile_ref, 'ACTIVE',
                        NULL, :now, 1
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "profile_ref": "urn:nex:agent-profile:ia:p6-s0-smoke",
                    "now": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO ae_agent_execution (
                        tenant_id, agent_execution_id, agent_id, agent_type,
                        principal_id, trigger_id, source_type, source_ref,
                        project_id, workspace_id, conversation_id,
                        legacy_interaction_id, state, phase, version, result_id,
                        correlation_id, causation_id, received_at, created_at,
                        updated_at
                    ) VALUES (
                        :tenant_id, :execution_id, :agent_id, 'IA',
                        :principal_id, :trigger_id, 'PROMPT', :source_ref,
                        NULL, NULL, NULL, NULL, 'QUEUED', 'STEP_EXECUTION', 1,
                        NULL, :correlation_id, NULL, :now, :now, :now
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "execution_id": execution_id,
                    "agent_id": agent_id,
                    "principal_id": principal_id,
                    "trigger_id": trigger_id,
                    "source_ref": f"AE:P6-S0:SMOKE:{trigger_id}",
                    "correlation_id": f"p6-s0:{token}",
                    "now": now,
                },
            )

        queue.enqueue_unique(
            tenant_id=tenant_id,
            runtime_job_id=runtime_job_id,
            job_type="START_EXECUTION",
            execution_id=execution_id,
            dedup_key=f"p6-s0:{execution_id}",
            run_after=now,
            correlation_id=f"p6-s0:{token}",
            now=now,
            payload={"fixture_ref": f"AE:P6-S0:{runtime_job_id}"},
        )

        first_lifecycle = _lifecycle(
            profile=profile,
            store=heartbeat_store,
            started_at=now,
        )

        def complete_assignment(assignment: AgentRuntimeAssignment) -> dict[str, Any]:
            completed = queue.complete(
                tenant_id=assignment.tenant_id,
                runtime_job_id=assignment.runtime_job_id,
                worker_id=worker_id,
                lease_token=str(assignment.claim.job["lease_token"]),
                now=_utc_now(),
            )
            return {"runtime_job_state": completed["state"]}

        first_run = run_bounded_agent_runtime_worker(
            config=config,
            assignment_source=_PostgresSmokeAssignmentSource(queue, tenant_id),
            handler=complete_assignment,
            lifecycle=first_lifecycle,
            available_executor_kinds=(LOCAL_SKILL_EXECUTOR,),
            available_backend_profiles=(NSL_V01_PROCESS_ISOLATED_BACKEND,),
            max_cycles=1,
        )
        completed_job = queue.get(tenant_id, runtime_job_id)
        attempts = queue.list_attempts(tenant_id, runtime_job_id)
        first_heartbeat = heartbeat_store.get_heartbeat("nex-ae-api", worker_id)

        restarted_at = _utc_now()
        second_lifecycle = _lifecycle(
            profile=profile,
            store=heartbeat_store,
            started_at=restarted_at,
        )
        second_run = run_bounded_agent_runtime_worker(
            config=config,
            assignment_source=_PostgresSmokeAssignmentSource(queue, tenant_id),
            handler=lambda _assignment: (_ for _ in ()).throw(
                RuntimeError("completed RuntimeJob must not be executed again")
            ),
            lifecycle=second_lifecycle,
            available_executor_kinds=(LOCAL_SKILL_EXECUTOR,),
            available_backend_profiles=(NSL_V01_PROCESS_ISOLATED_BACKEND,),
            max_cycles=1,
        )
        restarted_heartbeat = heartbeat_store.get_heartbeat("nex-ae-api", worker_id)

        checks = {
            "target_identity": database == EXPECTED_DATABASE and role == EXPECTED_ROLE,
            "runtime_job_completed": completed_job is not None
            and completed_job["state"] == "DONE",
            "attempt_ledger_completed": len(attempts) == 1
            and attempts[0]["outcome"] == "DONE",
            "bounded_worker_executed_once": first_run["claimed_count"] == 1
            and first_run["succeeded_count"] == 1,
            "lifecycle_heartbeat_persisted": first_heartbeat is not None
            and first_heartbeat["status"] == "STOPPED",
            "profile_metadata_persisted": first_heartbeat is not None
            and first_heartbeat["metadata"].get("capability_profile_hash")
            == profile.profile_hash,
            "restart_is_idempotent": second_run["claimed_count"] == 0
            and second_run["idle_cycle_count"] == 1,
            "restart_heartbeat_refreshed": restarted_heartbeat is not None
            and restarted_heartbeat["status"] == "STOPPED"
            and restarted_heartbeat["started_at"] == restarted_at,
            "content_excluded": first_run["content_included"] is False,
        }
        row_counts = {
            "runtime_job": 1 if completed_job is not None else 0,
            "runtime_job_attempt": len(attempts),
            "heartbeat": 1 if restarted_heartbeat is not None else 0,
        }
    finally:
        with engine.begin() as connection:
            cleanup_counts["attempts"] = int(
                connection.execute(
                    text("DELETE FROM ae_runtime_job_attempt WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
            cleanup_counts["jobs"] = int(
                connection.execute(
                    text("DELETE FROM ae_runtime_job WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
            cleanup_counts["executions"] = int(
                connection.execute(
                    text("DELETE FROM ae_agent_execution WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
            cleanup_counts["identities"] = int(
                connection.execute(
                    text("DELETE FROM ae_agent_identity WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
            cleanup_counts["heartbeats"] = int(
                connection.execute(
                    text(
                        "DELETE FROM service_worker_heartbeats "
                        "WHERE service_id = 'nex-ae-api' AND worker_id = :worker_id"
                    ),
                    {"worker_id": worker_id},
                ).rowcount
                or 0
            )
            cleanup_counts["remaining"] = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM ae_runtime_job "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
        engine.dispose()

    checks["zero_residue"] = cleanup_counts["remaining"] == 0
    return {
        "status": "PASS",
        "actual_postgres": True,
        "database": database,
        "role": role,
        "checks": checks,
        "row_counts": row_counts,
        "cleanup_counts": cleanup_counts,
        "worker": {
            "worker_id": worker_id,
            "profile_hash": profile.profile_hash,
            "first_stop_reason": first_run["stop_reason"],
            "restart_stop_reason": second_run["stop_reason"],
        },
    }


def _lifecycle(
    *,
    profile: Any,
    store: SqlAlchemyWorkerHeartbeatStore,
    started_at: str,
) -> AgentRuntimeWorkerLifecycle:
    emitter = WorkerHeartbeatEmitter(
        service_id="nex-ae-api",
        worker_id=profile.worker_id,
        worker_type=AE_AGENT_RUNTIME_WORKER_TYPE,
        store=store,
        started_at=started_at,
    )
    return AgentRuntimeWorkerLifecycle(profile=profile, emitter=emitter, store=store)


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        parsed.scheme.startswith("postgresql")
        and unquote(parsed.username or "") == EXPECTED_ROLE
        and parsed.path.removeprefix("/") == EXPECTED_DATABASE
    )


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6-S0",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def _redact_detail(detail: str, *, database_url: str) -> str:
    redacted = detail.replace(database_url, redact_database_url(database_url))
    password = urlsplit(database_url).password
    return redacted.replace(unquote(password), "***") if password else redacted


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status", "FAIL")).lower()
    checks = evidence.get("checks") if isinstance(evidence.get("checks"), Mapping) else {}
    passed = sum(value is True for value in checks.values())
    rows = evidence.get("row_counts") if isinstance(evidence.get("row_counts"), Mapping) else {}
    cleanup = evidence.get("cleanup_counts") if isinstance(evidence.get("cleanup_counts"), Mapping) else {}
    return (
        f"p6_s0_postgres={status} actual_postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"checks={passed}/{len(checks)} jobs={rows.get('runtime_job', 0)} "
        f"attempts={rows.get('runtime_job_attempt', 0)} "
        f"heartbeats={rows.get('heartbeat', 0)} remaining={cleanup.get('remaining', 0)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run protected P6-S0 PostgreSQL smoke")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()
    env = dict(os.environ)
    env.update(load_env_file(Path(args.env_file)) or {})
    evidence = run_p6_s0_postgres_smoke(env)
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    if evidence["status"] == "SKIPPED":
        return 0
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
