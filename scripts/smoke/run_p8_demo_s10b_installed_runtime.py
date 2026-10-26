#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services/_shared",
    ROOT / "services/nex-ae-api",
    ROOT / "services/nex-eos",
    ROOT / "services/nex-oa",
    ROOT / "services/nex-wc",
    ROOT / "scripts/db",
    ROOT / "scripts/deployment",
    ROOT / "scripts/smoke",
):
    sys.path.insert(0, str(path))

import run_ae_web_credential_login_playwright_postgres_smoke as browser_runtime
import run_p8_s65_golden_a_approval_journey as p8_s65
import run_p8_s66_golden_a_eos_commit_journey as p8_s66
from nex_ae_api.agent_context import SqlAlchemyAgentContextRepository
from nex_ae_api.agent_execution import (
    AgentExecutionAdmissionService,
    SqlAlchemyAgentExecutionRepository,
)
from nex_ae_api.agent_identity import SqlAlchemyAgentIdentityRegistry
from nex_ae_api.agent_plans import SqlAlchemyAgentPlanRepository
from nex_ae_api.approval_decision_event_api import (
    SqlAlchemyNslApprovalDecisionAdmission,
    register_approval_decision_event_routes,
)
from nex_ae_api.executable_plans import SqlAlchemyExecutablePlanRepository
from nex_ae_api.golden_a_approval_journey import GoldenAPlanningJourneyService
from nex_ae_api.golden_a_planning import GOLDEN_A_CAPABILITY_ID
from nex_ae_api.intent_candidate_generation import LiveIntentCandidateService
from nex_ae_api.mo_generation_client import (
    AeMoGenerationReadiness,
    AeMoGenerationResult,
)
from nex_ae_api.multi_step_engine import (
    SqlAlchemyMultiStepEngine,
    StepExecutionContext,
    _load_step,
)
from nex_ae_api.nsl_approval_events import SqlAlchemyNslApprovalEventService
from nex_ae_api.p8_demo_runtime_composition import (
    build_installed_p8_runtime_composition,
)
from nex_ae_api.plan_candidate_generation import LivePlanCandidateService
from nex_ae_api.plan_validation import SqlAlchemyPlanValidationRepository
from nex_ae_api.planning_capabilities import SqlAlchemyCapabilitySnapshotRepository
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_ae_api.semantic_candidates import (
    SemanticCalibrationPolicy,
    SemanticCalibrationRegistry,
)
from nex_ae_api.work_intent import SqlAlchemyWorkIntentRepository
from nex_eos import (
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosOrganizationRepository,
    SqlAlchemyEosProjectMembershipRepository,
    SqlAlchemyEosProjectRepository,
    create_eos_app,
)
from nex_oa.memberships import SqlAlchemyOaTenantMembershipRegistry
from nex_oa.subjects import SqlAlchemyOaSubjectRegistry
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    BoundedJwksCache,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
    WorkerHeartbeatEmitter,
    build_service_app,
    load_env_file,
)
from nex_runtime.demo_process_runtime import (
    DemoProcessDatabaseResource,
    DemoProcessRuntimeConfig,
)
from nex_runtime.semantic_hashes import canonical_json, sha256_text
from nex_runtime.worker_heartbeats import SqlAlchemyWorkerHeartbeatStore
from nex_wc.approval_api import register_approval_routes
from nex_wc.approval_event_delivery import (
    HttpAeApprovalEventClient,
    SqlAlchemyApprovalEventDeliveryStore,
    deliver_pending_approval_events,
)
from nex_wc.approvals import (
    ApprovalDecisionAuthorizer,
    ApprovalDecisionService,
    ApprovalDetailService,
    ApprovalInboxService,
    ApprovalWorkItemService,
    SqlAlchemyApprovalWorkItemRepository,
)
from nex_wc.coordination_clients import HttpAuthorizationSource
from run_migrations import run_service_migrations
from run_p8_demo_tenant_fixture import load_demo_fixture

SCHEMA_VERSION = "p8_demo_s10b_installed_runtime.v1"
SMOKE_ENV = "NEX_P8_DEMO_S10B_LIVE"
DEFAULT_REPORT = ROOT / "reports/deployment/p8-demo-s10b-installed-runtime.json"
DATABASES = {
    "nex-ae-api": (
        "NEX_AE_TEST_DATABASE_URL",
        "nex_ae_user",
        "nex_ae_test",
    ),
    "nex-wc": ("NEX_WC_TEST_DATABASE_URL", "nex_wc_user", "nex_wc_test"),
    "nex-eos": (
        "NEX_EOS_TEST_DATABASE_URL",
        "nex_eos_user",
        "nex_eos_test",
    ),
    "nex-oa": ("NEX_OA_TEST_DATABASE_URL", "nex_oa_user", "nex_oa_test"),
}


