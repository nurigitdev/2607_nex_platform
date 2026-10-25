#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
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

import run_ae_web_credential_login_playwright_postgres_smoke as browser_smoke
import run_p65_s7_postgres_live_e2e as p65_s7
from nex_ae_api.intent_candidate_generation import LiveIntentCandidateService
from nex_ae_api.mo_generation_client import build_default_ae_mo_generation_client
from nex_ae_api.project_membership_batch import (
    PROJECT_MEMBERSHIP_ADD_MANY,
    HttpOaEmployeeBatchResolutionSource,
)
from nex_ae_api.project_membership_batch_orchestration import (
    build_project_membership_batch_result_projection,
    orchestrate_project_membership_batch_candidate,
)
from nex_ae_api.prompt_persistence import SqlAlchemyAePromptRegistryStore
from nex_ae_api.prompts import seed_ae_prompt_registry
from nex_ae_api.semantic_candidates import (
    SemanticCalibrationPolicy,
    SemanticCalibrationRegistry,
)
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_PROJECT_MEMBER_TABLE,
    EOS_PROJECT_TABLE,
    NVT_PROJECT_ADMIN_SCOPE,
    NVT_PROJECT_CREATE_OPERATION,
    NVT_PROJECT_CREATE_SCOPE,
    NVT_PROJECT_READ_SCOPE,
    NVT_PROJECT_UPDATE_OPERATION,
    PROJECT_ADMIN_SCOPE,
    PROJECT_CREATE_OPERATION,
    PROJECT_CREATE_SCOPE,
    PROJECT_MEMBERSHIP_ADD_MANY_OPERATION,
    PROJECT_MEMBERSHIP_MANAGE_SCOPE,
    PROJECT_READ_SCOPE,
    EosGovernedProjectService,
    EosServiceCaller,
    SqlAlchemyEosBusinessTransactionCoordinator,
    build_eos_database_runtime,
    deterministic_project_membership_id,
    project_operation_payload_hash,
)
from nex_eos import (
    HttpOaAuthorizationSource as EosHttpOaAuthorizationSource,
)
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
from nex_oa.credentials import (
    build_credential_registry_for_runtime,
    register_local_credential_routes,
)
from nex_oa.employee_batch_resolution import (
    OA_EMPLOYEE_BATCH_RESOLVE_SCOPE,
    OaEmployeeBatchResolver,
    register_employee_batch_resolution_routes,
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
    sqlalchemy_database_url,
)
from nex_wc.approvals import (
    ApprovalDecisionAuthorizer,
    ApprovalDecisionService,
    ApprovalWorkItemService,
    SqlAlchemyApprovalWorkItemRepository,
)
from nex_wc.coordination_clients import HttpAuthorizationSource
from run_migrations import run_service_migrations
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

SCHEMA_VERSION = "p8_s112_nvt_membership_acceptance.v1"
SMOKE_ENV = "NEX_P8_S112_PROTECTED_ACCEPTANCE"
DEFAULT_REPORT = ROOT / "reports/acceptance/p8-s112-protected.json"
NODE_SCRIPT = ROOT / "apps/nex-ae-web/scripts/runP8S112ProjectMembershipPlaywrightSmoke.mjs"
EXPECTED_DATABASES = {
    "NEX_OA_TEST_DATABASE_URL": ("nex_oa_user", "nex_oa_test"),
    "NEX_AE_TEST_DATABASE_URL": ("nex_ae_user", "nex_ae_test"),
    "NEX_WC_TEST_DATABASE_URL": ("nex_wc_user", "nex_wc_test"),
    "NEX_EOS_TEST_DATABASE_URL": ("nex_eos_user", "nex_eos_test"),
}
PROTECTED_ENV_KEYS = (
    *EXPECTED_DATABASES,
    "NEX_MO_VLLM_API_KEY",
    "NEX_AE_TO_MO_SERVICE_TOKEN",
    browser_smoke.PASSWORD_ENV,
)


class P8S112AcceptanceError(RuntimeError):
    pass


