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

from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services/_shared",
    ROOT / "services/nex-oa",
    ROOT / "scripts/db",
):
    sys.path.insert(0, str(path))

from nex_oa.authorization_repository import (  # noqa: E402
    bind_authorization_session_registry,
    build_authorization_repository_for_runtime,
)
from nex_oa.authorization_resolver import (  # noqa: E402
    OaEffectiveAuthorizationResolver,
)
from nex_oa.authorization_service import OaAuthorizationService  # noqa: E402
from nex_oa.credentials import build_credential_registry_for_runtime  # noqa: E402
from nex_oa.memberships import (  # noqa: E402
    build_tenant_membership_registry_for_runtime,
)
from nex_oa.mvp_identity_restart_smoke import (  # noqa: E402
    EXPECTED_DATABASE,
    EXPECTED_ROLE,
    evaluate_oa_identity_restart_smoke,
)
from nex_oa.sessions import build_oa_session_registry_for_runtime  # noqa: E402
from nex_oa.subjects import build_subject_registry_for_runtime  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SMOKE_ENV = "NEX_OA_IDENTITY_RESTART_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
SCHEMA_VERSION = "oa_identity_session_authorization_restart_smoke.v1"
SERVICE_ID = "nex-oa"
PROFILE = "test"


def run_oa_identity_session_authorization_restart_smoke(
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
        workflow = _execute_restart_workflow(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPECS[SERVICE_ID].database_env: database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            },
        )
        evidence = evaluate_oa_identity_restart_smoke(
            {
                "planned": migration.planned,
                "applied": migration.applied,
                "skipped": migration.skipped,
            },
            workflow,
        )
        evidence.update(
            smoke_schema_version=SCHEMA_VERSION,
            slice="1295",
            requirement="S130",
            service_id=SERVICE_ID,
            profile=PROFILE,
            database_env=DATABASE_ENV,
            redacted_database_url=redact_database_url(database_url),
            migration={
                "planned_count": len(migration.planned),
                "applied": list(migration.applied),
                "skipped_count": len(migration.skipped),
            },
            next_slice="1296",
        )
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", exc.__class__.__name__)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__)