class P8DemoS10BSmokeError(RuntimeError):
    pass


class _SignedAuthority:
    def __init__(self) -> None:
        self.now_epoch = int(time())
        self.key_ref = "memory://p8-demo-s10b-oa-key"
        self.key_id = "p8-demo-s10b-key"
        self.signer = InMemoryOaRsaSigningProvider()
        self.signer.generate_key(self.key_ref)
        self.jwks = {
            "issuer": "urn:nex-platform:oa",
            "keys": [self.signer.public_jwk(self.key_ref, key_id=self.key_id)],
        }

    def token(self, service_id: str, audience: str) -> str:
        now = self.now_epoch
        return encode_signed_jwt(
            headers={"alg": "RS256", "typ": "at+jwt", "kid": self.key_id},
            claims={
                "iss": "urn:nex-platform:oa",
                "sub": f"service:{service_id}",
                "aud": audience,
                "iat": now,
                "nbf": now,
                "exp": now + 300,
                "jti": f"sat-p8-demo-s10b-{uuid4().hex}",
                "token_use": "service_access",
                "scope": f"authorization:read {DEFAULT_SERVICE_SCOPE}",
                "service_id": service_id,
                "credential_id": f"p8-demo-s10b-{service_id}",
                "credential_revision": 1,
            },
            private_key_ref=self.key_ref,
            signing_provider=self.signer,
        )

    def admission(self, audience: str) -> ServiceTokenAdmissionRuntime:
        verifier = SignedServiceTokenVerifier(
            BoundedJwksCache(StaticJwksSource(self.jwks), clock=lambda: self.now_epoch),
            clock=lambda: self.now_epoch,
        )
        return ServiceTokenAdmissionRuntime(
            expected_audience=audience,
            rollout_profile="SIGNED_ONLY",
            signed_verifier=verifier,
            introspector=_VerifierIntrospector(verifier, self.now_epoch),
            clock=lambda: self.now_epoch,
        )


class _VerifierIntrospector:
    def __init__(self, verifier: SignedServiceTokenVerifier, now_epoch: int) -> None:
        self._verifier = verifier
        self._now_epoch = now_epoch

    def introspect(
        self,
        token: str,
        *,
        expected_audience: str,
        required_scopes: Sequence[str],
    ) -> dict[str, Any]:
        claims = self._verifier.verify(
            token,
            expected_audience=expected_audience,
            required_scopes=required_scopes,
            now_epoch=self._now_epoch,
        )
        return {
            "introspection_schema_version": "oa_token_introspection.v1",
            "active": True,
            "token_use": claims.token_use,
            "sub": claims.subject,
            "aud": claims.audience,
            "scope": " ".join(claims.scopes),
            "service_id": claims.service_id,
            "credential_id": claims.credential_id,
            "credential_revision": claims.credential_revision,
            "iat": claims.issued_at,
            "exp": claims.expires_at,
            "token_id_digest": claims.token_id_digest,
        }


class _CandidateClient:
    def __init__(self, fixture: Mapping[str, Any], now: str) -> None:
        self._fixture = fixture
        self._now = now

    def check_required_mode_readiness(self, **_values: Any) -> AeMoGenerationReadiness:
        return AeMoGenerationReadiness(
            provider_mode="live",
            readiness_status="READY",
            model_profile="p8-demo-s10b-deterministic",
            model_ref="installed-composition-fixture",
            deployment_id="p8-demo-s10b",
            route_id="p8-demo-s10b",
            checked_at=self._now,
            expires_at="2099-12-31T23:59:59Z",
            cache_status="FRESH",
            source="protected_fixture",
        )

    def generate_candidate(self, **values: Any) -> AeMoGenerationResult:
        stage = values["semantic_stage"]
        output = canonical_json(
            _intent_candidate(self._fixture) if stage == "INTENT" else _plan_candidate()
        )
        return AeMoGenerationResult(
            mo_generation_id=f"p8-demo-s10b-{stage.lower()}-{uuid4().hex}",
            model_profile="p8-demo-s10b-deterministic",
            model_ref="installed-composition-fixture",
            deployment_id="p8-demo-s10b",
            provider_type="deterministic-protected-smoke",
            output_text=output,
            provider_output_sha256=sha256_text(output),
            provider_output_size_bytes=len(output.encode("utf-8")),
            finish_reason="STOP",
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            request_id=values["request_id"],
            trace_id=values["trace_id"],
            route_id="p8-demo-s10b",
            provider_request_id=f"provider-{uuid4().hex}",
            queue_ms=0,
            provider_ms=1,
            total_ms=1,
            created_at=self._now,
            updated_at=self._now,
        )


