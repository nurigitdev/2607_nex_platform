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
import run_p6_s0_postgres_smoke as p6_s0
import run_p6_s2_postgres_smoke as p6_s2
import run_p6_s5_postgres_smoke as p6_s5
from nex_ae_api.agent_execution_timeline import SqlAlchemyAgentExecutionTimeline
from nex_ae_api.agent_runtime_dispatcher import (
    AgentRuntimeDispatcherConfig,
    SqlAlchemyAgentRuntimeAssignmentSource,
    SqlAlchemyAgentRuntimeDispatcher,
)
from nex_ae_api.agent_runtime_worker import (
    AgentRuntimeWorkerConfig,
    build_agent_runtime_worker_profile,
    run_bounded_agent_runtime_worker,
)
from nex_ae_api.multi_step_engine import MultiStepEngineError, SqlAlchemyMultiStepEngine
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
    to_p5_executor_outcome,
)
from nex_ae_api.nsl_step_executions import (
    NSLStepExecutionError,
    SqlAlchemyNSLStepExecutionRepository,
    build_context_projection,
)
from nex_ae_api.p6_ia_read_runtime import (
    AgentRuntimeStepAssignmentHandler,
    LocalSkillInvocation,
    P6LocalSkillReadHandler,
)
from nex_ae_api.plan_finalization import (
    P5PlanFinalizationError,
    SqlAlchemyP5PlanFinalizationService,
)
from nex_ae_api.runtime_jobs import RuntimeJobError, SqlAlchemyRuntimeJobQueue
from nex_ae_api.skill_artifacts import (
    SkillArtifactGateway,
    SkillArtifactGatewayError,
    SqlAlchemySkillArtifactRepository,
)
from nex_ae_api.step_executors import (
    LocalSkillExecutorDependencies,
    P5StepExecutionWorker,
    P5StepExecutorError,
    default_p6_executor_registry,
)
from nex_runtime import (
    SqlAlchemyWorkerHeartbeatStore,
    load_env_file,
    redact_database_url,
)
from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p6_s7_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P6_S7_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
NSL_SOURCE_ENV = "NEX_AE_P6_S7_NSL_SOURCE"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2204_ae_nsl_backend_run"


