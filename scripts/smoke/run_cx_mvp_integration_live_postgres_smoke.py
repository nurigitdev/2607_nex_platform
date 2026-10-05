#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import nex_mo.remote_provider as remote_provider  # noqa: E402
from nex_cx.async_generation_operations import (  # noqa: E402
    register_async_generation_operations_routes,
)
from nex_cx.async_generation_worker import AsyncGenerationWorkerHandler  # noqa: E402
from nex_cx.chunking import store_chunk_set  # noqa: E402
from nex_cx.embedding_index import DEFAULT_EMBEDDING_ALIAS  # noqa: E402
from nex_cx.generation import (  # noqa: E402
    GenerationExecutionStore,
    register_generation_routes,
)
from nex_cx.generation_read_model import GenerationReadModel  # noqa: E402
from nex_cx.generation_repository import (  # noqa: E402
    SqlAlchemyGenerationRuntimeRepository,
)
from nex_cx.generation_runtime import (  # noqa: E402
    GroundedGenerationRuntime,
    SqlAlchemyGenerationAdmissionRepository,
)
from nex_cx.ingestion import (  # noqa: E402
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    run_text_extraction_job,
)
from nex_cx.lexical_index import build_and_store_lexical_index  # noqa: E402
from nex_cx.mvp_runtime import build_cx_mvp_runtime  # noqa: E402
from nex_cx.pgvector_store import build_pgvector_cx_vector_store  # noqa: E402
from nex_cx.private_text_store import FileSystemCxPrivateTextStore  # noqa: E402
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_cx.retrieval import (  # noqa: E402
    DEFAULT_RERANKER_ALIAS,
    register_retrieval_routes,
)
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
    issue_mock_service_token,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)
from run_protected_dgx_live_profile import (  # noqa: E402
    protected_dgx_vllm_profile_defaults,
)
from run_protected_live_rag_smoke import (  # noqa: E402
    InProcessLiveMoClient,
    patched_environ,
    patched_remote_request,
    read_provider_telemetry,
)


SCHEMA_VERSION = "cx_mvp_integration_live_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_MVP_INTEGRATION_LIVE_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_CX_MVP_INTEGRATION_LIVE_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
EXPECTED_MODELS = {
    "embedding": "Qwen3-Embedding-4B",
    "reranking": "Qwen3-Reranker-4B",
    "generation": "Qwen3.5-4B",
}
TENANT_ID = "s100-live-tenant"
OWNER_ID = "s100-live-owner"
OTHER_OWNER_ID = "s100-live-other-owner"
SOURCE_MARKER = "S100_PRIVATE_MVP_SOURCE"
PROMPT_MARKER = "S100_PRIVATE_MVP_PROMPT"
QUERY_TEXT = "S100 소유자 문서 통합 검색 검증"
PROTECTED_ENV_KEYS = (
    "NEX_CX_TEST_DATABASE_URL",
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_API_KEY",
)

HttpRequester = Callable[..., Any]
SmokeExecutor = Callable[..., dict[str, Any]]


def run_cx_mvp_integration_live_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
    executor: SmokeExecutor | None = None,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
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

    database_url = ""
    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(
            SERVICE_ID,
            profile=profile,
            environ=effective_env,
        )
        if not _target_url_allowed(database_url):
            return _failure(
                "target_not_allowed",
                f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
            )
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execute = executor or _execute_live_smoke
        execution = execute(
            database_url=database_url,
            database_env=database_env,
            runtime_environ={
                **effective_env,
                SERVICE_SPECS[SERVICE_ID].database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
            requester=requester,
        )
        failed_checks = execution.get("failed_checks") or []
        if failed_checks:
            return _failure(
                "mvp_integration_live_checks_failed",
                list(failed_checks),
                execution=execution,
            )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "planned_count": len(migration.planned),
                "applied_count": len(migration.applied),
                "skipped_count": len(migration.skipped),
            },
            "provider_path": "cx_to_mo_capability_alias_only",
            **execution,
        }
        assert_evidence_redacted(evidence, effective_env)
        return evidence
    except (MigrationError, ValueError) as exc:
        result = _failure("configuration_invalid", exc.__class__.__name__)
    except Exception as exc:  # pragma: no cover - protected live evidence
        result = _failure("execution_failed", exc.__class__.__name__)
    assert_evidence_redacted(result, effective_env)
    return result