def run_p8_s112_nvt_membership_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool,
    journey_runner: Any = None,
    browser_runner: Any = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S112",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {SMOKE_ENV}=1 are required",
            "actual_postgres": False,
            "actual_remote_provider": False,
            "actual_playwright": False,
        }
    journey_runner = journey_runner or _execute_live_journey
    browser_runner = (
        browser_runner
        or browser_smoke.run_ae_web_credential_login_playwright_postgres_smoke
    )
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
            "NEX_MO_BASE_URL": "http://p8-s112-in-process-mo",
        }
        effective_env.setdefault(
            "NEX_AE_TO_MO_SERVICE_TOKEN",
            _service_token("nex-ae-api", "nex-mo"),
        )
        migrations = {
            service_id: run_service_migrations(
                service_id,
                database_url=database_urls[database_env],
                profile="test",
            )
            for service_id, database_env in (
                ("nex-oa", "NEX_OA_TEST_DATABASE_URL"),
                ("nex-ae-api", "NEX_AE_TEST_DATABASE_URL"),
                ("nex-wc", "NEX_WC_TEST_DATABASE_URL"),
                ("nex-eos", "NEX_EOS_TEST_DATABASE_URL"),
            )
        }
        backend = journey_runner(effective_env, database_urls)
        if backend.get("status") != "PASS":
            raise P8S112AcceptanceError("protected backend journey failed")

        projection = backend["project_membership_batch_result"]

        def prepare_runner(browser_env: dict[str, str], profile: str):
            prepared = browser_smoke.prepare_playwright_postgres_smoke(
                browser_env, profile=profile
            )
            _register_browser_routes(prepared.ae_app, projection=projection)
            return prepared

        browser = browser_runner(
            {
                **effective_env,
                browser_smoke.SMOKE_ENV: "1",
                browser_smoke.CHROMIUM_EXECUTABLE_ENV: effective_env.get(
                    browser_smoke.CHROMIUM_EXECUTABLE_ENV,
                    "/usr/bin/google-chrome",
                ),
            },
            prepare_runner=prepare_runner,
            node_runner=_run_browser_node,
        )
        node = browser.get("source_smokes", {}).get("node_playwright", {})
        checks = {
            "actual_oa_ae_wc_eos_postgres": backend.get("actual_postgres") is True,
            "live_nvt_and_membership_intent": backend.get(
                "live_generation_stages"
            )
            == ["INTENT", "INTENT"],
            "nvt_crud_verified": backend.get("nvt_crud_verified") is True,
            "oa_batch_resolution_verified": backend.get(
                "oa_batch_resolution_verified"
            )
            is True,
            "wc_approval_verified": backend.get("wc_approval_verified") is True,
            "eos_exact_replay_verified": backend.get(
                "eos_exact_replay_verified"
            )
            is True,
            "partial_result_projected": projection.get("overall_status")
            == "PARTIALLY_APPLIED",
            "authenticated_playwright": browser.get("status") == "PASS",
            "playwright_batch_surface": node.get("status") == "PASS",
            "backend_zero_residue": backend.get("residue_count") == 0,
        }
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S112",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "actual_postgres": True,
            "actual_remote_provider": True,
            "actual_playwright": True,
            "migrations": {
                service: {
                    "planned": len(result.planned),
                    "applied": len(result.applied),
                    "skipped": len(result.skipped),
                }
                for service, result in migrations.items()
            },
            "backend": {
                key: backend[key]
                for key in (
                    "model_profile",
                    "model_ref",
                    "nvt_intent_label",
                    "membership_intent_label",
                    "nvt_crud_verified",
                    "oa_batch_resolution_verified",
                    "wc_approval_verified",
                    "eos_exact_replay_verified",
                    "residue_count",
                )
            },
            "browser": {
                "status": browser.get("status"),
                "node_status": node.get("status"),
                "observations": browser.get("browser_observations", {}),
                "cleanup": browser.get("cleanup_observations", {}),
            },
            "result_summary": projection["summary"],
            "checks": checks,
            "checks_passed": sum(bool(value) for value in checks.values()),
            "checks_total": len(checks),
            "redaction": {
                "raw_prompt_included": False,
                "credentials_included": False,
                "database_endpoints_included": False,
                "provider_endpoint_included": False,
            },
        }
        _assert_redacted(evidence, effective_env)
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected gate records safe failure.
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S112",
            "status": "FAIL",
            "actual_postgres": False,
            "actual_remote_provider": False,
            "actual_playwright": False,
            "failure_code": type(exc).__name__,
            "detail": "protected acceptance failed",
            "checks": {},
        }
        _assert_redacted(evidence, env)
        return evidence


