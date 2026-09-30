#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "db",
):
    sys.path.insert(0, str(path))

from nex_mo.provider_readiness_api import register_provider_readiness_routes  # noqa: E402
from nex_mo.provider_readiness_service import ProviderReadinessService  # noqa: E402
from nex_mo.providers import register_mock_provider_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_common_job,
    build_service_app,
    build_service_log_entry,
    build_service_persistence_runtime,
    issue_mock_service_token,
    redact_database_url,
    register_service_job_control_routes,
    register_service_log_retention_routes,
)
from run_migrations import run_service_migrations  # noqa: E402


SCHEMA_VERSION = "mo_contract_api_postgres_smoke.v1"
ACTIVATION_ENV = "NEX_MO_CONTRACT_API_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_MO_CONTRACT_API_POSTGRES_SMOKE_PROFILE"
DATABASE_ENV = "NEX_MO_TEST_DATABASE_URL"
DEFAULT_PROFILE = "test"
EXPECTED_DATABASE = "nex_mo_test"
EXPECTED_ROLE = "nex_mo_user"
SERVICE_ID = "nex-mo"

Exercise = Callable[[str], Mapping[str, Any]]


def run_mo_contract_api_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    exercise: Exercise | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1140",
            "requirement": "S114",
            "status": "SKIPPED",
            "skip_reason": f"{ACTIVATION_ENV} is not enabled.",
        }
    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure("profile_not_allowed", diagnostics={"expected_profile": "test"})
    database_url = str(env.get(DATABASE_ENV) or "").strip()
    if not database_url:
        return _failure(
            "configuration_invalid",
            diagnostics={"missing_env": [DATABASE_ENV]},
        )
    target = _database_target(database_url)
    if target != {
        "backend": "postgresql",
        "database_name": EXPECTED_DATABASE,
        "database_user": EXPECTED_ROLE,
    }:
        return _failure(
            "database_target_not_allowed",
            diagnostics={
                "expected_database": EXPECTED_DATABASE,
                "expected_role": EXPECTED_ROLE,
            },
        )

    try:
        observations = dict((exercise or _exercise_postgres)(database_url))
        cleanup = _mapping(observations.get("cleanup"))
        checks = {
            "actual_test_database_identity": observations.get("database_identity")
            == {"database_name": EXPECTED_DATABASE, "database_user": EXPECTED_ROLE},
            "migrations_current": observations.get("migrations_current") is True,
            "postgres_persistence_active": observations.get("persistence_mode")
            == "postgres",
            "job_insert_select_succeeded": observations.get("job_store_round_trip")
            is True,
            "job_api_read_succeeded": observations.get("job_read_status") == 200,
            "job_api_update_succeeded": observations.get("job_cancel_status") == 200
            and observations.get("job_cancelled_in_database") is True,
            "service_log_insert_select_succeeded": observations.get(
                "service_log_round_trip"
            )
            is True,
            "retention_purge_api_succeeded": observations.get("purge_status") == 200
            and _nonnegative_int(observations.get("candidate_count")) >= 1,
            "retention_history_list_api_succeeded": observations.get(
                "history_list_status"
            )
            == 200
            and observations.get("history_list_contains_execution") is True,
            "retention_history_detail_api_succeeded": observations.get(
                "history_detail_status"
            )
            == 200,
            "unauthorized_route_rejected": observations.get("unauthorized_status")
            == 401,
            "cleanup_complete": cleanup
            == {"service_jobs": 1, "service_log_entries": 1, "retention_history": 1, "residue": 0},
        }
        passed = all(checks.values())
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1140",
            "requirement": "S114",
            "status": "PASS" if passed else "FAIL",
            "failure_code": None if passed else "mo_contract_api_postgres_smoke_failed",
            "service_id": SERVICE_ID,
            "profile": profile,
            "redacted_database_url": redact_database_url(database_url),
            "database_identity": observations.get("database_identity"),
            "migration": _mapping(observations.get("migration")),
            "checks": checks,
            "summary": {
                "passed_check_count": sum(checks.values()),
                "check_count": len(checks),
                "planned_migration_count": _nonnegative_int(
                    _mapping(observations.get("migration")).get("planned_count")
                ),
                "applied_migration_count": _nonnegative_int(
                    _mapping(observations.get("migration")).get("applied_count")
                ),
                "skipped_migration_count": _nonnegative_int(
                    _mapping(observations.get("migration")).get("skipped_count")
                ),
                "database_write_count": 3,
                "api_request_count": 6,
            },
            "cleanup": cleanup,
            "redaction": {
                "status": "PASS",
                "excluded": [
                    "database_password",
                    "authorization_token",
                    "request_payload",
                    "response_payload",
                    "smoke_record_ids",
                ],
            },
            "next_slice": "1141" if passed else "blocked",
        }
        assert_evidence_redacted(evidence, database_url)
        return evidence
    except Exception as exc:
        failure = _failure(
            "postgres_execution_failed",
            diagnostics={"exception_type": exc.__class__.__name__},
        )
        assert_evidence_redacted(failure, database_url)
        return failure


