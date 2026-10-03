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

from nex_oa.authorization_postgres_smoke import (  # noqa: E402
    EXPECTED_DATABASE,
    EXPECTED_ROLE,
    evaluate_authorization_postgres_smoke,
)
from nex_oa.authorization_repository import (  # noqa: E402
    build_authorization_repository_for_runtime,
)
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver  # noqa: E402
from nex_oa.authorization_service import (  # noqa: E402
    OA_AUTHORIZATION_ADMIN_SCOPE,
    OA_AUTHORIZATION_READ_SCOPE,
    OaAuthorizationService,
    register_authorization_routes,
)
from nex_oa.identity_access import OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE  # noqa: E402
from nex_oa.memberships import (  # noqa: E402
    build_tenant_membership_registry_for_runtime,
    register_identity_membership_routes,
)
from nex_oa.sessions import (  # noqa: E402
    build_oa_session_registry_for_runtime,
    register_user_session_routes,
)
from nex_oa.subjects import build_subject_registry_for_runtime  # noqa: E402
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


SMOKE_ENV = "NEX_OA_AUTHORIZATION_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
SCHEMA_VERSION = "oa_authorization_postgres_smoke.v1"
SERVICE_ID = "nex-oa"
PROFILE = "test"


def run_oa_authorization_postgres_smoke(
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
        workflow = _execute_authorization_postgres_smoke(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPECS[SERVICE_ID].database_env: database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            },
        )
        evidence = evaluate_authorization_postgres_smoke(
            {
                "planned": migration.planned,
                "applied": migration.applied,
                "skipped": migration.skipped,
            },
            workflow,
        )
        evidence.update(
            smoke_schema_version=SCHEMA_VERSION,
            slice="1240",
            requirement="S124",
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


def _execute_authorization_postgres_smoke(
    *, database_url: str, runtime_environ: Mapping[str, str]
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    tenant_id = f"tenant-oa-authz-{suffix}"
    subject_id = f"subject-oa-authz-{suffix}"
    role_id = f"editor-{suffix}"
    group_id = f"engineering-{suffix}"

    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    persistence = attach_service_persistence_runtime(
        app,
        SERVICE_SPECS[SERVICE_ID],
        environ=runtime_environ,
    )
    if persistence.api_session_factory is None or persistence.api_engine is None:
        raise RuntimeError("OA authorization PostgreSQL smoke runtime is unavailable")
    subjects = build_subject_registry_for_runtime(persistence)
    memberships = build_tenant_membership_registry_for_runtime(
        persistence, subject_registry=subjects
    )
    repository = build_authorization_repository_for_runtime(persistence)
    resolver = OaEffectiveAuthorizationResolver(repository)
    sessions = build_oa_session_registry_for_runtime(
        persistence,
        membership_registry=memberships,
        authorization_resolver=resolver,
    )
    service = OaAuthorizationService(repository, resolver, memberships)
    register_identity_membership_routes(app, registry=memberships)
    register_user_session_routes(app, registry=sessions)
    register_authorization_routes(app, service=service)
    client = TestClient(app)
    engine = persistence.api_engine
    result: dict[str, Any] = {}

    try:
        bootstrap_headers = _service_headers(OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE)
        admin_headers = _service_headers(OA_AUTHORIZATION_ADMIN_SCOPE)
        read_headers = _service_headers(OA_AUTHORIZATION_READ_SCOPE)
        service_headers = _service_headers()
        membership = client.post(
            "/internal/v1/identity/memberships/ensure",
            headers=bootstrap_headers,
            json={
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "tenant_display_name": "OA Authorization Smoke Tenant",
                "subject_display_name": "OA Authorization Smoke Subject",
                "roles": ["employee"],
                "scopes": ["workspace:use"],
            },
        )
        membership.raise_for_status()
        base = f"/internal/v1/auth/tenants/{tenant_id}"
        role = client.put(
            f"{base}/roles/{role_id}",
            headers=admin_headers,
            json={
                "display_name": "Smoke Editor",
                "scopes": ["document:read"],
                "expected_revision": 0,
            },
        )
        role.raise_for_status()
        group = client.put(
            f"{base}/groups/{group_id}",
            headers=admin_headers,
            json={"display_name": "Smoke Engineering", "expected_revision": 0},
        )
        group.raise_for_status()
        member = client.put(
            f"{base}/groups/{group_id}/members/{subject_id}",
            headers=admin_headers,
            json={"expected_revision": 0},
        )
        member.raise_for_status()

        first_session = client.post(
            "/internal/v1/auth/user-sessions/issue",
            headers=service_headers,
            json={
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "requested_scopes": ["workspace:use"],
            },
        )
        first_session.raise_for_status()
        first_session_id = str(first_session.json()["session"]["session_id"])
        assignment = client.put(
            f"{base}/groups/{group_id}/roles/{role_id}",
            headers=admin_headers,
            json={"expected_revision": 0},
        )
        assignment.raise_for_status()

        second_session = client.post(
            "/internal/v1/auth/user-sessions/issue",
            headers=service_headers,
            json={
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "requested_scopes": ["document:read"],
            },
        )
        second_session.raise_for_status()
        second_payload = second_session.json()["session"]
        second_session_id = str(second_payload["session_id"])
        role_update = client.put(
            f"{base}/roles/{role_id}",
            headers=admin_headers,
            json={
                "display_name": "Smoke Editor",
                "scopes": ["document:read", "document:write"],
                "expected_revision": 1,
            },
        )
        role_update.raise_for_status()
        stale = client.put(
            f"{base}/roles/{role_id}",
            headers=admin_headers,
            json={"scopes": ["document:read"], "expected_revision": 1},
        )
        denied = client.put(
            f"{base}/roles/denied-{suffix}",
            headers=service_headers,
            json={"scopes": ["document:read"], "expected_revision": 0},
        )
        effective = client.get(
            f"{base}/subjects/{subject_id}/authorization",
            headers=read_headers,
        )
        effective.raise_for_status()
        events = client.get(f"{base}/authorization-events", headers=read_headers)
        events.raise_for_status()

        restarted = build_authorization_repository_for_runtime(persistence)
        restart_inputs = restarted.authorization_inputs(
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
        observations = _db_observations(
            engine,
            tenant_id=tenant_id,
            role_id=role_id,
            session_ids=(first_session_id, second_session_id),
            restart_inputs=restart_inputs,
        )
        effective_payload = effective.json()["authorization"]
        checks = {
            "membership_created": membership.status_code == 200,
            "role_group_member_created": all(
                response.status_code == 200 for response in (role, group, member)
            ),
            "assignment_revoked_first_session": (
                assignment.json().get("revoked_session_count") == 1
            ),
            "effective_session_issued": (
                second_payload.get("roles") == ["editor-" + suffix, "employee"]
                and second_payload.get("scopes") == ["document:read"]
            ),
            "role_update_revoked_second_session": (
                role_update.json().get("revoked_session_count") == 1
            ),
            "stale_revision_rejected": (
                stale.status_code == 409
                and stale.json().get("error_code")
                == "oa.authorization_revision_conflict"
            ),
            "missing_admin_scope_rejected": denied.status_code == 403,
            "effective_readback": (
                role_id in effective_payload.get("roles", [])
                and "document:write" in effective_payload.get("scopes", [])
            ),
            "event_readback": events.json().get("count") == 5,
            "restart_readback": (
                len(restart_inputs["roles"]) == 1
                and len(restart_inputs["groups"]) == 1
                and len(restart_inputs["group_roles"]) == 1
            ),
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
    role_id: str,
    session_ids: tuple[str, str],
    restart_inputs: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    with engine.connect() as connection:
        database, role = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
        role_row = connection.execute(
            text(
                "SELECT revision, status, scopes FROM oa_roles "
                "WHERE tenant_id = :tenant_id AND role_id = :role_id"
            ),
            {"tenant_id": tenant_id, "role_id": role_id},
        ).one()
        counts = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM oa_groups WHERE tenant_id = :tenant_id) AS group_count, "
                "(SELECT count(*) FROM oa_group_members WHERE tenant_id = :tenant_id) AS group_member_count, "
                "(SELECT count(*) FROM oa_group_roles WHERE tenant_id = :tenant_id) AS group_role_count"
            ),
            {"tenant_id": tenant_id},
        ).mappings().one()
        sessions = connection.execute(
            text(
                "SELECT status, count(*) FROM oa_user_sessions "
                "WHERE session_id IN (:first_session_id, :second_session_id) "
                "GROUP BY status"
            ),
            {
                "first_session_id": session_ids[0],
                "second_session_id": session_ids[1],
            },
        ).all()
        events = connection.execute(
            text(
                "SELECT count(*) AS event_count, "
                "count(*) FILTER (WHERE actor_ref = 'nex.service:nex-ag') AS server_actor_count, "
                "count(*) FILTER (WHERE request_id <> '' AND trace_id <> '') AS request_trace_count, "
                "count(*) FILTER (WHERE details->>'revoked_session_count' = '1') AS revocation_event_count "
                "FROM oa_authz_events WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).mappings().one()
    session_counts = {str(status): int(count) for status, count in sessions}
    return {
        "database": str(database),
        "role": str(role),
        "role_revision": int(role_row[0]),
        "role_status": str(role_row[1]),
        "role_scopes": list(role_row[2]),
        "group_count": int(counts["group_count"]),
        "group_member_count": int(counts["group_member_count"]),
        "group_role_count": int(counts["group_role_count"]),
        "event_count": int(events["event_count"]),
        "server_actor_count": int(events["server_actor_count"]),
        "request_trace_count": int(events["request_trace_count"]),
        "revocation_event_count": int(events["revocation_event_count"]),
        "revoked_session_count": session_counts.get("REVOKED", 0),
        "active_session_count": session_counts.get("ACTIVE", 0),
        "restart_role_count": len(restart_inputs.get("roles", [])),
        "restart_group_count": len(restart_inputs.get("groups", [])),
        "restart_group_role_count": len(restart_inputs.get("group_roles", [])),
    }


def _delete_smoke_rows(engine: Any, *, tenant_id: str) -> dict[str, int]:
    statements = (
        ("authz_event_count", "DELETE FROM oa_authz_events WHERE tenant_id = :tenant_id"),
        ("group_role_count", "DELETE FROM oa_group_roles WHERE tenant_id = :tenant_id"),
        ("group_member_count", "DELETE FROM oa_group_members WHERE tenant_id = :tenant_id"),
        ("role_count", "DELETE FROM oa_roles WHERE tenant_id = :tenant_id"),
        ("group_count", "DELETE FROM oa_groups WHERE tenant_id = :tenant_id"),
        ("session_count", "DELETE FROM oa_user_sessions WHERE tenant_id = :tenant_id"),
        ("membership_count", "DELETE FROM oa_tenant_memberships WHERE tenant_id = :tenant_id"),
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
        "authz_event_count": "oa_authz_events",
        "group_role_count": "oa_group_roles",
        "group_member_count": "oa_group_members",
        "role_count": "oa_roles",
        "group_count": "oa_groups",
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


def _service_headers(*scopes: str) -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, *scopes],
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
        "slice": "1240",
        "requirement": "S124",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"oa_authorization_postgres_smoke=skipped reason={SMOKE_ENV}"
    summary = evidence.get("summary") or {}
    return (
        "oa_authorization_postgres_smoke="
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
    evidence = run_oa_authorization_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
