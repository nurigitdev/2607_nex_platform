#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p6_ca02_s3_in_process_smoke as p6_ca02_s3  # noqa: E402
import run_p6_s5_postgres_smoke as p6_s5  # noqa: E402
import run_p6_s7_postgres_smoke as p6_s7  # noqa: E402
from nex_ae_api.agent_context import (  # noqa: E402
    SqlAlchemyAgentContextRepository,
    TrustedContextResolution,
    runtime_policy_ref_from_compatibility_policy,
)
from nex_ae_api.agent_execution import (  # noqa: E402
    AgentExecutionAdmissionService,
    SqlAlchemyAgentExecutionRepository,
)
from nex_ae_api.agent_identity import SqlAlchemyAgentIdentityRegistry  # noqa: E402
from nex_ae_api.agent_plans import SqlAlchemyAgentPlanRepository  # noqa: E402
from nex_ae_api.context_candidate_generation import (  # noqa: E402
    LiveContextCandidateService,
)
from nex_ae_api.executable_plans import (  # noqa: E402
    SqlAlchemyExecutablePlanRepository,
)
from nex_ae_api.intent_candidate_generation import (  # noqa: E402
    LiveIntentCandidateService,
)
from nex_ae_api.mo_generation_client import (  # noqa: E402
    AeMoGenerationClient,
    AeMoGenerationClientError,
    AeMoGenerationReadiness,
    AeMoGenerationResult,
    build_default_ae_mo_generation_client,
)
from nex_ae_api.plan_candidate_generation import LivePlanCandidateService  # noqa: E402
from nex_ae_api.plan_validation import SqlAlchemyPlanValidationRepository  # noqa: E402
from nex_ae_api.planning_capabilities import (  # noqa: E402
    REPORT_CAPABILITY_ID,
    SqlAlchemyCapabilitySnapshotRepository,
    build_capability_snapshot,
    build_local_skill_capability,
)
from nex_ae_api.prompt_persistence import SqlAlchemyAePromptRegistryStore  # noqa: E402
from nex_ae_api.prompts import seed_ae_prompt_registry  # noqa: E402
from nex_ae_api.runtime_policy import resolve_runtime_policy  # noqa: E402
from nex_ae_api.semantic_candidate_admission import (  # noqa: E402
    DeterministicCandidateAdmissionService,
    SemanticCandidateAdmissionRequest,
    SemanticCandidateAdmissionError,
)
from nex_ae_api.semantic_candidate_evidence import (  # noqa: E402
    LocalSemanticCandidateStorage,
    SqlAlchemySemanticCandidateEvidenceRepository,
)
from nex_ae_api.semantic_candidates import (  # noqa: E402
    SemanticCalibrationPolicy,
    SemanticCalibrationRegistry,
)
from nex_ae_api.work_intent import SqlAlchemyWorkIntentRepository  # noqa: E402
from nex_mo.providers import register_mock_provider_routes  # noqa: E402
from nex_mo.provider_readiness_api import (  # noqa: E402
    register_provider_readiness_routes,
)
from nex_mo.provider_readiness_service import ProviderReadinessService  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_service_app,
    load_env_file,
    redact_database_url,
    sqlalchemy_database_url,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref  # noqa: E402
from run_migrations import MigrationError, run_service_migrations  # noqa: E402
from run_p5_s3_postgres_smoke import (  # noqa: E402
    _cleanup as _cleanup_planning,
    _seed_workspace_conversation,
)
from run_protected_dgx_live_profile import (  # noqa: E402
    protected_dgx_vllm_profile_defaults,
)


SCHEMA_VERSION = "p65_s7_postgres_live_e2e.v1"
SMOKE_ENV = "NEX_AE_P65_S7_POSTGRES_LIVE_E2E"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
NSL_SOURCE_ENV = "NEX_AE_P65_S7_NSL_SOURCE"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2300_ae_semantic_candidate"
NOW = "2026-10-17T06:30:00Z"
GOLDEN_PROMPT = (
    "내가 접근할 수 있는 프로젝트 예산 자료를 확인해서 총 예산, "
    "집행액, 잔액을 한국어로 요약해줘."
)
PROTECTED_ENV_KEYS = (
    DATABASE_ENV,
    "NEX_MO_VLLM_API_KEY",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_AE_TO_MO_SERVICE_TOKEN",
)

SmokeExecutor = Callable[..., dict[str, Any]]


