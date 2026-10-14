#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

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
from nex_ae_api.nsl_step_executions import (
    NSLStepExecutionError,
    SqlAlchemyNSLStepExecutionRepository,
    build_context_projection,
)
from nex_ae_api.skill_artifacts import (
    SkillArtifactGatewayError,
    SqlAlchemySkillArtifactRepository,
)
from nex_runtime import load_env_file, redact_database_url
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p6_s3_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P6_S3_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2202_ae_nsl_step_execution"
ARTIFACT = (
    ROOT / "docs/transition/P6/contracts/examples/p6-golden-verified-artifact-v1.json"
)


def run_p6_s3_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-S3",
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
            database_url, verifier=_verify_nsl_binding
        )
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P6-S3",
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
            "migration_current": (
                REQUIRED_MIGRATION in migration.planned
                and migration.planned[-1] == REQUIRED_MIGRATION
                and len(migration.planned)
                == len(migration.applied) + len(migration.skipped)
            ),
            **evidence["checks"],
        }
        evidence["status"] = "PASS" if all(evidence["checks"].values()) else "FAIL"
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "p6_s3_postgres_smoke_failed"
        return evidence
    except (
        MigrationError,
        NSLStepExecutionError,
        OSError,
        RuntimeError,
        SkillArtifactGatewayError,
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


def _verify_nsl_binding(fixture: Mapping[str, Any]) -> dict[str, Any]:
    factory = fixture["factory"]
    tenant_id = str(fixture["tenant_id"])
    execution = dict(fixture["execution"])
    plan = dict(fixture["executable_plan"])
    now = str(fixture["now"])
    step = plan["steps"][0]
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    artifacts = SqlAlchemySkillArtifactRepository(factory)
    artifacts.save(tenant_id=tenant_id, artifact=artifact)

    with factory.begin() as session:
        session.execute(
            text(
                "UPDATE ae_executable_step SET step_kind = 'LOCAL_SKILL_UNAVAILABLE', "
                "step_type = 'LOCAL_SKILL', executor_kind = 'LOCAL_SKILL_UNAVAILABLE', "
                "required_capability = :skill_id, capability_version = :skill_version "
                "WHERE tenant_id = :tenant_id AND executable_step_id = :step_id"
            ),
            {
                "tenant_id": tenant_id,
                "step_id": step["executable_step_id"],
                "skill_id": artifact["skill_id"],
                "skill_version": artifact["skill_version"],
            },
        )
        context = (
            session.execute(
                text(
                    "SELECT context_id, context_generation, context_hash, context_json "
                    "FROM ae_agent_context WHERE tenant_id = :tenant_id "
                    "AND agent_execution_id = :execution_id "
                    "ORDER BY context_generation DESC LIMIT 1"
                ),
                {
                    "tenant_id": tenant_id,
                    "execution_id": execution["agent_execution_id"],
                },
            )
            .mappings()
            .one()
        )
        database, role = session.execute(
            text("SELECT current_database(), current_user")
        ).one()
    context_json = context["context_json"]
    principal_id = context_json["identity"]["principal_id"]
    projection = build_context_projection(
        agent_context_ref=(
            f"AE:AGENT_CONTEXT:{context['context_id']}:{context['context_generation']}"
        ),
        agent_context_hash=context["context_hash"],
        runtime_context_entries=(),
        explicit_resource_refs=(),
        verified_principal={
            "tenant_id": tenant_id,
            "subject_id": principal_id,
            "actor_type": "USER",
            "roles": ["EMPLOYEE"],
            "scopes": ["nsl:skill:execute"],
            "auth_context_ref": f"OA:AUTH_CONTEXT:{principal_id}",
            "verification": "VERIFIED",
            "on_behalf_of": None,
        },
        authority={
            "effective_role_bindings": ["EMPLOYEE"],
            "org_scope": ["ORG-SMOKE"],
            "project_scope": None,
        },
        data_policy={
            "policy_ref": "OA:DATA_POLICY:p6-s3-smoke",
            "max_trace_classification": "CONFIDENTIAL",
            "snapshot_retention_days": 30,
            "audit_retention_days": 90,
        },
    )
    ids = iter((str(uuid4()), str(uuid4())))
    repository = SqlAlchemyNSLStepExecutionRepository(factory, id_factory=ids.__next__)
    arguments = {
        "tenant_id": tenant_id,
        "executable_step_id": step["executable_step_id"],
        "verified_artifact_ref": artifact["artifact_ref"],
        "context_projection": projection,
        "compiled_inputs": {"year": 2026},
        "input_provenance": {"year": "USER"},
        "now": now,
    }
    bound = repository.bind_request(**arguments)
    replay = SqlAlchemyNSLStepExecutionRepository(factory).bind_request(**arguments)
    restarted = SqlAlchemyNSLStepExecutionRepository(factory).get(
        tenant_id=tenant_id, executable_step_id=step["executable_step_id"]
    )
    with factory() as session:
        row = (
            session.execute(
                text(
                    "SELECT count(*) AS total, count(DISTINCT nsl_execution_id) AS nsl_ids, "
                    "count(DISTINCT business_operation_id) AS operation_ids, "
                    "count(*) FILTER (WHERE request_hash = binding_json ->> 'request_hash') "
                    "AS hash_matches FROM ae_nsl_step_execution "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            )
            .mappings()
            .one()
        )
        migration_recorded = bool(
            session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM schema_migrations "
                    "WHERE version = :version)"
                ),
                {"version": REQUIRED_MIGRATION},
            ).scalar_one()
        )

    changed_rejected = False
    try:
        repository.bind_request(**{**arguments, "compiled_inputs": {"year": 2027}})
    except NSLStepExecutionError as exc:
        changed_rejected = exc.error_code == "ae.nsl_binding_immutable_conflict"

    checks = {
        "actual_test_database": database == EXPECTED_DATABASE,
        "actual_test_role": role == EXPECTED_ROLE,
        "migration_recorded": migration_recorded,
        "binding_request_round_trip": bound == replay == restarted,
        "one_binding_per_step": int(row["total"]) == 1,
        "stable_distinct_runtime_ids": int(row["nsl_ids"]) == 1
        and int(row["operation_ids"]) == 1
        and bound["binding"]["nsl_execution_id"]
        != bound["binding"]["business_operation_id"],
        "request_hash_bound": int(row["hash_matches"]) == 1,
        "immutable_replay_rejected": changed_rejected,
        "pre_s4_executor_not_activated": bound["binding"]["state"] == "REQUEST_BOUND",
    }
    with factory.begin() as session:
        deleted_binding = int(
            session.execute(
                text("DELETE FROM ae_nsl_step_execution WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            ).rowcount
            or 0
        )
        deleted_artifact = int(
            session.execute(
                text("DELETE FROM ae_nsl_artifact WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            ).rowcount
            or 0
        )
    with factory() as session:
        remaining = sum(
            int(
                session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for table in ("ae_nsl_step_execution", "ae_nsl_artifact")
        )
    checks["s3_cleanup_complete"] = remaining == 0
    return {
        "checks": checks,
        "row_counts": {"nsl_step_execution": int(row["total"])},
        "cleanup_counts": {
            "nsl_step_execution_deleted": deleted_binding,
            "nsl_artifact_deleted": deleted_artifact,
            "s3_remaining": remaining,
        },
    }


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6-S3",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    migration = evidence.get("migration") or {}
    rows = evidence.get("row_counts") or {}
    cleanup = evidence.get("cleanup_counts") or {}
    return (
        "p6_s3_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"actual_postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"bindings={rows.get('nsl_step_execution', 0)} "
        f"remaining={cleanup.get('s3_remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p6_s3_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