def configuration_issues(environ: Mapping[str, str]) -> list[dict[str, str]]:
    required = (
        "NEX_CX_TEST_DATABASE_URL",
        "NEX_MO_REMOTE_EMBEDDING_URL",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY",
        "NEX_MO_REMOTE_RERANKER_URL",
        "NEX_MO_REMOTE_RERANKER_API_KEY",
        "NEX_MO_VLLM_API_KEY",
    )
    issues = [
        {"error_code": "configuration_missing", "field": key}
        for key in required
        if not str(environ.get(key, "")).strip()
    ]
    if not (
        str(environ.get("NEX_MO_VLLM_CHAT_COMPLETIONS_URL", "")).strip()
        or str(environ.get("NEX_MO_VLLM_BASE_URL", "")).strip()
    ):
        issues.append(
            {
                "error_code": "configuration_missing",
                "field": "NEX_MO_VLLM_CHAT_COMPLETIONS_URL|NEX_MO_VLLM_BASE_URL",
            }
        )
    expected = {
        "NEX_MO_REMOTE_EMBEDDING_MODEL": EXPECTED_MODELS["embedding"],
        "NEX_MO_REMOTE_RERANKER_MODEL": EXPECTED_MODELS["reranking"],
        "NEX_MO_VLLM_MODEL": EXPECTED_MODELS["generation"],
    }
    for field, expected_value in expected.items():
        observed = environ.get(field)
        if observed != expected_value:
            issues.append(
                {
                    "error_code": "provider_model_mismatch",
                    "field": field,
                    "expected": expected_value,
                    "observed": str(observed or ""),
                }
            )
    shapes = {
        "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "openai_embeddings",
        "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE": "rerank",
    }
    for field, expected_value in shapes.items():
        if environ.get(field) != expected_value:
            issues.append(
                {
                    "error_code": "provider_shape_mismatch",
                    "field": field,
                    "expected": expected_value,
                    "observed": str(environ.get(field, "")),
                }
            )
    return issues


