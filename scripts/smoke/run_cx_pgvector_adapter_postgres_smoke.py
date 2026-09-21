#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import psycopg


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "db",
):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.pgvector_store import build_pgvector_cx_vector_store  # noqa: E402
from nex_cx.private_content import (  # noqa: E402
    build_private_payload_key,
    sha256_private_vector,
)
from nex_cx.vector_index_freshness import (  # noqa: E402
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
)
from nex_runtime import redact_database_url  # noqa: E402
from run_migrations import (  # noqa: E402
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "cx_pgvector_adapter_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_PGVECTOR_ADAPTER_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_CX_PGVECTOR_ADAPTER_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"


def run_cx_pgvector_adapter_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure("profile_not_allowed", f"{PROFILE_ENV} must be test.")

    database_url = ""
    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        if not _target_url_allowed(database_url):
            return _failure("target_not_allowed", "CX test database target is required.")
        migration = run_service_migrations(
            SERVICE_ID, database_url=database_url, profile=profile
        )
        execution = _execute_smoke(
            database_url,
            environ={**env, database_env: database_url},
            database_env=database_env,
        )
        if execution["failed_checks"]:
            return _failure(
                "pgvector_adapter_smoke_failed",
                execution["failed_checks"],
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
                "applied": list(migration.applied),
                "skipped": list(migration.skipped),
            },
            "remote_embedding_required": False,
            **execution,
        }
    except Exception as exc:  # pragma: no cover - protected PostgreSQL evidence
        return _failure(
            "execution_failed",
            exc.__class__.__name__,
            redacted_database_url=(
                redact_database_url(database_url) if database_url else None
            ),
        )


def _execute_smoke(  # pragma: no cover - protected PostgreSQL evidence
    database_url: str,
    *,
    environ: Mapping[str, str],
    database_env: str,
) -> dict[str, Any]:
    ids = SimpleNamespace(
        source=uuid4(),
        content=uuid4(),
        upload=uuid4(),
        artifact=uuid4(),
        chunk_set=uuid4(),
        chunk=uuid4(),
    )
    now = datetime.now(UTC)
    source_hash = _digest(f"source:{ids.content}")
    markdown_hash = _digest(f"markdown:{ids.content}")
    source = build_source_snapshot(
        chunk_set_id=str(ids.chunk_set),
        chunk_policy_id="1000_100",
        source_markdown_sha256=markdown_hash,
        chunks=[
            {
                "chunk_id": str(ids.chunk),
                "ordinal": 0,
                "text_sha256": _digest(f"chunk:{ids.chunk}"),
            }
        ],
    )
    profile = build_embedding_profile(
        provider_alias="mock-s94",
        model_profile_id="Qwen3-Embedding-4B",
        model_revision="bf16",
        deployment_id="mock-local",
        vector_dimension=2560,
    )
    manifest = build_vector_index_manifest(
        content_object_id=str(ids.content),
        tenant_ref={"type": "oa.tenant", "id": "s94-adapter-tenant"},
        owner_subject_ref={"type": "oa.user", "id": "s94-adapter-owner"},
        source_snapshot=source,
        embedding_profile=profile,
        trace_id="s94-adapter-trace",
        request_id="s94-adapter-request",
        observed_at=now.isoformat(),
    )
    checks: dict[str, bool] = {}
    vector = tuple([1.0] + ([0.0] * 2559))
    checksum = sha256_private_vector(vector)

    with psycopg.connect(database_url, autocommit=True) as connection:
        _seed_fixture(
            connection,
            ids=ids,
            manifest=manifest,
            source_hash=source_hash,
            markdown_hash=markdown_hash,
            observed_at=now,
        )
        try:
            adapter = build_pgvector_cx_vector_store(
                database_env=database_env,
                environ=environ,
                workload="worker",
            )
            bound = adapter.bind_index(manifest)
            context = CxAccessContext(
                caller_service_id="nex-cx",
                tenant_id="s94-adapter-tenant",
                subject_id="s94-adapter-owner",
                request_id="s94-adapter-request",
                trace_id="93400000000000000000000000000001",
                scopes=("service:call",),
            )
            key = build_private_payload_key(
                context,
                payload_kind="chunk_embedding",
                content_id=str(ids.chunk),
            )
            first = bound.put_vector(
                access_context=context,
                key=key,
                vector=vector,
                expected_sha256=checksum,
            )
            second = bound.put_vector(
                access_context=context,
                key=key,
                vector=vector,
                expected_sha256=checksum,
            )
            loaded = bound.get_vector(
                access_context=context,
                key=key,
                expected_sha256=checksum,
                expected_dimension=2560,
            )
            matches = bound.search(
                access_context=context,
                query_vector=vector,
                limit=1,
            )
            checks.update(
                {
                    "primary_fallback_route": adapter.uses_primary_database,
                    "redacted_route": "nuri1004" not in adapter.redacted_database_url,
                    "idempotent_receipt": first == second,
                    "owner_safe_uri": all(
                        item not in first.storage_uri
                        for item in ("s94-adapter-tenant", "s94-adapter-owner")
                    ),
                    "vector_round_trip": loaded == vector,
                    "cosine_search": len(matches) == 1
                    and matches[0]["chunk_id"] == str(ids.chunk)
                    and matches[0]["score"] == 1.0,
                    "delete_once": bound.delete_vector(
                        access_context=context, key=key
                    ),
                    "delete_idempotent": not bound.delete_vector(
                        access_context=context, key=key
                    ),
                    "read_after_delete": bound.get_vector(
                        access_context=context,
                        key=key,
                        expected_sha256=checksum,
                        expected_dimension=2560,
                    )
                    is None,
                }
            )
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM cx_vectors WHERE vector_index_id = %s",
                    (manifest["vector_index_id"],),
                )
                cursor.execute(
                    "DELETE FROM cx_content_objects WHERE content_object_id = %s",
                    (ids.content,),
                )
                cursor.execute(
                    "DELETE FROM cx_source_files WHERE source_file_id = %s",
                    (ids.source,),
                )
                cursor.execute(
                    "SELECT count(*) FROM cx_vectors WHERE vector_index_id = %s",
                    (manifest["vector_index_id"],),
                )
                checks["cleanup_complete"] = cursor.fetchone() == (0,)

    return {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "check_count": len(checks),
        "vector_dimension": 2560,
        "vector_route": "primary_fallback",
    }


