#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
for path in (SHARED_PATH, DB_SCRIPT_PATH):
    sys.path.insert(0, str(path))

from nex_runtime import (  # noqa: E402
    load_env_file,
    psycopg_database_url,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "cx_private_ownership_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_PRIVATE_OWNERSHIP_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_CX_PRIVATE_OWNERSHIP_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
MIGRATION_VERSION = "0917_cx_owner_lineage_persistence"
PRIVATE_SENTINEL = "private-s92-payload-must-not-persist"
OWNER_COLUMNS = (
    "tenant_ref_type",
    "tenant_ref_id",
    "owner_subject_ref_type",
    "owner_subject_ref_id",
)
FORBIDDEN_GENERATION_COLUMNS = {
    "prompt",
    "messages",
    "content",
    "text",
    "raw_output",
    "output_preview",
    "chunk_text",
    "summary_text",
    "embedding",
    "vector",
}


def run_cx_private_ownership_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure(
            "profile_not_allowed",
            f"{PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(
            SERVICE_ID,
            profile=profile,
            environ=env,
        )
        if not _target_url_allowed(database_url):
            return _failure(
                "target_not_allowed",
                f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
                profile=profile,
            )
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_private_ownership_smoke(database_url)
        checks = execution.get("checks") or {}
        if not checks or not all(checks.values()):
            return _failure(
                "ownership_smoke_failed",
                ",".join(name for name, passed in checks.items() if not passed),
                profile=profile,
                execution=execution,
            )
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "planned": list(migration.planned),
                "applied": list(migration.applied),
                "skipped": list(migration.skipped),
            },
            "dgx_live_provider_required": False,
            **execution,
        }
    except (MigrationError, psycopg.Error, OSError, ValueError) as exc:
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_url=env.get("NEX_CX_TEST_DATABASE_URL", "")),
            profile=profile,
        )


