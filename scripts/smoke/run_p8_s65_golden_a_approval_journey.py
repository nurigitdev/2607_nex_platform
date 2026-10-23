#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-eos",
    ROOT / "services" / "nex-mo",
    ROOT / "services" / "nex-oa",
    ROOT / "services" / "nex-wc",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_ae_web_credential_login_playwright_postgres_smoke as browser_runtime
import run_p8_s06_nsl_compatibility as p8_s06
import run_p8_s53_approval_resume_postgres as p8_s53
import run_p65_s7_postgres_live_e2e as p65_s7
from nex_ae_api.agent_context import SqlAlchemyAgentContextRepository
from nex_ae_api.agent_execution import (
    AgentExecutionAdmissionService,
    SqlAlchemyAgentExecutionRepository,
)
from nex_ae_api.agent_identity import SqlAlchemyAgentIdentityRegistry
from nex_ae_api.agent_plans import SqlAlchemyAgentPlanRepository
from nex_ae_api.executable_plans import SqlAlchemyExecutablePlanRepository
from nex_ae_api.golden_a_approval_journey import GoldenAPlanningJourneyService
from nex_ae_api.golden_a_planning import (
    GOLDEN_A_CAPABILITY_ID,
    GOLDEN_A_NSL_SKILL_ID,
    build_golden_a_canonical_write_payload,
)
from nex_ae_api.intent_candidate_generation import LiveIntentCandidateService
from nex_ae_api.mo_generation_client import build_default_ae_mo_generation_client
from nex_ae_api.plan_candidate_generation import LivePlanCandidateService
from nex_ae_api.plan_validation import SqlAlchemyPlanValidationRepository
from nex_ae_api.planning_capabilities import (
    SqlAlchemyCapabilitySnapshotRepository,
)
from nex_ae_api.prompt_persistence import SqlAlchemyAePromptRegistryStore
from nex_ae_api.prompts import seed_ae_prompt_registry
from nex_ae_api.semantic_candidates import (
    SemanticCalibrationPolicy,
    SemanticCalibrationRegistry,
)
from nex_ae_api.work_intent import SqlAlchemyWorkIntentRepository
from nex_mo.provider_readiness_api import register_provider_readiness_routes
from nex_mo.provider_readiness_service import ProviderReadinessService
from nex_mo.providers import register_mock_provider_routes
from nex_oa.authorization_repository import build_authorization_repository_for_runtime
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver
from nex_oa.authorization_service import (
    OA_AUTHORIZATION_READ_SCOPE,
    OaAuthorizationService,
    register_authorization_routes,
)
from nex_oa.memberships import (
    build_tenant_membership_registry_for_runtime,
    register_identity_membership_routes,
)
from nex_oa.subjects import (
    OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE,
    build_subject_registry_for_runtime,
    register_subject_registry_routes,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
    sqlalchemy_database_url,
)
from nex_runtime.semantic_hashes import nsl_write_payload_hash_ref
from nex_wc.coordination_clients import HttpAuthorizationSource
from p8_golden_a_fixture import load_golden_a_fixture
from run_migrations import run_service_migrations
from run_p5_s3_postgres_smoke import _seed_workspace_conversation
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

SCHEMA_VERSION = "p8_s65_golden_a_approval_journey.v1"
SMOKE_ENV = "NEX_P8_S65_GOLDEN_A_LIVE"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
WC_DATABASE_ENV = "NEX_WC_TEST_DATABASE_URL"
OA_DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
DEFAULT_SOURCE = Path("/home/tprover/2608_nsl")
DEFAULT_LOCK = ROOT / "deployment/locks/nsl-v0.2-wheel.json"
DEFAULT_WHEEL_DIRECTORY = ROOT / "reports/deployment/p8-nsl-v0.2-wheel"
DEFAULT_REPORT = Path("/tmp/nex-p8-s65-golden-a-approval-journey.json")
EXPECTED_DATABASES = {
    AE_DATABASE_ENV: ("nex_ae_user", "nex_ae_test"),
    WC_DATABASE_ENV: ("nex_wc_user", "nex_wc_test"),
    OA_DATABASE_ENV: ("nex_oa_user", "nex_oa_test"),
}
PROTECTED_ENV_KEYS = (
    AE_DATABASE_ENV,
    WC_DATABASE_ENV,
    OA_DATABASE_ENV,
    "NEX_MO_VLLM_API_KEY",
    "NEX_AE_TO_MO_SERVICE_TOKEN",
)


