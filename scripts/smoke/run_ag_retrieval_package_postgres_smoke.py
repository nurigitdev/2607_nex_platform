#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.operations import register_unified_operation_routes  # noqa: E402
from nex_ag.retrieval_operations import (  # noqa: E402
    AG_RETRIEVAL_PACKAGE_DETAIL_PROJECTION_SCHEMA_VERSION,
    AG_RETRIEVAL_PACKAGE_OPERATIONS_PROJECTION_SCHEMA_VERSION,
    SqlAlchemyRetrievalPackageOperationsStore,
    register_retrieval_package_operation_routes,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    database_pool_settings,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SMOKE_ENV = "NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SCHEMA_VERSION = "ag_retrieval_package_postgres_smoke.v1"
TRACE_TIMELINE_SCHEMA_VERSION = "ag_cross_service_trace_timeline_projection.v1"
CREATED_AT = "2026-08-09T00:00:00Z"


def run_ag_retrieval_package_postgres_smoke(
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
            f"{SMOKE_PROFILE_ENV} must be test for AG PostgreSQL smoke execution.",
            profile=profile,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        run_service_migrations(SERVICE_ID, database_url=database_url, profile=profile)
        execution = _execute_ag_retrieval_package_postgres_smoke(
            database_url=database_url,
            database_env=database_env,
            environ=env,
        )
        raw_values = execution.pop("raw_values", [])
        if "failure_code" in execution:
            return _failure(
                str(execution["failure_code"]),
                str(execution["detail"]),
                profile=profile,
                database_env=database_env,
                checks=execution.get("checks"),
            )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            **execution,
        }
        if not _redaction_safe(evidence, raw_values):
            return _failure(
                "evidence_redaction_failed",
                "AG retrieval package PostgreSQL smoke evidence leaked private data.",
                profile=profile,
                database_env=database_env,
            )
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_ag_retrieval_package_postgres_smoke(
    *,
    database_url: str,
    database_env: str,
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    env = environ if environ is not None else os.environ
    pool_settings = database_pool_settings(SERVICE_ID, workload="api", environ=env)
    engine = build_engine(database_url, pool_settings=pool_settings)
    refs = _smoke_refs()
    raw_values = [
        refs["query_text"],
        refs["evidence_text"],
        refs["principal_id"],
    ]
    _delete_smoke_rows(engine, refs=refs)
    try:
        _seed_retrieval_rows(engine, refs=refs)
        store = SqlAlchemyRetrievalPackageOperationsStore(
            build_session_factory(engine),
            database_env=database_env,
            redacted_database_url=redact_database_url(database_url),
        )
        client = _build_ag_client(store=store)
        list_response = _get_json(
            client,
            "/admin/v1/operations/retrieval-packages",
            params={
                "service_id": SERVICE_ID,
                "status": "READY",
                "trace_id": refs["trace_id"],
                "limit": "5",
            },
            trace_id=refs["trace_id"],
            request_id=refs["request_id"],
        )
        detail_response = _get_json(
            client,
            f"/admin/v1/operations/retrieval-packages/{refs['retrieval_package_id']}",
            params={"service_id": SERVICE_ID},
            trace_id=refs["trace_id"],
            request_id=refs["request_id"],
        )
        trace_response = _get_json(
            client,
            f"/admin/v1/operations/traces/{refs['trace_id']}",
            params={"service_id": SERVICE_ID, "limit": "10", "sort": "asc"},
            trace_id=refs["trace_id"],
            request_id=refs["request_id"],
        )
        checks = _checks(
            list_response=list_response,
            detail_response=detail_response,
            trace_response=trace_response,
            refs=refs,
            raw_values=raw_values,
        )
        if not all(checks.values()):
            return _execution_failure(
                "checks_failed",
                "AG retrieval package PostgreSQL smoke checks failed.",
                checks=checks,
                raw_values=raw_values,
            )
        return {
            "retrieval_package_id": refs["retrieval_package_id"],
            "request_id": refs["request_id"],
            "trace_id": refs["trace_id"],
            "projection_versions": {
                "list": list_response.get("projection_schema_version"),
                "detail": detail_response.get("projection_schema_version"),
                "trace": trace_response.get("projection_schema_version"),
            },
            "http_statuses": {
                "list": list_response["_http_status"],
                "detail": detail_response["_http_status"],
                "trace": trace_response["_http_status"],
            },
            "counts": {
                "list_total": list_response.get("summary", {}).get("total"),
                "detail_evidence_items": detail_response.get("summary", {}).get(
                    "returned_evidence_items"
                ),
                "trace_timeline_total": trace_response.get("summary", {}).get("total"),
            },
            "checks": checks,
            "raw_values": raw_values,
        }
    finally:
        _delete_smoke_rows(engine, refs=refs)


def _build_ag_client(
    *,
    store: SqlAlchemyRetrievalPackageOperationsStore,
) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    stores = {SERVICE_ID: store}
    register_retrieval_package_operation_routes(app, stores=stores)
    register_unified_operation_routes(app, retrieval_package_stores=stores)
    return TestClient(app)


def _get_json(
    client: TestClient,
    path: str,
    *,
    params: dict[str, str],
    trace_id: str,
    request_id: str,
) -> dict[str, Any]:
    response = client.get(
        path,
        params=params,
        headers=_ag_headers(trace_id=trace_id, request_id=request_id),
    )
    body = response.json()
    body["_http_status"] = response.status_code
    return body


def _ag_headers(*, trace_id: str, request_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _seed_retrieval_rows(engine: object, *, refs: dict[str, str]) -> None:
    with engine.begin() as connection:
        json_expr = _json_sql_expression
        connection.execute(
            text(
                """
                INSERT INTO cx_source_files (
                    source_file_id,
                    source_sha256,
                    size_bytes,
                    content_type,
                    storage_uri,
                    first_seen_trace_id,
                    storage_backend,
                    storage_key,
                    stored_filename,
                    stored_extension,
                    checksum_verified_at,
                    created_at
                )
                VALUES (
                    :source_file_id,
                    :source_sha256,
                    :size_bytes,
                    :content_type,
                    :storage_uri,
                    :first_seen_trace_id,
                    :storage_backend,
                    :storage_key,
                    :stored_filename,
                    :stored_extension,
                    :checksum_verified_at,
                    :created_at
                )
                """
            ),
            _source_file_params(refs),
        )
        connection.execute(
            text(
                f"""
                INSERT INTO cx_content_objects (
                    content_object_id,
                    tenant_id,
                    owner_user_id,
                    tenant_ref_type,
                    tenant_ref_id,
                    owner_subject_ref_type,
                    owner_subject_ref_id,
                    uploaded_by_subject_ref_type,
                    uploaded_by_subject_ref_id,
                    source_file_id,
                    source_sha256,
                    upload_id,
                    original_filename,
                    content_type,
                    size_bytes,
                    classification,
                    lifecycle_status,
                    retrieval_policy,
                    created_trace_id,
                    created_at,
                    updated_at
                )
                VALUES (
                    :content_object_id,
                    :tenant_id,
                    :owner_user_id,
                    :tenant_ref_type,
                    :tenant_ref_id,
                    :owner_subject_ref_type,
                    :owner_subject_ref_id,
                    :uploaded_by_subject_ref_type,
                    :uploaded_by_subject_ref_id,
                    :source_file_id,
                    :source_sha256,
                    :upload_id,
                    :original_filename,
                    :content_type,
                    :size_bytes,
                    :classification,
                    :lifecycle_status,
                    {json_expr(connection, "retrieval_policy")},
                    :created_trace_id,
                    :created_at,
                    :updated_at
                )
                """
            ),
            _content_object_params(refs),
        )
        connection.execute(
            text(
                """
                INSERT INTO cx_extraction_artifacts (
                    extraction_artifact_id,
                    content_object_id,
                    source_file_id,
                    artifact_kind,
                    status,
                    extractor_name,
                    extractor_version,
                    markdown_sha256,
                    markdown_storage_uri,
                    markdown_char_count,
                    created_trace_id,
                    created_at,
                    updated_at
                )
                VALUES (
                    :extraction_artifact_id,
                    :content_object_id,
                    :source_file_id,
                    :artifact_kind,
                    :status,
                    :extractor_name,
                    :extractor_version,
                    :markdown_sha256,
                    :markdown_storage_uri,
                    :markdown_char_count,
                    :created_trace_id,
                    :created_at,
                    :updated_at
                )
                """
            ),
            _extraction_artifact_params(refs),
        )
        connection.execute(
            text(
                """
                INSERT INTO cx_chunk_sets (
                    chunk_set_id,
                    content_object_id,
                    extraction_artifact_id,
                    chunk_policy_id,
                    chunk_size,
                    chunk_overlap,
                    source_markdown_sha256,
                    chunk_count,
                    created_trace_id,
                    created_at
                )
                VALUES (
                    :chunk_set_id,
                    :content_object_id,
                    :extraction_artifact_id,
                    :chunk_policy_id,
                    :chunk_size,
                    :chunk_overlap,
                    :source_markdown_sha256,
                    :chunk_count,
                    :created_trace_id,
                    :created_at
                )
                """
            ),
            _chunk_set_params(refs),
        )
        connection.execute(
            text(
                """
                INSERT INTO cx_chunks (
                    chunk_id,
                    chunk_set_id,
                    content_object_id,
                    ordinal,
                    start_offset,
                    end_offset,
                    char_count,
                    text_sha256,
                    text_preview,
                    created_at
                )
                VALUES (
                    :chunk_id,
                    :chunk_set_id,
                    :content_object_id,
                    :ordinal,
                    :start_offset,
                    :end_offset,
                    :char_count,
                    :text_sha256,
                    :text_preview,
                    :created_at
                )
                """
            ),
            _chunk_params(refs),
        )
        connection.execute(
            text(
                f"""
                INSERT INTO cx_retrieval_packages (
                    retrieval_package_id,
                    retrieval_package_schema_version,
                    package_hash,
                    status,
                    trace_id,
                    request_id,
                    query_text_sha256,
                    query_text_preview,
                    query_embedding_provided,
                    query_embedding_sha256,
                    query_embedding_dimension,
                    purpose,
                    retrieval_policy_id,
                    retrieval_policy_version,
                    retrieval_policy_hash,
                    retrieval_policy_source,
                    ranker_mix,
                    rerank_state,
                    permission_snapshot_hash,
                    source_summary,
                    score_summary,
                    warning_count,
                    evidence_count,
                    no_answer_reason,
                    created_at,
                    updated_at
                )
                VALUES (
                    :retrieval_package_id,
                    :retrieval_package_schema_version,
                    :package_hash,
                    :status,
                    :trace_id,
                    :request_id,
                    :query_text_sha256,
                    :query_text_preview,
                    :query_embedding_provided,
                    :query_embedding_sha256,
                    :query_embedding_dimension,
                    :purpose,
                    :retrieval_policy_id,
                    :retrieval_policy_version,
                    :retrieval_policy_hash,
                    :retrieval_policy_source,
                    :ranker_mix,
                    :rerank_state,
                    :permission_snapshot_hash,
                    {json_expr(connection, "source_summary")},
                    {json_expr(connection, "score_summary")},
                    :warning_count,
                    :evidence_count,
                    :no_answer_reason,
                    :created_at,
                    :updated_at
                )
                """
            ),
            _retrieval_package_params(refs),
        )
        connection.execute(
            text(
                f"""
                INSERT INTO cx_retrieval_evidence_items (
                    retrieval_package_id,
                    evidence_id,
                    rank,
                    content_object_id,
                    content_version_id,
                    chunk_id,
                    chunk_policy_id,
                    source_anchor,
                    citation_label,
                    evidence_text_sha256,
                    evidence_text_preview,
                    final_score,
                    scores,
                    matched_terms,
                    permission_result,
                    neighbor_context,
                    quality_flags,
                    created_at
                )
                VALUES (
                    :retrieval_package_id,
                    :evidence_id,
                    :rank,
                    :content_object_id,
                    :content_version_id,
                    :chunk_id,
                    :chunk_policy_id,
                    {json_expr(connection, "source_anchor")},
                    :citation_label,
                    :evidence_text_sha256,
                    :evidence_text_preview,
                    :final_score,
                    {json_expr(connection, "scores")},
                    {json_expr(connection, "matched_terms")},
                    {json_expr(connection, "permission_result")},
                    {json_expr(connection, "neighbor_context")},
                    {json_expr(connection, "quality_flags")},
                    :created_at
                )
                """
            ),
            _retrieval_evidence_params(refs),
        )


def _delete_smoke_rows(engine: object, *, refs: dict[str, str]) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM cx_retrieval_evidence_items
                WHERE retrieval_package_id = :retrieval_package_id
                   OR evidence_id = :evidence_id
                """
            ),
            refs,
        )
        connection.execute(
            text(
                """
                DELETE FROM cx_retrieval_packages
                WHERE retrieval_package_id = :retrieval_package_id
                   OR request_id = :request_id
                   OR trace_id = :trace_id
                """
            ),
            refs,
        )
        connection.execute(text("DELETE FROM cx_chunks WHERE chunk_id = :chunk_id"), refs)
        connection.execute(
            text("DELETE FROM cx_chunk_sets WHERE chunk_set_id = :chunk_set_id"),
            refs,
        )
        connection.execute(
            text(
                """
                DELETE FROM cx_extraction_artifacts
                WHERE extraction_artifact_id = :extraction_artifact_id
                """
            ),
            refs,
        )
        connection.execute(
            text(
                """
                DELETE FROM cx_content_objects
                WHERE content_object_id = :content_object_id
                   OR upload_id = :upload_id
                """
            ),
            refs,
        )
        connection.execute(
            text("DELETE FROM cx_source_files WHERE source_file_id = :source_file_id"),
            refs,
        )


def _checks(
    *,
    list_response: dict[str, Any],
    detail_response: dict[str, Any],
    trace_response: dict[str, Any],
    refs: dict[str, str],
    raw_values: list[str],
) -> dict[str, bool]:
    list_packages = list_response.get("retrieval_packages", [])
    detail_evidence = detail_response.get("evidence_items", [])
    first_evidence = detail_evidence[0] if detail_evidence else {}
    trace_items = trace_response.get("timeline", [])
    serialized_responses = json.dumps(
        {
            "list": list_response,
            "detail": detail_response,
            "trace": trace_response,
        },
        ensure_ascii=False,
    )
    return {
        "list_projection_reads_postgres": (
            list_response["_http_status"] == 200
            and list_response.get("projection_schema_version")
            == AG_RETRIEVAL_PACKAGE_OPERATIONS_PROJECTION_SCHEMA_VERSION
            and list_response.get("projection_status") == "READY"
            and list_response.get("source_statuses", {})
            .get(SERVICE_ID, {})
            .get("source_kind")
            == "postgres-read"
        ),
        "list_filter_returns_seeded_package": (
            list_response.get("summary", {}).get("total") == 1
            and [item.get("retrieval_package_id") for item in list_packages]
            == [refs["retrieval_package_id"]]
        ),
        "detail_projection_redacts_evidence": (
            detail_response["_http_status"] == 200
            and detail_response.get("projection_schema_version")
            == AG_RETRIEVAL_PACKAGE_DETAIL_PROJECTION_SCHEMA_VERSION
            and detail_response.get("summary", {}).get("returned_evidence_items") == 1
            and detail_response.get("summary", {}).get(
                "evidence_text_preview_redacted"
            )
            is True
            and first_evidence.get("evidence_text_preview_redacted") is True
            and "evidence_text_preview" not in first_evidence
        ),
        "permission_projection_excludes_principal_id": (
            first_evidence.get("permission_result", {}).get("principal_type")
            == "user"
            and "principal_id" not in first_evidence.get("permission_result", {})
        ),
        "trace_timeline_correlates_package": (
            trace_response["_http_status"] == 200
            and trace_response.get("projection_schema_version")
            == TRACE_TIMELINE_SCHEMA_VERSION
            and any(
                item.get("timeline_item_type") == "retrieval_package"
                and item.get("retrieval_package", {}).get("retrieval_package_id")
                == refs["retrieval_package_id"]
                for item in trace_items
            )
            and trace_response.get("retrieval_package_source_statuses", {})
            .get(SERVICE_ID, {})
            .get("status")
            == "READY"
        ),
        "raw_values_absent_from_ag_evidence": not any(
            value and value in serialized_responses for value in raw_values
        ),
    }


def _execution_failure(
    failure_code: str,
    detail: str,
    *,
    checks: dict[str, bool],
    raw_values: list[str],
) -> dict[str, object]:
    return {
        "failure_code": failure_code,
        "detail": detail,
        "checks": checks,
        "raw_values": raw_values,
    }


def _smoke_refs() -> dict[str, str]:
    run_id = uuid4()
    source_text = (
        "AG retrieval package PostgreSQL smoke source "
        f"{run_id} verifies cross-service read evidence."
    )
    markdown_text = source_text + "\n\nThe AG projection should never emit raw text."
    query_text = "AG retrieval package smoke query " + ("q" * 360)
    evidence_text = "AG retrieval package smoke evidence " + ("e" * 360)
    source_file_id = str(uuid4())
    storage_extension = ".txt"
    return {
        "source_file_id": source_file_id,
        "content_object_id": str(uuid4()),
        "upload_id": str(uuid4()),
        "extraction_artifact_id": str(uuid4()),
        "chunk_set_id": str(uuid4()),
        "chunk_id": str(uuid4()),
        "retrieval_package_id": str(uuid4()),
        "evidence_id": str(uuid4()),
        "request_id": f"ag-retrieval-package-postgres-smoke-{run_id}",
        "trace_id": uuid4().hex,
        "source_text": source_text,
        "markdown_text": markdown_text,
        "query_text": query_text,
        "evidence_text": evidence_text,
        "principal_id": f"smoke-user-{run_id}",
        "source_sha256": _sha256_text(source_text),
        "markdown_sha256": _sha256_text(markdown_text),
        "chunk_text_sha256": _sha256_text(markdown_text),
        "source_storage_key": (
            f"20260809/{_sha256_text(source_text)[:2]}/"
            f"{_sha256_text(source_text)[2:4]}/{source_file_id}{storage_extension}"
        ),
        "source_stored_filename": f"{source_file_id}{storage_extension}",
        "source_stored_extension": storage_extension,
    }


def _source_file_params(refs: dict[str, str]) -> dict[str, object]:
    return {
        "source_file_id": refs["source_file_id"],
        "source_sha256": refs["source_sha256"],
        "size_bytes": len(refs["source_text"].encode("utf-8")),
        "content_type": "text/plain",
        "storage_uri": f"file:///data/nex-platform/cx/source-files/{refs['source_storage_key']}",
        "first_seen_trace_id": refs["trace_id"],
        "storage_backend": "local_filesystem",
        "storage_key": refs["source_storage_key"],
        "stored_filename": refs["source_stored_filename"],
        "stored_extension": refs["source_stored_extension"],
        "checksum_verified_at": CREATED_AT,
        "created_at": CREATED_AT,
    }


def _content_object_params(refs: dict[str, str]) -> dict[str, object]:
    return {
        "content_object_id": refs["content_object_id"],
        "tenant_id": "smoke-tenant",
        "owner_user_id": "smoke-owner",
        "tenant_ref_type": "oa.tenant",
        "tenant_ref_id": "smoke-tenant",
        "owner_subject_ref_type": "oa.user",
        "owner_subject_ref_id": "smoke-owner",
        "uploaded_by_subject_ref_type": "oa.user",
        "uploaded_by_subject_ref_id": "smoke-owner",
        "source_file_id": refs["source_file_id"],
        "source_sha256": refs["source_sha256"],
        "upload_id": refs["upload_id"],
        "original_filename": "ag-retrieval-package-postgres-smoke.txt",
        "content_type": "text/plain",
        "size_bytes": len(refs["source_text"].encode("utf-8")),
        "classification": "internal",
        "lifecycle_status": "ACTIVE",
        "retrieval_policy": _json_dumps({"scope": "smoke"}),
        "created_trace_id": refs["trace_id"],
        "created_at": CREATED_AT,
        "updated_at": CREATED_AT,
    }


def _extraction_artifact_params(refs: dict[str, str]) -> dict[str, object]:
    return {
        "extraction_artifact_id": refs["extraction_artifact_id"],
        "content_object_id": refs["content_object_id"],
        "source_file_id": refs["source_file_id"],
        "artifact_kind": "markdown",
        "status": "SUCCEEDED",
        "extractor_name": "ag_retrieval_package_postgres_smoke",
        "extractor_version": "0179",
        "markdown_sha256": refs["markdown_sha256"],
        "markdown_storage_uri": (
            "file:///data/nex-platform/cx/extracted-markdown/"
            f"20260809/{refs['extraction_artifact_id']}.md"
        ),
        "markdown_char_count": len(refs["markdown_text"]),
        "created_trace_id": refs["trace_id"],
        "created_at": CREATED_AT,
        "updated_at": CREATED_AT,
    }


def _chunk_set_params(refs: dict[str, str]) -> dict[str, object]:
    return {
        "chunk_set_id": refs["chunk_set_id"],
        "content_object_id": refs["content_object_id"],
        "extraction_artifact_id": refs["extraction_artifact_id"],
        "chunk_policy_id": "chunk_1000_100",
        "chunk_size": 1000,
        "chunk_overlap": 100,
        "source_markdown_sha256": refs["markdown_sha256"],
        "chunk_count": 1,
        "created_trace_id": refs["trace_id"],
        "created_at": CREATED_AT,
    }


def _chunk_params(refs: dict[str, str]) -> dict[str, object]:
    return {
        "chunk_id": refs["chunk_id"],
        "chunk_set_id": refs["chunk_set_id"],
        "content_object_id": refs["content_object_id"],
        "ordinal": 0,
        "start_offset": 0,
        "end_offset": len(refs["markdown_text"]),
        "char_count": len(refs["markdown_text"]),
        "text_sha256": refs["chunk_text_sha256"],
        "text_preview": _preview(refs["markdown_text"]),
        "created_at": CREATED_AT,
    }


def _retrieval_package_params(refs: dict[str, str]) -> dict[str, object]:
    return {
        "retrieval_package_id": refs["retrieval_package_id"],
        "retrieval_package_schema_version": "cx_retrieval_context_package.v1",
        "package_hash": _sha256_json(
            {
                "retrieval_package_id": refs["retrieval_package_id"],
                "query": refs["query_text"],
            }
        ),
        "status": "READY",
        "trace_id": refs["trace_id"],
        "request_id": refs["request_id"],
        "query_text_sha256": _sha256_text(refs["query_text"]),
        "query_text_preview": _preview(refs["query_text"]),
        "query_embedding_provided": True,
        "query_embedding_sha256": _sha256_json({"embedding": [0.1, 0.2, 0.3]}),
        "query_embedding_dimension": 3,
        "purpose": "grounded_answer",
        "retrieval_policy_id": "weighted_rrf_vector_bm25_v1",
        "retrieval_policy_version": "2026-08-09",
        "retrieval_policy_hash": _sha256_json({"policy": "weighted_rrf_v1"}),
        "retrieval_policy_source": "ag_registry_active",
        "ranker_mix": "weighted_rrf_vector_bm25_v1",
        "rerank_state": "APPLIED",
        "permission_snapshot_hash": _sha256_json(
            {
                "principal_id": refs["principal_id"],
                "content_object_id": refs["content_object_id"],
            }
        ),
        "source_summary": _json_dumps(
            {
                "source_count": 1,
                "document_count": 1,
                "chunk_count": 1,
                "source_types": ["cx.document"],
            }
        ),
        "score_summary": _json_dumps(
            {
                "best_score": 0.91,
                "score_spread": 0.0,
                "ranker_mix": "weighted_rrf_vector_bm25_v1",
                "rerank_state": "APPLIED",
            }
        ),
        "warning_count": 0,
        "evidence_count": 1,
        "no_answer_reason": None,
        "created_at": CREATED_AT,
        "updated_at": CREATED_AT,
    }


def _retrieval_evidence_params(refs: dict[str, str]) -> dict[str, object]:
    return {
        "retrieval_package_id": refs["retrieval_package_id"],
        "evidence_id": refs["evidence_id"],
        "rank": 1,
        "content_object_id": refs["content_object_id"],
        "content_version_id": refs["markdown_sha256"],
        "chunk_id": refs["chunk_id"],
        "chunk_policy_id": "chunk_1000_100",
        "source_anchor": _json_dumps(
            {
                "type": "character_range",
                "start_offset": 0,
                "end_offset": len(refs["markdown_text"]),
            }
        ),
        "citation_label": "[1]",
        "evidence_text_sha256": _sha256_text(refs["evidence_text"]),
        "evidence_text_preview": _preview(refs["evidence_text"]),
        "final_score": 0.91,
        "scores": _json_dumps(
            {
                "bm25_score": 0.73,
                "vector_score": 0.88,
                "rerank_score": 0.91,
                "final_score": 0.91,
            }
        ),
        "matched_terms": _json_dumps(["retrieval", "postgres", "smoke"]),
        "permission_result": _json_dumps(
            {
                "allowed": True,
                "reason": "owner",
                "principal_type": "user",
                "principal_id": refs["principal_id"],
                "permission": "read",
            }
        ),
        "neighbor_context": _json_dumps([]),
        "quality_flags": _json_dumps(["postgres_smoke_verified"]),
        "created_at": CREATED_AT,
    }


def _json_sql_expression(connection: object, param_name: str) -> str:
    dialect_name = getattr(getattr(connection, "dialect", None), "name", "")
    if dialect_name == "postgresql":
        return f"CAST(:{param_name} AS jsonb)"
    return f":{param_name}"


def _preview(value: str, max_chars: int = 240) -> str:
    return value[:max_chars]


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_text(_json_dumps(value))


def _redaction_safe(evidence: dict[str, object], raw_values: object) -> bool:
    serialized = json.dumps(evidence, ensure_ascii=False)
    banned_values = ["secret", "nuri1004"]
    if isinstance(raw_values, list):
        banned_values.extend(str(value) for value in raw_values if value)
    return not any(value in serialized for value in banned_values)


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    database_env: str | None = None,
    checks: object | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }
    if database_env is not None:
        payload["database_env"] = database_env
    if checks is not None:
        payload["checks"] = checks
    return payload


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ag_retrieval_package_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        counts = evidence["counts"]
        return (
            "ag_retrieval_package_postgres_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']} "
            f"list={counts['list_total']} "
            f"detail_evidence={counts['detail_evidence_items']} "
            f"timeline={counts['trace_timeline_total']}"
        )
    return (
        "ag_retrieval_package_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG retrieval package PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    load_env_file(ROOT / ".env.local")
    evidence = run_ag_retrieval_package_postgres_smoke()
    output = (
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False)
    )
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