def run_p8_demo_s10b_installed_runtime(
    environ: Mapping[str, str], *, execute: bool
) -> dict[str, Any]:
    if not execute or environ.get(SMOKE_ENV) != "1":
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"--execute and {SMOKE_ENV}=1 are required",
        }
    urls = _database_urls(environ)
    servers: list[Any] = []
    resources: list[Any] = []
    cleanup: dict[str, int] = {}
    try:
        migrations = {
            service: run_service_migrations(
                service, database_url=urls[service], profile="test"
            )
            for service in DATABASES
        }
        _fixture_document, fixture = load_demo_fixture()
        tenant_id = "VO00"
        authority = _SignedAuthority()
        tokens = {
            "ae_to_oa": authority.token("nex-ae-api", "nex-oa"),
            "ae_to_wc": authority.token("nex-ae-api", "nex-wc"),
            "ae_to_eos": authority.token("nex-ae-api", "nex-eos"),
            "wc_to_oa": authority.token("nex-wc", "nex-oa"),
            "wc_to_ae": authority.token("nex-wc", "nex-ae-api"),
            "eos_to_oa": authority.token("nex-eos", "nex-oa"),
        }
        engines = {
            service: create_engine(url, poolclass=NullPool)
            for service, url in urls.items()
        }
        resources.extend(engines.values())
        factories = {
            service: sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
            for service, engine in engines.items()
        }
        _cleanup_dynamic_rows(engines, tenant_id=tenant_id)
        _ensure_seed_fixture(engines, factories, fixture)

        oa_app = p8_s65._build_oa_app(urls["nex-oa"])
        oa_app.state.service_token_admission = authority.admission("nex-oa")
        oa_server = browser_runtime.start_api_server(
            oa_app, browser_runtime.find_free_port()
        )
        servers.append(oa_server)

        wc_app, wc_repository, wc_decisions = _build_wc_app(
            factories["nex-wc"],
            oa_base_url=oa_server.url,
            wc_to_oa_token=tokens["wc_to_oa"],
            admission=authority.admission("nex-wc"),
        )
        wc_server = browser_runtime.start_api_server(
            wc_app, browser_runtime.find_free_port()
        )
        servers.append(wc_server)

        eos_app = create_eos_app(
            environ={
                "NEX_PROFILE": "test",
                "NEX_EOS_DATABASE_URL": urls["nex-eos"],
                "NEX_OA_BASE_URL": oa_server.url,
                "NEX_EOS_TO_OA_SERVICE_TOKEN": tokens["eos_to_oa"],
                "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
            }
        )
        eos_app.state.service_token_admission = authority.admission("nex-eos")
        eos_server = browser_runtime.start_api_server(
            eos_app, browser_runtime.find_free_port()
        )
        servers.append(eos_server)
        resources.append(eos_app.state.eos_database_runtime)

        jobs = SqlAlchemyRuntimeJobQueue(factories["nex-ae-api"])
        ae_app = build_service_app(
            SERVICE_SPECS["nex-ae-api"],
            service_token_admission=authority.admission("nex-ae-api"),
        )
        register_approval_decision_event_routes(
            ae_app,
            admission=SqlAlchemyNslApprovalDecisionAdmission(
                factories["nex-ae-api"],
                event_service=SqlAlchemyNslApprovalEventService(
                    factories["nex-ae-api"], runtime_jobs=jobs
                ),
            ),
        )
        ae_server = browser_runtime.start_api_server(
            ae_app, browser_runtime.find_free_port()
        )
        servers.append(ae_server)

        with TemporaryDirectory(prefix="p8-demo-s10b-state-") as state_root:
            execution = _persist_compiled_execution(
                factories["nex-ae-api"], fixture=fixture
            )
            engine = SqlAlchemyMultiStepEngine(factories["nex-ae-api"], jobs)
            scheduled = engine.schedule_next(
                tenant_id=tenant_id,
                execution_id=execution["agent_execution_id"],
                now=execution["created_at"],
            )
            if scheduled is None:
                raise P8DemoS10BSmokeError("COMPILED execution was not scheduled")
            resource = _ae_worker_resource(
                engines["nex-ae-api"], factories["nex-ae-api"]
            )
            with _temporary_environ(
                {
                    "NEX_WC_BASE_URL": wc_server.url,
                    "NEX_AE_TO_WC_SERVICE_TOKEN": tokens["ae_to_wc"],
                }
            ):
                composition = build_installed_p8_runtime_composition(
                    resource,
                    {
                        "NEX_AE_AGENT_WORKER_MODE": "enabled",
                        "NEX_AE_AGENT_WORKER_ID": "ae-demo-s10b-worker",
                        "NEX_AE_AGENT_WORKER_EXECUTOR_KINDS": "LOCAL_SKILL",
                        "NEX_AE_AGENT_WORKER_BACKEND_PROFILES": ("NSL_V02_IN_PROCESS"),
                        "NEX_AE_DEMO_NSL_STATE_ROOT": state_root,
                        "NEX_OA_BASE_URL": oa_server.url,
                        "NEX_EOS_BASE_URL": eos_server.url,
                        "NEX_AE_TO_OA_SERVICE_TOKEN": tokens["ae_to_oa"],
                        "NEX_AE_TO_EOS_SERVICE_TOKEN": tokens["ae_to_eos"],
                    },
                )
                initial_failure: list[str] = []
                original_initial = composition.controlled_skill.initial

                def capture_initial_failure(*args: Any, **kwargs: Any) -> Any:
                    try:
                        return original_initial(*args, **kwargs)
                    except Exception as exc:
                        initial_failure.extend(_exception_chain(exc))
                        raise

                composition.controlled_skill.initial = capture_initial_failure
                prefix_cycle = composition.run_cycle()
                prefix_projection = _result_projection(
                    engines,
                    tenant_id=tenant_id,
                    execution_id=execution["agent_execution_id"],
                    state_root=Path(state_root),
                )
                pending = list(
                    wc_repository.list_pending_work_items(tenant_id=tenant_id, limit=10)
                )
                if len(pending) != 1:
                    raise P8DemoS10BSmokeError(
                        "installed prefix did not publish one WC approval item: "
                        + json.dumps(
                            {
                                "cycle": prefix_cycle,
                                "jobs": _runtime_job_diagnostics(
                                    engines["nex-ae-api"], tenant_id
                                ),
                                "cause": initial_failure
                                or _controlled_failure_detail(
                                    composition,
                                    factories["nex-ae-api"],
                                    scheduled,
                                ),
                            },
                            sort_keys=True,
                        )
                    )
                approver = fixture["approval_target"]["approver_subject_id"]
                decision = wc_decisions.decide(
                    tenant_id=tenant_id,
                    approval_work_item_id=pending[0]["approval_work_item_id"],
                    decision="APPROVE",
                    decided_by=approver,
                )
                delivery = deliver_pending_approval_events(
                    store=SqlAlchemyApprovalEventDeliveryStore(factories["nex-wc"]),
                    client=HttpAeApprovalEventClient(
                        base_url=ae_server.url,
                        service_token=tokens["wc_to_ae"],
                    ),
                )
                resume_cycle = composition.run_cycle()

            projection = _result_projection(
                engines,
                tenant_id=tenant_id,
                execution_id=execution["agent_execution_id"],
                state_root=Path(state_root),
            )
        admissions = {
            "oa": oa_app.state.service_token_admission.public_snapshot(),
            "wc": wc_app.state.service_token_admission.public_snapshot(),
            "ae": ae_app.state.service_token_admission.public_snapshot(),
            "eos": eos_app.state.service_token_admission.public_snapshot(),
        }
        identities = _database_identities(engines)
        checks = {
            "migrations_current": all(
                len(item.planned) == len(item.applied) + len(item.skipped)
                for item in migrations.values()
            ),
            "actual_database_identities": all(
                identities[service] == [DATABASES[service][2], DATABASES[service][1]]
                for service in DATABASES
            ),
            "compiled_scheduled": scheduled["job_type"] == "START_EXECUTION",
            "prefix_waiting": (
                prefix_cycle["execution_count"] == 1
                and prefix_projection["execution_state"] == "WAITING_APPROVAL"
                and prefix_projection["execution_phase"] == "STEP_EXECUTION"
                and prefix_projection["step_state"] == "WAITING"
                and prefix_projection["approval_request_count"] == 1
                and prefix_projection["checkpoint_count"] == 1
            ),
            "approval_delivered": (
                decision["decision"]["decision"] == "APPROVE"
                and delivery == {"pending_count": 1, "delivered_count": 1}
            ),
            "resume_controlled_write_completed": (
                resume_cycle["execution_count"] == 1
                and projection["execution_state"] == "RUNNING"
                and projection["execution_phase"] == "RESULT_VERIFY"
                and projection["step_state"] == "SUCCEEDED"
            ),
            "eos_committed_once": (
                projection["voucher_count"] == 1
                and projection["voucher_line_count"] == 2
                and projection["business_operation_count"] == 1
            ),
            "write_evidence_durable": (
                projection["idempotency_evidence_count"] == 1
                and projection["write_evidence_count"] >= 1
            ),
            "signed_only_cross_service": all(
                snapshot["rollout_profile"] == "SIGNED_ONLY"
                and snapshot["admission_counts"]["accepted_mock"] == 0
                for snapshot in admissions.values()
            ),
            "signed_tokens_observed": all(
                admissions[name]["admission_counts"]["accepted_signed"] >= 1
                for name in ("oa", "wc", "ae", "eos")
            ),
        }
        result = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-DEMO-S10B",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "actual_postgres": True,
            "signed_service_tokens": True,
            "composition_mode": "EXISTING_COMPONENT_COMPOSITION",
            "new_business_behavior_added": False,
            "database_identities": identities,
            "prefix_cycle": prefix_cycle,
            "prefix_projection": prefix_projection,
            "resume_cycle": resume_cycle,
            "projection": projection,
            "admission": {
                name: {
                    "rollout_profile": value["rollout_profile"],
                    "admission_counts": value["admission_counts"],
                }
                for name, value in admissions.items()
            },
            "checks": checks,
            "checks_passed": sum(bool(value) for value in checks.values()),
            "checks_total": len(checks),
            "secret_included": False,
        }
        return result
    finally:
        for server in reversed(servers):
            server.stop()
        engine_map = locals().get("engines")
        if isinstance(engine_map, Mapping):
            try:
                cleanup = _cleanup_dynamic_rows(engine_map, tenant_id="VO00")
            finally:
                for engine in engine_map.values():
                    engine.dispose()
        for resource in resources:
            dispose = getattr(resource, "dispose", None)
            if callable(dispose):
                dispose()


