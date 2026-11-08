#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
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

from nex_ae_api.agent_context import (
    AgentContextError,
    SqlAlchemyAgentContextRepository,
    TrustedContextResolution,
    build_agent_context,
    runtime_policy_ref_from_compatibility_policy,
)
from nex_ae_api.agent_execution import (
    AgentExecutionAdmissionService,
    AgentExecutionError,
    SqlAlchemyAgentExecutionRepository,
)
from nex_ae_api.agent_identity import (
    AgentIdentityRepositoryError,
    SqlAlchemyAgentIdentityRegistry,
)
from nex_ae_api.agent_plans import (
    AgentPlanError,
    SqlAlchemyAgentPlanRepository,
    build_deterministic_agent_plan,
)
from nex_ae_api.intent_policy import resolve_intent_decision
from nex_ae_api.planning_capabilities import (
    CapabilitySnapshotError,
    SqlAlchemyCapabilitySnapshotRepository,
    build_capability_snapshot,
)
from nex_ae_api.runtime_policy import RuntimePolicyError, resolve_runtime_policy
from nex_ae_api.work_intent import (
    SqlAlchemyWorkIntentRepository,
    WorkIntentError,
    build_work_intent_from_decision,
)
from nex_runtime import (
    load_env_file,
    redact_database_url,
    sqlalchemy_database_url,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p5_s3_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P5_S3_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2103_ae_capability_plan_validation"
PROFILES = (
    ("GENERAL_ANSWER", "DIRECT", 1, None),
    ("GROUNDED_ANSWER", "KNOWN_TEMPLATE", 2, "INTERACTIVE_RESPONSE"),
    ("DOCUMENT_SUMMARY", "KNOWN_TEMPLATE", 2, "INTERACTIVE_RESPONSE"),
    ("DOCUMENT_GENERATION", "KNOWN_TEMPLATE", 2, "ARTIFACT"),
)


class _ReferenceResolver:
    def __init__(self, resolution: TrustedContextResolution) -> None:
        self._resolution = resolution
        self.call_count = 0

    def resolve(self, _request) -> TrustedContextResolution:
        self.call_count += 1
        return self._resolution


def run_p5_s3_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P5-S3",
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
            REQUIRED_MIGRATION in migration.planned
            and len(migration.planned)
            == len(migration.applied) + len(migration.skipped)
        )
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P5-S3",
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
            evidence["failure_code"] = "p5_s3_postgres_smoke_failed"
        return evidence
    except (
        AgentContextError,
        AgentExecutionError,
        AgentIdentityRepositoryError,
        AgentPlanError,
        CapabilitySnapshotError,
        MigrationError,
        OSError,
        RuntimeError,
        RuntimePolicyError,
        SQLAlchemyError,
        ValueError,
        WorkIntentError,
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
    tenant_id = f"tenant-p5-s3-{token[:12]}"
    principal_id = f"user-p5-s3-{token[:12]}"
    workspace_id = str(uuid4())
    conversation_id = str(uuid4())
    trace_id = uuid4().hex
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    database = ""
    role = ""
    cleanup_counts: dict[str, int] = {}

    identities = SqlAlchemyAgentIdentityRegistry(factory)
    executions = SqlAlchemyAgentExecutionRepository(factory)
    admission = AgentExecutionAdmissionService(
        identities=identities, executions=executions, mode="required"
    )
    intents = SqlAlchemyWorkIntentRepository(factory)
    contexts = SqlAlchemyAgentContextRepository(factory)
    snapshots = SqlAlchemyCapabilitySnapshotRepository(factory)
    plans = SqlAlchemyAgentPlanRepository(factory)

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
        snapshot = build_capability_snapshot(
            tenant_id=tenant_id,
            capability_snapshot_id=str(uuid4()),
            snapshot_version=1,
            created_at=now,
        )
        saved_snapshot = snapshots.save(snapshot)
        repeated_snapshot = snapshots.save(snapshot)
        profile_results: dict[str, dict[str, Any]] = {}
        resolver_calls = 0
        private_markers: list[str] = []

        for mode, expected_kind, expected_steps, expected_report in PROFILES:
            interaction_id = str(uuid4())
            marker = f"private-p5-s3-{mode.lower()}-{token}"
            private_markers.append(marker)
            admitted = admission.admit_prompt(
                tenant_id=tenant_id,
                principal_id=principal_id,
                profile_ref="urn:nex:agent-profile:ia:default:v1",
                trigger_id=interaction_id,
                interaction_id=interaction_id,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                correlation_id=f"p5-s3:{trace_id}:{mode.lower()}",
            )
            execution = admitted.execution
            if execution is None:
                raise RuntimeError("required admission did not create AgentExecution")
            decision = resolve_intent_decision(
                {
                    "user_message": marker,
                    "generation": {"execution_mode": mode},
                }
            )
            work_intent = build_work_intent_from_decision(
                execution_id=execution["agent_execution_id"],
                source_ref=f"AE:INTERACTION:{interaction_id}",
                actor_ref=f"OA:SUBJECT:{principal_id}",
                received_at=now,
                intent_decision=decision,
                input_context_hash=semantic_sha256_hash_ref(
                    {"tenant_id": tenant_id, "interaction_id": interaction_id}
                ),
            )
            intents.save(tenant_id=tenant_id, work_intent=work_intent, created_at=now)
            resolver = _ReferenceResolver(
                TrustedContextResolution(
                    project_ref=None,
                    authority_ref="OA:EAC:p5-s3-smoke",
                    resolved_entities=(),
                    retrieval_refs=(),
                    evidence_refs=(),
                    conflicts=(),
                    degradations=(),
                    context_manifest=(
                        {
                            "kind": "INTERACTION_REF",
                            "source_ref": f"AE:INTERACTION:{interaction_id}",
                            "source_version": "1",
                            "content_hash": semantic_sha256_hash_ref(
                                {"interaction_id": interaction_id}
                            ),
                            "as_of": now,
                        },
                    ),
                    budget_tokens=4096,
                    estimated_used_tokens=128,
                )
            )
            generation_request = {"execution_mode": mode}
            if mode == "DOCUMENT_GENERATION":
                generation_request.update(
                    {"template_id": "report", "template_version": "v1"}
                )
            context = build_agent_context(
                tenant_id=tenant_id,
                principal_id=principal_id,
                agent_id=execution["agent_id"],
                execution_id=execution["agent_execution_id"],
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                interaction_id=interaction_id,
                work_intent=work_intent,
                runtime_policy_ref=runtime_policy_ref_from_compatibility_policy(
                    resolve_runtime_policy(
                        {
                            "user_message": marker,
                            "generation": generation_request,
                        }
                    )
                ),
                resolver=resolver,
                built_at=now,
            )
            contexts.save(tenant_id=tenant_id, agent_context=context)
            plan = build_deterministic_agent_plan(
                work_intent=work_intent,
                agent_context=context,
                capability_snapshot=saved_snapshot,
                agent_plan_id=str(uuid4()),
            )
            saved_plan = plans.save(
                tenant_id=tenant_id, agent_plan=plan, created_at=now
            )
            repeated_plan = plans.save(
                tenant_id=tenant_id, agent_plan=plan, created_at=now
            )
            restarted = SqlAlchemyAgentPlanRepository(factory).get(
                tenant_id=tenant_id, agent_plan_id=plan["agent_plan_id"]
            )
            resolver_calls += resolver.call_count
            profile_results[mode] = {
                "expected_kind": expected_kind,
                "actual_kind": saved_plan["plan_kind"],
                "expected_steps": expected_steps,
                "actual_steps": len(saved_plan["steps"]),
                "expected_report": expected_report,
                "actual_report": (
                    saved_plan["steps"][-1]["report"]["report_kind"]
                    if saved_plan["steps"][-1]["report"] is not None
                    else None
                ),
                "idempotent_restart": saved_plan == repeated_plan == restarted,
            }

        restarted_snapshot = SqlAlchemyCapabilitySnapshotRepository(factory).get(
            tenant_id=tenant_id,
            capability_snapshot_id=snapshot["capability_snapshot_id"],
        )
        with engine.connect() as connection:
            database, role = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            snapshot_count = _tenant_count(
                connection, "ae_capability_snapshot", tenant_id
            )
            plan_count = _tenant_count(connection, "ae_agent_plan", tenant_id)
        serialized = json.dumps(profile_results, ensure_ascii=False, sort_keys=True)
        checks = {
            "actual_database_identity": database == EXPECTED_DATABASE
            and role == EXPECTED_ROLE,
            "snapshot_idempotent_restart": saved_snapshot
            == repeated_snapshot
            == restarted_snapshot,
            "exact_snapshot_version": saved_snapshot["snapshot_version"] == 1,
            "all_deterministic_profiles": all(
                result["expected_kind"] == result["actual_kind"]
                and result["expected_steps"] == result["actual_steps"]
                and result["expected_report"] == result["actual_report"]
                for result in profile_results.values()
            )
            and len(profile_results) == len(PROFILES),
            "plans_idempotent_restart": all(
                result["idempotent_restart"] for result in profile_results.values()
            ),
            "trusted_resolver_once": resolver_calls == len(PROFILES),
            "durable_row_counts": snapshot_count == 1
            and plan_count == len(PROFILES),
            "private_prompt_absent": not any(
                marker in serialized for marker in private_markers
            ),
        }
    finally:
        try:
            cleanup_counts = _cleanup(
                factory, tenant_id=tenant_id, workspace_id=workspace_id
            )
        finally:
            engine.dispose()
    checks["cleanup_complete"] = cleanup_counts.get("remaining", -1) == 0
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "execution_state": "EXECUTED",
        "actual_postgres": True,
        "database": database,
        "role": role,
        "provider_mode": "not-required",
        "checks": checks,
        "profiles": profile_results,
        "row_counts": {
            "capability_snapshot": snapshot_count,
            "agent_plan": plan_count,
        },
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
                    'P5-S3 PostgreSQL Smoke', 'ko-KR', :conversation_id,
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
                    title, status, next_journal_seq, created_at, updated_at, version
                ) VALUES (
                    :conversation_id, :tenant_id, :workspace_id, :principal_id,
                    'P5-S3 Conversation', 'ACTIVE', 1, :now, :now, 1
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


def _tenant_count(connection, table: str, tenant_id: str) -> int:
    return int(
        connection.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).scalar_one()
    )


def _cleanup(factory, *, tenant_id: str, workspace_id: str) -> dict[str, int]:
    tables = (
        "ae_plan_validation",
        "ae_agent_plan",
        "ae_capability_snapshot",
        "ae_agent_context",
        "ae_work_intent",
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
        "slice": "P5-S3",
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
        "p5_s3_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"execution={str(evidence.get('execution_state') or 'not-run').lower()} "
        f"database={evidence.get('database', 'not-run')} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"snapshots={rows.get('capability_snapshot', 0)} "
        f"plans={rows.get('agent_plan', 0)} "
        f"cleanup={(evidence.get('cleanup_counts') or {}).get('remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p5_s3_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
