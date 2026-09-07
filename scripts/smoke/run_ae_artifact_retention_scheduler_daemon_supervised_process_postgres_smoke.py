#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AE_PATH = ROOT / "services" / "nex-ae-api"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(SMOKE_PATH))

import run_ae_artifact_postgres_smoke as artifact_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifact_retention_scheduler_daemon import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_COLLECTION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DETAIL_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DISPATCH_SCHEMA_VERSION,
    SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore,
)
from nex_ae_api.artifacts import register_artifact_handoff_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_POSTGRES_SMOKE"
)
SMOKE_PROFILE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
MIGRATION_VERSION = (
    "0575_ae_artifact_retention_scheduler_daemon_supervised_process_persistence"
)
CHECKED_AT = "2026-09-08T06:15:00Z"
OBSERVED_AT = "2026-09-08T06:15:04Z"
STARTED_AT = "2026-09-08T06:15:01Z"
EXPECTED_TABLES = {
    "ae_artifact_retention_scheduler_daemon_process_snapshots",
    "ae_artifact_retention_scheduler_daemon_process_events",
}
EXPECTED_INDEXES = {
    "idx_ae_daemon_process_snapshots_observed",
    "idx_ae_daemon_process_snapshots_action_status",
    "idx_ae_daemon_process_snapshots_pid",
    "idx_ae_daemon_process_events_record",
    "idx_ae_daemon_process_events_scheduler",
}
EXPECTED_JSONB_TYPES = {
    "summary": "jsonb",
    "metadata": "jsonb",
    "supervised_process_snapshot": "jsonb",
}


def run_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
            env=env,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        base_auth._require_test_database_url(database_url, env_name=database_env)
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_ae_artifact_retention_scheduler_daemon_supervised_process_smoke(
            database_url=database_url,
            database_env=database_env,
        )
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile, env=env)
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        return _failure("execution_failed", detail, profile=profile, env=env)

    evidence = {
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
        **execution,
    }
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _execute_ae_artifact_retention_scheduler_daemon_supervised_process_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    record_ids: list[str] = []
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        _ensure_sqlite_migration_marker(engine)
        supervised_process_store = (
            SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore(
                session_factory
            )
        )
        supervised_process_store.ensure_schema()
        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        app.state.nex_persistence = SimpleNamespace(
            api_session_factory=session_factory
        )
        register_artifact_handoff_routes(app)
        client = TestClient(app)
        headers = artifact_pg._auth_headers(request_id=request_id, trace_id=trace_id)

        missing_response = client.post(
            "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
            json=_process_payload(
                action="status_probe",
                suffix=suffix,
                reason="slice_0575_postgresql_status_probe",
                process_status="MISSING",
                host_id=f"ae-smoke-{suffix}",
            ),
            headers=headers,
        )
        missing_payload = _json_payload(missing_response)
        missing_record_id = _record_id(missing_payload)
        if missing_record_id:
            record_ids.append(missing_record_id)

        running_response = client.post(
            "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
            json=_process_payload(
                action="start_daemon",
                suffix=suffix,
                reason="slice_0575_postgresql_running_snapshot",
                enabled=True,
                explicit_opt_in=True,
                max_cycles=2,
                run_worker=True,
                process_status="RUNNING",
                process_id=57575,
                host_id=f"ae-smoke-{suffix}",
                started_at=STARTED_AT,
                message="observed guarded test-profile process snapshot",
            ),
            headers=headers,
        )
        running_payload = _json_payload(running_response)
        running_record_id = _record_id(running_payload)
        if running_record_id:
            record_ids.append(running_record_id)

        scheduler_id = (
            _mapping_value(running_payload.get("supervised_process_record")).get(
                "scheduler_id"
            )
            or _mapping_value(missing_payload.get("supervised_process_record")).get(
                "scheduler_id"
            )
            or "ae-artifact-retention-scheduler-local-v1"
        )
        list_response = client.get(
            "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
            params={
                "scheduler_id": scheduler_id,
                "action": "start_daemon",
                "process_status": "RUNNING",
                "limit": "5",
            },
            headers=headers,
        )
        list_payload = _json_payload(list_response)
        detail_response = client.get(
            (
                "/api/v1/artifact-retention/scheduler-daemon-process-snapshots/"
                f"{running_record_id or 'missing'}"
            ),
            headers=headers,
        )
        detail_payload = _json_payload(detail_response)

        db_observations = _db_observations(
            engine,
            record_ids=record_ids,
            scheduler_id=scheduler_id,
            host_id=f"ae-smoke-{suffix}",
            process_id=57575,
        )
        checks = _supervised_process_smoke_checks(
            database_url=database_url,
            database_env=database_env,
            missing_response=missing_response.status_code,
            running_response=running_response.status_code,
            list_response=list_response.status_code,
            detail_response=detail_response.status_code,
            missing_payload=missing_payload,
            running_payload=running_payload,
            list_payload=list_payload,
            detail_payload=detail_payload,
            db_observations=db_observations,
            record_ids=record_ids,
        )
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "AE artifact retention scheduler daemon supervised process "
                f"PostgreSQL smoke checks failed: {', '.join(failed_checks)}"
            )

        cleanup = _cleanup_supervised_process_records(
            supervised_process_store,
            record_ids,
        )
        post_cleanup = _db_observations(
            engine,
            record_ids=record_ids,
            scheduler_id=scheduler_id,
            host_id=f"ae-smoke-{suffix}",
            process_id=57575,
        )
        if post_cleanup["row_counts"] != {
            "process_records": 0,
            "process_events": 0,
        }:
            raise RuntimeError(
                "AE artifact retention scheduler daemon supervised process "
                "PostgreSQL smoke cleanup verification failed."
            )
        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "routes": {
                "missing_dispatch_status": missing_response.status_code,
                "running_dispatch_status": running_response.status_code,
                "collection_status": list_response.status_code,
                "detail_status": detail_response.status_code,
            },
            "dispatches": {
                "status_probe_missing": _dispatch_evidence(missing_payload),
                "start_daemon_running": _dispatch_evidence(running_payload),
            },
            "collection": _collection_evidence(list_payload),
            "detail": _detail_evidence(detail_payload),
            "db_observations": db_observations,
            "checks": checks,
            "cleanup": cleanup,
            "post_cleanup": post_cleanup,
            "live_db": True,
        }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        if record_ids:
            try:
                session_factory = build_session_factory(engine)
                supervised_process_store = (
                    SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore(
                        session_factory
                    )
                )
                _cleanup_supervised_process_records(
                    supervised_process_store,
                    record_ids,
                )
            except (SQLAlchemyError, RuntimeError, ValueError):
                pass
        engine.dispose()


