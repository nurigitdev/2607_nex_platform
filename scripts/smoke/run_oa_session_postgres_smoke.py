#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
OA_PATH = ROOT / "services" / "nex-oa"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(OA_PATH))

from nex_oa.memberships import (  # noqa: E402
    build_tenant_membership_registry_for_runtime,
    register_identity_membership_routes,
)
from nex_oa.sessions import (  # noqa: E402
    build_oa_session_registry_for_runtime,
    register_user_session_routes,
)
from nex_oa.subjects import (  # noqa: E402
    build_subject_registry_for_runtime,
    register_subject_registry_routes,
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
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SMOKE_ENV = "NEX_OA_SESSION_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_OA_SESSION_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-oa"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
SCHEMA_VERSION = "oa_session_postgres_smoke.v1"
SECRET_MARKER = "OA session PostgreSQL smoke private marker"


def run_oa_session_postgres_smoke(
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
            f"{SMOKE_PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        migration_result = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_oa_session_postgres_smoke(
            database_env=database_env,
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPEC.database_env: database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            },
        )
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            "migration": _migration_evidence(migration_result),
            **execution,
        }
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_oa_session_postgres_smoke(
    *,
    database_env: str,
    database_url: str,
    runtime_environ: dict[str, str],
) -> dict[str, object]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.split("-", maxsplit=1)[0]
    tenant_id = f"tenant-oa-session-smoke-{suffix}"
    subject_id = f"user-oa-session-smoke-{suffix}"
    session_id: str | None = None
    result: dict[str, object] = {}
    engine = build_engine(database_url)
    app = build_service_app(SERVICE_SPEC)
    persistence = attach_service_persistence_runtime(
        app,
        SERVICE_SPEC,
        environ=runtime_environ,
    )
    if persistence.api_session_factory is None:
        raise RuntimeError("OA PostgreSQL session smoke factory is unavailable")

    subject_registry = build_subject_registry_for_runtime(persistence)
    membership_registry = build_tenant_membership_registry_for_runtime(
        persistence,
        subject_registry=subject_registry,
    )
    session_registry = build_oa_session_registry_for_runtime(
        persistence,
        membership_registry=membership_registry,
    )
    register_subject_registry_routes(app, registry=subject_registry)
    register_identity_membership_routes(app, registry=membership_registry)
    register_user_session_routes(app, registry=session_registry)
    client = TestClient(app)

    try:
        membership_response = client.post(
            "/internal/v1/identity/memberships/ensure",
            headers=_service_headers(trace_id=trace_id, request_id=request_id),
            json={
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "tenant_display_name": "OA Session Smoke Tenant",
                "subject_display_name": "OA Session Smoke User",
                "roles": ["employee", "smoke-tester"],
                "scopes": ["workspace:use", "documents:read"],
                "membership_metadata": {"smoke_marker": "oa-session-postgres"},
            },
        )
        membership_response.raise_for_status()
        issue_response = client.post(
            "/internal/v1/auth/user-sessions/issue",
            headers=_service_headers(trace_id=trace_id, request_id=request_id),
            json={
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "requested_scopes": ["workspace:use"],
                "ttl_seconds": 1800,
            },
        )
        issue_response.raise_for_status()
        issued = issue_response.json()
        session_id = str(issued["session"]["session_id"])
        readback_response = client.get(
            f"/internal/v1/auth/user-sessions/{session_id}",
            headers=_service_headers(trace_id=trace_id, request_id=request_id),
        )
        readback_response.raise_for_status()
        readback = readback_response.json()
        db_observations = _db_observations(
            engine,
            tenant_id=tenant_id,
            subject_id=subject_id,
            session_id=session_id,
        )
        checks = {
            "runtime_mode": persistence.mode == "postgres",
            "membership_status_ok": membership_response.status_code == 200,
            "issue_status_ok": issue_response.status_code == 200,
            "readback_status_ok": readback_response.status_code == 200,
            "session_id_roundtrip": readback["session"]["session_id"] == session_id,
            "scope_subset_applied": issued["session"]["scopes"] == ["workspace:use"],
            "membership_persisted": db_observations["membership_count"] == 1,
            "session_persisted": db_observations["session_count"] == 1,
            "session_subject_matches": (
                db_observations["session_tenant_id"] == tenant_id
                and db_observations["session_subject_id"] == subject_id
            ),
            "raw_payload_absent": _redaction_safe(
                {
                    "membership": membership_response.json(),
                    "issued": issued,
                    "readback": readback,
                    "db": db_observations,
                },
                forbidden_fragments=[
                    SECRET_MARKER,
                    "access_token",
                    "nuri1004",
                    database_url,
                ],
            ),
        }
        if not all(checks.values()):
            raise RuntimeError("OA session PostgreSQL smoke checks failed")
        result = {
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "session_id": session_id,
            "db_observations": db_observations,
            "checks": checks,
        }
    finally:
        result["cleanup_observations"] = _delete_smoke_rows(
            engine,
            tenant_id=tenant_id,
            subject_id=subject_id,
            session_id=session_id,
        )
    return result