def _build_wc_app(
    factory: sessionmaker[Session],
    *,
    oa_base_url: str,
    wc_to_oa_token: str,
    admission: ServiceTokenAdmissionRuntime,
) -> tuple[Any, SqlAlchemyApprovalWorkItemRepository, ApprovalDecisionService]:
    app = build_service_app(SERVICE_SPECS["nex-wc"], service_token_admission=admission)
    repository = SqlAlchemyApprovalWorkItemRepository(factory)
    authorization = HttpAuthorizationSource(
        base_url=oa_base_url,
        service_token=wc_to_oa_token,
    )
    inbox = ApprovalInboxService(repository, authorization_source=authorization)
    work_items = ApprovalWorkItemService(repository)
    detail = ApprovalDetailService(repository, authorization_source=authorization)
    decisions = ApprovalDecisionService(
        repository,
        authorizer=ApprovalDecisionAuthorizer(authorization),
    )
    register_approval_routes(
        app,
        inbox_service=inbox,
        work_item_service=work_items,
        detail_service=detail,
        decision_service=decisions,
    )
    return app, repository, decisions


def _persist_compiled_execution(
    factory: sessionmaker[Session], *, fixture: Mapping[str, Any]
) -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0)
    now_text = now.isoformat().replace("+00:00", "Z")
    tenant_id = "VO00"
    requester = fixture["scenario"]["requester_subject_id"]
    workspace_id, conversation_id, interaction_id = (str(uuid4()) for _ in range(3))
    p8_s65._seed_workspace_conversation(
        factory,
        tenant_id=tenant_id,
        principal_id=requester,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        trace_id=uuid4().hex,
        now=now_text,
    )
    execution = (
        AgentExecutionAdmissionService(
            identities=SqlAlchemyAgentIdentityRegistry(factory),
            executions=SqlAlchemyAgentExecutionRepository(factory),
            mode="required",
            clock=lambda: now,
        )
        .admit_prompt(
            tenant_id=tenant_id,
            principal_id=requester,
            profile_ref="urn:nex:agent-profile:ia:p8-demo-s10b:v1",
            trigger_id=interaction_id,
            interaction_id=interaction_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            correlation_id=f"p8-demo-s10b:{uuid4().hex}",
        )
        .execution
    )
    if execution is None:
        raise P8DemoS10BSmokeError("IA execution admission failed")
    client = _CandidateClient(fixture, now_text)
    policies = SemanticCalibrationRegistry(
        tuple(
            SemanticCalibrationPolicy(
                semantic_stage=stage,
                policy_ref=f"semantic-admission://{stage.lower()}/p8-demo-s10b/v1",
                policy_version="p8-demo-s10b-v1",
                model_profile="p8-demo-s10b-deterministic",
                model_ref="installed-composition-fixture",
                minimum_confidence=0.7,
                golden_evidence_ref=f"smoke://p8-demo-s10b/{stage.lower()}/golden",
                adversarial_evidence_ref=(
                    f"smoke://p8-demo-s10b/{stage.lower()}/adversarial"
                ),
            )
            for stage in ("INTENT", "PLAN")
        )
    )
    from nex_ae_api.prompts import seed_ae_prompt_registry
    from nex_runtime.prompts import PromptRegistryStore

    prompts = PromptRegistryStore()
    seed_ae_prompt_registry(prompts)
    planning = GoldenAPlanningJourneyService(
        intent_service=LiveIntentCandidateService(client, prompts, policies),
        plan_service=LivePlanCandidateService(client, prompts, policies),
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
        received_at=now_text,
        request_id=f"p8-demo-s10b-{uuid4().hex}",
        trace_id=uuid4().hex,
        authority_ref="oa-authz:p8-demo-s10b",
    )
    _persist_planning(factory, tenant_id, execution, planning, now_text)
    return {
        **execution,
        "created_at": now_text,
        "workspace_id": workspace_id,
    }


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