def _process_payload(
    *,
    action: str,
    suffix: str,
    reason: str,
    process_status: str,
    host_id: str,
    enabled: bool = False,
    explicit_opt_in: bool = False,
    max_cycles: int = 1,
    run_worker: bool = False,
    process_id: int | None = None,
    started_at: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    payload = {
        "action": action,
        "profile": DEFAULT_PROFILE,
        "enabled": enabled,
        "explicit_opt_in": explicit_opt_in,
        "checked_at": CHECKED_AT,
        "observed_at": OBSERVED_AT,
        "process_status": process_status,
        "host_id": host_id,
        "requested_by": {
            "actor_type": "operator",
            "actor_id": f"ae-supervised-process-postgres-smoke-{suffix}",
        },
        "reason": reason,
        "max_cycles": str(max_cycles),
        "run_worker": run_worker,
        "supervisor_mode": "fake_dry_run",
        "output_format": "json",
    }
    if process_id is not None:
        payload["process_id"] = process_id
    if started_at is not None:
        payload["started_at"] = started_at
    if message is not None:
        payload["message"] = message
    return payload


def _json_payload(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _mapping_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _record_id(payload: Mapping[str, Any]) -> str | None:
    record_id = _mapping_value(payload.get("supervised_process_record")).get(
        "daemon_supervised_process_record_id"
    )
    return record_id if isinstance(record_id, str) and record_id else None


def _dispatch_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    record = _mapping_value(payload.get("supervised_process_record"))
    event = _mapping_value(payload.get("supervised_process_event"))
    metadata = _mapping_value(record.get("metadata"))
    guardrails = _mapping_value(payload.get("guardrails"))
    return {
        "schema_version": payload.get(
            "daemon_supervised_process_dispatch_schema_version"
        ),
        "action": payload.get("action"),
        "process_status": payload.get("process_status"),
        "record_id": record.get("daemon_supervised_process_record_id"),
        "event_id": event.get("daemon_supervised_process_event_id"),
        "event_type": event.get("event_type"),
        "process_id": record.get("process_id"),
        "process_running": record.get("process_running"),
        "process_started_observed": record.get("process_started_observed"),
        "subprocess_adapter_required": record.get("subprocess_adapter_required"),
        "process_control_allowed": guardrails.get("process_control_allowed"),
        "safe_for_ag_projection": metadata.get("safe_for_ag_projection"),
    }


def _collection_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    return {
        "schema_version": payload.get(
            "daemon_supervised_process_collection_schema_version"
        ),
        "count": payload.get("count"),
        "item_ids": [
            item.get("daemon_supervised_process_record_id")
            for item in items
            if isinstance(item, Mapping)
        ],
        "actions": [
            item.get("action") for item in items if isinstance(item, Mapping)
        ],
        "process_statuses": [
            item.get("process_status")
            for item in items
            if isinstance(item, Mapping)
        ],
    }


def _detail_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    events = (
        payload.get("supervised_process_events")
        if isinstance(payload.get("supervised_process_events"), list)
        else []
    )
    return {
        "schema_version": payload.get(
            "daemon_supervised_process_detail_schema_version"
        ),
        "record_id": payload.get("daemon_supervised_process_record_id"),
        "supervised_process_event_count": payload.get(
            "supervised_process_event_count"
        ),
        "event_types": [
            item.get("event_type") for item in events if isinstance(item, Mapping)
        ],
    }


def _db_observations(
    engine: Any,
    *,
    record_ids: list[str],
    scheduler_id: str,
    host_id: str,
    process_id: int,
) -> dict[str, Any]:
    with engine.connect() as connection:
        dialect_name = connection.dialect.name
        tables_present = sorted(
            table_name
            for table_name in EXPECTED_TABLES
            if _table_exists(connection, table_name)
        )
        migration_recorded = _schema_migration_recorded(connection)
        row_counts = {
            "process_records": sum(
                _scalar_count(
                    connection,
                    """
                    SELECT count(*)
                    FROM ae_artifact_retention_scheduler_daemon_process_snapshots
                    WHERE daemon_supervised_process_record_id = :record_id
                    """,
                    {"record_id": record_id},
                )
                for record_id in record_ids
            ),
            "process_events": sum(
                _scalar_count(
                    connection,
                    """
                    SELECT count(*)
                    FROM ae_artifact_retention_scheduler_daemon_process_events
                    WHERE daemon_supervised_process_record_id = :record_id
                    """,
                    {"record_id": record_id},
                )
                for record_id in record_ids
            ),
        }
        record_counts = {
            "status_probe_missing": _record_status_count(
                connection,
                record_ids=record_ids,
                action="status_probe",
                process_status="MISSING",
            ),
            "start_daemon_running": _record_status_count(
                connection,
                record_ids=record_ids,
                action="start_daemon",
                process_status="RUNNING",
            ),
            "running_pid": _scalar_count(
                connection,
                """
                SELECT count(*)
                FROM ae_artifact_retention_scheduler_daemon_process_snapshots
                WHERE scheduler_id = :scheduler_id
                  AND host_id = :host_id
                  AND process_id = :process_id
                  AND process_status = 'RUNNING'
                """,
                {
                    "scheduler_id": scheduler_id,
                    "host_id": host_id,
                    "process_id": process_id,
                },
            ),
        }
        indexes_present = _indexes_present(connection, dialect_name)
        jsonb_columns = _jsonb_column_types(connection, dialect_name, record_ids)
    return {
        "dialect": dialect_name,
        "tables_present": tables_present,
        "indexes_present": indexes_present,
        "migration_recorded": migration_recorded,
        "row_counts": row_counts,
        "record_counts": record_counts,
        "jsonb_columns": jsonb_columns,
    }


def _record_status_count(
    connection: Any,
    *,
    record_ids: list[str],
    action: str,
    process_status: str,
) -> int:
    return sum(
        _scalar_count(
            connection,
            """
            SELECT count(*)
            FROM ae_artifact_retention_scheduler_daemon_process_snapshots
            WHERE daemon_supervised_process_record_id = :record_id
              AND action = :action
              AND process_status = :process_status
            """,
            {
                "record_id": record_id,
                "action": action,
                "process_status": process_status,
            },
        )
        for record_id in record_ids
    )


def _ensure_sqlite_migration_marker(engine: Any) -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO schema_migrations (version, description)
                VALUES (:version, :description)
                ON CONFLICT(version) DO NOTHING
                """
            ),
            {
                "version": MIGRATION_VERSION,
                "description": (
                    "SQLite regression marker for AE supervised process smoke"
                ),
            },
        )


def _table_exists(connection: Any, table_name: str) -> bool:
    if connection.dialect.name == "postgresql":
        return (
            connection.execute(
                text("SELECT to_regclass(:table_name)"),
                {"table_name": f"public.{table_name}"},
            ).scalar()
            == table_name
        )
    return bool(
        connection.execute(
            text(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = :table_name
                """
            ),
            {"table_name": table_name},
        ).scalar()
    )


