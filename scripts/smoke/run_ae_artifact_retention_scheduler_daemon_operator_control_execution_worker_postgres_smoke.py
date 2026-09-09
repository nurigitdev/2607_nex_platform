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

import run_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke as ae_execution_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifact_retention_scheduler_daemon import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_SCHEMA_VERSION,
    SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore,
    SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore,
    SqlAlchemyArtifactRetentionSchedulerDaemonSupervisorStore,
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
    "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE"
)
SMOKE_PROFILE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = ae_execution_pg.SERVICE_ID
DEFAULT_PROFILE = ae_execution_pg.DEFAULT_PROFILE
MIGRATION_VERSION = "0596_ae_operator_control_execution_persistence"
CHECKED_AT = "2026-09-08T08:25:00Z"
REQUESTED_AT = "2026-09-08T08:24:55Z"
WORKER_OBSERVED_AT = "2026-09-08T08:25:20Z"
TRANSITIONED_AT = "2026-09-08T08:25:35Z"
EXECUTION_ROUTE = (
    "/api/v1/artifact-retention/scheduler-daemon-operator-control-executions"
)
WORKER_ROUTE = (
    "/api/v1/artifact-retention/"
    "scheduler-daemon-operator-control-execution-workers"
)
TRANSITION_ROUTE = (
    "/api/v1/artifact-retention/"
    "scheduler-daemon-operator-control-execution-transitions"
)
EXPECTED_EXECUTION_TABLES = {
    "ae_daemon_operator_control_execution_states",
    "ae_daemon_operator_control_execution_transitions",
}
EXPECTED_EXECUTION_INDEXES = {
    "idx_ae_operator_control_execution_states_observed",
    "idx_ae_operator_control_execution_states_status",
    "idx_ae_operator_control_execution_states_idempotency",
    "idx_ae_operator_control_execution_states_request",
    "idx_ae_operator_control_execution_transitions_state",
    "idx_ae_operator_control_execution_transitions_scheduler",
}
EXPECTED_TABLES = ae_execution_pg.EXPECTED_TABLES | EXPECTED_EXECUTION_TABLES
EXPECTED_INDEXES = ae_execution_pg.EXPECTED_INDEXES | EXPECTED_EXECUTION_INDEXES
EXPECTED_JSONB_TYPES = {
    "state.allowed_next_statuses": "jsonb",
    "state.guardrails": "jsonb",
    "state.metadata": "jsonb",
    "state.operator_control_execution_request": "jsonb",
    "transition.operator_control_execution_state": "jsonb",
    "transition.guardrails": "jsonb",
    "transition.metadata": "jsonb",
}


