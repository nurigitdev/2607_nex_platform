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
import run_p6_s5_postgres_smoke as p6_s5
from nex_ae_api.agent_execution_timeline import SqlAlchemyAgentExecutionTimeline
from nex_ae_api.multi_step_engine import (
    MultiStepEngineError,
    SqlAlchemyMultiStepEngine,
    StepTerminalOutcome,
)
from nex_ae_api.nsl_read_backends import (
    NSLReadBackendError,
    NSLReadExecutionService,
    SqlAlchemyNSLBackendRunRepository,
    V01ProcessEntrypoint,
    build_v01_process_isolated_backend,
)
from nex_ae_api.nsl_result_integration import (
    NSLResultIntegrationError,
    NSLResultIntegrationService,
)
from nex_ae_api.nsl_step_executions import (
    NSLStepExecutionError,
    SqlAlchemyNSLStepExecutionRepository,
    build_context_projection,
)
from nex_ae_api.runtime_jobs import RuntimeJobError, SqlAlchemyRuntimeJobQueue
from nex_ae_api.skill_artifacts import (
    SkillArtifactGatewayError,
    SqlAlchemySkillArtifactRepository,
)
from nex_ae_api.step_results import SqlAlchemyStepResultRepository, StepResultError
from nex_runtime import load_env_file, redact_database_url
from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p6_s6_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P6_S6_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
NSL_SOURCE_ENV = "NEX_AE_P6_S6_NSL_SOURCE"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2204_ae_nsl_backend_run"