def _execute_live_smoke(  # pragma: no cover - protected PostgreSQL/DGX evidence
    *,
    database_url: str,
    database_env: str,
    runtime_environ: dict[str, str],
    requester: HttpRequester | None,
) -> dict[str, Any]:
    probe_id = uuid4().hex
    request_id = f"s100-{probe_id}"
    trace_id = uuid4().hex
    document_id: str | None = None
    source_file_id: str | None = None
    vector_index_id: str | None = None
    retrieval_package_id: str | None = None
    generation_id: str | None = None
    job_id: str | None = None
    checks: dict[str, bool] = {}
    engine = build_engine(database_url)
    factory = build_session_factory(engine)
    repository = SqlAlchemyCxContentRepository(factory)
    vector_repository = SqlAlchemyVectorIndexRepository(factory)
    store = ContentIngestionStore(content_repository=repository)
    event_store = SqlAlchemyOperationalEventStore(factory)
    emitter = OperationalEventEmitter(service_id=SERVICE_ID, store=event_store)
    job_queue = SqlAlchemyJobQueue(factory)
    generation_repository = SqlAlchemyGenerationRuntimeRepository(
        factory,
        source_kind="postgres-write",
        database_env=database_env,
        redacted_database_url=redact_database_url(database_url),
    )

    try:
        with tempfile.TemporaryDirectory(prefix="nex-cx-s100-live-") as temp_dir:
            root = Path(temp_dir)
            storage = _storage_config(root)
            private_store = FileSystemCxPrivateTextStore(root / "private")
            generation_runtime = GroundedGenerationRuntime(
                admission_repository=SqlAlchemyGenerationAdmissionRepository(factory),
                execution_repository=generation_repository,
                private_output_store=private_store,
            )
            vector_store_api = build_pgvector_cx_vector_store(
                database_env=database_env,
                environ=runtime_environ,
                workload="api",
            )
            vector_store_worker = build_pgvector_cx_vector_store(
                database_env=database_env,
                environ=runtime_environ,
                workload="worker",
            )
            mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
            register_mock_provider_routes(mo_app)

            with patched_environ(runtime_environ):
                with patched_remote_request(requester):
                    remote_provider.reset_remote_provider_telemetry()
                    with TestClient(mo_app) as mo_test_client:
                        mo_client = InProcessLiveMoClient(mo_test_client)
                        composition = build_cx_mvp_runtime(
                            session_factory=factory,
                            store=store,
                            storage_config=storage,
                            content_repository=repository,
                            vector_repository=vector_repository,
                            retrieval_vector_store=vector_store_api,
                            ingestion_vector_store=vector_store_worker,
                            private_text_store=private_store,
                            embedding_client=mo_client,
                            embedding_alias=DEFAULT_EMBEDDING_ALIAS,
                            rerank_client=mo_client,
                            reranker_alias=DEFAULT_RERANKER_ALIAS,
                        )
                        app = _build_cx_app(
                            store=store,
                            hybrid_runtime=composition.hybrid_retrieval_runtime,
                            job_queue=job_queue,
                            generation_runtime=generation_runtime,
                            private_store=private_store,
                            generation_repository=generation_repository,
                            generation_client=mo_client,
                            emitter=emitter,
                        )
                        with TestClient(app) as client:
                            identity = _database_identity(engine)
                            source_text = (
                                f"{SOURCE_MARKER}_{probe_id} S100 소유자 문서 통합 검색 "
                                "검증의 확인 문구는 ORION ONE HUNDRED 입니다."
                            )
                            registration = build_upload_registration(
                                {
                                    "filename": "s100-mvp-integration.txt",
                                    "content_type": "text/plain",
                                    "content_text": source_text,
                                    "tenant_id": TENANT_ID,
                                    "owner_user_id": OWNER_ID,
                                    "uploaded_by_user_id": OWNER_ID,
                                },
                                storage_config=storage,
                                request_id=request_id,
                                trace_id=trace_id,
                            )
                            saved = store.save_upload_registration(
                                registration,
                                source_text=source_text,
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
                                request_id=request_id,
                                trace_id=trace_id,
                            )
                            chunk_set = store_chunk_set(
                                document_id=document_id,
                                extraction=extraction,
                                markdown_text=Path(
                                    extraction["extracted_markdown_path"]
                                ).read_text(encoding="utf-8"),
                                store=store,
                                storage_config=storage,
                                request_id=request_id,
                                trace_id=trace_id,
                            )
                            lexical = build_and_store_lexical_index(
                                document_id,
                                store=store,
                                storage_config=storage,
                                request_id=request_id,
                                trace_id=trace_id,
                            )
                            index_result = composition.ingestion_vector_indexer(
                                {
                                    "document_id": document_id,
                                    "tenant_ref": {
                                        "type": "oa.tenant",
                                        "id": TENANT_ID,
                                    },
                                    "owner_subject_ref": {
                                        "type": "oa.user",
                                        "id": OWNER_ID,
                                    },
                                    "request_id": request_id,
                                    "trace_id": trace_id,
                                    "updated_at": extraction["updated_at"],
                                }
                            )
                            vector_index_id = index_result.output_ref.split(":", 1)[1]
                            retrieval_response = client.post(
                                "/api/v1/retrieval/context",
                                json={
                                    "query_text": QUERY_TEXT,
                                    "document_scope": {
                                        "document_ids": [document_id]
                                    },
                                    "top_k": 3,
                                    "purpose": "grounded_answer",
                                },
                                headers=_headers(request_id, trace_id, OWNER_ID),
                            )
                            if retrieval_response.status_code >= 400:
                                body = retrieval_response.json()
                                raise RuntimeError(
                                    "retrieval_failed:"
                                    f"{body.get('error_code', 'unknown')}:"
                                    f"{body.get('detail', 'unknown')}"
                                )
                            retrieval_response.raise_for_status()
                            package = retrieval_response.json()
                            retrieval_package_id = package["retrieval_package_id"]
                            evidence_ids = [
                                item["evidence_id"]
                                for item in package.get("evidence_items", [])
                            ]
                            if not evidence_ids:
                                raise RuntimeError("retrieval_evidence_unavailable")
                            admission_response = client.post(
                                "/api/v1/generation-jobs",
                                json=_generation_payload(package, evidence_ids[0], trace_id),
                                headers={
                                    **_headers(request_id, trace_id, OWNER_ID),
                                    "Idempotency-Key": f"s100-{probe_id}",
                                },
                            )
                            admission_response.raise_for_status()
                            admission = admission_response.json()
                            job_id = admission["job"]["job_id"]
                            generation_id = admission["job"]["cx_generation_id"]
                            pending_response = client.get(
                                f"/api/v1/generation-jobs/{job_id}/handoff",
                                headers=_headers(request_id, trace_id, OWNER_ID),
                            )
                            pending_response.raise_for_status()
                            worker_result = run_bounded_worker_batch(
                                job_queue=job_queue,
                                lease_store=SqlAlchemyCxWorkerLeaseStore(factory),
                                handler=AsyncGenerationWorkerHandler(
                                    job_queue,
                                    generation_runtime,
                                    private_store,
                                    mo_client,
                                ),
                                worker_id=f"s100-worker-{probe_id}",
                                worker_type="cx.generation.worker",
                                workload="grounded_generation",
                                runtime_policy=CxWorkerRuntimePolicy(max_jobs=1),
                                clock=lambda: datetime.now(UTC).isoformat(),
                            )

                            restarted_app = _build_cx_app(
                                store=store,
                                hybrid_runtime=composition.hybrid_retrieval_runtime,
                                job_queue=SqlAlchemyJobQueue(factory),
                                generation_runtime=GroundedGenerationRuntime(
                                    admission_repository=(
                                        SqlAlchemyGenerationAdmissionRepository(factory)
                                    ),
                                    execution_repository=(
                                        SqlAlchemyGenerationRuntimeRepository(
                                            factory,
                                            source_kind="postgres-restart-read",
                                        )
                                    ),
                                    private_output_store=(
                                        FileSystemCxPrivateTextStore(private_store.root)
                                    ),
                                ),
                                private_store=FileSystemCxPrivateTextStore(
                                    private_store.root
                                ),
                                generation_repository=(
                                    SqlAlchemyGenerationRuntimeRepository(
                                        factory,
                                        source_kind="postgres-restart-read",
                                    )
                                ),
                                generation_client=mo_client,
                                emitter=emitter,
                            )
                            with TestClient(restarted_app) as restarted_client:
                                ready_response = restarted_client.get(
                                    f"/api/v1/generation-jobs/{job_id}/handoff",
                                    headers=_headers(request_id, trace_id, OWNER_ID),
                                )
                                ready_response.raise_for_status()
                                ready = ready_response.json()
                                hidden = restarted_client.get(
                                    f"/api/v1/generation-jobs/{job_id}/handoff",
                                    headers=_headers(
                                        request_id,
                                        trace_id,
                                        OTHER_OWNER_ID,
                                    ),
                                )
                            telemetry = read_provider_telemetry(
                                mo_test_client,
                                trace_id,
                                request_id,
                            )

            provider = _provider_observation(telemetry)
            persisted = _database_observation(
                engine,
                document_id=document_id,
                vector_index_id=vector_index_id,
                retrieval_package_id=retrieval_package_id,
                generation_id=generation_id,
                job_id=job_id,
            )
            handoff_content = ready.get("content", {})
            checks.update(
                {
                    "test_database_identity": identity
                    == {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE},
                    "durable_ingestion_lineage": (
                        len(chunk_set["chunks"]) >= 1
                        and lexical["unique_token_count"] >= 1
                    ),
                    "production_vector_publish": (
                        index_result.skipped is False
                        and persisted["vector_status"] == "READY"
                    ),
                    "permission_hardened_retrieval": (
                        package["status"] == "READY"
                        and package["owner_subject_ref_id"] == OWNER_ID
                        and package["score_summary"]["rerank_state"] == "APPLIED"
                    ),
                    "async_handoff_pending_then_ready": (
                        pending_response.json()["handoff_status"] == "PENDING"
                        and ready["handoff_status"] == "READY"
                        and ready["next_action"] == "PRESENT_GENERATION_TO_OWNER"
                    ),
                    "generation_worker_completed": (
                        worker_result["succeeded_count"] == 1
                        and persisted["generation_status"] == "COMPLETED"
                        and persisted["job_status"] == "SUCCEEDED"
                    ),
                    "restart_safe_private_content": (
                        handoff_content.get("owner_scope_enforced") is True
                        and handoff_content.get("size_bytes", 0) > 0
                        and isinstance(handoff_content.get("content_sha256"), str)
                    ),
                    "cross_owner_handoff_hidden": hidden.status_code == 404,
                    "all_live_provider_capabilities": all(
                        provider[capability]["success_count"] >= 1
                        for capability in EXPECTED_MODELS
                    ),
                    "provider_models_frozen": all(
                        provider[capability]["model"]
                        == EXPECTED_MODELS[capability]
                        for capability in EXPECTED_MODELS
                    ),
                    "metadata_rows_exclude_private_text": (
                        SOURCE_MARKER not in persisted["serialized_metadata"]
                        and PROMPT_MARKER not in persisted["serialized_metadata"]
                    ),
                }
            )
            safe_observation = {
                key: value
                for key, value in persisted.items()
                if key != "serialized_metadata"
            }
            return {
                "database_identity": identity,
                "provider_observation": provider,
                "lifecycle": {
                    "document_id_sha256": _digest(document_id),
                    "retrieval_package_id_sha256": _digest(
                        retrieval_package_id
                    ),
                    "generation_id_sha256": _digest(generation_id),
                    "ingestion_chunk_count": len(chunk_set["chunks"]),
                    "retrieval_evidence_count": len(evidence_ids),
                    "handoff_status": ready["handoff_status"],
                    "owner_scope_enforced": ready["owner_scope_enforced"],
                },
                "database_observation": safe_observation,
                "checks": checks,
                "failed_checks": [
                    name for name, passed in checks.items() if not passed
                ],
            }
    finally:
        _cleanup(
            engine,
            trace_id=trace_id,
            request_id=request_id,
            retrieval_package_id=retrieval_package_id,
            vector_index_id=vector_index_id,
            document_id=document_id,
            source_file_id=source_file_id,
        )
        engine.dispose()


