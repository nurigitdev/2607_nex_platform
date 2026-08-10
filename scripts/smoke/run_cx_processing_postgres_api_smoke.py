#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient


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
    ContentIngestionStore,
    build_upload_registration,
    register_ingestion_routes,
)
from nex_cx.processing import (  # noqa: E402
    build_failed_pipeline_step,
    build_queued_pipeline_run_record,
    build_pipeline_run_record,
    register_processing_routes,
)
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_runtime import (  # noqa: E402
    attach_service_persistence_runtime,
    build_engine,
    build_service_app,
    load_env_file,
    redact_database_url,
)
from run_cx_processing_postgres_jobqueue_smoke import (  # noqa: E402
    SERVICE_ID,
    SERVICE_SPEC,
    _service_headers,
    _storage_config,
)
from run_cx_processing_postgres_persistence_smoke import (  # noqa: E402
    _delete_smoke_processing_persistence_rows,
    _processing_job,
    _redaction_safe,
    _sha256_text,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SMOKE_ENV = "NEX_CX_PROCESSING_POSTGRES_API_SMOKE"
SMOKE_PROFILE_ENV = "NEX_CX_PROCESSING_POSTGRES_API_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SCHEMA_VERSION = "cx_processing_postgres_api_smoke.v1"
SECRET_SOURCE_TEXT = "CX processing PostgreSQL API smoke source should not leak"
SECRET_ERROR_DETAIL = "CX processing API smoke failure detail should not leak"


class SmokeProcessingApiError(Exception):
    error_code = "cx.processing_api_smoke_failed"
    detail = SECRET_ERROR_DETAIL
    retryable = False


def run_cx_processing_postgres_api_smoke(
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
        run_service_migrations(SERVICE_ID, database_url=database_url, profile=profile)
        execution = _execute_processing_api_smoke(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            **execution,
        }
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_processing_api_smoke(
    *,
    database_url: str,
    runtime_environ: dict[str, str],
) -> dict[str, object]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    failed_run_id = str(uuid4())
    memory_run_id = str(uuid4())
    document_id: str | None = None
    source_file_id: str | None = None
    engine = build_engine(database_url)
    with tempfile.TemporaryDirectory(prefix="nex-cx-processing-api-smoke-") as temp_dir:
        storage_config = _storage_config(Path(temp_dir))
        app = build_service_app(SERVICE_SPEC)
        persistence = attach_service_persistence_runtime(
            app,
            SERVICE_SPEC,
            environ=runtime_environ,
        )
        if persistence.api_session_factory is None:
            raise RuntimeError("CX PostgreSQL API smoke session factory is unavailable")

        repository = SqlAlchemyCxContentRepository(
            persistence.api_session_factory,
            local_source_root=storage_config.source_root,
        )
        store = ContentIngestionStore(content_repository=repository)
        register_ingestion_routes(app, store=store, storage_config=storage_config)
        register_processing_routes(
            app,
            store=store,
            storage_config=storage_config,
            job_queue=persistence.job_queue,
            processing_run_repository=repository,
        )
        client = TestClient(app)
        try:
            source_text = f"{SECRET_SOURCE_TEXT} request={request_id}"
            document = build_upload_registration(
                {
                    "filename": "cx-processing-postgres-api-smoke.txt",
                    "content_type": "text/plain",
                    "content_text": source_text,
                },
                storage_config=storage_config,
                request_id=request_id,
                trace_id=trace_id,
            )
            saved_document = store.save_upload_registration(
                document,
                source_text=source_text,
            )
            document_id = str(saved_document["document_id"])
            refs = store.get_content_ref(document_id)
            source_file_id = refs["source_file_id"] if refs is not None else None

            failed_step = build_failed_pipeline_step(
                "summary",
                SmokeProcessingApiError(),
            )
            failed_job = _processing_job(
                document_id=document_id,
                pipeline_run_id=failed_run_id,
                request_id=request_id,
                trace_id=trace_id,
                status="FAILED",
                created_at="2026-08-10T00:10:00Z",
                updated_at="2026-08-10T00:10:01Z",
                attempt_count=1,
            )
            failed_run = build_pipeline_run_record(
                document_id=document_id,
                pipeline_run_id=failed_run_id,
                request_id=request_id,
                trace_id=trace_id,
                started_at="2026-08-10T00:10:00Z",
                steps=[failed_step],
                status="FAILED",
                job=failed_job,
            )
            failed_run["completed_at"] = "2026-08-10T00:10:01Z"
            failed_run["updated_at"] = "2026-08-10T00:10:01Z"
            store.save_document_processing_run(failed_run)

            memory_decoy_job = _processing_job(
                document_id=document_id,
                pipeline_run_id=memory_run_id,
                request_id=request_id,
                trace_id=trace_id,
                status="QUEUED",
                created_at="2026-08-10T00:10:02Z",
            )
            memory_decoy = build_queued_pipeline_run_record(
                document_id=document_id,
                pipeline_run_id=memory_run_id,
                request_id=request_id,
                trace_id=trace_id,
                queued_at="2026-08-10T00:10:02Z",
                job=memory_decoy_job,
            )
            store.document_processing_runs[memory_run_id] = memory_decoy
            store.latest_processing_run_ids_by_document[document_id] = memory_run_id

            response = client.get(
                f"/api/v1/documents/{document_id}/processing",
                headers=_service_headers(trace_id=trace_id, request_id=request_id),
            )
            response.raise_for_status()
            payload = response.json()
            latest = repository.get_latest_processing_run_record(document_id)
            checks = {
                "api_status_ok": response.status_code == 200,
                "runtime_mode": persistence.mode == "postgres",
                "persisted_projection_schema": payload.get(
                    "processing_run_schema_version"
                )
                == "cx_document_processing_run.persistence.v1",
                "latest_pipeline_run_returned": payload.get("pipeline_run_id")
                == failed_run_id,
                "memory_fallback_bypassed": payload.get("pipeline_run_id")
                != memory_run_id
                and "job" not in payload,
                "job_id_projected": payload.get("job_id") == failed_job["job_id"],
                "steps_included": payload.get("steps_included") is True,
                "failed_step_projected": _failed_step_projected(payload),
                "failed_error_hash_projected": _failed_error_hash_projected(payload),
                "repository_latest_round_trip": latest is not None
                and latest["pipeline_run_id"] == failed_run_id,
                "raw_payload_absent": _redaction_safe(
                    payload,
                    forbidden_fragments=[
                        SECRET_SOURCE_TEXT,
                        SECRET_ERROR_DETAIL,
                    ],
                ),
            }
            if not all(checks.values()):
                raise RuntimeError("CX processing PostgreSQL API smoke checks failed")
            return {
                "document_id": document_id,
                "pipeline_run_id": failed_run_id,
                "step_count": len(payload.get("steps", [])),
                "checks": checks,
            }
        finally:
            _delete_smoke_processing_persistence_rows(
                engine,
                pipeline_run_ids=[failed_run_id],
                document_id=document_id,
                source_file_id=source_file_id,
            )


def _failed_step_projected(payload: dict[str, object]) -> bool:
    steps = payload.get("steps")
    return (
        isinstance(steps, list)
        and len(steps) == 1
        and isinstance(steps[0], dict)
        and steps[0].get("step_id") == "summary"
        and steps[0].get("status") == "FAILED"
    )


def _failed_error_hash_projected(payload: dict[str, object]) -> bool:
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps or not isinstance(steps[0], dict):
        return False
    return steps[0].get("error_detail_sha256") == _sha256_text(SECRET_ERROR_DETAIL)


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
        return f"cx_processing_postgres_api_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "cx_processing_postgres_api_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']}"
        )
    return (
        "cx_processing_postgres_api_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional CX processing service API PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_cx_processing_postgres_api_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