def _execute_live_journey(
    env: dict[str, str], database_urls: Mapping[str, str]
) -> dict[str, Any]:  # pragma: no cover - actual PostgreSQL/DGX gate.
    suffix = uuid4().hex[:10]
    tenant_id = f"tenant-p8-s112-{suffix}"
    operator_id = f"operator-p8-s112-{suffix}"
    approver_id = f"approver-p8-s112-{suffix}"
    target_id = f"member-p8-s112-{suffix}"
    nvt_id = str(uuid4())
    project_id = str(uuid4())
    trace_id = uuid4().hex
    nvt_request_id = f"p8-s112-nvt-{suffix}"
    batch_request_id = f"p8-s112-batch-{suffix}"
    now = datetime.now(UTC).replace(microsecond=0)
    oa_engine = create_engine(
        sqlalchemy_database_url(database_urls["NEX_OA_TEST_DATABASE_URL"]),
        poolclass=NullPool,
    )
    ae_engine = create_engine(
        sqlalchemy_database_url(database_urls["NEX_AE_TEST_DATABASE_URL"]),
        poolclass=NullPool,
    )
    wc_engine = create_engine(
        sqlalchemy_database_url(database_urls["NEX_WC_TEST_DATABASE_URL"]),
        poolclass=NullPool,
    )
    eos_runtime = build_eos_database_runtime(
        environ={
            "NEX_EOS_TEST_DATABASE_URL": database_urls["NEX_EOS_TEST_DATABASE_URL"]
        },
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    oa_server = None
    original_environ = dict(os.environ)
    result: dict[str, Any] | None = None
    try:
        _cleanup_oa(oa_engine, tenant_id)
        _cleanup_wc(wc_engine, tenant_id)
        _cleanup_eos(eos_runtime.engine, tenant_id)
        _cleanup_ae(ae_engine, (nvt_request_id, batch_request_id))
        identities = _database_identities(
            oa_engine=oa_engine,
            ae_engine=ae_engine,
            wc_engine=wc_engine,
            eos_engine=eos_runtime.engine,
        )
        oa_app = _build_oa_app(database_urls["NEX_OA_TEST_DATABASE_URL"])
        common_scopes = [DEFAULT_USER_SCOPE]
        _seed_oa_identity(
            oa_app,
            tenant_id=tenant_id,
            subject_id=operator_id,
            employee_id=f"EMP-OP-{suffix}",
            display_name="시연 운영자",
            scopes=[
                *common_scopes,
                NVT_PROJECT_CREATE_SCOPE,
                NVT_PROJECT_READ_SCOPE,
                NVT_PROJECT_ADMIN_SCOPE,
                PROJECT_CREATE_SCOPE,
                PROJECT_READ_SCOPE,
                PROJECT_ADMIN_SCOPE,
                PROJECT_MEMBERSHIP_MANAGE_SCOPE,
            ],
        )
        _seed_oa_identity(
            oa_app,
            tenant_id=tenant_id,
            subject_id=approver_id,
            employee_id=f"EMP-AP-{suffix}",
            display_name="시연 승인자",
            scopes=[*common_scopes, "approval:read", "approval:decide"],
        )
        _seed_oa_identity(
            oa_app,
            tenant_id=tenant_id,
            subject_id=target_id,
            employee_id="EMP-S112-01",
            display_name="홍길동",
            scopes=common_scopes,
        )
        _seed_oa_identity(
            oa_app,
            tenant_id=tenant_id,
            subject_id=f"mismatch-p8-s112-{suffix}",
            employee_id="EMP-S112-02",
            display_name="김정확",
            scopes=common_scopes,
        )
        oa_server = browser_smoke.start_api_server(
            oa_app, browser_smoke.find_free_port()
        )
        eos_authorization = EosHttpOaAuthorizationSource(
            base_url=oa_server.url,
            service_token=_service_token(
                "nex-eos", "nex-oa", OA_AUTHORIZATION_READ_SCOPE
            ),
        )
        wc_authorization = HttpAuthorizationSource(
            base_url=oa_server.url,
            service_token=_service_token(
                "nex-wc", "nex-oa", OA_AUTHORIZATION_READ_SCOPE
            ),
        )
        eos = EosGovernedProjectService(
            session_factory=eos_runtime.session_factory,
            coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
                eos_runtime.session_factory
            ),
            authorization_source=eos_authorization,
        )
        caller = EosServiceCaller(
            "service:nex-ae-api", "nex-eos", (DEFAULT_SERVICE_SCOPE,)
        )

        os.environ.clear()
        os.environ.update(env)
        mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
        register_mock_provider_routes(mo_app)
        register_provider_readiness_routes(
            mo_app, service=ProviderReadinessService(environ=env)
        )
        ae_factory = sessionmaker(
            bind=ae_engine, autoflush=False, expire_on_commit=False
        )
        prompt_store = SqlAlchemyAePromptRegistryStore(ae_factory)
        seed_ae_prompt_registry(prompt_store)
        with TestClient(mo_app) as mo_client:
            generation_client = p65_s7.CountingGenerationClient(
                build_default_ae_mo_generation_client(
                    env, requester=p65_s7.TestClientRequester(mo_client)
                )
            )
            readiness = generation_client.check_required_mode_readiness(
                request_id=f"p8-s112-ready-{suffix}", trace_id=trace_id
            )
            intent_service = LiveIntentCandidateService(
                generation_client,
                prompt_store,
                _calibration_registry(readiness),
            )
            nvt_stage = _generate_intent(
                intent_service,
                prompt="NVT 코드 NVT-DEMO, 이름 회장님 시연 NVT인 NVT 프로젝트를 생성해줘.",
                actor_ref=operator_id,
                request_id=nvt_request_id,
                trace_id=trace_id,
            )
            batch_stage = _generate_intent(
                intent_service,
                prompt=(
                    "NVT-DEMO 프로젝트에 사번 EMP-S112-01 홍길동, "
                    "EMP-S112-02 잘못된이름, EMP-S112-404 직원을 "
                    "MEMBER 역할로 한 번에 추가해줘."
                ),
                actor_ref=operator_id,
                request_id=batch_request_id,
                trace_id=trace_id,
            )

        if nvt_stage.candidate.get("intent_label") != NVT_PROJECT_CREATE_OPERATION:
            raise P8S112AcceptanceError("live NVT intent label was not admitted")
        if batch_stage.candidate.get("intent_label") != PROJECT_MEMBERSHIP_ADD_MANY:
            raise P8S112AcceptanceError("live membership intent label was not admitted")

        created_nvt = eos.create_nvt_project(
            _project_payload(
                NVT_PROJECT_CREATE_OPERATION,
                tenant_id=tenant_id,
                requester_subject_id=operator_id,
                sequence=1,
                nvt_project={
                    "nvt_project_id": nvt_id,
                    "nvt_project_code": "NVT-DEMO",
                    "name": "회장님 시연 NVT",
                    "status": "ACTIVE",
                },
            ),
            caller=caller,
        )
        read_nvt = eos.get_nvt_project(
            tenant_id=tenant_id,
            nvt_project_id=nvt_id,
            requester_subject_id=operator_id,
        )
        listed_nvt = eos.list_nvt_projects(
            tenant_id=tenant_id,
            requester_subject_id=operator_id,
            status="ACTIVE",
        )
        updated_nvt = eos.update_nvt_project(
            _project_payload(
                NVT_PROJECT_UPDATE_OPERATION,
                tenant_id=tenant_id,
                requester_subject_id=operator_id,
                sequence=2,
                nvt_project_id=nvt_id,
                expected_version=read_nvt["version"],
                changes={"name": "회장님 시연 NVT v2"},
            ),
            caller=caller,
        )
        eos.create_project(
            _project_payload(
                PROJECT_CREATE_OPERATION,
                tenant_id=tenant_id,
                requester_subject_id=operator_id,
                sequence=3,
                project={
                    "project_id": project_id,
                    "project_code": "NVT-DEMO",
                    "name": "NVT 시연 프로젝트",
                    "nvt_project_id": nvt_id,
                    "currency": "KRW",
                },
                initial_owner_subject_id=operator_id,
                initial_owner_membership_id=deterministic_project_membership_id(
                    tenant_id, project_id, operator_id
                ),
            ),
            caller=caller,
        )
        oa_source = HttpOaEmployeeBatchResolutionSource(
            base_url=oa_server.url,
            service_token=_service_token(
                "nex-ae-api", "nex-oa", OA_EMPLOYEE_BATCH_RESOLVE_SCOPE
            ),
        )
        orchestration = orchestrate_project_membership_batch_candidate(
            candidate=batch_stage.candidate,
            tenant_id=tenant_id,
            requester_subject_id=operator_id,
            projects=[
                {
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "project_code": "NVT-DEMO",
                    "name": "NVT 시연 프로젝트",
                    "status": "ACTIVE",
                }
            ],
            source=oa_source,
            request_id=f"p8-s112-oa-{suffix}",
            trace_id=trace_id,
        )
        admission = orchestration["admission"]
        if admission is None or admission["directive"] != "CONTINUE":
            raise P8S112AcceptanceError(
                "membership batch was not admitted: "
                f"{orchestration.get('failure_code')}"
            )

        wc_factory = sessionmaker(
            bind=wc_engine, autoflush=False, expire_on_commit=False
        )
        wc_repository = SqlAlchemyApprovalWorkItemRepository(wc_factory)
        work_item = _approval_work_item(
            tenant_id=tenant_id,
            approver_id=approver_id,
            project_id=project_id,
            admission=admission,
            now=now,
        )
        created_approval = ApprovalWorkItemService(wc_repository).create_or_get(
            work_item
        )
        decision = ApprovalDecisionService(
            wc_repository,
            authorizer=ApprovalDecisionAuthorizer(
                wc_authorization, clock=lambda: now + timedelta(seconds=1)
            ),
            clock=lambda: now + timedelta(seconds=1),
        ).decide(
            tenant_id=tenant_id,
            approval_work_item_id=work_item["approval_work_item_id"],
            decision="APPROVE",
            decided_by=approver_id,
            decision_comment="P8-S112 protected acceptance",
        )

        governed = {
            "schema_version": "eos_project_operation.v1",
            "business_operation_id": str(uuid4()),
            "idempotency_key": f"p8-s112-members-{suffix}",
            "requested_operation": PROJECT_MEMBERSHIP_ADD_MANY_OPERATION,
            **admission["governed_payload"],
            "payload_hash": admission["payload_hash"],
        }
        committed = eos.add_memberships(governed, caller=caller)
        replayed = eos.add_memberships(governed, caller=caller)
        projection = build_project_membership_batch_result_projection(
            admission, committed
        )
        counts = _domain_counts(
            ae_engine=ae_engine,
            wc_engine=wc_engine,
            eos_engine=eos_runtime.engine,
            tenant_id=tenant_id,
            request_ids=(nvt_request_id, batch_request_id),
        )
        result = {
            "status": "PASS",
            "actual_postgres": identities
            == {
                "oa": ["nex_oa_test", "nex_oa_user"],
                "ae": ["nex_ae_test", "nex_ae_user"],
                "wc": ["nex_wc_test", "nex_wc_user"],
                "eos": ["nex_eos_test", "nex_eos_user"],
            },
            "model_profile": readiness.model_profile,
            "model_ref": readiness.model_ref,
            "live_generation_stages": generation_client.generation_stages,
            "nvt_intent_label": nvt_stage.candidate["intent_label"],
            "membership_intent_label": batch_stage.candidate["intent_label"],
            "nvt_crud_verified": (
                created_nvt["commit_state"] == "COMMITTED"
                and read_nvt["nvt_project_code"] == "NVT-DEMO"
                and len(listed_nvt) == 1
                and updated_nvt["result"]["nvt_project"]["name"].endswith("v2")
            ),
            "oa_batch_resolution_verified": (
                admission["requested_count"] == 3
                and admission["admitted_count"] == 1
                and len(admission["rejected_candidates"]) == 2
            ),
            "wc_approval_verified": (
                created_approval["created"] is True
                and decision["decision"]["decision"] == "APPROVE"
            ),
            "eos_exact_replay_verified": (
                committed["created"] is True
                and replayed["created"] is False
                and committed["result"] == replayed["result"]
            ),
            "project_membership_batch_result": projection,
            "row_counts": counts,
        }
        if not all(
            result[key]
            for key in (
                "actual_postgres",
                "nvt_crud_verified",
                "oa_batch_resolution_verified",
                "wc_approval_verified",
                "eos_exact_replay_verified",
            )
        ):
            raise P8S112AcceptanceError("protected backend checks failed")
        return result
    finally:
        os.environ.clear()
        os.environ.update(original_environ)
        if oa_server is not None:
            oa_server.stop()
        _cleanup_ae(ae_engine, (nvt_request_id, batch_request_id))
        _cleanup_wc(wc_engine, tenant_id)
        _cleanup_eos(eos_runtime.engine, tenant_id)
        _cleanup_oa(oa_engine, tenant_id)
        residue = _residue_count(
            oa_engine=oa_engine,
            ae_engine=ae_engine,
            wc_engine=wc_engine,
            eos_engine=eos_runtime.engine,
            tenant_id=tenant_id,
            request_ids=(nvt_request_id, batch_request_id),
        )
        if result is not None:
            result["residue_count"] = residue
        oa_engine.dispose()
        ae_engine.dispose()
        wc_engine.dispose()
        eos_runtime.dispose()