def run_p6_s6_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-S6",
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
    nsl_source_value = env.get(NSL_SOURCE_ENV, "")
    if not nsl_source_value:
        return _failure("nsl_source_missing", f"{NSL_SOURCE_ENV} is required.")
    try:
        nsl_source = p6_s5._verified_nsl_source(Path(nsl_source_value))
    except (OSError, RuntimeError, ValueError) as exc:
        return _failure("nsl_source_invalid", str(exc))
    if str(nsl_source) not in sys.path:
        sys.path.insert(0, str(nsl_source))

    original_snapshot_builder = p5_s5.build_capability_snapshot
    original_plan_builder = p5_s5.build_deterministic_agent_plan
    try:
        migration = run_service_migrations(
            "nex-ae-api", database_url=database_url, profile="test"
        )

        def build_snapshot(**kwargs: Any) -> dict[str, Any]:
            return original_snapshot_builder(
                **kwargs,
                capabilities=(
                    *p6_s5.DEFAULT_P5_CAPABILITIES,
                    p6_s5._local_capability(),
                ),
            )

        def build_plan(**kwargs: Any) -> dict[str, Any]:
            plan = original_plan_builder(**kwargs)
            plan["steps"][0].update(
                {
                    "title": "Run exact local Skill",
                    "objective": "Execute deterministic NSL READ.",
                    "required_capability": p6_s5.SKILL_ID,
                    "capability_version_constraint": p6_s5.SKILL_VERSION,
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
            database_url,
            verifier=lambda fixture: _verify_result_timeline(
                fixture, nsl_source=nsl_source
            ),
        )
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P6-S6",
                "profile": "test",
                "database_env": DATABASE_ENV,
                "redacted_database_url": redact_database_url(database_url),
                "nsl_source_revision": p6_s5.EXPECTED_NSL_SHA,
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
            "migration_current_without_s6_table": (
                REQUIRED_MIGRATION in migration.planned
                and migration.planned[-1] == REQUIRED_MIGRATION
                and len(migration.planned)
                == len(migration.applied) + len(migration.skipped)
            ),
            **evidence["checks"],
        }
        evidence["status"] = "PASS" if all(evidence["checks"].values()) else "FAIL"
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "p6_s6_postgres_smoke_failed"
        return evidence
    except (
        MigrationError,
        MultiStepEngineError,
        NSLReadBackendError,
        NSLResultIntegrationError,
        NSLStepExecutionError,
        OSError,
        RuntimeError,
        RuntimeJobError,
        SkillArtifactGatewayError,
        StepResultError,
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


def _verify_result_timeline(
    fixture: Mapping[str, Any], *, nsl_source: Path
) -> dict[str, Any]:
    factory = fixture["factory"]
    tenant_id = str(fixture["tenant_id"])
    execution = dict(fixture["execution"])
    plan = dict(fixture["executable_plan"])
    step = plan["steps"][0]
    now = str(fixture["now"])
    artifact = json.loads(p6_s5.ARTIFACT.read_text(encoding="utf-8"))
    artifacts = SqlAlchemySkillArtifactRepository(factory)
    bindings = SqlAlchemyNSLStepExecutionRepository(factory)
    runs = SqlAlchemyNSLBackendRunRepository(factory)
    queue = SqlAlchemyRuntimeJobQueue(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue)
    try:
        artifacts.save(tenant_id=tenant_id, artifact=artifact)
        with factory() as session:
            context = (
                session.execute(
                    text(
                        "SELECT context_id, context_generation, context_hash, "
                        "context_json FROM ae_agent_context "
                        "WHERE tenant_id = :tenant_id "
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
        principal_id = context["context_json"]["identity"]["principal_id"]
        projection = build_context_projection(
            agent_context_ref=(
                f"AE:AGENT_CONTEXT:{context['context_id']}:"
                f"{context['context_generation']}"
            ),
            agent_context_hash=context["context_hash"],
            runtime_context_entries=(
                {
                    "path": "user.team_id",
                    "value": "TEAM-FINANCE",
                    "classification": "INTERNAL",
                    "source_ref": (
                        f"AE:AGENT_CONTEXT:{context['context_id']}:"
                        f"{context['context_generation']}"
                    ),
                },
            ),
            explicit_resource_refs=(),
            verified_principal={
                "tenant_id": tenant_id,
                "subject_id": principal_id,
                "actor_type": "USER",
                "roles": ["EMPLOYEE"],
                "scopes": ["nsl:skill:execute", "project:budget:read"],
                "auth_context_ref": f"OA:AUTH_CONTEXT:{principal_id}",
                "verification": "VERIFIED",
                "on_behalf_of": None,
            },
            authority={
                "effective_role_bindings": ["EMPLOYEE"],
                "org_scope": ["ORG-FINANCE"],
                "project_scope": None,
            },
            data_policy={
                "policy_ref": "OA:DATA_POLICY:p6-s6-smoke",
                "max_trace_classification": "CONFIDENTIAL",
                "snapshot_retention_days": 30,
                "audit_retention_days": 90,
            },
        )
        first_job = engine.schedule_next(
            tenant_id=tenant_id,
            execution_id=execution["agent_execution_id"],
            now=now,
        )
        claim = queue.claim(
            tenant_id=tenant_id,
            worker_id="p6-s6-smoke-worker",
            lease_seconds=60,
            now=now,
        )
        if first_job is None or claim is None:
            raise RuntimeError("P6-S6 LOCAL_SKILL RuntimeJob was not claimable")
        context_record = engine.begin_claim(tenant_id=tenant_id, claim=claim, now=now)
        bindings.bind_request(
            tenant_id=tenant_id,
            executable_step_id=step["executable_step_id"],
            verified_artifact_ref=artifact["artifact_ref"],
            context_projection=projection,
            compiled_inputs={"year": 2026},
            input_provenance={"year": "USER"},
            now=now,
        )
        backend = build_v01_process_isolated_backend(
            V01ProcessEntrypoint(p6_s5._GoldenWorkerFactory(str(nsl_source))),
            timeout_ms=30_000,
        )
        backend_run = NSLReadExecutionService(
            bindings=bindings,
            artifacts=artifacts,
            backend=backend,
            runs=runs,
        ).execute_bound(
            tenant_id=tenant_id,
            executable_step_id=step["executable_step_id"],
            attempt_no=int(claim.attempt["attempt_no"]),
        )
        integration = NSLResultIntegrationService(
            bindings=bindings,
            artifacts=artifacts,
            runs=runs,
        ).finalize_bound(
            tenant_id=tenant_id,
            executable_step_id=step["executable_step_id"],
            attempt_no=int(claim.attempt["attempt_no"]),
        )
        outcome = integration.outcome
        step_result = engine.record_outcome(
            tenant_id=tenant_id,
            claim=claim,
            outcome=StepTerminalOutcome(
                status=outcome.state,
                result_contract_ref=outcome.result_contract_ref,
                result_payload=outcome.result_payload,
                external_refs=outcome.external_refs,
                artifact_refs=outcome.artifact_refs,
                evidence_refs=outcome.evidence_refs,
                error_ref=outcome.error_ref,
                executor_kind="LOCAL_SKILL",
                business_operation_id=outcome.business_operation_id,
                started_at=outcome.started_at,
                completed_at=outcome.completed_at,
            ),
        )
        queue.complete(
            tenant_id=tenant_id,
            runtime_job_id=claim.job["runtime_job_id"],
            worker_id="p6-s6-smoke-worker",
            lease_token=claim.job["lease_token"],
            now=integration.summary["completed_at"],
        )
        timeline_repository = SqlAlchemyAgentExecutionTimeline(factory)
        timeline = timeline_repository.project(
            tenant_id=tenant_id,
            agent_execution_id=execution["agent_execution_id"],
        )
        restarted_timeline = SqlAlchemyAgentExecutionTimeline(factory).project(
            tenant_id=tenant_id,
            agent_execution_id=execution["agent_execution_id"],
        )
        persisted_result = SqlAlchemyStepResultRepository(factory).get_by_step(
            tenant_id=tenant_id,
            executable_step_id=step["executable_step_id"],
        )
        with factory() as session:
            counts = {
                table: _tenant_count(session, table, tenant_id)
                for table in (
                    "ae_runtime_job",
                    "ae_runtime_job_attempt",
                    "ae_nsl_artifact",
                    "ae_nsl_step_execution",
                    "ae_nsl_backend_run",
                    "ae_step_result",
                )
            }
        serialized_summary = canonical_json(integration.summary)
        serialized_timeline = canonical_json(timeline)
        event_types = {event["event_type"] for event in timeline["events"]}
        checks = {
            "local_skill_job_claimed": first_job["executable_step_id"]
            == step["executable_step_id"]
            and context_record.step["executor_kind"] == "LOCAL_SKILL",
            "source_backed_nsl_completed": backend_run["runtime_status"] == "COMPLETED",
            "bounded_summary_terminalized": integration.binding["state"] == "SUCCEEDED"
            and integration.summary["execution_status"] == "COMPLETED"
            and integration.summary_hash == integration.binding["result_summary_hash"],
            "step_result_v12_lineage": step_result == persisted_result
            and step_result["schema_version"] == "1.2"
            and step_result["executor_kind"] == "LOCAL_SKILL"
            and step_result["business_operation_id"]
            == integration.summary["business_operation_id"],
            "timeline_complete_retained_sources": event_types
            >= {
                "EXECUTION_ADMITTED",
                "PLAN_COMPILED",
                "JOB_ATTEMPT_STARTED",
                "NSL_REQUEST_BOUND",
                "NSL_PROGRESS_SKILL_RESOLVED",
                "NSL_RESULT_SUMMARY_RECORDED",
                "STEP_RESULT_RECORDED",
            },
            "timeline_restart_deterministic": timeline == restarted_timeline,
            "timeline_sequence_ordered": [
                event["sequence"] for event in timeline["events"]
            ]
            == list(range(1, len(timeline["events"]) + 1)),
            "projection_gaps_explicit": {
                gap["gap_code"] for gap in timeline["projection_gaps"]
            }
            >= {
                "EXECUTION_TRANSITION_HISTORY_UNAVAILABLE",
                "STEP_TRANSITION_HISTORY_UNAVAILABLE",
                "NSL_PROGRESS_TIMESTAMPS_UNAVAILABLE",
            },
            "raw_content_absent": "runtime_result_envelope" not in serialized_summary
            and "100000000" not in serialized_summary
            and "100000000" not in serialized_timeline,
            "one_durable_result_lineage": all(count == 1 for count in counts.values()),
        }
        return {
            "checks": checks,
            "row_counts": {
                **counts,
                "timeline_events": len(timeline["events"]),
                "timeline_gaps": len(timeline["projection_gaps"]),
            },
            "cleanup_counts": _cleanup_s6_rows(factory, tenant_id),
        }
    finally:
        _cleanup_s6_rows(factory, tenant_id)


def _cleanup_s6_rows(factory: object, tenant_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    tables = (
        "ae_nsl_backend_run",
        "ae_nsl_step_execution",
        "ae_nsl_artifact",
        "ae_step_result",
        "ae_runtime_job_attempt",
        "ae_runtime_job",
    )
    with factory.begin() as session:
        for table in tables:
            counts[table] = int(
                session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
    with factory() as session:
        counts["s6_remaining"] = sum(
            _tenant_count(session, table, tenant_id) for table in tables
        )
    return counts


def _tenant_count(connection: object, table: str, tenant_id: str) -> int:
    return int(
        connection.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).scalar_one()
    )


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6-S6",
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
        "p6_s6_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"actual_postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"results={rows.get('ae_step_result', 0)} "
        f"events={rows.get('timeline_events', 0)} "
        f"remaining={cleanup.get('s6_remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p6_s6_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
