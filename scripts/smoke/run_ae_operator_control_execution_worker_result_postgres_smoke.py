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

import run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke as worker_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifact_retention_scheduler_daemon import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_RECORD_SCHEMA_VERSION,
    AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE,
    SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore,
    SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore,
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


SCHEMA_VERSION = "ae_operator_control_execution_worker_result_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = (
    "NEX_AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = worker_pg.SERVICE_ID
DEFAULT_PROFILE = worker_pg.DEFAULT_PROFILE
MIGRATION_VERSION = "0612_ae_worker_result_persistence"
CHECKED_AT = "2026-09-08T09:14:00Z"
REQUESTED_AT = "2026-09-08T09:13:55Z"
WORKER_OBSERVED_AT = "2026-09-08T09:14:20Z"
EXECUTION_ROUTE = worker_pg.EXECUTION_ROUTE
WORKER_ROUTE = worker_pg.WORKER_ROUTE
EXPECTED_RESULT_INDEXES = {
    "idx_ae_op_worker_results_observed",
    "idx_ae_op_worker_results_state",
    "idx_ae_op_worker_results_status",
    "idx_ae_op_worker_results_request",
}
EXPECTED_TABLES = {
    "ae_daemon_operator_control_execution_states",
    "ae_daemon_operator_control_execution_transitions",
    AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE,
}
EXPECTED_INDEXES = worker_pg.EXPECTED_EXECUTION_INDEXES | EXPECTED_RESULT_INDEXES
EXPECTED_JSONB_TYPES = {
    "result.status_path": "jsonb",
    "result.supervisor_result_statuses": "jsonb",
    "result.supervisor_actions": "jsonb",
    "result.supervisor_result_ids": "jsonb",
    "result.guardrails": "jsonb",
    "result.metadata": "jsonb",
}


def run_ae_operator_control_execution_worker_result_postgres_smoke(
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
            f"{SMOKE_PROFILE_ENV} must be test for worker-result PostgreSQL smoke.",
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
        execution = _execute_worker_result_route_smoke(
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


def _execute_worker_result_route_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    idempotency_key = f"slice-0614-worker-result-{suffix}"
    state_ids: list[str] = []
    result_ids: list[str] = []
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        worker_pg.ae_execution_pg.process_pg._ensure_sqlite_migration_marker(engine)
        worker_pg.ae_execution_pg.supervisor_pg._ensure_sqlite_migration_marker(engine)
        worker_pg._ensure_sqlite_migration_marker(engine)
        _ensure_sqlite_migration_marker(engine)
        execution_store = (
            SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
                session_factory
            )
        )
        result_store = (
            SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore(
                session_factory
            )
        )
        execution_store.ensure_schema()
        result_store.ensure_schema()
        before = _db_observations(engine, idempotency_key=idempotency_key)

        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        app.state.nex_persistence = SimpleNamespace(
            api_session_factory=session_factory
        )
        register_artifact_handoff_routes(
            app,
            retention_scheduler_daemon_operator_control_execution_store=(
                execution_store
            ),
            retention_scheduler_daemon_operator_control_execution_worker_result_store=(
                result_store
            ),
        )
        client = TestClient(app)
        headers = worker_pg.ae_execution_pg.artifact_pg._auth_headers(
            request_id=request_id,
            trace_id=trace_id,
        )

        admitted_response = client.post(
            EXECUTION_ROUTE,
            json={
                **_execution_payload(suffix=suffix),
                "persist_execution_state": True,
            },
            headers={**headers, "Idempotency-Key": idempotency_key},
        )
        admitted_payload = worker_pg.ae_execution_pg._json_payload(
            admitted_response
        )
        state_id = _append_optional_text(
            state_ids,
            admitted_payload.get("operator_control_execution_state_id")
        )

        worker_response = client.post(
            WORKER_ROUTE,
            json={
                "operator_control_execution_state_id": state_id,
                "checked_at": CHECKED_AT,
                "worker_observed_at": WORKER_OBSERVED_AT,
                "persist_worker_result": True,
            },
            headers=headers,
        )
        worker_payload = worker_pg.ae_execution_pg._json_payload(worker_response)
        result_id = _append_optional_text(
            result_ids,
            worker_payload.get("operator_control_execution_worker_result_id")
        )
        result_record = (
            result_store.get_worker_result(result_id) if result_id is not None else None
        )
        result_collection = (
            result_store.list_worker_results(
                operator_control_execution_state_id=state_id,
                worker_status="SUCCEEDED",
                limit=3,
            )
            if state_id is not None
            else []
        )
        after = _db_observations(
            engine,
            state_ids=state_ids,
            result_ids=result_ids,
            idempotency_key=idempotency_key,
        )

        checks = _smoke_checks(
            database_url=database_url,
            database_env=database_env,
            admitted_response=admitted_response.status_code,
            worker_response=worker_response.status_code,
            admitted_payload=admitted_payload,
            worker_payload=worker_payload,
            result_record=result_record,
            result_collection=result_collection,
            before=before,
            after=after,
        )
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "AE operator-control execution worker result PostgreSQL "
                f"smoke checks failed: {', '.join(failed_checks)}"
            )

        cleanup = _cleanup_worker_result_rows(
            result_store=result_store,
            execution_store=execution_store,
            result_ids=result_ids,
            state_ids=state_ids,
        )
        post_cleanup = _db_observations(
            engine,
            state_ids=state_ids,
            result_ids=result_ids,
            idempotency_key=idempotency_key,
        )
        if post_cleanup["scoped_row_counts"] != {
            "execution_states": 0,
            "execution_transitions": 0,
            "worker_results": 0,
        }:
            raise RuntimeError(
                "AE operator-control execution worker result PostgreSQL "
                "smoke cleanup verification failed."
            )

        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "persisted": {
                "execution_state_id": state_id,
                "worker_result_id": result_id,
            },
            "routes": {
                "ae_persisted_execution_status": admitted_response.status_code,
                "ae_persisted_worker_result_status": worker_response.status_code,
            },
            "execution": worker_pg.ae_execution_pg._execution_evidence(
                admitted_payload
            ),
            "worker": worker_pg._worker_evidence(worker_payload),
            "worker_result_record": _worker_result_record_evidence(
                result_record or {}
            ),
            "db_observations": {
                "before": before,
                "after": after,
            },
            "checks": checks,
            "cleanup": cleanup,
            "post_cleanup": post_cleanup,
            "live_db": True,
        }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        if state_ids or result_ids:
            try:
                session_factory = build_session_factory(engine)
                _cleanup_worker_result_rows(
                    result_store=(
                        SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore(
                            session_factory
                        )
                    ),
                    execution_store=(
                        SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
                            session_factory
                        )
                    ),
                    result_ids=result_ids,
                    state_ids=state_ids,
                )
            except (SQLAlchemyError, RuntimeError, ValueError):
                pass
        engine.dispose()