class P8S65SmokeError(RuntimeError):
    pass


def run_p8_s65_golden_a_approval_journey(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool,
    source: Path = DEFAULT_SOURCE,
    lock_path: Path = DEFAULT_LOCK,
    wheel_directory: Path = DEFAULT_WHEEL_DIRECTORY,
    python_bin: str = sys.executable,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S65",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {SMOKE_ENV}=1 are required",
            "actual_postgres": False,
            "actual_remote_provider": False,
        }
    database_urls = {key: env.get(key, "") for key in EXPECTED_DATABASES}
    try:
        for key, (role, database) in EXPECTED_DATABASES.items():
            _require_database_target(
                database_urls[key], role=role, database=database, label=key
            )
        effective_env = {
            **protected_dgx_vllm_profile_defaults(),
            **env,
            "NEX_MO_PROVIDER_MODE": "live",
            "NEX_MO_BASE_URL": "http://p8-s65-in-process-mo",
        }
        if p65_s7._missing_provider_configuration(effective_env):
            raise P8S65SmokeError(
                "live generation provider configuration is incomplete"
            )
        lock = p8_s06._load_object(lock_path, "NSL v0.2 wheel lock")
        release = p8_s06._verify_v02_release(source, wheel_directory, lock)
        migrations = {
            service_id: run_service_migrations(
                service_id,
                database_url=database_urls[database_env],
                profile="test",
            )
            for service_id, database_env in (
                ("nex-ae-api", AE_DATABASE_ENV),
                ("nex-wc", WC_DATABASE_ENV),
                ("nex-oa", OA_DATABASE_ENV),
            )
        }
        journey = _execute_live_journey(
            env=effective_env,
            ae_database_url=database_urls[AE_DATABASE_ENV],
            wc_database_url=database_urls[WC_DATABASE_ENV],
            oa_database_url=database_urls[OA_DATABASE_ENV],
            source=source,
            lock_path=lock_path,
            wheel_directory=wheel_directory,
            lock=lock,
            python_bin=python_bin,
        )
        checks = {
            "nsl_release_exact": release["wheel_sha256"] == lock["wheel_sha256"],
            "migrations_current": all(
                len(item.planned) == len(item.applied) + len(item.skipped)
                for item in migrations.values()
            ),
            **journey["checks"],
        }
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S65",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "actual_postgres": True,
            "actual_remote_provider": True,
            "release": release,
            "databases": {
                key: redact_database_url(value) for key, value in database_urls.items()
            },
            "migrations": {
                service: _migration_summary(value)
                for service, value in migrations.items()
            },
            **{key: value for key, value in journey.items() if key != "checks"},
            "checks": checks,
            "checks_passed": sum(bool(value) for value in checks.values()),
            "checks_total": len(checks),
            "decision": {
                "p8_s65_closed": all(checks.values()),
                "eos_write_enabled": False,
                "next_slice": "P8-S66",
            },
        }
        _assert_redacted(evidence, effective_env)
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected gate records sanitized failure.
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S65",
            "status": "FAIL",
            "actual_postgres": False,
            "actual_remote_provider": False,
            "failure_code": getattr(exc, "error_code", type(exc).__name__),
            "detail": _redact(str(exc), *database_urls.values()),
            "decision": {"p8_s65_closed": False, "eos_write_enabled": False},
        }
        _assert_redacted(evidence, env)
        return evidence