def _generate_intent(
    service: LiveIntentCandidateService,
    *,
    prompt: str,
    actor_ref: str,
    request_id: str,
    trace_id: str,
) -> Any:
    return service.generate_and_resolve(
        user_prompt=prompt,
        execution_id=str(uuid4()),
        source_ref=f"conversation:p8-s112:{request_id}",
        actor_ref=actor_ref,
        received_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        request_id=request_id,
        trace_id=trace_id,
        planning_mode="required",
        trusted_execution_mode="GENERAL_ANSWER",
        retrieval_enabled=False,
        authorized_resource_context_available=False,
        work_intent_id=str(uuid4()),
    )


def _build_oa_app(database_url: str) -> Any:
    spec = SERVICE_SPECS["nex-oa"]
    app = build_service_app(spec)
    runtime = attach_service_persistence_runtime(
        app,
        spec,
        environ={spec.database_env: database_url, "NEX_OA_PERSISTENCE_MODE": "postgres"},
    )
    subjects = build_subject_registry_for_runtime(runtime)
    memberships = build_tenant_membership_registry_for_runtime(
        runtime, subject_registry=subjects
    )
    credentials = build_credential_registry_for_runtime(
        runtime, subject_registry=subjects
    )
    repository = build_authorization_repository_for_runtime(runtime)
    resolver = OaEffectiveAuthorizationResolver(repository=repository)
    register_subject_registry_routes(app, registry=subjects)
    register_identity_membership_routes(app, registry=memberships)
    register_local_credential_routes(app, registry=credentials)
    register_employee_batch_resolution_routes(
        app,
        resolver=OaEmployeeBatchResolver(
            credential_registry=credentials,
            membership_registry=memberships,
        ),
    )
    register_authorization_routes(
        app,
        service=OaAuthorizationService(
            repository=repository,
            resolver=resolver,
            membership_registry=memberships,
        ),
    )
    return app