def _execution_payload(*, suffix: str) -> dict[str, Any]:
    reason = "slice_0614_worker_result_postgresql_persistence"
    payload = worker_pg.ae_execution_pg._execution_payload(
        suffix=suffix,
        reason=reason,
        execution_mode="fake_dry_run_supervisor_persistent_dispatch",
    )
    payload.update(
        {
            "checked_at": CHECKED_AT,
            "requested_at": REQUESTED_AT,
            "observed_at": CHECKED_AT,
            "reason": reason,
            "max_cycles": "2",
            "run_worker": True,
            "approval": {
                "approved": True,
                "approved_by": payload["requested_by"],
                "approved_at": REQUESTED_AT,
                "reason": reason,
            },
        }
    )
    return payload


def _worker_result_record_evidence(record: Mapping[str, Any]) -> dict[str, Any]:
    guardrails = _mapping_value(record.get("guardrails"))
    metadata = _mapping_value(record.get("metadata"))
    hashes = {
        "worker_command": record.get(
            "operator_control_execution_worker_command_hash"
        ),
        "transition_plan": record.get(
            "operator_control_execution_worker_transition_plan_hash"
        ),
        "supervisor_results": record.get("supervisor_results_hash"),
        "worker_result": record.get("worker_result_hash"),
    }
    return {
        "schema_version": record.get(
            "operator_control_execution_worker_result_record_schema_version"
        ),
        "worker_result_id": record.get(
            "operator_control_execution_worker_result_id"
        ),
        "state_id": record.get("operator_control_execution_state_id"),
        "request_id": record.get("operator_control_execution_request_id"),
        "action": record.get("action"),
        "execution_mode": record.get("execution_mode"),
        "worker_mode": record.get("worker_mode"),
        "worker_status": record.get("worker_status"),
        "transition_terminal_status": record.get("transition_terminal_status"),
        "status_path": list(record.get("status_path", [])),
        "supervisor_result_count": record.get("supervisor_result_count"),
        "supervisor_result_statuses": list(
            record.get("supervisor_result_statuses", [])
        ),
        "supervisor_actions": list(record.get("supervisor_actions", [])),
        "database_write_performed": metadata.get("database_write_performed"),
        "worker_result_record_only": metadata.get("worker_result_record_only"),
        "stored_table": metadata.get("stored_table"),
        "safe_summary_only": guardrails.get("safe_summary_only"),
        "stores_full_worker_result_payload": guardrails.get(
            "stores_full_worker_result_payload"
        ),
        "stores_full_supervisor_result_payload": metadata.get(
            "stores_full_supervisor_result_payload"
        ),
        "hashes_present": all(
            isinstance(value, str) and len(value) == 64 for value in hashes.values()
        ),
    }