def _exercise_postgres(database_url: str) -> dict[str, Any]:
    migration = run_service_migrations(
        SERVICE_ID,
        database_url=database_url,
        profile="test",
    )
    spec = SERVICE_SPECS[SERVICE_ID]
    runtime = build_service_persistence_runtime(
        service_id=SERVICE_ID,
        database_env=spec.database_env,
        environ={spec.database_env: database_url},
        mode="postgres",
    )
    if runtime.api_engine is None:
        raise RuntimeError("postgres runtime did not create an API engine")
    engine = runtime.api_engine
    suffix = uuid4().hex
    job_id = f"s1140-job-{suffix}"
    log_id = f"s1140-log-{suffix}"
    idempotency_key = f"s1140-retention-{suffix}"
    trace_id = suffix[:32]
    request_id = str(uuid4())
    cleanup_done = False
    try:
        _cleanup_smoke_rows(
            engine,
            job_id=job_id,
            log_id=log_id,
            idempotency_key=idempotency_key,
        )
        with engine.connect() as connection:
            database_name, database_user = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            recorded_migrations = int(
                connection.execute(
                    text("SELECT count(*) FROM schema_migrations")
                ).scalar_one()
            )

        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        job = build_common_job(
            job_id=job_id,
            job_type="mo.contract_api_smoke",
            trace_id=trace_id,
            request_id=request_id,
            subject_ref={"type": "mo.contract", "id": "s1140"},
            idempotency_key=f"s1140-job-{suffix}",
            created_at=now,
            max_attempts=2,
        )
        runtime.job_queue.enqueue(job)
        stored_job = runtime.job_queue.get_job(job_id)
        log = build_service_log_entry(
            service_id=SERVICE_ID,
            severity="info",
            logger_name="nex_mo.contract_api_smoke",
            message="S1140 PostgreSQL contract API smoke probe.",
            trace_id=trace_id,
            request_id=request_id,
            job_id=job_id,
            subject_ref={"type": "mo.contract", "id": "s1140"},
            attributes={"slice": "1140", "payload_recorded": False},
            observed_at="2026-01-01T00:00:00Z",
            log_id=log_id,
        )
        runtime.service_log_store.append(log)
        stored_log = runtime.service_log_store.get_log(log_id)

        app = build_service_app(spec)
        app.state.nex_persistence = runtime
        register_service_job_control_routes(
            app,
            service_id=SERVICE_ID,
            job_queue=runtime.job_queue,
        )
        register_service_log_retention_routes(
            app,
            service_id=SERVICE_ID,
            store=runtime.service_log_store,
        )
        register_mock_provider_routes(app)
        register_provider_readiness_routes(
            app,
            service=ProviderReadinessService(environ={"NEX_MO_PROVIDER_MODE": "mock"}),
        )
        client = TestClient(app)
        headers = _auth_headers(request_id=request_id, trace_id=trace_id)
        unauthorized = client.get(f"/internal/v1/jobs/{job_id}")
        job_read = client.get(f"/internal/v1/jobs/{job_id}", headers=headers)
        job_cancel = client.post(
            f"/internal/v1/jobs/{job_id}/cancel",
            json={"observed_at": now},
            headers=headers,
        )
        cancelled_job = runtime.job_queue.get_job(job_id)
        purge = client.post(
            "/internal/v1/service-logs/retention/purge",
            json={
                "retention_cutoff": "2026-09-01T00:00:00Z",
                "retention_days": 30,
                "checked_at": "2026-09-30T00:00:00Z",
                "dry_run": True,
                "delete_enabled": False,
                "max_delete_count": 10,
                "requested_by": {
                    "actor_type": "service",
                    "actor_id": "s1140-smoke",
                    "service_id": "nex-ag",
                },
                "idempotency_key": idempotency_key,
            },
            headers=headers,
        )
        purge_payload = _json_object(purge.json())
        execution_id = str(purge_payload.get("execution_id") or "")
        history_list = client.get(
            "/internal/v1/service-logs/retention/history",
            params={"idempotency_key": idempotency_key},
            headers=headers,
        )
        history_list_payload = _json_object(history_list.json())
        history_detail = client.get(
            f"/internal/v1/service-logs/retention/history/{execution_id}",
            headers=headers,
        )

        cleanup = _cleanup_smoke_rows(
            engine,
            job_id=job_id,
            log_id=log_id,
            idempotency_key=idempotency_key,
        )
        cleanup_done = True
        planned_count = len(migration.planned)
        return {
            "database_identity": {
                "database_name": database_name,
                "database_user": database_user,
            },
            "migration": {
                "planned_count": planned_count,
                "applied_count": len(migration.applied),
                "skipped_count": len(migration.skipped),
                "recorded_count": recorded_migrations,
                "profile": migration.profile,
            },
            "migrations_current": (
                planned_count == len(migration.applied) + len(migration.skipped)
                and recorded_migrations >= planned_count
                and migration.dry_run is False
            ),
            "persistence_mode": runtime.mode,
            "job_store_round_trip": stored_job is not None
            and stored_job.get("job_id") == job_id,
            "job_read_status": job_read.status_code,
            "job_cancel_status": job_cancel.status_code,
            "job_cancelled_in_database": cancelled_job is not None
            and cancelled_job.get("status") == "CANCELLED",
            "service_log_round_trip": stored_log is not None
            and stored_log.get("log_id") == log_id,
            "purge_status": purge.status_code,
            "candidate_count": _nonnegative_int(purge_payload.get("candidate_count")),
            "history_list_status": history_list.status_code,
            "history_list_contains_execution": any(
                isinstance(item, Mapping) and item.get("execution_id") == execution_id
                for item in history_list_payload.get("items", [])
            ),
            "history_detail_status": history_detail.status_code,
            "unauthorized_status": unauthorized.status_code,
            "cleanup": cleanup,
        }
    finally:
        if not cleanup_done:
            _cleanup_smoke_rows(
                engine,
                job_id=job_id,
                log_id=log_id,
                idempotency_key=idempotency_key,
            )
        if runtime.api_engine is not None:
            runtime.api_engine.dispose()
        if runtime.worker_engine is not None:
            runtime.worker_engine.dispose()


