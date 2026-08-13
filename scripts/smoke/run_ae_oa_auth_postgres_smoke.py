#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote
from uuid import uuid4

from fastapi import Header, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
OA_PATH = ROOT / "services" / "nex-oa"
AE_PATH = ROOT / "services" / "nex-ae-api"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(OA_PATH))
sys.path.insert(0, str(AE_PATH))

from nex_ae_api.auth_sessions import (  # noqa: E402
    AUTH_SESSION_MODE_OA,
    SESSION_COOKIE_NAME,
    register_auth_session_routes,
)
from nex_ae_api.oa_session_client import (  # noqa: E402
    OaUserSessionClientError,
    oa_session_issue_payload,
    oa_user_login_payload,
)
from nex_ae_api.route_auth import authorize_ae_facade_route_request  # noqa: E402
from nex_oa.credentials import (  # noqa: E402
    build_credential_registry_for_runtime,
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
    build_subject_registry_for_runtime,
    register_subject_registry_routes,
)
from nex_oa.user_login import OaUserLoginService, register_user_login_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    DEFAULT_USER_SCOPE,
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


SCHEMA_VERSION = "ae_oa_auth_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_OA_AUTH_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_OA_AUTH_POSTGRES_SMOKE_PROFILE"
TENANT_ID_ENV = "NEX_AE_OA_AUTH_POSTGRES_SMOKE_TENANT_ID"
SUBJECT_ID_ENV = "NEX_AE_OA_AUTH_POSTGRES_SMOKE_SUBJECT_ID"
EMPLOYEE_ID_ENV = "NEX_AE_OA_AUTH_POSTGRES_SMOKE_EMPLOYEE_ID"
PASSWORD_ENV = "NEX_AE_OA_AUTH_POSTGRES_SMOKE_PASSWORD"
DEFAULT_PROFILE = "test"
AE_SERVICE_ID = "nex-ae-api"
OA_SERVICE_ID = "nex-oa"
AE_SERVICE_SPEC = SERVICE_SPECS[AE_SERVICE_ID]
OA_SERVICE_SPEC = SERVICE_SPECS[OA_SERVICE_ID]
SECRET_MARKER = "AE OA auth PostgreSQL smoke private marker"
SMOKE_LOGIN_PASSWORD = "Nuri1004!"