def run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke(
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
            f"{SMOKE_PROFILE_ENV} must be test for worker PostgreSQL smoke.",
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
        execution = _execute_operator_control_execution_worker_route_smoke(
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


def _execute_operator_control_execution_worker_route_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    idempotency_key = f"slice-0606-worker-{suffix}"
    state_ids: list[str] = []
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        ae_execution_pg.process_pg._ensure_sqlite_migration_marker(engine)
        ae_execution_pg.supervisor_pg._ensure_sqlite_migration_marker(engine)
        _ensure_sqlite_migration_marker(engine)
        execution_store = (
            SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
                session_factory
            )
        )
        process_store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore(
            session_factory
        )
        supervisor_store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisorStore(
            session_factory
        )
        process_store.ensure_schema()
        supervisor_store.ensure_schema()
        execution_store.ensure_schema()
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
        )
        client = TestClient(app)
        headers = ae_execution_pg.artifact_pg._auth_headers(
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
        admitted_payload = ae_execution_pg._json_payload(admitted_response)
        state_id = _text_or_none(
            admitted_payload.get("operator_control_execution_state_id")
        )
        if state_id is not None:
            state_ids.append(state_id)

        worker_response = client.post(
            WORKER_ROUTE,
            json={
                "operator_control_execution_state_id": state_id,
                "checked_at": CHECKED_AT,
                "worker_observed_at": WORKER_OBSERVED_AT,
            },
            headers=headers,
        )
        worker_payload = ae_execution_pg._json_payload(worker_response)

        transition_response = client.post(
            TRANSITION_ROUTE,
            json={
                "operator_control_execution_state": admitted_payload,
                "target_status": "EXECUTING",
                "decision_reason": (
                    "slice_0606_worker_smoke_transition_to_executing"
                ),
                "transitioned_at": TRANSITIONED_AT,
                "persist_transition": True,
            },
            headers=headers,
        )
        transition_payload = ae_execution_pg._json_payload(transition_response)

        detail_response = client.get(
            f"{EXECUTION_ROUTE}/{state_id or 'missing-state'}",
            headers=headers,
        )
        detail_payload = ae_execution_pg._json_payload(detail_response)
        after = _db_observations(
            engine,
            state_ids=state_ids,
            scheduler_id=_text_or_none(admitted_payload.get("scheduler_id")),
            idempotency_key=idempotency_key,
        )

        checks = _smoke_checks(
            database_url=database_url,
            database_env=database_env,
            admitted_response=admitted_response.status_code,
            worker_response=worker_response.status_code,
            transition_response=transition_response.status_code,
            detail_response=detail_response.status_code,
            admitted_payload=admitted_payload,
            worker_payload=worker_payload,
            transition_payload=transition_payload,
            detail_payload=detail_payload,
            before=before,
            after=after,
        )
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "AE scheduler daemon operator-control execution worker "
                "PostgreSQL smoke checks failed: "
                f"{', '.join(failed_checks)}"
            )

        cleanup = _cleanup_execution_states(execution_store, state_ids)
        post_cleanup = _db_observations(
            engine,
            state_ids=state_ids,
            idempotency_key=idempotency_key,
        )
        if post_cleanup["scoped_row_counts"] != {
            "execution_states": 0,
            "execution_transitions": 0,
        }:
            raise RuntimeError(
                "AE scheduler daemon operator-control execution worker "
                "PostgreSQL smoke cleanup verification failed."
            )

        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "persisted": {
                "execution_state_id": state_id,
                "transition_id": transition_payload.get(
                    "operator_control_execution_state_transition_id"
                ),
            },
            "routes": {
                "ae_persisted_execution_status": admitted_response.status_code,
                "ae_worker_status": worker_response.status_code,
                "ae_persisted_transition_status": transition_response.status_code,
                "ae_execution_detail_status": detail_response.status_code,
            },
            "execution": ae_execution_pg._execution_evidence(admitted_payload),
            "worker": _worker_evidence(worker_payload),
            "transition": ae_execution_pg._transition_evidence(transition_payload),
            "detail": _detail_evidence(detail_payload),
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
        if state_ids:
            try:
                session_factory = build_session_factory(engine)
                execution_store = (
                    SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
                        session_factory
                    )
                )
                _cleanup_execution_states(execution_store, state_ids)
            except (SQLAlchemyError, RuntimeError, ValueError):
                pass
        engine.dispose()


def _execution_payload(*, suffix: str) -> dict[str, Any]:
    reason = "slice_0606_worker_postgresql_fake_dispatch_admission"
    payload = ae_execution_pg._execution_payload(
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


def _worker_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    command = _mapping_value(payload.get("operator_control_execution_worker_command"))
    plan = _mapping_value(command.get("operator_control_execution_worker_plan"))
    transition_plan = _mapping_value(
        payload.get("operator_control_execution_worker_transition_plan")
    )
    guardrails = _mapping_value(payload.get("guardrails"))
    metadata = _mapping_value(payload.get("metadata"))
    return {
        "schema_version": payload.get(
            "operator_control_execution_worker_result_schema_version"
        ),
        "worker_result_id": payload.get("operator_control_execution_worker_result_id"),
        "worker_command_id": payload.get(
            "operator_control_execution_worker_command_id"
        ),
        "worker_plan_id": payload.get("operator_control_execution_worker_plan_id"),
        "state_id": payload.get("operator_control_execution_state_id"),
        "request_id": payload.get("operator_control_execution_request_id"),
        "action": payload.get("action"),
        "execution_mode": payload.get("execution_mode"),
        "worker_status": payload.get("worker_status"),
        "decision_reason": payload.get("decision_reason"),
        "observed_at": payload.get("observed_at"),
        "plan_status": plan.get("plan_status"),
        "command_status": command.get("command_status"),
        "transition_plan_status": transition_plan.get("transition_plan_status"),
        "terminal_status": transition_plan.get("terminal_status"),
        "transition_count": transition_plan.get("transition_count"),
        "status_path": list(metadata.get("status_path", [])),
        "supervisor_result_count": payload.get("supervisor_result_count"),
        "supervisor_result_statuses": list(
            metadata.get("supervisor_result_statuses", [])
        ),
        "worker_execution_performed": metadata.get("worker_execution_performed"),
        "database_write_performed": metadata.get("database_write_performed"),
        "transition_persistence_performed": metadata.get(
            "transition_persistence_performed"
        ),
        "supervisor_adapter_invoked": guardrails.get("supervisor_adapter_invoked"),
        "subprocess_started": guardrails.get("subprocess_started"),
        "physical_delete_automation_enabled": guardrails.get(
            "physical_delete_automation_enabled"
        ),
        "safe_for_ag_projection": metadata.get("safe_for_ag_projection"),
    }


def _detail_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": payload.get("operator_control_execution_detail_schema_version"),
        "state_id": payload.get("operator_control_execution_state_id"),
        "transition_count": payload.get("transition_count"),
        "transition_statuses": list(
            _mapping_value(payload.get("metadata")).get("transition_statuses", [])
        ),
    }