def _seed_fixture(  # pragma: no cover - protected PostgreSQL evidence
    connection: Any,
    *,
    ids: Any,
    manifest: Mapping[str, Any],
    source_hash: str,
    markdown_hash: str,
    observed_at: datetime,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cx_source_files (
                source_file_id, source_sha256, size_bytes, content_type,
                storage_uri, storage_backend, storage_key,
                stored_filename, stored_extension, created_at
            ) VALUES (%s, %s, 16, 'text/markdown', %s, 'local_filesystem',
                      %s, %s, '.md', %s)
            """,
            (
                ids.source,
                source_hash,
                f"cx-source://{ids.source}",
                f"{observed_at:%Y%m%d}/{source_hash[:2]}/{source_hash[2:4]}/{ids.source}.md",
                f"{ids.source}.md",
                observed_at,
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
                %s, 's94-adapter-tenant', 's94-adapter-owner', %s, %s, %s,
                's94-adapter.md', 'text/markdown', 16,
                'oa.tenant', 's94-adapter-tenant', 'oa.user', 's94-adapter-owner',
                'oa.user', 's94-adapter-owner', %s, %s
            )
            """,
            (ids.content, ids.source, source_hash, ids.upload, observed_at, observed_at),
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
                ids.artifact,
                ids.content,
                ids.source,
                markdown_hash,
                f"cx-private://markdown/{ids.artifact}",
                observed_at,
                observed_at,
            ),
        )
        cursor.execute(
            """
            INSERT INTO cx_chunk_sets (
                chunk_set_id, content_object_id, extraction_artifact_id,
                chunk_policy_id, chunk_size, chunk_overlap,
                source_markdown_sha256, chunk_count, created_at
            ) VALUES (%s, %s, %s, '1000_100', 1000, 100, %s, 1, %s)
            """,
            (ids.chunk_set, ids.content, ids.artifact, markdown_hash, observed_at),
        )
        cursor.execute(
            """
            INSERT INTO cx_chunks (
                chunk_id, chunk_set_id, content_object_id, ordinal,
                start_offset, end_offset, char_count, text_sha256,
                text_preview, created_at
            ) VALUES (%s, %s, %s, 0, 0, 8, 8, %s, 'chunk-0', %s)
            """,
            (
                ids.chunk,
                ids.chunk_set,
                ids.content,
                manifest["source_snapshot"]["chunk_refs"][0]["text_sha256"],
                observed_at,
            ),
        )
        profile = manifest["embedding_profile"]
        source = manifest["source_snapshot"]
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
                %s, %s, %s, 's94-adapter-tenant', 's94-adapter-owner',
                %s, %s, %s, 1, %s, %s, %s, %s, 2560, %s, 'BUILDING',
                's94-adapter-trace', 's94-adapter-request', %s, %s
            )
            """,
            (
                manifest["vector_index_id"],
                ids.content,
                ids.chunk_set,
                source["chunk_policy_id"],
                source["source_markdown_sha256"],
                source["source_fingerprint"],
                profile["provider_alias"],
                profile["model_profile_id"],
                profile["model_revision"],
                profile["deployment_id"],
                profile["profile_fingerprint"],
                observed_at,
                observed_at,
            ),
        )


def _digest(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    return unquote(parsed.username or "") == EXPECTED_ROLE and parsed.path.lstrip("/") == EXPECTED_DATABASE


def _failure(code: str, detail: Any, **extra: Any) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "error": {"code": code, "detail": detail},
        **extra,
    }


def _summary(result: Mapping[str, Any]) -> str:
    status = str(result["status"]).lower()
    if status == "skipped":
        return f"cx_pgvector_adapter_postgres_smoke=skipped reason={SMOKE_ENV}"
    if status == "pass":
        return (
            "cx_pgvector_adapter_postgres_smoke=pass "
            f"checks={result['check_count']}/{result['check_count']} "
            "route=primary_fallback remote_required=False"
        )
    return f"cx_pgvector_adapter_postgres_smoke=fail error={result['error']['code']}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_pgvector_adapter_postgres_smoke()
    print(_summary(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
