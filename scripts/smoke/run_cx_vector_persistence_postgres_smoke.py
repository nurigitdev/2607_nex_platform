#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import psycopg


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "scripts" / "db"):
    sys.path.insert(0, str(path))

from nex_runtime import redact_database_url  # noqa: E402
from run_migrations import (  # noqa: E402
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "cx_vector_persistence_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_VECTOR_PERSISTENCE_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_CX_VECTOR_PERSISTENCE_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
MIGRATION_VERSION = "0933_cx_vector_index_persistence"
MIGRATION_PATH = (
    ROOT / "database" / "nex-cx" / "migrations" / f"{MIGRATION_VERSION}.sql"
)


def audit_vector_persistence_schema() -> dict[str, Any]:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    compact = " ".join(sql.lower().split())
    checks = {
        "manifest_table": "create table if not exists cx_vector_indexes" in compact,
        "payload_table": "create table if not exists cx_vectors" in compact,
        "pgvector_prerequisite": "pgvector extension must be provisioned" in compact,
        "owner_lineage_trigger": "cx_assert_vector_index_lineage" in compact,
        "dimension_guard": "vector_dims(embedding) = vector_dimension" in compact,
        "profile_uniqueness": "ux_cx_vector_indexes_source_profile" in compact,
        "owner_lookup_index": "ix_cx_vectors_owner_index" in compact,
        "qwen_hnsw_index": "embedding::halfvec(2560)" in compact
        and "halfvec_cosine_ops" in compact,
        "migration_record": MIGRATION_VERSION in compact,
    }
    return {
        "audit_schema_version": "cx_vector_persistence_schema_audit.v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "table_names": ["cx_vector_indexes", "cx_vectors"],
        "default_ann_dimension": 2560,
        "remote_embedding_required": False,
    }


def run_cx_vector_persistence_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    schema_audit = audit_vector_persistence_schema()
    if schema_audit["status"] != "PASS":
        return _failure("schema_audit_failed", schema_audit["failed_checks"])
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "schema_audit": schema_audit,
        }
    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure(
            "profile_not_allowed",
            f"{PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
        )

    database_url = ""
    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
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
        execution = _execute_smoke(database_url)
        if execution["failed_checks"]:
            return _failure(
                "vector_persistence_smoke_failed",
                execution["failed_checks"],
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
            "schema_audit": schema_audit,
            "remote_embedding_required": False,
            **execution,
        }
    except Exception as exc:  # pragma: no cover - protected PostgreSQL evidence
        return _failure(
            "execution_failed",
            exc.__class__.__name__,
            profile=profile,
            redacted_database_url=(
                redact_database_url(database_url) if database_url else None
            ),
        )


