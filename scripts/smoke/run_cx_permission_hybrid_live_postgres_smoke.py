#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence
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

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.chunking import store_chunk_set  # noqa: E402
from nex_cx.hybrid_candidate_orchestration import (  # noqa: E402
    orchestrate_permission_filtered_candidates,
)
from nex_cx.hybrid_retrieval_package import (  # noqa: E402
    PermissionFilteredHybridPackageRuntime,
)
from nex_cx.ingestion import (  # noqa: E402
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    run_text_extraction_job,
)
from nex_cx.lexical_candidates import PostgresLexicalCandidateStore  # noqa: E402
from nex_cx.lexical_index import build_and_store_lexical_index  # noqa: E402
from nex_cx.pgvector_store import build_pgvector_cx_vector_store  # noqa: E402
from nex_cx.private_content import sha256_private_vector  # noqa: E402
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_cx.retrieval import register_retrieval_routes  # noqa: E402
from nex_cx.retrieval_permissions import evaluate_retrieval_permission  # noqa: E402
from nex_cx.vector_index_freshness import (  # noqa: E402
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
)
from nex_cx.vector_index_publish import publish_vector_index  # noqa: E402
from nex_cx.vector_index_repository import (  # noqa: E402
    SqlAlchemyVectorIndexRepository,
)
from nex_mo.remote_provider import (  # noqa: E402
    GENERIC_RERANK_SHAPE,
    OPENAI_EMBEDDINGS_SHAPE,
    build_remote_embedding_execution_config,
    build_remote_reranker_execution_config,
    execute_remote_embedding_request,
    execute_remote_rerank_request,
    expected_models_from_env,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    run_service_migrations,
    service_database_env,
    service_database_url,
)
from run_protected_dgx_live_profile import (  # noqa: E402
    protected_dgx_vllm_profile_defaults,
)


SCHEMA_VERSION = "cx_permission_hybrid_live_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_PERMISSION_HYBRID_LIVE_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_CX_PERMISSION_HYBRID_LIVE_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
VECTOR_DIMENSION = 2560
TENANT_ID = "s95-live-tenant"
OWNER_ID = "s95-live-owner"
QUERY_TEXT = "권한 검색 하이브리드 검증"
SOURCE_PREFIX = "S95_PRIVATE_LIVE_SOURCE"
RERANKER_ALIAS = "s95-live-reranker"
PROTECTED_ENV_KEYS = (
    "NEX_CX_TEST_DATABASE_URL",
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
)

HttpRequester = Callable[..., Any]


def run_cx_permission_hybrid_live_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    embedding_requester: HttpRequester | None = None,
    rerank_requester: HttpRequester | None = None,
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
    issues = remote_provider_configuration_issues(effective_env)
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
                "CX test database target is required.",
            )
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_smoke(
            database_url,
            environ={**effective_env, database_env: database_url},
            database_env=database_env,
            embedding_requester=embedding_requester,
            rerank_requester=rerank_requester,
        )
        if execution["failed_checks"]:
            return _failure(
                "permission_hybrid_live_smoke_failed",
                execution["failed_checks"],
                execution=execution,
            )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "applied": list(migration.applied),
                "skipped": list(migration.skipped),
            },
            "remote_embedding_required": True,
            "remote_reranker_required": True,
            **execution,
        }
        assert_evidence_redacted(evidence, effective_env)
        return evidence
    except Exception as exc:  # pragma: no cover - protected live evidence
        return _failure(
            "execution_failed",
            exc.__class__.__name__,
            redacted_database_url=(
                redact_database_url(database_url) if database_url else None
            ),
        )


