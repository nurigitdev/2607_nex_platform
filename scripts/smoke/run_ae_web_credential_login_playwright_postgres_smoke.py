#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_runtime import load_env_file  # noqa: E402
from run_ae_web_playwright_readiness import (  # noqa: E402
    run_ae_web_playwright_readiness,
)
from run_ae_web_same_origin_runtime_boundary import (  # noqa: E402
    PROXY_TARGET_ENV,
    run_ae_web_same_origin_runtime_boundary,
)
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402


SCHEMA_VERSION = "ae_web_credential_login_playwright_postgres_smoke.v1"
NODE_SMOKE_SCHEMA_VERSION = "ae_web_credential_login_playwright_smoke.v1"
SMOKE_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE"
PROFILE_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_PROFILE"
TENANT_ID_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_TENANT_ID"
SUBJECT_ID_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_SUBJECT_ID"
EMPLOYEE_ID_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_EMPLOYEE_ID"
PASSWORD_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_PASSWORD"
CHROMIUM_EXECUTABLE_ENV = "NEX_AE_WEB_PLAYWRIGHT_CHROMIUM_EXECUTABLE"
TIMEOUT_MS_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_TIMEOUT_MS"
DEFAULT_PROFILE = "test"
DEFAULT_PASSWORD = "Nuri1004!"
WEB_ROOT = ROOT / "apps" / "nex-ae-web"
NODE_SMOKE_SCRIPT = WEB_ROOT / "scripts" / "runCredentialLoginPlaywrightSmoke.mjs"

ProtectedRunner = Callable[[dict[str, str]], dict[str, Any]]
NodeRunner = Callable[..., dict[str, Any]]
PortAllocator = Callable[[], int]

PROTECTED_ENV_KEYS = (
    base_auth.service_database_env(base_auth.AE_SERVICE_ID, profile=DEFAULT_PROFILE),
    base_auth.service_database_env(base_auth.OA_SERVICE_ID, profile=DEFAULT_PROFILE),
    TENANT_ID_ENV,
    SUBJECT_ID_ENV,
    EMPLOYEE_ID_ENV,
    PASSWORD_ENV,
    PROXY_TARGET_ENV,
)


@dataclass
class PreparedPlaywrightPostgresSmoke:
    profile: str
    request_id: str
    trace_id: str
    tenant_id: str
    subject_id: str
    employee_id: str
    password: str
    ae_database_env: str
    oa_database_env: str
    redacted_database_urls: dict[str, str]
    migrations: dict[str, dict[str, object]]
    ae_engine: Any
    oa_engine: Any
    ae_app: Any
    ae_marker_id: str | None

    def cleanup(self, *, session_id: str | None) -> dict[str, Any]:
        return {
            "ae_marker_rows_after_delete": base_auth._delete_ae_smoke_marker(
                self.ae_engine,
                event_id=self.ae_marker_id,
            ),
            "oa_rows": base_auth._delete_oa_smoke_rows(
                self.oa_engine,
                tenant_id=self.tenant_id,
                subject_id=self.subject_id,
                employee_id=self.employee_id,
                session_id=session_id,
            ),
        }


@dataclass
class StartedServer:
    url: str
    stop: Callable[[], None]


