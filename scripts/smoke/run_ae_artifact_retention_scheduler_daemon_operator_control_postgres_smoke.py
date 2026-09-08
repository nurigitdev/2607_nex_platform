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
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifact_retention_scheduler_daemon import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_FACADE_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POLICY_SCHEMA_VERSION,
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
    "ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POSTGRES_SMOKE"
)
SMOKE_PROFILE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
MIGRATION_VERSION = process_pg.MIGRATION_VERSION
CHECKED_AT = "2026-09-08T07:15:00Z"
REQUESTED_AT = "2026-09-08T07:14:55Z"
EXPECTED_TABLES = process_pg.EXPECTED_TABLES
EXPECTED_INDEXES = process_pg.EXPECTED_INDEXES


def run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke(
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
        execution = _execute_operator_control_facade_smoke(
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


def _execute_operator_control_facade_smoke(
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
        supervised_process_store = (
            SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore(
                session_factory
            )
        )
        supervised_process_store.ensure_schema()
        before = _db_observations(engine)

        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        app.state.nex_persistence = SimpleNamespace(
            api_session_factory=session_factory
        )
        register_artifact_handoff_routes(app)
        client = TestClient(app)
        headers = artifact_pg._auth_headers(request_id=request_id, trace_id=trace_id)

        policy_response = client.get(
            "/api/v1/artifact-retention/scheduler-daemon-operator-control-policy",
            params={"checked_at": CHECKED_AT},
            headers=headers,
        )
        status_response = client.post(
            "/api/v1/artifact-retention/scheduler-daemon-operator-control-preview",
            json={
                "action": "status_probe",
                "requested_by": _operator_subject(suffix),
                "reason": "slice_0586_postgresql_status_preview",
                "requested_at": REQUESTED_AT,
                "checked_at": CHECKED_AT,
            },
            headers={
                **headers,
                "Idempotency-Key": f"slice-0586-status-{suffix}",
            },
        )
        start_response = client.post(
            "/api/v1/artifact-retention/scheduler-daemon-operator-control-preview",
            json={
                "action": "start_daemon",
                "requested_by": _operator_subject(suffix),
                "reason": "slice_0586_postgresql_start_preview",
                "requested_at": REQUESTED_AT,
                "checked_at": CHECKED_AT,
                "enabled": True,
                "explicit_opt_in": True,
                "max_cycles": "2",
                "run_worker": True,
                "approval": {
                    "approved": True,
                    "approved_by": _operator_subject(suffix),
                    "approved_at": REQUESTED_AT,
                    "reason": "slice_0586_postgresql_start_preview",
                },
            },
            headers={
                **headers,
                "Idempotency-Key": f"slice-0586-start-{suffix}",
            },
        )
        after = _db_observations(engine)

        policy_payload = _json_payload(policy_response)
        status_payload = _json_payload(status_response)
        start_payload = _json_payload(start_response)
        checks = _smoke_checks(
            database_url=database_url,
            database_env=database_env,
            policy_response=policy_response.status_code,
            status_response=status_response.status_code,
            start_response=start_response.status_code,
            policy_payload=policy_payload,
            status_payload=status_payload,
            start_payload=start_payload,
            before=before,
            after=after,
        )
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "AE scheduler daemon operator-control PostgreSQL smoke checks "
                f"failed: {', '.join(failed_checks)}"
            )

        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "routes": {
                "policy_status": policy_response.status_code,
                "status_preview_status": status_response.status_code,
                "start_preview_status": start_response.status_code,
            },
            "policy": _policy_evidence(policy_payload),
            "previews": {
                "status_probe": _preview_evidence(status_payload),
                "start_daemon": _preview_evidence(start_payload),
            },
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


def _operator_subject(suffix: str) -> dict[str, str]:
    return {
        "actor_type": "operator",
        "actor_id": f"ag-retention-operator-{suffix}",
        "tenant_id": f"tenant-0586-{suffix}",
        "workspace_id": f"workspace-0586-{suffix}",
        "service_id": "nex-ag",
    }


def _json_payload(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _mapping_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _policy_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    guardrails = _mapping_value(payload.get("guardrails"))
    return {
        "schema_version": payload.get("operator_control_policy_schema_version"),
        "scheduler_id": payload.get("scheduler_id"),
        "checked_at": payload.get("checked_at"),
        "supported_actions": [
            action.get("action")
            for action in payload.get("supported_actions", [])
            if isinstance(action, Mapping)
        ],
        "ag_direct_process_control_allowed": guardrails.get(
            "ag_direct_process_control_allowed"
        ),
        "test_profile_required": guardrails.get("test_profile_required"),
    }


def _preview_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    request = _mapping_value(payload.get("operator_control_request"))
    admission = _mapping_value(payload.get("operator_control_admission"))
    preview = _mapping_value(payload.get("operator_control_command_preview"))
    guardrails = _mapping_value(payload.get("guardrails"))
    metadata = _mapping_value(payload.get("metadata"))
    return {
        "schema_version": payload.get("operator_control_facade_schema_version"),
        "action": payload.get("action"),
        "facade_status": payload.get("facade_status"),
        "request_id": request.get("operator_control_request_id"),
        "admission_id": admission.get("operator_control_admission_id"),
        "command_preview_id": preview.get("operator_control_command_preview_id"),
        "command_preview_count": metadata.get("command_preview_count"),
        "supervisor_actions": list(metadata.get("supervisor_actions", [])),
        "preview_only": guardrails.get("preview_only"),
        "process_control_allowed": guardrails.get("process_control_allowed"),
        "supervisor_adapter_invoked": guardrails.get("supervisor_adapter_invoked"),
        "database_write_performed": metadata.get("database_write_performed"),
        "job_queue_enqueue_performed": metadata.get("job_queue_enqueue_performed"),
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
        }
        migration_recorded = process_pg._schema_migration_recorded(connection)
        indexes_present = process_pg._indexes_present(connection, dialect_name)
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
    policy_response: int,
    status_response: int,
    start_response: int,
    policy_payload: Mapping[str, Any],
    status_payload: Mapping[str, Any],
    start_payload: Mapping[str, Any],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, bool]:
    status_preview = _preview_evidence(status_payload)
    start_preview = _preview_evidence(start_payload)
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
        "operator_control_policy_route_passed": policy_response == 200
        and policy_payload.get("operator_control_policy_schema_version")
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POLICY_SCHEMA_VERSION
        and policy_payload.get("checked_at") == CHECKED_AT
        and _mapping_value(policy_payload.get("guardrails")).get(
            "ag_direct_process_control_allowed"
        )
        is False,
        "status_preview_route_passed": status_response == 200
        and status_preview["schema_version"]
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_FACADE_SCHEMA_VERSION
        and status_preview["action"] == "status_probe"
        and status_preview["facade_status"] == "READY"
        and status_preview["supervisor_actions"] == ["status_probe"],
        "start_preview_route_passed": start_response == 200
        and start_preview["schema_version"]
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_FACADE_SCHEMA_VERSION
        and start_preview["action"] == "start_daemon"
        and start_preview["facade_status"] == "READY"
        and start_preview["supervisor_actions"] == ["start_daemon"],
        "preview_only_guardrails": status_preview["preview_only"] is True
        and start_preview["preview_only"] is True
        and status_preview["process_control_allowed"] is False
        and start_preview["process_control_allowed"] is False
        and status_preview["supervisor_adapter_invoked"] is False
        and start_preview["supervisor_adapter_invoked"] is False,
        "no_database_write_or_job_enqueue": status_preview[
            "database_write_performed"
        ]
        is False
        and start_preview["database_write_performed"] is False
        and status_preview["job_queue_enqueue_performed"] is False
        and start_preview["job_queue_enqueue_performed"] is False,
        "preview_route_kept_rows_unchanged": before.get("row_counts")
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
            "AE scheduler daemon operator-control smoke contains a database password."
        )
    if "ed6@c496em" in serialized_evidence:
        raise ValueError(
            "AE scheduler daemon operator-control smoke contains a provider API key."
        )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke="
            f"pass service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            "routes=3 "
            "preview_only=true "
            f"unchanged={str(evidence['checks']['preview_route_kept_rows_unchanged']).lower()} "
            f"live_db={str(evidence['live_db']).lower()}"
        )
    return (
        "ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke="
        f"fail service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE scheduler daemon operator-control facade PostgreSQL "
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
        run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke()
    )
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, default=str)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
