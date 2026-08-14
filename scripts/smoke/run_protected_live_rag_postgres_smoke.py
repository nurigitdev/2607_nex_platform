#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
CX_PATH = ROOT / "services" / "nex-cx"
MO_PATH = ROOT / "services" / "nex-mo"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(CX_PATH))
sys.path.insert(0, str(MO_PATH))
sys.path.insert(0, str(SMOKE_PATH))

import nex_mo.remote_provider as remote_provider  # noqa: E402
from nex_cx.chunking import register_chunking_routes  # noqa: E402
from nex_cx.embedding_index import (  # noqa: E402
    DEFAULT_EMBEDDING_ALIAS,
    register_embedding_index_routes,
)
from nex_cx.generation import (  # noqa: E402
    GenerationExecutionStore,
    register_generation_routes,
)
from nex_cx.ingestion import ContentIngestionStore, register_ingestion_routes  # noqa: E402
from nex_cx.lexical_index import register_lexical_index_routes  # noqa: E402
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_cx.retrieval import (  # noqa: E402
    DEFAULT_RERANKER_ALIAS,
    DEFAULT_RETRIEVAL_QUALITY_POLICY,
    register_retrieval_routes,
)
from nex_mo.providers import register_mock_provider_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_cx_document_library_postgres_smoke import _migration_evidence  # noqa: E402
from run_cx_real_document_processing_pipeline_postgres_smoke import (  # noqa: E402
    _delete_real_document_processing_rows,
)
from run_cx_retrieval_postgres_smoke import _delete_smoke_retrieval_rows  # noqa: E402
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults  # noqa: E402
from run_protected_live_rag_smoke import (  # noqa: E402
    REQUEST_ID,
    SMOKE_TEXT,
    TRACE_ID,
    HttpRequester,
    InProcessLiveMoClient,
    assert_protected_live_rag_evidence_redacted,
    build_rag_evidence_summary,
    build_smoke_storage_config,
    create_grounded_generation,
    patched_environ,
    patched_remote_request,
    protected_live_rag_config_issues,
    read_provider_telemetry,
    register_smoke_document,
    run_cx_post,
    service_headers,
)


SMOKE_ENV = "NEX_PROTECTED_LIVE_RAG_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_PROTECTED_LIVE_RAG_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
SCHEMA_VERSION = "protected_live_rag_postgres_smoke.v1"
SCORE_CALIBRATION_SCHEMA_VERSION = "protected_live_rag_score_calibration.v1"
DB_SECRET_ENV_KEYS = (
    "NEX_CX_DATABASE_URL",
    "NEX_CX_TEST_DATABASE_URL",
)
FORBIDDEN_EVIDENCE_FRAGMENTS = (
    SMOKE_TEXT,
    "source_storage_path",
    "extracted_markdown_path",
    "nex-live-rag-postgres-smoke-",
    "/data/nex-platform",
)
EXECUTION_STAGES = (
    "database_engine",
    "service_apps",
    "upload",
    "extraction",
    "chunking",
    "lexical_index",
    "embedding_index",
    "retrieval",
    "score_calibration",
    "generation",
    "provider_telemetry",
    "rag_evidence_assertion",
    "db_observation",
    "checks",
    "redaction",
    "cleanup",
)


class LiveRagSmokeStageError(RuntimeError):
    def __init__(
        self,
        *,
        stage: str,
        error_code: str,
        detail: str,
        status_code: int | None = None,
        retryable: bool | None = None,
        stage_status: dict[str, str] | None = None,
    ) -> None:
        super().__init__(error_code)
        self.stage = stage
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        self.stage_status = stage_status or {}

    def to_safe_diagnostics(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "stage": self.stage,
            "error_code": self.error_code,
            "detail": _bounded_detail(self.detail),
            "stage_status": dict(self.stage_status),
        }
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        if self.retryable is not None:
            payload["retryable"] = self.retryable
        return payload