def remote_provider_configuration_issues(
    environ: Mapping[str, str],
) -> list[dict[str, Any]]:
    env = dict(environ)
    try:
        embedding = build_remote_embedding_execution_config(env)
        reranker = build_remote_reranker_execution_config(env)
    except ValueError:
        return [{"error_code": "remote_provider_timeout_invalid"}]

    issues: list[dict[str, Any]] = []
    checks = (
        (
            "embedding",
            embedding,
            OPENAI_EMBEDDINGS_SHAPE,
            "NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS",
            ("Qwen3-Embedding-4B",),
        ),
        (
            "reranker",
            reranker,
            GENERIC_RERANK_SHAPE,
            "NEX_MO_LIVE_EXPECTED_RERANKER_MODELS",
            ("Qwen3-Reranker-4B",),
        ),
    )
    for capability, config, shape, model_env, model_defaults in checks:
        if not config.configured:
            issues.append(
                {"error_code": f"remote_{capability}_endpoint_not_configured"}
            )
        if not config.api_key:
            issues.append(
                {"error_code": f"remote_{capability}_authorization_not_configured"}
            )
        if config.request_shape != shape:
            issues.append(
                {
                    "error_code": f"remote_{capability}_request_shape_mismatch",
                    "observed": config.request_shape,
                    "expected": shape,
                }
            )
        expected_models = expected_models_from_env(
            env.get(model_env),
            model_defaults,
        )
        if config.model_name not in expected_models:
            issues.append(
                {
                    "error_code": f"remote_{capability}_model_mismatch",
                    "observed": config.model_name,
                    "expected": list(expected_models),
                }
            )
    return issues


def request_live_embeddings(
    environ: Mapping[str, str],
    texts: Sequence[str],
    *,
    requester: HttpRequester | None = None,
) -> tuple[list[tuple[float, ...]], dict[str, Any]]:
    if (
        isinstance(texts, (str, bytes))
        or not texts
        or not all(isinstance(item, str) and item for item in texts)
    ):
        raise ValueError("Live embedding inputs must be non-empty strings.")
    env = dict(environ)
    config = build_remote_embedding_execution_config(env)
    response = execute_remote_embedding_request(
        {"alias": "cx-s95-live-smoke", "inputs": list(texts)},
        environ=env,
        requester=requester,
    )
    data = response.get("data")
    if not isinstance(data, list) or len(data) != len(texts):
        raise ValueError("Remote embedding response count does not match inputs.")
    ordered: list[tuple[float, ...] | None] = [None] * len(texts)
    for item in data:
        if not isinstance(item, Mapping):
            raise ValueError("Remote embedding response item is invalid.")
        index = item.get("index")
        raw_vector = item.get("embedding")
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < len(texts)
            or ordered[index] is not None
            or not isinstance(raw_vector, list)
        ):
            raise ValueError("Remote embedding response lineage is invalid.")
        vector = tuple(float(value) for value in raw_vector)
        if len(vector) != VECTOR_DIMENSION:
            raise ValueError("Remote embedding vector dimension does not match S95.")
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("Remote embedding vector contains a non-finite value.")
        if not any(value != 0.0 for value in vector):
            raise ValueError("Remote embedding vector must not be all zero.")
        ordered[index] = vector
    vectors = [vector for vector in ordered if vector is not None]
    return vectors, {
        "config": config.to_safe_summary(),
        "response_count": len(vectors),
        "vector_dimension": VECTOR_DIMENSION,
        "finite": True,
        "non_zero": True,
    }