def _execute_live_journey(  # pragma: no cover - actual PostgreSQL/DGX/NSL gate.
    *,
    env: dict[str, str],
    ae_database_url: str,
    wc_database_url: str,
    oa_database_url: str,
    source: Path,
    lock_path: Path,
    wheel_directory: Path,
    lock: Mapping[str, Any],
    python_bin: str,
) -> dict[str, Any]:
    fixture = load_golden_a_fixture()
    original_environ = dict(os.environ)
    oa_server = None
    oa_engine = create_engine(oa_database_url, poolclass=NullPool)
    try:
        _cleanup_oa(oa_engine, fixture["tenant"]["tenant_id"])
        oa_app = _build_oa_app(oa_database_url)
        for principal in fixture["principals"]:
            _seed_identity(
                oa_app,
                tenant_id=fixture["tenant"]["tenant_id"],
                subject_id=principal["subject_id"],
                roles=list(principal["roles"]),
                scopes=list(principal["scopes"]),
            )
        oa_server = browser_runtime.start_api_server(
            oa_app, browser_runtime.find_free_port()
        )
        authorization = HttpAuthorizationSource(
            base_url=oa_server.url,
            service_token=_service_token(
                "nex-wc", "nex-oa", OA_AUTHORIZATION_READ_SCOPE
            ),
        )
        requester = fixture["scenario"]["requester_subject_id"]
        approver = fixture["approval_target"]["approver_subject_id"]
        requester_authorization = authorization.effective_authorization(
            tenant_id=fixture["tenant"]["tenant_id"], subject_id=requester
        )
        os.environ.clear()
        os.environ.update(env)
        mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
        register_mock_provider_routes(mo_app)
        register_provider_readiness_routes(
            mo_app, service=ProviderReadinessService(environ=env)
        )
        with TemporaryDirectory(prefix="p8-s65-") as temporary:
            temporary_root = Path(temporary)
            target = temporary_root / "site-packages"
            p8_s06._install_wheel(
                python_bin,
                wheel_directory / str(lock["wheel_filename"]),
                target,
                env,
            )
            worker_env = p8_s53._worker_environment(env, target)
            profile = _copy_golden_a_profile(
                source=source, case_root=temporary_root / "golden-a"
            )
            _customize_profile(profile, fixture)
            skill = p8_s53._skill_identity(
                python_bin=python_bin, profile=profile, env=worker_env
            )
            with TestClient(mo_app) as mo_client:
                generation_client = p65_s7.CountingGenerationClient(
                    build_default_ae_mo_generation_client(
                        env, requester=p65_s7.TestClientRequester(mo_client)
                    )
                )
                readiness = generation_client.check_required_mode_readiness(
                    request_id=f"p8-s65-readiness-{uuid4().hex}",
                    trace_id=uuid4().hex,
                )
                result = _execute_postgres_journey(
                    fixture=fixture,
                    ae_database_url=ae_database_url,
                    wc_database_url=wc_database_url,
                    authorization=authorization,
                    requester_authorization=requester_authorization,
                    generation_client=generation_client,
                    readiness=readiness,
                    profile=profile,
                    target=target,
                    worker_env=worker_env,
                    python_bin=python_bin,
                    lock_path=lock_path,
                )
            result["checks"]["actual_nsl_skill_v11_admitted"] = (
                skill["skill_id"] == fixture["admission"]["skill_id"]
                and skill["skill_version"]
                == fixture["admission"]["exact_skill_version"]
                and skill["semantic_hash"]
                == fixture["admission"]["skill_semantic_hash"]
            )
        return {
            **result,
            "provider": {
                "mode": readiness.provider_mode,
                "readiness": readiness.readiness_status,
                "model_profile": readiness.model_profile,
                "model_ref": readiness.model_ref,
                "generation_stages": generation_client.generation_stages,
            },
            "skill": skill,
        }
    finally:
        os.environ.clear()
        os.environ.update(original_environ)
        if oa_server is not None:
            oa_server.stop()
        oa_remaining = _cleanup_oa(oa_engine, fixture["tenant"]["tenant_id"])
        oa_engine.dispose()
        if "result" in locals():
            result["oa_cleanup_remaining"] = oa_remaining
            result["checks"]["oa_cleanup_complete"] = oa_remaining == 0