def run_protected_live_rag_postgres_smoke(
    environ: dict[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
    trace_id: str = TRACE_ID,
) -> dict[str, object]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != "test":
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
        )

    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
    }
    config_issues = protected_live_rag_config_issues(effective_env)
    if config_issues:
        return _failure(
            "configuration_invalid",
            ",".join(str(issue["error_code"]) for issue in config_issues),
            profile=profile,
            issues=config_issues,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        migration_result = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_protected_live_rag_postgres_smoke(
            database_env=database_env,
            database_url=database_url,
            runtime_environ={
                **effective_env,
                SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
            requester=requester,
            trace_id=trace_id,
        )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            "migration": _migration_evidence(migration_result),
            **execution,
        }
        assert_protected_live_rag_postgres_evidence_redacted(evidence, env)
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except LiveRagSmokeStageError as exc:
        failure = _failure(
            "execution_failed",
            exc.error_code,
            profile=profile,
            diagnostics=exc.to_safe_diagnostics(),
        )
        assert_protected_live_rag_postgres_evidence_redacted(failure, env)
        return failure
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_protected_live_rag_postgres_smoke(
    *,
    database_env: str,
    database_url: str,
    runtime_environ: dict[str, str],
    requester: HttpRequester | None = None,
    trace_id: str = TRACE_ID,
) -> dict[str, object]:
    request_id = REQUEST_ID
    stage_status = _initial_stage_status()
    engine = _run_stage(
        "database_engine",
        stage_status,
        lambda: build_engine(database_url),
    )
    document_id: str | None = None
    source_file_id: str | None = None
    retrieval_package_id: str | None = None
    result: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="nex-live-rag-postgres-smoke-") as temp_dir:
        storage_config = _run_stage(
            "service_apps",
            stage_status,
            lambda: build_smoke_storage_config(Path(temp_dir)),
        )
        repository = SqlAlchemyCxContentRepository(
            build_session_factory(engine),
            local_source_root=storage_config.source_root,
        )
        cx_store = ContentIngestionStore(content_repository=repository)
        generation_store = GenerationExecutionStore()
        mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
        register_mock_provider_routes(mo_app)
        mo_test_client = TestClient(mo_app)
        mo_client = InProcessLiveMoClient(mo_test_client)

        cx_app = build_service_app(SERVICE_SPEC)
        register_ingestion_routes(
            cx_app,
            store=cx_store,
            storage_config=storage_config,
            database_env=database_env,
            redacted_database_url=redact_database_url(database_url),
            source_kind="postgres-read",
        )
        register_chunking_routes(
            cx_app,
            store=cx_store,
            storage_config=storage_config,
        )
        register_lexical_index_routes(
            cx_app,
            store=cx_store,
            storage_config=storage_config,
        )
        register_embedding_index_routes(
            cx_app,
            store=cx_store,
            mo_client=mo_client,
            embedding_alias=DEFAULT_EMBEDDING_ALIAS,
        )
        register_retrieval_routes(
            cx_app,
            store=cx_store,
            rerank_client=mo_client,
            reranker_alias=DEFAULT_RERANKER_ALIAS,
        )
        register_generation_routes(
            cx_app,
            store=generation_store,
            mo_client=mo_client,
            retrieval_store=cx_store,
        )
        cx_client = TestClient(cx_app)

        try:
            with patched_environ(runtime_environ):
                with patched_remote_request(requester):
                    remote_provider.reset_remote_provider_telemetry()
                    upload = _run_stage(
                        "upload",
                        stage_status,
                        lambda: register_smoke_document(
                            cx_client,
                            trace_id,
                            request_id,
                        ),
                    )
                    document_id = str(upload["document_id"])
                    refs = cx_store.get_content_ref(document_id)
                    source_file_id = (
                        str(refs["source_file_id"]) if refs is not None else None
                    )
                    extraction = _run_stage(
                        "extraction",
                        stage_status,
                        lambda: run_cx_post(
                            cx_client,
                            f"/api/v1/jobs/{upload['extraction']['job_id']}/run",
                            trace_id,
                            request_id,
                        ),
                    )
                    chunk_set = _run_stage(
                        "chunking",
                        stage_status,
                        lambda: run_cx_post(
                            cx_client,
                            f"/api/v1/documents/{document_id}/chunks/run",
                            trace_id,
                            request_id,
                        ),
                    )
                    lexical_index = _run_stage(
                        "lexical_index",
                        stage_status,
                        lambda: run_cx_post(
                            cx_client,
                            f"/api/v1/documents/{document_id}/lexical-index/run",
                            trace_id,
                            request_id,
                        ),
                    )
                    embedding_index = _run_stage(
                        "embedding_index",
                        stage_status,
                        lambda: run_cx_post(
                            cx_client,
                            f"/api/v1/documents/{document_id}/embeddings/run",
                            trace_id,
                            request_id,
                        ),
                    )
                    retrieval = _run_stage(
                        "retrieval",
                        stage_status,
                        lambda: create_live_rag_postgres_retrieval_context(
                            cx_client,
                            document_id=document_id,
                            trace_id=trace_id,
                            request_id=request_id,
                        ),
                    )
                    retrieval_package_id = str(retrieval["retrieval_package_id"])
                    score_calibration = _run_stage(
                        "score_calibration",
                        stage_status,
                        lambda: build_score_calibration_checkpoint(retrieval),
                    )
                    generation = _run_stage(
                        "generation",
                        stage_status,
                        lambda: create_grounded_generation(
                            cx_client,
                            retrieval_package=retrieval,
                            trace_id=trace_id,
                            request_id=request_id,
                        ),
                    )
                    telemetry = _run_stage(
                        "provider_telemetry",
                        stage_status,
                        lambda: read_provider_telemetry(
                            mo_test_client,
                            trace_id,
                            request_id,
                        ),
                    )
            rag_evidence = _run_stage(
                "rag_evidence_assertion",
                stage_status,
                lambda: build_rag_evidence_summary(
                    trace_id=trace_id,
                    request_id=request_id,
                    upload=upload,
                    extraction=extraction,
                    chunk_set=chunk_set,
                    lexical_index=lexical_index,
                    embedding_index=embedding_index,
                    retrieval=retrieval,
                    generation=generation,
                    telemetry=telemetry,
                ),
            )
            db_observations = _run_stage(
                "db_observation",
                stage_status,
                lambda: _read_live_rag_db_observations(
                    engine,
                    document_id=document_id,
                    source_file_id=source_file_id,
                    retrieval_package_id=retrieval_package_id,
                ),
            )
            checks = _run_stage(
                "checks",
                stage_status,
                lambda: _checks(
                    rag_evidence=rag_evidence,
                    db_observations=db_observations,
                    score_calibration=score_calibration,
                ),
            )
            if not all(checks.values()):
                stage_status["checks"] = "FAIL"
                raise LiveRagSmokeStageError(
                    stage="checks",
                    error_code="protected_live_rag_postgres_checks_failed",
                    detail="Protected live RAG PostgreSQL smoke checks failed.",
                    stage_status=stage_status,
                )
            result = {
                "stage_status": stage_status,
                "rag_evidence": rag_evidence,
                "score_calibration": score_calibration,
                "db_observations": db_observations,
                "checks": checks,
            }
            _run_stage(
                "redaction",
                stage_status,
                lambda: assert_protected_live_rag_postgres_evidence_redacted(
                    result,
                    runtime_environ,
                ),
            )
        finally:
            result["cleanup_observations"] = _run_stage(
                "cleanup",
                stage_status,
                lambda: _cleanup_live_rag_rows(
                    engine=engine,
                    retrieval_package_id=retrieval_package_id,
                    document_id=document_id,
                    source_file_id=source_file_id,
                ),
            )
    return result