@dataclass
class TestClientOaUserSessionClient:
    client: TestClient
    calls: list[dict[str, object]] = field(default_factory=list)

    def issue_session(
        self,
        login_request: Mapping[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/internal/v1/auth/user-sessions/issue",
            headers=_service_headers(trace_id=trace_id, request_id=request_id),
            json=oa_session_issue_payload(login_request),
        )
        return self._payload_or_error(
            response,
            operation="issue_session",
            error_code="oa.session_issue_failed",
        )

    def login_with_credentials(
        self,
        login_request: Mapping[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/internal/v1/auth/user-login",
            headers=_service_headers(trace_id=trace_id, request_id=request_id),
            json=oa_user_login_payload(login_request),
        )
        payload = self._payload_or_error(
            response,
            operation="login_with_credentials",
            error_code="oa.user_login_failed",
        )
        if self.calls:
            metadata = payload.get("metadata")
            self.calls[-1]["password_verified"] = (
                metadata.get("password_verified") is True
                if isinstance(metadata, Mapping)
                else False
            )
        return payload

    def introspect_session(
        self,
        session_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/internal/v1/auth/user-sessions/introspect",
            headers=_service_headers(trace_id=trace_id, request_id=request_id),
            json={"session_id": session_id},
        )
        return self._payload_or_error(
            response,
            operation="introspect_session",
            error_code="oa.session_introspection_failed",
        )

    def revoke_session(
        self,
        session_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            f"/internal/v1/auth/user-sessions/{quote(session_id, safe='')}/revoke",
            headers=_service_headers(trace_id=trace_id, request_id=request_id),
        )
        return self._payload_or_error(
            response,
            operation="revoke_session",
            error_code="oa.session_revocation_failed",
        )

    def _payload_or_error(
        self,
        response: object,
        *,
        operation: str,
        error_code: str,
    ) -> dict[str, Any]:
        body = _safe_response_json(response)
        status_code = int(getattr(response, "status_code", 500))
        self.calls.append({"operation": operation, "status_code": status_code})
        if status_code >= 400:
            raise OaUserSessionClientError(
                status_code=status_code,
                error_code=str(body.get("error_code", error_code)),
                detail=str(body.get("detail", "OA user-session request failed.")),
                retryable=bool(body.get("retryable", status_code >= 500)),
            )
        return body


def run_ae_oa_auth_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
        )

    try:
        ae_database_env = service_database_env(AE_SERVICE_ID, profile=profile)
        oa_database_env = service_database_env(OA_SERVICE_ID, profile=profile)
        ae_database_url = service_database_url(
            AE_SERVICE_ID,
            profile=profile,
            environ=env,
        )
        oa_database_url = service_database_url(
            OA_SERVICE_ID,
            profile=profile,
            environ=env,
        )
        _require_test_database_url(ae_database_url, env_name=ae_database_env)
        _require_test_database_url(oa_database_url, env_name=oa_database_env)
        ae_migration = run_service_migrations(
            AE_SERVICE_ID,
            database_url=ae_database_url,
            profile=profile,
        )
        oa_migration = run_service_migrations(
            OA_SERVICE_ID,
            database_url=oa_database_url,
            profile=profile,
        )
        execution = _execute_ae_oa_auth_postgres_smoke(
            env=env,
            ae_database_url=ae_database_url,
            oa_database_url=oa_database_url,
        )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "profile": profile,
            "services": [AE_SERVICE_ID, OA_SERVICE_ID],
            "database_envs": {
                "ae": ae_database_env,
                "oa": oa_database_env,
            },
            "redacted_database_urls": {
                "ae": redact_database_url(ae_database_url),
                "oa": redact_database_url(oa_database_url),
            },
            "migrations": {
                "ae": _migration_evidence(ae_migration),
                "oa": _migration_evidence(oa_migration),
            },
            **execution,
        }
        assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_ae_oa_auth_postgres_smoke(
    *,
    env: dict[str, str],
    ae_database_url: str,
    oa_database_url: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.split("-", maxsplit=1)[0]
    tenant_id = env.get(TENANT_ID_ENV) or f"tenant-ae-oa-auth-smoke-{suffix}"
    subject_id = env.get(SUBJECT_ID_ENV) or f"user-ae-oa-auth-smoke-{suffix}"
    employee_id = env.get(EMPLOYEE_ID_ENV) or f"EMP-AE-OA-AUTH-{suffix}"
    login_password = env.get(PASSWORD_ENV) or SMOKE_LOGIN_PASSWORD
    ae_engine = build_engine(ae_database_url)
    oa_engine = build_engine(oa_database_url)
    ae_marker_id: str | None = None
    session_id: str | None = None
    result: dict[str, Any] = {}

    try:
        ae_marker_id = _write_ae_smoke_marker(
            ae_engine,
            request_id=request_id,
            trace_id=trace_id,
            subject_id=subject_id,
        )
        oa_app = build_service_app(OA_SERVICE_SPEC)
        oa_persistence = attach_service_persistence_runtime(
            oa_app,
            OA_SERVICE_SPEC,
            environ={
                **env,
                OA_SERVICE_SPEC.database_env: oa_database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            },
        )
        if oa_persistence.api_session_factory is None:
            raise RuntimeError("OA PostgreSQL session factory is unavailable")
        subject_registry = build_subject_registry_for_runtime(oa_persistence)
        membership_registry = build_tenant_membership_registry_for_runtime(
            oa_persistence,
            subject_registry=subject_registry,
        )
        credential_registry = build_credential_registry_for_runtime(
            oa_persistence,
            subject_registry=subject_registry,
        )
        session_registry = build_oa_session_registry_for_runtime(
            oa_persistence,
            membership_registry=membership_registry,
        )
        user_login_service = OaUserLoginService(
            credential_registry=credential_registry,
            session_registry=session_registry,
        )
        register_subject_registry_routes(oa_app, registry=subject_registry)
        register_local_credential_routes(oa_app, registry=credential_registry)
        register_identity_membership_routes(oa_app, registry=membership_registry)
        register_user_session_routes(oa_app, registry=session_registry)
        register_user_login_routes(oa_app, service=user_login_service)
        oa_client = TestClient(oa_app)
        oa_session_client = TestClientOaUserSessionClient(oa_client)

        ae_app = build_service_app(AE_SERVICE_SPEC)
        ae_persistence = attach_service_persistence_runtime(
            ae_app,
            AE_SERVICE_SPEC,
            environ={
                **env,
                AE_SERVICE_SPEC.database_env: ae_database_url,
                "NEX_AE_PERSISTENCE_MODE": "postgres",
            },
        )
        if ae_persistence.api_session_factory is None:
            raise RuntimeError("AE PostgreSQL session factory is unavailable")
        register_auth_session_routes(
            ae_app,
            oa_session_client=oa_session_client,
            session_mode=AUTH_SESSION_MODE_OA,
        )

        @ae_app.get("/smoke/v1/auth/protected", response_model=None)
        def protected_route(
            request: Request,
            authorization: str | None = Header(default=None),
        ) -> dict[str, Any] | JSONResponse:
            auth_context = authorize_ae_facade_route_request(
                request,
                authorization,
                oa_session_client=oa_session_client,
                session_mode=AUTH_SESSION_MODE_OA,
            )
            if isinstance(auth_context, JSONResponse):
                return auth_context
            return auth_context.to_wire()

        ae_client = TestClient(ae_app)

        membership_response = oa_client.post(
            "/internal/v1/identity/memberships/ensure",
            headers=_service_headers(trace_id=trace_id, request_id=request_id),
            json={
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "tenant_display_name": "AE OA Auth Smoke Tenant",
                "subject_display_name": "AE OA Auth Smoke User",
                "roles": ["employee", "smoke-tester"],
                "scopes": [DEFAULT_USER_SCOPE, "documents:read"],
                "membership_metadata": {"smoke_marker": "ae-oa-auth-postgres"},
            },
        )
        membership_response.raise_for_status()

        credential_response = oa_client.post(
            "/internal/v1/auth/local-credentials/ensure",
            headers=_service_headers(trace_id=trace_id, request_id=request_id),
            json={
                "tenant_id": tenant_id,
                "employee_id": employee_id,
                "subject_id": subject_id,
                "password": login_password,
                "credential_metadata": {"smoke_marker": "ae-oa-auth-postgres"},
            },
        )
        credential_response.raise_for_status()

        login_response = ae_client.post(
            "/api/v1/auth/session/login",
            headers=_ae_headers(trace_id=trace_id, request_id=request_id),
            json={
                "tenant_id": tenant_id,
                "employee_id": employee_id,
                "password": login_password,
                "scopes": [DEFAULT_USER_SCOPE],
                "ttl_seconds": 1800,
            },
        )
        login_response.raise_for_status()
        login = login_response.json()
        session_id = str(login["session_id"])
        cookie_set_after_login = SESSION_COOKIE_NAME in ae_client.cookies

        current_response = ae_client.get(
            "/api/v1/auth/session",
            headers=_ae_headers(trace_id=trace_id, request_id=request_id),
        )
        current_response.raise_for_status()
        current = current_response.json()

        protected_response = ae_client.get(
            "/smoke/v1/auth/protected",
            headers=_ae_headers(trace_id=trace_id, request_id=request_id),
        )
        protected_response.raise_for_status()
        protected = protected_response.json()

        logout_response = ae_client.post(
            "/api/v1/auth/session/logout",
            headers=_ae_headers(trace_id=trace_id, request_id=request_id),
        )
        logout_response.raise_for_status()
        logout = logout_response.json()
        cookie_present_after_logout = SESSION_COOKIE_NAME in ae_client.cookies

        current_after_logout_response = ae_client.get(
            "/api/v1/auth/session",
            headers=_ae_headers(trace_id=trace_id, request_id=request_id),
        )
        post_logout_introspection = oa_session_client.introspect_session(
            session_id,
            request_id=request_id,
            trace_id=trace_id,
        )
        db_observations = _db_observations(
            oa_engine,
            tenant_id=tenant_id,
            subject_id=subject_id,
            session_id=session_id,
        )
        ae_marker_rows = _count_ae_marker_rows(ae_engine, event_id=ae_marker_id)
        rendered = json.dumps(
            {
                "login": login,
                "current": current,
                "protected": protected,
                "logout": logout,
                "current_after_logout": _safe_response_json(current_after_logout_response),
                "post_logout_introspection": post_logout_introspection,
                "db_observations": db_observations,
                "adapter_calls": oa_session_client.calls,
            },
            ensure_ascii=False,
            default=str,
        )
        checks = {
            "ae_runtime_mode": ae_persistence.mode == "postgres",
            "oa_runtime_mode": oa_persistence.mode == "postgres",
            "ae_marker_write_readback": ae_marker_rows == 1,
            "membership_status_ok": membership_response.status_code == 200,
            "credential_status_ok": credential_response.status_code == 200,
            "login_status_ok": login_response.status_code == 200,
            "current_status_ok": current_response.status_code == 200,
            "protected_status_ok": protected_response.status_code == 200,
            "logout_status_ok": logout_response.status_code == 200,
            "current_after_logout_rejected": (
                current_after_logout_response.status_code == 401
            ),
            "cookie_set_after_login": cookie_set_after_login is True,
            "cookie_removed_after_logout": cookie_present_after_logout is False,
            "protected_owner_scope_claim_derived": (
                protected.get("auth_mode") == "browser_user"
                and protected.get("tenant_ref", {}).get("id") == tenant_id
                and protected.get("subject_ref", {}).get("id") == subject_id
            ),
            "current_session_matches_login": (
                current.get("session_id") == session_id
                and current.get("tenant_ref", {}).get("id") == tenant_id
                and current.get("subject_ref", {}).get("id") == subject_id
            ),
            "logout_revoked_session": logout.get("status") == "REVOKED",
            "oa_post_logout_inactive": (
                post_logout_introspection.get("active") is False
                and post_logout_introspection.get("inactive_reason") == "revoked"
            ),
            "oa_adapter_login_introspect_revoke_called": [
                call["operation"] for call in oa_session_client.calls
            ]
            == [
                "login_with_credentials",
                "introspect_session",
                "introspect_session",
                "revoke_session",
                "introspect_session",
            ],
            "login_password_verified": (
                bool(oa_session_client.calls)
                and oa_session_client.calls[0].get("password_verified") is True
            ),
            "membership_persisted": db_observations["membership_count"] == 1,
            "credential_persisted": db_observations["credential_count"] == 1,
            "session_persisted": db_observations["session_count"] == 1,
            "db_session_revoked": (
                db_observations.get("session_status") == "REVOKED"
                and db_observations.get("session_revoked_at") is not None
            ),
            "session_subject_matches": (
                db_observations.get("session_tenant_id") == tenant_id
                and db_observations.get("session_subject_id") == subject_id
            ),
            "raw_payload_absent": _redaction_safe(
                rendered,
                forbidden_fragments=[
                    SECRET_MARKER,
                    "access_token",
                    "Bearer ",
                    login_password,
                    SMOKE_LOGIN_PASSWORD,
                    "Nuri1004",
                    "nuri1004",
                    ae_database_url,
                    oa_database_url,
                ],
            ),
        }
        if not all(checks.values()):
            failed = ",".join(name for name, ok in checks.items() if not ok)
            raise RuntimeError(
                "AE OA auth PostgreSQL smoke checks failed: "
                f"{failed or 'unknown'}"
            )
        result = {
            "request_id": request_id,
            "trace_id": trace_id,
            "db_observations": {
                "ae_marker_rows": ae_marker_rows,
                "oa_membership_count": db_observations["membership_count"],
                "oa_credential_count": db_observations["credential_count"],
                "oa_session_count": db_observations["session_count"],
                "oa_session_status": db_observations["session_status"],
                "oa_session_revoked_at_present": (
                    db_observations["session_revoked_at"] is not None
                ),
            },
            "auth_observations": {
                "ae_auth_session_mode": AUTH_SESSION_MODE_OA,
                "ae_facade_auth_mode": protected["auth_mode"],
                "browser_cookie_name": SESSION_COOKIE_NAME,
                "browser_cookie_http_only": "httponly"
                in login_response.headers.get("set-cookie", "").lower(),
                "browser_cookie_material_in_evidence": False,
                "authorization_header_used_for_protected_route": False,
                "service_token_used_for_ae_facade": False,
                "owner_scope_authority": protected["owner_scope_authority"],
            },
            "adapter_observations": {
                "oa_client_operations": [
                    call["operation"] for call in oa_session_client.calls
                ],
            },
            "checks": checks,
        }
    finally:
        result["cleanup_observations"] = {
            "ae_marker_rows_after_delete": _delete_ae_smoke_marker(
                ae_engine,
                event_id=ae_marker_id,
            ),
            "oa_rows": _delete_oa_smoke_rows(
                oa_engine,
                tenant_id=tenant_id,
                subject_id=subject_id,
                employee_id=employee_id,
                session_id=session_id,
            ),
        }
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
        credential_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM oa_local_credentials
                WHERE tenant_id = :tenant_id
                  AND subject_id = :subject_id
                """
            ),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        ).scalar_one()
        session_row = connection.execute(
            text(
                """
                SELECT tenant_id, subject_id, status, revoked_at, scopes, roles
                FROM oa_user_sessions
                WHERE session_id = :session_id
                """
            ),
            {"session_id": session_id},
        ).mappings().first()
    return {
        "membership_count": int(membership_count),
        "credential_count": int(credential_count),
        "session_count": 1 if session_row is not None else 0,
        "session_tenant_id": session_row["tenant_id"] if session_row else None,
        "session_subject_id": session_row["subject_id"] if session_row else None,
        "session_status": session_row["status"] if session_row else None,
        "session_revoked_at": (
            str(session_row["revoked_at"])
            if session_row and session_row["revoked_at"]
            else None
        ),
        "session_scopes": _json_loads(session_row["scopes"]) if session_row else [],
        "session_roles": _json_loads(session_row["roles"]) if session_row else [],
    }


def _write_ae_smoke_marker(
    engine: Any,
    *,
    request_id: str,
    trace_id: str,
    subject_id: str,
) -> str:
    event_id = str(uuid4())
    details_expression = "CAST(:details AS jsonb)" if _is_postgresql(engine) else ":details"
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                INSERT INTO service_operational_events (
                    event_id,
                    service_id,
                    event_type,
                    severity,
                    trace_id,
                    request_id,
                    subject_type,
                    subject_id,
                    message,
                    details
                )
                VALUES (
                    :event_id,
                    'nex-ae-api',
                    'ae.auth.oa_postgres_smoke',
                    'INFO',
                    :trace_id,
                    :request_id,
                    'smoke',
                    :subject_id,
                    'AE OA auth PostgreSQL smoke marker.',
                    {details_expression}
                )
                """
            ),
            {
                "event_id": event_id,
                "trace_id": trace_id,
                "request_id": request_id,
                "subject_id": subject_id,
                "details": json.dumps(
                    {
                        "smoke_schema_version": SCHEMA_VERSION,
                        "test_database_marker": True,
                    },
                    sort_keys=True,
                ),
            },
        )
    return event_id


