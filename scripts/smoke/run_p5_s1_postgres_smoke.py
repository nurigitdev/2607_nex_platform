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
from nex_ae_api.prompt_persistence import (
    PromptRepositoryError,
    SqlAlchemyAePromptRegistryStore,
)
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
from nex_runtime.prompts import (
    PromptSeed,
    build_prompt_binding,
    build_prompt_template,
    build_prompt_template_version,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p5_s1_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P5_S1_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"


def run_p5_s1_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P5-S1",
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
            "2101_ae_work_intent" in migration.planned
            and len(migration.planned)
            == len(migration.applied) + len(migration.skipped)
        )
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P5-S1",
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
            evidence["failure_code"] = "p5_s1_postgres_smoke_failed"
        return evidence
    except (
        AgentExecutionError,
        AgentIdentityRepositoryError,
        MigrationError,
        OSError,
        PromptRepositoryError,
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
    tenant_id = f"tenant-p5-s1-{token[:12]}"
    principal_id = f"user-p5-s1-{token[:12]}"
    interaction_id = str(uuid4())
    trace_id = uuid4().hex
    correlation_id = f"p5-s1:{trace_id}"
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    cleanup_counts: dict[str, int] = {}
    checks: dict[str, bool] = {}
    database = ""
    role = ""

    identities = SqlAlchemyAgentIdentityRegistry(factory)
    executions = SqlAlchemyAgentExecutionRepository(factory)
    admission = AgentExecutionAdmissionService(
        identities=identities, executions=executions, mode="required"
    )
    prompts = SqlAlchemyAePromptRegistryStore(factory)
    intents = SqlAlchemyWorkIntentRepository(factory)
    seed = PromptSeed(
        service_id="nex-ae-api",
        purpose=f"p5_s1_smoke_{token}",
        name=f"p5_s1_smoke_{token}",
        owner_domain="agent-experience",
        binding_key=f"ae.p5_s1_smoke.{token}",
        version="v1",
        role="system",
        segment_order=0,
        content="P5-S1 deterministic smoke prompt version one.",
        model_capability="generation",
        metadata={"slice": "P5-S1"},
    )
    template_id: str | None = None
    execution_id: str | None = None
    agent_id: str | None = None

    try:
        admitted = admission.admit_prompt(
            tenant_id=tenant_id,
            principal_id=principal_id,
            profile_ref="urn:nex:agent-profile:ia:default:v1",
            trigger_id=interaction_id,
            interaction_id=interaction_id,
            workspace_id=None,
            conversation_id=None,
            correlation_id=correlation_id,
        )
        if admitted.execution is None:
            raise RuntimeError("required admission did not create AgentExecution")
        execution_id = str(admitted.execution["agent_execution_id"])
        agent_id = str(admitted.execution["agent_id"])

        template = prompts.save_template(build_prompt_template(seed))
        template_id = str(template["prompt_template_id"])
        first = prompts.save_template_version(
            build_prompt_template_version(seed, template)
        )
        prompts.save_binding(build_prompt_binding(seed, first))
        first_snapshot = prompts.get_prompt_provenance(seed.binding_key)
        second_seed = replace(
            seed,
            version="v2",
            content="P5-S1 deterministic smoke prompt version two.",
        )
        second = prompts.save_template_version(
            build_prompt_template_version(second_seed, template)
        )
        activation = prompts.activate_binding(
            binding_key=seed.binding_key,
            new_prompt_template_version_id=second["prompt_template_version_id"],
            expected_prompt_template_version_id=first[
                "prompt_template_version_id"
            ],
            changed_by="p5-s1-smoke",
            reason="Verify atomic prompt pointer activation.",
            correlation_id=correlation_id,
        )
        repeated_activation = prompts.activate_binding(
            binding_key=seed.binding_key,
            new_prompt_template_version_id=second["prompt_template_version_id"],
            expected_prompt_template_version_id=first[
                "prompt_template_version_id"
            ],
            changed_by="p5-s1-smoke",
            reason="Verify idempotent replay.",
            correlation_id=f"{correlation_id}:replay",
        )
        decision = resolve_intent_decision(
            {
                "user_message": "P5-S1 private PostgreSQL smoke prompt",
                "generation": {"execution_mode": "GROUNDED_ANSWER"},
            }
        )
        work_intent = build_work_intent_from_decision(
            execution_id=execution_id,
            source_ref=f"AE:INTERACTION:{interaction_id}",
            actor_ref=f"OA:SUBJECT:{principal_id}",
            received_at=now,
            intent_decision=decision,
            input_context_hash=semantic_sha256_hash_ref(
                {
                    "tenant_id": tenant_id,
                    "principal_id": principal_id,
                    "interaction_id": interaction_id,
                }
            ),
            prompt_provenance={
                **prompts.get_prompt_provenance(seed.binding_key),
                "rendered_prompt_hash": second["content_sha256"],
                "model_profile": "deterministic-smoke",
                "model_ref": "mock/no-provider-call",
            },
        )
        saved = intents.save(
            tenant_id=tenant_id, work_intent=work_intent, created_at=now
        )
        repeated = intents.save(
            tenant_id=tenant_id, work_intent=work_intent, created_at=now
        )
        restarted = SqlAlchemyWorkIntentRepository(factory).get(
            tenant_id=tenant_id, work_intent_id=work_intent["work_intent_id"]
        )

        with engine.connect() as connection:
            database, role = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            history_count = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM ae_prompt_binding_history "
                        "WHERE binding_key = :binding_key"
                    ),
                    {"binding_key": seed.binding_key},
                ).scalar_one()
            )
            intent_count = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM ae_work_intent "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )

        serialized = json.dumps(saved, ensure_ascii=False, sort_keys=True)
        checks = {
            "actual_database_identity": database == EXPECTED_DATABASE
            and role == EXPECTED_ROLE,
            "binding_changed_once": activation["changed"] is True
            and repeated_activation["changed"] is False
            and history_count == 1,
            "captured_provenance_isolated": first_snapshot[
                "prompt_template_version_id"
            ]
            == first["prompt_template_version_id"]
            and saved["provenance"]["prompt_template_version_id"]
            == second["prompt_template_version_id"],
            "work_intent_idempotent": saved == repeated == restarted
            and intent_count == 1,
            "prompt_private": "private PostgreSQL smoke prompt" not in serialized,
            "semantic_hash_prefixed": str(saved["intent_hash"]).startswith(
                "sha256:"
            ),
        }
    finally:
        try:
            cleanup_counts = _cleanup(
                factory,
                tenant_id=tenant_id,
                principal_id=principal_id,
                agent_id=agent_id,
                template_id=template_id,
                binding_key=seed.binding_key,
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
        "row_counts": {"binding_history": history_count, "work_intent": intent_count},
        "cleanup_counts": cleanup_counts,
    }