def _cleanup_live_rag_rows(
    *,
    engine: object,
    retrieval_package_id: str | None,
    document_id: str | None,
    source_file_id: str | None,
) -> dict[str, object]:
    _delete_smoke_retrieval_rows(
        engine,
        retrieval_package_id=retrieval_package_id,
        document_id=None,
        source_file_id=None,
    )
    return _delete_real_document_processing_rows(
        engine,
        document_id=document_id,
        source_file_id=source_file_id,
        pipeline_run_id=None,
        job_id=None,
    )


def _initial_stage_status() -> dict[str, str]:
    return {stage: "NOT_RUN" for stage in EXECUTION_STAGES}


def _run_stage(
    stage: str,
    stage_status: dict[str, str],
    operation: Callable[[], Any],
) -> Any:
    try:
        result = operation()
    except LiveRagSmokeStageError:
        stage_status[stage] = "FAIL"
        raise
    except Exception as exc:
        stage_status[stage] = "FAIL"
        raise _stage_failure_from_exception(
            stage,
            exc,
            stage_status=stage_status,
        ) from exc
    stage_status[stage] = "PASS"
    return result


def _stage_failure_from_exception(
    stage: str,
    exc: Exception,
    *,
    stage_status: dict[str, str],
) -> LiveRagSmokeStageError:
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        problem = _safe_problem_payload(response)
        return LiveRagSmokeStageError(
            stage=stage,
            error_code=str(problem.get("error_code") or f"http_status_{response.status_code}"),
            detail=str(problem.get("detail") or exc.__class__.__name__),
            status_code=response.status_code,
            retryable=_optional_bool(problem.get("retryable")),
            stage_status=stage_status,
        )
    error_code = getattr(exc, "error_code", None)
    detail = getattr(exc, "detail", None)
    status_code = getattr(exc, "status_code", None)
    retryable = getattr(exc, "retryable", None)
    return LiveRagSmokeStageError(
        stage=stage,
        error_code=str(error_code or exc.__class__.__name__),
        detail=str(detail or exc.__class__.__name__),
        status_code=status_code if isinstance(status_code, int) else None,
        retryable=retryable if isinstance(retryable, bool) else None,
        stage_status=stage_status,
    )


