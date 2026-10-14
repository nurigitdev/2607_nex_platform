#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
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
from nex_ae_api.agent_runtime_worker import (
    AgentRuntimeWorkerConfig,
    build_agent_runtime_worker_check,
    build_agent_runtime_worker_profile,
)
from nex_ae_api.nsl_read_backends import (
    NSLReadBackendError,
    NSLReadExecutionService,
    SqlAlchemyNSLBackendRunRepository,
    V01ProcessEntrypoint,
    build_v01_process_isolated_backend,
)
from nex_ae_api.nsl_step_executions import (
    NSLStepExecutionError,
    SqlAlchemyNSLStepExecutionRepository,
    build_context_projection,
)
from nex_ae_api.planning_capabilities import (
    DEFAULT_P5_CAPABILITIES,
    build_local_skill_capability,
)
from nex_ae_api.skill_artifacts import (
    SkillArtifactGatewayError,
    SqlAlchemySkillArtifactRepository,
)
from nex_ae_api.step_executors import (
    LocalSkillExecutorDependencies,
    P5ExecutorOutcome,
    P5StepExecutorError,
    default_p6_executor_registry,
)
from nex_runtime import load_env_file, redact_database_url
from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p6_s5_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P6_S5_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
NSL_SOURCE_ENV = "NEX_AE_P6_S5_NSL_SOURCE"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
EXPECTED_NSL_SHA = "803f22aadc3946a48b05472c80b60fe11d9d9554"
REQUIRED_MIGRATION = "2204_ae_nsl_backend_run"
SKILL_ID = "FINANCE.PROJECT_BUDGET_CHECK"
SKILL_VERSION = "1.0.0"
SEMANTIC_HASH = (
    "sha256:ba75f7b96d08f0a8bff6ff1917b127c36cf2a0c96f1d29b7dc883674a4678b56"
)
PACKAGE_HASH = "sha256:9e538ec352bddc4ba4a43ac1510759c02491f74f52c50bf4f817f94c9925622e"
ARTIFACT = (
    ROOT / "docs/transition/P6/contracts/examples/p6-golden-verified-artifact-v1.json"
)


class _ArtifactGateway:
    def resolve_verified(self, **_kwargs: Any) -> dict[str, Any]:
        return {}


class _BindingRepository:
    def bind_request(self, **_kwargs: Any) -> dict[str, Any]:
        return {}


class _ActivationBackend:
    backend_profile = "NSL_V01_PROCESS_ISOLATED"

    def execute(self, _request: Mapping[str, Any]) -> dict[str, Any]:
        return {}


class _GoldenWorkerSession:
    def __init__(self, worker: object, audit: object) -> None:
        self.worker = worker
        self._audit = audit

    def evidence_refs(self) -> list[str]:
        events = list(getattr(self._audit, "events", ()))
        refs = {f"NSL:AUDIT:{event.event_hash}" for event in events}
        refs.update(
            f"NSL:SNAPSHOT:{event.payload['snapshot_ref']}"
            for event in events
            if isinstance(event.payload, Mapping) and event.payload.get("snapshot_ref")
        )
        if not events or not any(ref.startswith("NSL:SNAPSHOT:") for ref in refs):
            raise RuntimeError("source-backed worker did not publish required evidence")
        return sorted(refs)