def run_p6_s7_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-S7",
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
            verifier=lambda fixture: _verify_ia_read_closure(
                fixture, nsl_source=nsl_source
            ),
        )
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P6-S7",
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
            "migration_current_without_s7_table": (
                REQUIRED_MIGRATION in migration.planned
                and migration.planned[-1] == REQUIRED_MIGRATION
                and len(migration.planned)
                == len(migration.applied) + len(migration.skipped)
            ),
            **evidence["checks"],
        }
        evidence["status"] = "PASS" if all(evidence["checks"].values()) else "FAIL"
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "p6_s7_postgres_smoke_failed"
        return evidence
    except (
        MigrationError,
        MultiStepEngineError,
        NSLReadBackendError,
        NSLResultIntegrationError,
        NSLStepExecutionError,
        OSError,
        P5PlanFinalizationError,
        P5StepExecutorError,
        RuntimeError,
        RuntimeJobError,
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
    finally:
        p5_s5.build_capability_snapshot = original_snapshot_builder
        p5_s5.build_deterministic_agent_plan = original_plan_builder


def _verify_ia_read_closure(
    fixture: Mapping[str, Any], *, nsl_source: Path
) -> dict[str, Any]:
    factory = fixture["factory"]
    tenant_id = str(fixture["tenant_id"])
    execution = dict(fixture["execution"])
    plan = dict(fixture["executable_plan"])
    local_step, final_step = plan["steps"]
    now = str(fixture["now"])
    worker_id = f"ae-p6-s7-{uuid4().hex[:12]}"
    queue_name = f"ae-runtime-p6-s7-{uuid4().hex[:12]}"
    queue = SqlAlchemyRuntimeJobQueue(factory)
    engine = SqlAlchemyMultiStepEngine(factory, queue)
    artifacts = SqlAlchemySkillArtifactRepository(factory)
    bindings = SqlAlchemyNSLStepExecutionRepository(factory)
    runs = SqlAlchemyNSLBackendRunRepository(factory)
    golden = json.loads(p6_s5.ARTIFACT.read_text(encoding="utf-8"))
    gateway = SkillArtifactGateway(
        resolver=p6_s2._Resolver(golden),
        admission_source=p6_s2._AdmissionSource(golden),
        repository=artifacts,
    )
    backend = build_v01_process_isolated_backend(
        V01ProcessEntrypoint(p6_s5._GoldenWorkerFactory(str(nsl_source))),
        timeout_ms=30_000,
    )
    read_execution = NSLReadExecutionService(
        bindings=bindings,
        artifacts=artifacts,
        backend=backend,
        runs=runs,
    )
    result_integration = NSLResultIntegrationService(
        bindings=bindings,
        artifacts=artifacts,
        runs=runs,
    )
    try:
        projection = _context_projection(factory, tenant_id, execution, now)
        invocation = LocalSkillInvocation(
            context_projection=projection,
            compiled_inputs={"year": 2026},
            input_provenance={"year": "USER"},
            observed_at=now,
            environment="test",
        )
        dependencies = LocalSkillExecutorDependencies(
            artifact_gateway=gateway,
            binding_repository=bindings,
            request_builder=lambda **_kwargs: invocation,
            backend=backend,
            result_mapper=to_p5_executor_outcome,
        )
        registry = default_p6_executor_registry(
            lambda _context: {},
            local_skill_dependencies=dependencies,
            local_skill_handler=P6LocalSkillReadHandler(
                read_execution=read_execution,
                result_integration=result_integration,
            ),
        )
        step_worker = P5StepExecutionWorker(
            engine=engine,
            jobs=queue,
            executors=registry,
        )
        first_job = engine.schedule_next(
            tenant_id=tenant_id,
            execution_id=execution["agent_execution_id"],
            now=now,
        )
        dispatcher = SqlAlchemyAgentRuntimeDispatcher(
            factory,
            config=AgentRuntimeDispatcherConfig(
                dispatcher_id=f"dispatcher-{worker_id}",
                queue_name=queue_name,
                leadership_lease_seconds=15,
                tenant_snapshot_limit=1,
                dispatch_batch_size=1,
                global_active_claim_cap=1,
                per_tenant_active_claim_cap=1,
            ),
            queue=queue,
        )
        assignment_source = SqlAlchemyAgentRuntimeAssignmentSource(dispatcher)
        profile = build_agent_runtime_worker_profile(
            worker_id=worker_id,
            declared_at=_utc_now(),
        )
        config = AgentRuntimeWorkerConfig(
            mode="enabled",
            profile=profile,
            lease_seconds=60,
            poll_interval_seconds=0,
        )
        heartbeat_store = SqlAlchemyWorkerHeartbeatStore(factory)
        first_run = run_bounded_agent_runtime_worker(
            config=config,
            assignment_source=assignment_source,
            handler=AgentRuntimeStepAssignmentHandler(step_worker),
            lifecycle=p6_s0._lifecycle(
                profile=profile,
                store=heartbeat_store,
                started_at=_utc_now(),
            ),
            available_executor_kinds=registry.registered_kinds,
            available_backend_profiles=registry.backend_profiles,
            max_cycles=1,
        )
        local_result = first_run["executions"][0]["handler_result"]

        second_job = engine.schedule_next(
            tenant_id=tenant_id,
            execution_id=execution["agent_execution_id"],
            now=_utc_now(),
        )
        second_claim = queue.claim(
            tenant_id=tenant_id,
            worker_id=f"{worker_id}-deterministic",
            lease_seconds=60,
            now=_utc_now(),
        )
        if second_job is None or second_claim is None:
            raise RuntimeError("P6-S7 deterministic finalization step was not claimable")
        final_execution = step_worker.run_claim(
            tenant_id=tenant_id,
            claim=second_claim,
        )
        exhausted = engine.schedule_next(
            tenant_id=tenant_id,
            execution_id=execution["agent_execution_id"],
            now=_utc_now(),
        )
        finalizer = SqlAlchemyP5PlanFinalizationService(factory)
        aggregate = finalizer.finalize(
            tenant_id=tenant_id,
            execution_id=execution["agent_execution_id"],
            created_at=_utc_now(),
        )
        replayed = SqlAlchemyP5PlanFinalizationService(factory).finalize(
            tenant_id=tenant_id,
            execution_id=execution["agent_execution_id"],
            created_at=_utc_now(),
        )
        timeline = SqlAlchemyAgentExecutionTimeline(factory).project(
            tenant_id=tenant_id,
            agent_execution_id=execution["agent_execution_id"],
        )
        restarted_timeline = SqlAlchemyAgentExecutionTimeline(factory).project(
            tenant_id=tenant_id,
            agent_execution_id=execution["agent_execution_id"],
        )
        restart_run = run_bounded_agent_runtime_worker(
            config=config,
            assignment_source=SqlAlchemyAgentRuntimeAssignmentSource(dispatcher),
            handler=lambda _assignment: (_ for _ in ()).throw(
                RuntimeError("completed LOCAL_SKILL must not be dispatched again")
            ),
            lifecycle=p6_s0._lifecycle(
                profile=profile,
                store=heartbeat_store,
                started_at=_utc_now(),
            ),
            available_executor_kinds=registry.registered_kinds,
            available_backend_profiles=registry.backend_profiles,
            max_cycles=1,
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
                    "ae_agent_result",
                    "ae_result_delivery",
                )
            }
        serialized_result = canonical_json(aggregate.result)
        checks = {
            "dispatcher_worker_consumed_local_skill": first_job is not None
            and first_run["claimed_count"] == 1
            and first_run["succeeded_count"] == 1
            and local_result["runtime_job_state"] == "DONE"
            and local_result["step_result_status"] == "SUCCEEDED",
            "exact_source_backed_read_completed": counts["ae_nsl_artifact"] == 1
            and counts["ae_nsl_step_execution"] == 1
            and counts["ae_nsl_backend_run"] == 1,
            "dependent_deterministic_step_completed": second_job["executable_step_id"]
            == final_step["executable_step_id"]
            and final_execution.step_result is not None
            and final_execution.step_result["status"] == "SUCCEEDED"
            and exhausted is None,
            "agent_result_persisted": aggregate.result["status"] == "SUCCEEDED"
            and counts["ae_agent_result"] == 1,
            "delivery_remains_pending": aggregate.delivery["state"] == "PENDING"
            and counts["ae_result_delivery"] == 1,
            "result_publish_phase_reached": aggregate.execution["state"] == "RUNNING"
            and aggregate.execution["phase"] == "RESULT_PUBLISH",
            "deterministic_result_separates_runtime_content": (
                "runtime_result_envelope" not in serialized_result
                and "100000000" not in serialized_result
                and aggregate.result["structured_result"]["output_step_results"][0][
                    "compiled_step_key"
                ]
                == final_step["compiled_step_key"]
            ),
            "finalization_restart_idempotent": replayed == aggregate,
            "timeline_restart_deterministic": timeline == restarted_timeline,
            "timeline_contains_publication_boundary": {
                event["event_type"] for event in timeline["events"]
            }
            >= {
                "NSL_REQUEST_BOUND",
                "NSL_RESULT_SUMMARY_RECORDED",
                "STEP_RESULT_RECORDED",
                "AGENT_RESULT_RECORDED",
                "RESULT_DELIVERY_CREATED",
                "RESULT_DELIVERY_CURRENT",
            },
            "worker_restart_deduplicated": restart_run["claimed_count"] == 0
            and restart_run["idle_cycle_count"] == 1,
            "canonical_cardinality": counts
            == {
                "ae_runtime_job": 2,
                "ae_runtime_job_attempt": 2,
                "ae_nsl_artifact": 1,
                "ae_nsl_step_execution": 1,
                "ae_nsl_backend_run": 1,
                "ae_step_result": 2,
                "ae_agent_result": 1,
                "ae_result_delivery": 1,
            },
            "local_skill_lineage": local_step["executor_kind"] == "LOCAL_SKILL",
        }
        return {
            "checks": checks,
            "row_counts": {
                **counts,
                "timeline_events": len(timeline["events"]),
                "timeline_gaps": len(timeline["projection_gaps"]),
            },
            "cleanup_counts": _cleanup_s7_rows(
                factory,
                tenant_id=tenant_id,
                worker_id=worker_id,
                queue_name=queue_name,
            ),
        }
    finally:
        _cleanup_s7_rows(
            factory,
            tenant_id=tenant_id,
            worker_id=worker_id,
            queue_name=queue_name,
        )