def _execute_smoke(  # pragma: no cover - protected PostgreSQL/live evidence
    database_url: str,
    *,
    environ: Mapping[str, str],
    database_env: str,
    embedding_requester: HttpRequester | None = None,
    rerank_requester: HttpRequester | None = None,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    source_text = (
        f"{SOURCE_PREFIX}_{request_id} 권한 검색 하이브리드 검증 문서입니다. "
        "소유자 범위 BM25와 벡터 검색 결과를 함께 재정렬합니다."
    )
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    repository = SqlAlchemyCxContentRepository(session_factory)
    vector_repository = SqlAlchemyVectorIndexRepository(session_factory)
    lexical_store = PostgresLexicalCandidateStore(session_factory)
    store = ContentIngestionStore(content_repository=repository)
    vector_store = build_pgvector_cx_vector_store(
        database_env=database_env,
        environ=environ,
        workload="worker",
    )
    document_id: str | None = None
    source_file_id: str | None = None
    vector_index_id: str | None = None
    retrieval_package_id: str | None = None
    api_observation: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="nex-cx-s95-live-") as temp_dir:
            storage = _storage_config(Path(temp_dir))
            registration = build_upload_registration(
                {
                    "filename": "s95-permission-hybrid-live.txt",
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
                raise RuntimeError("S95 content lineage was not persisted.")
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
                markdown_text=Path(extraction["extracted_markdown_path"]).read_text(
                    encoding="utf-8"
                ),
                store=store,
                storage_config=storage,
                request_id=request_id,
                trace_id=trace_id,
            )
            lexical_index = build_and_store_lexical_index(
                document_id,
                store=store,
                storage_config=storage,
                request_id=request_id,
                trace_id=trace_id,
            )
            chunk_texts = [
                store.get_chunk_text(chunk["chunk_id"])
                for chunk in chunk_set["chunks"]
            ]
            if any(text_value is None for text_value in chunk_texts):
                raise RuntimeError("S95 chunk text was unavailable.")
            private_chunk_texts = [
                text_value for text_value in chunk_texts if text_value is not None
            ]
            vectors, provider_evidence = request_live_embeddings(
                environ,
                [QUERY_TEXT, *private_chunk_texts],
                requester=embedding_requester,
            )
            query_vector, *chunk_vectors = vectors
            persisted_chunk_set = store._find_persisted_chunk_set(document_id)
            if persisted_chunk_set is None:
                raise RuntimeError("S95 persisted chunk set was unavailable.")

            embedding_config = build_remote_embedding_execution_config(dict(environ))
            source_snapshot = build_source_snapshot(
                chunk_set_id=persisted_chunk_set["chunk_set_id"],
                chunk_policy_id=persisted_chunk_set["chunk_policy_id"],
                source_markdown_sha256=persisted_chunk_set[
                    "source_markdown_sha256"
                ],
                chunks=persisted_chunk_set["chunks"],
            )
            embedding_profile = build_embedding_profile(
                provider_alias="dgx-openai-compatible",
                model_profile_id=embedding_config.model_name,
                model_revision=embedding_config.model_revision,
                deployment_id=embedding_config.deployment_id,
                vector_dimension=VECTOR_DIMENSION,
            )
            manifest = build_vector_index_manifest(
                content_object_id=document_id,
                tenant_ref={"type": "oa.tenant", "id": TENANT_ID},
                owner_subject_ref={"type": "oa.user", "id": OWNER_ID},
                source_snapshot=source_snapshot,
                embedding_profile=embedding_profile,
                trace_id=trace_id,
                request_id=request_id,
                observed_at=extraction["updated_at"],
            )
            ready_manifest = publish_vector_index(
                access_context=_access_context(request_id, trace_id),
                manifest=manifest,
                vectors_by_chunk_id={
                    chunk["chunk_id"]: vector
                    for chunk, vector in zip(
                        persisted_chunk_set["chunks"],
                        chunk_vectors,
                        strict=True,
                    )
                },
                vector_store=vector_store,
                repository=vector_repository,
                observed_at=extraction["updated_at"],
            )
            vector_index_id = ready_manifest["vector_index_id"]
            candidate_observation: dict[str, Any] = {}

            class CandidateProvider:
                def build_candidate_set(
                    self,
                    *,
                    access_context: CxAccessContext,
                    query_text: str,
                    requested_document_ids: Sequence[str],
                ) -> dict[str, Any]:
                    content = repository.get_content_object(document_id)
                    permission = evaluate_retrieval_permission(
                        access_context,
                        content,
                    )
                    result = orchestrate_permission_filtered_candidates(
                        access_context=access_context,
                        query_text=query_text,
                        requested_document_ids=requested_document_ids,
                        content_objects={document_id: content},
                        lexical_store=lexical_store,
                        vector_targets_by_document_id={
                            document_id: {
                                "content_object_id": document_id,
                                "vector_index_id": vector_index_id,
                                "source_snapshot": source_snapshot,
                                "embedding_profile": embedding_profile,
                                "permission_decision": permission,
                            }
                        },
                        query_vector=query_vector,
                        vector_repository=vector_repository,
                        vector_store=vector_store,
                    )
                    result["query_vector_sha256"] = sha256_private_vector(
                        query_vector
                    )
                    candidate_observation.update(result)
                    return result

            class EvidenceMaterializer:
                def _load(
                    self,
                    *,
                    access_context: CxAccessContext,
                    chunk_refs: Sequence[Mapping[str, str]],
                    include_evidence: bool,
                ) -> list[dict[str, Any]]:
                    content = repository.get_content_object(document_id)
                    if not evaluate_retrieval_permission(
                        access_context,
                        content,
                    )["visible"]:
                        raise RuntimeError("S95 evidence permission was denied.")
                    chunks = {
                        item["chunk_id"]: item
                        for item in persisted_chunk_set["chunks"]
                    }
                    records: list[dict[str, Any]] = []
                    for ref in chunk_refs:
                        if ref["content_object_id"] != document_id:
                            raise RuntimeError("S95 evidence scope changed.")
                        chunk = chunks[ref["chunk_id"]]
                        chunk_text = store.get_chunk_text(ref["chunk_id"])
                        if chunk_text is None:
                            raise RuntimeError("S95 evidence text was unavailable.")
                        record = {
                            **ref,
                            "chunk_text": chunk_text,
                            "text_sha256": chunk["text_sha256"],
                        }
                        if include_evidence:
                            record.update(
                                {
                                    "chunk_policy_id": persisted_chunk_set[
                                        "chunk_policy_id"
                                    ],
                                    "start_offset": chunk["start_offset"],
                                    "end_offset": chunk["end_offset"],
                                    "matched_terms": ["권한", "검색"],
                                }
                            )
                        records.append(record)
                    return records

                def load_authorized_texts(self, **kwargs: Any) -> list[dict[str, Any]]:
                    return self._load(**kwargs, include_evidence=False)

                def load_authorized_evidence(
                    self,
                    **kwargs: Any,
                ) -> list[dict[str, Any]]:
                    return self._load(**kwargs, include_evidence=True)

            class LiveReranker:
                calls = 0

                def rerank_documents(
                    self,
                    query: str,
                    documents: list[str],
                    *,
                    alias: str,
                    top_n: int,
                    request_id: str,
                    trace_id: str,
                ) -> dict[str, Any]:
                    del request_id, trace_id
                    self.calls += 1
                    return execute_remote_rerank_request(
                        {
                            "alias": alias,
                            "query": query,
                            "documents": documents,
                            "top_n": top_n,
                        },
                        environ=dict(environ),
                        requester=rerank_requester,
                    )

            materializer = EvidenceMaterializer()
            reranker = LiveReranker()
            runtime = PermissionFilteredHybridPackageRuntime(
                candidate_provider=CandidateProvider(),
                evidence_materializer=materializer,
                rerank_client=reranker,
                reranker_alias=RERANKER_ALIAS,
            )
            app = build_service_app(SERVICE_SPECS[SERVICE_ID])
            register_retrieval_routes(
                app,
                store=store,
                hybrid_runtime=runtime,
            )
            response = TestClient(app).post(
                "/api/v1/retrieval/context",
                json={
                    "query_text": QUERY_TEXT,
                    "document_scope": {"document_ids": [document_id]},
                    "top_k": 3,
                    "purpose": "grounded_answer",
                },
                headers=_headers(request_id, trace_id),
            )
            package = response.json()
            api_observation = {
                "status_code": response.status_code,
                "error_code": package.get("error_code"),
            }
            retrieval_package_id = package.get("retrieval_package_id")
            persisted = _read_persisted_result(
                engine,
                retrieval_package_id=retrieval_package_id,
            )
            identity = _read_database_identity(engine)
            serialized = json.dumps(persisted, ensure_ascii=False, default=str)
            lexical_candidates = candidate_observation.get(
                "lexical_candidates", {}
            )
            vector_candidates = candidate_observation.get("vector_candidates", {})
            quality_policy = (
                package.get("retrieval_profile", {})
                .get("quality_policy", {})
            )
            checks.update(
                {
                    "test_database_connected": identity
                    == {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE},
                    "ingestion_lineage_persisted": (
                        persisted_chunk_set["content_object_id"] == document_id
                        and lexical_index["unique_token_count"] > 0
                    ),
                    "remote_embedding_completed": (
                        provider_evidence["response_count"]
                        == len(persisted_chunk_set["chunks"]) + 1
                    ),
                    "remote_embedding_dimension": (
                        provider_evidence["vector_dimension"] == VECTOR_DIMENSION
                        and provider_evidence["finite"]
                        and provider_evidence["non_zero"]
                    ),
                    "permission_first": candidate_observation.get(
                        "permission_enforced_before_candidates"
                    )
                    is True,
                    "owner_scope_exact": (
                        candidate_observation.get("permission_snapshot", {})
                        .get("scope_applied", {})
                        .get("document_ids")
                        == [document_id]
                    ),
                    "postgres_bm25_candidate": (
                        lexical_candidates.get("candidate_count", 0) >= 1
                    ),
                    "fresh_pgvector_candidate": (
                        vector_candidates.get("status") == "READY"
                        and vector_candidates.get("candidate_count", 0) >= 1
                    ),
                    "weighted_rrf_policy": (
                        quality_policy.get("vector_weight") == 0.7
                        and quality_policy.get("bm25_weight") == 0.3
                        and quality_policy.get("rrf_k") == 60
                    ),
                    "remote_rerank_applied": (
                        reranker.calls == 1
                        and package.get("score_summary", {}).get("rerank_state")
                        == "APPLIED"
                    ),
                    "canonical_api_ready": (
                        response.status_code == 200
                        and package.get("status") == "READY"
                    ),
                    "package_persisted": (
                        str(persisted.get("retrieval_package_id"))
                        == retrieval_package_id
                        and persisted.get("evidence_count", 0) >= 1
                    ),
                    "hash_only_persistence": (
                        persisted.get("query_text_preview") is None
                        and persisted.get("evidence_text_preview") is None
                        and persisted.get("query_text_sha256")
                        == _digest(QUERY_TEXT)
                        and bool(persisted.get("evidence_text_sha256"))
                    ),
                    "private_payload_absent": (
                        QUERY_TEXT not in serialized
                        and SOURCE_PREFIX not in serialized
                    ),
                    "primary_vector_route": vector_store.uses_primary_database,
                }
            )
    finally:
        _delete_fixture(
            engine,
            retrieval_package_id=retrieval_package_id,
            vector_index_id=vector_index_id,
            document_id=document_id,
            source_file_id=source_file_id,
        )
        checks["cleanup_complete"] = _cleanup_complete(
            engine,
            retrieval_package_id=retrieval_package_id,
            vector_index_id=vector_index_id,
            document_id=document_id,
            source_file_id=source_file_id,
        )
        engine.dispose()
    return {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "check_count": len(checks),
        "provider": {
            "embedding_model": build_remote_embedding_execution_config(
                dict(environ)
            ).model_name,
            "reranker_model": build_remote_reranker_execution_config(
                dict(environ)
            ).model_name,
            "vector_dimension": VECTOR_DIMENSION,
        },
        "retrieval": {
            "policy_id": "weighted_rrf_vector_bm25_v1",
            "permission_policy": "cx.private_owner_active.v1",
            "persistence_payload_policy": "hash_only_private_owner",
        },
        "api": api_observation,
    }


def _storage_config(  # pragma: no cover - protected PostgreSQL/live evidence
    root: Path,
) -> CxStorageConfig:
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


def _access_context(  # pragma: no cover - protected PostgreSQL/live evidence
    request_id: str,
    trace_id: str,
) -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id=TENANT_ID,
        subject_id=OWNER_ID,
        request_id=request_id,
        trace_id=trace_id,
        scopes=("service:call",),
    )


