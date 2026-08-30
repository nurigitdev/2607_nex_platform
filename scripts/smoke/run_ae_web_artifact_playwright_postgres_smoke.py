#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping
from uuid import uuid4

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
SMOKE_PATH = ROOT / "scripts" / "smoke"
AE_PATH = ROOT / "services" / "nex-ae-api"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(SMOKE_PATH))
sys.path.insert(0, str(AE_PATH))

from nex_ae_api.artifacts import (  # noqa: E402
    LocalRenderedArtifactStorage,
    register_artifact_handoff_routes,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_ae_web_playwright_readiness import (  # noqa: E402
    run_ae_web_playwright_readiness,
)
from run_ae_web_same_origin_runtime_boundary import PROXY_TARGET_ENV  # noqa: E402
from run_ae_web_same_origin_runtime_boundary import (  # noqa: E402
    run_ae_web_same_origin_runtime_boundary,
)
import run_ae_artifact_postgres_smoke as artifact_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
import run_ae_web_artifact_postgres_smoke as web_artifact_pg  # noqa: E402
import run_ae_web_credential_login_playwright_postgres_smoke as login_pg  # noqa: E402


SCHEMA_VERSION = "ae_web_artifact_playwright_postgres_smoke.v1"
NODE_SMOKE_SCHEMA_VERSION = "ae_web_artifact_playwright_smoke.v1"
SMOKE_ENV = "NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_POSTGRES_SMOKE_PROFILE"
CHROMIUM_EXECUTABLE_ENV = "NEX_AE_WEB_PLAYWRIGHT_CHROMIUM_EXECUTABLE"
TIMEOUT_MS_ENV = "NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_SMOKE_TIMEOUT_MS"
DEFAULT_PROFILE = "test"
SERVICE_ID = artifact_pg.SERVICE_ID
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
WEB_ROOT = ROOT / "apps" / "nex-ae-web"
NODE_SMOKE_SCRIPT = WEB_ROOT / "scripts" / "runArtifactPlaywrightSmoke.mjs"

ProtectedRunner = Callable[[dict[str, str]], dict[str, Any]]
NodeRunner = Callable[[Mapping[str, str]], dict[str, Any]]
PortAllocator = Callable[[], int]

PROTECTED_ENV_KEYS = (
    artifact_pg.service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE),
    PROXY_TARGET_ENV,
)


@dataclass
class PreparedArtifactPlaywrightPostgresSmoke:
    profile: str
    request_id: str
    trace_id: str
    database_env: str
    redacted_database_url: str
    migration: dict[str, object]
    engine: Any
    ae_app: Any
    artifact_handoff_id: str
    artifact_id: str
    artifact_version_id: str
    render_job_id: str
    artifact_file_id: str
    markdown_file_count: int
    db_observations: dict[str, Any]
    storage_tempdir: tempfile.TemporaryDirectory[str]

    def cleanup(self) -> dict[str, Any]:
        deleted = artifact_pg._cleanup_smoke_rows(
            self.engine,
            artifact_id=self.artifact_id,
            artifact_handoff_id=self.artifact_handoff_id,
        )
        self.storage_tempdir.cleanup()
        return deleted


