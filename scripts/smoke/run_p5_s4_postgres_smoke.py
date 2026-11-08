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
    ROOT / "scripts" / "smoke",
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
from nex_ae_api.plan_validation import (
    PlanValidationError,
    SqlAlchemyPlanValidationRepository,
    runtime_outcome_for_status,
    validate_agent_plan,
)
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
from run_p5_s3_postgres_smoke import (
    _cleanup,
    _ReferenceResolver,
    _seed_workspace_conversation,
)

SCHEMA_VERSION = "p5_s4_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P5_S4_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2103_ae_capability_plan_validation"


def run_p5_s4_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P5-S4",
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
                "slice": "P5-S4",
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
            evidence["failure_code"] = "p5_s4_postgres_smoke_failed"
        return evidence
    except (
        AgentContextError,
        AgentExecutionError,
        AgentIdentityRepositoryError,
        AgentPlanError,
        CapabilitySnapshotError,
        MigrationError,
        OSError,
        PlanValidationError,
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
    tenant_id = f"tenant-p5-s4-{token[:12]}"
    principal_id = f"user-p5-s4-{token[:12]}"
    workspace_id = str(uuid4())
    conversation_id = str(uuid4())
    interaction_id = str(uuid4())
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
    validations = SqlAlchemyPlanValidationRepository(factory)

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
            correlation_id=f"p5-s4:{trace_id}",
        )
        execution = admitted.execution
        if execution is None:
            raise RuntimeError("required admission did not create AgentExecution")
        marker = f"private-p5-s4-{token}"
        request = {
            "user_message": marker,
            "generation": {"execution_mode": "GROUNDED_ANSWER"},
        }
        work_intent = build_work_intent_from_decision(
            execution_id=execution["agent_execution_id"],
            source_ref=f"AE:INTERACTION:{interaction_id}",
            actor_ref=f"OA:SUBJECT:{principal_id}",
            received_at=now,
            intent_decision=resolve_intent_decision(request),
            input_context_hash=semantic_sha256_hash_ref(
                {"tenant_id": tenant_id, "interaction_id": interaction_id}
            ),
        )
        intents.save(tenant_id=tenant_id, work_intent=work_intent, created_at=now)
        resolver = _ReferenceResolver(
            TrustedContextResolution(
                project_ref=None,
                authority_ref="OA:EAC:p5-s4-smoke",
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
                resolve_runtime_policy(request)
            ),
            resolver=resolver,
            built_at=now,
        )
        contexts.save(tenant_id=tenant_id, agent_context=context)
        snapshot = build_capability_snapshot(
            tenant_id=tenant_id,
            capability_snapshot_id=str(uuid4()),
            snapshot_version=1,
            created_at=now,
        )
        snapshots.save(snapshot)
        plan = build_deterministic_agent_plan(
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            agent_plan_id=str(uuid4()),
        )
        plans.save(tenant_id=tenant_id, agent_plan=plan, created_at=now)
        result = validate_agent_plan(
            agent_plan=plan,
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            validated_at=now,
        )
        saved = validations.save_and_apply_runtime(
            tenant_id=tenant_id,
            result=result,
            expected_execution_version=execution["version"],
        )
        repeated = validations.save_and_apply_runtime(
            tenant_id=tenant_id,
            result=result,
            expected_execution_version=execution["version"],
        )
        restarted = SqlAlchemyPlanValidationRepository(factory).get(
            tenant_id=tenant_id,
            validation_result_id=result["validation_result_id"],
        )
        outcome = runtime_outcome_for_status(saved["status"])

        with engine.connect() as connection:
            database, role = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            execution_row = connection.execute(
                text(
                    "SELECT state, phase, version FROM ae_agent_execution "
                    "WHERE tenant_id = :tenant_id "
                    "AND agent_execution_id = :execution_id"
                ),
                {
                    "tenant_id": tenant_id,
                    "execution_id": execution["agent_execution_id"],
                },
            ).mappings().one()
            validation_count = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM ae_plan_validation "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            compile_row_count = _compile_row_count(connection, tenant_id)
        serialized = json.dumps(saved, ensure_ascii=False, sort_keys=True)
        checks = {
            "actual_database_identity": database == EXPECTED_DATABASE
            and role == EXPECTED_ROLE,
            "validation_valid": saved["status"] == "VALID"
            and saved["runtime_directive"] == "PROCEED_TO_COMPILE",
            "topological_order": saved["topological_step_order"] == ["S1", "S2"],
            "atomic_runtime_mapping": execution_row["state"]
            == outcome.agent_execution_state
            and execution_row["phase"] == outcome.agent_execution_phase
            and int(execution_row["version"]) == execution["version"] + 1,
            "validation_idempotent_restart": saved == repeated == restarted
            and validation_count == 1,
            "compile_authority_only": outcome.compile_allowed
            and compile_row_count == 0,
            "zero_auto_replan": outcome.auto_replan_allowed is False,
            "trusted_resolver_once": resolver.call_count == 1,
            "private_prompt_absent": marker not in serialized,
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
        "row_counts": {
            "plan_validation": validation_count,
            "compile_rows": compile_row_count,
        },
        "cleanup_counts": cleanup_counts,
    }


def _compile_row_count(connection, tenant_id: str) -> int:
    return sum(
        int(
            connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )
        for table in ("ae_executable_plan", "ae_executable_step")
        if _table_exists(connection, table)
    )


def _table_exists(connection, table: str) -> bool:
    return bool(
        connection.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :table)"
            ),
            {"table": table},
        ).scalar_one()
    )


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
        "slice": "P5-S4",
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
        "p5_s4_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"execution={str(evidence.get('execution_state') or 'not-run').lower()} "
        f"database={evidence.get('database', 'not-run')} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"validations={rows.get('plan_validation', 0)} "
        f"compile_rows={rows.get('compile_rows', 0)} "
        f"cleanup={(evidence.get('cleanup_counts') or {}).get('remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p5_s4_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