def _safe_problem_payload(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _bounded_detail(value: object, *, limit: int = 240) -> str:
    detail = " ".join(str(value).split())
    if len(detail) <= limit:
        return detail
    return detail[: limit - 3] + "..."


def create_live_rag_postgres_retrieval_context(
    client: TestClient,
    *,
    document_id: str,
    trace_id: str,
    request_id: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/retrieval/context",
        json={
            "trace_id": trace_id,
            "query_text": "protected live RAG smoke evidence",
            "purpose": "grounded_answer",
            "document_scope": {"document_ids": [document_id]},
            "top_k": 1,
            "include_source_preview": True,
            "retrieval_policy": {
                "rerank_candidate_limit": 5,
                "low_confidence_threshold": 0.0,
            },
        },
        headers=service_headers("nex-ae-api", "nex-cx", trace_id, request_id),
    )
    response.raise_for_status()
    return response.json()


def build_score_calibration_checkpoint(
    retrieval: dict[str, Any],
    *,
    default_low_confidence_threshold: float | None = None,
) -> dict[str, object]:
    score_summary = retrieval.get("score_summary")
    if not isinstance(score_summary, dict):
        score_summary = {}
    evidence_items = retrieval.get("evidence_items")
    evidence_count = len(evidence_items) if isinstance(evidence_items, list) else 0
    best_score = _safe_float(score_summary.get("best_score"), default=0.0)
    observed_threshold = _safe_float(
        score_summary.get("low_confidence_threshold"),
        default=DEFAULT_RETRIEVAL_QUALITY_POLICY.low_confidence_threshold,
    )
    default_threshold = _safe_float(
        default_low_confidence_threshold,
        default=DEFAULT_RETRIEVAL_QUALITY_POLICY.low_confidence_threshold,
    )
    observed_bucket = _safe_string(
        score_summary.get("confidence_bucket"),
        default=_confidence_bucket(
            evidence_count=evidence_count,
            best_score=best_score,
            threshold=observed_threshold,
        ),
    )
    default_bucket = _confidence_bucket(
        evidence_count=evidence_count,
        best_score=best_score,
        threshold=default_threshold,
    )
    override_used = not _float_values_match(observed_threshold, default_threshold)
    override_direction = _threshold_override_direction(
        observed_threshold,
        default_threshold,
    )
    return {
        "checkpoint_schema_version": SCORE_CALIBRATION_SCHEMA_VERSION,
        "quality_policy_id": _safe_string(
            score_summary.get("quality_policy_id"),
            default=DEFAULT_RETRIEVAL_QUALITY_POLICY.policy_id,
        ),
        "ranker_mix": _safe_string(score_summary.get("ranker_mix")),
        "rerank_state": _safe_string(score_summary.get("rerank_state")),
        "observed_status": _safe_string(retrieval.get("status")),
        "observed_confidence_bucket": observed_bucket,
        "default_confidence_bucket": default_bucket,
        "best_score": best_score,
        "evidence_count": evidence_count,
        "observed_low_confidence_threshold": observed_threshold,
        "default_low_confidence_threshold": default_threshold,
        "threshold_override_used": override_used,
        "threshold_override_direction": override_direction,
        "would_pass_default_threshold": default_bucket == "READY",
        "score_margin_to_observed_threshold": round(best_score - observed_threshold, 6),
        "score_margin_to_default_threshold": round(best_score - default_threshold, 6),
        "calibration_action": _calibration_action(
            observed_bucket=observed_bucket,
            default_bucket=default_bucket,
            override_used=override_used,
            override_direction=override_direction,
        ),
    }


def _confidence_bucket(
    *,
    evidence_count: int,
    best_score: float,
    threshold: float,
) -> str:
    if evidence_count <= 0:
        return "NO_ANSWER"
    if best_score < threshold:
        return "LOW_CONFIDENCE"
    return "READY"


def _threshold_override_direction(
    observed_threshold: float,
    default_threshold: float,
) -> str:
    if _float_values_match(observed_threshold, default_threshold):
        return "none"
    if observed_threshold < default_threshold:
        return "lowered"
    return "raised"


def _calibration_action(
    *,
    observed_bucket: str,
    default_bucket: str,
    override_used: bool,
    override_direction: str,
) -> str:
    if default_bucket == "NO_ANSWER":
        return "inspect_no_answer_retrieval"
    if override_used and override_direction == "lowered" and default_bucket != "READY":
        return "review_live_threshold_before_canonical_policy"
    if observed_bucket != default_bucket:
        return "compare_observed_and_default_confidence"
    if default_bucket == "READY":
        return "default_threshold_accepts_score"
    return "review_low_confidence_boundary"


def _safe_float(value: object, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return default


def _safe_string(value: object, *, default: str = "UNKNOWN") -> str:
    if isinstance(value, str) and value:
        return value
    return default


def _float_values_match(left: float, right: float) -> bool:
    return abs(left - right) < 0.000001


def _read_live_rag_db_observations(
    engine: object,
    *,
    document_id: str | None,
    source_file_id: str | None,
    retrieval_package_id: str | None,
) -> dict[str, object]:
    if document_id is None or source_file_id is None or retrieval_package_id is None:
        raise RuntimeError("Protected live RAG PostgreSQL smoke lineage is incomplete")
    with engine.begin() as connection:
        content_count = _count_where(
            connection,
            "cx_content_objects",
            "content_object_id = :document_id",
            {"document_id": document_id},
        )
        source_file_count = _count_where(
            connection,
            "cx_source_files",
            "source_file_id = :source_file_id",
            {"source_file_id": source_file_id},
        )
        extraction_artifact_count = _count_where(
            connection,
            "cx_extraction_artifacts",
            "content_object_id = :document_id",
            {"document_id": document_id},
        )
        chunk_set_count = _count_where(
            connection,
            "cx_chunk_sets",
            "content_object_id = :document_id",
            {"document_id": document_id},
        )
        chunk_count = _count_where(
            connection,
            "cx_chunks",
            "content_object_id = :document_id",
            {"document_id": document_id},
        )
        lexical_term_count = int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM cx_lexical_terms
                    WHERE chunk_set_id IN (
                        SELECT chunk_set_id
                        FROM cx_chunk_sets
                        WHERE content_object_id = :document_id
                    )
                    """
                ),
                {"document_id": document_id},
            ).scalar_one()
        )
        lexical_posting_count = int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM cx_lexical_postings
                    WHERE lexical_term_id IN (
                        SELECT lexical_term_id
                        FROM cx_lexical_terms
                        WHERE chunk_set_id IN (
                            SELECT chunk_set_id
                            FROM cx_chunk_sets
                            WHERE content_object_id = :document_id
                        )
                    )
                    """
                ),
                {"document_id": document_id},
            ).scalar_one()
        )
        chunk_embedding_row = connection.execute(
            text(
                """
                SELECT count(*) AS embedding_count,
                       COALESCE(min(embedding.vector_dimension), 0) AS min_dimension,
                       COALESCE(max(embedding.vector_dimension), 0) AS max_dimension
                FROM cx_chunk_embeddings AS embedding
                JOIN cx_chunks AS chunk ON chunk.chunk_id = embedding.chunk_id
                WHERE chunk.content_object_id = :document_id
                """
            ),
            {"document_id": document_id},
        ).mappings().one()
        retrieval_row = connection.execute(
            text(
                """
                SELECT
                    package.status,
                    package.rerank_state,
                    package.ranker_mix,
                    package.evidence_count,
                    count(evidence.evidence_id) AS stored_evidence_count,
                    COALESCE(max(evidence.final_score), 0) AS max_final_score
                FROM cx_retrieval_packages AS package
                LEFT JOIN cx_retrieval_evidence_items AS evidence
                  ON evidence.retrieval_package_id = package.retrieval_package_id
                WHERE package.retrieval_package_id = :retrieval_package_id
                GROUP BY
                    package.retrieval_package_id,
                    package.status,
                    package.rerank_state,
                    package.ranker_mix,
                    package.evidence_count
                """
            ),
            {"retrieval_package_id": retrieval_package_id},
        ).mappings().first()
    if retrieval_row is None:
        raise RuntimeError("Protected live RAG retrieval package was not persisted")
    return {
        "content_object_count": content_count,
        "source_file_count": source_file_count,
        "extraction_artifact_count": extraction_artifact_count,
        "chunk_set_count": chunk_set_count,
        "chunk_count": chunk_count,
        "lexical_term_count": lexical_term_count,
        "lexical_posting_count": lexical_posting_count,
        "chunk_embedding_count": int(chunk_embedding_row["embedding_count"]),
        "chunk_embedding_min_dimension": int(chunk_embedding_row["min_dimension"]),
        "chunk_embedding_max_dimension": int(chunk_embedding_row["max_dimension"]),
        "retrieval_package_count": 1,
        "retrieval_status": retrieval_row["status"],
        "retrieval_rerank_state": retrieval_row["rerank_state"],
        "retrieval_ranker_mix": retrieval_row["ranker_mix"],
        "retrieval_evidence_count": int(retrieval_row["evidence_count"]),
        "retrieval_stored_evidence_count": int(
            retrieval_row["stored_evidence_count"]
        ),
        "retrieval_max_final_score": float(retrieval_row["max_final_score"] or 0.0),
    }