@dataclass
class CountingGenerationClient:
    delegate: AeMoGenerationClient
    readiness_calls: int = 0
    generation_stages: list[str] = field(default_factory=list)

    def check_required_mode_readiness(
        self, *, request_id: str, trace_id: str
    ) -> AeMoGenerationReadiness:
        self.readiness_calls += 1
        return self.delegate.check_required_mode_readiness(
            request_id=request_id,
            trace_id=trace_id,
        )

    def generate_candidate(
        self,
        *,
        semantic_stage: str,
        messages: Sequence[Mapping[str, Any]],
        request_id: str,
        trace_id: str,
    ) -> AeMoGenerationResult:
        self.generation_stages.append(semantic_stage)
        return self.delegate.generate_candidate(
            semantic_stage=semantic_stage,
            messages=messages,
            request_id=request_id,
            trace_id=trace_id,
        )


@dataclass(frozen=True)
class TestClientRequester:
    client: TestClient

    def __call__(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> Any:
        del timeout
        parsed = urlsplit(url)
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        return self.client.request(method, target, json=json, headers=dict(headers))


class TrustedResolver:
    def __init__(self, interaction_id: str, built_at: str = NOW) -> None:
        self.interaction_id = interaction_id
        self.built_at = built_at

    def resolve(self, _request: Any) -> TrustedContextResolution:
        return TrustedContextResolution(
            project_ref=None,
            authority_ref="OA:EAC:p65-s7-live-e2e",
            resolved_entities=(),
            retrieval_refs=(),
            evidence_refs=(),
            conflicts=(),
            degradations=(),
            context_manifest=(
                {
                    "kind": "INTERACTION_REF",
                    "source_ref": f"AE:INTERACTION:{self.interaction_id}",
                    "source_version": "1",
                    "content_hash": semantic_sha256_hash_ref(
                        {"interaction_id": self.interaction_id}
                    ),
                    "as_of": self.built_at,
                },
            ),
            budget_tokens=4096,
            estimated_used_tokens=128,
        )


def run_p65_s7_postgres_live_e2e(
    environ: Mapping[str, str] | None = None,
    *,
    executor: SmokeExecutor | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6.5-S7",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
            "actual_remote_provider": False,
        }
    database_url = env.get(DATABASE_ENV, "")
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    if not _target_url_allowed(database_url):
        return _failure(
            "target_not_allowed",
            f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
        )
    nsl_source_value = env.get(NSL_SOURCE_ENV, "")
    if not nsl_source_value:
        return _failure("nsl_source_missing", f"{NSL_SOURCE_ENV} is required.")

    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_BASE_URL": "http://p65-s7-in-process-mo",
    }
    missing = _missing_provider_configuration(effective_env)
    if missing:
        return _failure(
            "provider_configuration_missing",
            "Protected generation provider configuration is incomplete.",
            diagnostics={"missing_env": missing},
        )
    try:
        nsl_source = Path(nsl_source_value).resolve(strict=True)
        nsl_lock = json.loads(p6_ca02_s3.DEFAULT_LOCK.read_text(encoding="utf-8"))
        p6_ca02_s3._installed_package_evidence(nsl_source, nsl_lock)
    except (OSError, RuntimeError, ValueError) as exc:
        return _failure("nsl_source_invalid", type(exc).__name__)

    try:
        migration = run_service_migrations(
            "nex-ae-api", database_url=database_url, profile="test"
        )
        execute = executor or _execute_live_e2e
        execution = execute(
            database_url=database_url,
            nsl_source=nsl_source,
            runtime_environ=effective_env,
        )
        migration_current = (
            REQUIRED_MIGRATION in migration.planned
            and migration.planned[-1] == REQUIRED_MIGRATION
            and len(migration.planned)
            == len(migration.applied) + len(migration.skipped)
        )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6.5-S7",
            "status": "PASS",
            "profile": "test",
            "platform_revision": _platform_revision(),
            "nsl_revision": nsl_lock["source_revision"],
            "nsl_wheel_sha256": nsl_lock["wheel_sha256"],
            "database_env": DATABASE_ENV,
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "planned_count": len(migration.planned),
                "applied_count": len(migration.applied),
                "skipped_count": len(migration.skipped),
                "latest_version": migration.planned[-1],
            },
            **execution,
        }
        evidence["checks"] = {
            "migration_current": migration_current,
            **dict(execution.get("checks") or {}),
        }
        if not all(evidence["checks"].values()):
            evidence["status"] = "FAIL"
            evidence["failure_code"] = "p65_s7_acceptance_failed"
        _assert_evidence_redacted(evidence, effective_env)
        return evidence
    except (
        AeMoGenerationClientError,
        MigrationError,
        OSError,
        RuntimeError,
        SemanticCandidateAdmissionError,
        SQLAlchemyError,
        ValueError,
    ) as exc:
        failure = _failure("execution_failed", _safe_error_code(exc))
        _assert_evidence_redacted(failure, effective_env)
        return failure
    except Exception as exc:  # pragma: no cover - defensive protected boundary
        failure = _failure("unexpected_failure", type(exc).__name__)
        _assert_evidence_redacted(failure, effective_env)
        return failure


