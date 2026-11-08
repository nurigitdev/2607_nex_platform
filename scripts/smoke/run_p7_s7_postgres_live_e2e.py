#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-mo",
    ROOT / "services" / "nex-wc",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p5_s5_postgres_smoke as p5_s5  # noqa: E402
import run_p6_ca02_s3_in_process_smoke as p6_ca02_s3  # noqa: E402
import run_p6_s5_postgres_smoke as p6_s5  # noqa: E402
import run_p6_s7_postgres_smoke as p6_s7  # noqa: E402
import run_p7_s5_postgres_smoke as p7_s5  # noqa: E402
import run_p7_s6_postgres_smoke as p7_s6  # noqa: E402
import run_p65_s7_postgres_live_e2e as p65_s7  # noqa: E402
from nex_ae_api.agent_execution import (  # noqa: E402
    AgentExecutionAdmissionService,
    SqlAlchemyAgentExecutionRepository,
)
from nex_ae_api.agent_identity import SqlAlchemyAgentIdentityRegistry  # noqa: E402
from nex_ae_api.background_planning import BackgroundAgentPlanningService  # noqa: E402
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue  # noqa: E402
from nex_ae_api.work_result_events import (  # noqa: E402
    SqlAlchemyWorkResultEventService,
)
from nex_ae_api.work_result_publication import (  # noqa: E402
    SqlAlchemyWcWorkResultPublisher,
)
from nex_mo.provider_readiness_api import (  # noqa: E402
    register_provider_readiness_routes,
)
from nex_mo.provider_readiness_service import ProviderReadinessService  # noqa: E402
from nex_mo.providers import register_mock_provider_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_service_app,
    load_env_file,
    redact_database_url,
)
from nex_wc.coordination import (  # noqa: E402
    RoutingPolicy,
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.work_items import (  # noqa: E402
    SqlAlchemyWorkItemRepository,
    WorkItemService,
)
from nex_wc.work_results import (  # noqa: E402
    SqlAlchemyWorkResultRepository,
    WorkResultService,
)
from run_migrations import run_service_migrations  # noqa: E402
from run_protected_dgx_live_profile import (  # noqa: E402
    protected_dgx_vllm_profile_defaults,
)

SCHEMA_VERSION = "p7_s7_postgres_live_e2e.v1"
SMOKE_ENV = "NEX_P7_S7_POSTGRES_LIVE_E2E"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
WC_DATABASE_ENV = "NEX_WC_TEST_DATABASE_URL"
NSL_SOURCE_ENV = "NEX_AE_P65_S7_NSL_SOURCE"
PROFILE = "agent-profile://pa/project-margin-read/v1"
CAPABILITY = "FINANCE.PROJECT_MARGIN_READ"


@dataclass
class _DiagnosticGenerationClient:
    delegate: object
    readiness_calls: int = 0
    generation_stages: list[str] = field(default_factory=list)
    candidate_shapes: dict[str, object] = field(default_factory=dict)

    def check_required_mode_readiness(self, **kwargs):
        self.readiness_calls += 1
        return self.delegate.check_required_mode_readiness(**kwargs)

    def generate_candidate(self, **kwargs):
        stage = str(kwargs["semantic_stage"])
        self.generation_stages.append(stage)
        result = self.delegate.generate_candidate(**kwargs)
        expected_goal = None
        if stage == "PLAN":
            try:
                generation_input = json.loads(kwargs["messages"][1]["content"])
                expected_goal = generation_input["work_intent"]["goal"]
            except (KeyError, IndexError, TypeError, ValueError):
                expected_goal = None
        self.candidate_shapes[stage] = _candidate_shape(
            result.output_text, expected_goal=expected_goal
        )
        return result


class _DirectWcResultClient:
    def __init__(self, *, items: WorkItemService, results: WorkResultService) -> None:
        self._items = items
        self._results = results
        self.status_calls = 0
        self.submit_calls = 0

    def status(self, *, tenant_id: str, work_item_id: str):
        self.status_calls += 1
        return self._items.status(tenant_id=tenant_id, work_item_id=work_item_id)

    def submit(self, *, expected_version: int, work_result: Mapping[str, object]):
        self.submit_calls += 1
        return self._results.submit(
            tenant_id=str(work_result["tenant_id"]),
            work_item_id=str(work_result["work_item_id"]),
            expected_version=expected_version,
            work_result=work_result,
        )


def run_p7_s7_postgres_live_e2e(
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P7-S7",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
            "actual_remote_provider": False,
        }
    ae_url = env.get(AE_DATABASE_ENV, "")
    wc_url = env.get(WC_DATABASE_ENV, "")
    nsl_source_value = env.get(NSL_SOURCE_ENV, "")
    if not _target_allowed(ae_url, user="nex_ae_user", database="nex_ae_test"):
        return _failure("target_not_allowed", "AE test database is required.")
    if not _target_allowed(wc_url, user="nex_wc_user", database="nex_wc_test"):
        return _failure("target_not_allowed", "WC test database is required.")
    if not nsl_source_value:
        return _failure("nsl_source_missing", f"{NSL_SOURCE_ENV} is required.")
    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_BASE_URL": "http://p7-s7-in-process-mo",
    }
    missing = p65_s7._missing_provider_configuration(effective_env)
    if missing:
        return _failure(
            "provider_configuration_missing",
            "Protected generation provider configuration is incomplete.",
        )
    try:
        nsl_source = Path(nsl_source_value).resolve(strict=True)
        nsl_lock = json.loads(p6_ca02_s3.DEFAULT_LOCK.read_text(encoding="utf-8"))
        p6_ca02_s3._installed_package_evidence(nsl_source, nsl_lock)
        ae_migration = run_service_migrations(
            "nex-ae-api", database_url=ae_url, profile="test"
        )
        wc_migration = run_service_migrations(
            "nex-wc", database_url=wc_url, profile="test"
        )
        execution = _execute_live_e2e(
            ae_url=ae_url,
            wc_url=wc_url,
            nsl_source=nsl_source,
            runtime_environ=effective_env,
        )
        checks = {
            "ae_migration_current": ae_migration.planned[-1]
            == "2405_ae_claimed_planning_source",
            "wc_migration_current": wc_migration.planned[-1]
            == "1003_wc_work_item_authorization",
            **dict(execution.get("checks") or {}),
        }
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P7-S7",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "profile": "test",
            "actual_postgres": True,
            "actual_remote_provider": True,
            "redacted_database_urls": {
                "ae": redact_database_url(ae_url),
                "wc": redact_database_url(wc_url),
            },
            "migration": {
                "ae_latest": ae_migration.planned[-1],
                "ae_applied": len(ae_migration.applied),
                "wc_latest": wc_migration.planned[-1],
                "wc_applied": len(wc_migration.applied),
            },
            "nsl_revision": nsl_lock["source_revision"],
            "checks": checks,
            **{key: value for key, value in execution.items() if key != "checks"},
        }
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "p7_s7_acceptance_failed"
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected smoke boundary
        detail = p5_s5._redact_detail(str(exc), database_url=ae_url)
        detail = p5_s5._redact_detail(detail, database_url=wc_url)
        typed_code = str(getattr(exc, "error_code", type(exc).__name__))
        return _failure("execution_failed", typed_code + ": " + detail)