def _cleanup(
    factory,
    *,
    tenant_id: str,
    principal_id: str,
    agent_id: str | None,
    template_id: str | None,
    binding_key: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    with factory.begin() as session:
        for key, statement, params in (
            (
                "work_intent",
                "DELETE FROM ae_work_intent WHERE tenant_id = :tenant_id",
                {"tenant_id": tenant_id},
            ),
            (
                "binding_history",
                "DELETE FROM ae_prompt_binding_history WHERE binding_key = :binding_key",
                {"binding_key": binding_key},
            ),
            (
                "binding",
                "DELETE FROM ae_prompt_bindings WHERE binding_key = :binding_key",
                {"binding_key": binding_key},
            ),
            (
                "template_versions",
                "DELETE FROM ae_prompt_template_versions WHERE prompt_template_id = :id",
                {"id": template_id},
            ),
            (
                "template",
                "DELETE FROM ae_prompt_templates WHERE prompt_template_id = :id",
                {"id": template_id},
            ),
            (
                "execution",
                "DELETE FROM ae_agent_execution WHERE tenant_id = :tenant_id",
                {"tenant_id": tenant_id},
            ),
            (
                "assignment",
                (
                    "DELETE FROM ae_ia_principal_assignment "
                    "WHERE tenant_id = :tenant_id AND principal_id = :principal_id"
                ),
                {"tenant_id": tenant_id, "principal_id": principal_id},
            ),
            (
                "identity",
                (
                    "DELETE FROM ae_agent_identity "
                    "WHERE tenant_id = :tenant_id AND agent_id = :agent_id"
                ),
                {"tenant_id": tenant_id, "agent_id": agent_id},
            ),
        ):
            counts[key] = int(session.execute(text(statement), params).rowcount or 0)
    with factory() as session:
        counts["remaining"] = sum(
            int(
                session.execute(
                    text(statement), params
                ).scalar_one()
            )
            for statement, params in (
                (
                    "SELECT count(*) FROM ae_work_intent WHERE tenant_id = :tenant_id",
                    {"tenant_id": tenant_id},
                ),
                (
                    "SELECT count(*) FROM ae_prompt_binding_history WHERE binding_key = :binding_key",
                    {"binding_key": binding_key},
                ),
                (
                    "SELECT count(*) FROM ae_prompt_bindings WHERE binding_key = :binding_key",
                    {"binding_key": binding_key},
                ),
                (
                    "SELECT count(*) FROM ae_agent_execution WHERE tenant_id = :tenant_id",
                    {"tenant_id": tenant_id},
                ),
                (
                    "SELECT count(*) FROM ae_agent_identity WHERE tenant_id = :tenant_id",
                    {"tenant_id": tenant_id},
                ),
            )
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
        "slice": "P5-S1",
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
        "p5_s1_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"execution={str(evidence.get('execution_state') or 'not-run').lower()} "
        f"database={evidence.get('database', 'not-run')} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"rows={rows.get('binding_history', 0)}/{rows.get('work_intent', 0)} "
        f"cleanup={(evidence.get('cleanup_counts') or {}).get('remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p5_s1_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