def run_ae_web_artifact_playwright_postgres_smoke(
    environ: dict[str, str] | None = None,
    *,
    readiness_runner: ProtectedRunner = run_ae_web_playwright_readiness,
    web_postgres_runner: ProtectedRunner = (
        web_artifact_pg.run_ae_web_artifact_postgres_smoke
    ),
    boundary_runner: ProtectedRunner = run_ae_web_same_origin_runtime_boundary,
    prepare_runner: Callable[
        [dict[str, str], str],
        PreparedArtifactPlaywrightPostgresSmoke,
    ] = lambda env, profile: prepare_artifact_playwright_postgres_smoke(
        env,
        profile=profile,
    ),
    node_runner: NodeRunner | None = None,
    artifact_observer: Callable[..., dict[str, Any]] | None = None,
    port_allocator: PortAllocator | None = None,
    api_server_starter: Callable[[Any, int], login_pg.StartedServer] | None = None,
    web_server_starter: Callable[[int, str], login_pg.StartedServer] | None = None,
) -> dict[str, Any]:
    node_runner = node_runner or run_node_playwright_artifact_smoke
    artifact_observer = artifact_observer or latest_artifact_observations
    port_allocator = port_allocator or login_pg.find_free_port
    api_server_starter = api_server_starter or login_pg.start_api_server
    web_server_starter = web_server_starter or login_pg.start_web_server
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

    web_postgres_env = dict(env)
    web_postgres_env[web_artifact_pg.SMOKE_ENV] = "1"
    web_postgres_env[web_artifact_pg.SMOKE_PROFILE_ENV] = profile
    web_postgres = web_postgres_runner(web_postgres_env)
    if web_postgres["status"] != "PASS":
        return _failure(
            "web_artifact_postgres_failed",
            profile=profile,
            env=web_postgres_env,
            readiness=readiness,
            web_postgres=web_postgres,
            detail=_safe_source_detail(web_postgres),
        )

    prepared: PreparedArtifactPlaywrightPostgresSmoke | None = None
    api_server: login_pg.StartedServer | None = None
    web_server: login_pg.StartedServer | None = None
    evidence: dict[str, Any] | None = None
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
                web_postgres=web_postgres,
                boundary=boundary,
            )

        node_smoke = node_runner(
            _node_environ(
                env,
                web_url=web_server.url,
                artifact_id=prepared.artifact_id,
                artifact_file_id=prepared.artifact_file_id,
            )
        )
        artifact_observations = artifact_observer(
            prepared.engine,
            artifact_id=prepared.artifact_id,
            artifact_handoff_id=prepared.artifact_handoff_id,
            artifact_version_id=prepared.artifact_version_id,
            render_job_id=prepared.render_job_id,
            artifact_file_id=prepared.artifact_file_id,
        )
        evidence = _pass_or_fail_evidence(
            profile=profile,
            env={**env, PROXY_TARGET_ENV: api_server.url},
            readiness=readiness,
            web_postgres=web_postgres,
            boundary=boundary,
            prepared=prepared,
            node_smoke=node_smoke,
            artifact_observations=artifact_observations,
        )
        return evidence
    except (artifact_pg.MigrationError, ValueError) as exc:
        return _failure(
            "configuration_invalid",
            profile=profile,
            env=env,
            detail=exc.__class__.__name__,
            readiness=readiness,
            web_postgres=web_postgres,
        )
    except Exception as exc:
        return _failure(
            "execution_failed",
            profile=profile,
            env=env,
            detail=exc.__class__.__name__,
            readiness=readiness,
            web_postgres=web_postgres,
        )
    finally:
        if web_server is not None:
            web_server.stop()
        if api_server is not None:
            api_server.stop()
        if prepared is not None:
            cleanup_observations = prepared.cleanup()
            if cleanup_observations and evidence is not None:
                evidence["cleanup_observations"] = cleanup_observations
            prepared.engine.dispose()


def prepare_artifact_playwright_postgres_smoke(
    env: dict[str, str],
    *,
    profile: str,
) -> PreparedArtifactPlaywrightPostgresSmoke:  # pragma: no cover
    database_env = artifact_pg.service_database_env(SERVICE_ID, profile=profile)
    database_url = artifact_pg.service_database_url(
        SERVICE_ID,
        profile=profile,
        environ=env,
    )
    base_auth._require_test_database_url(database_url, env_name=database_env)
    migration = artifact_pg.run_service_migrations(
        SERVICE_ID,
        database_url=database_url,
        profile=profile,
    )
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    storage_tempdir = tempfile.TemporaryDirectory(
        prefix="nex-ae-web-artifact-playwright-smoke-"
    )
    storage_root = Path(storage_tempdir.name) / "artifact-storage"
    engine = build_engine(database_url)
    artifact_handoff_id: str | None = None
    artifact_id: str | None = None
    try:
        session_factory = build_session_factory(engine)
        ae_app = build_ae_artifact_app(
            env=env,
            session_factory=session_factory,
            storage_root=storage_root,
            suffix=suffix,
            request_id=request_id,
            trace_id=trace_id,
        )
        client = TestClient(ae_app)
        headers = artifact_pg._auth_headers(request_id=request_id, trace_id=trace_id)

        handoff_response = client.post(
            "/api/v1/artifact-handoffs",
            json=artifact_pg._artifact_handoff_payload(suffix),
            headers={
                **headers,
                "Idempotency-Key": f"artifact-handoff-playwright-{suffix}",
            },
        )
        handoff_response.raise_for_status()
        artifact_handoff_id = handoff_response.json()["artifact_handoff_id"]
        artifact_response = client.post(
            "/api/v1/artifacts",
            json={"artifact_handoff_id": artifact_handoff_id},
            headers={
                **headers,
                "Idempotency-Key": f"artifact-playwright-{suffix}",
            },
        )
        artifact_response.raise_for_status()
        artifact = artifact_response.json()
        artifact_id = artifact["artifact_id"]
        render_response = client.post(
            f"/api/v1/artifacts/{artifact_id}/render-jobs",
            json={},
            headers={
                **headers,
                "Idempotency-Key": f"artifact-render-playwright-{suffix}",
            },
        )
        render_response.raise_for_status()
        rendered = render_response.json()
        rendered_artifact = rendered["artifact"]
        render_job = rendered["render_job"]
        artifact_version_id = rendered_artifact["current_version_id"]
        artifact_file_id = rendered_artifact["files"][0]["artifact_file_id"]
        db_observations = latest_artifact_observations(
            engine,
            artifact_id=artifact_id,
            artifact_handoff_id=artifact_handoff_id,
            artifact_version_id=artifact_version_id,
            render_job_id=render_job["render_job_id"],
            artifact_file_id=artifact_file_id,
        )
        markdown_file_count = sum(1 for _ in storage_root.rglob("*.md"))
        return PreparedArtifactPlaywrightPostgresSmoke(
            profile=profile,
            request_id=request_id,
            trace_id=trace_id,
            database_env=database_env,
            redacted_database_url=redact_database_url(database_url),
            migration=base_auth._migration_evidence(migration),
            engine=engine,
            ae_app=ae_app,
            artifact_handoff_id=artifact_handoff_id,
            artifact_id=artifact_id,
            artifact_version_id=artifact_version_id,
            render_job_id=render_job["render_job_id"],
            artifact_file_id=artifact_file_id,
            markdown_file_count=markdown_file_count,
            db_observations=db_observations,
            storage_tempdir=storage_tempdir,
        )
    except Exception:
        artifact_pg._cleanup_smoke_rows(
            engine,
            artifact_id=artifact_id,
            artifact_handoff_id=artifact_handoff_id,
        )
        storage_tempdir.cleanup()
        engine.dispose()
        raise