def _execute_postgres_journey(  # pragma: no cover - actual protected integration.
    *,
    fixture: Mapping[str, Any],
    ae_database_url: str,
    wc_database_url: str,
    authorization: HttpAuthorizationSource,
    requester_authorization: Mapping[str, Any],
    generation_client: Any,
    readiness: Any,
    profile: Path,
    target: Path,
    worker_env: Mapping[str, str],
    python_bin: str,
    lock_path: Path,
) -> dict[str, Any]:
    engine = create_engine(sqlalchemy_database_url(ae_database_url), pool_pre_ping=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    tenant_id = fixture["tenant"]["tenant_id"]
    requester = fixture["scenario"]["requester_subject_id"]
    approver = fixture["approval_target"]["approver_subject_id"]
    workspace_id, conversation_id, interaction_id = (str(uuid4()) for _ in range(3))
    trace_id = uuid4().hex
    now_dt = datetime.now(UTC).replace(microsecond=0)
    now = now_dt.isoformat().replace("+00:00", "Z")
    cleanup: dict[str, int] = {}
    try:
        _cleanup_ae(factory, tenant_id=tenant_id, workspace_id=workspace_id)
        _seed_workspace_conversation(
            factory,
            tenant_id=tenant_id,
            principal_id=requester,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            now=now,
        )
        executions = SqlAlchemyAgentExecutionRepository(factory)
        admitted = AgentExecutionAdmissionService(
            identities=SqlAlchemyAgentIdentityRegistry(factory),
            executions=executions,
            mode="required",
            clock=lambda: now_dt,
        ).admit_prompt(
            tenant_id=tenant_id,
            principal_id=requester,
            profile_ref="urn:nex:agent-profile:ia:golden-a:v1",
            trigger_id=interaction_id,
            interaction_id=interaction_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            correlation_id=f"p8-s65:{trace_id}",
        )
        execution = admitted.execution
        if execution is None:
            raise P8S65SmokeError("required IA admission did not create execution")
        prompt_store = SqlAlchemyAePromptRegistryStore(factory)
        seed_ae_prompt_registry(prompt_store)
        policies = _calibration_registry(readiness)
        planning = GoldenAPlanningJourneyService(
            intent_service=LiveIntentCandidateService(
                generation_client, prompt_store, policies
            ),
            plan_service=LivePlanCandidateService(
                generation_client, prompt_store, policies
            ),
        ).plan(
            fixture=fixture,
            user_prompt=fixture["scenario"]["prompt"],
            tenant_id=tenant_id,
            principal_id=requester,
            agent_id=execution["agent_id"],
            execution_id=execution["agent_execution_id"],
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            interaction_id=interaction_id,
            received_at=now,
            request_id=f"p8-s65-{uuid4().hex}",
            trace_id=trace_id,
            authority_ref=("oa-authz:" + str(requester_authorization["revision_hash"])),
        )
        _persist_planning(factory, tenant_id, execution, planning, now)
        row_counts = _planning_counts(factory, tenant_id)
        approval = p8_s53._verify_scenario(
            {
                "factory": factory,
                "tenant_id": tenant_id,
                "execution": execution,
                "executable_plan": planning.executable_plan,
            },
            scenario="golden-a",
            decision="APPROVE",
            ae_database_url=ae_database_url,
            wc_database_url=wc_database_url,
            profile=profile,
            target=target,
            env=worker_env,
            python_bin=python_bin,
            lock_path=lock_path,
            authorization_source=authorization,
            approver_id_override=approver,
            nsl_subject_id_override=requester,
            business_operation_id_override=str(uuid4()),
        )["scenario"]
        canonical_payload_hash = nsl_write_payload_hash_ref(
            build_golden_a_canonical_write_payload(fixture)
        )
        exact_binding = planning.activation["authoritative_binding"]["capability_ref"]
        checks = {
            "live_provider_ready": readiness.readiness_status == "READY",
            "live_intent_then_plan": generation_client.generation_stages
            == ["INTENT", "PLAN"],
            "deterministic_planning_valid": planning.validation["status"] == "VALID",
            "ia_remains_project_neutral": planning.agent_context["project_ref"] is None,
            "exact_project_resolved": planning.activation["authoritative_binding"][
                "project_code"
            ]
            == fixture["projects"]["child"]["project_code"],
            "exact_capability_skill_tool_lineage": (
                exact_binding["capability_id"] == GOLDEN_A_CAPABILITY_ID
                and exact_binding["skill_id"] == GOLDEN_A_NSL_SKILL_ID
                and exact_binding["tool_id"] == GOLDEN_A_CAPABILITY_ID
                and exact_binding["skill_semantic_hash"]
                == fixture["admission"]["skill_semantic_hash"]
            ),
            "canonical_planning_rows_persisted": all(
                row_counts[table] == expected
                for table, expected in {
                    "ae_work_intent": 1,
                    "ae_agent_context": 1,
                    "ae_capability_snapshot": 1,
                    "ae_agent_plan": 1,
                    "ae_plan_validation": 1,
                    "ae_executable_plan": 1,
                    "ae_executable_step": len(planning.executable_plan["steps"]),
                }.items()
            ),
            "actual_oa_fresh_authorization": (
                requester_authorization["active"] is True
                and approval["resume"]["approval_status"] == "APPROVED"
            ),
            "nsl_prefix_suspended": approval["prefix_status"] == "WAITING_FOR_APPROVAL",
            "canonical_payload_hash_preserved": (
                approval["payload_hash"] == canonical_payload_hash
            ),
            "approval_event_matched_once": (
                approval["matched_event"]["inbox_state"] == "MATCHED"
                and approval["mismatch_event"]["inbox_state"] == "REJECTED"
            ),
            "resume_completed": (
                approval["resume"]["runtime_job_state"] == "DONE"
                and approval["resume"]["approval_gate_passed"] is True
            ),
            "lineage_exact": approval["lineage_exact"] is True,
            "zero_eos_mutation": (
                approval["resume"]["eos_mutation_count"] == 0
                and approval["prefix_audit"]["write_requested_count"] == 0
            ),
            "approval_cleanup_complete": approval["cleanup_remaining"] == 0,
        }
        return {
            "checks": checks,
            "planning_rows": row_counts,
            "lineage": {
                "agent_execution_id": execution["agent_execution_id"],
                "work_intent_id": planning.work_intent["work_intent_id"],
                "agent_plan_id": planning.plan_stage.agent_plan["agent_plan_id"],
                "executable_plan_id": planning.executable_plan["executable_plan_id"],
                "capability_id": exact_binding["capability_id"],
                "skill_id": exact_binding["skill_id"],
                "tool_id": exact_binding["tool_id"],
            },
            "approval": {
                "prefix_status": approval["prefix_status"],
                "inbox_state": approval["matched_event"]["inbox_state"],
                "resume_state": approval["resume"]["runtime_job_state"],
                "approval_status": approval["resume"]["approval_status"],
                "lineage_exact": approval["lineage_exact"],
                "payload_hash": approval["payload_hash"],
                "write_identity": approval["write_identity"],
                "platform_approval_evidence": approval["platform_approval_evidence"],
                "eos_mutation_count": approval["resume"]["eos_mutation_count"],
            },
        }
    finally:
        cleanup = _cleanup_ae(factory, tenant_id=tenant_id, workspace_id=workspace_id)
        engine.dispose()
        if "checks" in locals():
            checks["ae_cleanup_complete"] = cleanup["remaining"] == 0


def _persist_planning(
    factory: sessionmaker[Session],
    tenant_id: str,
    execution: Mapping[str, Any],
    planning: Any,
    now: str,
) -> None:
    SqlAlchemyWorkIntentRepository(factory).save(
        tenant_id=tenant_id, work_intent=planning.work_intent, created_at=now
    )
    SqlAlchemyAgentContextRepository(factory).save(
        tenant_id=tenant_id, agent_context=planning.agent_context
    )
    SqlAlchemyCapabilitySnapshotRepository(factory).save(planning.capability_snapshot)
    SqlAlchemyAgentPlanRepository(factory).save(
        tenant_id=tenant_id,
        agent_plan=planning.plan_stage.agent_plan,
        created_at=now,
    )
    SqlAlchemyPlanValidationRepository(factory).save_and_apply_runtime(
        tenant_id=tenant_id,
        result=planning.validation,
        expected_execution_version=int(execution["version"]),
    )
    SqlAlchemyExecutablePlanRepository(factory).save(
        tenant_id=tenant_id, executable_plan=planning.executable_plan
    )


def _calibration_registry(readiness: Any) -> SemanticCalibrationRegistry:
    return SemanticCalibrationRegistry(
        tuple(
            SemanticCalibrationPolicy(
                semantic_stage=stage,
                policy_ref=f"semantic-admission://{stage.lower()}/p8-s65-live/v1",
                policy_version="p8-s65-live-v1",
                model_profile=readiness.model_profile,
                model_ref=readiness.model_ref,
                minimum_confidence=0.5,
                golden_evidence_ref=f"smoke://p8-s65/{stage.lower()}/golden",
                adversarial_evidence_ref=(
                    f"smoke://p8-s65/{stage.lower()}/adversarial"
                ),
            )
            for stage in ("INTENT", "PLAN")
        )
    )


def _customize_profile(profile: Path, fixture: Mapping[str, Any]) -> None:
    scenario = fixture["scenario"]
    account_code = next(
        item["account_code"]
        for item in fixture["accounts"]
        if item["account_id"] == fixture["voucher_line_policy"]["debit_account_id"]
    )
    counter_account_code = next(
        item["account_code"]
        for item in fixture["accounts"]
        if item["account_id"] == fixture["voucher_line_policy"]["credit_account_id"]
    )
    project_code = fixture["projects"]["child"]["project_code"]
    accounting_period = str(scenario["transaction_date"])[:7]
    description = str(scenario["description"])
    tenant_id = str(fixture["tenant"]["tenant_id"])
    requester_id = str(scenario["requester_subject_id"])
    amount = {
        "$type": "Money",
        "amount": scenario["amount"],
        "currency": scenario["currency"],
    }
    input_value = {
        "tenant_id": tenant_id,
        "requester_id": requester_id,
        "account_code": account_code,
        "counter_account_code": counter_account_code,
        "project_code": project_code,
        "accounting_period": accounting_period,
        "amount": amount,
        "transaction_date": scenario["transaction_date"],
        "voucher_type": scenario["voucher_type"],
        "economic_category": scenario["economic_category"],
        "settlement_method": scenario["settlement_method"],
        "description_text": description,
    }
    input_path = profile.parent / "input.json"
    input_path.write_text(
        json.dumps(input_value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    fixture_path = profile.parent / "fixtures/success.json"
    tool_fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    replacements: dict[str, tuple[str, str]] = {
        "ACCOUNT.GET_ACCOUNT": ("account_code", account_code),
        "PROJECT.GET_PROJECT": ("project_code", project_code),
        "FINANCE.GET_ACCOUNTING_PERIOD": (
            "accounting_period",
            accounting_period,
        ),
    }
    for tool in tool_fixture["tools"]:
        if tool["tool_id"] == "FINANCE.RESOLVE_VOUCHER_DRAFT_COMMAND":
            case = tool["cases"][0]
            case["arguments"] = input_value
            case["result"] = build_golden_a_canonical_write_payload(fixture)
            continue
        key, value = replacements[tool["tool_id"]]
        tool["cases"][0]["arguments"][key] = value
        tool["cases"][0]["result"][key] = value
    fixture_path.write_text(
        json.dumps(tool_fixture, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _copy_golden_a_profile(*, source: Path, case_root: Path) -> Path:
    shutil.copytree(source / "examples/golden_a_voucher_draft", case_root)
    return case_root / "controlled.profile.json"


def _build_oa_app(database_url: str) -> Any:  # pragma: no cover - live gate.
    spec = SERVICE_SPECS["nex-oa"]
    app = build_service_app(spec)
    runtime = attach_service_persistence_runtime(
        app,
        spec,
        environ={
            spec.database_env: database_url,
            "NEX_OA_PERSISTENCE_MODE": "postgres",
        },
    )
    subjects = build_subject_registry_for_runtime(runtime)
    memberships = build_tenant_membership_registry_for_runtime(
        runtime, subject_registry=subjects
    )
    authorization_repository = build_authorization_repository_for_runtime(runtime)
    resolver = OaEffectiveAuthorizationResolver(repository=authorization_repository)
    register_subject_registry_routes(app, registry=subjects)
    register_identity_membership_routes(app, registry=memberships)
    register_authorization_routes(
        app,
        service=OaAuthorizationService(
            repository=authorization_repository,
            resolver=resolver,
            membership_registry=memberships,
        ),
    )
    return app


def _seed_identity(  # pragma: no cover - live gate.
    app: Any,
    *,
    tenant_id: str,
    subject_id: str,
    roles: list[str],
    scopes: list[str],
) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/internal/v1/identity/memberships/ensure",
            headers={
                "Authorization": "Bearer "
                + _service_token(
                    "nex-ae-api",
                    "nex-oa",
                    OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE,
                ),
                "X-Service-ID": "nex-ae-api",
                "X-Request-ID": str(uuid4()),
            },
            json={
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "tenant_display_name": "P8 Golden A",
                "subject_display_name": f"P8-S65 {subject_id}",
                "status": "ACTIVE",
                "roles": roles,
                "scopes": sorted({DEFAULT_USER_SCOPE, *scopes}),
                "membership_metadata": {"smoke_marker": "p8-s65"},
            },
        )
        response.raise_for_status()


def _service_token(service_id: str, audience: str, *scopes: str) -> str:
    return issue_mock_service_token(
        service_id=service_id,
        audience=audience,
        scopes=[DEFAULT_SERVICE_SCOPE, *scopes],
    ).access_token


def _planning_counts(factory: sessionmaker[Session], tenant_id: str) -> dict[str, int]:
    tables = (
        "ae_work_intent",
        "ae_agent_context",
        "ae_capability_snapshot",
        "ae_agent_plan",
        "ae_plan_validation",
        "ae_executable_plan",
        "ae_executable_step",
    )
    with factory() as session:
        return {
            table: int(
                session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant"),
                    {"tenant": tenant_id},
                ).scalar_one()
            )
            for table in tables
        }


def _cleanup_ae(
    factory: sessionmaker[Session], *, tenant_id: str, workspace_id: str
) -> dict[str, int]:
    tables = (
        "ae_runtime_job_attempt",
        "ae_external_event_inbox",
        "ae_approval_evidence",
        "ae_wait_registration",
        "ae_runtime_job",
        "ae_nsl_approval_request",
        "ae_executable_step",
        "ae_executable_plan",
        "ae_plan_validation",
        "ae_agent_plan",
        "ae_capability_snapshot",
        "ae_agent_context",
        "ae_work_intent",
        "ae_agent_execution",
        "ae_conversation_events",
        "ae_conversation_messages",
        "ae_conversations",
        "ae_ia_principal_assignment",
        "ae_agent_identity",
    )
    with factory.begin() as session:
        for table in tables:
            session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tenant"),
                {"tenant": tenant_id},
            )
        session.execute(
            text("DELETE FROM ae_workspace_activities WHERE workspace_id = :id"),
            {"id": workspace_id},
        )
        session.execute(
            text("DELETE FROM ae_workspaces WHERE workspace_id = :id"),
            {"id": workspace_id},
        )
    with factory() as session:
        remaining = sum(
            int(
                session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant"),
                    {"tenant": tenant_id},
                ).scalar_one()
            )
            for table in tables
        )
    return {"remaining": remaining}


def _cleanup_oa(engine: Any, tenant_id: str) -> int:
    tables = (
        "oa_user_sessions",
        "oa_local_credentials",
        "oa_tenant_memberships",
        "oa_subjects",
        "oa_tenants",
    )
    with engine.begin() as connection:
        for table in tables:
            connection.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tenant"),
                {"tenant": tenant_id},
            )
    with engine.connect() as connection:
        return sum(
            int(
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant"),
                    {"tenant": tenant_id},
                ).scalar_one()
            )
            for table in tables
        )