def _schema_migration_recorded(connection: Any) -> bool:
    try:
        return bool(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM schema_migrations
                    WHERE version = :version
                    """
                ),
                {"version": MIGRATION_VERSION},
            ).scalar()
        )
    except SQLAlchemyError:
        return False


def _indexes_present(connection: Any, dialect_name: str) -> list[str]:
    if dialect_name == "postgresql":
        indexes = (
            connection.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename IN (
                        'ae_artifact_retention_scheduler_daemon_process_snapshots',
                        'ae_artifact_retention_scheduler_daemon_process_events'
                      )
                    ORDER BY indexname
                    """
                )
            )
            .scalars()
            .all()
        )
    else:
        indexes = (
            connection.execute(
                text(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'index'
                      AND tbl_name IN (
                        'ae_artifact_retention_scheduler_daemon_process_snapshots',
                        'ae_artifact_retention_scheduler_daemon_process_events'
                      )
                    ORDER BY name
                    """
                )
            )
            .scalars()
            .all()
        )
    return sorted(set(indexes).intersection(EXPECTED_INDEXES))


def _jsonb_column_types(
    connection: Any,
    dialect_name: str,
    record_ids: list[str],
) -> dict[str, str]:
    if dialect_name != "postgresql" or not record_ids:
        return {}
    row = (
        connection.execute(
            text(
                """
                SELECT
                    pg_typeof(summary)::text AS summary,
                    pg_typeof(metadata)::text AS metadata,
                    pg_typeof(supervised_process_snapshot)::text
                        AS supervised_process_snapshot
                FROM ae_artifact_retention_scheduler_daemon_process_snapshots
                WHERE daemon_supervised_process_record_id = :record_id
                LIMIT 1
                """
            ),
            {"record_id": record_ids[0]},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else {}


def _scalar_count(connection: Any, sql: str, params: dict[str, Any]) -> int:
    return int(connection.execute(text(sql), params).scalar() or 0)


def _cleanup_supervised_process_records(
    supervised_process_store: (
        SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore
    ),
    record_ids: list[str],
) -> dict[str, int]:
    cleanup = {
        "daemon_supervised_process_events": 0,
        "daemon_supervised_process_records": 0,
    }
    for record_id in dict.fromkeys(record_ids):
        deleted = supervised_process_store.delete_supervised_process_record(record_id)
        cleanup["daemon_supervised_process_events"] += deleted[
            "daemon_supervised_process_events"
        ]
        cleanup["daemon_supervised_process_records"] += deleted[
            "daemon_supervised_process_records"
        ]
    return cleanup


def _supervised_process_smoke_checks(
    *,
    database_url: str,
    database_env: str,
    missing_response: int,
    running_response: int,
    list_response: int,
    detail_response: int,
    missing_payload: Mapping[str, Any],
    running_payload: Mapping[str, Any],
    list_payload: Mapping[str, Any],
    detail_payload: Mapping[str, Any],
    db_observations: Mapping[str, Any],
    record_ids: list[str],
) -> dict[str, bool]:
    list_items = (
        list_payload.get("items") if isinstance(list_payload.get("items"), list) else []
    )
    missing_record = _mapping_value(missing_payload.get("supervised_process_record"))
    running_record = _mapping_value(running_payload.get("supervised_process_record"))
    detail_events = (
        detail_payload.get("supervised_process_events")
        if isinstance(detail_payload.get("supervised_process_events"), list)
        else []
    )
    jsonb_columns = _mapping_value(db_observations.get("jsonb_columns"))
    return {
        "test_database_url": database_env == "NEX_AE_TEST_DATABASE_URL"
        and _database_name(database_url).endswith("_test"),
        "migration_recorded": db_observations.get("migration_recorded") is True,
        "tables_present": set(db_observations.get("tables_present", []))
        == EXPECTED_TABLES,
        "indexes_present": set(db_observations.get("indexes_present", []))
        == EXPECTED_INDEXES,
        "missing_route_passed": missing_response == 200
        and missing_payload.get("daemon_supervised_process_dispatch_schema_version")
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DISPATCH_SCHEMA_VERSION
        and missing_payload.get("action") == "status_probe"
        and missing_payload.get("process_status") == "MISSING"
        and missing_record.get("process_running") is False,
        "running_route_passed": running_response == 200
        and running_payload.get("daemon_supervised_process_dispatch_schema_version")
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DISPATCH_SCHEMA_VERSION
        and running_payload.get("action") == "start_daemon"
        and running_payload.get("process_status") == "RUNNING"
        and running_record.get("process_id") == 57575
        and running_record.get("process_running") is True
        and running_record.get("process_started_observed") is True,
        "guardrails_block_process_control": _mapping_value(
            running_payload.get("guardrails")
        ).get("process_control_allowed")
        is False
        and running_record.get("subprocess_adapter_required") is True,
        "collection_reads_running_start": list_response == 200
        and list_payload.get("daemon_supervised_process_collection_schema_version")
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_COLLECTION_SCHEMA_VERSION
        and list_payload.get("count") == 1
        and len(list_items) == 1
        and _mapping_value(list_items[0]).get(
            "daemon_supervised_process_record_id"
        )
        == running_record.get("daemon_supervised_process_record_id"),
        "detail_reads_event": detail_response == 200
        and detail_payload.get("daemon_supervised_process_detail_schema_version")
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DETAIL_SCHEMA_VERSION
        and detail_payload.get("daemon_supervised_process_record_id")
        == running_record.get("daemon_supervised_process_record_id")
        and detail_payload.get("supervised_process_event_count") == 1
        and [
            _mapping_value(item).get("event_type")
            for item in detail_events
            if isinstance(item, Mapping)
        ]
        == ["SUPERVISED_PROCESS_SNAPSHOT_RECORDED"],
        "process_rows_persisted": db_observations.get("row_counts")
        == {"process_records": 2, "process_events": 2},
        "record_status_counts_persisted": db_observations.get("record_counts")
        == {
            "status_probe_missing": 1,
            "start_daemon_running": 1,
            "running_pid": 1,
        },
        "record_ids_collected": len(set(record_ids)) == 2,
        "postgres_jsonb_columns_verified": db_observations.get("dialect")
        != "postgresql"
        or jsonb_columns == EXPECTED_JSONB_TYPES,
    }


def _database_name(database_url: str) -> str:
    try:
        database = make_url(database_url).database
    except SQLAlchemyError:
        return ""
    return database or ""


def _database_url_password(database_url: str | None) -> str | None:
    if not database_url:
        return None
    try:
        return make_url(database_url).password
    except SQLAlchemyError:
        return None


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    env: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": _safe_detail(detail, env),
    }


def _safe_detail(detail: str, env: Mapping[str, str]) -> str:
    safe = artifact_pg._safe_detail(detail, env)
    for key in (SMOKE_PROFILE_ENV,):
        value = env.get(key)
        if value:
            safe = safe.replace(value, f"<redacted:{key}>")
    password = _database_url_password(
        env.get(service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE))
    )
    if password:
        safe = safe.replace(password, "***")
    return safe


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    artifact_pg.assert_smoke_evidence_redacted(serialized_evidence, environ)
    database_url = environ.get(service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE))
    password = _database_url_password(database_url)
    if password and password in serialized_evidence:
        raise ValueError(
            "AE daemon supervised process smoke contains a database password."
        )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        rows = evidence["db_observations"]["row_counts"]
        return (
            "ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke="
            f"pass service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            "dispatches=2 "
            f"records={rows['process_records']} "
            f"events={rows['process_events']} "
            f"running={evidence['dispatches']['start_daemon_running']['process_status']} "
            f"cleanup_records={evidence['cleanup']['daemon_supervised_process_records']} "
            f"live_db={str(evidence['live_db']).lower()}"
        )
    return (
        "ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke="
        f"fail service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE scheduler daemon supervised process PostgreSQL "
            "smoke."
        )
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = (
        run_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke()
    )
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