def _seed_oa_identity(
    app: Any,
    *,
    tenant_id: str,
    subject_id: str,
    employee_id: str,
    display_name: str,
    scopes: Sequence[str],
) -> None:
    headers = {
        "Authorization": "Bearer "
        + _service_token(
            "nex-ae-api", "nex-oa", OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE
        ),
        "X-Service-ID": "nex-ae-api",
        "X-Request-ID": str(uuid4()),
    }
    with TestClient(app) as client:
        membership = client.post(
            "/internal/v1/identity/memberships/ensure",
            headers=headers,
            json={
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "tenant_display_name": "P8-S112 Protected Tenant",
                "subject_display_name": display_name,
                "status": "ACTIVE",
                "roles": ["employee"],
                "scopes": sorted(set(scopes)),
                "membership_metadata": {"smoke_marker": "p8-s112"},
            },
        )
        membership.raise_for_status()
        credential = client.post(
            "/internal/v1/auth/local-credentials/ensure",
            headers=headers,
            json={
                "tenant_id": tenant_id,
                "employee_id": employee_id,
                "subject_id": subject_id,
                "password": "P8S112-Not-For-Login!",
                "credential_metadata": {"smoke_marker": "p8-s112"},
            },
        )
        credential.raise_for_status()


def _project_payload(
    operation: str,
    *,
    tenant_id: str,
    requester_subject_id: str,
    sequence: int,
    **values: Any,
) -> dict[str, Any]:
    payload = {
        "schema_version": "eos_project_operation.v1",
        "tenant_id": tenant_id,
        "business_operation_id": str(uuid4()),
        "idempotency_key": f"p8-s112-{sequence}-{tenant_id}",
        "requester_subject_id": requester_subject_id,
        **values,
    }
    payload["payload_hash"] = project_operation_payload_hash(payload, operation)
    return payload