def _ae_worker_resource(
    engine: Any, factory: sessionmaker[Session]
) -> DemoProcessDatabaseResource:
    config = DemoProcessRuntimeConfig(
        process_id="nex-ae-agent-runtime-worker",
        service_id="nex-ae-api",
        worker_id="ae-demo-s10b-worker",
        worker_type="ae.agent_runtime.worker",
        database_environment="NEX_AE_DATABASE_URL",
    )
    return DemoProcessDatabaseResource(
        config=config,
        engine=engine,
        sessions=factory,
        heartbeat=WorkerHeartbeatEmitter(
            service_id="nex-ae-api",
            worker_id=config.worker_id,
            worker_type=config.worker_type,
            store=SqlAlchemyWorkerHeartbeatStore(factory),
        ),
    )


def _intent_candidate(fixture: Mapping[str, Any]) -> dict[str, Any]:
    scenario = fixture["scenario"]
    return {
        "schema_version": "p65.intent_candidate.v1",
        "intent_label": GOLDEN_A_CAPABILITY_ID,
        "suggested_execution_mode": "GENERAL_ANSWER",
        "entity_selectors": [
            {
                "selector_id": "E1",
                "selector_type": "QUERY_TERM",
                "value": fixture["projects"]["child"]["project_code"],
                "confidence": 0.99,
            }
        ],
        "parameter_candidates": [
            {"name": name, "value": scenario[name], "confidence": 0.99}
            for name in (
                "amount",
                "currency",
                "transaction_date",
                "voucher_type",
                "economic_category",
                "settlement_method",
            )
        ],
        "clarification": {"required": False, "reasons": [], "questions": []},
        "confidence": 0.99,
    }


