#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
CX_PATH = ROOT / "services" / "nex-cx"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(CX_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_cx.ingestion import (  # noqa: E402
    UPLOAD_OWNER_RESOLVER_DISABLED,
    ContentIngestionStore,
    register_ingestion_routes,
)
from nex_cx.processing import PIPELINE_STEPS, register_processing_routes  # noqa: E402
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_runtime import (  # noqa: E402
    OperationalEventEmitResult,
    SERVICE_SPECS,
    WorkerHeartbeatEmitResult,
    attach_service_persistence_runtime,
    build_engine,
    build_service_app,
    load_env_file,
    redact_database_url,
)
from run_cx_document_library_postgres_smoke import _migration_evidence  # noqa: E402
from run_cx_extractor_backend_gap_audit import (  # noqa: E402
    sample_docx_bytes,
    sample_pdf_bytes,
    sample_pptx_bytes,
    sample_xlsx_bytes,
)
from run_cx_upload_ownership_postgres_smoke import (  # noqa: E402
    _redaction_safe,
    _service_headers,
    _storage_config,
)
from run_cx_uploaded_source_extraction_postgres_smoke import (  # noqa: E402
    _read_source_file_observation,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SMOKE_ENV = "NEX_CX_REAL_DOCUMENT_PROCESSING_PIPELINE_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_CX_REAL_DOCUMENT_PROCESSING_PIPELINE_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
SCHEMA_VERSION = "cx_real_document_processing_pipeline_postgres_smoke.v1"
SECRET_MARKER_PREFIX = "CX real document processing pipeline PostgreSQL smoke marker"
EMBEDDING_ALIAS = "smoke-real-document-processing"


REAL_DOCUMENT_FORMATS: tuple[dict[str, object], ...] = (
    {
        "source_format": "pdf",
        "filename": "cx-real-document-processing-smoke.pdf",
        "content_type": "application/pdf",
        "expected_mode": "pdf_to_markdown",
        "bytes_factory": sample_pdf_bytes,
    },
    {
        "source_format": "docx",
        "filename": "cx-real-document-processing-smoke.docx",
        "content_type": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        "expected_mode": "docx_to_markdown",
        "bytes_factory": sample_docx_bytes,
    },
    {
        "source_format": "pptx",
        "filename": "cx-real-document-processing-smoke.pptx",
        "content_type": (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
        "expected_mode": "pptx_to_markdown",
        "bytes_factory": sample_pptx_bytes,
    },
    {
        "source_format": "xlsx",
        "filename": "cx-real-document-processing-smoke.xlsx",
        "content_type": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        "expected_mode": "xlsx_to_markdown",
        "bytes_factory": sample_xlsx_bytes,
    },
)


class StaticMoEmbeddingClient:
    def create_embeddings(
        self,
        inputs: list[str],
        *,
        alias: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, object]:
        return {
            "object": "list",
            "alias": alias,
            "model_revision": "smoke-real-document-processing-embedding-v1",
            "deployment_id": "cx-real-document-processing-pipeline-smoke",
            "data": [
                {
                    "object": "embedding",
                    "index": index,
                    "embedding": [0.1, 0.2, 0.3, float(index + 1)],
                }
                for index, _ in enumerate(inputs)
            ],
            "usage": {
                "input_tokens": len(inputs),
                "output_tokens": 0,
                "total_tokens": len(inputs),
            },
        }


class NoopOperationalEventEmitter:
    def safe_emit(self, **_: object) -> OperationalEventEmitResult:
        return OperationalEventEmitResult(ok=True)


class NoopWorkerHeartbeatEmitter:
    def safe_emit(self, **_: object) -> WorkerHeartbeatEmitResult:
        return WorkerHeartbeatEmitResult(ok=True)


def run_cx_real_document_processing_pipeline_postgres_smoke(
    environ: dict[str, str] | None = None,
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

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        migration_result = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_real_document_processing_pipeline_smoke(
            database_env=database_env,
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
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
        assert_evidence_redacted(evidence)
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_real_document_processing_pipeline_smoke(
    *,
    database_env: str,
    database_url: str,
    runtime_environ: dict[str, str],
) -> dict[str, object]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.split("-", maxsplit=1)[0]
    tenant_id = f"tenant-real-document-processing-{suffix}"
    owner_user_id = f"owner-real-document-processing-{suffix}"
    engine = build_engine(database_url)
    tracked_rows: list[dict[str, str | None]] = []
    result: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="nex-cx-real-document-processing-smoke-") as temp_dir:
        storage_config = _storage_config(Path(temp_dir))
        app = build_service_app(SERVICE_SPEC)
        persistence = attach_service_persistence_runtime(
            app,
            SERVICE_SPEC,
            environ=runtime_environ,
        )
        if persistence.api_session_factory is None:
            raise RuntimeError(
                "CX PostgreSQL real-document processing smoke session factory is unavailable"
            )

        repository = SqlAlchemyCxContentRepository(
            persistence.api_session_factory,
            local_source_root=storage_config.source_root,
        )
        store = ContentIngestionStore(content_repository=repository)
        register_ingestion_routes(
            app,
            store=store,
            storage_config=storage_config,
            owner_resolver_mode=UPLOAD_OWNER_RESOLVER_DISABLED,
            database_env=database_env,
            redacted_database_url=redact_database_url(database_url),
            source_kind="postgres-read",
        )
        register_processing_routes(
            app,
            store=store,
            storage_config=storage_config,
            mo_client=StaticMoEmbeddingClient(),
            embedding_alias=EMBEDDING_ALIAS,
            job_queue=persistence.job_queue,
            event_emitter=NoopOperationalEventEmitter(),
            worker_heartbeat_emitter=NoopWorkerHeartbeatEmitter(),
            processing_run_repository=repository,
        )
        client = TestClient(app)
        try:
            observations = [
                _run_one_format_pipeline_smoke(
                    spec=spec,
                    client=client,
                    store=store,
                    engine=engine,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    trace_id=trace_id,
                    request_id=request_id,
                    tracked_rows=tracked_rows,
                )
                for spec in REAL_DOCUMENT_FORMATS
            ]
            evidence_payload = {"observations": observations}
            checks = {
                "runtime_mode": persistence.mode == "postgres",
                "format_count": len(observations) == len(REAL_DOCUMENT_FORMATS),
                "all_uploads_created": all(
                    item["upload_status"] == "CREATED" for item in observations
                ),
                "all_runtime_source_bytes_evicted": all(
                    item["runtime_source_bytes_evicted"] is True
                    for item in observations
                ),
                "all_processing_runs_succeeded": all(
                    item["processing_status"] == "SUCCEEDED" for item in observations
                ),
                "all_pipeline_steps_succeeded": all(
                    item["step_summary"] == {
                        "total": len(PIPELINE_STEPS),
                        "succeeded": len(PIPELINE_STEPS),
                        "skipped": 0,
                        "failed": 0,
                    }
                    for item in observations
                ),
                "all_extractions_used_materialized_source": all(
                    item["source_reader"] == "materialized_local_source_file"
                    and item["fallback_used"] is True
                    for item in observations
                ),
                "all_expected_extractors_used": all(
                    item["expected_mode_used"] is True for item in observations
                ),
                "all_normalization_valid": all(
                    item["normalization_contract_status"] == "valid"
                    for item in observations
                ),
                "all_private_markers_seen": all(
                    item["private_marker_seen"] is True for item in observations
                ),
                "all_db_pipeline_records_persisted": all(
                    all(item["db_checks"].values()) for item in observations
                ),
                "evidence_redacted": _redaction_safe(
                    evidence_payload,
                    forbidden_fragments=[
                        SECRET_MARKER_PREFIX,
                        str(storage_config.source_root),
                        str(storage_config.extracted_markdown_root),
                        "source_storage_path",
                        "extracted_markdown_path",
                    ],
                ),
            }
            if not all(checks.values()):
                raise RuntimeError(
                    "CX real-document processing pipeline PostgreSQL smoke checks failed"
                )
            result = {
                "format_count": len(observations),
                "formats": [
                    {
                        "source_format": item["source_format"],
                        "extractor_mode": item["extractor_mode"],
                        "pipeline_run_id": item["pipeline_run_id"],
                        "chunk_count": item["db_observations"]["chunk_count"],
                        "lexical_term_count": item["db_observations"][
                            "lexical_term_count"
                        ],
                        "summary_char_count": item["db_observations"][
                            "summary_char_count"
                        ],
                    }
                    for item in observations
                ],
                "db_observations": _aggregate_db_observations(observations),
                "checks": checks,
            }
        finally:
            result["cleanup_observations"] = [
                _delete_real_document_processing_rows(
                    engine,
                    document_id=item["document_id"],
                    source_file_id=item["source_file_id"],
                    pipeline_run_id=item["pipeline_run_id"],
                    job_id=item["job_id"],
                )
                for item in tracked_rows
            ]
    return result


def _run_one_format_pipeline_smoke(
    *,
    spec: dict[str, object],
    client: TestClient,
    store: ContentIngestionStore,
    engine: object,
    tenant_id: str,
    owner_user_id: str,
    trace_id: str,
    request_id: str,
    tracked_rows: list[dict[str, str | None]],
) -> dict[str, object]:
    source_format = str(spec["source_format"])
    marker = f"{SECRET_MARKER_PREFIX}: {source_format} request={request_id}"
    bytes_factory = spec["bytes_factory"]
    source_bytes = bytes_factory(marker) if callable(bytes_factory) else b""
    upload_response = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": spec["filename"],
            "content_type": spec["content_type"],
            "content_base64": base64.b64encode(source_bytes).decode("ascii"),
            "tenant_id": tenant_id,
            "owner_user_id": f"{owner_user_id}-{source_format}",
        },
        headers=_service_headers(trace_id=trace_id, request_id=str(uuid4())),
    )
    upload_response.raise_for_status()
    upload = upload_response.json()
    document_id = str(upload["document_id"])
    upload_id = str(upload["upload_id"])
    refs = store.get_content_ref(document_id)
    source_file_id = refs["source_file_id"] if refs is not None else None
    tracked = {
        "document_id": document_id,
        "source_file_id": source_file_id,
        "pipeline_run_id": None,
        "job_id": None,
    }
    tracked_rows.append(tracked)
    store.source_bytes.pop(upload_id, None)
    store.source_texts.pop(upload_id, None)

    processing_response = client.post(
        f"/api/v1/documents/{document_id}/processing/run",
        headers=_service_headers(trace_id=trace_id, request_id=str(uuid4())),
    )
    processing_response.raise_for_status()
    pipeline_run = processing_response.json()
    pipeline_run_id = str(pipeline_run["pipeline_run_id"])
    job_id = str(pipeline_run["job"]["job_id"])
    tracked["pipeline_run_id"] = pipeline_run_id
    tracked["job_id"] = job_id

    extraction = store.get_extraction_result(document_id)
    if extraction is None:
        raise RuntimeError("real document pipeline smoke extraction result missing")
    markdown_text = Path(extraction["extracted_markdown_path"]).read_text(
        encoding="utf-8"
    )
    db_observation = _read_pipeline_db_observation(
        engine,
        document_id=document_id,
        pipeline_run_id=pipeline_run_id,
        job_id=job_id,
    )
    source_observation = _read_source_file_observation(
        engine,
        source_file_id=source_file_id,
    )
    source_reader = extraction["source_reader"]
    normalization = extraction["extracted_markdown_normalization"]
    db_checks = {
        "source_checksum_verified": source_observation["checksum_verified"] is True,
        "extraction_artifact_persisted": db_observation["extraction_artifact_count"]
        == 1,
        "chunk_set_persisted": db_observation["chunk_set_count"] == 1,
        "chunks_persisted": db_observation["chunk_count"] >= 1,
        "lexical_terms_persisted": db_observation["lexical_term_count"] >= 1,
        "lexical_postings_persisted": db_observation["lexical_posting_count"] >= 1,
        "chunk_embeddings_match_chunks": db_observation["chunk_embedding_count"]
        == db_observation["chunk_count"],
        "document_summary_persisted": db_observation["document_summary_count"] == 1,
        "summary_embedding_persisted": db_observation["summary_embedding_count"] == 1,
        "processing_run_persisted": db_observation["processing_run_count"] == 1,
        "processing_steps_persisted": db_observation["processing_step_count"]
        == len(PIPELINE_STEPS),
        "service_job_completed": db_observation["service_job_status"] == "SUCCEEDED",
    }
    return {
        "source_format": source_format,
        "upload_status": upload["dedupe"]["status"],
        "runtime_source_bytes_evicted": not store.source_bytes_available(upload_id),
        "processing_status": pipeline_run["status"],
        "pipeline_run_id": pipeline_run_id,
        "job_id": job_id,
        "step_summary": dict(pipeline_run["step_summary"]),
        "source_reader": source_reader["source"],
        "fallback_used": source_reader["fallback_used"],
        "extractor_mode": extraction["extractor"]["mode"],
        "expected_mode_used": extraction["extractor"]["mode"] == spec["expected_mode"],
        "normalization_contract_status": normalization["contract_status"],
        "private_marker_seen": marker in markdown_text,
        "db_observations": db_observation,
        "db_checks": db_checks,
    }


def _read_pipeline_db_observation(
    engine: object,
    *,
    document_id: str,
    pipeline_run_id: str,
    job_id: str,
) -> dict[str, object]:
    with engine.begin() as connection:
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
        summary_row = connection.execute(
            text(
                """
                SELECT count(*) AS summary_count,
                       COALESCE(max(summary_char_count), 0) AS summary_char_count
                FROM cx_document_summaries
                WHERE content_object_id = :document_id
                """
            ),
            {"document_id": document_id},
        ).mappings().one()
        summary_embedding_count = int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM cx_document_summary_embeddings AS embedding
                    JOIN cx_document_summaries AS summary
                      ON summary.document_summary_id = embedding.document_summary_id
                    WHERE summary.content_object_id = :document_id
                    """
                ),
                {"document_id": document_id},
            ).scalar_one()
        )
        processing_row = connection.execute(
            text(
                """
                SELECT count(*) AS run_count,
                       COALESCE(max(status), '') AS run_status,
                       COALESCE(max(job_status), '') AS job_status,
                       COALESCE(max(step_total), 0) AS step_total,
                       COALESCE(max(step_succeeded), 0) AS step_succeeded,
                       COALESCE(max(step_failed), 0) AS step_failed
                FROM cx_document_processing_runs
                WHERE pipeline_run_id = :pipeline_run_id
                """
            ),
            {"pipeline_run_id": pipeline_run_id},
        ).mappings().one()
        step_count = _count_where(
            connection,
            "cx_document_processing_steps",
            "pipeline_run_id = :pipeline_run_id",
            {"pipeline_run_id": pipeline_run_id},
        )
        succeeded_step_count = int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM cx_document_processing_steps
                    WHERE pipeline_run_id = :pipeline_run_id
                      AND status = 'SUCCEEDED'
                    """
                ),
                {"pipeline_run_id": pipeline_run_id},
            ).scalar_one()
        )
        service_job_row = connection.execute(
            text(
                """
                SELECT count(*) AS job_count, COALESCE(max(status), '') AS status
                FROM service_jobs
                WHERE job_id = :job_id
                """
            ),
            {"job_id": job_id},
        ).mappings().one()
    return {
        "extraction_artifact_count": extraction_artifact_count,
        "chunk_set_count": chunk_set_count,
        "chunk_count": chunk_count,
        "lexical_term_count": lexical_term_count,
        "lexical_posting_count": lexical_posting_count,
        "chunk_embedding_count": int(chunk_embedding_row["embedding_count"]),
        "chunk_embedding_min_dimension": int(chunk_embedding_row["min_dimension"]),
        "chunk_embedding_max_dimension": int(chunk_embedding_row["max_dimension"]),
        "document_summary_count": int(summary_row["summary_count"]),
        "summary_char_count": int(summary_row["summary_char_count"]),
        "summary_embedding_count": summary_embedding_count,
        "processing_run_count": int(processing_row["run_count"]),
        "processing_run_status": processing_row["run_status"],
        "processing_job_status": processing_row["job_status"],
        "processing_step_total": int(processing_row["step_total"]),
        "processing_step_succeeded": int(processing_row["step_succeeded"]),
        "processing_step_failed": int(processing_row["step_failed"]),
        "processing_step_count": step_count,
        "processing_succeeded_step_count": succeeded_step_count,
        "service_job_count": int(service_job_row["job_count"]),
        "service_job_status": service_job_row["status"],
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


def _aggregate_db_observations(
    observations: list[dict[str, object]],
) -> dict[str, int]:
    aggregate_keys = (
        "extraction_artifact_count",
        "chunk_set_count",
        "chunk_count",
        "lexical_term_count",
        "lexical_posting_count",
        "chunk_embedding_count",
        "document_summary_count",
        "summary_embedding_count",
        "processing_run_count",
        "processing_step_count",
        "service_job_count",
    )
    return {
        key: sum(
            int(item["db_observations"][key])
            for item in observations
            if isinstance(item.get("db_observations"), dict)
        )
        for key in aggregate_keys
    }


def _delete_real_document_processing_rows(
    engine: object,
    *,
    document_id: str | None,
    source_file_id: str | None,
    pipeline_run_id: str | None,
    job_id: str | None,
) -> dict[str, object]:
    before = _cleanup_counts(
        engine,
        document_id=document_id,
        source_file_id=source_file_id,
        pipeline_run_id=pipeline_run_id,
        job_id=job_id,
    )
    with engine.begin() as connection:
        if pipeline_run_id is not None:
            connection.execute(
                text(
                    """
                    DELETE FROM cx_document_processing_steps
                    WHERE pipeline_run_id = :pipeline_run_id
                    """
                ),
                {"pipeline_run_id": pipeline_run_id},
            )
            connection.execute(
                text(
                    """
                    DELETE FROM cx_document_processing_runs
                    WHERE pipeline_run_id = :pipeline_run_id
                    """
                ),
                {"pipeline_run_id": pipeline_run_id},
            )
        if job_id is not None:
            connection.execute(
                text("DELETE FROM service_jobs WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
        if document_id is not None:
            _delete_document_derived_rows(connection, document_id=document_id)
            connection.execute(
                text(
                    """
                    DELETE FROM cx_extraction_artifacts
                    WHERE content_object_id = :document_id
                    """
                ),
                {"document_id": document_id},
            )
            connection.execute(
                text(
                    """
                    DELETE FROM cx_content_acl_entries
                    WHERE content_object_id = :document_id
                    """
                ),
                {"document_id": document_id},
            )
            connection.execute(
                text(
                    """
                    DELETE FROM cx_content_objects
                    WHERE content_object_id = :document_id
                    """
                ),
                {"document_id": document_id},
            )
        if source_file_id is not None:
            connection.execute(
                text(
                    """
                    DELETE FROM cx_source_files
                    WHERE source_file_id = :source_file_id
                    """
                ),
                {"source_file_id": source_file_id},
            )
    after = _cleanup_counts(
        engine,
        document_id=document_id,
        source_file_id=source_file_id,
        pipeline_run_id=pipeline_run_id,
        job_id=job_id,
    )
    return {"before": before, "after": after}


def _delete_document_derived_rows(connection: Any, *, document_id: str) -> None:
    connection.execute(
        text(
            """
            DELETE FROM cx_document_summary_embeddings
            WHERE document_summary_id IN (
                SELECT document_summary_id
                FROM cx_document_summaries
                WHERE content_object_id = :document_id
            )
            """
        ),
        {"document_id": document_id},
    )
    connection.execute(
        text(
            """
            DELETE FROM cx_document_summaries
            WHERE content_object_id = :document_id
            """
        ),
        {"document_id": document_id},
    )
    connection.execute(
        text(
            """
            DELETE FROM cx_chunk_embeddings
            WHERE chunk_id IN (
                SELECT chunk_id
                FROM cx_chunks
                WHERE content_object_id = :document_id
            )
            """
        ),
        {"document_id": document_id},
    )
    connection.execute(
        text(
            """
            DELETE FROM cx_lexical_postings
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
    )
    connection.execute(
        text(
            """
            DELETE FROM cx_lexical_terms
            WHERE chunk_set_id IN (
                SELECT chunk_set_id
                FROM cx_chunk_sets
                WHERE content_object_id = :document_id
            )
            """
        ),
        {"document_id": document_id},
    )
    connection.execute(
        text(
            """
            DELETE FROM cx_chunks
            WHERE content_object_id = :document_id
            """
        ),
        {"document_id": document_id},
    )
    connection.execute(
        text(
            """
            DELETE FROM cx_chunk_sets
            WHERE content_object_id = :document_id
            """
        ),
        {"document_id": document_id},
    )


def _cleanup_counts(
    engine: object,
    *,
    document_id: str | None,
    source_file_id: str | None,
    pipeline_run_id: str | None,
    job_id: str | None,
) -> dict[str, int]:
    with engine.begin() as connection:
        return {
            "processing_run_rows": _optional_count(
                connection,
                "cx_document_processing_runs",
                "pipeline_run_id = :pipeline_run_id",
                {"pipeline_run_id": pipeline_run_id},
                enabled=pipeline_run_id is not None,
            ),
            "processing_step_rows": _optional_count(
                connection,
                "cx_document_processing_steps",
                "pipeline_run_id = :pipeline_run_id",
                {"pipeline_run_id": pipeline_run_id},
                enabled=pipeline_run_id is not None,
            ),
            "service_job_rows": _optional_count(
                connection,
                "service_jobs",
                "job_id = :job_id",
                {"job_id": job_id},
                enabled=job_id is not None,
            ),
            "extraction_artifact_rows": _optional_count(
                connection,
                "cx_extraction_artifacts",
                "content_object_id = :document_id",
                {"document_id": document_id},
                enabled=document_id is not None,
            ),
            "chunk_set_rows": _optional_count(
                connection,
                "cx_chunk_sets",
                "content_object_id = :document_id",
                {"document_id": document_id},
                enabled=document_id is not None,
            ),
            "chunk_rows": _optional_count(
                connection,
                "cx_chunks",
                "content_object_id = :document_id",
                {"document_id": document_id},
                enabled=document_id is not None,
            ),
            "summary_rows": _optional_count(
                connection,
                "cx_document_summaries",
                "content_object_id = :document_id",
                {"document_id": document_id},
                enabled=document_id is not None,
            ),
            "content_object_rows": _optional_count(
                connection,
                "cx_content_objects",
                "content_object_id = :document_id",
                {"document_id": document_id},
                enabled=document_id is not None,
            ),
            "source_file_rows": _optional_count(
                connection,
                "cx_source_files",
                "source_file_id = :source_file_id",
                {"source_file_id": source_file_id},
                enabled=source_file_id is not None,
            ),
        }


def _optional_count(
    connection: Any,
    table: str,
    where_clause: str,
    params: dict[str, object],
    *,
    enabled: bool,
) -> int:
    if not enabled:
        return 0
    return _count_where(connection, table, where_clause, params)


def assert_evidence_redacted(evidence: object) -> None:
    rendered = json.dumps(evidence, default=str, ensure_ascii=False)
    forbidden = [
        SECRET_MARKER_PREFIX,
        "source_storage_path",
        "extracted_markdown_path",
        "nex-cx-real-document-processing-smoke-",
        "/data/nex-platform",
    ]
    for fragment in forbidden:
        if fragment in rendered:
            raise ValueError(
                "CX real-document processing pipeline smoke evidence is not redacted."
            )


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
) -> dict[str, object]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "cx_real_document_processing_pipeline_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "cx_real_document_processing_pipeline_postgres_smoke=pass "
            f"profile={evidence['profile']} "
            f"db_env={evidence['database_env']} "
            f"formats={evidence['format_count']} "
            f"pipeline_runs={evidence['db_observations']['processing_run_count']} "
            f"chunks={evidence['db_observations']['chunk_count']}"
        )
    return (
        "cx_real_document_processing_pipeline_postgres_smoke=fail "
        f"profile={evidence.get('profile')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the protected CX real-document processing pipeline PostgreSQL smoke."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_env_file(ROOT / ".env")
    args = build_parser().parse_args(argv)
    evidence = run_cx_real_document_processing_pipeline_postgres_smoke()
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