def _checks(
    *,
    rag_evidence: dict[str, Any],
    db_observations: dict[str, object],
    score_calibration: dict[str, object],
) -> dict[str, bool]:
    telemetry_by_capability = {
        item["capability"]: item for item in rag_evidence["provider_telemetry"]["data"]
    }
    expected_embedding_dimension = int(
        rag_evidence["document"]["embedding_dimension"]
    )
    expected_chunk_count = int(rag_evidence["document"]["chunk_count"])
    expected_evidence_count = int(rag_evidence["retrieval"]["evidence_count"])
    return {
        "source_file_persisted": db_observations["source_file_count"] == 1,
        "content_object_persisted": db_observations["content_object_count"] == 1,
        "extraction_artifact_persisted": (
            db_observations["extraction_artifact_count"] == 1
        ),
        "chunk_set_persisted": db_observations["chunk_set_count"] == 1,
        "chunks_persisted": (
            db_observations["chunk_count"] == expected_chunk_count
            and expected_chunk_count > 0
        ),
        "lexical_index_persisted": (
            int(db_observations["lexical_term_count"]) > 0
            and int(db_observations["lexical_posting_count"]) > 0
        ),
        "chunk_embeddings_persisted": (
            db_observations["chunk_embedding_count"] == expected_chunk_count
        ),
        "embedding_dimension_persisted": (
            db_observations["chunk_embedding_min_dimension"]
            == expected_embedding_dimension
            == db_observations["chunk_embedding_max_dimension"]
        ),
        "retrieval_package_persisted": (
            db_observations["retrieval_package_count"] == 1
        ),
        "retrieval_ready_persisted": db_observations["retrieval_status"] == "READY",
        "retrieval_evidence_persisted": (
            db_observations["retrieval_evidence_count"] == expected_evidence_count
            and db_observations["retrieval_stored_evidence_count"]
            == expected_evidence_count
        ),
        "rerank_applied_persisted": (
            db_observations["retrieval_rerank_state"] == "APPLIED"
        ),
        "retrieval_score_persisted": (
            float(db_observations["retrieval_max_final_score"]) > 0
        ),
        "score_calibration_recorded": (
            score_calibration.get("checkpoint_schema_version")
            == SCORE_CALIBRATION_SCHEMA_VERSION
            and score_calibration.get("observed_status")
            == rag_evidence["retrieval"]["status"]
        ),
        "grounded_generation_completed": (
            rag_evidence["generation"]["status"] == "COMPLETED"
        ),
        "embedding_live_call_observed": (
            telemetry_by_capability["embedding"]["success_count"] >= 1
        ),
        "rerank_live_call_observed": (
            telemetry_by_capability["reranking"]["success_count"] >= 1
        ),
        "generation_live_call_observed": (
            telemetry_by_capability["generation"]["success_count"] >= 1
        ),
    }


