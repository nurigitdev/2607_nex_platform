#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

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
    build_upload_registration,
)
from nex_cx.processing import (  # noqa: E402
    build_failed_pipeline_step,
    build_pipeline_run_record,
    build_pipeline_step,
    build_queued_pipeline_run_record,
)
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_runtime import (  # noqa: E402
    build_common_job,
    build_engine,
    build_session_factory,
    build_subject_ref,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SMOKE_ENV = "NEX_CX_PROCESSING_POSTGRES_PERSISTENCE_SMOKE"
SMOKE_PROFILE_ENV = "NEX_CX_PROCESSING_POSTGRES_PERSISTENCE_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SCHEMA_VERSION = "cx_processing_postgres_persistence_smoke.v1"
SECRET_SOURCE_TEXT = "CX processing PostgreSQL persistence smoke source should not leak"
SECRET_OUTPUT_PAYLOAD = "CX processing output payload should not leak"
SECRET_ERROR_DETAIL = "CX processing failure detail should not leak"


class SmokeProcessingError(Exception):
    error_code = "cx.processing_smoke_failed"
    detail = SECRET_ERROR_DETAIL
    retryable = False


def run_cx_processing_postgres_persistence_smoke(
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
        execution = _execute_processing_persistence_smoke(database_url=database_url)
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


def _execute_processing_persistence_smoke(*, database_url: str) -> dict[str, object]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    engine = build_engine(database_url)
    repository = SqlAlchemyCxContentRepository(build_session_factory(engine))
    store = ContentIngestionStore(content_repository=repository)
    document_id: str | None = None
    source_file_id: str | None = None
    pipeline_run_ids: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="nex-cx-processing-persistence-smoke-") as temp_dir:
            storage_config = _storage_config(Path(temp_dir))
            document = build_upload_registration(
                {
                    "filename": "cx-processing-postgres-persistence-smoke.txt",
                    "content_type": "text/plain",
                    "content_text": SECRET_SOURCE_TEXT,
                },
                storage_config=storage_config,
                request_id=request_id,
                trace_id=trace_id,
            )
            saved_document = store.save_upload_registration(
                document,
                source_text=SECRET_SOURCE_TEXT,
            )
            document_id = str(saved_document["document_id"])
            refs = store.get_content_ref(document_id)
            source_file_id = refs["source_file_id"] if refs is not None else None

            queued_run_id = str(uuid4())
            queued_at = "2026-08-10T00:00:00Z"
            queued_job = _processing_job(
                document_id=document_id,
                pipeline_run_id=queued_run_id,
                request_id=request_id,
                trace_id=trace_id,
                status="QUEUED",
                created_at=queued_at,
            )
            queued = build_queued_pipeline_run_record(
                document_id=document_id,
                pipeline_run_id=queued_run_id,
                request_id=request_id,
                trace_id=trace_id,
                queued_at=queued_at,
                job=queued_job,
            )
            store.save_document_processing_run(queued)
            pipeline_run_ids.append(queued_run_id)
            stored_queued = _read_stored_processing_run(
                engine,
                pipeline_run_id=queued_run_id,
            )

            success_step = build_pipeline_step(
                "extraction",
                status="SUCCEEDED",
                output={
                    "document_id": document_id,
                    "private_payload": SECRET_OUTPUT_PAYLOAD,
                },
            )
            succeeded_job = _processing_job(
                document_id=document_id,
                pipeline_run_id=queued_run_id,
                request_id=request_id,
                trace_id=trace_id,
                status="SUCCEEDED",
                created_at=queued_at,
                updated_at="2026-08-10T00:00:02Z",
                attempt_count=1,
            )
            succeeded = build_pipeline_run_record(
                document_id=document_id,
                pipeline_run_id=queued_run_id,
                request_id=request_id,
                trace_id=trace_id,
                started_at="2026-08-10T00:00:01Z",
                steps=[success_step],
                status="SUCCEEDED",
                job=succeeded_job,
            )
            succeeded["completed_at"] = "2026-08-10T00:00:02Z"
            succeeded["updated_at"] = "2026-08-10T00:00:02Z"
            store.save_document_processing_run(succeeded)
            stored_succeeded = _read_stored_processing_run(
                engine,
                pipeline_run_id=queued_run_id,
            )

            failed_run_id = str(uuid4())
            failed_step = build_failed_pipeline_step("summary", SmokeProcessingError())
            failed_job = _processing_job(
                document_id=document_id,
                pipeline_run_id=failed_run_id,
                request_id=request_id,
                trace_id=trace_id,
                status="FAILED",
                created_at="2026-08-10T00:00:03Z",
                updated_at="2026-08-10T00:00:04Z",
                attempt_count=1,
            )
            failed = build_pipeline_run_record(
                document_id=document_id,
                pipeline_run_id=failed_run_id,
                request_id=request_id,
                trace_id=trace_id,
                started_at="2026-08-10T00:00:03Z",
                steps=[failed_step],
                status="FAILED",
                job=failed_job,
            )
            failed["completed_at"] = "2026-08-10T00:00:04Z"
            failed["updated_at"] = "2026-08-10T00:00:04Z"
            store.save_document_processing_run(failed)
            pipeline_run_ids.append(failed_run_id)
            stored_failed = _read_stored_processing_run(
                engine,
                pipeline_run_id=failed_run_id,
            )

            round_trip = repository.get_processing_run_record(queued_run_id)
            latest = repository.get_latest_processing_run_record(document_id)
            dump = _read_smoke_processing_dump(
                engine,
                pipeline_run_ids=pipeline_run_ids,
            )
            expected_output_hash = _sha256_json(
                {
                    "type": "cx.extraction",
                    "id": document_id,
                    "document_id": document_id,
                }
            )
            checks = {
                "queued_run_persisted": stored_queued["status"] == "QUEUED",
                "queued_step_count_zero": stored_queued["stored_step_count"] == 0,
                "queued_run_upserted_to_succeeded": stored_succeeded["status"] == "SUCCEEDED",
                "succeeded_step_persisted": stored_succeeded["stored_step_count"] == 1,
                "output_ref_hash_persisted": (
                    stored_succeeded["output_ref_hash"] == expected_output_hash
                ),
                "failed_step_persisted": stored_failed["status"] == "FAILED"
                and stored_failed["stored_step_count"] == 1,
                "failed_error_hash_persisted": (
                    stored_failed["error_detail_sha256"] == _sha256_text(SECRET_ERROR_DETAIL)
                ),
                "repository_round_trip": round_trip is not None
                and round_trip["status"] == "SUCCEEDED",
                "latest_round_trip": latest is not None
                and latest["pipeline_run_id"] == failed_run_id,
                "raw_payload_absent": _redaction_safe(
                    dump,
                    forbidden_fragments=[
                        SECRET_SOURCE_TEXT,
                        SECRET_OUTPUT_PAYLOAD,
                        SECRET_ERROR_DETAIL,
                    ],
                ),
            }
            if not all(checks.values()):
                raise RuntimeError("CX processing PostgreSQL persistence smoke checks failed")
            return {
                "document_id": document_id,
                "succeeded_pipeline_run_id": queued_run_id,
                "failed_pipeline_run_id": failed_run_id,
                "step_count": (
                    stored_succeeded["stored_step_count"]
                    + stored_failed["stored_step_count"]
                ),
                "checks": checks,
            }
    finally:
        _delete_smoke_processing_persistence_rows(
            engine,
            pipeline_run_ids=pipeline_run_ids,
            document_id=document_id,
            source_file_id=source_file_id,
        )


def _processing_job(
    *,
    document_id: str,
    pipeline_run_id: str,
    request_id: str,
    trace_id: str,
    status: str,
    created_at: str,
    updated_at: str | None = None,
    attempt_count: int = 0,
) -> dict[str, Any]:
    job = build_common_job(
        job_id=str(uuid4()),
        job_type="cx.document_processing",
        trace_id=trace_id,
        request_id=request_id,
        subject_ref=build_subject_ref("cx.document", document_id),
        idempotency_key=pipeline_run_id,
        created_at=created_at,
        status=status,
        links={"document": f"/api/v1/documents/{document_id}"},
    )
    job["attempt_count"] = attempt_count
    job["updated_at"] = updated_at or created_at
    return job


def _read_stored_processing_run(
    engine: object,
    *,
    pipeline_run_id: str,
) -> dict[str, object]:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    run.pipeline_run_id,
                    run.document_id,
                    run.status,
                    run.job_status,
                    run.step_total,
                    run.step_succeeded,
                    run.step_failed,
                    step.output_ref_hash,
                    step.error_detail_sha256,
                    count(step.step_id) OVER (
                        PARTITION BY run.pipeline_run_id
                    ) AS stored_step_count
                FROM cx_document_processing_runs AS run
                LEFT JOIN cx_document_processing_steps AS step
                  ON step.pipeline_run_id = run.pipeline_run_id
                WHERE run.pipeline_run_id = :pipeline_run_id
                ORDER BY step.step_order ASC
                """
            ),
            {"pipeline_run_id": pipeline_run_id},
        ).mappings().first()
    if row is None:
        raise RuntimeError("stored processing run was not found")
    return {
        "pipeline_run_id": str(row["pipeline_run_id"]),
        "document_id": str(row["document_id"]),
        "status": row["status"],
        "job_status": row["job_status"],
        "step_total": int(row["step_total"]),
        "step_succeeded": int(row["step_succeeded"]),
        "step_failed": int(row["step_failed"]),
        "output_ref_hash": row["output_ref_hash"],
        "error_detail_sha256": row["error_detail_sha256"],
        "stored_step_count": int(row["stored_step_count"] or 0),
    }


def _read_smoke_processing_dump(
    engine: object,
    *,
    pipeline_run_ids: list[str],
) -> str:
    rows: list[object] = []
    with engine.begin() as connection:
        for pipeline_run_id in pipeline_run_ids:
            rows.extend(
                connection.execute(
                    text(
                        """
                        SELECT
                            status,
                            job_subject_ref,
                            job_links,
                            step_total,
                            step_succeeded,
                            step_failed
                        FROM cx_document_processing_runs
                        WHERE pipeline_run_id = :pipeline_run_id
                        """
                    ),
                    {"pipeline_run_id": pipeline_run_id},
                ).fetchall()
            )
            rows.extend(
                connection.execute(
                    text(
                        """
                        SELECT
                            step_id,
                            status,
                            output_ref_type,
                            output_ref_id,
                            output_ref_document_id,
                            output_ref_hash,
                            error_code,
                            error_detail_sha256,
                            error_retryable
                        FROM cx_document_processing_steps
                        WHERE pipeline_run_id = :pipeline_run_id
                        ORDER BY step_order ASC
                        """
                    ),
                    {"pipeline_run_id": pipeline_run_id},
                ).fetchall()
            )
    return str(rows)


def _delete_smoke_processing_persistence_rows(
    engine: object,
    *,
    pipeline_run_ids: list[str],
    document_id: str | None,
    source_file_id: str | None,
) -> None:
    with engine.begin() as connection:
        for pipeline_run_id in pipeline_run_ids:
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
        if document_id is not None:
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


def _redaction_safe(value: object, *, forbidden_fragments: list[str]) -> bool:
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    return not any(fragment in serialized for fragment in forbidden_fragments)


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
        return f"cx_processing_postgres_persistence_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "cx_processing_postgres_persistence_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']}"
        )
    return (
        "cx_processing_postgres_persistence_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional CX processing run PostgreSQL persistence smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_cx_processing_postgres_persistence_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