def _execute_restart_workflow(
    *, database_url: str, runtime_environ: Mapping[str, str]
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    tenant_id = f"tenant-s130-{suffix}"
    subject_id = f"user-s130-{suffix}"
    employee_id = f"EMP-S130-{suffix}"
    role_id = f"role-{suffix}"
    group_id = f"group-{suffix}"
    password = f"S130-{uuid4().hex}!"
    context = {
        "actor_ref": "nex.service:nex-ag",
        "request_id": f"request-{suffix}",
        "trace_id": uuid4().hex,
    }
    first = _build_stack(runtime_environ)
    first_persistence = first["persistence"]
    session_id: str | None = None
    second: dict[str, Any] | None = None
    result: dict[str, Any] = {}
    try:
        first["memberships"].ensure_membership(
            {
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "tenant_display_name": "S130 Restart Tenant",
                "subject_display_name": "S130 Restart User",
                "roles": ["employee"],
                "scopes": ["workspace:use"],
            }
        )
        first["credentials"].ensure_credential(
            {
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "employee_id": employee_id,
                "password": password,
                "subject_display_name": "S130 Restart User",
            }
        )
        _seed_authorization(
            first["authorization"],
            tenant_id=tenant_id,
            subject_id=subject_id,
            role_id=role_id,
            group_id=group_id,
            context=context,
        )
        issued = first["sessions"].issue_session(
            {
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "requested_scopes": ["document:read"],
                "ttl_seconds": 1800,
            }
        )
        session_id = str(issued["session"]["session_id"])
        _dispose_runtime(first_persistence)

        second = _build_stack(runtime_environ)
        verified = second["credentials"].verify_credential(
            {
                "tenant_id": tenant_id,
                "employee_id": employee_id,
                "password": password,
            }
        )
        membership = second["memberships"].get_membership(
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
        introspection = second["sessions"].introspect_session(
            {"session_id": session_id}
        )
        authorization = second["authorization"].effective_authorization(
            tenant_id=tenant_id,
            subject_id=subject_id,
        )["authorization"]
        observations = _database_observations(
            second["persistence"].api_engine,
            tenant_id=tenant_id,
            subject_id=subject_id,
            employee_id=employee_id,
            role_id=role_id,
            group_id=group_id,
            password=password,
        )
        result = {
            "database": observations.pop("database"),
            "role": observations.pop("role"),
            "runtime_mode": second["persistence"].mode,
            "checks": {
                "credential_verified_after_restart": (
                    verified["subject_ref"]["id"] == subject_id
                ),
                "membership_loaded_after_restart": (
                    membership is not None
                    and membership["membership"]["status"] == "ACTIVE"
                ),
                "session_active_after_restart": (
                    introspection.get("active") is True
                    and introspection.get("session", {}).get("session_id")
                    == session_id
                ),
                "authorization_loaded_after_restart": (
                    role_id in authorization["roles"]
                    and group_id in authorization["group_ids"]
                    and "document:read" in authorization["scopes"]
                ),
            },
            "db_observations": observations,
        }
    finally:
        cleanup_runtime = (
            second["persistence"] if second is not None else first_persistence
        )
        engine = cleanup_runtime.api_engine
        if engine is not None:
            _cleanup(engine, tenant_id=tenant_id)
            result["cleanup_residue"] = _cleanup_residue(
                engine, tenant_id=tenant_id
            )
        _dispose_runtime(cleanup_runtime)
    return result


def _build_stack(runtime_environ: Mapping[str, str]) -> dict[str, Any]:
    app = build_service_app(
        SERVICE_SPECS[SERVICE_ID], include_oa_mock_auth_routes=False
    )
    persistence = attach_service_persistence_runtime(
        app, SERVICE_SPECS[SERVICE_ID], environ=runtime_environ
    )
    if persistence.api_session_factory is None or persistence.api_engine is None:
        raise RuntimeError("OA PostgreSQL restart runtime is unavailable")
    subjects = build_subject_registry_for_runtime(persistence)
    memberships = build_tenant_membership_registry_for_runtime(
        persistence, subject_registry=subjects
    )
    credentials = build_credential_registry_for_runtime(
        persistence, subject_registry=subjects
    )
    authorization_repository = build_authorization_repository_for_runtime(
        persistence
    )
    resolver = OaEffectiveAuthorizationResolver(authorization_repository)
    sessions = build_oa_session_registry_for_runtime(
        persistence,
        membership_registry=memberships,
        authorization_resolver=resolver,
    )
    bind_authorization_session_registry(authorization_repository, sessions)
    authorization = OaAuthorizationService(
        authorization_repository, resolver, memberships
    )
    return {
        "persistence": persistence,
        "memberships": memberships,
        "credentials": credentials,
        "sessions": sessions,
        "authorization": authorization,
    }


def _seed_authorization(
    service: OaAuthorizationService,
    *,
    tenant_id: str,
    subject_id: str,
    role_id: str,
    group_id: str,
    context: Mapping[str, str],
) -> None:
    service.upsert_role(
        tenant_id=tenant_id,
        role_id=role_id,
        payload={
            "display_name": "S130 Reader",
            "scopes": ["document:read"],
            "expected_revision": 0,
        },
        context=context,
    )
    service.upsert_group(
        tenant_id=tenant_id,
        group_id=group_id,
        payload={"display_name": "S130 Group", "expected_revision": 0},
        context=context,
    )
    service.upsert_group_member(
        tenant_id=tenant_id,
        group_id=group_id,
        subject_id=subject_id,
        payload={"expected_revision": 0},
        context=context,
    )
    service.upsert_group_role(
        tenant_id=tenant_id,
        group_id=group_id,
        role_id=role_id,
        payload={"expected_revision": 0},
        context=context,
    )


def _database_observations(
    engine: Any,
    *,
    tenant_id: str,
    subject_id: str,
    employee_id: str,
    role_id: str,
    group_id: str,
    password: str,
) -> dict[str, Any]:
    params = {
        "tenant_id": tenant_id,
        "subject_id": subject_id,
        "employee_id": employee_id.casefold(),
        "role_id": role_id,
        "group_id": group_id,
        "password": password,
    }
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT current_database(), current_user, "
                "(SELECT count(*) FROM schema_migrations), "
                "(SELECT count(*) FROM oa_tenants WHERE tenant_id = :tenant_id), "
                "(SELECT count(*) FROM oa_subjects WHERE tenant_id = :tenant_id AND subject_id = :subject_id), "
                "(SELECT count(*) FROM oa_tenant_memberships WHERE tenant_id = :tenant_id AND subject_id = :subject_id), "
                "(SELECT count(*) FROM oa_local_credentials WHERE tenant_id = :tenant_id AND normalized_employee_id = :employee_id), "
                "(SELECT count(*) FROM oa_user_sessions WHERE tenant_id = :tenant_id AND subject_id = :subject_id), "
                "(SELECT count(*) FROM oa_roles WHERE tenant_id = :tenant_id AND role_id = :role_id), "
                "(SELECT count(*) FROM oa_groups WHERE tenant_id = :tenant_id AND group_id = :group_id), "
                "(SELECT count(*) FROM oa_group_members WHERE tenant_id = :tenant_id AND group_id = :group_id AND subject_id = :subject_id), "
                "(SELECT count(*) FROM oa_group_roles WHERE tenant_id = :tenant_id AND group_id = :group_id AND role_id = :role_id), "
                "(SELECT count(*) FROM oa_authz_events WHERE tenant_id = :tenant_id), "
                "(SELECT count(*) FROM oa_local_credentials WHERE tenant_id = :tenant_id AND password_hash = :password), "
                "(SELECT count(*) FROM oa_local_credentials WHERE tenant_id = :tenant_id AND password_hash IS NOT NULL)"
            ),
            params,
        ).one()
    names = (
        "database",
        "role",
        "migration_ledger_count",
        "tenant_count",
        "subject_count",
        "membership_count",
        "credential_count",
        "session_count",
        "role_count",
        "group_count",
        "group_member_count",
        "group_role_count",
        "authz_event_count",
        "raw_password_match_count",
        "password_hash_count",
    )
    return dict(zip(names, row, strict=True))