def _db_observations(
    engine: Any,
    *,
    tenant_id: str,
    subject_id: str,
    session_id: str,
) -> dict[str, object]:
    with engine.connect() as connection:
        membership_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM oa_tenant_memberships
                WHERE tenant_id = :tenant_id
                  AND subject_id = :subject_id
                """
            ),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        ).scalar_one()
        session_row = connection.execute(
            text(
                """
                SELECT tenant_id, subject_id, status, scopes, roles
                FROM oa_user_sessions
                WHERE session_id = :session_id
                """
            ),
            {"session_id": session_id},
        ).mappings().first()
    return {
        "membership_count": int(membership_count),
        "session_count": 1 if session_row is not None else 0,
        "session_tenant_id": session_row["tenant_id"] if session_row else None,
        "session_subject_id": session_row["subject_id"] if session_row else None,
        "session_status": session_row["status"] if session_row else None,
        "session_scopes": _json_loads(session_row["scopes"]) if session_row else [],
        "session_roles": _json_loads(session_row["roles"]) if session_row else [],
    }


def _delete_smoke_rows(
    engine: Any,
    *,
    tenant_id: str,
    subject_id: str,
    session_id: str | None,
) -> dict[str, int]:
    with engine.begin() as connection:
        deleted_sessions = connection.execute(
            text(
                """
                DELETE FROM oa_user_sessions
                WHERE session_id = :session_id
                   OR (tenant_id = :tenant_id AND subject_id = :subject_id)
                """
            ),
            {
                "session_id": session_id or "",
                "tenant_id": tenant_id,
                "subject_id": subject_id,
            },
        ).rowcount
        deleted_memberships = connection.execute(
            text(
                """
                DELETE FROM oa_tenant_memberships
                WHERE tenant_id = :tenant_id
                  AND subject_id = :subject_id
                """
            ),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        ).rowcount
        deleted_subjects = connection.execute(
            text(
                """
                DELETE FROM oa_subjects
                WHERE tenant_id = :tenant_id
                  AND subject_id = :subject_id
                """
            ),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        ).rowcount
        deleted_tenants = connection.execute(
            text(
                """
                DELETE FROM oa_tenants
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).rowcount
    return {
        "deleted_sessions": int(deleted_sessions),
        "deleted_memberships": int(deleted_memberships),
        "deleted_subjects": int(deleted_subjects),
        "deleted_tenants": int(deleted_tenants),
    }


def _service_headers(*, trace_id: str, request_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-oa")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        "X-Request-ID": request_id,
    }


def _migration_evidence(result: Any) -> dict[str, object]:
    return {
        "service_id": result.service_id,
        "profile": result.profile,
        "planned_count": len(result.planned),
        "applied": list(result.applied),
        "skipped_count": len(result.skipped),
        "dry_run": result.dry_run,
    }


def _redaction_safe(value: object, forbidden_fragments: list[str]) -> bool:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return all(fragment not in serialized for fragment in forbidden_fragments)


def _json_loads(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


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
        return f"oa_session_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "oa_session_postgres_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']}"
        )
    return (
        "oa_session_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional OA user-session PostgreSQL smoke."
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
    evidence = run_oa_session_postgres_smoke()
    output = (
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False)
    )
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