class _GoldenWorkerFactory:
    def __init__(self, nsl_source: str) -> None:
        self._nsl_source = nsl_source

    def __call__(self, artifact_handle: str, progress: object) -> _GoldenWorkerSession:
        source_root = Path(self._nsl_source)
        if str(source_root) not in sys.path:
            sys.path.insert(0, str(source_root))
        from nsl.adapters.ed25519 import Ed25519PackageSigner, Ed25519TrustStore
        from nsl.api import (
            RuntimeEngine,
            SkillExecutionWorker,
            VerifiedPackageSkillResolver,
            WorkerEvidencePolicy,
        )
        from nsl.audit import InMemoryAuditSink, InMemorySnapshotStore
        from nsl.compiler import NslCompiler
        from nsl.nsp import NspBuilder
        from nsl.nsp_verification import NspVerificationPolicy, NspVerifier
        from nsl.security import RuntimeEnvironment
        from nsl.vertical_slice import build_mock_executor, build_tool_catalog

        catalog = build_tool_catalog()
        source = (source_root / "examples/project_budget_check.ns").read_text(
            encoding="utf-8"
        )
        compilation = NslCompiler(catalog).compile(source)
        if compilation.nso_bytes is None:
            raise RuntimeError("golden NSL source did not compile")
        signer = Ed25519PackageSigner("publisher.p6-golden-1", bytes(range(1, 33)))
        package = NspBuilder().build((compilation.nso_bytes,), signer=signer)
        trust = Ed25519TrustStore({signer.key_id: signer.public_key_bytes})
        verified = NspVerifier(
            policy=NspVerificationPolicy(RuntimeEnvironment.PRODUCTION),
            signature_verifier=trust,
        ).verify(package.data)
        package_digest = verified.package_hash.removeprefix("sha256:")
        expected_handle = f"nsp+sha256://{package_digest}/{SKILL_ID}@{SKILL_VERSION}"
        if (
            artifact_handle != expected_handle
            or verified.package_hash != PACKAGE_HASH
            or verified.skills[0].skill.semantic_hash != SEMANTIC_HASH
        ):
            raise RuntimeError("golden NSL artifact identity drifted")
        audit = InMemoryAuditSink()
        snapshots = InMemorySnapshotStore()
        worker = SkillExecutionWorker(
            runtime=RuntimeEngine(catalog),
            resolver=VerifiedPackageSkillResolver((verified,)),
            tools=build_mock_executor(catalog),
            audit_sink=audit,
            snapshot_store=snapshots,
            progress_sink=progress,
            evidence_policy=WorkerEvidencePolicy.SNAPSHOT_REQUIRED,
        )
        return _GoldenWorkerSession(worker, audit)


def _sleep_target(payload: bytes) -> bytes:
    time.sleep(0.2)
    return payload


def _crash_target(_payload: bytes) -> bytes:
    os._exit(23)