def build_ae_artifact_app(
    *,
    env: Mapping[str, str],
    session_factory: Any,
    storage_root: Path,
    suffix: str,
    request_id: str,
    trace_id: str,
) -> Any:  # pragma: no cover
    app = build_service_app(SERVICE_SPEC)
    app.state.nex_persistence = SimpleNamespace(api_session_factory=session_factory)
    cx_client = artifact_pg.FakeCxArtifactSourceClient(
        suffix=suffix,
        request_id=request_id,
        trace_id=trace_id,
    )
    install_playwright_service_auth_middleware(app)
    with artifact_pg._temporary_env("NEX_AE_ARTIFACT_STORAGE_ROOT", str(storage_root)):
        register_artifact_handoff_routes(app, cx_client=cx_client, artifact_store=None)
    return app


def install_playwright_service_auth_middleware(app: Any) -> None:
    token = issue_mock_service_token(service_id="nex-ag", audience=SERVICE_ID).access_token

    @app.middleware("http")
    async def add_artifact_service_auth(request, call_next):  # type: ignore[no-untyped-def]
        path = request.scope.get("path", "")
        if _is_artifact_browser_path(path) and not _has_header(
            request.scope.get("headers", []),
            b"authorization",
        ):
            request.scope["headers"] = [
                *request.scope.get("headers", []),
                (b"authorization", f"Bearer {token}".encode("latin-1")),
                (b"x-service-id", b"nex-ag"),
            ]
        return await call_next(request)


def latest_artifact_observations(
    engine: Any,
    *,
    artifact_id: str,
    artifact_handoff_id: str,
    artifact_version_id: str,
    render_job_id: str,
    artifact_file_id: str,
) -> dict[str, Any]:
    raw = artifact_pg._db_observations(
        engine,
        artifact_handoff_id=artifact_handoff_id,
        artifact_id=artifact_id,
        artifact_version_id=artifact_version_id,
        render_job_id=render_job_id,
        artifact_file_id=artifact_file_id,
    )
    return {
        "row_counts": dict(raw.get("row_counts", {})),
        "migration_recorded": raw.get("migration_recorded") is True,
        "tables_present_count": len(raw.get("tables_present", [])),
        "indexes_present_count": len(raw.get("indexes_present", [])),
        "logical_storage_ref_present": bool(raw.get("storage_ref")),
        "jsonb_column_count": len(raw.get("jsonb_columns", {})),
        "handoff_correlation_columns_present": raw.get(
            "handoff_correlation_columns"
        )
        == list(artifact_pg.EXPECTED_HANDOFF_CORRELATION_COLUMNS),
    }