def _count_ae_marker_rows(engine: Any, *, event_id: str | None) -> int:
    if event_id is None:
        return 0
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM service_operational_events
                    WHERE event_id = :event_id
                      AND service_id = 'nex-ae-api'
                      AND event_type = 'ae.auth.oa_postgres_smoke'
                    """
                ),
                {"event_id": event_id},
            ).scalar_one()
        )


def _delete_ae_smoke_marker(engine: Any, *, event_id: str | None) -> int:
    if event_id is None:
        return 0
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_operational_events
                WHERE event_id = :event_id
                """
            ),
            {"event_id": event_id},
        )
    return _count_ae_marker_rows(engine, event_id=event_id)


def _delete_oa_smoke_rows(
    engine: Any,
    *,
    tenant_id: str,
    subject_id: str,
    employee_id: str,
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
        deleted_credentials = connection.execute(
            text(
                """
                DELETE FROM oa_local_credentials
                WHERE tenant_id = :tenant_id
                  AND (
                    subject_id = :subject_id
                    OR normalized_employee_id = lower(:employee_id)
                  )
                """
            ),
            {
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "employee_id": employee_id,
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
        "deleted_credentials": int(deleted_credentials),
        "deleted_memberships": int(deleted_memberships),
        "deleted_subjects": int(deleted_subjects),
        "deleted_tenants": int(deleted_tenants),
    }


def _service_headers(*, trace_id: str, request_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id=AE_SERVICE_ID, audience=OA_SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        "X-Request-ID": request_id,
        "X-Service-ID": AE_SERVICE_ID,
    }


def _ae_headers(*, trace_id: str, request_id: str) -> dict[str, str]:
    return {
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


def _require_test_database_url(database_url: str, *, env_name: str) -> None:
    try:
        parsed = make_url(database_url)
    except SQLAlchemyError as exc:
        raise ValueError(f"{env_name} is not a valid database URL.") from exc
    if not parsed.database or not parsed.database.endswith("_test"):
        raise ValueError(f"{env_name} must target a *_test database.")


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    protected_env_keys = (
        service_database_env(AE_SERVICE_ID, profile=DEFAULT_PROFILE),
        service_database_env(OA_SERVICE_ID, profile=DEFAULT_PROFILE),
        TENANT_ID_ENV,
        SUBJECT_ID_ENV,
        EMPLOYEE_ID_ENV,
        PASSWORD_ENV,
        SMOKE_PROFILE_ENV,
    )
    leaked = [
        key
        for key in protected_env_keys
        if _protected_env_value_leaked(serialized_evidence, environ.get(key))
    ]
    if leaked:
        raise ValueError(
            "AE OA auth PostgreSQL smoke evidence contains unredacted "
            f"environment value: {leaked[0]}"
        )


def _protected_env_value_leaked(serialized: str, value: str | None) -> bool:
    return bool(value and value not in {DEFAULT_PROFILE} and value in serialized)


def _safe_response_json(response: object) -> dict[str, Any]:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _redaction_safe(value: object, forbidden_fragments: list[str]) -> bool:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
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


def _is_postgresql(engine: Any) -> bool:
    return getattr(getattr(engine, "dialect", None), "name", "") == "postgresql"


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "services": [AE_SERVICE_ID, OA_SERVICE_ID],
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ae_oa_auth_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ae_oa_auth_postgres_smoke=pass "
            f"profile={evidence['profile']} "
            f"ae_db={evidence['database_envs']['ae']} "
            f"oa_db={evidence['database_envs']['oa']} "
            f"oa_session_status={evidence['db_observations']['oa_session_status']}"
        )
    return f"ae_oa_auth_postgres_smoke=fail reason={evidence.get('failure_code')}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE OA-backed auth PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_oa_auth_postgres_smoke()
    output = (
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, default=str)
    )
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