def _cleanup(engine: Any, *, tenant_id: str) -> None:
    tables = (
        "oa_authz_events",
        "oa_group_roles",
        "oa_group_members",
        "oa_groups",
        "oa_roles",
        "oa_user_sessions",
        "oa_local_credentials",
        "oa_tenant_memberships",
        "oa_subjects",
        "oa_tenants",
    )
    with engine.begin() as connection:
        for table in tables:
            connection.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )


def _cleanup_residue(engine: Any, *, tenant_id: str) -> dict[str, int]:
    tables = {
        "authz_event_count": "oa_authz_events",
        "group_role_count": "oa_group_roles",
        "group_member_count": "oa_group_members",
        "group_count": "oa_groups",
        "role_count": "oa_roles",
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
                    text(
                        f"SELECT count(*) FROM {table} "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for name, table in tables.items()
        }


def _target_url_allowed(database_url: str) -> bool:
    try:
        parsed = urlsplit(
            database_url.replace("postgresql+psycopg", "postgresql", 1)
        )
    except ValueError:
        return False
    return (
        parsed.scheme == "postgresql"
        and unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


def _dispose_runtime(runtime: Any) -> None:
    seen: set[int] = set()
    for engine in (runtime.api_engine, runtime.worker_engine):
        if engine is not None and id(engine) not in seen:
            seen.add(id(engine))
            engine.dispose()


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1295",
        "requirement": "S130",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"oa_identity_restart_postgres=skip reason={SMOKE_ENV}"
    if evidence.get("status") != "PASS":
        return (
            "oa_identity_restart_postgres=fail "
            f"code={evidence.get('failure_code')}"
        )
    summary = evidence.get("summary") or {}
    workflow = evidence.get("workflow") or {}
    return (
        "oa_identity_restart_postgres=pass "
        f"database={workflow.get('database')} "
        f"migrations={summary.get('migration_count', 0)} "
        f"restart_reads={summary.get('restart_read_count', 0)} "
        f"rows={summary.get('persisted_row_class_count', 0)} "
        f"residue={summary.get('cleanup_residue_count', 0)} next=1296"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_oa_identity_session_authorization_restart_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
