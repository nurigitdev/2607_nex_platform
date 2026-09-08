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
import run_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke as process_pg  # noqa: E402
import run_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke as supervisor_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifact_retention_scheduler_daemon import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_TRANSITION_SCHEMA_VERSION,
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
    "ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_POSTGRES_SMOKE"
)
SMOKE_PROFILE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
CHECKED_AT = "2026-09-08T07:25:00Z"
REQUESTED_AT = "2026-09-08T07:24:55Z"
REPLAYED_AT = "2026-09-08T07:25:20Z"
TRANSITIONED_AT = "2026-09-08T07:25:35Z"
EXPECTED_TABLES = process_pg.EXPECTED_TABLES | supervisor_pg.EXPECTED_TABLES
EXPECTED_INDEXES = process_pg.EXPECTED_INDEXES | supervisor_pg.EXPECTED_INDEXES


def run_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke(
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
            f"{SMOKE_PROFILE_ENV} must be test for PostgreSQL smoke execution.",
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
        execution = _execute_operator_control_execution_route_smoke(
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


def _execute_operator_control_execution_route_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        process_pg._ensure_sqlite_migration_marker(engine)
        supervisor_pg._ensure_sqlite_migration_marker(engine)
        process_store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore(
            session_factory
        )
        supervisor_store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisorStore(
            session_factory
        )
        process_store.ensure_schema()
        supervisor_store.ensure_schema()
        before = _db_observations(engine)

        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        app.state.nex_persistence = SimpleNamespace(
            api_session_factory=session_factory
        )
        register_artifact_handoff_routes(app)
        client = TestClient(app)
        headers = artifact_pg._auth_headers(request_id=request_id, trace_id=trace_id)

        contract_response = client.post(
            "/api/v1/artifact-retention/scheduler-daemon-operator-control-executions",
            json=_execution_payload(
                suffix=suffix,
                reason="slice_0595_postgresql_contract_only_execution",
            ),
            headers={
                **headers,
                "Idempotency-Key": f"slice-0595-contract-{suffix}",
            },
        )
        contract_payload = _json_payload(contract_response)
        admitted_response = client.post(
            "/api/v1/artifact-retention/scheduler-daemon-operator-control-executions",
            json=_execution_payload(
                suffix=suffix,
                reason="slice_0595_postgresql_fake_dispatch_admission",
                execution_mode="fake_dry_run_supervisor_persistent_dispatch",
            ),
            headers={
                **headers,
                "Idempotency-Key": f"slice-0595-admitted-{suffix}",
            },
        )
        admitted_payload = _json_payload(admitted_response)
        replay_response = client.post(
            "/api/v1/artifact-retention/scheduler-daemon-operator-control-executions",
            json={
                **_execution_payload(
                    suffix=suffix,
                    reason="slice_0595_postgresql_fake_dispatch_admission",
                    execution_mode="fake_dry_run_supervisor_persistent_dispatch",
                ),
                "existing_execution_state": admitted_payload,
                "observed_at": REPLAYED_AT,
            },
            headers={
                **headers,
                "Idempotency-Key": f"slice-0595-admitted-{suffix}",
            },
        )
        replay_payload = _json_payload(replay_response)
        transition_response = client.post(
            "/api/v1/artifact-retention/"
            "scheduler-daemon-operator-control-execution-transitions",
            json={
                "operator_control_execution_state": admitted_payload,
                "target_status": "EXECUTING",
                "decision_reason": "slice_0595_transition_to_executing",
                "transitioned_at": TRANSITIONED_AT,
            },
            headers=headers,
        )
        transition_payload = _json_payload(transition_response)
        after = _db_observations(engine)

        checks = _smoke_checks(
            database_url=database_url,
            database_env=database_env,
            contract_response=contract_response.status_code,
            admitted_response=admitted_response.status_code,
            replay_response=replay_response.status_code,
            transition_response=transition_response.status_code,
            contract_payload=contract_payload,
            admitted_payload=admitted_payload,
            replay_payload=replay_payload,
            transition_payload=transition_payload,
            before=before,
            after=after,
        )
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "AE scheduler daemon operator-control execution PostgreSQL "
                f"smoke checks failed: {', '.join(failed_checks)}"
            )

        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "routes": {
                "contract_only_execution_status": contract_response.status_code,
                "fake_dispatch_admission_status": admitted_response.status_code,
                "idempotency_replay_status": replay_response.status_code,
                "transition_status": transition_response.status_code,
            },
            "executions": {
                "contract_only": _execution_evidence(contract_payload),
                "admitted": _execution_evidence(admitted_payload),
                "replayed": _execution_evidence(replay_payload),
            },
            "transition": _transition_evidence(transition_payload),
            "db_observations": {
                "before": before,
                "after": after,
            },
            "checks": checks,
            "live_db": True,
        }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        engine.dispose()