def _execute_smoke(database_url: str) -> dict[str, Any]:  # pragma: no cover
    ids = {name: uuid4() for name in ("blob", "content", "upload", "artifact", "set", "index")}
    chunk_ids = [uuid4(), uuid4()]
    vector_ids = [uuid4(), uuid4()]
    now = datetime.now(UTC)
    source_hash = _digest(f"source:{ids['content']}")
    markdown_hash = _digest(f"markdown:{ids['content']}")
    source_fingerprint = _digest(f"source-profile:{ids['content']}")
    profile_fingerprint = _digest("qwen3-embedding-4b:2560")
    payload_fingerprint = _digest(f"payload:{ids['index']}")
    embeddings = [_embedding(0), _embedding(1)]
    checks: dict[str, bool] = {}

    with psycopg.connect(database_url, autocommit=True) as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
                )
                extension_row = cursor.fetchone()
                checks["pgvector_enabled"] = extension_row is not None
                cursor.execute(
                    "SELECT 1 FROM pg_indexes WHERE indexname = %s",
                    ("ix_cx_vectors_hnsw_2560_cosine",),
                )
                checks["hnsw_index_present"] = cursor.fetchone() == (1,)
                cursor.execute(
                    """
                    INSERT INTO cx_source_files (
                        source_file_id, source_sha256, size_bytes, content_type,
                        storage_uri, storage_backend, storage_key,
                        stored_filename, stored_extension, created_at
                    ) VALUES (
                        %s, %s, 16, 'text/markdown', %s, 'local_filesystem',
                        %s, %s, '.md', %s
                    )
                    """,
                    (
                        ids["blob"], source_hash, f"cx-source://{ids['blob']}",
                        f"{now:%Y%m%d}/{source_hash[:2]}/{source_hash[2:4]}/{ids['blob']}.md",
                        f"{ids['blob']}.md", now,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO cx_content_objects (
                        content_object_id, tenant_id, owner_user_id, source_file_id,
                        source_sha256, upload_id, original_filename, content_type,
                        size_bytes, tenant_ref_type, tenant_ref_id,
                        owner_subject_ref_type, owner_subject_ref_id,
                        uploaded_by_subject_ref_type, uploaded_by_subject_ref_id,
                        created_at, updated_at
                    ) VALUES (
                        %s, 's94-tenant', 's94-owner', %s, %s, %s,
                        's94-vector.md', 'text/markdown', 16,
                        'oa.tenant', 's94-tenant', 'oa.user', 's94-owner',
                        'oa.user', 's94-owner', %s, %s
                    )
                    """,
                    (ids["content"], ids["blob"], source_hash, ids["upload"], now, now),
                )
                cursor.execute(
                    """
                    INSERT INTO cx_extraction_artifacts (
                        extraction_artifact_id, content_object_id, source_file_id,
                        extractor_name, extractor_version, markdown_sha256,
                        markdown_storage_uri, markdown_char_count, created_at, updated_at
                    ) VALUES (%s, %s, %s, 's94-smoke', '1', %s, %s, 16, %s, %s)
                    """,
                    (
                        ids["artifact"], ids["content"], ids["blob"], markdown_hash,
                        f"cx-private://markdown/{ids['artifact']}", now, now,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO cx_chunk_sets (
                        chunk_set_id, content_object_id, extraction_artifact_id,
                        chunk_policy_id, chunk_size, chunk_overlap,
                        source_markdown_sha256, chunk_count, created_at
                    ) VALUES (%s, %s, %s, '1000_100', 1000, 100, %s, 2, %s)
                    """,
                    (ids["set"], ids["content"], ids["artifact"], markdown_hash, now),
                )
                for ordinal, chunk_id in enumerate(chunk_ids):
                    cursor.execute(
                        """
                        INSERT INTO cx_chunks (
                            chunk_id, chunk_set_id, content_object_id, ordinal,
                            start_offset, end_offset, char_count, text_sha256,
                            text_preview, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, 8, %s, %s, %s)
                        """,
                        (
                            chunk_id, ids["set"], ids["content"], ordinal,
                            ordinal * 8, (ordinal + 1) * 8,
                            _digest(f"chunk:{chunk_id}"), f"chunk-{ordinal}", now,
                        ),
                    )
                _insert_manifest(
                    cursor,
                    vector_index_id=ids["index"],
                    content_object_id=ids["content"],
                    chunk_set_id=ids["set"],
                    source_hash=markdown_hash,
                    source_fingerprint=source_fingerprint,
                    profile_fingerprint=profile_fingerprint,
                    tenant_id="s94-tenant",
                    owner_id="s94-owner",
                    observed_at=now,
                )
                for vector_id, chunk_id, embedding in zip(
                    vector_ids, chunk_ids, embeddings, strict=True
                ):
                    cursor.execute(
                        """
                        INSERT INTO cx_vectors (
                            vector_id, vector_index_id, content_object_id, chunk_set_id,
                            chunk_id, tenant_ref_id, owner_subject_ref_id,
                            embedding_sha256, vector_dimension, embedding, created_at
                        ) VALUES (%s, %s, %s, %s, %s, 's94-tenant', 's94-owner',
                                  %s, 2560, %s::vector, %s)
                        """,
                        (
                            vector_id, ids["index"], ids["content"], ids["set"],
                            chunk_id, _digest(embedding), embedding, now,
                        ),
                    )
                cursor.execute(
                    """
                    UPDATE cx_vector_indexes
                    SET status = 'READY', payload_count = 2,
                        payload_fingerprint = %s, checkpoint_version = 1,
                        updated_at = %s, ready_at = %s
                    WHERE vector_index_id = %s
                    """,
                    (payload_fingerprint, now, now, ids["index"]),
                )
                cursor.execute(
                    """
                    SELECT count(*), min(vector_dims(embedding)), max(vector_dims(embedding))
                    FROM cx_vectors WHERE vector_index_id = %s
                    """,
                    (ids["index"],),
                )
                count, min_dims, max_dims = cursor.fetchone()
                checks["vector_round_trip"] = (count, min_dims, max_dims) == (2, 2560, 2560)
                cursor.execute(
                    """
                    SELECT chunk_id
                    FROM cx_vectors
                    WHERE tenant_ref_id = 's94-tenant'
                      AND owner_subject_ref_id = 's94-owner'
                      AND vector_index_id = %s
                      AND vector_dimension = 2560
                    ORDER BY embedding::halfvec(2560) <=> %s::halfvec(2560)
                    LIMIT 1
                    """,
                    (ids["index"], embeddings[0]),
                )
                checks["owner_scoped_cosine_search"] = cursor.fetchone() == (chunk_ids[0],)
                cursor.execute(
                    """
                    SELECT count(*) FROM cx_vectors
                    WHERE vector_index_id = %s AND owner_subject_ref_id = 'other-owner'
                    """,
                    (ids["index"],),
                )
                checks["cross_owner_excluded"] = cursor.fetchone() == (0,)
                checks["owner_lineage_rejected"] = _lineage_rejected(
                    cursor,
                    content_object_id=ids["content"],
                    chunk_set_id=ids["set"],
                    source_hash=markdown_hash,
                    source_fingerprint=_digest("other-source"),
                    profile_fingerprint=profile_fingerprint,
                    observed_at=now,
                )
                checks["dimension_mismatch_rejected"] = _dimension_rejected(
                    cursor,
                    vector_index_id=ids["index"],
                    content_object_id=ids["content"],
                    chunk_set_id=ids["set"],
                    observed_at=now,
                )
                cursor.execute(
                    "SELECT status, payload_count FROM cx_vector_indexes WHERE vector_index_id = %s",
                    (ids["index"],),
                )
                checks["ready_manifest_persisted"] = cursor.fetchone() == ("READY", 2)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM cx_vectors WHERE vector_index_id = %s", (ids["index"],))
                cursor.execute("DELETE FROM cx_content_objects WHERE content_object_id = %s", (ids["content"],))
                cursor.execute("DELETE FROM cx_source_files WHERE source_file_id = %s", (ids["blob"],))
                cursor.execute("SELECT count(*) FROM cx_vectors WHERE vector_index_id = %s", (ids["index"],))
                checks["cleanup_complete"] = cursor.fetchone() == (0,)

    return {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "check_count": len(checks),
        "table_names": ["cx_vector_indexes", "cx_vectors"],
        "vector_dimension": 2560,
    }


def _insert_manifest(
    cursor: Any,
    *,
    vector_index_id: Any,
    content_object_id: Any,
    chunk_set_id: Any,
    source_hash: str,
    source_fingerprint: str,
    profile_fingerprint: str,
    tenant_id: str,
    owner_id: str,
    observed_at: datetime,
) -> None:  # pragma: no cover
    cursor.execute(
        """
        INSERT INTO cx_vector_indexes (
            vector_index_id, content_object_id, chunk_set_id,
            tenant_ref_id, owner_subject_ref_id, chunk_policy_id,
            source_markdown_sha256, source_fingerprint, source_chunk_count,
            provider_alias, model_profile_id, model_revision, deployment_id,
            vector_dimension, profile_fingerprint, status,
            trace_id, request_id, created_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, '1000_100', %s, %s, 2,
            'dgx-embedding', 'Qwen3-Embedding-4B', 'bf16', 'dgx-spark-9112',
            2560, %s, 'BUILDING', 's94-trace', 's94-request', %s, %s
        )
        """,
        (
            vector_index_id, content_object_id, chunk_set_id, tenant_id, owner_id,
            source_hash, source_fingerprint, profile_fingerprint,
            observed_at, observed_at,
        ),
    )


def _lineage_rejected(cursor: Any, **values: Any) -> bool:  # pragma: no cover
    try:
        _insert_manifest(
            cursor,
            vector_index_id=uuid4(),
            tenant_id="s94-tenant",
            owner_id="wrong-owner",
            **values,
        )
    except psycopg.errors.CheckViolation:
        return True
    return False


def _dimension_rejected(
    cursor: Any,
    *,
    vector_index_id: Any,
    content_object_id: Any,
    chunk_set_id: Any,
    observed_at: datetime,
) -> bool:  # pragma: no cover
    try:
        cursor.execute(
            """
            INSERT INTO cx_vectors (
                vector_id, vector_index_id, content_object_id, chunk_set_id,
                chunk_id, tenant_ref_id, owner_subject_ref_id,
                embedding_sha256, vector_dimension, embedding, created_at
            ) VALUES (%s, %s, %s, %s, %s, 's94-tenant', 's94-owner',
                      %s, 2560, '[1,2]'::vector, %s)
            """,
            (
                uuid4(), vector_index_id, content_object_id, chunk_set_id, uuid4(),
                _digest("bad-vector"), observed_at,
            ),
        )
    except psycopg.errors.CheckViolation:
        return True
    return False


def _embedding(hot_index: int) -> str:
    values = ["0"] * 2560
    values[hot_index] = "1"
    return "[" + ",".join(values) + "]"


def _digest(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    return unquote(parsed.username or "") == EXPECTED_ROLE and parsed.path.lstrip("/") == EXPECTED_DATABASE


def _failure(error_code: str, detail: Any, **extra: Any) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "error": {"code": error_code, "detail": detail},
        **extra,
    }


def _format_summary(result: Mapping[str, Any]) -> str:
    status = str(result["status"]).lower()
    if status == "skipped":
        return f"cx_vector_persistence_postgres_smoke=skipped reason={SMOKE_ENV}"
    if status == "pass":
        return (
            "cx_vector_persistence_postgres_smoke=pass "
            f"checks={result['check_count']}/{result['check_count']} "
            f"dimension={result['vector_dimension']} remote_required=False"
        )
    return f"cx_vector_persistence_postgres_smoke=fail error={result['error']['code']}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    result = run_cx_vector_persistence_postgres_smoke()
    print(_format_summary(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
