#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
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

from nex_oa.identity_lifecycle_postgres_smoke import (  # noqa: E402
    EXPECTED_DATABASE,
    EXPECTED_ROLE,
    evaluate_identity_lifecycle_postgres_smoke,
)
from nex_oa.identity_lifecycle_repository import (  # noqa: E402
    build_identity_lifecycle_repository_for_runtime,
)
from nex_oa.identity_lifecycle_service import (  # noqa: E402
    OA_IDENTITY_LIFECYCLE_WRITE_SCOPE,
    OaIdentityLifecycleService,
    register_identity_lifecycle_routes,
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
)
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


SMOKE_ENV = "NEX_OA_IDENTITY_LIFECYCLE_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
SCHEMA_VERSION = "oa_identity_lifecycle_postgres_smoke.v1"
SERVICE_ID = "nex-oa"
PROFILE = "test"


def run_oa_identity_lifecycle_postgres_smoke(
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
        workflow = _execute_identity_lifecycle_postgres_smoke(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPECS[SERVICE_ID].database_env: database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            },
        )
        evidence = evaluate_identity_lifecycle_postgres_smoke(
            {
                "planned": migration.planned,
                "applied": migration.applied,
                "skipped": migration.skipped,
            },
            workflow,
        )
        evidence.update(
            smoke_schema_version=SCHEMA_VERSION,
            slice="1220",
            requirement="S122",
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


def _execute_identity_lifecycle_postgres_smoke(
    *, database_url: str, runtime_environ: Mapping[str, str]
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    tenant_id = f"tenant-oa-lifecycle-{suffix}"
    subject_id = f"subject-oa-lifecycle-{suffix}"
    member_id = f"member-oa-lifecycle-{suffix}"
    subject_session_id: str | None = None
    member_session_id: str | None = None

    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    persistence = attach_service_persistence_runtime(
        app,
        SERVICE_SPECS[SERVICE_ID],
        environ=runtime_environ,
    )
    if persistence.api_session_factory is None or persistence.api_engine is None:
        raise RuntimeError("OA lifecycle PostgreSQL smoke runtime is unavailable")
    subjects = build_subject_registry_for_runtime(persistence)
    memberships = build_tenant_membership_registry_for_runtime(
        persistence, subject_registry=subjects
    )
    sessions = build_oa_session_registry_for_runtime(
        persistence, membership_registry=memberships
    )
    repository = build_identity_lifecycle_repository_for_runtime(
        persistence,
        subject_registry=subjects,
        membership_registry=memberships,
        session_registry=sessions,
    )
    lifecycle = OaIdentityLifecycleService(subjects, memberships, repository)
    register_identity_membership_routes(app, registry=memberships)
    register_user_session_routes(app, registry=sessions)
    register_identity_lifecycle_routes(app, service=lifecycle)
    client = TestClient(app)
    engine = persistence.api_engine
    result: dict[str, Any] = {}

    try:
        service_headers = _service_headers(lifecycle=False)
        lifecycle_headers = _service_headers(lifecycle=True)
        for current_subject in (subject_id, member_id):
            response = client.post(
                "/internal/v1/identity/memberships/ensure",
                headers=service_headers,
                json={
                    "tenant_id": tenant_id,
                    "subject_id": current_subject,
                    "tenant_display_name": "OA Lifecycle Smoke Tenant",
                    "subject_display_name": "OA Lifecycle Smoke Subject",
                    "roles": ["employee"],
                    "scopes": ["workspace:use"],
                },
            )
            response.raise_for_status()

        subject_session = client.post(
            "/internal/v1/auth/user-sessions/issue",
            headers=service_headers,
            json={
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "requested_scopes": ["workspace:use"],
                "ttl_seconds": 1800,
            },
        )
        subject_session.raise_for_status()
        subject_session_id = str(subject_session.json()["session"]["session_id"])
        member_session = client.post(
            "/internal/v1/auth/user-sessions/issue",
            headers=service_headers,
            json={
                "tenant_id": tenant_id,
                "subject_id": member_id,
                "requested_scopes": ["workspace:use"],
                "ttl_seconds": 1800,
            },
        )
        member_session.raise_for_status()
        member_session_id = str(member_session.json()["session"]["session_id"])

        subject_response = client.patch(
            f"/internal/v1/identity/tenants/{tenant_id}/subjects/{subject_id}/lifecycle",
            headers=lifecycle_headers,
            json={
                "target_status": "DISABLED",
                "expected_revision": 1,
                "reason_code": "smoke.subject-disable",
            },
        )
        subject_response.raise_for_status()
        stale_response = client.patch(
            f"/internal/v1/identity/tenants/{tenant_id}/subjects/{subject_id}/lifecycle",
            headers=lifecycle_headers,
            json={
                "target_status": "DELETED",
                "expected_revision": 1,
                "reason_code": "smoke.stale-delete",
            },
        )
        membership_response = client.patch(
            f"/internal/v1/identity/tenants/{tenant_id}/memberships/{member_id}/lifecycle",
            headers=lifecycle_headers,
            json={
                "target_status": "DISABLED",
                "expected_revision": 1,
                "reason_code": "smoke.membership-disable",
            },
        )
        membership_response.raise_for_status()

        observations = _db_observations(
            engine,
            tenant_id=tenant_id,
            subject_id=subject_id,
            member_id=member_id,
            session_ids=(subject_session_id, member_session_id),
        )
        subject_payload = subject_response.json()
        membership_payload = membership_response.json()
        checks = {
            "subject_route_status": subject_response.status_code == 200,
            "subject_revision_advanced": (
                subject_payload.get("status") == "DISABLED"
                and subject_payload.get("revision") == 2
            ),
            "subject_session_revoked": (
                subject_payload.get("revoked_session_count") == 1
            ),
            "stale_revision_rejected": (
                stale_response.status_code == 409
                and stale_response.json().get("error_code")
                == "oa.lifecycle_revision_conflict"
            ),
            "membership_route_status": membership_response.status_code == 200,
            "membership_revision_advanced": (
                membership_payload.get("status") == "DISABLED"
                and membership_payload.get("revision") == 2
            ),
            "membership_session_revoked": (
                membership_payload.get("revoked_session_count") == 1
            ),
            "two_events_persisted": observations.get("event_count") == 2,
            "server_actor_persisted": observations.get("server_actor_count") == 2,
            "request_trace_persisted": observations.get("request_trace_count") == 2,
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


def _db_observations(
    engine: Any,
    *,
    tenant_id: str,
    subject_id: str,
    member_id: str,
    session_ids: tuple[str, str],
) -> dict[str, Any]:
    with engine.connect() as connection:
        database, role = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
        subject = connection.execute(
            text(
                "SELECT status, revision FROM oa_subjects "
                "WHERE tenant_id = :tenant_id AND subject_id = :subject_id"
            ),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        ).one()
        membership = connection.execute(
            text(
                "SELECT status, revision FROM oa_tenant_memberships "
                "WHERE tenant_id = :tenant_id AND subject_id = :subject_id"
            ),
            {"tenant_id": tenant_id, "subject_id": member_id},
        ).one()
        sessions = connection.execute(
            text(
                "SELECT status, count(*) FROM oa_user_sessions "
                "WHERE session_id IN (:subject_session_id, :member_session_id) "
                "GROUP BY status"
            ),
            {
                "subject_session_id": session_ids[0],
                "member_session_id": session_ids[1],
            },
        ).all()
        events = connection.execute(
            text(
                """
                SELECT
                    count(*) AS event_count,
                    count(*) FILTER (WHERE entity_type = 'SUBJECT') AS subject_event_count,
                    count(*) FILTER (WHERE entity_type = 'MEMBERSHIP') AS membership_event_count,
                    count(*) FILTER (
                        WHERE actor_ref_type = 'nex.service' AND actor_ref_id = 'nex-ag'
                    ) AS server_actor_count,
                    count(*) FILTER (
                        WHERE request_id <> '' AND trace_id <> ''
                    ) AS request_trace_count
                FROM oa_id_lifecycle_events
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().one()
    session_counts = {str(status): int(count) for status, count in sessions}
    return {
        "database": str(database),
        "role": str(role),
        "subject_status": str(subject[0]),
        "subject_revision": int(subject[1]),
        "membership_status": str(membership[0]),
        "membership_revision": int(membership[1]),
        "event_count": int(events["event_count"]),
        "subject_event_count": int(events["subject_event_count"]),
        "membership_event_count": int(events["membership_event_count"]),
        "server_actor_count": int(events["server_actor_count"]),
        "request_trace_count": int(events["request_trace_count"]),
        "revoked_session_count": session_counts.get("REVOKED", 0),
        "active_session_count": session_counts.get("ACTIVE", 0),
    }


def _delete_smoke_rows(engine: Any, *, tenant_id: str) -> dict[str, int]:
    statements = (
        ("event_count", "DELETE FROM oa_id_lifecycle_events WHERE tenant_id = :tenant_id"),
        ("session_count", "DELETE FROM oa_user_sessions WHERE tenant_id = :tenant_id"),
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
        "event_count": "oa_id_lifecycle_events",
        "session_count": "oa_user_sessions",
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


def _service_headers(*, lifecycle: bool) -> dict[str, str]:
    scopes = [DEFAULT_SERVICE_SCOPE, OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE]
    if lifecycle:
        scopes.append(OA_IDENTITY_LIFECYCLE_WRITE_SCOPE)
    token = issue_mock_service_token(
        service_id="nex-ag", audience="nex-oa", scopes=scopes
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
        "slice": "1220",
        "requirement": "S122",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"oa_identity_lifecycle_postgres_smoke=skipped reason={SMOKE_ENV}"
    summary = evidence.get("summary") or {}
    return (
        "oa_identity_lifecycle_postgres_smoke="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"database={evidence.get('workflow', {}).get('database', 'not-run')} "
        f"events={summary.get('event_count', 0)} "
        f"revoked={summary.get('revoked_session_count', 0)} "
        f"residue={summary.get('cleanup_residue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_oa_identity_lifecycle_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
