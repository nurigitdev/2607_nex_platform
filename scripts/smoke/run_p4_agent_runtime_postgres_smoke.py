#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
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

from nex_ae_api.agent_execution import (  # noqa: E402
    AgentExecutionAdmissionService,
    AgentExecutionError,
    SqlAlchemyAgentExecutionRepository,
)
from nex_ae_api.agent_identity import (  # noqa: E402
    AgentIdentityRepositoryError,
    SqlAlchemyAgentIdentityRegistry,
)
from nex_ae_api.agent_results import (  # noqa: E402
    AgentResultError,
    SqlAlchemyAgentResultRepository,
    build_agent_result,
)
from nex_ae_api.agent_runtime_foundation import (  # noqa: E402
    AgentRuntimeFoundationError,
    SqlAlchemyAgentRuntimeTraceSource,
)
from nex_ae_api.executable_steps import (  # noqa: E402
    CompatibilityChatRuntime,
    ExecutableStepError,
    SqlAlchemyExecutableStepRepository,
)
from nex_ae_api.runtime_jobs import (  # noqa: E402
    RuntimeJobError,
    SqlAlchemyRuntimeJobQueue,
)
from nex_runtime import (  # noqa: E402
    load_env_file,
    redact_database_url,
    sqlalchemy_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "p4_agent_runtime_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P4_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"


def run_p4_agent_runtime_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P4-S8",
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
        migration_current = (
            bool(migration.planned)
            and migration.planned[-1] == "2006_ae_agent_result"
            and len(migration.planned)
            == len(migration.applied) + len(migration.skipped)
        )
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P4-S8",
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
            evidence["failure_code"] = "p4_agent_runtime_postgres_smoke_failed"
        return evidence
    except (
        AgentExecutionError,
        AgentIdentityRepositoryError,
        AgentResultError,
        AgentRuntimeFoundationError,
        ExecutableStepError,
        MigrationError,
        OSError,
        RuntimeError,
        RuntimeJobError,
        SQLAlchemyError,
        ValueError,
    ) as exc:
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_url=database_url),
        )


