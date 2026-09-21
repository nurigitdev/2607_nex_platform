#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "db",
):
    sys.path.insert(0, str(path))

from nex_cx.ingestion import (  # noqa: E402
    ContentIngestionStore,
    CxStorageConfig,
    UPLOAD_OWNER_RESOLVER_DISABLED,
    register_ingestion_routes,
)
from nex_cx.ingestion_operations import (  # noqa: E402
    register_ingestion_operations_routes,
)
from nex_cx.ingestion_orchestration import claim_ingestion_run  # noqa: E402
from nex_cx.ingestion_orchestration_repository import (  # noqa: E402
    SqlAlchemyIngestionRunRepository,
)
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_runtime import (  # noqa: E402
    CX_INGESTION_LEASE_RECOVERED_EVENT,
    SERVICE_SPECS,
    OperationalEventEmitter,
    attach_service_persistence_runtime,
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


SCHEMA_VERSION = "cx_ingestion_operations_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_INGESTION_OPERATIONS_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_CX_INGESTION_OPERATIONS_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
MIGRATION_VERSION = "0923_cx_ingest_run_persistence"
TENANT_ID = "s93-postgres-tenant"
OWNER_ID = "s93-postgres-owner"
OTHER_OWNER_ID = "s93-postgres-other-owner"


def run_cx_ingestion_operations_postgres_smoke(
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
        return _failure(
            "profile_not_allowed",
            f"{PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
        )

    database_url = ""
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
        execution = _execute_ingestion_operations_smoke(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )
        failed_checks = execution.get("failed_checks") or []
        if failed_checks:
            return _failure(
                "ingestion_operations_smoke_failed",
                ",".join(str(item) for item in failed_checks),
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
    except (MigrationError, OSError, ValueError) as exc:
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_url=database_url),
            profile=profile,
        )
    except Exception as exc:
        return _failure(
            "execution_failed",
            exc.__class__.__name__,
            profile=profile,
        )


def _execute_ingestion_operations_smoke(  # pragma: no cover - protected PostgreSQL evidence
    *,
    database_url: str,
    runtime_environ: Mapping[str, str],
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    private_source = f"private-s93-source-{request_id}"
    document_id: str | None = None
    source_file_id: str | None = None
    job_id: str | None = None
    run_id: str | None = None
    event_id: str | None = None
    checks: dict[str, bool] = {}
    app = build_service_app(SERVICE_SPEC)
    runtime = attach_service_persistence_runtime(
        app,
        SERVICE_SPEC,
        environ=runtime_environ,
    )
    if runtime.api_session_factory is None or runtime.api_engine is None:
        raise RuntimeError("CX PostgreSQL API persistence runtime is unavailable")

    run_repository = SqlAlchemyIngestionRunRepository(
        runtime.api_session_factory,
        database_env=runtime.database_env,
        redacted_database_url=runtime.redacted_database_url,
    )
    with tempfile.TemporaryDirectory(prefix="nex-cx-ingestion-operations-") as temp_dir:
        storage_config = _storage_config(Path(temp_dir))
        content_repository = SqlAlchemyCxContentRepository(
            runtime.api_session_factory,
            local_source_root=storage_config.source_root,
        )
        store = ContentIngestionStore(content_repository=content_repository)
        register_ingestion_routes(
            app,
            store=store,
            storage_config=storage_config,
            owner_resolver_mode=UPLOAD_OWNER_RESOLVER_DISABLED,
            job_queue=runtime.job_queue,
            ingestion_run_repository=run_repository,
        )
        register_ingestion_operations_routes(
            app,
            job_queue=runtime.job_queue,
            run_repository=run_repository,
            event_emitter=OperationalEventEmitter(
                service_id=SERVICE_ID,
                store=runtime.operational_event_store,
            ),
        )

        try:
            with TestClient(app) as client:
                service_headers = _service_headers(
                    trace_id=trace_id,
                    request_id=request_id,
                )
                owner_headers = {
                    **service_headers,
                    "X-NEX-Tenant-ID": TENANT_ID,
                    "X-NEX-Subject-ID": OWNER_ID,
                }
                upload = client.post(
                    "/api/v1/documents/uploads",
                    headers=owner_headers,
                    json={
                        "filename": f"s93-{request_id}.md",
                        "content_type": "text/markdown",
                        "content_text": private_source,
                        "tenant_id": TENANT_ID,
                        "owner_user_id": OWNER_ID,
                    },
                )
                upload.raise_for_status()
                uploaded = upload.json()
                document_id = str(uploaded["document_id"])
                job_id = str(uploaded["ingestion_job"]["job_id"])
                content_refs = store.get_content_ref(document_id) or {}
                source_file_id = content_refs.get("source_file_id")
                admitted_run = run_repository.find_by_job_id(job_id)
                if admitted_run is None:
                    raise RuntimeError("durable ingestion run was not admitted")
                run_id = str(admitted_run["run_id"])

                observed = datetime.now(UTC) - timedelta(minutes=5)
                expired = observed + timedelta(seconds=1)
                observed_at = observed.isoformat().replace("+00:00", "Z")
                expired_at = expired.isoformat().replace("+00:00", "Z")
                runtime.job_queue.start_job(job_id, updated_at=observed_at)
                claimed_run = claim_ingestion_run(
                    admitted_run,
                    worker_id="s93-expired-worker",
                    lease_expires_at=expired_at,
                    observed_at=observed_at,
                )
                run_repository.save(
                    claimed_run,
                    expected_checkpoint_version=0,
                )

                detail = client.get(
                    f"/api/v1/ingestion-runs/{run_id}",
                    headers=owner_headers,
                )
                history = client.get(
                    f"/api/v1/documents/{document_id}/ingestion-runs",
                    headers=owner_headers,
                )
                denied = client.get(
                    f"/api/v1/ingestion-runs/{run_id}",
                    headers={
                        **service_headers,
                        "X-NEX-Tenant-ID": TENANT_ID,
                        "X-NEX-Subject-ID": OTHER_OWNER_ID,
                    },
                )
                restart = client.get(
                    "/internal/v1/ingestion/restart-plan?limit=500",
                    headers=service_headers,
                )
                restart.raise_for_status()
                restart_item = next(
                    (
                        item
                        for item in restart.json()["items"]
                        if item["job_id"] == job_id
                    ),
                    None,
                )
                recovery = client.post(
                    f"/internal/v1/ingestion/jobs/{job_id}/recover-expired-lease",
                    headers=service_headers,
                )
                recovery.raise_for_status()
                recovery_payload = recovery.json()
                event_id = recovery_payload["observability"].get("event_id")

            persisted = _read_persisted_evidence(
                runtime.api_engine,
                job_id=job_id,
                run_id=run_id,
                event_id=event_id,
                private_source=private_source,
            )
            serialized = json.dumps(
                {
                    "detail": detail.json(),
                    "history": history.json(),
                    "restart_item": restart_item,
                    "recovery": recovery_payload,
                    "persisted": persisted,
                },
                default=str,
                sort_keys=True,
            )
            checks.update(
                {
                    "actual_test_database": persisted["database"]
                    == EXPECTED_DATABASE,
                    "actual_test_role": persisted["role"] == EXPECTED_ROLE,
                    "migration_recorded": persisted["migration_count"] == 1,
                    "upload_admitted": upload.status_code == 202,
                    "owner_detail_allowed": detail.status_code == 200
                    and detail.json()["run_id"] == run_id,
                    "owner_history_allowed": history.status_code == 200
                    and history.json()["run_count"] == 1,
                    "cross_owner_hidden": denied.status_code == 404,
                    "expired_lease_planned": restart_item is not None
                    and restart_item["action"] == "RECOVER_EXPIRED_LEASE",
                    "restart_plan_read_only": restart.json()["mutation_performed"]
                    is False,
                    "recovery_succeeded": recovery_payload["result"]["recovered"]
                    is True
                    and recovery_payload["result"]["status"]
                    == "RETRY_SCHEDULED",
                    "job_requeued": persisted["job_status"] == "QUEUED",
                    "run_waiting_retry": persisted["run_status"]
                    == "WAITING_RETRY",
                    "checkpoint_advanced": persisted["checkpoint_version"] == 2,
                    "owner_lineage_persisted": persisted["tenant_ref_id"]
                    == TENANT_ID
                    and persisted["owner_subject_ref_id"] == OWNER_ID,
                    "event_persisted": persisted["event_type"]
                    == CX_INGESTION_LEASE_RECOVERED_EVENT,
                    "private_payload_absent": private_source not in serialized
                    and persisted["private_match_count"] == 0,
                }
            )
        finally:
            _cleanup_probe_rows(
                runtime.api_engine,
                trace_id=trace_id,
                request_id=request_id,
                event_id=event_id,
                run_id=run_id,
                job_id=job_id,
                document_id=document_id,
                source_file_id=source_file_id,
            )

        residue = _probe_residue(
            runtime.api_engine,
            trace_id=trace_id,
            request_id=request_id,
            event_id=event_id,
            run_id=run_id,
            job_id=job_id,
            document_id=document_id,
            source_file_id=source_file_id,
        )
        checks["cleanup_verified"] = residue == 0
        if runtime.api_engine is not None:
            runtime.api_engine.dispose()
        if runtime.worker_engine is not None:
            runtime.worker_engine.dispose()

    return {
        "database": EXPECTED_DATABASE,
        "role": EXPECTED_ROLE,
        "document_id": document_id,
        "job_id": job_id,
        "run_id": run_id,
        "event_id": event_id,
        "checkpoint_version": 2,
        "probe_residue": residue,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _read_persisted_evidence(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    *,
    job_id: str,
    run_id: str,
    event_id: str | None,
    private_source: str,
) -> dict[str, Any]:
    with engine.begin() as connection:
        database, role = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
        migration_count = connection.execute(
            text("SELECT count(*) FROM schema_migrations WHERE version = :version"),
            {"version": MIGRATION_VERSION},
        ).scalar_one()
        job = connection.execute(
            text(
                """
                SELECT status
                FROM service_jobs
                WHERE job_id = :job_id
                """
            ),
            {"job_id": job_id},
        ).mappings().one()
        run = connection.execute(
            text(
                """
                SELECT status, checkpoint_version, tenant_ref_id,
                       owner_subject_ref_id
                FROM cx_ingest_runs
                WHERE run_id = :run_id
                """
            ),
            {"run_id": run_id},
        ).mappings().one()
        event = connection.execute(
            text(
                """
                SELECT event_type
                FROM service_operational_events
                WHERE event_id = :event_id
                """
            ),
            {"event_id": event_id or ""},
        ).mappings().one()
        needle = f"%{private_source}%"
        private_match_count = connection.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM service_jobs
                     WHERE job_id = :job_id
                       AND (payload::text LIKE :needle OR links::text LIKE :needle))
                  + (SELECT count(*) FROM cx_ingest_runs
                     WHERE run_id = :run_id
                       AND (step_states::text LIKE :needle
                            OR coalesce(last_error::text, '') LIKE :needle))
                  + (SELECT count(*) FROM service_operational_events
                     WHERE event_id = :event_id
                       AND details::text LIKE :needle)
                """
            ),
            {
                "job_id": job_id,
                "run_id": run_id,
                "event_id": event_id or "",
                "needle": needle,
            },
        ).scalar_one()
    return {
        "database": database,
        "role": role,
        "migration_count": int(migration_count),
        "job_status": job["status"],
        "run_status": run["status"],
        "checkpoint_version": int(run["checkpoint_version"]),
        "tenant_ref_id": run["tenant_ref_id"],
        "owner_subject_ref_id": run["owner_subject_ref_id"],
        "event_type": event["event_type"],
        "private_match_count": int(private_match_count),
    }


def _cleanup_probe_rows(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    *,
    trace_id: str,
    request_id: str,
    event_id: str | None,
    run_id: str | None,
    job_id: str | None,
    document_id: str | None,
    source_file_id: str | None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_operational_events
                WHERE event_id = :event_id
                   OR trace_id = :trace_id
                   OR request_id = :request_id
                """
            ),
            {
                "event_id": event_id or "",
                "trace_id": trace_id,
                "request_id": request_id,
            },
        )
        connection.execute(
            text(
                """
                DELETE FROM cx_ingest_runs
                WHERE run_id = :run_id
                   OR trace_id = :trace_id
                   OR request_id = :request_id
                """
            ),
            {
                "run_id": run_id or str(uuid4()),
                "trace_id": trace_id,
                "request_id": request_id,
            },
        )
        connection.execute(
            text(
                """
                DELETE FROM service_jobs
                WHERE job_id = :job_id
                   OR trace_id = :trace_id
                   OR request_id = :request_id
                """
            ),
            {
                "job_id": job_id or "",
                "trace_id": trace_id,
                "request_id": request_id,
            },
        )
        connection.execute(
            text(
                """
                DELETE FROM cx_content_acl_entries
                WHERE content_object_id = :document_id
                   OR content_object_id IN (
                       SELECT content_object_id
                       FROM cx_content_objects
                       WHERE created_trace_id = :trace_id
                   )
                """
            ),
            {
                "document_id": document_id or str(uuid4()),
                "trace_id": trace_id,
            },
        )
        connection.execute(
            text(
                """
                DELETE FROM cx_content_objects
                WHERE content_object_id = :document_id
                   OR created_trace_id = :trace_id
                """
            ),
            {
                "document_id": document_id or str(uuid4()),
                "trace_id": trace_id,
            },
        )
        connection.execute(
            text(
                """
                DELETE FROM cx_source_files AS source
                WHERE (
                       source.source_file_id = :source_file_id
                    OR source.first_seen_trace_id = :trace_id
                )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM cx_content_objects AS content
                      WHERE content.source_file_id = source.source_file_id
                  )
                """
            ),
            {
                "source_file_id": source_file_id or str(uuid4()),
                "trace_id": trace_id,
            },
        )