def _plan_candidate() -> dict[str, Any]:
    return {
        "schema_version": "p65.plan_candidate.v1",
        "suggested_plan_kind": "DIRECT",
        "goal": (
            "Create a governed voucher draft after deterministic business binding."
        ),
        "logical_steps": [
            {
                "step_id": "S1",
                "step_type": "LOCAL_CAPABILITY",
                "title": "Create governed voucher draft",
                "objective": "Run the exact admitted WRITE Skill.",
                "depends_on": [],
                "capability_hint": GOLDEN_A_CAPABILITY_ID,
                "completion_criteria": ["A governed voucher draft is produced."],
            }
        ],
        "completion_mapping": [{"criterion_id": "C1", "terminal_step_refs": ["S1"]}],
        "confidence": 0.99,
    }


def _ensure_seed_fixture(
    engines: Mapping[str, Any],
    factories: Mapping[str, sessionmaker[Session]],
    fixture: Mapping[str, Any],
) -> None:
    expected = {
        "nex-oa": ("oa_tenant_memberships", 1),
        "nex-eos": ("eos_project", 2),
    }
    observed: dict[str, int] = {}
    for service, (table, _minimum) in expected.items():
        with engines[service].connect() as connection:
            observed[service] = int(
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = 'VO00'")
                ).scalar_one()
            )
    if all(count == 0 for count in observed.values()):
        p8_s66.seed_golden_a_fixture(
            fixture,
            memberships=SqlAlchemyOaTenantMembershipRegistry(
                factories["nex-oa"],
                subject_registry=SqlAlchemyOaSubjectRegistry(factories["nex-oa"]),
            ),
            organization=SqlAlchemyEosOrganizationRepository(factories["nex-eos"]),
            projects=SqlAlchemyEosProjectRepository(factories["nex-eos"]),
            accounts=SqlAlchemyEosAccountRepository(factories["nex-eos"]),
            expected_tenant_id="VO00",
        )
        p8_s66._seed_demo_requester_access(
            fixture,
            oa_engine=engines["nex-oa"],
            oa_factory=factories["nex-oa"],
            eos_memberships=SqlAlchemyEosProjectMembershipRepository(
                factories["nex-eos"]
            ),
        )
    elif any(
        observed[service] < minimum for service, (_table, minimum) in expected.items()
    ):
        raise P8DemoS10BSmokeError("VO00 Demo tenant fixture is partially seeded")
    expected_hash = fixture["admission"]["skill_semantic_hash"]
    if not isinstance(expected_hash, str) or not expected_hash.startswith("sha256:"):
        raise P8DemoS10BSmokeError("VO00 Skill admission fixture is invalid")