def run_ae_web_credential_login_playwright_postgres_smoke(
    environ: dict[str, str] | None = None,
    *,
    readiness_runner: ProtectedRunner = run_ae_web_playwright_readiness,
    boundary_runner: ProtectedRunner = run_ae_web_same_origin_runtime_boundary,
    prepare_runner: Callable[
        [dict[str, str], str],
        PreparedPlaywrightPostgresSmoke,
    ] = lambda env, profile: prepare_playwright_postgres_smoke(env, profile=profile),
    node_runner: NodeRunner | None = None,
    session_observer: Callable[..., dict[str, Any]] | None = None,
    port_allocator: PortAllocator | None = None,
    api_server_starter: Callable[[Any, int], StartedServer] | None = None,
    web_server_starter: Callable[[int, str], StartedServer] | None = None,
) -> dict[str, Any]:
    node_runner = node_runner or run_node_playwright_smoke
    session_observer = session_observer or latest_session_observations
    port_allocator = port_allocator or find_free_port
    api_server_starter = api_server_starter or start_api_server
    web_server_starter = web_server_starter or start_web_server
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        }

    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure("profile_not_allowed", profile=profile, env=env)

    readiness = readiness_runner(env)
    if readiness["status"] != "PASS":
        return _failure("readiness_failed", profile=profile, env=env, readiness=readiness)

    prepared: PreparedPlaywrightPostgresSmoke | None = None
    api_server: StartedServer | None = None
    web_server: StartedServer | None = None
    evidence: dict[str, Any] | None = None
    session_observations: dict[str, Any] = {}
    cleanup_observations: dict[str, Any] = {}
    try:
        prepared = prepare_runner(dict(env), profile)
        api_port = port_allocator()
        web_port = port_allocator()
        api_server = api_server_starter(prepared.ae_app, api_port)
        web_server = web_server_starter(web_port, api_server.url)
        boundary_env = {**env, PROXY_TARGET_ENV: api_server.url}
        boundary = boundary_runner(boundary_env)
        if boundary["status"] != "PASS":
            return _failure(
                "same_origin_boundary_failed",
                profile=profile,
                env=boundary_env,
                readiness=readiness,
                boundary=boundary,
            )
        node_env = _node_environ(
            env,
            web_url=web_server.url,
            tenant_id=prepared.tenant_id,
            employee_id=prepared.employee_id,
            password=prepared.password,
        )
        node_smoke = node_runner(node_env)
        session_observations = session_observer(
            prepared.oa_engine,
            tenant_id=prepared.tenant_id,
            subject_id=prepared.subject_id,
        )
        evidence = _pass_or_fail_evidence(
            profile=profile,
            env={**env, PROXY_TARGET_ENV: api_server.url},
            readiness=readiness,
            boundary=boundary,
            prepared=prepared,
            node_smoke=node_smoke,
            session_observations=session_observations,
        )
        return evidence
    except (base_auth.MigrationError, ValueError) as exc:
        return _failure(
            "configuration_invalid",
            profile=profile,
            env=env,
            detail=exc.__class__.__name__,
        )
    except Exception as exc:
        return _failure(
            "execution_failed",
            profile=profile,
            env=env,
            detail=exc.__class__.__name__,
        )
    finally:
        if web_server is not None:
            web_server.stop()
        if api_server is not None:
            api_server.stop()
        if prepared is not None:
            cleanup_observations = prepared.cleanup(
                session_id=session_observations.get("session_id")
            )
            if cleanup_observations and evidence is not None:
                evidence["cleanup_observations"] = cleanup_observations


