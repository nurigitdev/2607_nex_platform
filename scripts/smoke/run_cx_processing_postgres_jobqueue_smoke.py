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
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(CX_PATH))

from nex_cx.ingestion import (  # noqa: E402
    ContentIngestionStore,
    CxStorageConfig,
    register_ingestion_routes,
)
from nex_cx.processing import register_processing_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_engine,
    build_service_app,
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


SMOKE_ENV = "NEX_CX_PROCESSING_POSTGRES_JOBQUEUE_SMOKE"
SMOKE_PROFILE_ENV = "NEX_CX_PROCESSING_POSTGRES_JOBQUEUE_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]


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
            "model_revision": "smoke-mock-embedding-v1",
            "deployment_id": "cx-processing-postgres-jobqueue-smoke",
            "data": [
                {"object": "embedding", "index": index, "embedding": [0.1, 0.2, 0.3]}
                for index, _ in enumerate(inputs)
            ],
            "usage": {
                "input_tokens": len(inputs),
                "output_tokens": 0,
                "total_tokens": len(inputs),
            },
        }


def run_cx_processing_postgres_jobqueue_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": "cx_processing_postgres_jobqueue_smoke.v1",
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
        execution = _execute_processing_route_smoke(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )
        return {
            "smoke_schema_version": "cx_processing_postgres_jobqueue_smoke.v1",
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            **execution,
        }
    except (MigrationError, ValueError) as exc:
        return _failure(
            "configuration_invalid",
            str(exc),
            profile=profile,
        )
    except Exception as exc:
        return _failure(
            "execution_failed",
            exc.__class__.__name__,
            profile=profile,
        )


def _execute_processing_route_smoke(
    *,
    database_url: str,
    runtime_environ: dict[str, str],
) -> dict[str, object]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    job_id: str | None = None
    engine = build_engine(database_url)
    with tempfile.TemporaryDirectory(prefix="nex-cx-processing-smoke-") as temp_dir:
        storage_config = _storage_config(Path(temp_dir))
        app = build_service_app(SERVICE_SPEC)
        persistence = attach_service_persistence_runtime(
            app,
            SERVICE_SPEC,
            environ=runtime_environ,
        )
        store = ContentIngestionStore()
        register_ingestion_routes(app, store=store, storage_config=storage_config)
        register_processing_routes(
            app,
            store=store,
            storage_config=storage_config,
            mo_client=StaticMoEmbeddingClient(),
            embedding_alias="smoke-embedding",
            job_queue=persistence.job_queue,
        )
        client = TestClient(app)
        try:
            uploaded = _upload_smoke_document(client, trace_id=trace_id, request_id=request_id)
            response = client.post(
                f"/api/v1/documents/{uploaded['document_id']}/processing/run",
                headers=_service_headers(trace_id=trace_id, request_id=request_id),
            )
            response.raise_for_status()
            pipeline_run = response.json()
            job = pipeline_run["job"]
            job_id = job["job_id"]
            stored_job = _read_stored_processing_job(engine, job_id=job_id)
            checks = {
                "route_succeeded": pipeline_run["status"] == "SUCCEEDED",
                "runtime_mode": persistence.mode == "postgres",
                "response_job_succeeded": job["status"] == "SUCCEEDED",
                "stored_job_succeeded": stored_job["status"] == "SUCCEEDED",
                "stored_job_type": stored_job["job_type"] == "cx.document_processing",
                "stored_attempt_count": stored_job["attempt_count"] == 1,
                "stored_subject": stored_job["subject_id"] == uploaded["document_id"],
            }
            if not all(checks.values()):
                raise RuntimeError("cx processing PostgreSQL JobQueue smoke checks failed")
            return {
                "pipeline_run_id": pipeline_run["pipeline_run_id"],
                "document_id": uploaded["document_id"],
                "job_id": job_id,
                "checks": checks,
            }
        finally:
            _delete_smoke_processing_jobs(
                engine,
                trace_id=trace_id,
                request_id=request_id,
                job_id=job_id,
            )


def _upload_smoke_document(
    client: TestClient,
    *,
    trace_id: str,
    request_id: str,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "cx-processing-postgres-jobqueue-smoke.txt",
            "content_type": "text/plain",
            "content_text": (
                "CX processing PostgreSQL JobQueue smoke text "
                f"{request_id} verifies the route-backed durable job lifecycle."
            ),
        },
        headers=_service_headers(trace_id=trace_id, request_id=request_id),
    )
    response.raise_for_status()
    return response.json()


def _service_headers(*, trace_id: str, request_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _storage_config(temp_dir: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=temp_dir,
        source_root=temp_dir / "cx" / "source-files",
        extracted_markdown_root=temp_dir / "cx" / "extracted-markdown",
        extraction_temp_root=temp_dir / "cx" / "extraction-temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def _read_stored_processing_job(engine: object, *, job_id: str) -> dict[str, object]:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT job_id, job_type, status, attempt_count, subject_id
                FROM service_jobs
                WHERE job_id = :job_id
                """
            ),
            {"job_id": job_id},
        ).mappings().first()
    if row is None:
        raise RuntimeError("stored processing job was not found")
    return {
        "job_id": row["job_id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "attempt_count": int(row["attempt_count"]),
        "subject_id": row["subject_id"],
    }


def _delete_smoke_processing_jobs(
    engine: object,
    *,
    trace_id: str,
    request_id: str,
    job_id: str | None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_jobs
                WHERE job_id = :job_id
                   OR (
                        job_type = :job_type
                    AND trace_id = :trace_id
                    AND request_id = :request_id
                   )
                """
            ),
            {
                "job_id": job_id or "",
                "job_type": "cx.document_processing",
                "trace_id": trace_id,
                "request_id": request_id,
            },
        )


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
) -> dict[str, object]:
    return {
        "smoke_schema_version": "cx_processing_postgres_jobqueue_smoke.v1",
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"cx_processing_postgres_jobqueue_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "cx_processing_postgres_jobqueue_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']}"
        )
    return (
        "cx_processing_postgres_jobqueue_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional CX processing route PostgreSQL JobQueue smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_cx_processing_postgres_jobqueue_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