def _db_observations(
    engine: Any,
    *,
    state_ids: list[str] | None = None,
    result_ids: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    target_state_ids = state_ids or []
    target_result_ids = result_ids or []
    with engine.connect() as connection:
        dialect_name = connection.dialect.name
        health_probe = connection.execute(text("SELECT 1")).scalar() == 1
        tables_present = sorted(
            table_name
            for table_name in EXPECTED_TABLES
            if worker_pg.ae_execution_pg._table_exists(connection, table_name)
        )
        indexes_present = _indexes_present(connection, dialect_name)
        migration_recorded = _schema_migration_recorded(connection)
        jsonb_columns = _jsonb_column_types(
            connection,
            dialect_name,
            target_result_ids,
        )
        row_counts = {
            "execution_states": worker_pg.ae_execution_pg._table_count(
                connection,
                "ae_daemon_operator_control_execution_states",
            ),
            "execution_transitions": worker_pg.ae_execution_pg._table_count(
                connection,
                "ae_daemon_operator_control_execution_transitions",
            ),
            "worker_results": worker_pg.ae_execution_pg._table_count(
                connection,
                AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE,
            ),
        }
        scoped_row_counts = _scoped_row_counts(
            connection,
            state_ids=target_state_ids,
            result_ids=target_result_ids,
            idempotency_key=idempotency_key,
        )
    return {
        "dialect": dialect_name,
        "health_probe": health_probe,
        "tables_present": tables_present,
        "indexes_present": indexes_present,
        "migration_recorded": migration_recorded,
        "jsonb_columns": jsonb_columns,
        "row_counts": row_counts,
        "scoped_row_counts": scoped_row_counts,
    }


def _scoped_row_counts(
    connection: Any,
    *,
    state_ids: list[str],
    result_ids: list[str],
    idempotency_key: str | None,
) -> dict[str, int]:
    state_count = 0
    if idempotency_key:
        state_count = _scalar_count(
            connection,
            """
            SELECT count(*)
            FROM ae_daemon_operator_control_execution_states
            WHERE idempotency_key = :idempotency_key
            """,
            {"idempotency_key": idempotency_key},
        )
    for state_id in state_ids:
        if not idempotency_key:
            state_count += _scalar_count(
                connection,
                """
                SELECT count(*)
                FROM ae_daemon_operator_control_execution_states
                WHERE operator_control_execution_state_id =
                      :operator_control_execution_state_id
                """,
                {"operator_control_execution_state_id": state_id},
            )
    transition_count = sum(
        _scalar_count(
            connection,
            """
            SELECT count(*)
            FROM ae_daemon_operator_control_execution_transitions
            WHERE operator_control_execution_state_id =
                  :operator_control_execution_state_id
            """,
            {"operator_control_execution_state_id": state_id},
        )
        for state_id in state_ids
    )
    result_count = sum(
        _scalar_count(
            connection,
            f"""
            SELECT count(*)
            FROM {AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE}
            WHERE operator_control_execution_worker_result_id =
                  :operator_control_execution_worker_result_id
            """,
            {"operator_control_execution_worker_result_id": result_id},
        )
        for result_id in result_ids
    )
    return {
        "execution_states": state_count,
        "execution_transitions": transition_count,
        "worker_results": result_count,
    }


def _schema_migration_recorded(connection: Any) -> bool:
    try:
        versions = {
            row
            for row in connection.execute(
                text(
                    """
                    SELECT version
                    FROM schema_migrations
                    WHERE version IN (:execution_version, :result_version)
                    """
                ),
                {
                    "execution_version": worker_pg.MIGRATION_VERSION,
                    "result_version": MIGRATION_VERSION,
                },
            )
            .scalars()
            .all()
        }
    except SQLAlchemyError:
        return False
    return {worker_pg.MIGRATION_VERSION, MIGRATION_VERSION}.issubset(versions)


def _indexes_present(connection: Any, dialect_name: str) -> list[str]:
    if dialect_name == "postgresql":
        rows = (
            connection.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename IN (
                        'ae_daemon_operator_control_execution_states',
                        'ae_daemon_operator_control_execution_transitions',
                        'ae_op_exec_worker_results'
                      )
                    ORDER BY indexname
                    """
                )
            )
            .scalars()
            .all()
        )
    else:
        rows = (
            connection.execute(
                text(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'index'
                      AND tbl_name IN (
                        'ae_daemon_operator_control_execution_states',
                        'ae_daemon_operator_control_execution_transitions',
                        'ae_op_exec_worker_results'
                      )
                    ORDER BY name
                    """
                )
            )
            .scalars()
            .all()
        )
    return sorted(set(rows).intersection(EXPECTED_INDEXES))