def _execute_postgres_smoke(database_url: str) -> dict[str, Any]:
    engine = create_engine(
        sqlalchemy_database_url(database_url), future=True, pool_pre_ping=True
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    token = uuid4().hex
    tenant_id = f"tenant-p4-s8-{token[:12]}"
    principal_id = f"user-p4-s8-{token[:12]}"
    workspace_id = str(uuid4())
    conversation_id = str(uuid4())
    interaction_id = str(uuid4())
    reclaim_interaction_id = str(uuid4())
    trace_id = uuid4().hex
    correlation_id = f"p4-s8:{trace_id}"
    now_dt = datetime.now(UTC).replace(microsecond=0)
    now = _time(now_dt)
    cleanup_counts: dict[str, int] = {}
    row_counts: dict[str, int] = {}
    database = ""
    role = ""
    checks: dict[str, bool] = {}

    identities = SqlAlchemyAgentIdentityRegistry(factory)
    executions = SqlAlchemyAgentExecutionRepository(factory)
    admission = AgentExecutionAdmissionService(
        identities=identities, executions=executions, mode="required"
    )
    jobs = SqlAlchemyRuntimeJobQueue(factory)
    steps = SqlAlchemyExecutableStepRepository(factory)
    runtime = CompatibilityChatRuntime(
        steps=steps,
        jobs=jobs,
        mode="required",
        clock=lambda: now_dt,
    )
    results = SqlAlchemyAgentResultRepository(factory)

    try:
        _seed_workspace_conversation(
            factory,
            tenant_id=tenant_id,
            principal_id=principal_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            now=now,
        )
        admitted = admission.admit_prompt(
            tenant_id=tenant_id,
            principal_id=principal_id,
            profile_ref="urn:nex:agent-profile:ia:default:v1",
            trigger_id=interaction_id,
            interaction_id=interaction_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
        )
        repeated_admission = admission.admit_prompt(
            tenant_id=tenant_id,
            principal_id=principal_id,
            profile_ref="urn:nex:agent-profile:ia:default:v1",
            trigger_id=interaction_id,
            interaction_id=interaction_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
        )
        execution = admitted.execution
        if execution is None:
            raise RuntimeError("required admission did not create AgentExecution")
        step, job = runtime.enqueue_start(execution=execution)
        repeated_step, repeated_job = runtime.enqueue_start(execution=execution)
        claim = jobs.claim(
            tenant_id=tenant_id,
            worker_id="p4-s8-worker-a",
            lease_seconds=30,
            now=now,
        )
        if claim is None or claim.job["runtime_job_id"] != job["runtime_job_id"]:
            raise RuntimeError("START_EXECUTION was not claimed")
        legacy_result = _legacy_result(interaction_id)
        compatibility = runtime.run_start(claim=claim, callback=lambda: legacy_result)
        if compatibility.step is None:
            raise RuntimeError("required compatibility step was not persisted")
        result_id = str(uuid4())
        delivery_id = str(uuid4())
        result = build_agent_result(
            execution=execution,
            step=compatibility.step,
            legacy_result=legacy_result,
            result_id=result_id,
            created_at=now,
            structured_result_contract_ref="contract://p4/chat-result/v1",
            completion_verification_refs=("p4-smoke:legacy-terminal",),
        )
        aggregate = results.persist_with_pending_delivery(
            result=result, delivery_id=delivery_id
        )
        repeated_result = results.persist_with_pending_delivery(
            result=result, delivery_id=delivery_id
        )

        reclaim = admission.admit_prompt(
            tenant_id=tenant_id,
            principal_id=principal_id,
            profile_ref="urn:nex:agent-profile:ia:default:v1",
            trigger_id=reclaim_interaction_id,
            interaction_id=reclaim_interaction_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            correlation_id=f"{correlation_id}:reclaim",
        )
        if reclaim.execution is None:
            raise RuntimeError("reclaim execution was not admitted")
        _, reclaim_job = runtime.enqueue_start(execution=reclaim.execution)
        first_claim = jobs.claim(
            tenant_id=tenant_id,
            worker_id="p4-s8-worker-old",
            lease_seconds=1,
            now=now,
        )
        if first_claim is None:
            raise RuntimeError("reclaim job first lease was not claimed")
        restarted_jobs = SqlAlchemyRuntimeJobQueue(factory)
        second_claim = restarted_jobs.claim(
            tenant_id=tenant_id,
            worker_id="p4-s8-worker-new",
            lease_seconds=30,
            now=_time(now_dt + timedelta(seconds=2)),
        )
        if second_claim is None:
            raise RuntimeError("expired lease was not reclaimed after restart")
        restarted_jobs.cancel(
            tenant_id=tenant_id,
            runtime_job_id=second_claim.job["runtime_job_id"],
            worker_id="p4-s8-worker-new",
            lease_token=second_claim.job["lease_token"],
            now=_time(now_dt + timedelta(seconds=3)),
        )
        attempts = restarted_jobs.list_attempts(
            tenant_id, reclaim_job["runtime_job_id"]
        )

        restarted_trace = SqlAlchemyAgentRuntimeTraceSource(factory).get(
            tenant_id=tenant_id,
            agent_execution_id=execution["agent_execution_id"],
        )
        if restarted_trace is None:
            raise RuntimeError("restart trace projection was not restored")

        with engine.connect() as connection:
            database, role = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            row_counts = _row_counts(connection, tenant_id)
            serialized_runtime = json.dumps(
                {
                    "job": repeated_job,
                    "step": repeated_step,
                    "result": repeated_result.result,
                    "delivery": repeated_result.delivery,
                    "trace": restarted_trace,
                },
                ensure_ascii=False,
                sort_keys=True,
            )

        checks = {
            "actual_database_identity": database == EXPECTED_DATABASE
            and role == EXPECTED_ROLE,
            "canonical_chain_written": row_counts == {
                "identity": 1,
                "assignment": 1,
                "conversation": 1,
                "execution": 2,
                "job": 2,
                "attempt": 3,
                "step": 2,
                "result": 1,
                "delivery": 1,
            },
            "admission_idempotent": repeated_admission.execution == execution,
            "start_enqueue_idempotent": repeated_step == step
            and repeated_job == job,
            "result_idempotent": repeated_result == aggregate,
            "success_waits_for_ack": aggregate.execution["state"] == "RUNNING"
            and aggregate.execution["phase"] == "RESULT_PUBLISH"
            and aggregate.delivery["state"] == "PENDING",
            "restart_trace_restored": restarted_trace["identities"]
            ["agent_result_id"]
            == result_id
            and restarted_trace["identities"]["result_delivery_id"]
            == delivery_id,
            "lease_reclaimed_after_restart": [item["outcome"] for item in attempts]
            == ["LEASE_EXPIRED", "CANCELLED"],
            "project_neutral": restarted_trace["boundaries"]["project_resolved"]
            is False,
            "no_wc_delivery": "WC_WORK_RESULT" not in serialized_runtime,
            "runtime_metadata_private": "P4 private smoke prompt" not in serialized_runtime
            and "P4 private generated response" not in serialized_runtime
            and set(restarted_trace["privacy"].values()) == {False},
            "no_false_succeeded": restarted_trace["boundaries"]
            ["succeeded_without_ack"]
            is False,
        }
    finally:
        try:
            cleanup_counts = _cleanup(factory, tenant_id, workspace_id)
        finally:
            engine.dispose()

    checks["cleanup_complete"] = cleanup_counts.get("remaining", -1) == 0
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "execution_state": "EXECUTED",
        "actual_postgres": True,
        "database": database,
        "role": role,
        "provider_mode": "deterministic-mock",
        "checks": checks,
        "row_counts": row_counts,
        "cleanup_counts": cleanup_counts,
    }