def _execute_live_e2e(
    *,
    ae_url: str,
    wc_url: str,
    nsl_source: Path,
    runtime_environ: dict[str, str],
    authorization_source=None,
    parent_resume_verifier=None,
) -> dict[str, object]:
    original_environ = dict(os.environ)
    os.environ.clear()
    os.environ.update(runtime_environ)
    try:
        mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
        register_mock_provider_routes(mo_app)
        register_provider_readiness_routes(
            mo_app, service=ProviderReadinessService(environ=runtime_environ)
        )
        with TestClient(mo_app) as mo_test_client:
            client = _DiagnosticGenerationClient(
                p65_s7.build_default_ae_mo_generation_client(
                    runtime_environ,
                    requester=p65_s7.TestClientRequester(mo_test_client),
                )
            )
            readiness = client.check_required_mode_readiness(
                request_id=f"p7-s7-readiness-{uuid4().hex}",
                trace_id=uuid4().hex,
            )
            if (
                readiness.readiness_status != "READY"
                or readiness.source != "active_preflight"
            ):
                raise RuntimeError("actual MO provider readiness is not READY")
            try:
                evidence = p5_s5._execute_postgres_smoke(
                    ae_url,
                    expected_plan_count=2,
                    expected_step_count=4,
                    verifier=lambda fixture: p7_s5._verify_delegate_wait(
                        fixture,
                        wc_url=wc_url,
                        delegation_overrides={
                            "goal": (
                                "2026년 프로젝트 예산 데이터를 조회하여 총 예산, "
                                "집행액, 잔액을 근거와 함께 한국어로 요약한다."
                            )
                        },
                        authorization_source=authorization_source,
                        continuation_verifier=lambda continued: (
                            _verify_background_runtime(
                                continued,
                                client=client,
                                readiness=readiness,
                                nsl_source=nsl_source,
                                authorization_source=authorization_source,
                                parent_resume_verifier=parent_resume_verifier,
                            )
                        ),
                    ),
                )
            except Exception as exc:
                stages = ",".join(client.generation_stages) or "none"
                code = str(getattr(exc, "error_code", type(exc).__name__))
                shape = json.dumps(client.candidate_shapes.get("PLAN"), sort_keys=True)
                raise RuntimeError(
                    f"live semantic stage failure after [{stages}]: {code}; "
                    f"plan_shape={shape}"
                ) from exc
            evidence["provider"] = {
                "mode": readiness.provider_mode,
                "profile": readiness.model_profile,
                "model_ref": readiness.model_ref,
                "deployment_id": readiness.deployment_id,
                "readiness_calls": client.readiness_calls,
                "semantic_stages": list(client.generation_stages),
            }
            evidence["checks"] = {
                **dict(evidence.get("checks") or {}),
                "actual_live_provider_ready": readiness.readiness_status == "READY",
                "exact_live_semantic_stages": client.generation_stages
                == ["INTENT", "CONTEXT", "PLAN"],
            }
            return evidence
    finally:
        os.environ.clear()
        os.environ.update(original_environ)


