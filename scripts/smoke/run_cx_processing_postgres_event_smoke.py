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
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(CX_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_cx.ingestion import ContentIngestionStore, register_ingestion_routes  # noqa: E402
from nex_cx.processing import (  # noqa: E402
    PROCESSING_EVENT_FAILED,
    PROCESSING_EVENT_STARTED,
    PROCESSING_EVENT_SUCCEEDED,
    processing_event_id,
    register_processing_routes,
)
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
    StaticMoEmbeddingClient,
    _delete_smoke_processing_jobs,
    _service_headers,
    _storage_config,
    _upload_smoke_document,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SMOKE_ENV = "NEX_CX_PROCESSING_POSTGRES_EVENT_SMOKE"
SMOKE_PROFILE_ENV = "NEX_CX_PROCESSING_POSTGRES_EVENT_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SCHEMA_VERSION = "cx_processing_postgres_event_smoke.v1"
PROCESSING_EVENT_TYPES = (
    PROCESSING_EVENT_STARTED,
    PROCESSING_EVENT_SUCCEEDED,
    PROCESSING_EVENT_FAILED,
)


def run_cx_processing_postgres_event_smoke(
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
        execution = _execute_processing_event_route_smoke(
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


def _execute_processing_event_route_smoke(
    *,
    database_url: str,
    runtime_environ: dict[str, str],
) -> dict[str, object]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    job_id: str | None = None
    engine = build_engine(database_url)
    with tempfile.TemporaryDirectory(prefix="nex-cx-processing-event-smoke-") as temp_dir:
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
            job_id = pipeline_run["job"]["job_id"]
            stored_events = _read_stored_processing_events(
                engine,
                trace_id=trace_id,
                request_id=request_id,
            )
            checks = {
                "route_succeeded": pipeline_run["status"] == "SUCCEEDED",
                "runtime_mode": persistence.mode == "postgres",
                **_processing_event_checks(
                    stored_events=stored_events,
                    pipeline_run=pipeline_run,
                    document_id=str(uploaded["document_id"]),
                ),
            }
            if not all(checks.values()):
                raise RuntimeError("CX processing PostgreSQL OperationalEvent smoke checks failed")
            return {
                "pipeline_run_id": pipeline_run["pipeline_run_id"],
                "document_id": uploaded["document_id"],
                "job_id": job_id,
                "event_ids": [event["event_id"] for event in stored_events],
                "checks": checks,
            }
        finally:
            _delete_smoke_processing_events(
                engine,
                trace_id=trace_id,
                request_id=request_id,
            )
            _delete_smoke_processing_jobs(
                engine,
                trace_id=trace_id,
                request_id=request_id,
                job_id=job_id,
            )


def _read_stored_processing_events(
    engine: object,
    *,
    trace_id: str,
    request_id: str,
) -> list[dict[str, object]]:
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    event_id,
                    event_type,
                    severity,
                    trace_id,
                    request_id,
                    subject_type,
                    subject_id,
                    message,
                    details,
                    created_at
                FROM service_operational_events
                WHERE service_id = :service_id
                  AND trace_id = :trace_id
                  AND request_id = :request_id
                  AND event_type IN (
                    'cx.processing.started',
                    'cx.processing.succeeded',
                    'cx.processing.failed'
                  )
                ORDER BY created_at ASC, event_type ASC
                """
            ),
            {
                "service_id": SERVICE_ID,
                "trace_id": trace_id,
                "request_id": request_id,
            },
        ).mappings()
    return [_event_from_row(row) for row in rows]


def _processing_event_checks(
    *,
    stored_events: list[dict[str, object]],
    pipeline_run: dict[str, object],
    document_id: str,
) -> dict[str, bool]:
    events_by_type = {str(event["event_type"]): event for event in stored_events}
    started = events_by_type.get(PROCESSING_EVENT_STARTED)
    succeeded = events_by_type.get(PROCESSING_EVENT_SUCCEEDED)
    failed = events_by_type.get(PROCESSING_EVENT_FAILED)
    pipeline_run_id = str(pipeline_run["pipeline_run_id"])
    job = dict(pipeline_run["job"])
    expected_started_id = processing_event_id(
        pipeline_run_id=pipeline_run_id,
        event_type=PROCESSING_EVENT_STARTED,
    )
    expected_succeeded_id = processing_event_id(
        pipeline_run_id=pipeline_run_id,
        event_type=PROCESSING_EVENT_SUCCEEDED,
    )
    return {
        "started_event_persisted": started is not None,
        "succeeded_event_persisted": succeeded is not None,
        "failed_event_absent": failed is None,
        "started_event_id": _event_value(started, "event_id") == expected_started_id,
        "succeeded_event_id": _event_value(succeeded, "event_id") == expected_succeeded_id,
        "started_severity": _event_value(started, "severity") == "INFO",
        "succeeded_severity": _event_value(succeeded, "severity") == "INFO",
        "started_subject": _subject_matches(started, document_id=document_id),
        "succeeded_subject": _subject_matches(succeeded, document_id=document_id),
        "started_details": _event_details(started) == {
            "pipeline_run_id": pipeline_run_id,
            "job_id": job["job_id"],
            "job_status": "RUNNING",
        },
        "succeeded_details": _event_details(succeeded) == {
            "pipeline_run_id": pipeline_run_id,
            "job_id": job["job_id"],
            "job_status": "SUCCEEDED",
            "step_summary": pipeline_run["step_summary"],
        },
        "redaction_safe": _events_are_redaction_safe(stored_events),
    }


def _event_from_row(row: Any) -> dict[str, object]:
    return {
        "event_id": row["event_id"],
        "event_type": row["event_type"],
        "severity": row["severity"],
        "trace_id": row["trace_id"],
        "request_id": row["request_id"],
        "subject_type": row["subject_type"],
        "subject_id": row["subject_id"],
        "message": row["message"],
        "details": _json_loads(row["details"], default={}),
        "created_at": str(row["created_at"]),
    }


def _delete_smoke_processing_events(
    engine: object,
    *,
    trace_id: str,
    request_id: str,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_operational_events
                WHERE service_id = :service_id
                  AND trace_id = :trace_id
                  AND request_id = :request_id
                  AND event_type IN (
                    'cx.processing.started',
                    'cx.processing.succeeded',
                    'cx.processing.failed'
                  )
                """
            ),
            {
                "service_id": SERVICE_ID,
                "trace_id": trace_id,
                "request_id": request_id,
            },
        )


def _event_value(event: dict[str, object] | None, key: str) -> object:
    if event is None:
        return None
    return event.get(key)


def _event_details(event: dict[str, object] | None) -> dict[str, object]:
    if event is None:
        return {}
    details = event.get("details")
    return details if isinstance(details, dict) else {}


def _subject_matches(event: dict[str, object] | None, *, document_id: str) -> bool:
    return (
        event is not None
        and event.get("subject_type") == "cx.document"
        and event.get("subject_id") == document_id
    )


def _events_are_redaction_safe(events: list[dict[str, object]]) -> bool:
    serialized = json.dumps(events, ensure_ascii=False)
    forbidden_fragments = (
        "route-backed durable event lifecycle",
        "CX processing PostgreSQL",
        "provider",
        "api_key",
        "source_text",
    )
    return not any(fragment in serialized for fragment in forbidden_fragments)


def _json_loads(value: Any, *, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return default


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
        return f"cx_processing_postgres_event_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "cx_processing_postgres_event_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']}"
        )
    return (
        "cx_processing_postgres_event_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional CX processing route PostgreSQL OperationalEvent smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_cx_processing_postgres_event_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