def _execute_live_e2e(  # pragma: no cover - actual PostgreSQL/DGX/NSL evidence
    *,
    database_url: str,
    nsl_source: Path,
    runtime_environ: dict[str, str],
) -> dict[str, Any]:
    original_environ = dict(os.environ)
    os.environ.clear()
    os.environ.update(runtime_environ)
    try:
        mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
        register_mock_provider_routes(mo_app)
        register_provider_readiness_routes(
            mo_app,
            service=ProviderReadinessService(environ=runtime_environ),
        )
        with TestClient(mo_app) as mo_test_client:
            client = CountingGenerationClient(
                build_default_ae_mo_generation_client(
                    runtime_environ,
                    requester=TestClientRequester(mo_test_client),
                )
            )
            readiness = client.check_required_mode_readiness(
                request_id=f"p65-s7-readiness-{uuid4().hex}",
                trace_id=uuid4().hex,
            )
            if (
                readiness.provider_mode != "live"
                or readiness.readiness_status != "READY"
                or readiness.source != "active_preflight"
            ):
                raise RuntimeError("actual MO provider readiness is not READY")
            return _execute_postgres_journey(
                database_url=database_url,
                nsl_source=nsl_source,
                client=client,
                readiness=readiness,
            )
    finally:
        os.environ.clear()
        os.environ.update(original_environ)