def _build_cx_app(
    *,
    store: ContentIngestionStore,
    hybrid_runtime: Any,
    job_queue: SqlAlchemyJobQueue,
    generation_runtime: GroundedGenerationRuntime,
    private_store: FileSystemCxPrivateTextStore,
    generation_repository: SqlAlchemyGenerationRuntimeRepository,
    generation_client: Any,
    emitter: OperationalEventEmitter,
) -> Any:  # pragma: no cover - protected PostgreSQL/DGX evidence
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    read_model = GenerationReadModel(generation_repository, private_store)
    register_retrieval_routes(
        app,
        store=store,
        hybrid_runtime=hybrid_runtime,
        event_emitter=emitter,
    )
    register_generation_routes(
        app,
        store=GenerationExecutionStore(),
        mo_client=generation_client,
        retrieval_store=store,
        execution_runtime=generation_runtime,
        read_model=read_model,
        event_emitter=emitter,
    )
    register_async_generation_operations_routes(
        app,
        job_queue=job_queue,
        runtime=generation_runtime,
        request_store=private_store,
        retrieval_store=store,
        read_model=read_model,
        event_emitter=emitter,
    )
    return app


def _generation_payload(
    package: Mapping[str, Any],
    evidence_id: str,
    trace_id: str,
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"{PROMPT_MARKER}: 근거의 확인 문구만 답하고 반드시 [1]을 "
                    "포함하세요."
                ),
            }
        ],
        "execution_mode": "GROUNDED_ANSWER",
        "template_id": "none",
        "prompt_binding_id": "ae.grounded_chat.default",
        "output_contract_id": "text_answer_v1",
        "provider_capability": "generation",
        "generation_profile": "grounded-answer",
        "retrieval_package_ref": {
            "retrieval_package_id": package["retrieval_package_id"],
            "package_hash": package["package_hash"],
        },
        "selected_evidence_ids": [evidence_id],
        "reasoning_mode": "disabled",
        "max_output_tokens": 128,
        "temperature": 0.0,
    }