def _execution_payload(
    *,
    suffix: str,
    reason: str,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": "start_daemon",
        "profile": DEFAULT_PROFILE,
        "enabled": True,
        "explicit_opt_in": True,
        "checked_at": CHECKED_AT,
        "requested_at": REQUESTED_AT,
        "observed_at": CHECKED_AT,
        "requested_by": {
            "actor_type": "operator",
            "actor_id": f"ae-operator-execution-postgres-smoke-{suffix}",
            "tenant_id": f"tenant-0595-{suffix}",
            "workspace_id": f"workspace-0595-{suffix}",
            "service_id": "nex-ag",
        },
        "reason": reason,
        "max_cycles": "2",
        "run_worker": True,
        "supervisor_mode": "fake_dry_run",
        "output_format": "json",
        "approval": {
            "approved": True,
            "approved_by": {
                "actor_type": "operator",
                "actor_id": f"ae-operator-execution-postgres-smoke-{suffix}",
                "tenant_id": f"tenant-0595-{suffix}",
                "workspace_id": f"workspace-0595-{suffix}",
                "service_id": "nex-ag",
            },
            "approved_at": REQUESTED_AT,
            "reason": reason,
        },
    }
    if execution_mode is not None:
        payload["execution_mode"] = execution_mode
    return payload


