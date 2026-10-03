#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services/_shared",
    ROOT / "services/nex-oa",
    ROOT / "scripts/db",
):
    sys.path.insert(0, str(path))

from nex_oa.auth_events import (  # noqa: E402
    OA_CREDENTIAL_SECURITY_READ_SCOPE,
    build_auth_event_repository_for_runtime,
    register_auth_event_routes,
)
from nex_oa.credential_security import (  # noqa: E402
    OA_CREDENTIAL_SECURITY_WRITE_SCOPE,
    build_credential_security_repository_for_runtime,
    register_credential_security_routes,
)
from nex_oa.credential_security_postgres_smoke import (  # noqa: E402
    EXPECTED_DATABASE,
    EXPECTED_ROLE,
    evaluate_credential_security_postgres_smoke,
)
from nex_oa.credentials import (  # noqa: E402
    build_credential_registry_for_runtime,
    hash_password,
    register_local_credential_routes,
)
from nex_oa.memberships import (  # noqa: E402
    build_tenant_membership_registry_for_runtime,
    register_identity_membership_routes,
)
from nex_oa.sessions import (  # noqa: E402
    build_oa_session_registry_for_runtime,
    register_user_session_routes,
)
from nex_oa.subjects import (  # noqa: E402
    OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE,
    build_subject_registry_for_runtime,
    register_subject_registry_routes,
)
from nex_oa.user_login import OaUserLoginService, register_user_login_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SMOKE_ENV = "NEX_OA_CREDENTIAL_SECURITY_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
SCHEMA_VERSION = "oa_credential_security_postgres_smoke.v1"
SERVICE_ID = "nex-oa"
PROFILE = "test"
INITIAL_PASSWORD = "Smoke-Initial-123!"
TEMPORARY_PASSWORD = "Smoke-Temporary-456!"
NEXT_PASSWORD = "Smoke-Next-789!"
FINAL_PASSWORD = "Smoke-Final-987!"


def run_oa_credential_security_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    database_url = env.get(DATABASE_ENV, "")
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    if not _target_url_allowed(database_url):
        return _failure(
            "target_not_allowed",
            f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
        )

    try:
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=PROFILE,
        )
        workflow = _execute_credential_security_postgres_smoke(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPECS[SERVICE_ID].database_env: database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            },
        )
        evidence = evaluate_credential_security_postgres_smoke(
            {
                "planned": migration.planned,
                "applied": migration.applied,
                "skipped": migration.skipped,
            },
            workflow,
        )
        evidence.update(
            smoke_schema_version=SCHEMA_VERSION,
            slice="1230",
            requirement="S123",
            service_id=SERVICE_ID,
            profile=PROFILE,
            database_env=DATABASE_ENV,
            redacted_database_url=redact_database_url(database_url),
            migration={
                "planned_count": len(migration.planned),
                "applied": list(migration.applied),
                "skipped_count": len(migration.skipped),
            },
        )
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", exc.__class__.__name__)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__)