def _count_where(
    connection: Any,
    table: str,
    where_clause: str,
    params: dict[str, object],
) -> int:
    return int(
        connection.execute(
            text(f"SELECT count(*) FROM {table} WHERE {where_clause}"),
            params,
        ).scalar_one()
    )


def assert_protected_live_rag_postgres_evidence_redacted(
    evidence: object,
    env: dict[str, str],
) -> None:
    serialized = json.dumps(evidence, default=str, ensure_ascii=False, sort_keys=True)
    assert_protected_live_rag_evidence_redacted(serialized, env)
    for key in DB_SECRET_ENV_KEYS:
        value = env.get(key)
        if _database_secret_leaked(serialized, value):
            raise ValueError(
                "Protected live RAG PostgreSQL smoke evidence contains an "
                f"unredacted database secret: {key}"
            )
    for fragment in FORBIDDEN_EVIDENCE_FRAGMENTS:
        if fragment in serialized:
            raise ValueError(
                "Protected live RAG PostgreSQL smoke evidence contains raw "
                "source text or local storage paths."
            )


def _database_secret_leaked(
    serialized_evidence: str,
    database_url: str | None,
) -> bool:
    password = _database_password(database_url)
    return bool(password) and len(password) >= 4 and password in serialized_evidence


def _database_password(database_url: str | None) -> str | None:
    if not database_url or "@" not in database_url:
        return None
    authority = database_url.split("@", maxsplit=1)[0]
    if "://" in authority:
        authority = authority.split("://", maxsplit=1)[1]
    if ":" not in authority:
        return None
    password = authority.rsplit(":", maxsplit=1)[1]
    return password or None


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    issues: list[dict[str, object]] | None = None,
    diagnostics: dict[str, object] | None = None,
) -> dict[str, object]:
    failure = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }
    if issues is not None:
        failure["issues"] = issues
    if diagnostics is not None:
        failure["diagnostics"] = diagnostics
    return failure


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"protected_live_rag_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        rag = evidence["rag_evidence"]
        db_observations = evidence["db_observations"]
        return (
            "protected_live_rag_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"profile={evidence['profile']} "
            f"db_env={evidence['database_env']} "
            f"retrieval={rag['retrieval']['status']} "
            f"rerank={rag['retrieval']['rerank_state']} "
            f"generation={rag['generation']['status']} "
            f"embedding_dim={db_observations['chunk_embedding_max_dimension']}"
        )
    return (
        "protected_live_rag_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"profile={evidence.get('profile')} "
        f"reason={evidence.get('failure_code')} "
        f"stage={_summary_failure_stage(evidence)}"
    )


def _summary_failure_stage(evidence: dict[str, object]) -> str:
    diagnostics = evidence.get("diagnostics")
    if isinstance(diagnostics, dict):
        stage = diagnostics.get("stage")
        if isinstance(stage, str) and stage:
            return stage
    return "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run protected live RAG through CX PostgreSQL persistence."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_env_file(ROOT / ".env")
    args = build_parser().parse_args(argv)
    evidence = run_protected_live_rag_postgres_smoke()
    if args.output:
        serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{serialized}\n", encoding="utf-8")
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
