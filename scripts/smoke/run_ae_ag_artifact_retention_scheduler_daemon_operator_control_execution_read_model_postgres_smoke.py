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
AG_PATH = ROOT / "services" / "nex-ag"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(SMOKE_PATH))

import run_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke as ae_execution_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifact_retention_scheduler_daemon import (  # noqa: E402
    SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore,
    SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore,
    SqlAlchemyArtifactRetentionSchedulerDaemonSupervisorStore,
)
from nex_ae_api.artifacts import register_artifact_handoff_routes  # noqa: E402
from nex_ag.artifact_operations import (  # noqa: E402
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_DETAIL_PROJECTION_SCHEMA_VERSION,
    AeArtifactOperationsError,
    register_artifact_operation_routes,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
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


SCHEMA_VERSION = (
    "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_READ_MODEL_POSTGRES_SMOKE"
)
SMOKE_PROFILE_ENV = (
    "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_READ_MODEL_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = ae_execution_pg.SERVICE_ID
AG_SERVICE_ID = "nex-ag"
DEFAULT_PROFILE = ae_execution_pg.DEFAULT_PROFILE
MIGRATION_VERSION = "0596_ae_operator_control_execution_persistence"
TRANSITIONED_AT = "2026-09-08T07:58:35Z"
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


class AeTestClientDaemonOperatorControlExecutionReadModelClient:
    source_kind = "ae_test_client"
    base_url = "testclient://nex-ae-api"

    def __init__(self, client: TestClient, headers: Mapping[str, str]) -> None:
        self.client = client
        self.headers = dict(headers)
        self.execution_collection_statuses: list[int] = []
        self.execution_detail_statuses: list[int] = []

    def list_artifact_retention_scheduler_daemon_operator_control_executions(
        self,
        *,
        scheduler_id: str | None,
        action: str | None,
        execution_status: str | None,
        idempotency_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.get(
            "/api/v1/artifact-retention/"
            "scheduler-daemon-operator-control-executions",
            params={
                "limit": str(limit),
                **({"scheduler_id": scheduler_id} if scheduler_id else {}),
                **({"action": action} if action else {}),
                **(
                    {"execution_status": execution_status}
                    if execution_status
                    else {}
                ),
                **(
                    {"idempotency_status": idempotency_status}
                    if idempotency_status
                    else {}
                ),
            },
            headers=self._headers(request_id=request_id, trace_id=trace_id),
        )
        self.execution_collection_statuses.append(response.status_code)
        return self._json_or_error(response)

    def get_artifact_retention_scheduler_daemon_operator_control_execution_detail(
        self,
        operator_control_execution_state_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        response = self.client.get(
            "/api/v1/artifact-retention/"
            "scheduler-daemon-operator-control-executions/"
            f"{operator_control_execution_state_id}",
            headers=self._headers(request_id=request_id, trace_id=trace_id),
        )
        self.execution_detail_statuses.append(response.status_code)
        if response.status_code == 404:
            return None
        return self._json_or_error(response)

    def _headers(self, *, request_id: str, trace_id: str) -> dict[str, str]:
        return {
            **self.headers,
            "X-Request-ID": request_id,
            "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        }

    @staticmethod
    def _json_or_error(response: Any) -> dict[str, Any]:
        payload = _json_payload(response) if response.content else {}
        if response.status_code >= 400:
            raise AeArtifactOperationsError(
                error_code=payload.get(
                    "error_code",
                    "ag.ae_artifact_retention_daemon_operator_control_execution_source_failed",
                ),
                detail=payload.get(
                    "detail",
                    "AE artifact retention scheduler daemon operator-control "
                    "execution source failed.",
                ),
                status_code=response.status_code,
            )
        return payload if isinstance(payload, dict) else {}


def run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke(
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
            f"{SMOKE_PROFILE_ENV} must be test for AG-to-AE PostgreSQL smoke.",
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
        execution = _execute_ae_ag_operator_control_execution_read_model_smoke(
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
        "ag_service_id": AG_SERVICE_ID,
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


def _execute_ae_ag_operator_control_execution_read_model_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    idempotency_key = f"slice-0599-admitted-{suffix}"
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
        before = _db_observations(
            engine,
            idempotency_key=idempotency_key,
        )

        ae_app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        ae_app.state.nex_persistence = SimpleNamespace(
            api_session_factory=session_factory
        )
        register_artifact_handoff_routes(
            ae_app,
            retention_scheduler_daemon_operator_control_execution_store=execution_store,
        )
        ae_client = TestClient(ae_app)
        ae_headers = ae_execution_pg.artifact_pg._auth_headers(
            request_id=request_id,
            trace_id=trace_id,
        )

        admitted_response = ae_client.post(
            "/api/v1/artifact-retention/"
            "scheduler-daemon-operator-control-executions",
            json={
                **ae_execution_pg._execution_payload(
                    suffix=suffix,
                    reason="slice_0599_persisted_dispatch_admission",
                    execution_mode="fake_dry_run_supervisor_persistent_dispatch",
                ),
                "persist_execution_state": True,
            },
            headers={**ae_headers, "Idempotency-Key": idempotency_key},
        )
        admitted_payload = _json_payload(admitted_response)
        state_id = _text_or_none(
            admitted_payload.get("operator_control_execution_state_id")
        )
        if state_id is not None:
            state_ids.append(state_id)

        transition_response = ae_client.post(
            "/api/v1/artifact-retention/"
            "scheduler-daemon-operator-control-execution-transitions",
            json={
                "operator_control_execution_state": admitted_payload,
                "target_status": "EXECUTING",
                "decision_reason": (
                    "slice_0599_ag_read_model_transition_to_executing"
                ),
                "transitioned_at": TRANSITIONED_AT,
                "persist_transition": True,
            },
            headers=ae_headers,
        )
        transition_payload = _json_payload(transition_response)

        scheduler_id = _text_or_none(admitted_payload.get("scheduler_id"))
        bridge = AeTestClientDaemonOperatorControlExecutionReadModelClient(
            ae_client,
            headers=ae_headers,
        )
        ag_app = build_service_app(SERVICE_SPECS[AG_SERVICE_ID])
        register_artifact_operation_routes(ag_app, client=bridge)
        ag_client = TestClient(ag_app)
        ag_headers = _ag_auth_headers(request_id=request_id, trace_id=trace_id)

        ag_collection_response = ag_client.get(
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-executions",
            params={
                "service_id": SERVICE_ID,
                "scheduler_id": scheduler_id or "missing-scheduler",
                "action": "start-daemon",
                "execution_status": "admitted",
                "idempotency_status": "new",
                "limit": "5",
            },
            headers=ag_headers,
        )
        ag_collection = _json_payload(ag_collection_response)
        ag_detail_response = ag_client.get(
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-executions/"
            f"{state_id or 'missing'}",
            params={"service_id": SERVICE_ID},
            headers=ag_headers,
        )
        ag_detail = _json_payload(ag_detail_response)
        after = _db_observations(
            engine,
            state_ids=state_ids,
            scheduler_id=scheduler_id,
            idempotency_key=idempotency_key,
        )

        checks = _smoke_checks(
            database_url=database_url,
            database_env=database_env,
            admitted_response=admitted_response.status_code,
            transition_response=transition_response.status_code,
            admitted_payload=admitted_payload,
            transition_payload=transition_payload,
            before=before,
            after=after,
            bridge=bridge,
            ag_collection_status=ag_collection_response.status_code,
            ag_collection=ag_collection,
            ag_detail_status=ag_detail_response.status_code,
            ag_detail=ag_detail,
        )
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "AE/AG scheduler daemon operator-control execution read-model "
                "PostgreSQL smoke checks failed: "
                f"{', '.join(failed_checks)}"
            )

        cleanup = _cleanup_execution_states(execution_store, state_ids)
        post_cleanup = _db_observations(
            engine,
            state_ids=state_ids,
            scheduler_id=scheduler_id,
            idempotency_key=idempotency_key,
        )
        if post_cleanup["scoped_row_counts"] != {
            "execution_states": 0,
            "execution_transitions": 0,
        }:
            raise RuntimeError(
                "AE/AG scheduler daemon operator-control execution read-model "
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
                "ae_persisted_transition_status": transition_response.status_code,
                "ae_execution_collection_statuses": (
                    bridge.execution_collection_statuses
                ),
                "ae_execution_detail_statuses": bridge.execution_detail_statuses,
                "ag_execution_collection_status": (
                    ag_collection_response.status_code
                ),
                "ag_execution_detail_status": ag_detail_response.status_code,
            },
            "executions": {
                "admitted": ae_execution_pg._execution_evidence(admitted_payload),
            },
            "transition": ae_execution_pg._transition_evidence(transition_payload),
            "db_observations": {
                "before": before,
                "after": after,
            },
            "ag_execution_collection": _collection_evidence(ag_collection),
            "ag_execution_detail": _detail_evidence(ag_detail),
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
                    'SQLite marker for operator-control execution smoke'
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


def _collection_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    items = [item for item in _list_value(payload.get("items")) if isinstance(item, Mapping)]
    first = _mapping_value(items[0]) if items else {}
    return {
        "projection_schema_version": payload.get("projection_schema_version"),
        "projection_status": payload.get("projection_status"),
        "count": payload.get("count"),
        "limit": payload.get("limit"),
        "filter": payload.get("filter"),
        "summary": payload.get("summary"),
        "source_status": payload.get("source_status"),
        "operator_guidance": payload.get("operator_guidance"),
        "first_item": {
            "operator_control_execution_state_id": first.get(
                "operator_control_execution_state_id"
            ),
            "action": first.get("action"),
            "execution_status": first.get("execution_status"),
            "idempotency_status": first.get("idempotency_status"),
            "request_hash_present": bool(
                first.get("operator_control_execution_request_hash")
            ),
            "ag_detail_route": _mapping_value(first.get("routes")).get(
                "ag_detail"
            ),
            "idempotency_key_present": "idempotency_key" in first,
            "raw_request_present": (
                "operator_control_execution_request" in first
            ),
        },
    }


def _detail_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    execution_state = _mapping_value(payload.get("execution_state"))
    transitions = [
        transition
        for transition in _list_value(payload.get("transitions"))
        if isinstance(transition, Mapping)
    ]
    return {
        "projection_schema_version": payload.get("projection_schema_version"),
        "projection_status": payload.get("projection_status"),
        "operator_control_execution_state_id": payload.get(
            "operator_control_execution_state_id"
        ),
        "transition_count": payload.get("transition_count"),
        "summary": payload.get("summary"),
        "source_status": payload.get("source_status"),
        "operator_guidance": payload.get("operator_guidance"),
        "execution_state": {
            "operator_control_execution_state_id": execution_state.get(
                "operator_control_execution_state_id"
            ),
            "action": execution_state.get("action"),
            "execution_mode": execution_state.get("execution_mode"),
            "execution_status": execution_state.get("execution_status"),
            "idempotency_status": execution_state.get("idempotency_status"),
            "idempotency_key_present": "idempotency_key" in execution_state,
            "raw_request_present": (
                "operator_control_execution_request" in execution_state
            ),
        },
        "transition_statuses": [
            f"{transition.get('from_status')}->{transition.get('to_status')}"
            for transition in transitions
        ],
        "transition_raw_state_present": any(
            "operator_control_execution_state" in transition
            for transition in transitions
        ),
    }


def _smoke_checks(
    *,
    database_url: str,
    database_env: str,
    admitted_response: int,
    transition_response: int,
    admitted_payload: Mapping[str, Any],
    transition_payload: Mapping[str, Any],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    bridge: AeTestClientDaemonOperatorControlExecutionReadModelClient,
    ag_collection_status: int,
    ag_collection: Mapping[str, Any],
    ag_detail_status: int,
    ag_detail: Mapping[str, Any],
) -> dict[str, bool]:
    admitted = ae_execution_pg._execution_evidence(admitted_payload)
    transition = ae_execution_pg._transition_evidence(transition_payload)
    collection = _collection_evidence(ag_collection)
    detail = _detail_evidence(ag_detail)
    collection_summary = _mapping_value(collection.get("summary"))
    detail_summary = _mapping_value(detail.get("summary"))
    collection_source = _mapping_value(collection.get("source_status"))
    detail_source = _mapping_value(detail.get("source_status"))
    collection_guidance = _mapping_value(collection.get("operator_guidance"))
    detail_guidance = _mapping_value(detail.get("operator_guidance"))
    return {
        "test_database_url": database_env == "NEX_AE_TEST_DATABASE_URL"
        and ae_execution_pg._database_name(database_url).endswith("_test"),
        "database_health_probe": before.get("health_probe") is True
        and after.get("health_probe") is True,
        "migration_recorded": before.get("migration_recorded") is True
        and after.get("migration_recorded") is True,
        "tables_present": set(before.get("tables_present", [])) == EXPECTED_TABLES
        and set(after.get("tables_present", [])) == EXPECTED_TABLES,
        "indexes_present": set(before.get("indexes_present", [])) == EXPECTED_INDEXES
        and set(after.get("indexes_present", [])) == EXPECTED_INDEXES,
        "postgres_jsonb_columns_verified": after.get("dialect") != "postgresql"
        or after.get("jsonb_columns") == EXPECTED_JSONB_TYPES,
        "persisted_execution_state_route_passed": admitted_response == 200
        and admitted["schema_version"]
        == ae_execution_pg.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_SCHEMA_VERSION
        and admitted["execution_mode"]
        == "fake_dry_run_supervisor_persistent_dispatch"
        and admitted["execution_status"] == "ADMITTED"
        and admitted["idempotency_status"] == "NEW"
        and admitted["allowed_next_statuses"] == ["EXECUTING", "BLOCKED"],
        "persisted_transition_route_passed": transition_response == 200
        and transition["schema_version"]
        == ae_execution_pg.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_TRANSITION_SCHEMA_VERSION
        and transition["from_status"] == "ADMITTED"
        and transition["to_status"] == "EXECUTING"
        and transition["transition_allowed"] is True,
        "scoped_rows_persisted": before.get("scoped_row_counts")
        == {"execution_states": 0, "execution_transitions": 0}
        and after.get("scoped_row_counts")
        == {"execution_states": 1, "execution_transitions": 1},
        "ag_collection_route_ok": ag_collection_status == 200
        and bridge.execution_collection_statuses == [200],
        "ag_detail_route_ok": ag_detail_status == 200
        and bridge.execution_detail_statuses == [200],
        "ag_collection_projection_ready": collection.get(
            "projection_schema_version"
        )
        == AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_PROJECTION_SCHEMA_VERSION
        and collection.get("projection_status") == "READY"
        and collection.get("count") == 1
        and _mapping_value(collection.get("filter")).get("action")
        == "start_daemon"
        and _mapping_value(collection.get("filter")).get("execution_status")
        == "ADMITTED"
        and _mapping_value(collection.get("filter")).get("idempotency_status")
        == "NEW"
        and collection_summary.get("operator_control_execution_state_count")
        == 1
        and collection_summary.get("admitted_count") == 1
        and collection_summary.get("operator_attention_required") is False
        and collection_source.get("source_kind") == "ae_test_client"
        and collection_source.get("execution_collection_loaded") is True
        and collection["first_item"]["execution_status"] == "ADMITTED"
        and collection["first_item"]["idempotency_key_present"] is False
        and collection["first_item"]["raw_request_present"] is False,
        "ag_detail_projection_ready": detail.get("projection_schema_version")
        == AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_DETAIL_PROJECTION_SCHEMA_VERSION
        and detail.get("projection_status") == "READY"
        and detail.get("operator_control_execution_state_id")
        == admitted["state_id"]
        and detail.get("transition_count") == 1
        and detail_summary.get("execution_status") == "ADMITTED"
        and detail_summary.get("transition_statuses") == ["ADMITTED->EXECUTING"]
        and detail_source.get("execution_detail_loaded") is True
        and detail["execution_state"]["raw_request_present"] is False
        and detail["execution_state"]["idempotency_key_present"] is False
        and detail["transition_raw_state_present"] is False,
        "ag_projection_read_only": collection_guidance.get(
            "ag_direct_database_write_allowed"
        )
        is False
        and collection_guidance.get("ag_direct_daemon_process_control_allowed")
        is False
        and detail_guidance.get("ag_direct_job_enqueue_allowed") is False,
        "metadata_only_evidence": _metadata_only(
            admitted,
            transition,
            collection,
            detail,
            forbidden_fragments=[
                database_url,
                ae_execution_pg._database_url_password(database_url),
                "/data/nex-platform",
                "ed6@c496em",
                "slice-0599-admitted-",
                "content_base64",
                '"database_url_included": true',
                '"storage_path_included": true',
                '"raw_artifact_payload_included": true',
                '"raw_execution_payload_included": true',
                '"raw_daemon_runtime_payload_included": true',
                '"raw_supervised_process_snapshot_included": true',
            ],
        ),
    }


def _ag_auth_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=AG_SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _json_payload(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except (AttributeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text_or_none(value: Any) -> str | None:
    text_value = str(value).strip() if value is not None else ""
    return text_value or None


def _metadata_only(*payloads: Any, forbidden_fragments: list[str | None]) -> bool:
    serialized = json.dumps(payloads, ensure_ascii=False, sort_keys=True, default=str)
    return all(
        fragment not in serialized for fragment in forbidden_fragments if fragment
    )


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
        "ag_service_id": AG_SERVICE_ID,
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
    return safe


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    ae_execution_pg.assert_smoke_evidence_redacted(serialized_evidence, environ)
    for forbidden in (
        "slice-0599-admitted-",
        "body-slice-0599-admitted-",
        "DATABASE_URL_SHOULD_NOT_LEAK",
    ):
        if forbidden in serialized_evidence:
            raise ValueError(
                "AE/AG operator-control execution smoke contains private "
                "operator-control request data."
            )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        scoped_rows = evidence["db_observations"]["after"]["scoped_row_counts"]
        return (
            "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke="
            "pass "
            f"service={evidence['service_id']} "
            f"ag_service={evidence['ag_service_id']} "
            f"db_env={evidence['database_env']} "
            f"states={scoped_rows['execution_states']} "
            f"transitions={scoped_rows['execution_transitions']} "
            f"ag_collection={evidence['routes']['ag_execution_collection_status']} "
            f"ag_detail={evidence['routes']['ag_execution_detail_status']} "
            f"cleanup_states={evidence['cleanup']['execution_states']} "
            f"cleanup_transitions={evidence['cleanup']['execution_state_transitions']} "
            f"live_db={str(evidence['live_db']).lower()}"
        )
    return (
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke="
        "fail "
        f"service={evidence.get('service_id')} "
        f"ag_service={evidence.get('ag_service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE/AG scheduler daemon operator-control execution "
            "read-model PostgreSQL smoke."
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
        run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke()
    )
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