def _approval_work_item(
    *,
    tenant_id: str,
    approver_id: str,
    project_id: str,
    admission: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    approval_id = str(uuid4())
    return {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": tenant_id,
        "approval_work_item_id": str(uuid4()),
        "approval_domain": "NSL_WRITE",
        "source_ref": approval_id,
        "semantic_hash": admission["admission_hash"],
        "title": "프로젝트 멤버 일괄 추가 승인",
        "display_safe_summary": "해석된 직원 집합을 프로젝트에 추가합니다.",
        "approval_provider_type": "NSL",
        "approval_target_ref": approval_id,
        "target_approver_ref": approver_id,
        "target_role_ref": None,
        "target_org_scope_ref": None,
        "target_project_scope_ref": project_id,
        "agent_execution_id": str(uuid4()),
        "executable_step_id": str(uuid4()),
        "nsl_execution_id": str(uuid4()),
        "business_operation_id": str(uuid4()),
        "approval_request_id": approval_id,
        "protected_request_ref": f"ae-private:{approval_id}",
        "resume_target_ref": f"ae-wait:{approval_id}",
        "state": "PENDING",
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "version": 1,
    }


def _calibration_registry(readiness: Any) -> SemanticCalibrationRegistry:
    return SemanticCalibrationRegistry(
        (
            SemanticCalibrationPolicy(
                semantic_stage="INTENT",
                policy_ref="semantic-admission://intent/p8-s112-live/v1",
                policy_version="p8-s112-live-v1",
                model_profile=readiness.model_profile,
                model_ref=readiness.model_ref,
                minimum_confidence=0.5,
                golden_evidence_ref="smoke://p8-s112/intent/golden",
                adversarial_evidence_ref="smoke://p8-s112/intent/adversarial",
            ),
        )
    )


def _register_browser_routes(app: Any, *, projection: Mapping[str, Any]) -> None:
    interaction_id = "p8-s112-membership-interaction"
    assistant_text = "프로젝트 멤버 일괄 추가가 처리되었습니다."
    content_sha = hashlib.sha256(assistant_text.encode("utf-8")).hexdigest()

    def admitted(request: Request) -> JSONResponse | None:
        if not request.cookies:
            return JSONResponse({"error_code": "SESSION_REQUIRED"}, status_code=401)
        return None

    @app.post("/api/v1/chat/interactions", response_model=None)
    def create_interaction(payload: dict[str, Any], request: Request):
        denial = admitted(request)
        if denial is not None:
            return denial
        return _interaction(payload, interaction_id, "PENDING")

    @app.get("/api/v1/chat/interactions/{requested_id}/progress", response_model=None)
    def progress(requested_id: str, request: Request):
        denial = admitted(request)
        if denial is not None:
            return denial
        _require_interaction(requested_id, interaction_id)
        return {
            "progress_schema_version": "ae_generation_progress.v1",
            "interaction_id": interaction_id,
            "job_id": "p8-s112-browser-job",
            "cx_generation_id": "p8-s112-live-generation",
            "lifecycle_status": "COMPLETED",
            "event_type": "generation.completed",
            "current_stage": "COMPLETED",
            "progress_mode": "DETERMINATE",
            "progress_percent": 100,
            "message_key": "generation.progress.completed",
            "attempt_count": 1,
            "max_attempts": 1,
            "retryable": False,
            "cancellable": False,
            "terminal": True,
            "next_action": "PRESENT_GENERATION_TO_OWNER",
            "next_poll_after_seconds": None,
            "handoff_status": "READY",
            "error": None,
            "recovery": None,
        }

    @app.post("/api/v1/chat/interactions/{requested_id}/refresh", response_model=None)
    def refresh(requested_id: str, request: Request):
        denial = admitted(request)
        if denial is not None:
            return denial
        _require_interaction(requested_id, interaction_id)
        return {
            "refresh_schema_version": "ae_async_chat_refresh.v1",
            "interaction": _interaction({}, interaction_id, "COMPLETED"),
            "result": {
                "handoff_status": "READY",
                "cx_generation_id": "p8-s112-live-generation",
                "content": assistant_text,
                "content_type": "text/plain; charset=utf-8",
                "content_sha256": content_sha,
                "size_bytes": len(assistant_text.encode("utf-8")),
                "owner_scope_enforced": True,
            },
            "content_persisted_by_ae": True,
        }

    @app.get("/api/v1/chat/interactions/{requested_id}/response", response_model=None)
    def response(requested_id: str, request: Request):
        denial = admitted(request)
        if denial is not None:
            return denial
        _require_interaction(requested_id, interaction_id)
        return {
            "response_schema_version": "ae_generated_response.v1",
            "interaction_id": interaction_id,
            "chat_document_id": "p8-s112-chat",
            "response_id": "p8-s112-response",
            "cx_generation_id": "p8-s112-live-generation",
            "content_type": "text/plain; charset=utf-8",
            "content": assistant_text,
            "content_sha256": content_sha,
            "size_bytes": len(assistant_text.encode("utf-8")),
            "lineage": {"owner_scope_enforced": True, "raw_content_included": False},
            "project_membership_batch_result": dict(projection),
            "owner_scope_enforced": True,
        }

    @app.get(
        "/api/v1/chat/interactions/{requested_id}/citation-quality",
        response_model=None,
    )
    def quality(requested_id: str, request: Request):
        denial = admitted(request)
        if denial is not None:
            return denial
        _require_interaction(requested_id, interaction_id)
        return {
            "workflow_schema_version": "ae_citation_quality_workflow.v1",
            "interaction_id": interaction_id,
            "cx_generation_id": "p8-s112-live-generation",
            "workflow_status": "NOT_REQUIRED",
            "next_action": "PRESENT_RESPONSE",
            "quality": {
                "boundary_status": "NOT_REQUIRED",
                "citation_status": "NOT_REQUIRED",
                "issue_count": 0,
                "recommended_action": "proceed",
            },
            "repair": {"status": "NOT_ATTEMPTED", "attempted": False},
            "operator_remediation": {"required": False},
            "owner_scope_enforced": True,
            "content_included": False,
        }


def _interaction(payload: Mapping[str, Any], interaction_id: str, status: str):
    return {
        "interaction_schema_version": "ae_chat_interaction.v1",
        "interaction_id": interaction_id,
        "workspace_id": payload.get("workspace_id", "p8-s112-workspace"),
        "chat_document_id": payload.get("chat_document_id", "p8-s112-chat"),
        "status": status,
        "cx_generation_id": "p8-s112-live-generation",
        "cx_status": "SUCCEEDED" if status == "COMPLETED" else "QUEUED",
        "generation": {
            "async_generation": {
                "lifecycle_status": status,
                "retryable": status != "COMPLETED",
                "cancellable": status != "COMPLETED",
            }
        },
        "retrieval": None,
        "artifact_refs": [],
    }


def _require_interaction(requested: str, expected: str) -> None:
    if requested != expected:
        raise P8S112AcceptanceError("unexpected interaction identity")


def _run_browser_node(node_env: Mapping[str, str]) -> dict[str, Any]:
    env = {
        **os.environ,
        **node_env,
        "NEX_P8_S112_WEB_URL": node_env[
            "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_WEB_URL"
        ],
        "NEX_P8_S112_TENANT_ID": node_env[
            "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_TENANT_ID"
        ],
        "NEX_P8_S112_EMPLOYEE_ID": node_env[
            "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_EMPLOYEE_ID"
        ],
        "NEX_P8_S112_PASSWORD": node_env[
            "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_PASSWORD"
        ],
    }
    completed = subprocess.run(
        ["node", str(NODE_SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"status": "FAIL", "failure_code": "node_output_invalid"}
    return value if isinstance(value, dict) else {"status": "FAIL"}


def _database_identities(**engines: Any) -> dict[str, list[str]]:
    identities = {}
    for name, engine in engines.items():
        with engine.connect() as connection:
            identities[name.removesuffix("_engine")] = list(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            )
    return identities


def _domain_counts(
    *,
    ae_engine: Any,
    wc_engine: Any,
    eos_engine: Any,
    tenant_id: str,
    request_ids: Sequence[str],
) -> dict[str, int]:
    with ae_engine.connect() as connection:
        ae_count = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM ae_prompt_render_events "
                    "WHERE request_id IN (:first, :second)"
                ),
                {"first": request_ids[0], "second": request_ids[1]},
            ).scalar_one()
        )
    with wc_engine.connect() as connection:
        wc_count = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM wc_approval_work_item "
                    "WHERE tenant_id = :tenant"
                ),
                {"tenant": tenant_id},
            ).scalar_one()
        )
    with eos_engine.connect() as connection:
        project_members = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM eos_project_member "
                    "WHERE tenant_id = :tenant"
                ),
                {"tenant": tenant_id},
            ).scalar_one()
        )
    return {
        "ae_prompt_render_events": ae_count,
        "wc_approval_work_items": wc_count,
        "eos_project_members": project_members,
    }