def _result_projection(
    engines: Mapping[str, Any],
    *,
    tenant_id: str,
    execution_id: str,
    state_root: Path,
) -> dict[str, Any]:
    with engines["nex-ae-api"].connect() as connection:
        execution_state, execution_phase = connection.execute(
            text(
                "SELECT state, phase FROM ae_agent_execution "
                "WHERE tenant_id=:tenant AND agent_execution_id=:execution"
            ),
            {"tenant": tenant_id, "execution": execution_id},
        ).one()
        step_state = connection.execute(
            text(
                "SELECT state FROM ae_executable_step "
                "WHERE tenant_id=:tenant AND agent_execution_id=:execution"
            ),
            {"tenant": tenant_id, "execution": execution_id},
        ).scalar_one()
        counts = dict(
            connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM ae_nsl_approval_request WHERE tenant_id=:tenant) approval_request_count, "
                    "(SELECT count(*) FROM ae_nsl_idem_evidence WHERE tenant_id=:tenant) idempotency_evidence_count, "
                    "(SELECT count(*) FROM ae_nsl_write_evidence WHERE tenant_id=:tenant) write_evidence_count"
                ),
                {"tenant": tenant_id},
            )
            .mappings()
            .one()
        )
    with engines["nex-eos"].connect() as connection:
        eos = dict(
            connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM eos_voucher_draft WHERE tenant_id=:tenant) voucher_count, "
                    "(SELECT count(*) FROM eos_voucher_draft_line WHERE tenant_id=:tenant) voucher_line_count, "
                    "(SELECT count(*) FROM eos_business_operation WHERE tenant_id=:tenant) business_operation_count"
                ),
                {"tenant": tenant_id},
            )
            .mappings()
            .one()
        )
    return {
        "execution_state": execution_state,
        "execution_phase": execution_phase,
        "step_state": step_state,
        **{name: int(value) for name, value in counts.items()},
        **{name: int(value) for name, value in eos.items()},
        "checkpoint_count": len(tuple(state_root.rglob("controlled-prefix.nsc"))),
    }


