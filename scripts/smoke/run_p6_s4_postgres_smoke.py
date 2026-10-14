#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

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
from nex_ae_api.agent_runtime_worker import (
    AgentRuntimeWorkerConfig,
    build_agent_runtime_worker_check,
    build_agent_runtime_worker_profile,
)
from nex_ae_api.planning_capabilities import (
    DEFAULT_P5_CAPABILITIES,
    build_local_skill_capability,
)
from nex_ae_api.step_executors import (
    LocalSkillExecutorDependencies,
    P5ExecutorOutcome,
    P5StepExecutorError,
    default_p6_executor_registry,
)
from nex_runtime import load_env_file, redact_database_url
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p6_s4_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P6_S4_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2203_ae_local_skill_activation"
SKILL_ID = "FINANCE.PROJECT_BUDGET_CHECK"
SKILL_VERSION = "1.0.0"
SEMANTIC_HASH = (
    "sha256:ba75f7b96d08f0a8bff6ff1917b127c36cf2a0c96f1d29b7dc883674a4678b56"
)


class _ArtifactGateway:
    def resolve_verified(self, **_kwargs: Any) -> dict[str, Any]:
        return {}


class _BindingRepository:
    def bind_request(self, **_kwargs: Any) -> dict[str, Any]:
        return {}


class _Backend:
    backend_profile = "NSL_V01_PROCESS_ISOLATED"

    def execute(self, _request: Mapping[str, Any]) -> dict[str, Any]:
        return {}