def prepare_playwright_postgres_smoke(
    env: dict[str, str],
    *,
    profile: str,
) -> PreparedPlaywrightPostgresSmoke:  # pragma: no cover - protected live DB path
    ae_database_env = base_auth.service_database_env(
        base_auth.AE_SERVICE_ID,
        profile=profile,
    )
    oa_database_env = base_auth.service_database_env(
        base_auth.OA_SERVICE_ID,
        profile=profile,
    )
    ae_database_url = base_auth.service_database_url(
        base_auth.AE_SERVICE_ID,
        profile=profile,
        environ=env,
    )
    oa_database_url = base_auth.service_database_url(
        base_auth.OA_SERVICE_ID,
        profile=profile,
        environ=env,
    )
    base_auth._require_test_database_url(ae_database_url, env_name=ae_database_env)
    base_auth._require_test_database_url(oa_database_url, env_name=oa_database_env)
    ae_migration = base_auth.run_service_migrations(
        base_auth.AE_SERVICE_ID,
        database_url=ae_database_url,
        profile=profile,
    )
    oa_migration = base_auth.run_service_migrations(
        base_auth.OA_SERVICE_ID,
        database_url=oa_database_url,
        profile=profile,
    )
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.split("-", maxsplit=1)[0]
    tenant_id = env.get(TENANT_ID_ENV) or f"tenant-ae-web-pw-{suffix}"
    subject_id = env.get(SUBJECT_ID_ENV) or f"user-ae-web-pw-{suffix}"
    employee_id = env.get(EMPLOYEE_ID_ENV) or f"EMP-AE-WEB-PW-{suffix}"
    password = env.get(PASSWORD_ENV) or DEFAULT_PASSWORD
    ae_engine = base_auth.build_engine(ae_database_url)
    oa_engine = base_auth.build_engine(oa_database_url)
    ae_marker_id = base_auth._write_ae_smoke_marker(
        ae_engine,
        request_id=request_id,
        trace_id=trace_id,
        subject_id=subject_id,
    )
    try:
        oa_app = build_oa_app(
            env=env,
            oa_database_url=oa_database_url,
            trace_id=trace_id,
            request_id=request_id,
            tenant_id=tenant_id,
            subject_id=subject_id,
            employee_id=employee_id,
            password=password,
        )
        oa_client = TestClient(oa_app)
        oa_session_client = base_auth.TestClientOaUserSessionClient(oa_client)
        ae_app = build_ae_app(
            env=env,
            ae_database_url=ae_database_url,
            oa_session_client=oa_session_client,
        )
        return PreparedPlaywrightPostgresSmoke(
            profile=profile,
            request_id=request_id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            subject_id=subject_id,
            employee_id=employee_id,
            password=password,
            ae_database_env=ae_database_env,
            oa_database_env=oa_database_env,
            redacted_database_urls={
                "ae": base_auth.redact_database_url(ae_database_url),
                "oa": base_auth.redact_database_url(oa_database_url),
            },
            migrations={
                "ae": base_auth._migration_evidence(ae_migration),
                "oa": base_auth._migration_evidence(oa_migration),
            },
            ae_engine=ae_engine,
            oa_engine=oa_engine,
            ae_app=ae_app,
            ae_marker_id=ae_marker_id,
        )
    except Exception:
        base_auth._delete_ae_smoke_marker(ae_engine, event_id=ae_marker_id)
        base_auth._delete_oa_smoke_rows(
            oa_engine,
            tenant_id=tenant_id,
            subject_id=subject_id,
            employee_id=employee_id,
            session_id=None,
        )
        raise


def build_oa_app(
    *,
    env: Mapping[str, str],
    oa_database_url: str,
    trace_id: str,
    request_id: str,
    tenant_id: str,
    subject_id: str,
    employee_id: str,
    password: str,
) -> Any:  # pragma: no cover - protected live DB path
    oa_app = base_auth.build_service_app(base_auth.OA_SERVICE_SPEC)
    oa_persistence = base_auth.attach_service_persistence_runtime(
        oa_app,
        base_auth.OA_SERVICE_SPEC,
        environ={
            **env,
            base_auth.OA_SERVICE_SPEC.database_env: oa_database_url,
            "NEX_OA_PERSISTENCE_MODE": "postgres",
        },
    )
    if oa_persistence.api_session_factory is None:
        raise RuntimeError("OA PostgreSQL session factory is unavailable")
    subject_registry = base_auth.build_subject_registry_for_runtime(oa_persistence)
    membership_registry = base_auth.build_tenant_membership_registry_for_runtime(
        oa_persistence,
        subject_registry=subject_registry,
    )
    credential_registry = base_auth.build_credential_registry_for_runtime(
        oa_persistence,
        subject_registry=subject_registry,
    )
    session_registry = base_auth.build_oa_session_registry_for_runtime(
        oa_persistence,
        membership_registry=membership_registry,
    )
    user_login_service = base_auth.OaUserLoginService(
        credential_registry=credential_registry,
        session_registry=session_registry,
    )
    base_auth.register_subject_registry_routes(oa_app, registry=subject_registry)
    base_auth.register_local_credential_routes(oa_app, registry=credential_registry)
    base_auth.register_identity_membership_routes(
        oa_app,
        registry=membership_registry,
    )
    base_auth.register_user_session_routes(oa_app, registry=session_registry)
    base_auth.register_user_login_routes(oa_app, service=user_login_service)
    oa_client = TestClient(oa_app)
    headers = base_auth._service_headers(trace_id=trace_id, request_id=request_id)
    membership_response = oa_client.post(
        "/internal/v1/identity/memberships/ensure",
        headers=headers,
        json={
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "tenant_display_name": "AE Web Playwright Smoke Tenant",
            "subject_display_name": "AE Web Playwright Smoke User",
            "roles": ["employee", "smoke-tester"],
            "scopes": [
                base_auth.DEFAULT_USER_SCOPE,
                "documents:read",
                "documents:upload",
            ],
            "membership_metadata": {"smoke_marker": "ae-web-playwright-postgres"},
        },
    )
    membership_response.raise_for_status()
    credential_response = oa_client.post(
        "/internal/v1/auth/local-credentials/ensure",
        headers=headers,
        json={
            "tenant_id": tenant_id,
            "employee_id": employee_id,
            "subject_id": subject_id,
            "password": password,
            "credential_metadata": {"smoke_marker": "ae-web-playwright-postgres"},
        },
    )
    credential_response.raise_for_status()
    return oa_app