def _execute_private_ownership_smoke(database_url: str) -> dict[str, Any]:  # pragma: no cover - protected PostgreSQL evidence
    refs = _build_refs()
    dsn = psycopg_database_url(database_url)
    checks: dict[str, bool] = {}
    rows_written = 0
    connection: psycopg.Connection[Any] | None = None
    try:
        connection = psycopg.connect(dsn)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            database, role = cursor.fetchone()
            checks["actual_test_database"] = database == EXPECTED_DATABASE
            checks["actual_test_role"] = role == EXPECTED_ROLE
            cursor.execute(
                "SELECT count(*) FROM schema_migrations WHERE version = %s",
                (MIGRATION_VERSION,),
            )
            checks["owner_lineage_migration_recorded"] = cursor.fetchone()[0] == 1

            for owner_key in ("owner_a", "owner_b"):
                _insert_owner_document(cursor, refs, owner_key=owner_key)
                rows_written += 5

            cursor.execute(
                """
                SELECT tenant_ref_type, tenant_ref_id,
                       owner_subject_ref_type, owner_subject_ref_id
                FROM cx_content_objects
                WHERE content_object_id = %s
                """,
                (refs["owner_a_content_id"],),
            )
            checks["content_owner_trigger"] = cursor.fetchone() == _owner_tuple(refs, "owner_a")

            cursor.execute(
                """
                INSERT INTO service_jobs (
                    job_id, job_type, status, trace_id, request_id,
                    subject_type, subject_id, idempotency_key, links, payload
                ) VALUES (%s, %s, 'QUEUED', %s, %s, 'cx.document', %s, %s, %s, %s)
                """,
                (
                    refs["job_id"],
                    "cx.document.process",
                    refs["trace_id"],
                    refs["request_id"],
                    str(refs["owner_a_content_id"]),
                    refs["job_idempotency_key"],
                    Jsonb({}),
                    Jsonb({"document_id": str(refs["owner_a_content_id"])}),
                ),
            )
            rows_written += 1
            cursor.execute(
                f"SELECT {', '.join(OWNER_COLUMNS)} FROM service_jobs WHERE job_id = %s",
                (refs["job_id"],),
            )
            checks["job_owner_trigger"] = cursor.fetchone() == _owner_tuple(refs, "owner_a")

            cursor.execute(
                """
                INSERT INTO cx_document_processing_runs (
                    pipeline_run_id, document_id, status, trace_id, request_id,
                    job_id, job_type, job_status, job_attempt_count,
                    job_max_attempts, job_retryable, job_subject_ref, job_links
                ) VALUES (%s, %s, 'QUEUED', %s, %s, %s, %s, 'QUEUED', 0, 1, true, %s, %s)
                """,
                (
                    refs["pipeline_run_id"],
                    refs["owner_a_content_id"],
                    refs["trace_id"],
                    refs["request_id"],
                    refs["job_id"],
                    "cx.document.process",
                    Jsonb({"document_id": str(refs["owner_a_content_id"])}),
                    Jsonb({}),
                ),
            )
            rows_written += 1
            cursor.execute(
                f"SELECT {', '.join(OWNER_COLUMNS)} FROM cx_document_processing_runs WHERE pipeline_run_id = %s",
                (refs["pipeline_run_id"],),
            )
            checks["processing_owner_trigger"] = cursor.fetchone() == _owner_tuple(refs, "owner_a")

            _insert_retrieval_package(cursor, refs)
            rows_written += 1
            _insert_retrieval_evidence(cursor, refs, owner_key="owner_a", rank=1)
            rows_written += 1
            cursor.execute(
                f"SELECT {', '.join(OWNER_COLUMNS)} FROM cx_retrieval_packages WHERE retrieval_package_id = %s",
                (refs["retrieval_package_id"],),
            )
            checks["retrieval_owner_trigger"] = cursor.fetchone() == _owner_tuple(refs, "owner_a")

            cursor.execute("SAVEPOINT cx_mixed_owner_probe")
            try:
                _insert_retrieval_evidence(cursor, refs, owner_key="owner_b", rank=2)
            except psycopg.errors.CheckViolation:
                cursor.execute("ROLLBACK TO SAVEPOINT cx_mixed_owner_probe")
                checks["mixed_owner_retrieval_rejected"] = True
            else:
                checks["mixed_owner_retrieval_rejected"] = False
            finally:
                cursor.execute("RELEASE SAVEPOINT cx_mixed_owner_probe")

            cursor.execute(
                """
                INSERT INTO cx_generation_executions (
                    cx_generation_id, tenant_ref_type, tenant_ref_id,
                    owner_subject_ref_type, owner_subject_ref_id, status,
                    retrieval_package_id, trace_id, request_id, alias,
                    provider_capability, request_metadata, response_metadata,
                    mo_runtime_metadata, usage
                ) VALUES (%s, 'oa.tenant', %s, 'oa.user', %s, 'COMPLETED',
                          %s, %s, %s, %s, 'generation', %s, %s, %s, %s)
                """,
                (
                    refs["generation_id"],
                    refs["tenant_id"],
                    refs["owner_a_subject_id"],
                    refs["retrieval_package_id"],
                    refs["trace_id"],
                    refs["request_id"],
                    "general-llm-default",
                    Jsonb({"generation_request_hash": refs["safe_hash"]}),
                    Jsonb({"output_hash": refs["second_hash"]}),
                    Jsonb({"total_ms": 1}),
                    Jsonb({"input_tokens": 1, "output_tokens": 1}),
                ),
            )
            rows_written += 1
            cursor.execute("SAVEPOINT cx_private_metadata_probe")
            try:
                cursor.execute(
                    """
                    INSERT INTO cx_generation_executions (
                        cx_generation_id, tenant_ref_type, tenant_ref_id,
                        owner_subject_ref_type, owner_subject_ref_id, status,
                        trace_id, request_id, alias, provider_capability,
                        request_metadata
                    ) VALUES (%s, 'oa.tenant', %s, 'oa.user', %s, 'COMPLETED',
                              %s, %s, %s, 'generation', %s)
                    """,
                    (
                        refs["private_generation_id"],
                        refs["tenant_id"],
                        refs["owner_a_subject_id"],
                        refs["trace_id"],
                        refs["request_id"],
                        "general-llm-default",
                        Jsonb({"prompt": PRIVATE_SENTINEL}),
                    ),
                )
            except psycopg.errors.CheckViolation:
                cursor.execute("ROLLBACK TO SAVEPOINT cx_private_metadata_probe")
                checks["generation_private_metadata_rejected"] = True
            else:
                checks["generation_private_metadata_rejected"] = False
            finally:
                cursor.execute("RELEASE SAVEPOINT cx_private_metadata_probe")

            cursor.execute(
                """
                INSERT INTO cx_remediation_execution_attempts (
                    remediation_action_id, parent_cx_generation_id,
                    root_cx_generation_id, tenant_id, trace_id, request_id,
                    action_type, lineage_type, execution_status,
                    tenant_ref_type, tenant_ref_id,
                    owner_subject_ref_type, owner_subject_ref_id
                ) VALUES (%s, %s, %s, %s, %s, %s,
                          'retry_generation', 'retry', 'ACCEPTED',
                          'oa.tenant', %s, 'oa.user', %s)
                """,
                (
                    refs["remediation_action_id"],
                    refs["generation_id"],
                    refs["generation_id"],
                    refs["tenant_id"],
                    refs["trace_id"],
                    refs["request_id"],
                    refs["tenant_id"],
                    refs["owner_a_subject_id"],
                ),
            )
            rows_written += 1
        connection.commit()

        with connection.cursor() as cursor:
            checks.update(_read_committed_checks(cursor, refs))
        connection.commit()
    finally:
        if connection is not None:
            try:
                _cleanup_smoke_rows(connection, refs)
            finally:
                connection.close()

    with psycopg.connect(dsn) as verify_connection:
        with verify_connection.cursor() as cursor:
            checks["cleanup_verified"] = _smoke_row_count(cursor, refs) == 0
        verify_connection.rollback()

    return {
        "database": EXPECTED_DATABASE,
        "role": EXPECTED_ROLE,
        "rows_written": rows_written,
        "owner_scope_count": 2,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _build_refs() -> dict[str, Any]:
    token = uuid4().hex
    return {
        "tenant_id": f"tenant-s92-{token[:8]}",
        "owner_a_subject_id": f"employee-a-{token[:8]}",
        "owner_b_subject_id": f"employee-b-{token[:8]}",
        "trace_id": uuid4().hex,
        "request_id": f"request-s92-{token}",
        "safe_hash": sha256(f"safe-{token}".encode()).hexdigest(),
        "second_hash": sha256(f"second-{token}".encode()).hexdigest(),
        "owner_a_source_id": uuid4(),
        "owner_b_source_id": uuid4(),
        "owner_a_content_id": uuid4(),
        "owner_b_content_id": uuid4(),
        "owner_a_upload_id": uuid4(),
        "owner_b_upload_id": uuid4(),
        "owner_a_extraction_id": uuid4(),
        "owner_b_extraction_id": uuid4(),
        "owner_a_chunk_set_id": uuid4(),
        "owner_b_chunk_set_id": uuid4(),
        "owner_a_chunk_id": uuid4(),
        "owner_b_chunk_id": uuid4(),
        "owner_a_hash": sha256(f"owner-a-{token}".encode()).hexdigest(),
        "owner_b_hash": sha256(f"owner-b-{token}".encode()).hexdigest(),
        "job_id": f"cx-job-s92-{token}",
        "job_idempotency_key": f"cx-job-s92-idem-{token}",
        "pipeline_run_id": uuid4(),
        "retrieval_package_id": uuid4(),
        "owner_a_evidence_id": uuid4(),
        "owner_b_evidence_id": uuid4(),
        "generation_id": f"cx-gen-s92-{token}",
        "private_generation_id": f"cx-gen-private-s92-{token}",
        "remediation_action_id": f"cx-rem-s92-{token}",
    }


def _owner_tuple(refs: Mapping[str, Any], owner_key: str) -> tuple[str, str, str, str]:
    return (
        "oa.tenant",
        str(refs["tenant_id"]),
        "oa.user",
        str(refs[f"{owner_key}_subject_id"]),
    )


def _insert_owner_document(cursor: Any, refs: Mapping[str, Any], *, owner_key: str) -> None:  # pragma: no cover - protected PostgreSQL evidence
    source_id: UUID = refs[f"{owner_key}_source_id"]
    content_id: UUID = refs[f"{owner_key}_content_id"]
    source_hash = refs[f"{owner_key}_hash"]
    subject_id = refs[f"{owner_key}_subject_id"]
    stored_filename = f"{source_id}.txt"
    cursor.execute(
        """
        INSERT INTO cx_source_files (
            source_file_id, source_sha256, size_bytes, content_type,
            storage_uri, first_seen_trace_id, storage_backend, storage_key,
            stored_filename, stored_extension, checksum_verified_at
        ) VALUES (%s, %s, 1, 'text/plain', %s, %s, 'local_filesystem',
                  %s, %s, '.txt', now())
        """,
        (
            source_id,
            source_hash,
            f"file:///tmp/{stored_filename}",
            refs["trace_id"],
            f"20260921/{source_hash[:2]}/{source_hash[2:4]}/{stored_filename}",
            stored_filename,
        ),
    )
    cursor.execute(
        """
        INSERT INTO cx_content_objects (
            content_object_id, tenant_id, owner_user_id, source_file_id,
            source_sha256, upload_id, original_filename, content_type,
            size_bytes, classification, lifecycle_status, retrieval_policy,
            created_trace_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'text/plain', 1,
                  'private', 'ACTIVE', %s, %s)
        """,
        (
            content_id,
            refs["tenant_id"],
            subject_id,
            source_id,
            source_hash,
            refs[f"{owner_key}_upload_id"],
            f"{owner_key}.txt",
            Jsonb({}),
            refs["trace_id"],
        ),
    )
    cursor.execute(
        """
        INSERT INTO cx_extraction_artifacts (
            extraction_artifact_id, content_object_id, source_file_id,
            status, extractor_name, extractor_version, markdown_sha256,
            markdown_storage_uri, markdown_char_count, created_trace_id
        ) VALUES (%s, %s, %s, 'SUCCEEDED', 's92-smoke', '1', %s, %s, 10, %s)
        """,
        (
            refs[f"{owner_key}_extraction_id"],
            content_id,
            source_id,
            source_hash,
            f"private://text/{content_id}",
            refs["trace_id"],
        ),
    )
    cursor.execute(
        """
        INSERT INTO cx_chunk_sets (
            chunk_set_id, content_object_id, extraction_artifact_id,
            chunk_policy_id, chunk_size, chunk_overlap,
            source_markdown_sha256, chunk_count, created_trace_id
        ) VALUES (%s, %s, %s, 'chunk_1000_100', 1000, 100, %s, 1, %s)
        """,
        (
            refs[f"{owner_key}_chunk_set_id"],
            content_id,
            refs[f"{owner_key}_extraction_id"],
            source_hash,
            refs["trace_id"],
        ),
    )
    cursor.execute(
        """
        INSERT INTO cx_chunks (
            chunk_id, chunk_set_id, content_object_id, ordinal,
            start_offset, end_offset, char_count, text_sha256, text_preview
        ) VALUES (%s, %s, %s, 0, 0, 10, 10, %s, '[private text redacted]')
        """,
        (
            refs[f"{owner_key}_chunk_id"],
            refs[f"{owner_key}_chunk_set_id"],
            content_id,
            source_hash,
        ),
    )


def _insert_retrieval_package(cursor: Any, refs: Mapping[str, Any]) -> None:  # pragma: no cover - protected PostgreSQL evidence
    cursor.execute(
        """
        INSERT INTO cx_retrieval_packages (
            retrieval_package_id, package_hash, status, trace_id, request_id,
            query_text_sha256, query_embedding_provided,
            query_embedding_dimension, purpose, retrieval_policy_id,
            retrieval_policy_version, retrieval_policy_hash,
            retrieval_policy_source, ranker_mix, rerank_state,
            permission_snapshot_hash, source_summary, score_summary,
            warning_count, evidence_count
        ) VALUES (%s, %s, 'READY', %s, %s, %s, false, 0,
                  'grounded_answer', 'default', '1', %s, 'nex-cx',
                  'vector=0.7,bm25=0.3', 'APPLIED', %s, %s, %s, 0, 1)
        """,
        (
            refs["retrieval_package_id"],
            refs["safe_hash"],
            refs["trace_id"],
            refs["request_id"],
            refs["safe_hash"],
            refs["safe_hash"],
            refs["second_hash"],
            Jsonb({"count": 1}),
            Jsonb({"max": 1.0}),
        ),
    )


def _insert_retrieval_evidence(
    cursor: Any,
    refs: Mapping[str, Any],
    *,
    owner_key: str,
    rank: int,
) -> None:  # pragma: no cover - protected PostgreSQL evidence
    cursor.execute(
        """
        INSERT INTO cx_retrieval_evidence_items (
            retrieval_package_id, evidence_id, rank, content_object_id,
            content_version_id, chunk_id, chunk_policy_id, source_anchor,
            citation_label, evidence_text_sha256, evidence_text_preview,
            final_score, scores, matched_terms, permission_result,
            neighbor_context, quality_flags
        ) VALUES (%s, %s, %s, %s, 'v1', %s, 'chunk_1000_100', %s,
                  %s, %s, '[private evidence redacted]', 1.0,
                  %s, %s, %s, %s, %s)
        """,
        (
            refs["retrieval_package_id"],
            refs[f"{owner_key}_evidence_id"],
            rank,
            refs[f"{owner_key}_content_id"],
            refs[f"{owner_key}_chunk_id"],
            Jsonb({"document_id": str(refs[f"{owner_key}_content_id"])}),
            f"S92-{rank}",
            refs[f"{owner_key}_hash"],
            Jsonb({"final": 1.0}),
            Jsonb([]),
            Jsonb({"allowed": True}),
            Jsonb([]),
            Jsonb([]),
        ),
    )


def _read_committed_checks(cursor: Any, refs: Mapping[str, Any]) -> dict[str, bool]:  # pragma: no cover - protected PostgreSQL evidence
    owner = _owner_tuple(refs, "owner_a")
    checks: dict[str, bool] = {}
    cursor.execute(
        f"SELECT {', '.join(OWNER_COLUMNS)} FROM cx_generation_executions WHERE cx_generation_id = %s",
        (refs["generation_id"],),
    )
    checks["generation_owner_persisted"] = cursor.fetchone() == owner
    cursor.execute(
        f"SELECT {', '.join(OWNER_COLUMNS)} FROM cx_remediation_execution_attempts WHERE remediation_action_id = %s",
        (refs["remediation_action_id"],),
    )
    checks["remediation_owner_persisted"] = cursor.fetchone() == owner

    owner_tables = (
        ("service_jobs", "job_id", refs["job_id"]),
        ("cx_document_processing_runs", "pipeline_run_id", refs["pipeline_run_id"]),
        ("cx_retrieval_packages", "retrieval_package_id", refs["retrieval_package_id"]),
        ("cx_generation_executions", "cx_generation_id", refs["generation_id"]),
        (
            "cx_remediation_execution_attempts",
            "remediation_action_id",
            refs["remediation_action_id"],
        ),
    )
    visible = 0
    hidden = 0
    for table, key_column, key_value in owner_tables:
        cursor.execute(
            f"SELECT count(*) FROM {table} WHERE {key_column} = %s "
            "AND tenant_ref_id = %s AND owner_subject_ref_id = %s",
            (key_value, refs["tenant_id"], refs["owner_a_subject_id"]),
        )
        visible += cursor.fetchone()[0]
        cursor.execute(
            f"SELECT count(*) FROM {table} WHERE {key_column} = %s "
            "AND tenant_ref_id = %s AND owner_subject_ref_id = %s",
            (key_value, refs["tenant_id"], refs["owner_b_subject_id"]),
        )
        hidden += cursor.fetchone()[0]
    checks["owner_scoped_rows_visible"] = visible == len(owner_tables)
    checks["cross_owner_rows_hidden"] = hidden == 0

    cursor.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'cx_generation_executions'
        """
    )
    generation_columns = {row[0] for row in cursor.fetchall()}
    checks["generation_private_columns_absent"] = not (
        generation_columns & FORBIDDEN_GENERATION_COLUMNS
    )
    cursor.execute(
        """
        SELECT count(*) FROM cx_generation_executions
        WHERE cx_generation_id IN (%s, %s)
          AND (
              request_metadata::text LIKE %s
              OR response_metadata::text LIKE %s
              OR mo_runtime_metadata::text LIKE %s
          )
        """,
        (
            refs["generation_id"],
            refs["private_generation_id"],
            f"%{PRIVATE_SENTINEL}%",
            f"%{PRIVATE_SENTINEL}%",
            f"%{PRIVATE_SENTINEL}%",
        ),
    )
    checks["private_payload_absent"] = cursor.fetchone()[0] == 0
    checks["committed_write_read_verified"] = _smoke_row_count(cursor, refs) == 16
    return checks


def _smoke_row_count(cursor: Any, refs: Mapping[str, Any]) -> int:  # pragma: no cover - protected PostgreSQL evidence
    probes = (
        ("cx_source_files", "source_file_id", refs["owner_a_source_id"]),
        ("cx_source_files", "source_file_id", refs["owner_b_source_id"]),
        ("cx_content_objects", "content_object_id", refs["owner_a_content_id"]),
        ("cx_content_objects", "content_object_id", refs["owner_b_content_id"]),
        ("cx_extraction_artifacts", "extraction_artifact_id", refs["owner_a_extraction_id"]),
        ("cx_extraction_artifacts", "extraction_artifact_id", refs["owner_b_extraction_id"]),
        ("cx_chunk_sets", "chunk_set_id", refs["owner_a_chunk_set_id"]),
        ("cx_chunk_sets", "chunk_set_id", refs["owner_b_chunk_set_id"]),
        ("cx_chunks", "chunk_id", refs["owner_a_chunk_id"]),
        ("cx_chunks", "chunk_id", refs["owner_b_chunk_id"]),
        ("service_jobs", "job_id", refs["job_id"]),
        ("cx_document_processing_runs", "pipeline_run_id", refs["pipeline_run_id"]),
        ("cx_retrieval_packages", "retrieval_package_id", refs["retrieval_package_id"]),
        ("cx_retrieval_evidence_items", "evidence_id", refs["owner_a_evidence_id"]),
        ("cx_generation_executions", "cx_generation_id", refs["generation_id"]),
        (
            "cx_remediation_execution_attempts",
            "remediation_action_id",
            refs["remediation_action_id"],
        ),
    )
    total = 0
    for table, column, value in probes:
        cursor.execute(f"SELECT count(*) FROM {table} WHERE {column} = %s", (value,))
        total += cursor.fetchone()[0]
    return total


def _cleanup_smoke_rows(connection: Any, refs: Mapping[str, Any]) -> None:  # pragma: no cover - protected PostgreSQL evidence
    connection.rollback()
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM cx_generation_executions WHERE cx_generation_id IN (%s, %s)",
            (refs["generation_id"], refs["private_generation_id"]),
        )
        cursor.execute(
            "DELETE FROM cx_remediation_execution_attempts WHERE remediation_action_id = %s",
            (refs["remediation_action_id"],),
        )
        cursor.execute(
            "DELETE FROM cx_retrieval_packages WHERE retrieval_package_id = %s",
            (refs["retrieval_package_id"],),
        )
        cursor.execute(
            "DELETE FROM cx_document_processing_runs WHERE pipeline_run_id = %s",
            (refs["pipeline_run_id"],),
        )
        cursor.execute("DELETE FROM service_jobs WHERE job_id = %s", (refs["job_id"],))
        cursor.execute(
            "DELETE FROM cx_content_objects WHERE content_object_id IN (%s, %s)",
            (refs["owner_a_content_id"], refs["owner_b_content_id"]),
        )
        cursor.execute(
            "DELETE FROM cx_source_files WHERE source_file_id IN (%s, %s)",
            (refs["owner_a_source_id"], refs["owner_b_source_id"]),
        )
    connection.commit()


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


def _redact_detail(detail: str, *, database_url: str) -> str:
    if not database_url:
        return detail
    redacted = detail.replace(database_url, redact_database_url(database_url))
    password = urlsplit(database_url).password
    return redacted.replace(unquote(password), "***") if password else redacted


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    execution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }
    if execution is not None:
        result.update(execution)
    return result


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"cx_private_ownership_postgres_smoke=skipped reason={SMOKE_ENV}"
    return (
        "cx_private_ownership_postgres_smoke="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"database={evidence.get('database', 'not-run')} "
        f"rows={evidence.get('rows_written', 0)} "
        f"owners={evidence.get('owner_scope_count', 0)} "
        f"failed_checks={len(evidence.get('failed_checks') or [])} "
        f"dgx_required={evidence.get('dgx_live_provider_required', False)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run protected CX private ownership PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_cx_private_ownership_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