def _headers(  # pragma: no cover - protected PostgreSQL/live evidence
    request_id: str,
    trace_id: str,
) -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ae-api",
        audience=SERVICE_ID,
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-NEX-Tenant-ID": TENANT_ID,
        "X-NEX-Subject-ID": OWNER_ID,
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _read_database_identity(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
) -> dict[str, str]:
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT current_database() AS database, current_user AS role")
        ).mappings().one()
    return {"database": str(row["database"]), "role": str(row["role"])}


def _read_persisted_result(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    *,
    retrieval_package_id: object,
) -> dict[str, Any]:
    if not isinstance(retrieval_package_id, str):
        return {}
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT package.retrieval_package_id,
                       package.query_text_sha256,
                       package.query_text_preview,
                       package.evidence_count,
                       evidence.evidence_text_sha256,
                       evidence.evidence_text_preview
                FROM cx_retrieval_packages AS package
                LEFT JOIN cx_retrieval_evidence_items AS evidence
                  ON evidence.retrieval_package_id = package.retrieval_package_id
                WHERE package.retrieval_package_id = :retrieval_package_id
                ORDER BY evidence.rank ASC
                LIMIT 1
                """
            ),
            {"retrieval_package_id": retrieval_package_id},
        ).mappings().one_or_none()
    return dict(row) if row is not None else {}


def _delete_fixture(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    *,
    retrieval_package_id: str | None,
    vector_index_id: str | None,
    document_id: str | None,
    source_file_id: str | None,
) -> None:
    with engine.begin() as connection:
        if retrieval_package_id is not None:
            connection.execute(
                text(
                    "DELETE FROM cx_retrieval_packages "
                    "WHERE retrieval_package_id = :identifier"
                ),
                {"identifier": retrieval_package_id},
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


def _cleanup_complete(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    *,
    retrieval_package_id: str | None,
    vector_index_id: str | None,
    document_id: str | None,
    source_file_id: str | None,
) -> bool:
    identifiers = {
        "retrieval_package_id": retrieval_package_id,
        "vector_index_id": vector_index_id,
        "document_id": document_id,
        "source_file_id": source_file_id,
    }
    with engine.connect() as connection:
        checks = (
            ("cx_retrieval_packages", "retrieval_package_id"),
            ("cx_vector_indexes", "vector_index_id"),
            ("cx_content_objects", "document_id"),
            ("cx_source_files", "source_file_id"),
        )
        for table_name, key in checks:
            value = identifiers[key]
            if value is None:
                continue
            column = "content_object_id" if key == "document_id" else key
            count = connection.execute(
                text(
                    f"SELECT count(*) FROM {table_name} "
                    f"WHERE {column} = :identifier"
                ),
                {"identifier": value},
            ).scalar_one()
            if count != 0:
                return False
    return True


def assert_evidence_redacted(
    evidence: object,
    environ: Mapping[str, str],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    protected_values = [
        environ.get(key, "")
        for key in PROTECTED_ENV_KEYS
    ] + [QUERY_TEXT, SOURCE_PREFIX]
    if any(value and value in serialized for value in protected_values):
        raise ValueError("S95 live smoke evidence is not redacted.")


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and parsed.path.lstrip("/") == EXPECTED_DATABASE
    )


def _digest(value: str) -> str:  # pragma: no cover - protected live evidence
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _failure(code: str, detail: Any, **extra: Any) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "error": {"code": code, "detail": detail},
        **extra,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "skipped":
        return f"cx_permission_hybrid_live_postgres_smoke=skipped reason={SMOKE_ENV}"
    if status == "pass":
        return (
            "cx_permission_hybrid_live_postgres_smoke=pass "
            f"checks={result['check_count']}/{result['check_count']} "
            "database=nex_cx_test embedding=live reranker=live"
        )
    error = result.get("error", {})
    code = error.get("code", "unknown") if isinstance(error, Mapping) else "unknown"
    return f"cx_permission_hybrid_live_postgres_smoke=fail error={code}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_permission_hybrid_live_postgres_smoke()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
