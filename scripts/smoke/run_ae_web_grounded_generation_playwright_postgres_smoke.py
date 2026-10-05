#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import nex_mo.remote_provider as remote_provider  # noqa: E402
from nex_ae_api.auth_sessions import (  # noqa: E402
    build_browser_session_snapshot,
    register_auth_session_routes,
)
from nex_ae_api.chat import (  # noqa: E402
    SqlAlchemyChatInteractionStore,
    register_chat_routes,
)
from nex_ae_api.generated_response_storage import (  # noqa: E402
    LocalGeneratedResponseStorage,
)
from nex_ae_api.oa_session_client import OaUserSessionClientError  # noqa: E402
from nex_ae_api.prompt_persistence import (  # noqa: E402
    SqlAlchemyAePromptRegistryStore,
)
from nex_ae_api.prompts import seed_ae_prompt_registry  # noqa: E402
from nex_ae_api.workspace import (  # noqa: E402
    build_workspace_activity,
    build_workspace_state,
)
from nex_ae_api.workspace_persistence import (  # noqa: E402
    SqlAlchemyWorkspaceRepository,
)
from nex_cx.async_generation_worker import AsyncGenerationWorkerHandler  # noqa: E402
from nex_cx.chunking import store_chunk_set  # noqa: E402
from nex_cx.embedding_index import DEFAULT_EMBEDDING_ALIAS  # noqa: E402
from nex_cx.generation_repository import (  # noqa: E402
    SqlAlchemyGenerationRuntimeRepository,
)
from nex_cx.generation_runtime import (  # noqa: E402
    GroundedGenerationRuntime,
    SqlAlchemyGenerationAdmissionRepository,
)
from nex_cx.ingestion import (  # noqa: E402
    ContentIngestionStore,
    build_upload_registration,
    run_text_extraction_job,
)
from nex_cx.lexical_index import build_and_store_lexical_index  # noqa: E402
from nex_cx.mvp_runtime import build_cx_mvp_runtime  # noqa: E402
from nex_cx.pgvector_store import build_pgvector_cx_vector_store  # noqa: E402
from nex_cx.private_text_store import FileSystemCxPrivateTextStore  # noqa: E402
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_cx.retrieval import DEFAULT_RERANKER_ALIAS  # noqa: E402
from nex_cx.vector_index_repository import (  # noqa: E402
    SqlAlchemyVectorIndexRepository,
)
from nex_cx.worker_leases import SqlAlchemyCxWorkerLeaseStore  # noqa: E402
from nex_cx.worker_runtime import (  # noqa: E402
    CxWorkerRuntimePolicy,
    run_bounded_worker_batch,
)
from nex_mo.providers import register_mock_provider_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    OperationalEventEmitter,
    SERVICE_SPECS,
    SqlAlchemyJobQueue,
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
)
from run_ae_cx_async_generation_postgres_smoke import (  # noqa: E402
    _test_client_adapter,
)
import run_ae_web_credential_login_playwright_postgres_smoke as browser_pg  # noqa: E402
from run_ae_web_fetch_mode_postgres_smoke import (  # noqa: E402
    TestClientCxRetrievalClient,
)
from run_ae_web_playwright_readiness import (  # noqa: E402
    run_ae_web_playwright_readiness,
)
from run_cx_mvp_integration_live_postgres_smoke import (  # noqa: E402
    EXPECTED_MODELS,
    _build_cx_app,
    _cleanup as cleanup_cx_rows,
    _provider_observation,
    _storage_config,
    configuration_issues as cx_configuration_issues,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402
from run_protected_dgx_live_profile import (  # noqa: E402
    DGX_PROFILE_NAME,
    protected_dgx_vllm_profile_defaults,
    run_protected_dgx_live_profile,
)
from run_protected_live_rag_smoke import (  # noqa: E402
    InProcessLiveMoClient,
    patched_environ,
    read_provider_telemetry,
)


SCHEMA_VERSION = "ae_web_grounded_generation_playwright_postgres_smoke.v1"
NODE_SCHEMA_VERSION = "ae_web_grounded_generation_playwright_smoke.v1"
SMOKE_ENV = "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_POSTGRES_SMOKE"
PROFILE_ENV = f"{SMOKE_ENV}_PROFILE"
DEFAULT_PROFILE = "test"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
CX_DATABASE_ENV = "NEX_CX_TEST_DATABASE_URL"
AE_DATABASE = "nex_ae_test"
CX_DATABASE = "nex_cx_test"
AE_ROLE = "nex_ae_user"
CX_ROLE = "nex_cx_user"
CHROMIUM_ENV = "NEX_AE_WEB_PLAYWRIGHT_CHROMIUM_EXECUTABLE"
TIMEOUT_ENV = "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_TIMEOUT_MS"
TENANT_ID = "s109-live-tenant"
OWNER_ID = "s109-live-owner"
EMPLOYEE_ID = "s109-live-employee"
LOGIN_PASSWORD = "S109-Protected-Smoke!"
SOURCE_TEXT = (
    "S109 브라우저 기반 grounded generation 검증 문서입니다. "
    "검증 확인 문구는 ORION ONE ZERO NINE 입니다."
)
WEB_ROOT = ROOT / "apps" / "nex-ae-web"
NODE_SCRIPT = WEB_ROOT / "scripts" / "runGroundedGenerationPlaywrightSmoke.mjs"

PROTECTED_ENV_KEYS = (
    AE_DATABASE_ENV,
    CX_DATABASE_ENV,
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_API_KEY",
    CHROMIUM_ENV,
)

SmokeExecutor = Callable[..., dict[str, Any]]
EvidenceRunner = Callable[[dict[str, str]], dict[str, Any]]
JourneyHook = Callable[[dict[str, Any]], dict[str, Any]]


def run_ae_web_grounded_generation_playwright_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    preflight_runner: EvidenceRunner | None = None,
    readiness_runner: EvidenceRunner | None = None,
    executor: SmokeExecutor | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1090",
            "requirement": "S109",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
            "live_provider_required": True,
            "playwright_required": True,
        }
    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure("profile_not_allowed", f"{PROFILE_ENV} must be test.")

    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
    }
    issues = configuration_issues(effective_env)
    if issues:
        return _failure("configuration_invalid", issues)

    preflight = (preflight_runner or _run_live_preflight)(effective_env)
    if preflight.get("status") != "PASS":
        return _failure(
            "live_provider_preflight_failed",
            _source_failure_detail(preflight),
            sources={"live_provider_preflight": _source_status(preflight)},
        )
    readiness = (readiness_runner or _run_playwright_readiness)(effective_env)
    if readiness.get("status") != "PASS":
        return _failure(
            "playwright_readiness_failed",
            _source_failure_detail(readiness),
            sources={
                "live_provider_preflight": _source_status(preflight),
                "playwright_readiness": _source_status(readiness),
            },
        )

    ae_url = effective_env[AE_DATABASE_ENV]
    cx_url = effective_env[CX_DATABASE_ENV]
    try:
        ae_migration = run_service_migrations(
            "nex-ae-api", database_url=ae_url, profile=profile
        )
        cx_migration = run_service_migrations(
            "nex-cx", database_url=cx_url, profile=profile
        )
        execute = executor or _execute_live_browser_smoke
        execution = execute(
            ae_database_url=ae_url,
            cx_database_url=cx_url,
            runtime_environ=effective_env,
        )
        checks = {
            "ae_migration_current": _migration_current(ae_migration),
            "cx_migration_current": _migration_current(cx_migration),
            **dict(execution.get("checks") or {}),
        }
        failed_checks = [name for name, passed in checks.items() if not passed]
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1090",
            "requirement": "S109",
            "status": "PASS" if not failed_checks else "FAIL",
            "profile": profile,
            "actual_postgres": True,
            "live_provider_required": True,
            "playwright_required": True,
            "evidence_mode": "single_correlated_browser_request",
            "services": ["nex-ae-web", "nex-ae-api", "nex-cx", "nex-mo"],
            "databases": {
                "ae": redact_database_url(ae_url),
                "cx": redact_database_url(cx_url),
            },
            "migrations": {
                "ae": _migration_summary(ae_migration),
                "cx": _migration_summary(cx_migration),
            },
            "source_smokes": {
                "live_provider_preflight": _source_status(preflight),
                "playwright_readiness": _source_status(readiness),
            },
            **execution,
            "checks": checks,
            "failed_checks": failed_checks,
        }
        if failed_checks:
            evidence["failure_code"] = "grounded_generation_live_checks_failed"
        assert_evidence_redacted(evidence, effective_env)
        return evidence
    except (MigrationError, ValueError) as exc:
        result = _failure("configuration_invalid", _safe_exception_detail(exc))
    except Exception as exc:  # pragma: no cover - protected live evidence
        result = _failure("execution_failed", _safe_exception_detail(exc))
    assert_evidence_redacted(result, effective_env)
    return result