def _context_projection(
    factory: object,
    tenant_id: str,
    execution: Mapping[str, Any],
    now: str,
) -> dict[str, Any]:
    with factory() as session:
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
    context_ref = (
        f"AE:AGENT_CONTEXT:{context['context_id']}:{context['context_generation']}"
    )
    principal_id = context["context_json"]["identity"]["principal_id"]
    return build_context_projection(
        agent_context_ref=context_ref,
        agent_context_hash=context["context_hash"],
        runtime_context_entries=(
            {
                "path": "user.team_id",
                "value": "TEAM-FINANCE",
                "classification": "INTERNAL",
                "source_ref": context_ref,
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
            "policy_ref": f"OA:DATA_POLICY:p6-s7:{now[:10]}",
            "max_trace_classification": "CONFIDENTIAL",
            "snapshot_retention_days": 30,
            "audit_retention_days": 90,
        },
    )


def _cleanup_s7_rows(
    factory: object, *, tenant_id: str, worker_id: str, queue_name: str
) -> dict[str, int]:
    counts: dict[str, int] = {}
    tables = (
        "ae_result_delivery",
        "ae_agent_result",
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
        counts["dispatcher_lease"] = int(
            session.execute(
                text("DELETE FROM ae_rt_dispatch_lease WHERE queue_name = :queue_name"),
                {"queue_name": queue_name},
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
        counts["s7_remaining"] = sum(
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


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6-S7",
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
        "p6_s7_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"actual_postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"step_results={rows.get('ae_step_result', 0)} "
        f"agent_results={rows.get('ae_agent_result', 0)} "
        f"events={rows.get('timeline_events', 0)} "
        f"remaining={cleanup.get('s7_remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p6_s7_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