def _execute_credential_security_postgres_smoke(
    *, database_url: str, runtime_environ: Mapping[str, str]
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    tenant_id = f"tenant-oa-security-{suffix}"
    subject_id = f"subject-oa-security-{suffix}"
    employee_id = f"EMP-OA-SECURITY-{suffix}"
    session_ids: list[str] = []
    result: dict[str, Any] = {}

    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    persistence = attach_service_persistence_runtime(
        app,
        SERVICE_SPECS[SERVICE_ID],
        environ=runtime_environ,
    )
    if persistence.api_session_factory is None or persistence.api_engine is None:
        raise RuntimeError("OA credential security PostgreSQL runtime is unavailable")
    subjects = build_subject_registry_for_runtime(persistence)
    memberships = build_tenant_membership_registry_for_runtime(
        persistence, subject_registry=subjects
    )
    credentials = build_credential_registry_for_runtime(
        persistence, subject_registry=subjects
    )
    sessions = build_oa_session_registry_for_runtime(
        persistence, membership_registry=memberships
    )
    auth_events = build_auth_event_repository_for_runtime(persistence)
    security = build_credential_security_repository_for_runtime(
        persistence,
        credential_registry=credentials,
        session_registry=sessions,
    )
    login = OaUserLoginService(credentials, sessions)
    register_subject_registry_routes(app, registry=subjects)
    register_local_credential_routes(app, registry=credentials)
    register_identity_membership_routes(app, registry=memberships)
    register_user_session_routes(
        app, registry=sessions, auth_event_repository=auth_events
    )
    register_user_login_routes(app, service=login, auth_event_repository=auth_events)
    register_credential_security_routes(
        app, repository=security, auth_event_repository=auth_events
    )
    register_auth_event_routes(app, repository=auth_events)
    client = TestClient(app)
    engine = persistence.api_engine

    try:
        headers = _service_headers()
        credential = client.post(
            "/internal/v1/auth/local-credentials/ensure",
            headers=headers,
            json={
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "employee_id": employee_id,
                "tenant_display_name": "OA Security Smoke Tenant",
                "subject_display_name": "OA Security Smoke User",
                "password_hash": hash_password(
                    INITIAL_PASSWORD, salt=b"oa-security-smk", iterations=10_000
                ),
            },
        )
        credential.raise_for_status()
        membership = client.post(
            "/internal/v1/identity/memberships/ensure",
            headers=headers,
            json={
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "roles": ["employee"],
                "scopes": ["workspace:use"],
            },
        )
        membership.raise_for_status()

        failed_logins = [
            client.post(
                "/internal/v1/auth/user-login",
                headers=headers,
                json=_login_payload(
                    tenant_id, employee_id, f"Wrong-Password-{attempt}!"
                ),
            )
            for attempt in range(5)
        ]
        locked = _credential_observation(engine, tenant_id=tenant_id)
        _expire_lockout(engine, tenant_id=tenant_id)

        first_login = client.post(
            "/internal/v1/auth/user-login",
            headers=headers,
            json=_login_payload(tenant_id, employee_id, INITIAL_PASSWORD),
        )
        first_login.raise_for_status()
        first_session_id = str(first_login.json()["session"]["session_id"])
        session_ids.append(first_session_id)
        before_touch = _session_last_seen(engine, session_id=first_session_id)
        time.sleep(0.01)
        first_introspection = client.post(
            "/internal/v1/auth/user-sessions/introspect",
            headers=headers,
            json={"session_id": first_session_id},
        )
        first_introspection.raise_for_status()
        after_touch = _session_last_seen(engine, session_id=first_session_id)

        reset = client.post(
            "/internal/v1/auth/local-credentials/reset-password",
            headers=headers,
            json={
                "tenant_id": tenant_id,
                "employee_id": employee_id,
                "temporary_password": TEMPORARY_PASSWORD,
                "reason_code": "smoke.operator-reset",
            },
        )
        reset.raise_for_status()
        first_change = client.post(
            "/internal/v1/auth/local-credentials/change-password",
            headers=headers,
            json={
                "tenant_id": tenant_id,
                "employee_id": employee_id,
                "current_password": TEMPORARY_PASSWORD,
                "new_password": NEXT_PASSWORD,
            },
        )
        first_change.raise_for_status()
        second_login = client.post(
            "/internal/v1/auth/user-login",
            headers=headers,
            json=_login_payload(tenant_id, employee_id, NEXT_PASSWORD),
        )
        second_login.raise_for_status()
        second_session_id = str(second_login.json()["session"]["session_id"])
        session_ids.append(second_session_id)
        second_change = client.post(
            "/internal/v1/auth/local-credentials/change-password",
            headers=headers,
            json={
                "tenant_id": tenant_id,
                "employee_id": employee_id,
                "current_password": NEXT_PASSWORD,
                "new_password": FINAL_PASSWORD,
            },
        )
        second_change.raise_for_status()
        revoked_introspection = client.post(
            "/internal/v1/auth/user-sessions/introspect",
            headers=headers,
            json={"session_id": second_session_id},
        )
        revoked_introspection.raise_for_status()
        event_list = client.get(
            "/internal/v1/auth/security-events",
            headers=headers,
            params={"tenant_id": tenant_id, "limit": 100},
        )
        event_list.raise_for_status()
        events = event_list.json()["events"]
        observations = _db_observations(
            engine,
            tenant_id=tenant_id,
            subject_id=subject_id,
            session_ids=tuple(session_ids),
        )
        checks = {
            "credential_seeded": credential.status_code == 200,
            "membership_seeded": membership.status_code == 200,
            "five_failures_are_private": all(
                response.status_code == 401
                and response.json().get("error_code") == "oa.credential_not_verified"
                for response in failed_logins
            ),
            "fifth_failure_locked_atomically": (
                locked["status"] == "LOCKED"
                and locked["failed_attempt_count"] == 5
                and locked["locked_at"] is not None
            ),
            "expired_lock_recovered": first_login.status_code == 200,
            "legacy_hash_rehashed": (
                observations["password_hash_algorithm"] == "argon2id.v1"
            ),
            "session_ids_are_random_and_distinct": (
                len(session_ids) == 2
                and session_ids[0] != session_ids[1]
                and all(len(value) >= 32 for value in session_ids)
            ),
            "session_idle_lease_touched": after_touch > before_touch,
            "reset_revoked_first_session": (
                reset.json()["credential_status"] == "PASSWORD_RESET_REQUIRED"
                and reset.json()["revoked_session_count"] == 1
            ),
            "temporary_password_rotated": (
                first_change.json()["credential_status"] == "ACTIVE"
            ),
            "change_revoked_second_session": (
                second_change.json()["revoked_session_count"] == 1
            ),
            "revoked_session_is_inactive": (
                revoked_introspection.json()["active"] is False
                and revoked_introspection.json()["inactive_reason"] == "revoked"
            ),
            "event_read_model_matches_database": (
                len(events) == sum(observations["event_counts"].values()) == 12
            ),
            "event_projection_is_private": _events_are_private(events),
        }
        result = {
            "database": observations.pop("database"),
            "role": observations.pop("role"),
            "runtime_mode": persistence.mode,
            "checks": checks,
            "db_observations": observations,
        }
    finally:
        cleanup = _delete_smoke_rows(engine, tenant_id=tenant_id)
        residue = _cleanup_residue(engine, tenant_id=tenant_id)
        _dispose_runtime(persistence)

    result["cleanup"] = cleanup
    result["cleanup_residue"] = residue
    return result


def _login_payload(tenant_id: str, employee_id: str, password: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "employee_id": employee_id,
        "password": password,
        "requested_scopes": ["workspace:use"],
        "ttl_seconds": 1800,
    }


def _credential_observation(engine: Any, *, tenant_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status, failed_attempt_count, locked_at "
                "FROM oa_local_credentials WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).mappings().one()
    return dict(row)


def _expire_lockout(engine: Any, *, tenant_id: str) -> None:
    expired = datetime.now(UTC) - timedelta(minutes=16)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE oa_local_credentials SET locked_at = :expired, "
                "updated_at = :expired WHERE tenant_id = :tenant_id"
            ),
            {"expired": expired, "tenant_id": tenant_id},
        )