def _cleanup_dynamic_rows(
    engines: Mapping[str, Any], *, tenant_id: str
) -> dict[str, int]:
    deleted: dict[str, int] = {}
    ae_tables = (
        "ae_runtime_job_attempt",
        "ae_external_event_inbox",
        "ae_approval_evidence",
        "ae_wait_registration",
        "ae_nsl_write_evidence",
        "ae_nsl_idem_evidence",
        "ae_nsl_approval_request",
        "ae_nsl_step_execution",
        "ae_nsl_artifact",
        "ae_step_result",
        "ae_rt_job_issue",
        "ae_runtime_job",
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
    with engines["nex-ae-api"].begin() as connection:
        for table in ae_tables:
            deleted[f"ae:{table}"] = int(
                connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id=:tenant"),
                    {"tenant": tenant_id},
                ).rowcount
                or 0
            )
        connection.execute(
            text("DELETE FROM ae_rt_dispatch_lease WHERE queue_name='ae-runtime'")
        )
        connection.execute(
            text(
                "DELETE FROM service_worker_heartbeats "
                "WHERE service_id='nex-ae-api' AND worker_id='ae-demo-s10b-worker'"
            )
        )
        connection.execute(
            text(
                "DELETE FROM ae_workspace_activities WHERE workspace_id NOT IN "
                "(SELECT workspace_id FROM ae_workspaces)"
            )
        )
        connection.execute(
            text("DELETE FROM ae_workspaces WHERE tenant_id=:tenant"),
            {"tenant": tenant_id},
        )
    with engines["nex-wc"].begin() as connection:
        for table in (
            "wc_approval_outbox",
            "wc_approval_decision",
            "wc_approval_work_item",
        ):
            deleted[f"wc:{table}"] = int(
                connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id=:tenant"),
                    {"tenant": tenant_id},
                ).rowcount
                or 0
            )
    p8_s66._cleanup_eos_mutations(engines["nex-eos"], tenant_id)
    return deleted


def _database_urls(environ: Mapping[str, str]) -> dict[str, str]:
    result = {}
    from urllib.parse import unquote, urlsplit

    for service, (name, role, database) in DATABASES.items():
        value = str(environ.get(name) or "")
        parsed = urlsplit(value)
        if (
            unquote(parsed.username or "") != role
            or unquote(parsed.path.lstrip("/")) != database
        ):
            raise P8DemoS10BSmokeError(f"{name} must target {role}@.../{database}")
        result[service] = value
    return result


def _database_identities(engines: Mapping[str, Any]) -> dict[str, list[str]]:
    result = {}
    for service, engine in engines.items():
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
        result[service] = [str(row[0]), str(row[1])]
    return result


def _runtime_job_diagnostics(engine: Any, tenant_id: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT j.job_type, j.state, j.attempt_no, a.outcome, a.error_ref "
                "FROM ae_runtime_job j LEFT JOIN ae_runtime_job_attempt a "
                "ON a.tenant_id=j.tenant_id AND a.runtime_job_id=j.runtime_job_id "
                "AND a.attempt_no=j.attempt_no "
                "WHERE j.tenant_id=:tenant ORDER BY j.created_at"
            ),
            {"tenant": tenant_id},
        ).mappings()
        return [dict(row) for row in rows]


def _controlled_failure_detail(
    composition: Any,
    factory: sessionmaker[Session],
    job: Mapping[str, Any],
) -> list[str]:
    with factory() as session:
        step = _load_step(
            session,
            str(job["tenant_id"]),
            str(job["executable_step_id"]),
            lock=False,
        )
    if step is None:
        return ["ExecutableStep unavailable"]
    try:
        composition.controlled_skill.initial(
            StepExecutionContext(
                job=dict(job),
                attempt={"attempt_no": int(job.get("attempt_no") or 1)},
                step=step,
                dependency_results=(),
                existing_result=None,
            ),
            composition.controlled_skill.dependencies,
        )
    except Exception as exc:  # noqa: BLE001 - protected diagnostic is type bounded.
        return _exception_chain(exc)
    return ["Controlled Skill replay succeeded"]


def _exception_chain(exc: BaseException) -> list[str]:
    details = []
    current: BaseException | None = exc
    while current is not None and len(details) < 5:
        details.append(f"{current.__class__.__name__}: {current}")
        current = current.__cause__
    return details


class _TemporaryEnvironment:
    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)
        self._previous: dict[str, str | None] = {}

    def __enter__(self) -> None:
        self._previous = {name: os.environ.get(name) for name in self._values}
        os.environ.update(self._values)

    def __exit__(self, *_exc: object) -> None:
        for name, value in self._previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _temporary_environ(values: Mapping[str, str]) -> _TemporaryEnvironment:
    return _TemporaryEnvironment(values)


def summary_line(value: Mapping[str, Any]) -> str:
    checks = value.get("checks") or {}
    return (
        "p8_demo_s10b_installed_runtime="
        f"{str(value.get('status', 'FAIL')).lower()} "
        f"postgres={str(bool(value.get('actual_postgres'))).lower()} "
        f"signed={str(bool(value.get('signed_service_tokens'))).lower()} "
        f"checks={sum(bool(item) for item in checks.values())}/{len(checks)}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    result = run_p8_demo_s10b_installed_runtime(os.environ, execute=args.execute)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