def build_ae_app(
    *,
    env: Mapping[str, str],
    ae_database_url: str,
    oa_session_client: Any,
) -> Any:  # pragma: no cover - protected live DB path
    ae_app = base_auth.build_service_app(base_auth.AE_SERVICE_SPEC)
    ae_persistence = base_auth.attach_service_persistence_runtime(
        ae_app,
        base_auth.AE_SERVICE_SPEC,
        environ={
            **env,
            base_auth.AE_SERVICE_SPEC.database_env: ae_database_url,
            "NEX_AE_PERSISTENCE_MODE": "postgres",
        },
    )
    if ae_persistence.api_session_factory is None:
        raise RuntimeError("AE PostgreSQL session factory is unavailable")
    base_auth.register_auth_session_routes(
        ae_app,
        oa_session_client=oa_session_client,
        session_mode=base_auth.AUTH_SESSION_MODE_OA,
    )
    return ae_app


def start_api_server(app: Any, port: int) -> StartedServer:  # pragma: no cover
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    wait_for_url(f"{url}/health")

    def stop() -> None:
        server.should_exit = True
        thread.join(timeout=5)

    return StartedServer(url=url, stop=stop)


def start_web_server(port: int, api_target_url: str) -> StartedServer:  # pragma: no cover
    env = {
        **os.environ,
        "PORT": str(port),
        PROXY_TARGET_ENV: api_target_url,
    }
    process = subprocess.Popen(
        ["npm", "--prefix", str(WEB_ROOT), "run", "dev"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        wait_for_url(url)
    except Exception:
        stop_process(process)
        raise

    return StartedServer(url=f"{url}/", stop=lambda: stop_process(process))


def run_node_playwright_smoke(env: Mapping[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        ["node", str(NODE_SMOKE_SCRIPT)],
        cwd=ROOT,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        if completed.returncode != 0:
            return {
                "smoke_schema_version": NODE_SMOKE_SCHEMA_VERSION,
                "status": "FAIL",
                "failure_code": "node_playwright_failed",
                "returncode": completed.returncode,
            }
        return {
            "smoke_schema_version": NODE_SMOKE_SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "node_json_invalid",
            "returncode": completed.returncode,
        }
    if isinstance(payload, dict):
        payload.setdefault("returncode", completed.returncode)
        return payload
    return {
        "smoke_schema_version": NODE_SMOKE_SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "node_payload_invalid",
    }


def latest_session_observations(
    engine: Any,
    *,
    tenant_id: str,
    subject_id: str,
) -> dict[str, Any]:
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
                SELECT session_id, tenant_id, subject_id, status, revoked_at
                FROM oa_user_sessions
                WHERE tenant_id = :tenant_id
                  AND subject_id = :subject_id
                ORDER BY issued_at DESC
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        ).mappings().first()
    if session_row is None:
        return {
            "session_id": None,
            "membership_count": int(membership_count),
            "credential_count": int(credential_count),
            "session_count": 0,
            "session_status": None,
            "session_revoked_at_present": False,
            "session_subject_matches": False,
        }
    db_observations = base_auth._db_observations(
        engine,
        tenant_id=tenant_id,
        subject_id=subject_id,
        session_id=session_row["session_id"],
    )
    return {
        "session_id": session_row["session_id"],
        "membership_count": db_observations["membership_count"],
        "credential_count": db_observations["credential_count"],
        "session_count": db_observations["session_count"],
        "session_status": db_observations["session_status"],
        "session_revoked_at_present": db_observations["session_revoked_at"] is not None,
        "session_subject_matches": (
            db_observations["session_tenant_id"] == tenant_id
            and db_observations["session_subject_id"] == subject_id
        ),
    }


def _pass_or_fail_evidence(
    *,
    profile: str,
    env: Mapping[str, str],
    readiness: Mapping[str, Any],
    boundary: Mapping[str, Any],
    prepared: PreparedPlaywrightPostgresSmoke,
    node_smoke: Mapping[str, Any],
    session_observations: Mapping[str, Any],
) -> dict[str, Any]:
    node_checks = _mapping(node_smoke.get("checks"))
    checks = {
        "readiness_passed": readiness.get("status") == "PASS",
        "same_origin_boundary_passed": boundary.get("status") == "PASS",
        "node_playwright_smoke_passed": node_smoke.get("status") == "PASS",
        "playwright_browser_launched": (
            node_checks.get("playwright_browser_launched") is True
        ),
        "same_origin_login_called": node_checks.get("same_origin_login_called") is True,
        "same_origin_logout_called": node_checks.get("same_origin_logout_called") is True,
        "browser_route_guard_allowed": (
            node_checks.get("route_guard_allowed_after_login") is True
        ),
        "browser_logout_completed": (
            node_checks.get("logout_feedback_logged_out") is True
        ),
        "ae_test_database_connected": (
            base_auth._count_ae_marker_rows(
                prepared.ae_engine,
                event_id=prepared.ae_marker_id,
            )
            == 1
        ),
        "oa_membership_persisted": session_observations.get("membership_count") == 1,
        "oa_credential_persisted": session_observations.get("credential_count") == 1,
        "oa_session_persisted": session_observations.get("session_count") == 1,
        "oa_session_revoked": (
            session_observations.get("session_status") == "REVOKED"
            and session_observations.get("session_revoked_at_present") is True
        ),
        "oa_session_subject_matches": (
            session_observations.get("session_subject_matches") is True
        ),
        "redacted_evidence": True,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": status,
        "profile": profile,
        "services": ["nex-ae-web", base_auth.AE_SERVICE_ID, base_auth.OA_SERVICE_ID],
        "source_smokes": {
            "playwright_readiness": {
                "schema_version": readiness.get("readiness_schema_version"),
                "status": readiness.get("status"),
            },
            "same_origin_boundary": {
                "schema_version": boundary.get("boundary_schema_version"),
                "status": boundary.get("status"),
            },
            "node_playwright": {
                "schema_version": node_smoke.get("smoke_schema_version"),
                "status": node_smoke.get("status"),
                "failure_code": node_smoke.get("failure_code"),
                "detail": _mapping(node_smoke.get("detail")),
            },
        },
        "database_envs": {
            "ae": prepared.ae_database_env,
            "oa": prepared.oa_database_env,
        },
        "redacted_database_urls": prepared.redacted_database_urls,
        "migrations": prepared.migrations,
        "request_id": prepared.request_id,
        "trace_id": prepared.trace_id,
        "browser_observations": _mapping(node_smoke.get("browser_observations")),
        "request_observations": _mapping(node_smoke.get("request_observations")),
        "db_observations": {
            "ae_marker_rows": 1 if checks["ae_test_database_connected"] else 0,
            "oa_membership_count": session_observations.get("membership_count", 0),
            "oa_credential_count": session_observations.get("credential_count", 0),
            "oa_session_count": session_observations.get("session_count", 0),
            "oa_session_status": session_observations.get("session_status"),
            "oa_session_revoked_at_present": session_observations.get(
                "session_revoked_at_present",
                False,
            ),
        },
        "checks": checks,
        "issues": [
            {"category": "check_failed", "subject": name}
            for name, passed in checks.items()
            if not passed
        ],
        "redaction": {
            "raw_password_in_evidence": False,
            "cookie_material_in_evidence": False,
            "token_material_in_evidence": False,
            "database_endpoint_in_evidence": False,
            "provider_endpoint_in_evidence": False,
        },
    }
    assert_smoke_evidence_redacted(
        json.dumps(evidence, ensure_ascii=False, default=str),
        env,
    )
    return evidence


def _failure(
    failure_code: str,
    *,
    profile: str,
    env: Mapping[str, str],
    detail: str | None = None,
    readiness: Mapping[str, Any] | None = None,
    boundary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
        "source_smokes": {
            "playwright_readiness": _source_status(
                readiness,
                version_key="readiness_schema_version",
            ),
            "same_origin_boundary": _source_status(
                boundary,
                version_key="boundary_schema_version",
            ),
        },
        "checks": {
            "redacted_evidence": True,
        },
    }
    assert_smoke_evidence_redacted(
        json.dumps(evidence, ensure_ascii=False, default=str),
        env,
    )
    return evidence


def _node_environ(
    env: Mapping[str, str],
    *,
    web_url: str,
    tenant_id: str,
    employee_id: str,
    password: str,
) -> dict[str, str]:
    node_env = {
        "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_WEB_URL": web_url,
        "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_TENANT_ID": tenant_id,
        "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_EMPLOYEE_ID": employee_id,
        "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_PASSWORD": password,
    }
    if env.get(CHROMIUM_EXECUTABLE_ENV):
        node_env[CHROMIUM_EXECUTABLE_ENV] = env[CHROMIUM_EXECUTABLE_ENV]
    if env.get(TIMEOUT_MS_ENV):
        node_env[TIMEOUT_MS_ENV] = env[TIMEOUT_MS_ENV]
    return node_env


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    leaked = [
        key
        for key in PROTECTED_ENV_KEYS
        if _protected_env_value_leaked(serialized_evidence, environ.get(key))
    ]
    if leaked:
        raise ValueError(
            "AE Web Playwright PostgreSQL smoke evidence contains "
            f"unredacted environment value: {leaked[0]}"
        )


def _protected_env_value_leaked(serialized: str, value: str | None) -> bool:
    return bool(value and value not in {DEFAULT_PROFILE, "1"} and value in serialized)


def _source_status(
    evidence: Mapping[str, Any] | None,
    *,
    version_key: str,
) -> dict[str, Any]:
    if evidence is None:
        return {"status": "NOT_RUN"}
    source = {"status": evidence.get("status", "UNKNOWN")}
    if version_key in evidence:
        source["schema_version"] = evidence.get(version_key)
    return source


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def find_free_port() -> int:  # pragma: no cover
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_url(url: str, *, timeout_seconds: float = 15.0) -> None:  # pragma: no cover
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status < 500:
                    return
        except (OSError, URLError) as exc:
            last_error = exc
            time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for {url}: {last_error}")


def stop_process(process: subprocess.Popen[bytes]) -> None:  # pragma: no cover
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def write_smoke_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    assert_smoke_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ae_web_credential_login_playwright_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        db = _mapping(evidence.get("db_observations"))
        browser = _mapping(evidence.get("browser_observations"))
        return (
            "ae_web_credential_login_playwright_postgres_smoke=pass "
            f"profile={evidence['profile']} "
            f"route_guard={browser.get('route_guard_status_after_login')} "
            f"oa_session_status={db.get('oa_session_status')} "
            "live_db=true browser=playwright"
        )
    return (
        "ae_web_credential_login_playwright_postgres_smoke=fail "
        f"reason={evidence.get('failure_code', 'checks_failed')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run protected AE Web Playwright credential-login PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_env_file(ROOT / ".env.local")
        evidence = run_ae_web_credential_login_playwright_postgres_smoke()
        if args.output:
            write_smoke_evidence(args.output, evidence)
        print(
            summary_line(evidence)
            if args.summary
            else json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
        )
        return 1 if evidence["status"] == "FAIL" else 0
    except ValueError as exc:
        print(
            "ae_web_credential_login_playwright_postgres_smoke=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