def _require_database_target(
    value: str, *, role: str, database: str, label: str
) -> None:
    if not value:
        raise P8S65SmokeError(f"{label} is required")
    parsed = urlsplit(value)
    if (
        unquote(parsed.username or "") != role
        or unquote(parsed.path.lstrip("/")) != database
    ):
        raise P8S65SmokeError(f"{label} must target {role}@.../{database}")


def _migration_summary(value: Any) -> dict[str, Any]:
    return {
        "planned_count": len(value.planned),
        "applied_count": len(value.applied),
        "skipped_count": len(value.skipped),
        "latest_version": value.planned[-1] if value.planned else None,
    }


def _assert_redacted(evidence: Mapping[str, Any], env: Mapping[str, str]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    for key in PROTECTED_ENV_KEYS:
        value = str(env.get(key, ""))
        if len(value) >= 8 and value in serialized:
            raise P8S65SmokeError(f"protected evidence leaked {key}")


def _redact(detail: str, *database_urls: str) -> str:
    result = detail
    for database_url in database_urls:
        if not database_url:
            continue
        result = result.replace(database_url, redact_database_url(database_url))
        password = urlsplit(database_url).password
        if password:
            result = result.replace(unquote(password), "***")
    return result


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    provider = evidence.get("provider") or {}
    approval = evidence.get("approval") or {}
    return (
        "p8_s65_golden_a_approval_journey="
        f"{str(evidence.get('status', 'FAIL')).lower()} "
        f"postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"provider={str(bool(evidence.get('actual_remote_provider'))).lower()} "
        f"model={provider.get('model_ref', 'not-run')} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"approval={approval.get('approval_status', 'not-run')} "
        f"resume={approval.get('resume_state', 'not-run')}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run P8-S65 Golden A IA to NSL approval protected journey"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    load_env_file(ROOT / ".env.local")
    evidence = run_p8_s65_golden_a_approval_journey(
        execute=args.execute, source=args.source, python_bin=args.python_bin
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
