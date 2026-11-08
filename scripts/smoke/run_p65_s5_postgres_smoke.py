#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
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
    AeMoGenerationReadiness,
    AeMoGenerationResult,
)
from nex_ae_api.plan_candidate_generation import (  # noqa: E402
    LivePlanCandidateService,
)
from nex_ae_api.plan_validation import (  # noqa: E402
    SqlAlchemyPlanValidationRepository,
)
from nex_ae_api.planning_capabilities import (  # noqa: E402
    SqlAlchemyCapabilitySnapshotRepository,
    build_capability_snapshot,
)
from nex_ae_api.prompt_persistence import SqlAlchemyAePromptRegistryStore  # noqa: E402
from nex_ae_api.prompts import seed_ae_prompt_registry  # noqa: E402
from nex_ae_api.runtime_policy import resolve_runtime_policy  # noqa: E402
from nex_ae_api.semantic_candidate_admission import (  # noqa: E402
    DeterministicCandidateAdmissionService,
    SemanticCandidateAdmissionRequest,
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
from nex_runtime import (  # noqa: E402
    load_env_file,
    redact_database_url,
    sqlalchemy_database_url,
)
from nex_runtime.semantic_hashes import (  # noqa: E402
    canonical_json,
    semantic_sha256_hash_ref,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402
from run_p5_s3_postgres_smoke import (  # noqa: E402
    _cleanup as _cleanup_planning,
)
from run_p5_s3_postgres_smoke import (  # noqa: E402
    _seed_workspace_conversation,
)


SCHEMA_VERSION = "p65_s5_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P65_S5_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2300_ae_semantic_candidate"
MODEL_PROFILE = "general-llm-default"
MODEL_REF = "p65-s5-deterministic-smoke"
NOW = "2026-10-17T03:00:00Z"


class _SmokeGenerationClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def check_required_mode_readiness(self, **_kwargs: Any) -> AeMoGenerationReadiness:
        return AeMoGenerationReadiness(
            provider_mode="mock",
            readiness_status="READY",
            model_profile=MODEL_PROFILE,
            model_ref=MODEL_REF,
            deployment_id="p65-s5-postgres-smoke",
            route_id="p65-s5-postgres-route",
            checked_at=NOW,
            expires_at="2026-10-17T03:05:00Z",
            cache_status="FRESH",
            source="deterministic_postgres_fixture",
        )

    def generate_candidate(self, **kwargs: Any) -> AeMoGenerationResult:
        stage = str(kwargs["semantic_stage"])
        self.calls.append(stage)
        generation_input = json.loads(kwargs["messages"][1]["content"])
        candidate = self._candidate(stage, generation_input)
        output = canonical_json(candidate)
        return AeMoGenerationResult(
            mo_generation_id=f"p65-s5-{stage.lower()}-{uuid4().hex}",
            model_profile=MODEL_PROFILE,
            model_ref=MODEL_REF,
            deployment_id="p65-s5-postgres-smoke",
            provider_type="deterministic-smoke",
            output_text=output,
            provider_output_sha256=hashlib.sha256(output.encode()).hexdigest(),
            provider_output_size_bytes=len(output.encode()),
            finish_reason="STOP",
            input_tokens=64,
            output_tokens=64,
            total_tokens=128,
            request_id=str(kwargs["request_id"]),
            trace_id=str(kwargs["trace_id"]),
            route_id="p65-s5-postgres-route",
            provider_request_id=f"fixture-{stage.lower()}",
            queue_ms=0,
            provider_ms=1,
            total_ms=1,
            created_at=NOW,
            updated_at=NOW,
        )

    @staticmethod
    def _candidate(stage: str, generation_input: Mapping[str, Any]) -> dict[str, Any]:
        if stage == "INTENT":
            return {
                "schema_version": "p65.intent_candidate.v1",
                "intent_label": "analyze_project_budget",
                "suggested_execution_mode": "GROUNDED_ANSWER",
                "entity_selectors": [],
                "parameter_candidates": [],
                "clarification": {
                    "required": False,
                    "reasons": [],
                    "questions": [],
                },
                "confidence": 0.95,
            }
        if stage == "CONTEXT":
            return {
                "schema_version": "p65.context_candidate_set.v1",
                "entity_candidates": [],
                "retrieval_hints": [
                    {
                        "query_terms": ["프로젝트", "예산", "잔액"],
                        "resource_types": ["DOCUMENT"],
                        "confidence": 0.94,
                    }
                ],
                "resource_selectors": [],
                "parameter_candidates": [],
                "confidence": 0.94,
            }
        return {
            "schema_version": "p65.plan_candidate.v1",
            "suggested_plan_kind": "DIRECT",
            "goal": generation_input["work_intent"]["goal"],
            "logical_steps": [
                {
                    "step_id": "S1",
                    "step_type": "LOCAL_CAPABILITY",
                    "title": "Run grounded compatibility chat",
                    "objective": "Answer from admitted context.",
                    "depends_on": [],
                    "capability_hint": "AE.CHAT.COMPATIBILITY",
                    "completion_criteria": ["A grounded answer is returned."],
                }
            ],
            "completion_mapping": [
                {"criterion_id": "C1", "terminal_step_refs": ["S1"]}
            ],
            "confidence": 0.96,
        }


class _TrustedResolver:
    def __init__(self, interaction_id: str) -> None:
        self.interaction_id = interaction_id

    def resolve(self, _request: Any) -> TrustedContextResolution:
        return TrustedContextResolution(
            project_ref=None,
            authority_ref="OA:EAC:p65-s5-postgres-smoke",
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
                    "as_of": NOW,
                },
            ),
            budget_tokens=4096,
            estimated_used_tokens=128,
        )