def _cleanup_smoke_rows(
    engine: Any,
    *,
    job_id: str,
    log_id: str,
    idempotency_key: str,
) -> dict[str, int]:
    with engine.begin() as connection:
        history = connection.execute(
            text(
                "DELETE FROM service_log_retention_history "
                "WHERE idempotency_key = :idempotency_key"
            ),
            {"idempotency_key": idempotency_key},
        ).rowcount
        logs = connection.execute(
            text("DELETE FROM service_log_entries WHERE log_id = :log_id"),
            {"log_id": log_id},
        ).rowcount
        jobs = connection.execute(
            text("DELETE FROM service_jobs WHERE job_id = :job_id"),
            {"job_id": job_id},
        ).rowcount
        residue = int(
            connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM service_jobs WHERE job_id = :job_id) + "
                    "(SELECT count(*) FROM service_log_entries WHERE log_id = :log_id) + "
                    "(SELECT count(*) FROM service_log_retention_history "
                    " WHERE idempotency_key = :idempotency_key)"
                ),
                {
                    "job_id": job_id,
                    "log_id": log_id,
                    "idempotency_key": idempotency_key,
                },
            ).scalar_one()
        )
    return {
        "service_jobs": int(jobs or 0),
        "service_log_entries": int(logs or 0),
        "retention_history": int(history or 0),
        "residue": residue,
    }


def _auth_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-ag", audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-{trace_id[:16]}-01",
    }


def _database_target(database_url: str) -> dict[str, str | None]:
    try:
        parsed = make_url(database_url)
    except Exception:
        return {"backend": None, "database_name": None, "database_user": None}
    return {
        "backend": parsed.get_backend_name(),
        "database_name": parsed.database,
        "database_user": parsed.username,
    }


def _json_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("response_not_json_object")
    return dict(value)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _nonnegative_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _failure(
    failure_code: str,
    *,
    diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1140",
        "requirement": "S114",
        "status": "FAIL",
        "failure_code": failure_code,
        "issues": [failure_code],
        "next_slice": "blocked",
    }
    if diagnostics:
        evidence["diagnostics"] = dict(diagnostics)
    return evidence


def assert_evidence_redacted(evidence: Mapping[str, Any], database_url: str) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    protected = [database_url]
    try:
        protected.append(str(make_url(database_url).password or ""))
    except Exception:
        pass
    if any(value and len(value) >= 6 and value in serialized for value in protected):
        raise ValueError("MO contract API PostgreSQL evidence contains protected value")


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    cleanup = _mapping(evidence.get("cleanup"))
    return (
        "mo_contract_api_postgres_smoke="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"migrations={summary.get('applied_migration_count', 0)}+"
        f"{summary.get('skipped_migration_count', 0)}/"
        f"{summary.get('planned_migration_count', 0)} "
        f"writes={summary.get('database_write_count', 0)} "
        f"cleanup={cleanup.get('residue', 'not-run')} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_contract_api_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