def _cleanup_ae(engine: Any, request_ids: Sequence[str]) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM ae_prompt_render_events "
                "WHERE request_id IN (:first, :second)"
            ),
            {"first": request_ids[0], "second": request_ids[1]},
        )


def _cleanup_wc(engine: Any, tenant_id: str) -> None:
    with engine.begin() as connection:
        for table in (
            "wc_approval_outbox",
            "wc_approval_decision",
            "wc_approval_work_item",
        ):
            connection.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tenant"),
                {"tenant": tenant_id},
            )


def _cleanup_eos(engine: Any, tenant_id: str) -> None:
    with engine.begin() as connection:
        for table in (
            EOS_OUTBOX_TABLE,
            EOS_IDEMPOTENCY_TABLE,
            EOS_BUSINESS_OPERATION_TABLE,
            EOS_PROJECT_MEMBER_TABLE,
            EOS_PROJECT_TABLE,
            EOS_NVT_PROJECT_TABLE,
        ):
            connection.execute(table.delete().where(table.c.tenant_id == tenant_id))


def _cleanup_oa(engine: Any, tenant_id: str) -> None:
    with engine.begin() as connection:
        for table in (
            "oa_user_sessions",
            "oa_local_credentials",
            "oa_tenant_memberships",
            "oa_subjects",
            "oa_tenants",
        ):
            connection.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tenant"),
                {"tenant": tenant_id},
            )