def _db_observations(
    engine: Any,
    *,
    state_ids: list[str] | None = None,
    scheduler_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    target_state_ids = state_ids or []
    with engine.connect() as connection:
        dialect_name = connection.dialect.name
        health_probe = connection.execute(text("SELECT 1")).scalar() == 1
        tables_present = sorted(
            table_name
            for table_name in EXPECTED_TABLES
            if ae_execution_pg._table_exists(connection, table_name)
        )
        row_counts = {
            "process_records": ae_execution_pg._table_count(
                connection,
                "ae_artifact_retention_scheduler_daemon_process_snapshots",
            ),
            "process_events": ae_execution_pg._table_count(
                connection,
                "ae_artifact_retention_scheduler_daemon_process_events",
            ),
            "supervisor_records": ae_execution_pg._table_count(
                connection,
                "ae_artifact_retention_scheduler_daemon_supervisor_results",
            ),
            "supervisor_events": ae_execution_pg._table_count(
                connection,
                "ae_artifact_retention_scheduler_daemon_supervisor_events",
            ),
            "execution_states": ae_execution_pg._table_count(
                connection,
                "ae_daemon_operator_control_execution_states",
            ),
            "execution_transitions": ae_execution_pg._table_count(
                connection,
                "ae_daemon_operator_control_execution_transitions",
            ),
        }
        scoped_row_counts = _scoped_row_counts(
            connection,
            state_ids=target_state_ids,
            idempotency_key=idempotency_key,
        )
        migration_recorded = _schema_migration_recorded(connection)
        indexes_present = _indexes_present(connection, dialect_name)
        jsonb_columns = _jsonb_column_types(
            connection,
            dialect_name,
            target_state_ids,
        )
    return {
        "dialect": dialect_name,
        "health_probe": health_probe,
        "tables_present": tables_present,
        "indexes_present": indexes_present,
        "migration_recorded": migration_recorded,
        "row_counts": row_counts,
        "scoped_row_counts": scoped_row_counts,
        "scheduler_id": scheduler_id,
        "jsonb_columns": jsonb_columns,
    }


def _scoped_row_counts(
    connection: Any,
    *,
    state_ids: list[str],
    idempotency_key: str | None,
) -> dict[str, int]:
    state_count = 0
    transition_count = 0
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
        transition_count += _scalar_count(
            connection,
            """
            SELECT count(*)
            FROM ae_daemon_operator_control_execution_transitions
            WHERE operator_control_execution_state_id =
                  :operator_control_execution_state_id
            """,
            {"operator_control_execution_state_id": state_id},
        )
    return {
        "execution_states": state_count,
        "execution_transitions": transition_count,
    }


def _schema_migration_recorded(connection: Any) -> bool:
    try:
        return (
            ae_execution_pg.process_pg._schema_migration_recorded(connection)
            and ae_execution_pg.supervisor_pg._schema_migration_recorded(connection)
            and bool(
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
        )
    except SQLAlchemyError:
        return False


def _indexes_present(connection: Any, dialect_name: str) -> list[str]:
    if dialect_name == "postgresql":
        execution_indexes = (
            connection.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename IN (
                        'ae_daemon_operator_control_execution_states',
                        'ae_daemon_operator_control_execution_transitions'
                      )
                    ORDER BY indexname
                    """
                )
            )
            .scalars()
            .all()
        )
    else:
        execution_indexes = (
            connection.execute(
                text(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'index'
                      AND tbl_name IN (
                        'ae_daemon_operator_control_execution_states',
                        'ae_daemon_operator_control_execution_transitions'
                      )
                    ORDER BY name
                    """
                )
            )
            .scalars()
            .all()
        )
    return sorted(
        (
            set(ae_execution_pg.process_pg._indexes_present(connection, dialect_name))
            | set(
                ae_execution_pg.supervisor_pg._indexes_present(
                    connection,
                    dialect_name,
                )
            )
            | set(execution_indexes).intersection(EXPECTED_EXECUTION_INDEXES)
        ).intersection(EXPECTED_INDEXES)
    )


