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
AG_PATH = ROOT / "services" / "nex-ag"
CX_PATH = ROOT / "services" / "nex-cx"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(CX_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_ag.operations import (  # noqa: E402
    AG_OPERATIONS_SOURCE_MODE_ENV,
    AG_OPERATIONS_SOURCE_PROFILE_ENV,
    AG_OPERATIONS_SOURCE_SERVICES_ENV,
    attach_ag_operations_source_runtime,
    register_unified_operation_routes,
)
from nex_cx.ingestion import ContentIngestionStore, register_ingestion_routes  # noqa: E402
from nex_cx.processing import (  # noqa: E402
    PROCESSING_EVENT_STARTED,
    PROCESSING_EVENT_SUCCEEDED,
    PROCESSING_WORKER_EVENT_BUSY,
    PROCESSING_WORKER_EVENT_IDLE,
    register_processing_routes,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_engine,
    build_service_app,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_cx_processing_postgres_event_smoke import (  # noqa: E402
    _delete_smoke_processing_events,
    _delete_smoke_worker_heartbeat,
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


SMOKE_ENV = "NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SCHEMA_VERSION = "ag_cross_service_observability_smoke.v1"


def run_ag_cross_service_observability_smoke(
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
            f"{SMOKE_PROFILE_ENV} must be test for cross-service write smoke execution.",
            profile=profile,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        run_service_migrations(SERVICE_ID, database_url=database_url, profile=profile)
        execution = _execute_cross_service_observability_smoke(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPEC.database_env: database_url,
                database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
                AG_OPERATIONS_SOURCE_MODE_ENV: "postgres",
                AG_OPERATIONS_SOURCE_PROFILE_ENV: profile,
                AG_OPERATIONS_SOURCE_SERVICES_ENV: SERVICE_ID,
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


def _execute_cross_service_observability_smoke(
    *,
    database_url: str,
    runtime_environ: dict[str, str],
) -> dict[str, object]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    job_id: str | None = None
    engine = build_engine(database_url)
    with tempfile.TemporaryDirectory(prefix="nex-ag-observability-smoke-") as temp_dir:
        storage_config = _storage_config(Path(temp_dir))
        cx_app = build_service_app(SERVICE_SPEC)
        cx_persistence = attach_service_persistence_runtime(
            cx_app,
            SERVICE_SPEC,
            environ=runtime_environ,
        )
        store = ContentIngestionStore()
        register_ingestion_routes(cx_app, store=store, storage_config=storage_config)
        register_processing_routes(
            cx_app,
            store=store,
            storage_config=storage_config,
            mo_client=StaticMoEmbeddingClient(),
            embedding_alias="smoke-embedding",
            job_queue=cx_persistence.job_queue,
        )
        cx_client = TestClient(cx_app)
        try:
            uploaded = _upload_smoke_document(
                cx_client,
                trace_id=trace_id,
                request_id=request_id,
            )
            response = cx_client.post(
                f"/api/v1/documents/{uploaded['document_id']}/processing/run",
                headers=_service_headers(trace_id=trace_id, request_id=request_id),
            )
            response.raise_for_status()
            pipeline_run = response.json()
            job_id = pipeline_run["job"]["job_id"]

            ag_projection = _read_ag_unified_operations_projection(
                runtime_environ=runtime_environ,
                trace_id=trace_id,
            )
            checks = _cross_service_observability_checks(
                cx_runtime_mode=str(cx_persistence.mode),
                ag_projection=ag_projection,
                job_id=job_id,
                trace_id=trace_id,
            )
            if not all(checks.values()):
                raise RuntimeError("AG cross-service observability smoke checks failed")
            return {
                "pipeline_run_id": pipeline_run["pipeline_run_id"],
                "document_id": uploaded["document_id"],
                "job_id": job_id,
                "event_ids": _projected_event_ids(ag_projection),
                "checks": checks,
            }
        finally:
            _delete_smoke_processing_events(
                engine,
                trace_id=trace_id,
                request_id=request_id,
            )
            _delete_smoke_worker_heartbeat(engine)
            _delete_smoke_processing_jobs(
                engine,
                trace_id=trace_id,
                request_id=request_id,
                job_id=job_id,
            )


def _read_ag_unified_operations_projection(
    *,
    runtime_environ: dict[str, str],
    trace_id: str,
) -> dict[str, object]:
    ag_spec = SERVICE_SPECS["nex-ag"]
    ag_app = build_service_app(ag_spec)
    source_runtime = attach_ag_operations_source_runtime(
        ag_app,
        environ=runtime_environ,
    )
    register_unified_operation_routes(ag_app, registry=source_runtime.registry)
    client = TestClient(ag_app)
    response = client.get(
        "/admin/v1/operations",
        params={
            "service_id": SERVICE_ID,
            "job_status": "SUCCEEDED",
            "job_type": "cx.document_processing",
            "trace_id": trace_id,
            "limit": 50,
        },
        headers=_ag_service_headers(trace_id=trace_id),
    )
    response.raise_for_status()
    projection = response.json()
    projection["ag_source_runtime"] = source_runtime.to_summary()
    return projection


def _cross_service_observability_checks(
    *,
    cx_runtime_mode: str,
    ag_projection: dict[str, object],
    job_id: str,
    trace_id: str,
) -> dict[str, bool]:
    event_types = {
        str(event.get("event_type"))
        for event in _projected_events(ag_projection)
    }
    source_runtime = dict(ag_projection.get("ag_source_runtime", {}))
    source_registry = dict(ag_projection.get("source_registry", {}))
    source_summary = dict(source_registry.get("sources", {})).get(SERVICE_ID, {})
    return {
        "cx_runtime_mode": cx_runtime_mode == "postgres",
        "ag_source_runtime_mode": source_runtime.get("mode") == "postgres",
        "ag_source_runtime_profile": source_runtime.get("profile") == "test",
        "ag_source_registry_present": source_registry.get("service_count") == 1,
        "ag_source_kind": dict(source_summary).get("source_kind") == "postgres-read",
        "projection_ready": ag_projection.get("projection_status") == "READY",
        "job_visible": any(
            job.get("job_id") == job_id and job.get("status") == "SUCCEEDED"
            for job in _projected_jobs(ag_projection)
        ),
        "started_event_visible": PROCESSING_EVENT_STARTED in event_types,
        "succeeded_event_visible": PROCESSING_EVENT_SUCCEEDED in event_types,
        "worker_busy_event_visible": PROCESSING_WORKER_EVENT_BUSY in event_types,
        "worker_idle_event_visible": PROCESSING_WORKER_EVENT_IDLE in event_types,
        "event_trace_filter": all(
            event.get("trace_id") == trace_id
            for event in _projected_events(ag_projection)
        ),
        "redaction_safe": "secret" not in json.dumps(
            ag_projection,
            ensure_ascii=False,
        ),
    }


def _projected_jobs(ag_projection: dict[str, object]) -> list[dict[str, object]]:
    jobs_projection = ag_projection.get("jobs", {})
    if not isinstance(jobs_projection, dict):
        return []
    jobs = jobs_projection.get("jobs", [])
    return jobs if isinstance(jobs, list) else []


def _projected_events(ag_projection: dict[str, object]) -> list[dict[str, object]]:
    events_projection = ag_projection.get("events", {})
    if not isinstance(events_projection, dict):
        return []
    events = events_projection.get("events", [])
    return events if isinstance(events, list) else []


def _projected_event_ids(ag_projection: dict[str, object]) -> list[str]:
    return [
        str(event["event_id"])
        for event in _projected_events(ag_projection)
        if "event_id" in event
    ]


def _ag_service_headers(*, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


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
        return f"ag_cross_service_observability_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ag_cross_service_observability_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']} "
            f"job={evidence['job_id']} events={len(evidence['event_ids'])}"
        )
    return (
        "ag_cross_service_observability_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG cross-service PostgreSQL observability smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_cross_service_observability_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
