#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import replace
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
from nex_ae_api.intent_policy import resolve_intent_decision
from nex_ae_api.runtime_policy import resolve_runtime_policy
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

SCHEMA_VERSION = "p5_s2_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P5_S2_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2102_ae_agent_context"


class _ReferenceResolver:
    def __init__(self, resolution: TrustedContextResolution) -> None:
        self._resolution = resolution
        self.call_count = 0

    def resolve(self, _request) -> TrustedContextResolution:
        self.call_count += 1
        return self._resolution


def run_p5_s2_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P5-S2",
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
                "slice": "P5-S2",
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
            evidence["failure_code"] = "p5_s2_postgres_smoke_failed"
        return evidence
    except (
        AgentContextError,
        AgentExecutionError,
        AgentIdentityRepositoryError,
        MigrationError,
        OSError,
        RuntimeError,
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
    tenant_id = f"tenant-p5-s2-{token[:12]}"
    principal_id = f"user-p5-s2-{token[:12]}"
    workspace_id = str(uuid4())
    conversation_id = str(uuid4())
    interaction_id = str(uuid4())
    trace_id = uuid4().hex
    correlation_id = f"p5-s2:{trace_id}"
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
        execution = admitted.execution
        if execution is None:
            raise RuntimeError("required admission did not create AgentExecution")
        decision = resolve_intent_decision(
            {
                "user_message": "P5-S2 private PostgreSQL context prompt",
                "generation": {"execution_mode": "GROUNDED_ANSWER"},
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
        intents.save(
            tenant_id=tenant_id, work_intent=work_intent, created_at=now
        )
        resolution = TrustedContextResolution(
            project_ref=None,
            authority_ref="OA:EAC:p5-s2-smoke",
            resolved_entities=(),
            retrieval_refs=(
                {
                    "system": "CX",
                    "resource_type": "RETRIEVAL_PACKAGE",
                    "resource_id": f"retrieval-{token}",
                    "version": "1",
                },
            ),
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
        resolver = _ReferenceResolver(resolution)
        policy_ref = runtime_policy_ref_from_compatibility_policy(
            resolve_runtime_policy(
                {
                    "user_message": "P5-S2 policy-only private input",
                    "generation": {"execution_mode": "GROUNDED_ANSWER"},
                }
            )
        )
        build_args = {
            "tenant_id": tenant_id,
            "principal_id": principal_id,
            "agent_id": execution["agent_id"],
            "execution_id": execution["agent_execution_id"],
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "interaction_id": interaction_id,
            "work_intent": work_intent,
            "runtime_policy_ref": policy_ref,
            "resolver": resolver,
            "built_at": now,
        }
        first = build_agent_context(**build_args)
        saved = contexts.save(tenant_id=tenant_id, agent_context=first)
        repeated = contexts.save(tenant_id=tenant_id, agent_context=first)
        second_resolver = _ReferenceResolver(
            replace(resolution, degradations=("optional evidence unavailable",))
        )
        second = build_agent_context(
            **{
                **build_args,
                "resolver": second_resolver,
                "context_generation": 2,
            }
        )
        saved_second = contexts.save(tenant_id=tenant_id, agent_context=second)
        restarted_first = SqlAlchemyAgentContextRepository(factory).get(
            tenant_id=tenant_id, context_id=first["context_id"]
        )
        restarted_second = SqlAlchemyAgentContextRepository(factory).get(
            tenant_id=tenant_id, context_id=second["context_id"]
        )

        with engine.connect() as connection:
            database, role = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            context_count = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM ae_agent_context "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
        serialized = json.dumps(
            [saved, saved_second], ensure_ascii=False, sort_keys=True
        )
        checks = {
            "actual_database_identity": database == EXPECTED_DATABASE
            and role == EXPECTED_ROLE,
            "trusted_resolver_once_per_generation": resolver.call_count == 1
            and second_resolver.call_count == 1,
            "context_idempotent": saved == repeated == restarted_first,
            "generation_chain_restart_safe": saved_second == restarted_second
            and saved_second["context_generation"] == 2
            and context_count == 2,
            "exact_work_intent_lineage": saved["work_intent_ref"]["id"]
            == work_intent["work_intent_id"]
            and saved["work_intent_ref"]["hash"] == work_intent["intent_hash"],
            "context_private": "private PostgreSQL context prompt" not in serialized
            and "policy-only private input" not in serialized,
            "semantic_hash_prefixed": saved["context_hash"].startswith("sha256:"),
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
        "row_counts": {"agent_context": context_count},
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
                    'P5-S2 PostgreSQL Smoke', 'ko-KR', :conversation_id,
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
                    'P5-S2 Conversation', 'ACTIVE', 1, :now, :now, 1
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


def _cleanup(factory, *, tenant_id: str, workspace_id: str) -> dict[str, int]:
    tables = (
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
        "slice": "P5-S2",
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
        "p5_s2_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"execution={str(evidence.get('execution_state') or 'not-run').lower()} "
        f"database={evidence.get('database', 'not-run')} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"contexts={rows.get('agent_context', 0)} "
        f"cleanup={(evidence.get('cleanup_counts') or {}).get('remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p5_s2_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