def configuration_issues(environ: Mapping[str, str]) -> list[dict[str, str]]:
    issues = cx_configuration_issues(environ)
    for field in (AE_DATABASE_ENV, CX_DATABASE_ENV):
        if not str(environ.get(field, "")).strip() and not any(
            item.get("field") == field for item in issues
        ):
            issues.append({"error_code": "configuration_missing", "field": field})
    targets = (
        (AE_DATABASE_ENV, AE_ROLE, AE_DATABASE),
        (CX_DATABASE_ENV, CX_ROLE, CX_DATABASE),
    )
    for field, role, database in targets:
        value = str(environ.get(field, ""))
        if value and not _target_url_allowed(value, role=role, database=database):
            issues.append(
                {
                    "error_code": "database_target_not_allowed",
                    "field": field,
                }
            )
    return issues


def _run_live_preflight(env: dict[str, str]) -> dict[str, Any]:
    return run_protected_dgx_live_profile(
        env,
        profile_name=DGX_PROFILE_NAME,
    )


def _run_playwright_readiness(env: dict[str, str]) -> dict[str, Any]:
    return run_ae_web_playwright_readiness(env, require_installed=True)


@dataclass
class ProtectedOaSessionFixture:
    tenant_id: str
    owner_user_id: str
    employee_id: str
    password: str
    session: dict[str, Any] | None = None
    calls: list[str] = field(default_factory=list)

    def login_with_credentials(
        self,
        login_request: Mapping[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append("login")
        if (
            login_request.get("tenant_id") != self.tenant_id
            or login_request.get("employee_id") != self.employee_id
            or login_request.get("password") != self.password
        ):
            raise OaUserSessionClientError(
                401,
                "oa.user_login_invalid",
                "Protected smoke credential is invalid.",
            )
        issued = issue_mock_user_token(
            tenant_id=self.tenant_id,
            user_id=self.owner_user_id,
            scopes=tuple(login_request.get("requested_scopes") or ("workspace:use",)),
            roles=("employee", "smoke-tester"),
        )
        self.session = build_browser_session_snapshot(issued.claims)
        return {"session": self.session}

    def issue_session(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("credential login must be used")

    def introspect_session(
        self,
        session_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append("introspect")
        active = self.session is not None and self.session["session_id"] == session_id
        return {"active": active, "session": self.session if active else None}

    def revoke_session(
        self,
        session_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append("revoke")
        session = dict(self.session or {})
        session["status"] = "REVOKED"
        return {"revoked": bool(self.session), "session": session}


class LiveWorkerCxAsyncClient:
    def __init__(
        self,
        cx_client: TestClient,
        *,
        job_queue: SqlAlchemyJobQueue,
        leases: SqlAlchemyCxWorkerLeaseStore,
        generation_runtime: GroundedGenerationRuntime,
        private_store: FileSystemCxPrivateTextStore,
        generation_client: InProcessLiveMoClient,
    ) -> None:
        self._base = _test_client_adapter(cx_client)
        self._job_queue = job_queue
        self._leases = leases
        self._generation_runtime = generation_runtime
        self._private_store = private_store
        self._generation_client = generation_client
        self.worker_results: list[dict[str, Any]] = []

    def admit_generation(self, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        admitted = self._base.admit_generation(payload, **kwargs)
        result = run_bounded_worker_batch(
            job_queue=self._job_queue,
            lease_store=self._leases,
            handler=AsyncGenerationWorkerHandler(
                self._job_queue,
                self._generation_runtime,
                self._private_store,
                self._generation_client,
            ),
            worker_id=f"s109-worker-{uuid4().hex[:12]}",
            worker_type="cx.generation.worker",
            workload="grounded_generation",
            runtime_policy=CxWorkerRuntimePolicy(max_jobs=1),
            clock=lambda: datetime.now(UTC).isoformat(),
        )
        self.worker_results.append(result)
        return admitted

    def get_handoff(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._base.get_handoff(*args, **kwargs)

    def get_job(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._base.get_job(*args, **kwargs)

    def cancel_job(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._base.cancel_job(*args, **kwargs)


def build_live_ingestion_index_run(
    *,
    saved: Mapping[str, Any],
    extraction: Mapping[str, Any],
    document_id: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "job_id": str(saved["extraction"]["job_id"]),
        "idempotency_key": str(saved["upload_id"]),
        "tenant_ref": {"type": "oa.tenant", "id": TENANT_ID},
        "owner_subject_ref": {"type": "oa.user", "id": OWNER_ID},
        "request_id": request_id,
        "trace_id": trace_id,
        "created_at": str(saved["created_at"]),
        "updated_at": str(extraction["updated_at"]),
    }


def _execute_live_browser_smoke(  # pragma: no cover - protected DB/DGX/browser
    *,
    ae_database_url: str,
    cx_database_url: str,
    runtime_environ: dict[str, str],
    journey_hook: JourneyHook | None = None,
) -> dict[str, Any]:
    setup_request_id = f"s109-{uuid4().hex}"
    setup_trace_id = uuid4().hex
    workspace_id = str(uuid4())
    chat_document_id = str(uuid4())
    document_id: str | None = None
    source_file_id: str | None = None
    vector_index_id: str | None = None
    retrieval_package_id: str | None = None
    browser_interaction_id: str | None = None
    ae_trace_id: str | None = None
    ae_request_id: str | None = None
    prompt_render_event_id: str | None = None
    api_server = None
    web_server = None
    node_result: dict[str, Any] = {}
    extension_observation: dict[str, Any] = {}
    cleanup: dict[str, int] = {}

    cx_engine = build_engine(cx_database_url)
    cx_factory = build_session_factory(cx_engine)
    ae_engine = build_engine(ae_database_url)
    ae_factory = build_session_factory(ae_engine)
    stale_runtime_cleanup = {
        "ae": _cleanup_stale_s109_ae_runtime(ae_engine),
        "cx": _cleanup_stale_s109_runtime(cx_engine),
    }
    repository = SqlAlchemyCxContentRepository(cx_factory)
    vector_repository = SqlAlchemyVectorIndexRepository(cx_factory)
    store = ContentIngestionStore(content_repository=repository)
    event_store = SqlAlchemyOperationalEventStore(cx_factory)
    cx_emitter = OperationalEventEmitter(service_id="nex-cx", store=event_store)
    job_queue = SqlAlchemyJobQueue(cx_factory)
    generation_repository = SqlAlchemyGenerationRuntimeRepository(
        cx_factory,
        source_kind="s109-postgres-live",
    )
    oa_fixture = ProtectedOaSessionFixture(
        TENANT_ID,
        OWNER_ID,
        EMPLOYEE_ID,
        LOGIN_PASSWORD,
    )

    try:
        with tempfile.TemporaryDirectory(prefix="nex-s109-live-") as temp_dir:
            root = Path(temp_dir)
            storage = _storage_config(root)
            private_store = FileSystemCxPrivateTextStore(root / "cx-private")
            response_store = LocalGeneratedResponseStorage(root / "ae-responses")
            generation_runtime = GroundedGenerationRuntime(
                admission_repository=SqlAlchemyGenerationAdmissionRepository(cx_factory),
                execution_repository=generation_repository,
                private_output_store=private_store,
            )
            vector_store_api = build_pgvector_cx_vector_store(
                database_env=CX_DATABASE_ENV,
                environ={**runtime_environ, CX_DATABASE_ENV: cx_database_url},
                workload="api",
            )
            vector_store_worker = build_pgvector_cx_vector_store(
                database_env=CX_DATABASE_ENV,
                environ={**runtime_environ, CX_DATABASE_ENV: cx_database_url},
                workload="worker",
            )
            mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
            register_mock_provider_routes(mo_app)
            effective_env = {
                **runtime_environ,
                AE_DATABASE_ENV: ae_database_url,
                CX_DATABASE_ENV: cx_database_url,
                "NEX_AE_AUTH_SESSION_MODE": "oa",
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            }

            with patched_environ(effective_env):
                remote_provider.reset_remote_provider_telemetry()
                with TestClient(mo_app) as mo_client:
                    live_mo_client = InProcessLiveMoClient(mo_client)
                    composition = build_cx_mvp_runtime(
                        session_factory=cx_factory,
                        store=store,
                        storage_config=storage,
                        content_repository=repository,
                        vector_repository=vector_repository,
                        retrieval_vector_store=vector_store_api,
                        ingestion_vector_store=vector_store_worker,
                        private_text_store=private_store,
                        embedding_client=live_mo_client,
                        embedding_alias=DEFAULT_EMBEDDING_ALIAS,
                        rerank_client=live_mo_client,
                        reranker_alias=DEFAULT_RERANKER_ALIAS,
                    )
                    cx_app = _build_cx_app(
                        store=store,
                        hybrid_runtime=composition.hybrid_retrieval_runtime,
                        job_queue=job_queue,
                        generation_runtime=generation_runtime,
                        private_store=private_store,
                        generation_repository=generation_repository,
                        generation_client=live_mo_client,
                        emitter=cx_emitter,
                    )
                    with TestClient(cx_app) as cx_client:
                        registration = build_upload_registration(
                            {
                                "filename": "s109-grounded-generation.txt",
                                "content_type": "text/plain",
                                "content_text": SOURCE_TEXT,
                                "tenant_id": TENANT_ID,
                                "owner_user_id": OWNER_ID,
                                "uploaded_by_user_id": OWNER_ID,
                            },
                            storage_config=storage,
                            request_id=setup_request_id,
                            trace_id=setup_trace_id,
                        )
                        saved = store.save_upload_registration(
                            registration,
                            source_text=SOURCE_TEXT,
                        )
                        document_id = str(saved["document_id"])
                        refs = store.get_content_ref(document_id)
                        if refs is None:
                            raise RuntimeError("content_lineage_unavailable")
                        source_file_id = refs["source_file_id"]
                        extraction = run_text_extraction_job(
                            saved["extraction"]["job_id"],
                            store=store,
                            storage_config=storage,
                            request_id=setup_request_id,
                            trace_id=setup_trace_id,
                        )
                        chunk_set = store_chunk_set(
                            document_id=document_id,
                            extraction=extraction,
                            markdown_text=Path(
                                extraction["extracted_markdown_path"]
                            ).read_text(encoding="utf-8"),
                            store=store,
                            storage_config=storage,
                            request_id=setup_request_id,
                            trace_id=setup_trace_id,
                        )
                        lexical = build_and_store_lexical_index(
                            document_id,
                            store=store,
                            storage_config=storage,
                            request_id=setup_request_id,
                            trace_id=setup_trace_id,
                        )
                        vector_result = composition.ingestion_vector_indexer(
                            build_live_ingestion_index_run(
                                saved=saved,
                                extraction=extraction,
                                document_id=document_id,
                                request_id=setup_request_id,
                                trace_id=setup_trace_id,
                            )
                        )
                        vector_index_id = vector_result.output_ref.split(":", 1)[1]
                        async_client = LiveWorkerCxAsyncClient(
                            cx_client,
                            job_queue=job_queue,
                            leases=SqlAlchemyCxWorkerLeaseStore(cx_factory),
                            generation_runtime=generation_runtime,
                            private_store=private_store,
                            generation_client=live_mo_client,
                        )
                        ae_prompt_store = SqlAlchemyAePromptRegistryStore(ae_factory)
                        seed_ae_prompt_registry(ae_prompt_store)
                        ae_chat_store = SqlAlchemyChatInteractionStore(ae_factory)
                        ae_event_store = SqlAlchemyOperationalEventStore(ae_factory)
                        workspace_store = SqlAlchemyWorkspaceRepository(ae_factory)
                        workspace = build_workspace_state(
                            {
                                "workspace_id": workspace_id,
                                "chat_document_id": chat_document_id,
                                "tenant_id": TENANT_ID,
                                "owner_user_id": OWNER_ID,
                                "title": "S109 grounded generation smoke",
                            },
                            request_id=setup_request_id,
                            trace_id=setup_trace_id,
                        )
                        workspace_store.save_workspace(
                            workspace,
                            build_workspace_activity(
                                workspace_id=workspace_id,
                                activity_type="workspace.created",
                                request_id=setup_request_id,
                                trace_id=setup_trace_id,
                                summary="Workspace created.",
                            ),
                        )
                        ae_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
                        ae_app.state.ae_workspace_store = workspace_store
                        register_auth_session_routes(
                            ae_app,
                            oa_session_client=oa_fixture,
                            session_mode="oa",
                        )
                        register_chat_routes(
                            ae_app,
                            store=ae_chat_store,
                            cx_async_client=async_client,
                            retrieval_client=TestClientCxRetrievalClient(cx_client),
                            prompt_store=ae_prompt_store,
                            event_emitter=OperationalEventEmitter(
                                service_id="nex-ae-api",
                                store=ae_event_store,
                            ),
                            generated_response_storage=response_store,
                        )
                        _install_browser_user_auth_middleware(ae_app)
                        api_server = browser_pg.start_api_server(
                            ae_app, browser_pg.find_free_port()
                        )
                        web_server = browser_pg.start_web_server(
                            browser_pg.find_free_port(), api_server.url
                        )
                        node_result = run_node_playwright_smoke(
                            runtime_environ,
                            web_url=web_server.url,
                            document_id=document_id,
                            workspace_id=workspace_id,
                            chat_document_id=chat_document_id,
                        )
                        browser_interaction_id = str(
                            node_result.pop("interaction_ref", "") or ""
                        )
                        if not browser_interaction_id:
                            return {
                                "execution_state": "BROWSER_FAILED",
                                "browser_failure_code": str(
                                    node_result.get("failure_code")
                                    or "browser_interaction_ref_missing"
                                ),
                                "browser_observation": dict(
                                    node_result.get("browser_observations") or {}
                                ),
                                "request_observation": dict(
                                    node_result.get("request_observations")
                                    or node_result.get("observations")
                                    or {}
                                ),
                                "provider_observation": {},
                                "checks": {"playwright_browser_passed": False},
                                "failed_checks": ["playwright_browser_passed"],
                            }
                        ae_observation = _ae_observation(
                            ae_engine,
                            interaction_id=browser_interaction_id,
                        )
                        ae_trace_id = ae_observation["trace_id"]
                        ae_request_id = ae_observation["request_id"]
                        retrieval_package_id = ae_observation[
                            "cx_retrieval_package_id"
                        ]
                        prompt_render_event_id = ae_observation[
                            "prompt_render_event_id"
                        ]
                        telemetry = read_provider_telemetry(
                            mo_client,
                            ae_trace_id,
                            ae_request_id,
                        )
                        provider = _provider_observation(telemetry)
                        cx_observation = _cx_observation(
                            cx_engine,
                            document_id=document_id,
                            retrieval_package_id=retrieval_package_id,
                            cx_generation_id=ae_observation["cx_generation_id"],
                            job_id=ae_observation["job_id"],
                        )
                        if journey_hook is not None:
                            extension_observation = journey_hook(
                                {
                                    "ae_database_url": ae_database_url,
                                    "ae_engine": ae_engine,
                                    "ae_factory": ae_factory,
                                    "ae_chat_store": ae_chat_store,
                                    "cx_client": cx_client,
                                    "storage_root": root,
                                    "tenant_id": TENANT_ID,
                                    "owner_id": OWNER_ID,
                                    "workspace_id": workspace_id,
                                    "chat_document_id": chat_document_id,
                                    "interaction_id": browser_interaction_id,
                                    "cx_generation_id": ae_observation[
                                        "cx_generation_id"
                                    ],
                                    "trace_id": ae_trace_id,
                                    "request_id": ae_request_id,
                                }
                            )
                        ae_identity = _database_identity(ae_engine)
                        cx_identity = _database_identity(cx_engine)

            node_checks = dict(node_result.get("checks") or {})
            extension_checks = dict(extension_observation.get("checks") or {})
            checks = {
                "actual_ae_test_database": ae_identity
                == {"database": AE_DATABASE, "role": AE_ROLE},
                "actual_cx_test_database": cx_identity
                == {"database": CX_DATABASE, "role": CX_ROLE},
                "playwright_browser_passed": node_result.get("status") == "PASS",
                "same_origin_browser_lifecycle": all(node_checks.values()),
                "ae_chat_persisted": ae_observation["status"] == "COMPLETED",
                "cx_retrieval_persisted": cx_observation["retrieval_status"]
                == "READY",
                "cx_generation_persisted": cx_observation["generation_status"]
                == "COMPLETED",
                "cx_job_succeeded": cx_observation["job_status"] == "SUCCEEDED",
                "document_vector_ready": cx_observation["vector_status"] == "READY",
                "worker_succeeded": bool(async_client.worker_results)
                and async_client.worker_results[-1].get("succeeded_count") == 1,
                "live_provider_models_frozen": all(
                    provider[capability]["model"] == EXPECTED_MODELS[capability]
                    for capability in EXPECTED_MODELS
                ),
                "all_live_provider_capabilities_called": all(
                    provider[capability]["success_count"] >= 1
                    for capability in EXPECTED_MODELS
                ),
                "content_lineage_ready": len(chunk_set["chunks"]) >= 1
                and lexical["unique_token_count"] >= 1,
                "browser_received_no_server_secret": node_checks.get(
                    "browser_secret_headers_absent"
                )
                is True,
                **extension_checks,
            }
            return {
                "execution_state": "EXECUTED",
                "database_identity": {"ae": ae_identity, "cx": cx_identity},
                "browser_observation": {
                    **dict(
                        node_result.get("browser_observations")
                        or dict(node_result.get("observations") or {}).get(
                            "failure_stage"
                        )
                        or {}
                    ),
                    "interaction_id_sha256": _digest(browser_interaction_id),
                },
                "request_observation": dict(
                    node_result.get("request_observations")
                    or node_result.get("observations")
                    or {}
                ),
                "provider_observation": provider,
                "worker_observation": _worker_observation(
                    async_client.worker_results[-1]
                    if async_client.worker_results
                    else {}
                ),
                "stale_runtime_cleanup": stale_runtime_cleanup,
                "persistence_observation": {
                    "ae_status": ae_observation["status"],
                    **cx_observation,
                },
                "session_fixture": {
                    "mode": "protected_in_memory_oa_adapter",
                    "login_called": "login" in oa_fixture.calls,
                    "introspection_called": "introspect" in oa_fixture.calls,
                    "credential_material_included": False,
                },
                "extension_observation": extension_observation,
                "checks": checks,
                "failed_checks": [name for name, passed in checks.items() if not passed],
            }
    finally:
        if web_server is not None:
            web_server.stop()
        if api_server is not None:
            api_server.stop()
        if browser_interaction_id or workspace_id:
            cleanup.update(
                _cleanup_ae_rows(
                    ae_engine,
                    interaction_id=browser_interaction_id,
                    workspace_id=workspace_id,
                    trace_id=ae_trace_id,
                    request_id=ae_request_id,
                    prompt_render_event_id=prompt_render_event_id,
                )
            )
        cleanup_cx_rows(
            cx_engine,
            trace_id=ae_trace_id or setup_trace_id,
            request_id=ae_request_id or setup_request_id,
            retrieval_package_id=retrieval_package_id,
            vector_index_id=vector_index_id,
            document_id=document_id,
            source_file_id=source_file_id,
        )
        if ae_trace_id and ae_trace_id != setup_trace_id:
            cleanup_cx_rows(
                cx_engine,
                trace_id=setup_trace_id,
                request_id=setup_request_id,
                retrieval_package_id=None,
                vector_index_id=None,
                document_id=None,
                source_file_id=None,
            )
        ae_engine.dispose()
        cx_engine.dispose()


def _install_browser_user_auth_middleware(app: Any) -> None:  # pragma: no cover
    token = issue_mock_user_token(
        tenant_id=TENANT_ID,
        user_id=OWNER_ID,
        scopes=("workspace:use", "documents:upload"),
        roles=("employee", "smoke-tester"),
    ).access_token

    @app.middleware("http")
    async def add_user_auth(request, call_next):  # type: ignore[no-untyped-def]
        path = str(request.scope.get("path") or "")
        headers = list(request.scope.get("headers", []))
        if path.startswith("/api/v1/chat/") and not any(
            key.lower() == b"authorization" for key, _value in headers
        ):
            request.scope["headers"] = [
                *headers,
                (b"authorization", f"Bearer {token}".encode("latin-1")),
            ]
        return await call_next(request)


def run_node_playwright_smoke(
    environ: Mapping[str, str],
    *,
    web_url: str,
    document_id: str,
    workspace_id: str,
    chat_document_id: str,
) -> dict[str, Any]:
    node_env = {
        **os.environ,
        "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_WEB_URL": web_url,
        "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_TENANT_ID": TENANT_ID,
        "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_OWNER_USER_ID": OWNER_ID,
        "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_EMPLOYEE_ID": EMPLOYEE_ID,
        "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_PASSWORD": LOGIN_PASSWORD,
        "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_DOCUMENT_ID": document_id,
        "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_WORKSPACE_ID": workspace_id,
        "NEX_AE_WEB_GROUNDED_GENERATION_PLAYWRIGHT_CHAT_DOCUMENT_ID": (
            chat_document_id
        ),
    }
    for key in (CHROMIUM_ENV, TIMEOUT_ENV):
        if environ.get(key):
            node_env[key] = str(environ[key])
    completed = subprocess.run(
        ["node", str(NODE_SCRIPT)],
        cwd=ROOT,
        env=node_env,
        capture_output=True,
        text=True,
        timeout=330,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "smoke_schema_version": NODE_SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": (
                "node_playwright_failed"
                if completed.returncode
                else "node_json_invalid"
            ),
            "returncode": completed.returncode,
        }
    if isinstance(payload, dict):
        payload.setdefault("returncode", completed.returncode)
        return payload
    return {
        "smoke_schema_version": NODE_SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "node_payload_invalid",
    }


def _ae_observation(  # pragma: no cover
    engine: Any,
    *,
    interaction_id: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status, trace_id, request_id, cx_retrieval_package_id, "
                "cx_generation_id, generation_summary "
                "FROM ae_chat_interactions "
                "WHERE chat_interaction_id = :interaction_id"
            ),
            {"interaction_id": interaction_id},
        ).mappings().one()
    generation = dict(row["generation_summary"] or {})
    async_generation = dict(generation.get("async_generation") or {})
    policy = dict(generation.get("policy") or {})
    render_ref = dict(policy.get("prompt_render_event_ref") or {})
    return {
        "status": str(row["status"]),
        "trace_id": str(row["trace_id"]),
        "request_id": str(row["request_id"]),
        "cx_retrieval_package_id": str(row["cx_retrieval_package_id"]),
        "cx_generation_id": str(row["cx_generation_id"]),
        "job_id": str(async_generation.get("job_id") or ""),
        "prompt_render_event_id": render_ref.get("prompt_render_event_id"),
    }


def _cx_observation(
    engine: Any,
    *,
    document_id: str,
    retrieval_package_id: str,
    cx_generation_id: str,
    job_id: str,
) -> dict[str, Any]:  # pragma: no cover
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT "
                "(SELECT status FROM cx_vector_indexes "
                " WHERE content_object_id = :document_id "
                " ORDER BY created_at DESC LIMIT 1) AS vector_status, "
                "(SELECT status FROM cx_retrieval_packages "
                " WHERE retrieval_package_id = :retrieval_package_id) "
                " AS retrieval_status, "
                "(SELECT status FROM cx_generation_executions "
                " WHERE cx_generation_id = :cx_generation_id) "
                " AS generation_status, "
                "(SELECT status FROM service_jobs WHERE job_id = :job_id) AS job_status"
            ),
            {
                "document_id": document_id,
                "retrieval_package_id": retrieval_package_id,
                "cx_generation_id": cx_generation_id,
                "job_id": job_id,
            },
        ).mappings().one()
    return {key: row[key] for key in row}


def _database_identity(engine: Any) -> dict[str, str]:  # pragma: no cover
    with engine.connect() as connection:
        database, role = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
    return {"database": str(database), "role": str(role)}


def _worker_observation(result: Mapping[str, Any]) -> dict[str, Any]:
    executions = result.get("executions")
    latest = executions[-1] if isinstance(executions, list) and executions else {}
    return {
        "stop_reason": result.get("stop_reason"),
        "claimed_count": int(result.get("claimed_count") or 0),
        "succeeded_count": int(result.get("succeeded_count") or 0),
        "retry_scheduled_count": int(result.get("retry_scheduled_count") or 0),
        "dead_lettered_count": int(result.get("dead_lettered_count") or 0),
        "latest_state": latest.get("state") if isinstance(latest, Mapping) else None,
        "latest_error_code": (
            latest.get("error_code") if isinstance(latest, Mapping) else None
        ),
    }


def _cleanup_stale_s109_runtime(engine: Any) -> dict[str, int]:  # pragma: no cover
    deleted: dict[str, int] = {}
    with engine.begin() as connection:
        deleted["events"] = int(
            connection.execute(
                text(
                    "DELETE FROM service_operational_events WHERE trace_id IN ("
                    "SELECT trace_id FROM service_jobs "
                    "WHERE job_type = 'cx.grounded-generation.execute' "
                    "AND subject_type = 'oa.user' AND subject_id = :owner_id)"
                ),
                {"owner_id": OWNER_ID},
            ).rowcount
            or 0
        )
        deleted["executions"] = int(
            connection.execute(
                text(
                    "DELETE FROM cx_generation_executions "
                    "WHERE owner_subject_ref_id = :owner_id"
                ),
                {"owner_id": OWNER_ID},
            ).rowcount
            or 0
        )
        deleted["admissions"] = int(
            connection.execute(
                text(
                    "DELETE FROM cx_gen_admissions "
                    "WHERE owner_subject_ref_id = :owner_id"
                ),
                {"owner_id": OWNER_ID},
            ).rowcount
            or 0
        )
        deleted["jobs"] = int(
            connection.execute(
                text(
                    "DELETE FROM service_jobs "
                    "WHERE job_type = 'cx.grounded-generation.execute' "
                    "AND subject_type = 'oa.user' AND subject_id = :owner_id"
                ),
                {"owner_id": OWNER_ID},
            ).rowcount
            or 0
        )
    return deleted


def _cleanup_stale_s109_ae_runtime(engine: Any) -> dict[str, int]:
    deleted: dict[str, int] = {}
    with engine.begin() as connection:
        deleted["events"] = int(
            connection.execute(
                text(
                    "DELETE FROM service_operational_events "
                    "WHERE trace_id IN ("
                    "SELECT trace_id FROM ae_chat_interactions "
                    "WHERE user_id = :owner_id) "
                    "OR request_id IN ("
                    "SELECT request_id FROM ae_chat_interactions "
                    "WHERE user_id = :owner_id)"
                ),
                {"owner_id": OWNER_ID},
            ).rowcount
            or 0
        )
        deleted["render_events"] = int(
            connection.execute(
                text(
                    "DELETE FROM ae_prompt_render_events "
                    "WHERE chat_interaction_id IN ("
                    "SELECT chat_interaction_id FROM ae_chat_interactions "
                    "WHERE user_id = :owner_id)"
                ),
                {"owner_id": OWNER_ID},
            ).rowcount
            or 0
        )
        deleted["chat"] = int(
            connection.execute(
                text(
                    "DELETE FROM ae_chat_interactions WHERE user_id = :owner_id"
                ),
                {"owner_id": OWNER_ID},
            ).rowcount
            or 0
        )
        deleted["workspaces"] = int(
            connection.execute(
                text("DELETE FROM ae_workspaces WHERE owner_user_id = :owner_id"),
                {"owner_id": OWNER_ID},
            ).rowcount
            or 0
        )
    return deleted


def _cleanup_ae_rows(
    engine: Any,
    *,
    interaction_id: str | None,
    workspace_id: str,
    trace_id: str | None,
    request_id: str | None,
    prompt_render_event_id: str | None,
) -> dict[str, int]:  # pragma: no cover
    deleted: dict[str, int] = {}
    with engine.begin() as connection:
        deleted["events"] = int(
            connection.execute(
                text(
                    "DELETE FROM service_operational_events "
                    "WHERE trace_id = :trace_id OR request_id = :request_id"
                ),
                {"trace_id": trace_id or "", "request_id": request_id or ""},
            ).rowcount
            or 0
        )
        if interaction_id:
            deleted["chat"] = int(
                connection.execute(
                    text(
                        "DELETE FROM ae_chat_interactions "
                        "WHERE chat_interaction_id = :interaction_id"
                    ),
                    {"interaction_id": interaction_id},
                ).rowcount
                or 0
            )
        if prompt_render_event_id:
            deleted["render_event"] = int(
                connection.execute(
                    text(
                        "DELETE FROM ae_prompt_render_events "
                        "WHERE prompt_render_event_id = :event_id"
                    ),
                    {"event_id": prompt_render_event_id},
                ).rowcount
                or 0
            )
        deleted["workspace"] = int(
            connection.execute(
                text(
                    "DELETE FROM ae_workspaces WHERE workspace_id = :workspace_id"
                ),
                {"workspace_id": workspace_id},
            ).rowcount
            or 0
        )
    return deleted


def _target_url_allowed(database_url: str, *, role: str, database: str) -> bool:
    try:
        parsed = urlsplit(database_url)
        return (
            unquote(parsed.username or "") == role
            and unquote(parsed.path.lstrip("/")) == database
        )
    except ValueError:
        return False


def _migration_current(migration: object) -> bool:
    planned = tuple(getattr(migration, "planned", ()))
    applied = tuple(getattr(migration, "applied", ()))
    skipped = tuple(getattr(migration, "skipped", ()))
    return bool(planned) and len(planned) == len(applied) + len(skipped)


def _migration_summary(migration: object) -> dict[str, Any]:
    planned = tuple(getattr(migration, "planned", ()))
    return {
        "planned_count": len(planned),
        "applied_count": len(tuple(getattr(migration, "applied", ()))),
        "skipped_count": len(tuple(getattr(migration, "skipped", ()))),
        "latest_version": planned[-1] if planned else None,
    }


def _source_status(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {"status": evidence.get("status", "UNKNOWN")}


def _source_failure_detail(evidence: Mapping[str, Any]) -> str:
    return str(
        evidence.get("failure_code")
        or evidence.get("skip_reason")
        or evidence.get("status")
        or "unknown"
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def assert_evidence_redacted(
    evidence: Mapping[str, Any],
    environ: Mapping[str, str],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    if SOURCE_TEXT in serialized or LOGIN_PASSWORD in serialized:
        raise ValueError("Grounded generation smoke evidence contains private content.")
    if "cx-private" in serialized or "ae-responses" in serialized:
        raise ValueError("Grounded generation smoke evidence contains a storage path.")
    for key in PROTECTED_ENV_KEYS:
        value = _secret_fragment(key, environ.get(key))
        if value and value in serialized:
            raise ValueError("Grounded generation smoke evidence contains a protected value.")


def _secret_fragment(key: str, value: object) -> str | None:
    text_value = str(value or "")
    if not text_value:
        return None
    if key.endswith("DATABASE_URL"):
        try:
            return unquote(urlsplit(text_value).password or "") or None
        except ValueError:
            return text_value
    if key == CHROMIUM_ENV:
        return None
    return text_value if len(text_value) >= 8 else None


def _failure(
    code: str,
    detail: object,
    *,
    sources: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1090",
        "requirement": "S109",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
        "live_provider_required": True,
        "playwright_required": True,
    }
    if sources:
        result["source_smokes"] = dict(sources)
    return result


def _safe_exception_detail(exc: Exception) -> str:
    detail = exc.__class__.__name__
    smoke_stage = getattr(exc, "smoke_stage", None)
    if (
        isinstance(smoke_stage, str)
        and smoke_stage
        and all(character.isalnum() or character in "._-" for character in smoke_stage)
    ):
        return f"{detail}:{smoke_stage}"
    diagnostic = getattr(getattr(exc, "orig", None), "diag", None)
    constraint = getattr(diagnostic, "constraint_name", None)
    if isinstance(constraint, str) and constraint.replace("_", "").isalnum():
        return f"{detail}:{constraint}"
    return detail


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"ae_web_grounded_generation_live=skipped reason={SMOKE_ENV}"
    checks = dict(evidence.get("checks") or {})
    browser = dict(evidence.get("browser_observation") or {})
    provider = dict(evidence.get("provider_observation") or {})
    return (
        "ae_web_grounded_generation_live="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"display={browser.get('display_mode', 'not-run')} "
        f"providers={sum(bool(item.get('success_count')) for item in provider.values())}/3 "
        f"databases={'ae,cx' if evidence.get('actual_postgres') else 'not-run'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run protected AE Web grounded-generation Playwright/PostgreSQL/DGX smoke."
        )
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_web_grounded_generation_playwright_postgres_smoke()
    if args.output:
        serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
        assert_evidence_redacted(evidence, os.environ)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{serialized}\n", encoding="utf-8")
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    )
    return 1 if evidence.get("status") == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