def _session_last_seen(engine: Any, *, session_id: str) -> datetime:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT last_seen_at FROM oa_user_sessions "
                "WHERE session_id = :session_id"
            ),
            {"session_id": session_id},
        ).scalar_one()


def _db_observations(
    engine: Any,
    *,
    tenant_id: str,
    subject_id: str,
    session_ids: tuple[str, ...],
) -> dict[str, Any]:
    with engine.connect() as connection:
        database, role = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
        credential = connection.execute(
            text(
                "SELECT status, password_hash_algorithm, failed_attempt_count, locked_at "
                "FROM oa_local_credentials WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).mappings().one()
        sessions = connection.execute(
            text(
                "SELECT status, count(*) FROM oa_user_sessions "
                "WHERE tenant_id = :tenant_id GROUP BY status"
            ),
            {"tenant_id": tenant_id},
        ).all()
        event_types = connection.execute(
            text(
                "SELECT event_type, count(*) FROM oa_auth_events "
                "WHERE tenant_id = :tenant_id GROUP BY event_type"
            ),
            {"tenant_id": tenant_id},
        ).all()
        outcomes = connection.execute(
            text(
                "SELECT outcome, count(*) FROM oa_auth_events "
                "WHERE tenant_id = :tenant_id GROUP BY outcome"
            ),
            {"tenant_id": tenant_id},
        ).all()
        matching_sessions = connection.execute(
            text(
                "SELECT count(*) FROM oa_user_sessions "
                "WHERE tenant_id = :tenant_id AND subject_id = :subject_id"
            ),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        ).scalar_one()
    session_counts = {str(status): int(count) for status, count in sessions}
    outcome_counts = {str(outcome): int(count) for outcome, count in outcomes}
    return {
        "database": str(database),
        "role": str(role),
        "credential_status": str(credential["status"]),
        "password_hash_algorithm": str(credential["password_hash_algorithm"]),
        "failed_attempt_count": int(credential["failed_attempt_count"]),
        "locked_at": credential["locked_at"],
        "persisted_session_count": int(matching_sessions),
        "observed_session_id_count": len(session_ids),
        "revoked_session_count": session_counts.get("REVOKED", 0),
        "active_session_count": session_counts.get("ACTIVE", 0),
        "event_counts": {
            str(event_type): int(count) for event_type, count in event_types
        },
        "succeeded_event_count": outcome_counts.get("SUCCEEDED", 0),
        "blocked_event_count": outcome_counts.get("BLOCKED", 0),
        "failed_event_count": outcome_counts.get("FAILED", 0),
    }


def _events_are_private(events: list[dict[str, Any]]) -> bool:
    serialized = json.dumps(events, sort_keys=True).lower()
    forbidden = (
        INITIAL_PASSWORD.lower(),
        TEMPORARY_PASSWORD.lower(),
        NEXT_PASSWORD.lower(),
        FINAL_PASSWORD.lower(),
        "password_hash",
        "session_id",
    )
    return all(value not in serialized for value in forbidden)


def _delete_smoke_rows(engine: Any, *, tenant_id: str) -> dict[str, int]:
    statements = (
        ("event_count", "DELETE FROM oa_auth_events WHERE tenant_id = :tenant_id"),
        ("session_count", "DELETE FROM oa_user_sessions WHERE tenant_id = :tenant_id"),
        (
            "credential_count",
            "DELETE FROM oa_local_credentials WHERE tenant_id = :tenant_id",
        ),
        (
            "membership_count",
            "DELETE FROM oa_tenant_memberships WHERE tenant_id = :tenant_id",
        ),
        ("subject_count", "DELETE FROM oa_subjects WHERE tenant_id = :tenant_id"),
        ("tenant_count", "DELETE FROM oa_tenants WHERE tenant_id = :tenant_id"),
    )
    with engine.begin() as connection:
        return {
            name: int(
                connection.execute(text(statement), {"tenant_id": tenant_id}).rowcount
                or 0
            )
            for name, statement in statements
        }


def _cleanup_residue(engine: Any, *, tenant_id: str) -> dict[str, int]:
    tables = {
        "event_count": "oa_auth_events",
        "session_count": "oa_user_sessions",
        "credential_count": "oa_local_credentials",
        "membership_count": "oa_tenant_memberships",
        "subject_count": "oa_subjects",
        "tenant_count": "oa_tenants",
    }
    with engine.connect() as connection:
        return {
            name: int(
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for name, table in tables.items()
        }


def _service_headers() -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-oa",
        scopes=[
            DEFAULT_SERVICE_SCOPE,
            OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE,
            OA_CREDENTIAL_SECURITY_WRITE_SCOPE,
            OA_CREDENTIAL_SECURITY_READ_SCOPE,
        ],
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": str(uuid4()),
        "traceparent": f"00-{uuid4().hex}-{uuid4().hex[:16]}-01",
    }


def _dispose_runtime(runtime: Any) -> None:
    for engine in (runtime.api_engine, runtime.worker_engine):
        if engine is not None:
            engine.dispose()


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1230",
        "requirement": "S123",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"oa_credential_security_postgres_smoke=skipped reason={SMOKE_ENV}"
    summary = evidence.get("summary") or {}
    return (
        "oa_credential_security_postgres_smoke="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"database={evidence.get('workflow', {}).get('database', 'not-run')} "
        f"events={summary.get('auth_event_count', 0)} "
        f"revoked={summary.get('revoked_session_count', 0)} "
        f"residue={summary.get('cleanup_residue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_oa_credential_security_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True, default=str)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
