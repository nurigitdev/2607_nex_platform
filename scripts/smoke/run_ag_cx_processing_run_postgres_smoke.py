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

from nex_ag.processing_operations import (  # noqa: E402
    AG_CX_PROCESSING_RUN_DETAIL_PROJECTION_SCHEMA_VERSION,
    AG_CX_PROCESSING_RUN_OPERATIONS_PROJECTION_SCHEMA_VERSION,
    SqlAlchemyCxProcessingRunOperationsStore,
    register_cx_processing_run_operation_routes,
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


SMOKE_ENV = "NEX_AG_CX_PROCESSING_RUN_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AG_CX_PROCESSING_RUN_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SCHEMA_VERSION = "ag_cx_processing_run_postgres_smoke.v1"
CREATED_AT = "2026-08-10T00:00:00Z"
UPDATED_AT = "2026-08-10T00:02:10Z"


def run_ag_cx_processing_run_postgres_smoke(
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
        execution = _execute_ag_cx_processing_run_postgres_smoke(
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
                "AG CX processing run PostgreSQL smoke evidence leaked private data.",
                profile=profile,
                database_env=database_env,
            )
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_ag_cx_processing_run_postgres_smoke(
    *,
    database_url: str,
    database_env: str,
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    env = environ if environ is not None else os.environ
    pool_settings = database_pool_settings(SERVICE_ID, workload="api", environ=env)
    engine = build_engine(database_url, pool_settings=pool_settings)
    refs = _smoke_refs()
    raw_values = [refs["source_text"], refs["raw_error_detail"]]
    _delete_smoke_rows(engine, refs=refs)
    try:
        _seed_processing_rows(engine, refs=refs)
        store = SqlAlchemyCxProcessingRunOperationsStore(
            build_session_factory(engine),
            database_env=database_env,
            redacted_database_url=redact_database_url(database_url),
        )
        client = _build_ag_client(store=store)
        list_response = _get_json(
            client,
            "/admin/v1/operations/cx-processing-runs",
            params={
                "service_id": SERVICE_ID,
                "document_id": refs["content_object_id"],
                "status": "FAILED",
                "trace_id": refs["trace_id"],
                "include_steps": "false",
                "limit": "5",
            },
            trace_id=refs["trace_id"],
            request_id=refs["request_id"],
        )
        detail_response = _get_json(
            client,
            f"/admin/v1/operations/cx-processing-runs/{refs['pipeline_run_id']}",
            params={"service_id": SERVICE_ID},
            trace_id=refs["trace_id"],
            request_id=refs["request_id"],
        )
        checks = _checks(
            list_response=list_response,
            detail_response=detail_response,
            refs=refs,
            raw_values=raw_values,
        )
        if not all(checks.values()):
            return _execution_failure(
                "checks_failed",
                "AG CX processing run PostgreSQL smoke checks failed.",
                checks=checks,
                raw_values=raw_values,
            )
        return {
            "pipeline_run_id": refs["pipeline_run_id"],
            "request_id": refs["request_id"],
            "trace_id": refs["trace_id"],
            "projection_versions": {
                "list": list_response.get("projection_schema_version"),
                "detail": detail_response.get("projection_schema_version"),
            },
            "http_statuses": {
                "list": list_response["_http_status"],
                "detail": detail_response["_http_status"],
            },
            "counts": {
                "list_total": list_response.get("summary", {}).get("total"),
                "detail_steps": detail_response.get("summary", {}).get(
                    "returned_step_count"
                ),
                "detail_error_hashes": detail_response.get("summary", {}).get(
                    "error_hash_count"
                ),
            },
            "checks": checks,
            "raw_values": raw_values,
        }
    finally:
        _delete_smoke_rows(engine, refs=refs)


def _build_ag_client(
    *,
    store: SqlAlchemyCxProcessingRunOperationsStore,
) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_cx_processing_run_operation_routes(app, stores={SERVICE_ID: store})
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


def _seed_processing_rows(engine: object, *, refs: dict[str, str]) -> None:
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
                f"""
                INSERT INTO cx_document_processing_runs (
                    pipeline_run_id,
                    pipeline_schema_version,
                    document_id,
                    status,
                    trace_id,
                    request_id,
                    job_id,
                    job_type,
                    job_status,
                    job_attempt_count,
                    job_max_attempts,
                    job_retryable,
                    job_subject_ref,
                    job_links,
                    step_total,
                    step_succeeded,
                    step_skipped,
                    step_failed,
                    queued_at,
                    started_at,
                    completed_at,
                    updated_at
                )
                VALUES (
                    :pipeline_run_id,
                    :pipeline_schema_version,
                    :document_id,
                    :status,
                    :trace_id,
                    :request_id,
                    :job_id,
                    :job_type,
                    :job_status,
                    :job_attempt_count,
                    :job_max_attempts,
                    :job_retryable,
                    {json_expr(connection, "job_subject_ref")},
                    {json_expr(connection, "job_links")},
                    :step_total,
                    :step_succeeded,
                    :step_skipped,
                    :step_failed,
                    :queued_at,
                    :started_at,
                    :completed_at,
                    :updated_at
                )
                """
            ),
            _processing_run_params(refs),
        )
        for params in _processing_step_params(refs):
            connection.execute(
                text(
                    """
                    INSERT INTO cx_document_processing_steps (
                        pipeline_run_id,
                        step_order,
                        step_id,
                        status,
                        output_ref_type,
                        output_ref_id,
                        output_ref_document_id,
                        output_ref_hash,
                        error_code,
                        error_detail_sha256,
                        error_retryable,
                        created_at
                    )
                    VALUES (
                        :pipeline_run_id,
                        :step_order,
                        :step_id,
                        :status,
                        :output_ref_type,
                        :output_ref_id,
                        :output_ref_document_id,
                        :output_ref_hash,
                        :error_code,
                        :error_detail_sha256,
                        :error_retryable,
                        :created_at
                    )
                    """
                ),
                params,
            )


def _delete_smoke_rows(engine: object, *, refs: dict[str, str]) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM cx_document_processing_steps
                WHERE pipeline_run_id = :pipeline_run_id
                """
            ),
            refs,
        )
        connection.execute(
            text(
                """
                DELETE FROM cx_document_processing_runs
                WHERE pipeline_run_id = :pipeline_run_id
                   OR request_id = :request_id
                   OR trace_id = :trace_id
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
    refs: dict[str, str],
    raw_values: list[str],
) -> dict[str, bool]:
    list_runs = list_response.get("processing_runs", [])
    detail_run = detail_response.get("processing_run", {})
    detail_steps = detail_run.get("steps", [])
    failed_step = detail_steps[1] if len(detail_steps) > 1 else {}
    serialized_responses = json.dumps(
        {"list": list_response, "detail": detail_response},
        ensure_ascii=False,
    )
    return {
        "list_projection_reads_postgres": (
            list_response["_http_status"] == 200
            and list_response.get("projection_schema_version")
            == AG_CX_PROCESSING_RUN_OPERATIONS_PROJECTION_SCHEMA_VERSION
            and list_response.get("projection_status") == "READY"
            and list_response.get("source_statuses", {})
            .get(SERVICE_ID, {})
            .get("source_kind")
            == "postgres-read"
        ),
        "list_filter_returns_seeded_run": (
            list_response.get("summary", {}).get("total") == 1
            and [item.get("pipeline_run_id") for item in list_runs]
            == [refs["pipeline_run_id"]]
        ),
        "detail_projection_includes_safe_steps": (
            detail_response["_http_status"] == 200
            and detail_response.get("projection_schema_version")
            == AG_CX_PROCESSING_RUN_DETAIL_PROJECTION_SCHEMA_VERSION
            and detail_response.get("summary", {}).get("returned_step_count") == 2
            and failed_step.get("status") == "FAILED"
            and failed_step.get("error_detail_sha256")
            == _sha256_text(refs["raw_error_detail"])
            and "error_detail" not in failed_step
        ),
        "detail_source_status_ready": (
            detail_response.get("source_status", {}).get("status") == "READY"
            and detail_response.get("source_status", {}).get("source_kind")
            == "postgres-read"
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
        "AG CX processing run PostgreSQL smoke source "
        f"{run_id} verifies cross-service read evidence."
    )
    raw_error_detail = (
        "AG CX processing run raw provider error detail "
        f"{run_id} must never appear in AG responses."
    )
    source_file_id = str(uuid4())
    storage_extension = ".txt"
    source_sha256 = _sha256_text(source_text)
    return {
        "source_file_id": source_file_id,
        "content_object_id": str(uuid4()),
        "upload_id": str(uuid4()),
        "pipeline_run_id": str(uuid4()),
        "request_id": f"ag-cx-processing-run-postgres-smoke-{run_id}",
        "trace_id": uuid4().hex,
        "source_text": source_text,
        "raw_error_detail": raw_error_detail,
        "source_sha256": source_sha256,
        "source_storage_key": (
            f"20260810/{source_sha256[:2]}/{source_sha256[2:4]}/"
            f"{source_file_id}{storage_extension}"
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
        "storage_uri": (
            "file:///data/nex-platform/cx/source-files/"
            f"{refs['source_storage_key']}"
        ),
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
        "original_filename": "ag-cx-processing-run-postgres-smoke.txt",
        "content_type": "text/plain",
        "size_bytes": len(refs["source_text"].encode("utf-8")),
        "classification": "internal",
        "lifecycle_status": "ACTIVE",
        "retrieval_policy": _json_dumps({"scope": "smoke"}),
        "created_trace_id": refs["trace_id"],
        "created_at": CREATED_AT,
        "updated_at": CREATED_AT,
    }


def _processing_run_params(refs: dict[str, str]) -> dict[str, object]:
    return {
        "pipeline_run_id": refs["pipeline_run_id"],
        "pipeline_schema_version": "cx_document_processing_pipeline.v1",
        "document_id": refs["content_object_id"],
        "status": "FAILED",
        "trace_id": refs["trace_id"],
        "request_id": refs["request_id"],
        "job_id": f"job-{refs['pipeline_run_id']}",
        "job_type": "cx.document_processing",
        "job_status": "FAILED",
        "job_attempt_count": 1,
        "job_max_attempts": 3,
        "job_retryable": True,
        "job_subject_ref": _json_dumps(
            {"type": "document", "id": refs["content_object_id"]}
        ),
        "job_links": _json_dumps(
            {
                "processing": (
                    f"/api/v1/documents/{refs['content_object_id']}/processing"
                )
            }
        ),
        "step_total": 2,
        "step_succeeded": 1,
        "step_skipped": 0,
        "step_failed": 1,
        "queued_at": CREATED_AT,
        "started_at": "2026-08-10T00:01:00Z",
        "completed_at": "2026-08-10T00:02:00Z",
        "updated_at": UPDATED_AT,
    }


def _processing_step_params(refs: dict[str, str]) -> list[dict[str, object]]:
    return [
        {
            "pipeline_run_id": refs["pipeline_run_id"],
            "step_order": 1,
            "step_id": "extract_text",
            "status": "SUCCEEDED",
            "output_ref_type": "text_extraction",
            "output_ref_id": f"text-extraction-{refs['pipeline_run_id']}",
            "output_ref_document_id": refs["content_object_id"],
            "output_ref_hash": _sha256_text(refs["source_text"]),
            "error_code": None,
            "error_detail_sha256": None,
            "error_retryable": None,
            "created_at": "2026-08-10T00:01:30Z",
        },
        {
            "pipeline_run_id": refs["pipeline_run_id"],
            "step_order": 2,
            "step_id": "build_embedding_index",
            "status": "FAILED",
            "output_ref_type": None,
            "output_ref_id": None,
            "output_ref_document_id": refs["content_object_id"],
            "output_ref_hash": None,
            "error_code": "cx.embedding.provider_unavailable",
            "error_detail_sha256": _sha256_text(refs["raw_error_detail"]),
            "error_retryable": True,
            "created_at": "2026-08-10T00:02:00Z",
        },
    ]


def _json_sql_expression(connection: object, param_name: str) -> str:
    dialect_name = getattr(getattr(connection, "dialect", None), "name", "")
    if dialect_name == "postgresql":
        return f"CAST(:{param_name} AS jsonb)"
    return f":{param_name}"


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
        return f"ag_cx_processing_run_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        counts = evidence["counts"]
        return (
            "ag_cx_processing_run_postgres_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']} "
            f"list={counts['list_total']} "
            f"detail_steps={counts['detail_steps']} "
            f"error_hashes={counts['detail_error_hashes']}"
        )
    return (
        "ag_cx_processing_run_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG CX processing run PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    load_env_file(ROOT / ".env.local")
    evidence = run_ag_cx_processing_run_postgres_smoke()
    output = (
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False)
    )
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