def _probe_residue(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    *,
    trace_id: str,
    request_id: str,
    event_id: str | None,
    run_id: str | None,
    job_id: str | None,
    document_id: str | None,
    source_file_id: str | None,
) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM service_operational_events
                         WHERE event_id = :event_id OR trace_id = :trace_id
                            OR request_id = :request_id)
                      + (SELECT count(*) FROM cx_ingest_runs
                         WHERE run_id = :run_id OR trace_id = :trace_id
                            OR request_id = :request_id)
                      + (SELECT count(*) FROM service_jobs
                         WHERE job_id = :job_id OR trace_id = :trace_id
                            OR request_id = :request_id)
                      + (SELECT count(*) FROM cx_content_objects
                         WHERE content_object_id = :document_id
                            OR created_trace_id = :trace_id)
                      + (SELECT count(*) FROM cx_source_files
                         WHERE source_file_id = :source_file_id
                            OR first_seen_trace_id = :trace_id)
                    """
                ),
                {
                    "event_id": event_id or "",
                    "run_id": run_id or str(uuid4()),
                    "job_id": job_id or "",
                    "document_id": document_id or str(uuid4()),
                    "source_file_id": source_file_id or str(uuid4()),
                    "trace_id": trace_id,
                    "request_id": request_id,
                },
            ).scalar_one()
        )


def _service_headers(*, trace_id: str, request_id: str) -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-ag", audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _storage_config(root: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=root,
        source_root=root / "cx" / "source-files",
        extracted_markdown_root=root / "cx" / "extracted-markdown",
        extraction_temp_root=root / "cx" / "extraction-temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def _target_url_allowed(database_url: str) -> bool:
    try:
        parsed = urlsplit(database_url)
        return (
            unquote(parsed.username or "") == EXPECTED_ROLE
            and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
        )
    except ValueError:
        return False


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


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return f"cx_ingestion_operations_postgres_smoke=skipped reason={SMOKE_ENV}"
    return (
        "cx_ingestion_operations_postgres_smoke="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"database={result.get('database', 'not-run')} "
        f"checkpoint={result.get('checkpoint_version', 'not-run')} "
        f"residue={result.get('probe_residue', 'not-run')} "
        f"failed_checks={len(result.get('failed_checks') or [])} "
        f"dgx_required={result.get('dgx_live_provider_required', False)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run protected CX durable ingestion operations PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    result = run_cx_ingestion_operations_postgres_smoke()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] != "FAIL" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