def _residue_count(
    *,
    oa_engine: Any,
    ae_engine: Any,
    wc_engine: Any,
    eos_engine: Any,
    tenant_id: str,
    request_ids: Sequence[str],
) -> int:
    total = 0
    with oa_engine.connect() as connection:
        for table in (
            "oa_user_sessions",
            "oa_local_credentials",
            "oa_tenant_memberships",
            "oa_subjects",
            "oa_tenants",
        ):
            total += int(
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant"),
                    {"tenant": tenant_id},
                ).scalar_one()
            )
    with ae_engine.connect() as connection:
        total += int(
            connection.execute(
                text(
                    "SELECT count(*) FROM ae_prompt_render_events "
                    "WHERE request_id IN (:first, :second)"
                ),
                {"first": request_ids[0], "second": request_ids[1]},
            ).scalar_one()
        )
    with wc_engine.connect() as connection:
        for table in (
            "wc_approval_outbox",
            "wc_approval_decision",
            "wc_approval_work_item",
        ):
            total += int(
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant"),
                    {"tenant": tenant_id},
                ).scalar_one()
            )
    with eos_engine.connect() as connection:
        for table in (
            EOS_OUTBOX_TABLE,
            EOS_IDEMPOTENCY_TABLE,
            EOS_BUSINESS_OPERATION_TABLE,
            EOS_PROJECT_MEMBER_TABLE,
            EOS_PROJECT_TABLE,
            EOS_NVT_PROJECT_TABLE,
        ):
            total += int(
                connection.execute(
                    text("SELECT count(*) FROM " + table.name + " WHERE tenant_id = :tenant"),
                    {"tenant": tenant_id},
                ).scalar_one()
            )
    return total


def _require_database_target(
    value: str, *, role: str, database: str, label: str
) -> None:
    parsed = urlsplit(value)
    if (
        not value
        or unquote(parsed.username or "") != role
        or unquote(parsed.path.lstrip("/")) != database
        or parsed.hostname not in {"127.0.0.1", "localhost"}
    ):
        raise P8S112AcceptanceError(f"{label} must target protected local test DB")


def _service_token(service_id: str, audience: str, *scopes: str) -> str:
    return issue_mock_service_token(
        service_id=service_id,
        audience=audience,
        scopes=[DEFAULT_SERVICE_SCOPE, *scopes],
    ).access_token


def _assert_redacted(evidence: Mapping[str, Any], env: Mapping[str, str]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)
    for key in PROTECTED_ENV_KEYS:
        value = env.get(key)
        if value and len(value) >= 8 and value in serialized:
            raise P8S112AcceptanceError(f"protected value leaked: {key}")


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks", {})
    return (
        f"p8_s112_protected_acceptance={str(evidence.get('status')).lower()} "
        f"postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"provider={str(bool(evidence.get('actual_remote_provider'))).lower()} "
        f"playwright={str(bool(evidence.get('actual_playwright'))).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run P8-S112 protected acceptance.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p8_s112_nvt_membership_acceptance(execute=args.execute)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