def run_p65_s5_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6.5-S5",
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
            and migration.planned[-1] == REQUIRED_MIGRATION
            and len(migration.planned)
            == len(migration.applied) + len(migration.skipped)
        )
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P6.5-S5",
                "profile": "test",
                "database_env": DATABASE_ENV,
                "redacted_database_url": redact_database_url(database_url),
                "migration": {
                    "planned_count": len(migration.planned),
                    "applied_count": len(migration.applied),
                    "skipped_count": len(migration.skipped),
                    "latest_version": migration.planned[-1],
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
            evidence["failure_code"] = "p65_s5_postgres_smoke_failed"
        return evidence
    except (MigrationError, OSError, RuntimeError, SQLAlchemyError, ValueError) as exc:
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_url=database_url),
        )
    except Exception as exc:  # pragma: no cover - defensive smoke boundary
        return _failure("unexpected_failure", type(exc).__name__)


def _execute_postgres_smoke(database_url: str) -> dict[str, Any]:
    engine = create_engine(
        sqlalchemy_database_url(database_url), future=True, pool_pre_ping=True
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    token = uuid4().hex
    tenant_id = f"tenant-p65-s5-{token[:12]}"
    principal_id = f"user-p65-s5-{token[:12]}"
    workspace_id = str(uuid4())
    conversation_id = str(uuid4())
    interaction_id = str(uuid4())
    trace_id = uuid4().hex
    request_id = f"p65-s5-{token}"
    marker = f"private-p65-s5-{token}"
    cleanup_counts: dict[str, int] = {}
    checks: dict[str, bool] = {}
    row_counts: dict[str, int] = {}
    database = ""
    role = ""
    storage_root: Path | None = None
    client = _SmokeGenerationClient()

    identities = SqlAlchemyAgentIdentityRegistry(factory)
    executions = SqlAlchemyAgentExecutionRepository(factory)
    admission = AgentExecutionAdmissionService(
        identities=identities,
        executions=executions,
        mode="required",
    )
    prompt_store = SqlAlchemyAePromptRegistryStore(factory)
    policies = SemanticCalibrationRegistry(
        tuple(_calibration(stage) for stage in ("INTENT", "CONTEXT", "PLAN"))
    )
    try:
        _seed_workspace_conversation(
            factory,
            tenant_id=tenant_id,
            principal_id=principal_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            now=NOW,
        )
        seed_ae_prompt_registry(prompt_store)
        with TemporaryDirectory(prefix="nex-p65-s5-") as directory:
            storage_root = Path(directory)
            capabilities = SqlAlchemyCapabilitySnapshotRepository(factory)
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
                capabilities=capabilities,
                plans=SqlAlchemyAgentPlanRepository(factory),
                validations=SqlAlchemyPlanValidationRepository(factory),
                executable_plans=SqlAlchemyExecutablePlanRepository(factory),
                executions=executions,
                clock=lambda: datetime(2026, 10, 17, 3, 0, tzinfo=UTC),
            )
            runtime_policy = resolve_runtime_policy(
                {
                    "user_message": marker,
                    "generation": {"execution_mode": "GROUNDED_ANSWER"},
                }
            )
            request = SemanticCandidateAdmissionRequest(
                tenant_id=tenant_id,
                owner_subject_id=principal_id,
                profile_ref="urn:nex:agent-profile:ia:default:v1",
                interaction_id=interaction_id,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                correlation_id=f"p65-s5:{trace_id}",
                request_id=request_id,
                trace_id=trace_id,
                user_prompt=marker,
                base_context={
                    "interaction_text": marker,
                    "conversation_summary": None,
                    "resource_label_hints": ["프로젝트 예산 현황"],
                },
                runtime_policy_ref=runtime_policy_ref_from_compatibility_policy(
                    runtime_policy
                ),
                context_resolver=_TrustedResolver(interaction_id),
                capability_snapshot=build_capability_snapshot(
                    tenant_id=tenant_id,
                    capability_snapshot_id=str(uuid4()),
                    snapshot_version=1,
                    created_at=NOW,
                ),
                retrieval_enabled=True,
                authorized_resource_context_available=True,
                trusted_execution_mode="GROUNDED_ANSWER",
            )
            first = service.admit_and_compile(request)
            first_calls = tuple(client.calls)
            client.calls.clear()
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
                evidence_text = "\n".join(
                    connection.execute(
                        text(
                            "SELECT evidence_json::text FROM ae_semantic_candidate "
                            "WHERE tenant_id = :tenant_id"
                        ),
                        {"tenant_id": tenant_id},
                    ).scalars()
                )
            checks = {
                "actual_database_identity": (
                    database == EXPECTED_DATABASE and role == EXPECTED_ROLE
                ),
                "three_stage_compile_completed": (
                    first.status == "COMPILED"
                    and first.validation_status == "VALID"
                    and [stage.semantic_stage for stage in first.stages]
                    == ["INTENT", "CONTEXT", "PLAN"]
                ),
                "one_call_per_semantic_stage": first_calls
                == ("INTENT", "CONTEXT", "PLAN"),
                "restart_reuses_persisted_candidates": (
                    client.calls == []
                    and all(stage.resumed for stage in resumed.stages)
                    and resumed.executable_plan_hash == first.executable_plan_hash
                ),
                "candidate_rows_are_bounded": row_counts[
                    "ae_semantic_candidate"
                ]
                == 3,
                "canonical_records_are_singletons": all(
                    row_counts[table] == 1
                    for table in (
                        "ae_work_intent",
                        "ae_agent_context",
                        "ae_agent_plan",
                        "ae_plan_validation",
                        "ae_executable_plan",
                        "ae_agent_execution",
                    )
                ),
                "executable_step_created_after_valid": row_counts[
                    "ae_executable_step"
                ]
                == 1,
                "owner_private_payloads_content_addressed": len(private_files) == 3,
                "private_prompt_absent_from_candidate_rows": marker not in evidence_text,
            }
            cleanup_counts = _cleanup(
                factory,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
        checks["private_storage_zero_residue"] = (
            storage_root is not None and not storage_root.exists()
        )
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
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "execution_state": "EXECUTED",
        "actual_postgres": True,
        "provider_mode": "deterministic-postgres-fixture",
        "database": database,
        "role": role,
        "checks": checks,
        "row_counts": row_counts,
        "cleanup_counts": cleanup_counts,
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


def _calibration(stage: str) -> SemanticCalibrationPolicy:
    return SemanticCalibrationPolicy(
        semantic_stage=stage,
        policy_ref=f"semantic-admission://{stage.lower()}/p65-s5-postgres/v1",
        policy_version="p65-s5-postgres-v1",
        model_profile=MODEL_PROFILE,
        model_ref=MODEL_REF,
        minimum_confidence=0.5,
        golden_evidence_ref=f"smoke://p65-s5/{stage.lower()}/golden",
        adversarial_evidence_ref=f"smoke://p65-s5/{stage.lower()}/adversarial",
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
        "slice": "P6.5-S5",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"p65_s5_postgres=skipped reason={SMOKE_ENV}"
    checks = evidence.get("checks") or {}
    rows = evidence.get("row_counts") or {}
    return (
        "p65_s5_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"execution={str(evidence.get('execution_state') or 'not-run').lower()} "
        f"database={evidence.get('database', 'not-run')} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"candidates={rows.get('ae_semantic_candidate', 0)} "
        f"cleanup={(evidence.get('cleanup_counts') or {}).get('remaining', 'not-run')}"
    )


def write_evidence(output_path: Path, evidence: Mapping[str, Any]) -> None:
    resolved = output_path.expanduser().resolve()
    if not resolved.is_relative_to(Path("/tmp").resolve()):
        raise ValueError("protected PostgreSQL evidence output must be below /tmp")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        f"{json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the protected P6.5-S5 AE PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p65_s5_postgres_smoke()
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