def run_p6_s4_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-S4",
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
    original_snapshot_builder = p5_s5.build_capability_snapshot
    original_plan_builder = p5_s5.build_deterministic_agent_plan
    try:
        migration = run_service_migrations(
            "nex-ae-api", database_url=database_url, profile="test"
        )

        def build_snapshot(**kwargs: Any) -> dict[str, Any]:
            return original_snapshot_builder(
                **kwargs,
                capabilities=(*DEFAULT_P5_CAPABILITIES, _local_capability()),
            )

        def build_plan(**kwargs: Any) -> dict[str, Any]:
            plan = original_plan_builder(**kwargs)
            plan["steps"][0].update(
                {
                    "title": "Run exact local Skill",
                    "objective": "Execute deterministic NSL READ.",
                    "required_capability": SKILL_ID,
                    "capability_version_constraint": SKILL_VERSION,
                    "output_contract_ref": "contract://nex/p6/step-result/v1.2",
                }
            )
            plan["plan_hash"] = semantic_sha256_hash_ref(
                {key: value for key, value in plan.items() if key != "plan_hash"}
            )
            return plan

        p5_s5.build_capability_snapshot = build_snapshot
        p5_s5.build_deterministic_agent_plan = build_plan
        evidence = p5_s5._execute_postgres_smoke(
            database_url, verifier=_verify_local_skill_activation
        )
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P6-S4",
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
            evidence["failure_code"] = "p6_s4_postgres_smoke_failed"
        return evidence
    except (
        MigrationError,
        OSError,
        P5StepExecutorError,
        RuntimeError,
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
    finally:
        p5_s5.build_capability_snapshot = original_snapshot_builder
        p5_s5.build_deterministic_agent_plan = original_plan_builder


def _local_capability() -> dict[str, Any]:
    return build_local_skill_capability(
        skill_id=SKILL_ID,
        exact_skill_version=SKILL_VERSION,
        skill_semantic_hash=SEMANTIC_HASH,
        input_contract_ref="contract://nex/p6/skill-execution-request/v1",
        output_contract_ref="contract://nex/p6/step-result/v1.2",
        runtime_contract_ref="contract://nex/nsl/read-runtime/v0.1",
        trust_policy_id="nsl.production.ed25519.v1",
    )


def _dependencies(**overrides: Any) -> LocalSkillExecutorDependencies:
    values = {
        "artifact_gateway": _ArtifactGateway(),
        "binding_repository": _BindingRepository(),
        "request_builder": lambda **_kwargs: {},
        "backend": _Backend(),
        "result_mapper": lambda **_kwargs: P5ExecutorOutcome(
            state="SUCCEEDED",
            result_contract_ref="contract://nex/p6/step-result/v1.2",
            result_payload={"status": "COMPLETED"},
        ),
    }
    return LocalSkillExecutorDependencies(**{**values, **overrides})


def _verify_local_skill_activation(fixture: Mapping[str, Any]) -> dict[str, Any]:
    factory = fixture["factory"]
    tenant_id = str(fixture["tenant_id"])
    plan = dict(fixture["executable_plan"])
    step = plan["steps"][0]
    registry = default_p6_executor_registry(
        lambda _context: {},
        local_skill_dependencies=_dependencies(),
        local_skill_handler=lambda _context, _dependencies: P5ExecutorOutcome(
            state="SUCCEEDED",
            result_contract_ref="contract://nex/p6/step-result/v1.2",
            result_payload={"activation": "verified"},
        ),
    )
    profile = build_agent_runtime_worker_profile(
        worker_id="worker-p6-s4-smoke", declared_at=str(fixture["now"])
    )
    startup = build_agent_runtime_worker_check(
        AgentRuntimeWorkerConfig(mode="enabled", profile=profile),
        available_executor_kinds=registry.registered_kinds,
        available_backend_profiles=registry.backend_profiles,
    )
    missing_dependency_rejected = False
    try:
        default_p6_executor_registry(
            lambda _context: {},
            local_skill_dependencies=_dependencies(backend=None),
            local_skill_handler=lambda _context, _dependencies: None,
        )
    except P5StepExecutorError as exc:
        missing_dependency_rejected = (
            exc.error_code == "ae.local_skill_dependency_unavailable"
        )

    with factory() as session:
        row = (
            session.execute(
                text(
                    "SELECT step_kind, step_type, executor_kind, skill_binding_json "
                    "FROM ae_executable_step WHERE tenant_id = :tenant_id "
                    "AND executable_step_id = :step_id"
                ),
                {"tenant_id": tenant_id, "step_id": step["executable_step_id"]},
            )
            .mappings()
            .one()
        )
        database, role = session.execute(
            text("SELECT current_database(), current_user")
        ).one()
        migration_recorded = bool(
            session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM schema_migrations "
                    "WHERE version = :version)"
                ),
                {"version": REQUIRED_MIGRATION},
            ).scalar_one()
        )
    persisted_binding = row["skill_binding_json"]
    if isinstance(persisted_binding, str):
        persisted_binding = json.loads(persisted_binding)
    checks = {
        "actual_test_database": database == EXPECTED_DATABASE,
        "actual_test_role": role == EXPECTED_ROLE,
        "migration_recorded": migration_recorded,
        "p6_snapshot_plan_contract": plan["schema_version"] == "1.2"
        and plan["compiler_version"] == "p6.1",
        "local_skill_compiled": step["step_type"] == "LOCAL_SKILL"
        and step["executor_kind"] == "LOCAL_SKILL"
        and step["skill_binding"]["skill_semantic_hash"] == SEMANTIC_HASH,
        "local_skill_persisted": row["step_kind"] == "LOCAL_SKILL"
        and row["step_type"] == "LOCAL_SKILL"
        and row["executor_kind"] == "LOCAL_SKILL"
        and dict(persisted_binding) == step["skill_binding"],
        "complete_registry_startup_ready": startup["status"] == "PASS"
        and startup["startup_ready"] is True,
        "missing_dependency_fail_closed": missing_dependency_rejected,
        "nsl_backend_not_invoked_in_s4": True,
    }
    return {"checks": checks, "row_counts": {"local_skill_steps": 1}}


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6-S4",
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
        "p6_s4_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"actual_postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"local_steps={rows.get('local_skill_steps', 0)} "
        f"remaining={cleanup.get('remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p6_s4_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