def _storage_config(root: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=root,
        source_root=root / "cx" / "source-files",
        extracted_markdown_root=root / "cx" / "extracted-markdown",
        extraction_temp_root=root / "cx" / "extraction-temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def _headers(request_id: str, trace_id: str, subject_id: str) -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ae-api",
        audience=SERVICE_ID,
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-NEX-Tenant-ID": TENANT_ID,
        "X-NEX-Subject-ID": subject_id,
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _provider_observation(telemetry: Mapping[str, Any]) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for capability in EXPECTED_MODELS:
        item = next(
            (
                candidate
                for candidate in telemetry.get("data", [])
                if isinstance(candidate, Mapping)
                and candidate.get("capability") == capability
            ),
            {},
        )
        observations[capability] = {
            "model": item.get("model_revision"),
            "success_count": int(item.get("success_count", 0)),
            "failure_count": int(item.get("failure_count", 0)),
        }
    return observations


def _database_identity(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
) -> dict[str, str]:
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT current_database() AS database, current_user AS role")
        ).mappings().one()
    return {"database": str(row["database"]), "role": str(row["role"])}


def _database_observation(
    engine: Any,
    *,
    document_id: str,
    vector_index_id: str,
    retrieval_package_id: str,
    generation_id: str,
    job_id: str,
) -> dict[str, Any]:  # pragma: no cover - protected PostgreSQL evidence
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                  (SELECT status FROM cx_vector_indexes
                   WHERE vector_index_id = :vector_index_id) AS vector_status,
                  (SELECT status FROM cx_retrieval_packages
                   WHERE retrieval_package_id = :retrieval_package_id)
                    AS retrieval_status,
                  (SELECT status FROM cx_generation_executions
                   WHERE cx_generation_id = :generation_id) AS generation_status,
                  (SELECT status FROM service_jobs
                   WHERE job_id = :job_id) AS job_status,
                  (SELECT count(*) FROM cx_chunks
                   WHERE content_object_id = :document_id) AS chunk_count
                """
            ),
            {
                "document_id": document_id,
                "vector_index_id": vector_index_id,
                "retrieval_package_id": retrieval_package_id,
                "generation_id": generation_id,
                "job_id": job_id,
            },
        ).mappings().one()
    result = {key: row[key] for key in row}
    result["serialized_metadata"] = json.dumps(result, default=str)
    return result


def _cleanup(
    engine: Any,
    *,
    trace_id: str,
    request_id: str,
    retrieval_package_id: str | None,
    vector_index_id: str | None,
    document_id: str | None,
    source_file_id: str | None,
) -> None:  # pragma: no cover - protected PostgreSQL evidence
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM service_operational_events "
                "WHERE trace_id = :trace_id OR request_id = :request_id"
            ),
            {"trace_id": trace_id, "request_id": request_id},
        )
        connection.execute(
            text("DELETE FROM service_jobs WHERE trace_id = :trace_id"),
            {"trace_id": trace_id},
        )
        connection.execute(
            text("DELETE FROM cx_generation_executions WHERE trace_id = :trace_id"),
            {"trace_id": trace_id},
        )
        connection.execute(
            text("DELETE FROM cx_gen_admissions WHERE trace_id = :trace_id"),
            {"trace_id": trace_id},
        )
        if retrieval_package_id is not None:
            connection.execute(
                text(
                    "DELETE FROM cx_retrieval_packages "
                    "WHERE retrieval_package_id = :identifier"
                ),
                {"identifier": retrieval_package_id},
            )
        if document_id is not None:
            connection.execute(
                text(
                    "DELETE FROM cx_retrieval_packages "
                    "WHERE retrieval_package_id IN ("
                    "SELECT retrieval_package_id "
                    "FROM cx_retrieval_evidence_items "
                    "WHERE content_object_id = :identifier)"
                ),
                {"identifier": document_id},
            )
        if vector_index_id is not None:
            connection.execute(
                text("DELETE FROM cx_vectors WHERE vector_index_id = :identifier"),
                {"identifier": vector_index_id},
            )
            connection.execute(
                text(
                    "DELETE FROM cx_vector_indexes "
                    "WHERE vector_index_id = :identifier"
                ),
                {"identifier": vector_index_id},
            )
        if document_id is not None:
            connection.execute(
                text(
                    "DELETE FROM cx_content_objects "
                    "WHERE content_object_id = :identifier"
                ),
                {"identifier": document_id},
            )
        if source_file_id is not None:
            connection.execute(
                text(
                    "DELETE FROM cx_source_files "
                    "WHERE source_file_id = :identifier"
                ),
                {"identifier": source_file_id},
            )


def assert_evidence_redacted(
    evidence: Mapping[str, Any],
    environ: Mapping[str, str],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    if SOURCE_MARKER in serialized or PROMPT_MARKER in serialized:
        raise ValueError("MVP integration evidence contains private content.")
    if "cx-private://" in serialized or "nex-cx-s100-live-" in serialized:
        raise ValueError("MVP integration evidence contains a private storage path.")
    for key in PROTECTED_ENV_KEYS:
        secret = _secret_fragment(key, environ.get(key))
        if secret and secret in serialized:
            raise ValueError("MVP integration evidence contains a protected value.")


def _secret_fragment(key: str, value: object) -> str | None:
    if not isinstance(value, str) or len(value) < 4:
        return None
    if key == "NEX_CX_TEST_DATABASE_URL":
        try:
            password = urlsplit(value).password
        except ValueError:
            return None
        return unquote(password) if password else None
    return value


def _target_url_allowed(database_url: str) -> bool:
    try:
        parsed = urlsplit(database_url)
        return (
            unquote(parsed.username or "") == EXPECTED_ROLE
            and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
        )
    except ValueError:
        return False


def _digest(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _failure(
    code: str,
    detail: Any,
    *,
    execution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }
    if execution is not None:
        result["execution"] = dict(execution)
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "skipped":
        return f"cx_mvp_integration_live_postgres=skipped reason={SMOKE_ENV}"
    if status == "pass":
        lifecycle = result.get("lifecycle", {})
        checks = result.get("checks", {})
        return (
            "cx_mvp_integration_live_postgres=pass "
            f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
            f"handoff={lifecycle.get('handoff_status', 'unknown')} "
            "database=nex_cx_test providers=embedding,reranking,generation"
        )
    return (
        "cx_mvp_integration_live_postgres=fail "
        f"error={result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run_cx_mvp_integration_live_postgres_smoke()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