def _jsonb_column_types(
    connection: Any,
    dialect_name: str,
    result_ids: list[str],
) -> dict[str, str]:
    if dialect_name != "postgresql" or not result_ids:
        return {}
    row = (
        connection.execute(
            text(
                f"""
                SELECT
                    pg_typeof(status_path)::text AS status_path,
                    pg_typeof(supervisor_result_statuses)::text
                        AS supervisor_result_statuses,
                    pg_typeof(supervisor_actions)::text AS supervisor_actions,
                    pg_typeof(supervisor_result_ids)::text AS supervisor_result_ids,
                    pg_typeof(guardrails)::text AS guardrails,
                    pg_typeof(metadata)::text AS metadata
                FROM {AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE}
                WHERE operator_control_execution_worker_result_id =
                      :operator_control_execution_worker_result_id
                LIMIT 1
                """
            ),
            {"operator_control_execution_worker_result_id": result_ids[0]},
        )
        .mappings()
        .first()
    )
    return {
        f"result.{key}": value for key, value in dict(row or {}).items()
    }


def _scalar_count(connection: Any, sql: str, params: dict[str, Any]) -> int:
    return int(connection.execute(text(sql), params).scalar() or 0)


def _ensure_sqlite_migration_marker(engine: Any) -> None:
    with engine.begin() as connection:
        if connection.dialect.name != "sqlite":
            return
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT OR IGNORE INTO schema_migrations (version, description)
                VALUES (
                    :version,
                    'SQLite marker for worker result route smoke'
                )
                """
            ),
            {"version": MIGRATION_VERSION},
        )


def _cleanup_worker_result_rows(
    *,
    result_store: SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore,
    execution_store: SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore,
    result_ids: list[str],
    state_ids: list[str],
) -> dict[str, int]:
    cleanup = {
        "operator_control_execution_worker_results": 0,
        "execution_state_transitions": 0,
        "execution_states": 0,
    }
    for result_id in result_ids:
        deleted = result_store.delete_worker_result(result_id)
        cleanup["operator_control_execution_worker_results"] += int(
            deleted.get("operator_control_execution_worker_results", 0)
        )
    deleted_states = worker_pg._cleanup_execution_states(execution_store, state_ids)
    cleanup["execution_state_transitions"] += int(
        deleted_states.get("execution_state_transitions", 0)
    )
    cleanup["execution_states"] += int(deleted_states.get("execution_states", 0))
    return cleanup


def _smoke_checks(
    *,
    database_url: str,
    database_env: str,
    admitted_response: int,
    worker_response: int,
    admitted_payload: Mapping[str, Any],
    worker_payload: Mapping[str, Any],
    result_record: Mapping[str, Any] | None,
    result_collection: list[Mapping[str, Any]],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, bool]:
    execution_evidence = worker_pg.ae_execution_pg._execution_evidence(
        admitted_payload
    )
    worker_evidence = worker_pg._worker_evidence(worker_payload)
    record_evidence = _worker_result_record_evidence(result_record or {})
    expected_scoped_after = {
        "execution_states": 1,
        "execution_transitions": 0,
        "worker_results": 1,
    }
    return {
        "test_database_url": database_env == "NEX_AE_TEST_DATABASE_URL"
        and worker_pg.ae_execution_pg._database_name(database_url).endswith("_test"),
        "database_health_probe": before.get("health_probe") is True
        and after.get("health_probe") is True,
        "migration_recorded": before.get("migration_recorded") is True
        and after.get("migration_recorded") is True,
        "tables_present": EXPECTED_TABLES.issubset(
            set(after.get("tables_present", []))
        ),
        "indexes_present": EXPECTED_INDEXES.issubset(
            set(after.get("indexes_present", []))
        ),
        "postgres_jsonb_columns": after.get("dialect") != "postgresql"
        or after.get("jsonb_columns") == EXPECTED_JSONB_TYPES,
        "persisted_execution_route_passed": admitted_response == 200
        and execution_evidence["execution_status"] == "ADMITTED"
        and execution_evidence["execution_mode"]
        == "fake_dry_run_supervisor_persistent_dispatch"
        and execution_evidence["idempotency_status"] == "NEW"
        and execution_evidence["database_write_performed"] is False,
        "persisted_worker_result_route_passed": worker_response == 200
        and worker_evidence["worker_status"] == "SUCCEEDED"
        and worker_evidence["state_id"] == execution_evidence["state_id"]
        and worker_evidence["plan_status"] == "READY"
        and worker_evidence["command_status"] == "READY"
        and worker_evidence["transition_plan_status"] == "READY"
        and worker_evidence["database_write_performed"] is False
        and worker_evidence["transition_persistence_performed"] is False,
        "worker_result_record_written": record_evidence["schema_version"]
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_RECORD_SCHEMA_VERSION
        and record_evidence["worker_result_id"] == worker_evidence["worker_result_id"]
        and record_evidence["state_id"] == execution_evidence["state_id"]
        and record_evidence["worker_status"] == "SUCCEEDED"
        and record_evidence["status_path"]
        == ["ADMITTED", "EXECUTING", "SUCCEEDED"]
        and record_evidence["database_write_performed"] is True
        and record_evidence["safe_summary_only"] is True
        and record_evidence["stores_full_worker_result_payload"] is False
        and record_evidence["stores_full_supervisor_result_payload"] is False
        and record_evidence["stored_table"]
        == AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE
        and record_evidence["hashes_present"] is True,
        "result_collection_reads_scoped_record": len(result_collection) == 1
        and result_collection[0].get(
            "operator_control_execution_worker_result_id"
        )
        == worker_evidence["worker_result_id"],
        "scoped_rows_written": before.get("scoped_row_counts")
        == {
            "execution_states": 0,
            "execution_transitions": 0,
            "worker_results": 0,
        }
        and after.get("scoped_row_counts") == expected_scoped_after,
        "no_transition_rows_written": after.get("scoped_row_counts")
        == expected_scoped_after,
        "worker_guardrails_hold": worker_evidence["supervisor_adapter_invoked"]
        is True
        and worker_evidence["subprocess_started"] is False
        and worker_evidence["physical_delete_automation_enabled"] is False
        and worker_evidence["safe_for_ag_projection"] is True,
    }


def _mapping_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _append_optional_text(values: list[str], value: Any) -> str | None:
    text_value = _text_or_none(value)
    if text_value is not None:
        values.append(text_value)
    return text_value


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
    safe = worker_pg._safe_detail(detail, env)
    for key in (SMOKE_PROFILE_ENV,):
        value = env.get(key)
        if value:
            safe = safe.replace(value, f"<redacted:{key}>")
    password = worker_pg.ae_execution_pg._database_url_password(
        env.get(service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE))
    )
    if password:
        safe = safe.replace(password, "***")
    return safe


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    worker_pg.assert_smoke_evidence_redacted(serialized_evidence, environ)
    database_url = environ.get(
        service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE)
    )
    password = worker_pg.ae_execution_pg._database_url_password(database_url)
    if password and password in serialized_evidence:
        raise ValueError(
            "AE worker result smoke contains a database password."
        )
    if "ed6@c496em" in serialized_evidence:
        raise ValueError("AE worker result smoke contains a provider API key.")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_operator_control_execution_worker_result_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        scoped_rows = evidence["db_observations"]["after"]["scoped_row_counts"]
        cleanup = evidence["cleanup"]
        return (
            "ae_operator_control_execution_worker_result_postgres_smoke="
            f"pass service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            "routes=2 "
            f"worker={evidence['worker']['worker_status']} "
            f"results={scoped_rows['worker_results']} "
            f"states={scoped_rows['execution_states']} "
            f"transitions={scoped_rows['execution_transitions']} "
            f"cleanup_results={cleanup['operator_control_execution_worker_results']} "
            f"cleanup_states={cleanup['execution_states']} "
            f"live_db={str(evidence['live_db']).lower()}"
        )
    return (
        "ae_operator_control_execution_worker_result_postgres_smoke="
        f"fail service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE operator-control execution worker result "
            "PostgreSQL smoke."
        )
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.local")
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(args.env_file)
    evidence = run_ae_operator_control_execution_worker_result_postgres_smoke()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