def _seed_workspace_conversation(
    factory,
    *,
    tenant_id: str,
    principal_id: str,
    workspace_id: str,
    conversation_id: str,
    trace_id: str,
    now: str,
) -> None:
    with factory.begin() as session:
        session.execute(
            text("""
                INSERT INTO ae_workspaces (
                    workspace_id, tenant_id, owner_user_id, title, locale,
                    chat_document_id, runtime_defaults, activity_count,
                    trace_id, request_id, created_at, updated_at
                ) VALUES (
                    :workspace_id, :tenant_id, :principal_id,
                    'P4-S8 PostgreSQL Smoke', 'ko-KR', :conversation_id,
                    CAST('{}' AS JSONB), 0, :trace_id, :request_id, :now, :now
                )
            """),
            {
                "workspace_id": workspace_id,
                "tenant_id": tenant_id,
                "principal_id": principal_id,
                "conversation_id": conversation_id,
                "trace_id": trace_id,
                "request_id": f"request-{trace_id}",
                "now": now,
            },
        )
        session.execute(
            text("""
                INSERT INTO ae_conversations (
                    conversation_id, tenant_id, workspace_id, owner_user_id,
                    title, status, next_journal_seq, created_at, updated_at,
                    version
                ) VALUES (
                    :conversation_id, :tenant_id, :workspace_id, :principal_id,
                    'P4-S8 Conversation', 'ACTIVE', 1, :now, :now, 1
                )
            """),
            {
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "principal_id": principal_id,
                "now": now,
            },
        )


def _legacy_result(interaction_id: str) -> dict[str, Any]:
    return {
        "interaction_id": interaction_id,
        "status": "COMPLETED",
        "retrieval": {
            "cx_retrieval_package_id": "p4-retrieval-package",
            "cx_package_hash": "sha256:p4-retrieval-package",
            "quality_warnings": {"recommended_action": "proceed"},
        },
        "cx_generation_id": "p4-cx-generation",
        "generation": {
            "async_generation": {"job_id": "p4-cx-job"},
            "generated_response_ref": {
                "generated_response_id": "p4-generated-response"
            },
            "grounded_response_quality": {
                "boundary_status": "PASS",
                "issue_count": 0,
            },
        },
        "artifact_refs": [],
    }


def _row_counts(connection, tenant_id: str) -> dict[str, int]:
    tables = {
        "identity": "ae_agent_identity",
        "assignment": "ae_ia_principal_assignment",
        "conversation": "ae_conversations",
        "execution": "ae_agent_execution",
        "job": "ae_runtime_job",
        "attempt": "ae_runtime_job_attempt",
        "step": "ae_executable_step",
        "result": "ae_agent_result",
        "delivery": "ae_result_delivery",
    }
    return {
        key: int(
            connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )
        for key, table in tables.items()
    }


def _cleanup(factory, tenant_id: str, workspace_id: str) -> dict[str, int]:
    tables = (
        "ae_result_delivery",
        "ae_agent_result",
        "ae_runtime_job_attempt",
        "ae_runtime_job",
        "ae_executable_step",
        "ae_agent_execution",
        "ae_conversation_events",
        "ae_conversation_messages",
        "ae_conversations",
        "ae_ia_principal_assignment",
        "ae_agent_identity",
    )
    counts: dict[str, int] = {}
    with factory.begin() as session:
        for table in tables:
            counts[table] = int(
                session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
        counts["ae_workspace_activities"] = int(
            session.execute(
                text(
                    "DELETE FROM ae_workspace_activities "
                    "WHERE workspace_id = :workspace_id"
                ),
                {"workspace_id": workspace_id},
            ).rowcount
            or 0
        )
        counts["ae_workspaces"] = int(
            session.execute(
                text("DELETE FROM ae_workspaces WHERE workspace_id = :workspace_id"),
                {"workspace_id": workspace_id},
            ).rowcount
            or 0
        )
    with factory() as session:
        counts["remaining"] = sum(
            int(
                session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for table in tables
        ) + int(
            session.execute(
                text("SELECT count(*) FROM ae_workspaces WHERE workspace_id = :id"),
                {"id": workspace_id},
            ).scalar_one()
        )
    return counts


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


def _redact_detail(detail: str, *, database_url: str) -> str:
    redacted = detail.replace(database_url, redact_database_url(database_url))
    password = urlsplit(database_url).password
    return redacted.replace(unquote(password), "***") if password else redacted


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P4-S8",
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
        "p4_agent_runtime_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"execution={str(evidence.get('execution_state') or 'not-run').lower()} "
        f"database={evidence.get('database', 'not-run')} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"chain_rows={rows.get('execution', 0)}/{rows.get('job', 0)}/"
        f"{rows.get('step', 0)}/{rows.get('result', 0)}/"
        f"{rows.get('delivery', 0)} "
        f"cleanup={(evidence.get('cleanup_counts') or {}).get('remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p4_agent_runtime_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