def _verify_background_runtime(
    fixture: Mapping[str, object],
    *,
    client,
    readiness,
    nsl_source: Path,
    authorization_source=None,
    parent_resume_verifier=None,
) -> dict[str, object]:
    ae_factory = fixture["factory"]
    wc_factory = fixture["wc_factory"]
    tenant_id = str(fixture["tenant_id"])
    parent = dict(fixture["execution"])
    work_item_id = str(fixture["work_item_id"])
    wait_id = str(fixture["wait_id"])
    now = str(fixture["now"])
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    agent_id = str(uuid4())
    identities = SqlAlchemyAgentIdentityRegistry(
        ae_factory, id_factory=lambda: agent_id
    )
    identities.register_agent(
        tenant_id=tenant_id,
        agent_type="PA",
        profile_ref=PROFILE,
        project_id="project-p7-s5",
    )
    candidate = {
        "schema_version": "2.1",
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "agent_type": "PA",
        "profile_ref": PROFILE,
        "status": "ACTIVE",
        "project_id": "project-p7-s5",
        "created_at": now,
        "version": 1,
    }
    coordination = WorkCoordinationService(
        SqlAlchemyCoordinationRepository(wc_factory),
        candidate_source=p7_s6._Candidates(candidate),
        authorization_source=authorization_source or p7_s6._Authorization(),
        policy=RoutingPolicy({CAPABILITY: (PROFILE,)}),
        clock=lambda: now_dt,
    )
    coordination.route(
        tenant_id=tenant_id, work_item_id=work_item_id, expected_version=1
    )
    claimed = coordination.claim(
        tenant_id=tenant_id, work_item_id=work_item_id, expected_version=2
    )
    executions = SqlAlchemyAgentExecutionRepository(ae_factory)
    admission = AgentExecutionAdmissionService(
        identities=identities, executions=executions, mode="required"
    )
    admitted = admission.admit_claimed_work(
        event_id=str(claimed["event_id"]),
        requester_ref=str(parent["principal_id"]),
        handoff=claimed["handoff"],
        planning_source=claimed["planning_source"],
    )
    execution_id = str(admitted.execution["agent_execution_id"])
    prompt_store = p65_s7.SqlAlchemyAePromptRegistryStore(ae_factory)
    p65_s7.seed_ae_prompt_registry(prompt_store)
    capabilities = p65_s7.SqlAlchemyCapabilitySnapshotRepository(ae_factory)
    local_capability = p65_s7.build_local_skill_capability(
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
        if item["capability_id"] == p65_s7.REPORT_CAPABILITY_ID
    )
    current_snapshot = capabilities.get_latest(tenant_id=tenant_id)
    snapshot_version = (
        1 if current_snapshot is None else int(current_snapshot["snapshot_version"]) + 1
    )
    capabilities.save(
        p65_s7.build_capability_snapshot(
            tenant_id=tenant_id,
            capability_snapshot_id=str(uuid4()),
            snapshot_version=snapshot_version,
            created_at=now,
            capabilities=(local_capability, report_capability),
        )
    )
    cleanup: dict[str, int] = {}
    with TemporaryDirectory(prefix="nex-p7-s7-") as storage:
        semantic = p65_s7.DeterministicCandidateAdmissionService(
            mode="required",
            admission=admission,
            intent_stage=p65_s7.LiveIntentCandidateService(
                client, prompt_store, p65_s7._calibration_registry(readiness)
            ),
            context_stage=p65_s7.LiveContextCandidateService(
                client, prompt_store, p65_s7._calibration_registry(readiness)
            ),
            plan_stage=p65_s7.LivePlanCandidateService(
                client, prompt_store, p65_s7._calibration_registry(readiness)
            ),
            evidence=p65_s7.SqlAlchemySemanticCandidateEvidenceRepository(ae_factory),
            candidate_storage=p65_s7.LocalSemanticCandidateStorage(Path(storage)),
            work_intents=p65_s7.SqlAlchemyWorkIntentRepository(ae_factory),
            contexts=p65_s7.SqlAlchemyAgentContextRepository(ae_factory),
            capabilities=capabilities,
            plans=p65_s7.SqlAlchemyAgentPlanRepository(ae_factory),
            validations=p65_s7.SqlAlchemyPlanValidationRepository(ae_factory),
            executable_plans=p65_s7.SqlAlchemyExecutablePlanRepository(ae_factory),
            executions=executions,
            clock=lambda: datetime.now(UTC),
        )
        runtime_policy = p65_s7.resolve_runtime_policy(
            {
                "user_message": "프로젝트 손익 근거를 조회하고 요약해줘.",
                "generation": {"execution_mode": "DOCUMENT_SUMMARY"},
            }
        )
        planned = BackgroundAgentPlanningService(
            semantic_admission=semantic, executions=executions
        ).plan_claimed_execution(
            tenant_id=tenant_id,
            execution_id=execution_id,
            runtime_policy_ref=p65_s7.runtime_policy_ref_from_compatibility_policy(
                runtime_policy
            ),
            request_id=f"p7-s7-{uuid4().hex}",
            trace_id=uuid4().hex,
        )
        if planned.status != "COMPILED" or planned.executable_plan_id is None:
            raise RuntimeError(
                "background semantic admission stopped: "
                f"status={planned.status}, directive={planned.directive}"
            )
        execution = executions.get(tenant_id, execution_id)
        plan = p65_s7.SqlAlchemyExecutablePlanRepository(ae_factory).get(
            tenant_id=tenant_id,
            executable_plan_id=str(planned.executable_plan_id),
        )
        if execution is None or plan is None:
            raise RuntimeError("background planning lineage is incomplete")
        runtime = p6_s7._verify_ia_read_closure(
            {
                "factory": ae_factory,
                "tenant_id": tenant_id,
                "execution": execution,
                "executable_plan": plan,
                "now": now,
            },
            nsl_source=nsl_source,
            backend_profile=p6_s7.NSL_V01_IN_PROCESS_BACKEND,
            expected_runtime_job_count=3,
            expected_runtime_attempt_count=3,
            publication_verifier=lambda published: _publish_and_resume(
                published,
                wc_factory=wc_factory,
                work_item_id=work_item_id,
                wait_id=wait_id,
                now=now,
                parent_execution=parent,
                authorization_source=authorization_source,
                parent_resume_verifier=parent_resume_verifier,
            ),
        )
    with ae_factory.begin() as session:
        for table in ("ae_external_event_inbox", "ae_semantic_candidate"):
            cleanup[table] = int(
                session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
        cleanup["ae_claim_handoff_inbox"] = int(
            session.execute(
                text("DELETE FROM ae_claim_handoff_inbox WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            ).rowcount
            or 0
        )
    return {
        "checks": {
            "claimed_execution_admitted": execution["source_type"]
            == "CLAIMED_WORKITEM",
            "background_plan_compiled": planned.status == "COMPILED",
            "background_plan_uses_existing_runtime": [
                step["executor_kind"] for step in plan["steps"]
            ]
            == ["LOCAL_SKILL", "DETERMINISTIC_REPORT"],
            **dict(runtime["checks"]),
        },
        "row_counts": {
            **dict(runtime["row_counts"]),
            "background_semantic_stages": 3,
        },
        "cleanup_counts": cleanup,
        "background_lineage": {
            "agent_type": execution["agent_type"],
            "source_type": execution["source_type"],
            "work_item_ref": execution["work_item_ref"],
            "plan_id": planned.executable_plan_id,
        },
    }


def _publish_and_resume(
    fixture: Mapping[str, object],
    *,
    wc_factory,
    work_item_id: str,
    wait_id: str,
    now: str,
    parent_execution=None,
    authorization_source=None,
    parent_resume_verifier=None,
) -> dict[str, object]:
    ae_factory = fixture["factory"]
    tenant_id = str(fixture["tenant_id"])
    aggregate = fixture["aggregate"]
    effective_authorization_source = authorization_source or p7_s6._Authorization()
    items = WorkItemService(
        SqlAlchemyWorkItemRepository(wc_factory),
        authorization_source=effective_authorization_source,
    )
    result_repository = SqlAlchemyWorkResultRepository(wc_factory)
    results = WorkResultService(
        result_repository,
        authorization_source=effective_authorization_source,
        clock=lambda: datetime.fromisoformat(now.replace("Z", "+00:00")),
    )
    client = _DirectWcResultClient(items=items, results=results)
    published = SqlAlchemyWcWorkResultPublisher(ae_factory, client).publish(
        tenant_id=tenant_id,
        delivery_id=str(aggregate.delivery["delivery_id"]),
        now=now,
    )
    replayed = SqlAlchemyWcWorkResultPublisher(ae_factory, client).publish(
        tenant_id=tenant_id,
        delivery_id=str(aggregate.delivery["delivery_id"]),
        now=now,
    )
    event_row = next(
        row
        for row in result_repository.list_pending_result_events(limit=100)
        if row["event_payload"]["tenant_id"] == tenant_id
        and row["event_payload"]["work_item_id"] == work_item_id
    )
    delivery_job_id = str(uuid4())
    result_repository.mark_result_event_enqueued(
        outbox_id=str(event_row["outbox_id"]),
        event_id=str(event_row["event_id"]),
        job_id=delivery_job_id,
        updated_at=now,
    )
    loaded = result_repository.load_result_event(
        outbox_id=str(event_row["outbox_id"]),
        event_id=str(event_row["event_id"]),
    )
    event_service = SqlAlchemyWorkResultEventService(
        ae_factory,
        runtime_jobs=SqlAlchemyRuntimeJobQueue(ae_factory),
        clock=lambda: datetime.fromisoformat(now.replace("Z", "+00:00")),
    )
    admitted_event = event_service.ingest(loaded["event_payload"])
    duplicate_event = event_service.ingest(loaded["event_payload"])
    result_repository.mark_result_event_delivered(
        outbox_id=str(event_row["outbox_id"]),
        event_id=str(event_row["event_id"]),
        job_id=delivery_job_id,
        updated_at=now,
    )
    with ae_factory() as session:
        child = session.execute(
            text(
                "SELECT state, phase FROM ae_agent_execution "
                "WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id"
            ),
            {
                "tenant_id": tenant_id,
                "execution_id": aggregate.execution["agent_execution_id"],
            },
        ).one()
        wait = session.execute(
            text(
                "SELECT state FROM ae_wait_registration WHERE tenant_id = :tenant_id "
                "AND wait_id = :wait_id"
            ),
            {"tenant_id": tenant_id, "wait_id": wait_id},
        ).one()
    parent_completion = (
        {}
        if parent_resume_verifier is None
        else dict(
            parent_resume_verifier(
                {
                    **dict(fixture),
                    "wc_factory": wc_factory,
                    "work_item_id": work_item_id,
                    "wait_id": wait_id,
                    "result_event": loaded["event_payload"],
                    "parent_execution": parent_execution,
                    "authorization_source": effective_authorization_source,
                }
            )
        )
    )
    return {
        "checks": {
            "wc_result_exact_ack": published["delivery_state"] == "ACKNOWLEDGED",
            "child_success_only_after_ack": tuple(child) == ("SUCCEEDED", "FINALIZE"),
            "publication_restart_idempotent": replayed["created"] is False
            and client.status_calls == client.submit_calls == 1,
            "parent_resume_event_matched": admitted_event["inbox_state"] == "MATCHED"
            and tuple(wait) == ("RESUME_QUEUED",),
            "duplicate_result_event_idempotent": duplicate_event["created"] is False,
            **dict(parent_completion.get("checks") or {}),
        },
        "row_counts": {
            "wc_work_result": 1,
            "ae_result_event": 1,
            **dict(parent_completion.get("row_counts") or {}),
        },
        **{
            key: value
            for key, value in parent_completion.items()
            if key not in {"checks", "row_counts"}
        },
    }


def _target_allowed(database_url: str, *, user: str, database: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == user
        and unquote(parsed.path.lstrip("/")) == database
    )


def _candidate_shape(
    output_text: str, *, expected_goal: object = None
) -> dict[str, object]:
    try:
        value = json.loads(output_text)
    except (TypeError, ValueError):
        return {"strict_json": False}
    if not isinstance(value, dict):
        return {"strict_json": True, "json_type": type(value).__name__}
    shape: dict[str, object] = {
        "strict_json": True,
        "top_level_keys": sorted(value),
        "schema_version": value.get("schema_version"),
        "suggested_plan_kind": value.get("suggested_plan_kind"),
        "goal_character_count": (
            len(value["goal"]) if isinstance(value.get("goal"), str) else None
        ),
        "goal_matches_input": (
            value.get("goal") == expected_goal if expected_goal is not None else None
        ),
    }
    steps = value.get("logical_steps")
    if isinstance(steps, list):
        shape["logical_step_count"] = len(steps)
        shape["logical_step_keys"] = [
            sorted(item) if isinstance(item, dict) else type(item).__name__
            for item in steps
        ]
        shape["logical_step_types"] = [
            item.get("step_type") if isinstance(item, dict) else None for item in steps
        ]
    mappings = value.get("completion_mapping")
    if isinstance(mappings, list):
        shape["completion_mapping_keys"] = [
            sorted(item) if isinstance(item, dict) else type(item).__name__
            for item in mappings
        ]
    return shape


def _failure(code: str, detail: str) -> dict[str, object]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P7-S7",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
        "actual_remote_provider": False,
    }


def summary_line(evidence: Mapping[str, object]) -> str:
    checks = dict(evidence.get("checks") or {})
    provider = dict(evidence.get("provider") or {})
    return (
        "p7_s7_postgres_live="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"provider_stages={len(provider.get('semantic_stages') or [])}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p7_s7_postgres_live_e2e()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