def _jsonb_column_types(
    connection: Any,
    dialect_name: str,
    state_ids: list[str],
) -> dict[str, str]:
    if dialect_name != "postgresql" or not state_ids:
        return {}
    state_row = (
        connection.execute(
            text(
                """
                SELECT
                    pg_typeof(allowed_next_statuses)::text
                        AS allowed_next_statuses,
                    pg_typeof(guardrails)::text AS guardrails,
                    pg_typeof(metadata)::text AS metadata,
                    pg_typeof(operator_control_execution_request)::text
                        AS operator_control_execution_request
                FROM ae_daemon_operator_control_execution_states
                WHERE operator_control_execution_state_id =
                      :operator_control_execution_state_id
                LIMIT 1
                """
            ),
            {"operator_control_execution_state_id": state_ids[0]},
        )
        .mappings()
        .first()
    )
    transition_row = (
        connection.execute(
            text(
                """
                SELECT
                    pg_typeof(operator_control_execution_state)::text
                        AS operator_control_execution_state,
                    pg_typeof(guardrails)::text AS guardrails,
                    pg_typeof(metadata)::text AS metadata
                FROM ae_daemon_operator_control_execution_transitions
                WHERE operator_control_execution_state_id =
                      :operator_control_execution_state_id
                LIMIT 1
                """
            ),
            {"operator_control_execution_state_id": state_ids[0]},
        )
        .mappings()
        .first()
    )
    result: dict[str, str] = {}
    if state_row:
        result.update({f"state.{key}": value for key, value in dict(state_row).items()})
    if transition_row:
        result.update(
            {f"transition.{key}": value for key, value in dict(transition_row).items()}
        )
    return result


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
                    'SQLite marker for operator-control worker smoke'
                )
                """
            ),
            {"version": MIGRATION_VERSION},
        )


def _cleanup_execution_states(
    execution_store: SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore,
    state_ids: list[str],
) -> dict[str, int]:
    cleanup = {"execution_state_transitions": 0, "execution_states": 0}
    for state_id in state_ids:
        deleted = execution_store.delete_execution_state(state_id)
        cleanup["execution_state_transitions"] += int(
            deleted.get("execution_state_transitions", 0)
        )
        cleanup["execution_states"] += int(deleted.get("execution_states", 0))
    return cleanup


def _smoke_checks(
    *,
    database_url: str,
    database_env: str,
    admitted_response: int,
    worker_response: int,
    transition_response: int,
    detail_response: int,
    admitted_payload: Mapping[str, Any],
    worker_payload: Mapping[str, Any],
    transition_payload: Mapping[str, Any],
    detail_payload: Mapping[str, Any],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, bool]:
    execution_evidence = ae_execution_pg._execution_evidence(admitted_payload)
    worker_evidence = _worker_evidence(worker_payload)
    transition_evidence = ae_execution_pg._transition_evidence(transition_payload)
    detail_evidence = _detail_evidence(detail_payload)
    side_effect_keys = (
        "process_records",
        "process_events",
        "supervisor_records",
        "supervisor_events",
    )
    return {
        "test_database_url": database_env == "NEX_AE_TEST_DATABASE_URL"
        and ae_execution_pg._database_name(database_url).endswith("_test"),
        "database_health_probe": before.get("health_probe") is True
        and after.get("health_probe") is True,
        "migration_recorded": before.get("migration_recorded") is True
        and after.get("migration_recorded") is True,
        "execution_tables_present": EXPECTED_EXECUTION_TABLES.issubset(
            set(after.get("tables_present", []))
        ),
        "execution_indexes_present": EXPECTED_EXECUTION_INDEXES.issubset(
            set(after.get("indexes_present", []))
        ),
        "postgres_jsonb_columns": after.get("dialect") != "postgresql"
        or after.get("jsonb_columns") == EXPECTED_JSONB_TYPES,
        "persisted_execution_route_passed": admitted_response == 200
        and execution_evidence["schema_version"]
        == ae_execution_pg.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_SCHEMA_VERSION
        and execution_evidence["execution_mode"]
        == "fake_dry_run_supervisor_persistent_dispatch"
        and execution_evidence["execution_status"] == "ADMITTED"
        and execution_evidence["idempotency_status"] == "NEW"
        and execution_evidence["database_write_performed"] is False,
        "worker_state_id_route_passed": worker_response == 200
        and worker_evidence["schema_version"]
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_SCHEMA_VERSION
        and worker_evidence["state_id"] == execution_evidence["state_id"]
        and worker_evidence["worker_status"] == "SUCCEEDED"
        and worker_evidence["plan_status"] == "READY"
        and worker_evidence["command_status"] == "READY"
        and worker_evidence["transition_plan_status"] == "READY"
        and worker_evidence["terminal_status"] == "SUCCEEDED"
        and worker_evidence["transition_count"] == 2
        and worker_evidence["status_path"]
        == ["ADMITTED", "EXECUTING", "SUCCEEDED"]
        and worker_evidence["supervisor_result_count"] == 1
        and worker_evidence["worker_execution_performed"] is True
        and worker_evidence["database_write_performed"] is False,
        "worker_guardrails_hold": worker_evidence["supervisor_adapter_invoked"] is True
        and worker_evidence["subprocess_started"] is False
        and worker_evidence["transition_persistence_performed"] is False
        and worker_evidence["physical_delete_automation_enabled"] is False
        and worker_evidence["safe_for_ag_projection"] is True,
        "persisted_transition_route_passed": transition_response == 200
        and transition_evidence["schema_version"]
        == ae_execution_pg.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_TRANSITION_SCHEMA_VERSION
        and transition_evidence["state_id"] == execution_evidence["state_id"]
        and transition_evidence["from_status"] == "ADMITTED"
        and transition_evidence["to_status"] == "EXECUTING"
        and transition_evidence["database_write_performed"] is False,
        "detail_route_reads_persisted_rows": detail_response == 200
        and detail_evidence["state_id"] == execution_evidence["state_id"]
        and detail_evidence["transition_count"] == 1
        and detail_evidence["transition_statuses"] == ["ADMITTED->EXECUTING"],
        "scoped_rows_written": before.get("scoped_row_counts")
        == {"execution_states": 0, "execution_transitions": 0}
        and after.get("scoped_row_counts")
        == {"execution_states": 1, "execution_transitions": 1},
        "no_process_or_supervisor_rows_added": all(
            _mapping_value(before.get("row_counts")).get(key)
            == _mapping_value(after.get("row_counts")).get(key)
            for key in side_effect_keys
        ),
    }


def _mapping_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


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
    safe = ae_execution_pg._safe_detail(detail, env)
    for key in (SMOKE_PROFILE_ENV,):
        value = env.get(key)
        if value:
            safe = safe.replace(value, f"<redacted:{key}>")
    password = ae_execution_pg._database_url_password(
        env.get(service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE))
    )
    if password:
        safe = safe.replace(password, "***")
    return safe


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    ae_execution_pg.assert_smoke_evidence_redacted(serialized_evidence, environ)
    database_url = environ.get(
        service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE)
    )
    password = ae_execution_pg._database_url_password(database_url)
    if password and password in serialized_evidence:
        raise ValueError(
            "AE operator-control execution worker smoke contains a database password."
        )
    if "ed6@c496em" in serialized_evidence:
        raise ValueError(
            "AE operator-control execution worker smoke contains a provider API key."
        )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke="
            f"pass service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            "routes=4 "
            f"worker={evidence['worker']['worker_status']} "
            f"states={evidence['db_observations']['after']['scoped_row_counts']['execution_states']} "
            f"transitions={evidence['db_observations']['after']['scoped_row_counts']['execution_transitions']} "
            f"cleanup_states={evidence['cleanup']['execution_states']} "
            f"cleanup_transitions={evidence['cleanup']['execution_state_transitions']} "
            f"live_db={str(evidence['live_db']).lower()}"
        )
    return (
        "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke="
        f"fail service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE scheduler daemon operator-control execution "
            "worker PostgreSQL smoke."
        )
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.local")
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(args.env_file)
    evidence = run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