def _json_payload(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _mapping_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _execution_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    guardrails = _mapping_value(payload.get("guardrails"))
    metadata = _mapping_value(payload.get("metadata"))
    return {
        "schema_version": payload.get(
            "operator_control_execution_state_schema_version"
        ),
        "state_id": payload.get("operator_control_execution_state_id"),
        "request_id": payload.get("operator_control_execution_request_id"),
        "action": payload.get("action"),
        "execution_mode": payload.get("execution_mode"),
        "execution_status": payload.get("execution_status"),
        "idempotency_status": payload.get("idempotency_status"),
        "decision_reason": payload.get("decision_reason"),
        "allowed_next_statuses": list(payload.get("allowed_next_statuses", [])),
        "metadata_only": guardrails.get("metadata_only"),
        "state_machine_only": guardrails.get("state_machine_only"),
        "supervisor_adapter_invoked": guardrails.get("supervisor_adapter_invoked"),
        "database_write_performed": metadata.get("database_write_performed"),
        "job_queue_enqueue_performed": metadata.get("job_queue_enqueue_performed"),
        "worker_execution_performed": metadata.get("worker_execution_performed"),
        "safe_for_ag_projection": metadata.get("safe_for_ag_projection"),
        "prior_execution_state_id": payload.get("prior_execution_state_id"),
    }


def _transition_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    guardrails = _mapping_value(payload.get("guardrails"))
    metadata = _mapping_value(payload.get("metadata"))
    return {
        "schema_version": payload.get(
            "operator_control_execution_state_transition_schema_version"
        ),
        "transition_id": payload.get(
            "operator_control_execution_state_transition_id"
        ),
        "state_id": payload.get("operator_control_execution_state_id"),
        "from_status": payload.get("from_status"),
        "to_status": payload.get("to_status"),
        "decision_reason": payload.get("decision_reason"),
        "metadata_only": guardrails.get("metadata_only"),
        "state_transition_only": guardrails.get("state_transition_only"),
        "transition_allowed": guardrails.get("transition_allowed"),
        "database_write_performed": metadata.get("database_write_performed"),
        "safe_for_ag_projection": metadata.get("safe_for_ag_projection"),
    }


def _db_observations(engine: Any) -> dict[str, Any]:
    with engine.connect() as connection:
        dialect_name = connection.dialect.name
        health_probe = connection.execute(text("SELECT 1")).scalar() == 1
        tables_present = sorted(
            table_name
            for table_name in EXPECTED_TABLES
            if _table_exists(connection, table_name)
        )
        row_counts = {
            "process_records": _table_count(
                connection,
                "ae_artifact_retention_scheduler_daemon_process_snapshots",
            ),
            "process_events": _table_count(
                connection,
                "ae_artifact_retention_scheduler_daemon_process_events",
            ),
            "supervisor_records": _table_count(
                connection,
                "ae_artifact_retention_scheduler_daemon_supervisor_results",
            ),
            "supervisor_events": _table_count(
                connection,
                "ae_artifact_retention_scheduler_daemon_supervisor_events",
            ),
        }
        migration_recorded = process_pg._schema_migration_recorded(
            connection
        ) and supervisor_pg._schema_migration_recorded(connection)
        indexes_present = sorted(
            set(process_pg._indexes_present(connection, dialect_name))
            | set(supervisor_pg._indexes_present(connection, dialect_name))
        )
    return {
        "dialect": dialect_name,
        "health_probe": health_probe,
        "tables_present": tables_present,
        "indexes_present": indexes_present,
        "migration_recorded": migration_recorded,
        "row_counts": row_counts,
    }


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


def _table_count(connection: Any, table_name: str) -> int:
    if not _table_exists(connection, table_name):
        return 0
    return int(
        connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar() or 0
    )


def _smoke_checks(
    *,
    database_url: str,
    database_env: str,
    contract_response: int,
    admitted_response: int,
    replay_response: int,
    transition_response: int,
    contract_payload: Mapping[str, Any],
    admitted_payload: Mapping[str, Any],
    replay_payload: Mapping[str, Any],
    transition_payload: Mapping[str, Any],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, bool]:
    contract_evidence = _execution_evidence(contract_payload)
    admitted_evidence = _execution_evidence(admitted_payload)
    replay_evidence = _execution_evidence(replay_payload)
    transition_evidence = _transition_evidence(transition_payload)
    return {
        "test_database_url": database_env == "NEX_AE_TEST_DATABASE_URL"
        and _database_name(database_url).endswith("_test"),
        "database_health_probe": before.get("health_probe") is True
        and after.get("health_probe") is True,
        "migration_recorded": before.get("migration_recorded") is True
        and after.get("migration_recorded") is True,
        "tables_present": set(before.get("tables_present", [])) == EXPECTED_TABLES
        and set(after.get("tables_present", [])) == EXPECTED_TABLES,
        "indexes_present": set(before.get("indexes_present", [])) == EXPECTED_INDEXES
        and set(after.get("indexes_present", [])) == EXPECTED_INDEXES,
        "contract_only_execution_route_passed": contract_response == 200
        and contract_evidence["schema_version"]
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_SCHEMA_VERSION
        and contract_evidence["execution_mode"] == "contract_only"
        and contract_evidence["execution_status"] == "BLOCKED"
        and contract_evidence["idempotency_status"] == "NEW"
        and contract_evidence["decision_reason"] == "execution_contract_only",
        "fake_dispatch_admission_route_passed": admitted_response == 200
        and admitted_evidence["schema_version"]
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_SCHEMA_VERSION
        and admitted_evidence["execution_mode"]
        == "fake_dry_run_supervisor_persistent_dispatch"
        and admitted_evidence["execution_status"] == "ADMITTED"
        and admitted_evidence["idempotency_status"] == "NEW"
        and admitted_evidence["allowed_next_statuses"] == ["EXECUTING", "BLOCKED"],
        "idempotency_replay_route_passed": replay_response == 200
        and replay_evidence["execution_status"] == "BLOCKED"
        and replay_evidence["idempotency_status"] == "REPLAYED"
        and replay_evidence["prior_execution_state_id"]
        == admitted_evidence["state_id"],
        "transition_route_passed": transition_response == 200
        and transition_evidence["schema_version"]
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_TRANSITION_SCHEMA_VERSION
        and transition_evidence["from_status"] == "ADMITTED"
        and transition_evidence["to_status"] == "EXECUTING"
        and transition_evidence["transition_allowed"] is True,
        "metadata_only_guardrails": all(
            item["metadata_only"] is True
            and item["safe_for_ag_projection"] is True
            and item["database_write_performed"] is False
            for item in (
                contract_evidence,
                admitted_evidence,
                replay_evidence,
                transition_evidence,
            )
        )
        and contract_evidence["state_machine_only"] is True
        and admitted_evidence["supervisor_adapter_invoked"] is False
        and admitted_evidence["job_queue_enqueue_performed"] is False
        and admitted_evidence["worker_execution_performed"] is False
        and transition_evidence["state_transition_only"] is True,
        "execution_route_kept_rows_unchanged": before.get("row_counts")
        == after.get("row_counts"),
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
    database_url = environ.get(
        service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE)
    )
    password = _database_url_password(database_url)
    if password and password in serialized_evidence:
        raise ValueError(
            "AE operator-control execution smoke contains a database password."
        )
    if "ed6@c496em" in serialized_evidence:
        raise ValueError(
            "AE operator-control execution smoke contains a provider API key."
        )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke="
            f"pass service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            "routes=4 "
            "metadata_only=true "
            f"unchanged={str(evidence['checks']['execution_route_kept_rows_unchanged']).lower()} "
            f"live_db={str(evidence['live_db']).lower()}"
        )
    return (
        "ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke="
        f"fail service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE scheduler daemon operator-control execution "
            "PostgreSQL smoke."
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
        run_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke()
    )
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