def run_node_playwright_artifact_smoke(env: Mapping[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        ["node", str(NODE_SMOKE_SCRIPT)],
        cwd=ROOT,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=120,
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


def _pass_or_fail_evidence(
    *,
    profile: str,
    env: Mapping[str, str],
    readiness: Mapping[str, Any],
    web_postgres: Mapping[str, Any],
    boundary: Mapping[str, Any],
    prepared: PreparedArtifactPlaywrightPostgresSmoke,
    node_smoke: Mapping[str, Any],
    artifact_observations: Mapping[str, Any],
) -> dict[str, Any]:
    node_checks = _mapping(node_smoke.get("checks"))
    row_counts = dict(artifact_observations.get("row_counts", {}))
    checks = {
        "playwright_readiness_passed": readiness.get("status") == "PASS",
        "web_artifact_postgres_passed": web_postgres.get("status") == "PASS",
        "same_origin_boundary_passed": boundary.get("status") == "PASS",
        "node_playwright_smoke_passed": node_smoke.get("status") == "PASS",
        "playwright_browser_launched": (
            node_checks.get("playwright_browser_launched") is True
        ),
        "browser_artifact_detail_called": (
            node_checks.get("artifact_detail_called") is True
        ),
        "browser_artifact_versions_called": (
            node_checks.get("artifact_versions_called") is True
        ),
        "browser_artifact_file_metadata_called": (
            node_checks.get("artifact_file_metadata_called") is True
        ),
        "browser_artifact_preview_called": (
            node_checks.get("artifact_preview_called") is True
        ),
        "browser_artifact_download_called": (
            node_checks.get("artifact_download_called") is True
        ),
        "browser_request_secret_header_absent": (
            node_checks.get("browser_request_secret_header_absent") is True
        ),
        "browser_artifact_version_panel_ready": (
            node_checks.get("artifact_version_panel_ready") is True
        ),
        "browser_artifact_preview_panel_ready": (
            node_checks.get("artifact_preview_panel_ready") is True
        ),
        "browser_artifact_download_panel_ready": (
            node_checks.get("artifact_download_panel_ready") is True
        ),
        "browser_download_body_not_rendered": (
            node_checks.get("raw_download_retrieved_but_not_rendered") is True
        ),
        "ae_test_database_connected": sum(row_counts.values()) >= 8,
        "postgres_artifact_rows_persisted": row_counts
        == {
            "handoffs": 1,
            "artifacts": 1,
            "source_refs": 1,
            "versions": 1,
            "render_jobs": 1,
            "files": 1,
            "links": 2,
        },
        "postgres_migration_recorded": (
            artifact_observations.get("migration_recorded") is True
        ),
        "postgres_indexes_present": (
            artifact_observations.get("indexes_present_count")
            == len(artifact_pg.EXPECTED_INDEXES)
        ),
        "local_payload_written": prepared.markdown_file_count == 1,
        "logical_storage_ref_not_exposed": (
            artifact_observations.get("logical_storage_ref_present") is True
        ),
        "redacted_evidence": True,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": status,
        "profile": profile,
        "services": ["nex-ae-web", SERVICE_ID],
        "source_smokes": {
            "playwright_readiness": _source_status(
                readiness,
                version_key="readiness_schema_version",
            ),
            "web_artifact_postgres": _source_status(
                web_postgres,
                version_key="smoke_schema_version",
            ),
            "same_origin_boundary": _source_status(
                boundary,
                version_key="boundary_schema_version",
            ),
            "node_playwright": {
                "schema_version": node_smoke.get("smoke_schema_version"),
                "status": node_smoke.get("status"),
                "failure_code": node_smoke.get("failure_code"),
                "detail": _mapping(node_smoke.get("detail")),
            },
        },
        "database_env": prepared.database_env,
        "redacted_database_url": prepared.redacted_database_url,
        "migration": prepared.migration,
        "artifact": {
            "artifact_id": prepared.artifact_id,
            "artifact_version_id": prepared.artifact_version_id,
            "render_job_id": prepared.render_job_id,
            "artifact_file_id": prepared.artifact_file_id,
            "browser_summary": _mapping(_mapping(node_smoke.get("artifact")).get("summary")),
            "version_panel": _mapping(
                _mapping(node_smoke.get("artifact")).get("version_panel")
            ),
            "preview_panel": _mapping(
                _mapping(node_smoke.get("artifact")).get("preview_panel")
            ),
            "download_panel": _mapping(
                _mapping(node_smoke.get("artifact")).get("download_panel")
            ),
        },
        "browser_observations": _mapping(node_smoke.get("browser_observations")),
        "request_observations": _public_request_observations(
            _mapping(node_smoke.get("request_observations"))
        ),
        "db_observations": {
            "row_counts": row_counts,
            "migration_recorded": artifact_observations.get("migration_recorded")
            is True,
            "tables_present_count": artifact_observations.get(
                "tables_present_count",
                0,
            ),
            "indexes_present_count": artifact_observations.get(
                "indexes_present_count",
                0,
            ),
            "jsonb_column_count": artifact_observations.get(
                "jsonb_column_count",
                0,
            ),
        },
        "storage": {
            "storage_mode": "local",
            "markdown_file_count": prepared.markdown_file_count,
            "logical_storage_ref_present": True,
        },
        "checks": checks,
        "issues": [
            {"category": "check_failed", "subject": name}
            for name, passed in checks.items()
            if not passed
        ],
        "redaction": {
            "raw_download_body_in_evidence": False,
            "browser_service_secret_in_evidence": False,
            "database_endpoint_in_evidence": False,
            "provider_endpoint_in_evidence": False,
            "storage_location_in_evidence": False,
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
    web_postgres: Mapping[str, Any] | None = None,
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
            "web_artifact_postgres": _source_status(
                web_postgres,
                version_key="smoke_schema_version",
            ),
            "same_origin_boundary": _source_status(
                boundary,
                version_key="boundary_schema_version",
            ),
        },
        "checks": {"redacted_evidence": True},
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
    artifact_id: str,
    artifact_file_id: str,
) -> dict[str, str]:
    node_env = {
        "NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_SMOKE_WEB_URL": web_url,
        "NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_SMOKE_ARTIFACT_ID": artifact_id,
        "NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_SMOKE_ARTIFACT_FILE_ID": artifact_file_id,
    }
    if env.get(CHROMIUM_EXECUTABLE_ENV):
        node_env[CHROMIUM_EXECUTABLE_ENV] = env[CHROMIUM_EXECUTABLE_ENV]
    if env.get(TIMEOUT_MS_ENV):
        node_env[TIMEOUT_MS_ENV] = env[TIMEOUT_MS_ENV]
    return node_env


def _public_request_observations(observations: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ae_api_request_count": observations.get("ae_api_request_count", 0),
        "ae_api_response_count": observations.get("ae_api_response_count", 0),
        "request_routes": observations.get("request_routes", []),
        "response_routes": observations.get("response_routes", []),
    }


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


def _safe_source_detail(evidence: Mapping[str, Any]) -> str:
    status = evidence.get("status", "UNKNOWN")
    failure_code = evidence.get("failure_code", "unknown")
    return f"source_status={status} source_failure_code={failure_code}"


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _is_artifact_browser_path(path: object) -> bool:
    return isinstance(path, str) and (
        path.startswith("/api/v1/artifacts")
        or path.startswith("/api/v1/artifact-files")
        or path.startswith("/api/v1/artifact-render-jobs")
    )


def _has_header(headers: object, name: bytes) -> bool:
    if not isinstance(headers, list):
        return False
    return any(key.lower() == name for key, _value in headers)


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
            "AE Web artifact Playwright PostgreSQL smoke evidence contains "
            f"unredacted environment value: {leaked[0]}"
        )
    for fragment in (
        "".join(("nuri", "1004")),
        "".join(("ed6", "@", "c496em")),
        "/data/" "nex-platform",
    ):
        if fragment in serialized_evidence:
            raise ValueError(
                "AE Web artifact Playwright PostgreSQL smoke evidence contains "
                "server-only material."
            )


def _protected_env_value_leaked(serialized: str, value: str | None) -> bool:
    return bool(value and value not in {DEFAULT_PROFILE, "1"} and value in serialized)


def write_smoke_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    assert_smoke_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_web_artifact_playwright_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        artifact = _mapping(evidence.get("artifact"))
        browser = _mapping(evidence.get("browser_observations"))
        db = _mapping(evidence.get("db_observations"))
        return (
            "ae_web_artifact_playwright_postgres_smoke=pass "
            f"profile={evidence['profile']} "
            f"artifact={artifact.get('artifact_id')} "
            f"version_panel={browser.get('version_panel_status')} "
            f"preview_panel={browser.get('preview_panel_status')} "
            f"download_panel={browser.get('download_panel_status')} "
            f"rows={sum(_mapping(db.get('row_counts')).values())} "
            "live_db=true browser=playwright"
        )
    return (
        "ae_web_artifact_playwright_postgres_smoke=fail "
        f"reason={evidence.get('failure_code', 'checks_failed')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run protected AE Web artifact Playwright PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_env_file(ROOT / ".env.local")
        evidence = run_ae_web_artifact_playwright_postgres_smoke()
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
            "ae_web_artifact_playwright_postgres_smoke=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