def run_p6_s5_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-S5",
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
        nsl_source = _verified_nsl_source(Path(nsl_source_value))
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
            database_url,
            verifier=lambda fixture: _verify_nsl_read_backend_guarded(
                fixture, nsl_source
            ),
        )
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P6-S5",
                "profile": "test",
                "database_env": DATABASE_ENV,
                "redacted_database_url": redact_database_url(database_url),
                "nsl_source_revision": EXPECTED_NSL_SHA,
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
            evidence["failure_code"] = "p6_s5_postgres_smoke_failed"
        return evidence
    except (
        MigrationError,
        NSLReadBackendError,
        NSLStepExecutionError,
        OSError,
        P5StepExecutorError,
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
    finally:
        p5_s5.build_capability_snapshot = original_snapshot_builder
        p5_s5.build_deterministic_agent_plan = original_plan_builder


def _verified_nsl_source(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not (resolved / "nsl/api/__init__.py").is_file():
        raise ValueError("NSL source does not expose the stable nsl.api package")
    head = subprocess.run(
        ["git", "-C", str(resolved), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(resolved), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != EXPECTED_NSL_SHA or dirty:
        raise RuntimeError("NSL source revision or worktree cleanliness is invalid")
    return resolved


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


def _activation_dependencies() -> LocalSkillExecutorDependencies:
    return LocalSkillExecutorDependencies(
        artifact_gateway=_ArtifactGateway(),
        binding_repository=_BindingRepository(),
        request_builder=lambda **_kwargs: {},
        backend=_ActivationBackend(),
        result_mapper=lambda **_kwargs: P5ExecutorOutcome(
            state="SUCCEEDED",
            result_contract_ref="contract://nex/p6/step-result/v1.2",
            result_payload={"status": "COMPLETED"},
        ),
    )


def _verify_nsl_read_backend(
    fixture: Mapping[str, Any], nsl_source: Path
) -> dict[str, Any]:
    from nsl.process_isolation import IsolatedProcessStatus, ProcessIsolatedRuntime

    factory = fixture["factory"]
    tenant_id = str(fixture["tenant_id"])
    execution = dict(fixture["execution"])
    step = dict(fixture["executable_plan"])["steps"][0]
    now = str(fixture["now"])
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    artifacts = SqlAlchemySkillArtifactRepository(factory)
    artifacts.save(tenant_id=tenant_id, artifact=artifact)

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
        database, role = session.execute(
            text("SELECT current_database(), current_user")
        ).one()
    principal_id = context["context_json"]["identity"]["principal_id"]
    projection = build_context_projection(
        agent_context_ref=(
            f"AE:AGENT_CONTEXT:{context['context_id']}:{context['context_generation']}"
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
            "scopes": [
                "nsl:replay:read",
                "nsl:skill:execute",
                "project:budget:read",
            ],
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
            "policy_ref": "OA:DATA_POLICY:p6-s5-smoke",
            "max_trace_classification": "CONFIDENTIAL",
            "snapshot_retention_days": 30,
            "audit_retention_days": 90,
        },
    )
    ids = iter((str(uuid4()), str(uuid4())))
    bindings = SqlAlchemyNSLStepExecutionRepository(factory, id_factory=ids.__next__)
    bound = bindings.bind_request(
        tenant_id=tenant_id,
        executable_step_id=step["executable_step_id"],
        verified_artifact_ref=artifact["artifact_ref"],
        context_projection=projection,
        compiled_inputs={"year": 2026},
        input_provenance={"year": "USER"},
        now=now,
    )
    process_target = V01ProcessEntrypoint(_GoldenWorkerFactory(str(nsl_source)))
    backend = build_v01_process_isolated_backend(process_target, timeout_ms=30_000)
    runs = SqlAlchemyNSLBackendRunRepository(factory)
    service = NSLReadExecutionService(
        bindings=bindings,
        artifacts=artifacts,
        backend=backend,
        runs=runs,
    )
    record = service.execute_bound(
        tenant_id=tenant_id,
        executable_step_id=step["executable_step_id"],
        attempt_no=1,
    )
    replay = service.execute_bound(
        tenant_id=tenant_id,
        executable_step_id=step["executable_step_id"],
        attempt_no=1,
    )
    restarted = SqlAlchemyNSLBackendRunRepository(factory).get(
        tenant_id=tenant_id,
        nsl_execution_id=bound["binding"]["nsl_execution_id"],
        attempt_no=1,
    )
    timeout_result = ProcessIsolatedRuntime(
        _sleep_target, timeout_ms=20, max_payload_bytes=1024
    ).execute(b"timeout")
    crash_result = ProcessIsolatedRuntime(
        _crash_target, timeout_ms=1000, max_payload_bytes=1024
    ).execute(b"crash")

    registry = default_p6_executor_registry(
        lambda _context: {},
        local_skill_dependencies=_activation_dependencies(),
        local_skill_handler=lambda _context, _dependencies: P5ExecutorOutcome(
            state="SUCCEEDED",
            result_contract_ref="contract://nex/p6/step-result/v1.2",
            result_payload={"activation": "verified"},
        ),
    )
    startup = build_agent_runtime_worker_check(
        AgentRuntimeWorkerConfig(
            mode="enabled",
            profile=build_agent_runtime_worker_profile(
                worker_id="worker-p6-s5-smoke", declared_at=now
            ),
        ),
        available_executor_kinds=registry.registered_kinds,
        available_backend_profiles=registry.backend_profiles,
    )

    with factory() as session:
        row = (
            session.execute(
                text(
                    "SELECT isolation_status, runtime_status, record_hash, record_json "
                    "FROM ae_nsl_backend_run WHERE tenant_id = :tenant_id "
                    "AND nsl_execution_id = :nsl_execution_id AND attempt_no = 1"
                ),
                {
                    "tenant_id": tenant_id,
                    "nsl_execution_id": bound["binding"]["nsl_execution_id"],
                },
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
        parent_alive = session.execute(text("SELECT 1")).scalar_one() == 1
    persisted = row["record_json"]
    if isinstance(persisted, str):
        persisted = json.loads(persisted)
    if record["runtime_result_envelope"] is None:
        raise RuntimeError(
            "source-backed backend failed closed: "
            f"{record['isolation_status']}/{record['error_code']}"
        )
    result = record["runtime_result_envelope"]["runtime_result"]
    evidence = record["evidence_refs"]
    serialized_record = canonical_json(record)
    checks = {
        "actual_test_database": database == EXPECTED_DATABASE,
        "actual_test_role": role == EXPECTED_ROLE,
        "migration_recorded": migration_recorded,
        "worker_startup_ready": startup["status"] == "PASS"
        and startup["startup_ready"] is True,
        "source_backed_signed_read_completed": record["isolation_status"] == "COMPLETED"
        and record["runtime_status"] == "COMPLETED"
        and result["semantic_hash"] == SEMANTIC_HASH,
        "read_result_shape": result["resources"]["tool_calls"] == 2
        and result["resources"]["emitted_rows"] == 1
        and len(result["outputs"]) == 1,
        "ordered_progress_bridge": [
            event["state"] for event in record["progress_events"]
        ]
        == ["STARTED", "SKILL_RESOLVED", "RUNNING", "COMPLETED"],
        "audit_evidence_bridge": any(ref.startswith("NSL:AUDIT:") for ref in evidence),
        "snapshot_evidence_bridge": any(
            ref.startswith("NSL:SNAPSHOT:") for ref in evidence
        ),
        "restart_safe_attempt_replay": record == replay == restarted == persisted,
        "database_projection_matches": row["isolation_status"] == "COMPLETED"
        and row["runtime_status"] == "COMPLETED"
        and row["record_hash"] == record["record_hash"],
        "timeout_isolated": timeout_result.status is IsolatedProcessStatus.TIMED_OUT,
        "crash_isolated": crash_result.status == IsolatedProcessStatus.CRASHED
        and crash_result.exit_code not in {None, 0},
        "parent_and_database_survived": parent_alive,
        "private_material_absent": "publisher.p6-golden-1" not in serialized_record
        and "bytes(range" not in serialized_record,
    }

    with factory.begin() as session:
        deleted_runs = int(
            session.execute(
                text("DELETE FROM ae_nsl_backend_run WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            ).rowcount
            or 0
        )
        deleted_bindings = int(
            session.execute(
                text("DELETE FROM ae_nsl_step_execution WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            ).rowcount
            or 0
        )
        deleted_artifacts = int(
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
            for table in (
                "ae_nsl_backend_run",
                "ae_nsl_step_execution",
                "ae_nsl_artifact",
            )
        )
    checks["s5_cleanup_complete"] = remaining == 0
    return {
        "checks": checks,
        "row_counts": {
            "backend_runs": 1,
            "progress_events": len(record["progress_events"]),
            "evidence_refs": len(evidence),
        },
        "isolation_probe": {
            "timeout_status": str(timeout_result.status),
            "timeout_exit_code": timeout_result.exit_code,
            "crash_status": str(crash_result.status),
            "crash_exit_code": crash_result.exit_code,
        },
        "cleanup_counts": {
            "backend_runs_deleted": deleted_runs,
            "bindings_deleted": deleted_bindings,
            "artifacts_deleted": deleted_artifacts,
            "s5_remaining": remaining,
        },
    }


def _verify_nsl_read_backend_guarded(
    fixture: Mapping[str, Any], nsl_source: Path
) -> dict[str, Any]:
    try:
        return _verify_nsl_read_backend(fixture, nsl_source)
    finally:
        _cleanup_nsl_rows(fixture["factory"], str(fixture["tenant_id"]))


def _cleanup_nsl_rows(factory: object, tenant_id: str) -> None:
    with factory.begin() as session:
        for table in (
            "ae_nsl_backend_run",
            "ae_nsl_step_execution",
            "ae_nsl_artifact",
        ):
            session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6-S5",
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
        "p6_s5_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"actual_postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"runs={rows.get('backend_runs', 0)} "
        f"progress={rows.get('progress_events', 0)} "
        f"remaining={cleanup.get('s5_remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p6_s5_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