def _execute_postgres_journey(  # pragma: no cover - protected integration body
    *,
    database_url: str,
    nsl_source: Path,
    client: CountingGenerationClient,
    readiness: AeMoGenerationReadiness,
) -> dict[str, Any]:
    engine = create_engine(
        sqlalchemy_database_url(database_url), future=True, pool_pre_ping=True
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    token = uuid4().hex
    tenant_id = f"tenant-p65-s7-{token[:12]}"
    principal_id = f"user-p65-s7-{token[:12]}"
    workspace_id = str(uuid4())
    conversation_id = str(uuid4())
    interaction_id = str(uuid4())
    trace_id = uuid4().hex
    request_id = f"p65-s7-{token}"
    started_at = datetime.now(UTC)
    now = started_at.isoformat().replace("+00:00", "Z")
    cleanup_counts: dict[str, int] = {}
    runtime_evidence: dict[str, Any] = {}
    row_counts: dict[str, int] = {}
    private_storage_zero_residue = False
    database = ""
    role = ""
    prompt_versions: list[Mapping[str, Any]] = []
    storage_root: Path | None = None

    executions = SqlAlchemyAgentExecutionRepository(factory)
    admission = AgentExecutionAdmissionService(
        identities=SqlAlchemyAgentIdentityRegistry(factory),
        executions=executions,
        mode="required",
    )
    prompt_store = SqlAlchemyAePromptRegistryStore(factory)
    policies = _calibration_registry(readiness)
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
        seed_ae_prompt_registry(prompt_store)
        with TemporaryDirectory(prefix="nex-p65-s7-") as directory:
            storage_root = Path(directory)
            service = DeterministicCandidateAdmissionService(
                mode="required",
                admission=admission,
                intent_stage=LiveIntentCandidateService(client, prompt_store, policies),
                context_stage=LiveContextCandidateService(client, prompt_store, policies),
                plan_stage=LivePlanCandidateService(client, prompt_store, policies),
                evidence=SqlAlchemySemanticCandidateEvidenceRepository(factory),
                candidate_storage=LocalSemanticCandidateStorage(storage_root),
                work_intents=SqlAlchemyWorkIntentRepository(factory),
                contexts=SqlAlchemyAgentContextRepository(factory),
                capabilities=SqlAlchemyCapabilitySnapshotRepository(factory),
                plans=SqlAlchemyAgentPlanRepository(factory),
                validations=SqlAlchemyPlanValidationRepository(factory),
                executable_plans=SqlAlchemyExecutablePlanRepository(factory),
                executions=executions,
                clock=lambda: started_at,
            )
            local_capability = build_local_skill_capability(
                skill_id=p6_s5.SKILL_ID,
                exact_skill_version=p6_s5.SKILL_VERSION,
                skill_semantic_hash=p6_s5.SEMANTIC_HASH,
                input_contract_ref="contract://nex/p6/skill-execution-request/v1",
                output_contract_ref="contract://nex/p6/step-result/v1.2",
                runtime_contract_ref="contract://nex/nsl/read-runtime/v0.1",
                trust_policy_id="nsl.production.ed25519.v1",
            )
            report_capability = next(
                item
                for item in p6_s5.DEFAULT_P5_CAPABILITIES
                if item["capability_id"] == REPORT_CAPABILITY_ID
            )
            runtime_policy = resolve_runtime_policy(
                {
                    "user_message": GOLDEN_PROMPT,
                    "generation": {"execution_mode": "DOCUMENT_SUMMARY"},
                }
            )
            request = SemanticCandidateAdmissionRequest(
                tenant_id=tenant_id,
                owner_subject_id=principal_id,
                profile_ref="urn:nex:agent-profile:ia:default:v1",
                interaction_id=interaction_id,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                correlation_id=f"p65-s7:{trace_id}",
                request_id=request_id,
                trace_id=trace_id,
                user_prompt=GOLDEN_PROMPT,
                base_context={
                    "interaction_text": GOLDEN_PROMPT,
                    "conversation_summary": None,
                    "resource_label_hints": ["2026 프로젝트 예산 현황"],
                },
                runtime_policy_ref=runtime_policy_ref_from_compatibility_policy(
                    runtime_policy
                ),
                context_resolver=TrustedResolver(interaction_id, now),
                capability_snapshot=build_capability_snapshot(
                    tenant_id=tenant_id,
                    capability_snapshot_id=str(uuid4()),
                    snapshot_version=1,
                    created_at=now,
                    capabilities=(local_capability, report_capability),
                ),
                retrieval_enabled=True,
                authorized_resource_context_available=True,
                trusted_execution_mode="DOCUMENT_SUMMARY",
            )
            result = service.admit_and_compile(request)
            stages_after_first = tuple(client.generation_stages)
            if result.status != "COMPILED" or result.validation_status != "VALID":
                raise RuntimeError("semantic candidate journey did not compile")
            execution = executions.get(tenant_id, str(result.agent_execution_id))
            executable_plan = SqlAlchemyExecutablePlanRepository(factory).get(
                tenant_id=tenant_id,
                executable_plan_id=str(result.executable_plan_id),
            )
            if execution is None or executable_plan is None:
                raise RuntimeError("compiled runtime lineage is incomplete")
            if [step["executor_kind"] for step in executable_plan["steps"]] != [
                "LOCAL_SKILL",
                "DETERMINISTIC_REPORT",
            ]:
                raise RuntimeError("live plan did not bind LOCAL_SKILL then REPORT")

            runtime_evidence = p6_s7._verify_ia_read_closure(
                {
                    "factory": factory,
                    "tenant_id": tenant_id,
                    "execution": execution,
                    "executable_plan": executable_plan,
                    "now": now,
                },
                nsl_source=nsl_source,
                backend_profile=p6_s7.NSL_V01_IN_PROCESS_BACKEND,
            )
            resumed = service.admit_and_compile(request)
            private_files = tuple(storage_root.rglob("*.json"))
            with engine.connect() as connection:
                database, role = connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
                row_counts = {
                    table: _tenant_count(connection, table, tenant_id)
                    for table in (
                        "ae_semantic_candidate",
                        "ae_work_intent",
                        "ae_agent_context",
                        "ae_agent_plan",
                        "ae_plan_validation",
                        "ae_executable_plan",
                        "ae_executable_step",
                        "ae_agent_execution",
                    )
                }
                prompt_versions = list(
                    connection.execute(
                        text(
                            "SELECT b.binding_key, v.version "
                            "FROM ae_prompt_bindings AS b "
                            "JOIN ae_prompt_template_versions AS v "
                            "ON v.prompt_template_version_id = "
                            "b.prompt_template_version_id "
                            "WHERE b.binding_key IN "
                            "('ae.intent_resolution.default', "
                            "'ae.context_candidate_extraction.default', "
                            "'ae.plan_builder.default') ORDER BY b.binding_key"
                        )
                    ).mappings()
                )
            checks = {
                "actual_database_identity": (
                    database == EXPECTED_DATABASE and role == EXPECTED_ROLE
                ),
                "actual_live_provider_ready": (
                    readiness.provider_mode == "live"
                    and readiness.readiness_status == "READY"
                    and readiness.source == "active_preflight"
                ),
                "three_actual_provider_calls": stages_after_first
                == ("INTENT", "CONTEXT", "PLAN"),
                "minimum_golden_journey_compiled": (
                    result.status == "COMPILED"
                    and result.validation_status == "VALID"
                    and [stage.semantic_stage for stage in result.stages]
                    == ["INTENT", "CONTEXT", "PLAN"]
                ),
                "model_revision_consistent": all(
                    stage.model_profile == readiness.model_profile
                    and stage.model_ref == readiness.model_ref
                    for stage in result.stages
                ),
                "exact_prompt_versions_recorded": (
                    len(prompt_versions) == 3
                    and {
                        row["binding_key"]: row["version"]
                        for row in prompt_versions
                    }
                    == {
                        "ae.context_candidate_extraction.default": "v2",
                        "ae.intent_resolution.default": "v1",
                        "ae.plan_builder.default": "v1",
                    }
                ),
                "candidate_hashes_recorded": all(
                    stage.candidate_hash.startswith("sha256:")
                    for stage in result.stages
                ),
                "canonical_rows_are_singletons": (
                    row_counts["ae_semantic_candidate"] == 3
                    and all(
                        row_counts[table] == 1
                        for table in (
                            "ae_work_intent",
                            "ae_agent_context",
                            "ae_agent_plan",
                            "ae_plan_validation",
                            "ae_executable_plan",
                            "ae_agent_execution",
                        )
                    )
                    and row_counts["ae_executable_step"] == 2
                ),
                "extended_local_skill_result_delivery": all(
                    runtime_evidence["checks"].values()
                ),
                "restart_reuses_candidates": (
                    tuple(client.generation_stages) == stages_after_first
                    and all(stage.resumed for stage in resumed.stages)
                    and resumed.executable_plan_hash == result.executable_plan_hash
                ),
                "owner_private_candidate_payloads": len(private_files) == 3,
            }
            cleanup_counts = _cleanup(
                factory,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
        private_storage_zero_residue = storage_root is not None and not storage_root.exists()
    finally:
        try:
            if not cleanup_counts:
                cleanup_counts = _cleanup(
                    factory,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                )
        finally:
            engine.dispose()

    checks["database_zero_residue"] = cleanup_counts.get("remaining", -1) == 0
    checks["private_storage_zero_residue"] = private_storage_zero_residue
    return {
        "actual_postgres": True,
        "actual_remote_provider": True,
        "provider_mode": readiness.provider_mode,
        "provider_profile": readiness.model_profile,
        "model_ref": readiness.model_ref,
        "deployment_id": readiness.deployment_id,
        "provider_call_counts": {
            "readiness": client.readiness_calls,
            "generation": len(client.generation_stages),
            "semantic_stages": list(client.generation_stages),
        },
        "database": database,
        "role": role,
        "prompt_registry_versions": [dict(row) for row in prompt_versions],
        "checks": checks,
        "row_counts": row_counts,
        "runtime_row_counts": runtime_evidence.get("row_counts", {}),
        "cleanup_counts": cleanup_counts,
        "runtime_cleanup_counts": runtime_evidence.get("cleanup_counts", {}),
        "lineage": {
            "agent_execution_id": result.agent_execution_id,
            "work_intent_id": result.work_intent_id,
            "agent_context_id": result.agent_context_id,
            "agent_plan_id": result.agent_plan_id,
            "executable_plan_id": result.executable_plan_id,
            "executable_plan_hash": result.executable_plan_hash,
            "candidate_hashes": [stage.candidate_hash for stage in result.stages],
            "step_result_count": runtime_evidence.get("row_counts", {}).get(
                "ae_step_result", 0
            ),
            "agent_result_count": runtime_evidence.get("row_counts", {}).get(
                "ae_agent_result", 0
            ),
            "result_delivery_count": runtime_evidence.get("row_counts", {}).get(
                "ae_result_delivery", 0
            ),
        },
        "redaction": {
            "status": "PASS",
            "excluded": [
                "database_password",
                "provider_endpoint",
                "api_key",
                "service_token",
                "raw_prompt",
                "raw_provider_output",
                "candidate_payload",
                "hidden_reasoning",
                "tenant_id",
                "owner_subject_id",
            ],
        },
    }


def _calibration_registry(
    readiness: AeMoGenerationReadiness,
) -> SemanticCalibrationRegistry:
    return SemanticCalibrationRegistry(
        tuple(
            SemanticCalibrationPolicy(
                semantic_stage=stage,
                policy_ref=f"semantic-admission://{stage.lower()}/p65-s7-live/v1",
                policy_version="p65-s7-live-v1",
                model_profile=readiness.model_profile,
                model_ref=readiness.model_ref,
                minimum_confidence=0.5,
                golden_evidence_ref=f"smoke://p65-s7/{stage.lower()}/golden",
                adversarial_evidence_ref=(
                    f"smoke://p65-s7/{stage.lower()}/adversarial"
                ),
            )
            for stage in ("INTENT", "CONTEXT", "PLAN")
        )
    )


def _cleanup(factory: Any, *, tenant_id: str, workspace_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with factory.begin() as session:
        for table in (
            "ae_semantic_candidate",
            "ae_executable_step",
            "ae_executable_plan",
        ):
            counts[table] = int(
                session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
    counts.update(
        _cleanup_planning(
            factory,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
    )
    with factory() as session:
        counts["remaining"] += sum(
            _tenant_count(session, table, tenant_id)
            for table in (
                "ae_semantic_candidate",
                "ae_executable_step",
                "ae_executable_plan",
            )
        )
    return counts


def _tenant_count(connection: Any, table: str, tenant_id: str) -> int:
    return int(
        connection.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).scalar_one()
    )


def _missing_provider_configuration(env: Mapping[str, str]) -> list[str]:
    missing = []
    if not str(env.get("NEX_MO_VLLM_API_KEY", "")).strip():
        missing.append("NEX_MO_VLLM_API_KEY")
    if not (
        str(env.get("NEX_MO_VLLM_CHAT_COMPLETIONS_URL", "")).strip()
        or str(env.get("NEX_MO_VLLM_BASE_URL", "")).strip()
    ):
        missing.append("NEX_MO_VLLM_CHAT_COMPLETIONS_URL|NEX_MO_VLLM_BASE_URL")
    return missing


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


def _platform_revision() -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _safe_error_code(exc: Exception) -> str:
    code = getattr(exc, "error_code", None)
    return str(code) if isinstance(code, str) and code else type(exc).__name__


def _assert_evidence_redacted(
    evidence: Mapping[str, Any], environ: Mapping[str, str]
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    for key in PROTECTED_ENV_KEYS:
        value = str(environ.get(key, ""))
        if len(value) >= 8 and value in serialized:
            raise ValueError(f"protected evidence leaked {key}")


def _failure(
    code: str,
    detail: str,
    *,
    diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6.5-S7",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
        "actual_remote_provider": False,
    }
    if diagnostics is not None:
        evidence["diagnostics"] = dict(diagnostics)
    return evidence


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"p65_s7_postgres_live_e2e=skipped reason={SMOKE_ENV}"
    checks = evidence.get("checks") or {}
    calls = evidence.get("provider_call_counts") or {}
    runtime = evidence.get("runtime_row_counts") or {}
    cleanup = evidence.get("cleanup_counts") or {}
    return (
        "p65_s7_postgres_live_e2e="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"provider={str(bool(evidence.get('actual_remote_provider'))).lower()} "
        f"model_ref={evidence.get('model_ref', 'not-run')} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"generation_calls={calls.get('generation', 0)} "
        f"step_results={runtime.get('ae_step_result', 0)} "
        f"agent_results={runtime.get('ae_agent_result', 0)} "
        f"remaining={cleanup.get('remaining', 'not-run')}"
    )


def write_evidence(output_path: Path, evidence: Mapping[str, Any]) -> None:
    resolved = output_path.expanduser().resolve()
    if not resolved.is_relative_to(Path("/tmp").resolve()):
        raise ValueError("protected live evidence output must be below /tmp")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        f"{json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run P6.5-S7 actual PostgreSQL, MO provider, and NSL E2E."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p65_s7_postgres_live_e2e()
    if args.output:
        write_evidence(args.output, evidence)
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
