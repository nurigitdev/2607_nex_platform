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

from nex_runtime import (  # noqa: E402
    build_engine,
    build_session_factory,
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
import run_ae_artifact_collection_postgres_smoke as collection_pg  # noqa: E402
import run_ae_artifact_lifecycle_postgres_smoke as lifecycle_pg  # noqa: E402
import run_ae_artifact_postgres_smoke as artifact_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
import run_ae_web_artifact_playwright_postgres_smoke as base_playwright  # noqa: E402
import run_ae_web_credential_login_playwright_postgres_smoke as login_pg  # noqa: E402


SCHEMA_VERSION = "ae_web_artifact_lifecycle_playwright_postgres_smoke.v1"
NODE_SMOKE_SCHEMA_VERSION = "ae_web_artifact_lifecycle_playwright_smoke.v1"
SMOKE_ENV = "NEX_AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_POSTGRES_SMOKE_PROFILE"
CHROMIUM_EXECUTABLE_ENV = "NEX_AE_WEB_PLAYWRIGHT_CHROMIUM_EXECUTABLE"
TIMEOUT_MS_ENV = "NEX_AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_SMOKE_TIMEOUT_MS"
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
SERVICE_ID = artifact_pg.SERVICE_ID
WEB_ROOT = ROOT / "apps" / "nex-ae-web"
NODE_SMOKE_SCRIPT = WEB_ROOT / "scripts" / "runArtifactLifecyclePlaywrightSmoke.mjs"

ProtectedRunner = Callable[[dict[str, str]], dict[str, Any]]
NodeRunner = Callable[[Mapping[str, str]], dict[str, Any]]
PortAllocator = Callable[[], int]
ArtifactObserver = Callable[..., dict[str, Any]]

PROTECTED_ENV_KEYS = (
    artifact_pg.service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE),
    PROXY_TARGET_ENV,
)


@dataclass
class PreparedArtifactLifecyclePlaywrightPostgresSmoke:
    profile: str
    request_id: str
    trace_id: str
    database_env: str
    redacted_database_url: str
    migration: dict[str, object]
    engine: Any
    ae_app: Any
    tenant_id: str
    workspace_id: str
    owner_user_id: str
    artifact_handoff_id: str
    artifact_id: str
    materialized_file_count: int
    storage_tempdir: tempfile.TemporaryDirectory[str]

    def cleanup(self) -> dict[str, int]:
        deleted = collection_pg._cleanup_smoke_rows(
            self.engine,
            artifact_ids=[self.artifact_id],
            artifact_handoff_ids=[self.artifact_handoff_id],
        )
        self.storage_tempdir.cleanup()
        return deleted


def run_ae_web_artifact_lifecycle_playwright_postgres_smoke(
    environ: dict[str, str] | None = None,
    *,
    readiness_runner: ProtectedRunner = run_ae_web_playwright_readiness,
    lifecycle_runner: ProtectedRunner = lifecycle_pg.run_ae_artifact_lifecycle_postgres_smoke,
    boundary_runner: ProtectedRunner = run_ae_web_same_origin_runtime_boundary,
    prepare_runner: Callable[
        [dict[str, str], str],
        PreparedArtifactLifecyclePlaywrightPostgresSmoke,
    ] = lambda env, profile: prepare_artifact_lifecycle_playwright_postgres_smoke(
        env,
        profile=profile,
    ),
    node_runner: NodeRunner | None = None,
    artifact_observer: ArtifactObserver | None = None,
    port_allocator: PortAllocator | None = None,
    api_server_starter: Callable[[Any, int], login_pg.StartedServer] | None = None,
    web_server_starter: Callable[[int, str], login_pg.StartedServer] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    node_runner = node_runner or run_node_artifact_lifecycle_playwright_smoke
    artifact_observer = artifact_observer or latest_artifact_lifecycle_observations
    port_allocator = port_allocator or login_pg.find_free_port
    api_server_starter = api_server_starter or login_pg.start_api_server
    web_server_starter = web_server_starter or login_pg.start_web_server

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
    if readiness.get("status") != "PASS":
        return _failure(
            "readiness_failed",
            profile=profile,
            env=env,
            readiness=readiness,
        )

    lifecycle_env = dict(env)
    lifecycle_env[lifecycle_pg.SMOKE_ENV] = "1"
    lifecycle_env[lifecycle_pg.SMOKE_PROFILE_ENV] = profile
    lifecycle = lifecycle_runner(lifecycle_env)
    if lifecycle.get("status") != "PASS":
        return _failure(
            "artifact_lifecycle_postgres_failed",
            profile=profile,
            env=lifecycle_env,
            readiness=readiness,
            lifecycle=lifecycle,
            detail=_safe_source_detail(lifecycle),
        )

    prepared: PreparedArtifactLifecyclePlaywrightPostgresSmoke | None = None
    api_server: login_pg.StartedServer | None = None
    web_server: login_pg.StartedServer | None = None
    evidence: dict[str, Any] | None = None
    try:
        prepared = prepare_runner(dict(env), profile)
        api_port = port_allocator()
        web_port = port_allocator()
        api_server = api_server_starter(prepared.ae_app, api_port)
        web_server = web_server_starter(web_port, api_server.url)
        boundary_env = {**env, PROXY_TARGET_ENV: api_server.url}
        boundary = boundary_runner(boundary_env)
        if boundary.get("status") != "PASS":
            return _failure(
                "same_origin_boundary_failed",
                profile=profile,
                env=boundary_env,
                readiness=readiness,
                lifecycle=lifecycle,
                boundary=boundary,
            )

        node_smoke = node_runner(
            _node_environ(
                env,
                web_url=web_server.url,
                artifact_id=prepared.artifact_id,
            )
        )
        artifact_observations = artifact_observer(
            prepared.engine,
            artifact_id=prepared.artifact_id,
            tenant_id=prepared.tenant_id,
            workspace_id=prepared.workspace_id,
            owner_user_id=prepared.owner_user_id,
        )
        evidence = _pass_or_fail_evidence(
            profile=profile,
            env=boundary_env,
            readiness=readiness,
            lifecycle=lifecycle,
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
            lifecycle=lifecycle,
        )
    except Exception as exc:
        return _failure(
            "execution_failed",
            profile=profile,
            env=env,
            detail=exc.__class__.__name__,
            readiness=readiness,
            lifecycle=lifecycle,
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


def prepare_artifact_lifecycle_playwright_postgres_smoke(
    env: dict[str, str],
    *,
    profile: str,
) -> PreparedArtifactLifecyclePlaywrightPostgresSmoke:  # pragma: no cover
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
    tenant_id = f"tenant-artifact-lifecycle-web-{suffix}"
    workspace_id = f"workspace-artifact-lifecycle-web-{suffix}"
    owner_user_id = f"owner-artifact-lifecycle-web-{suffix}"
    storage_tempdir = tempfile.TemporaryDirectory(
        prefix="nex-ae-web-artifact-lifecycle-playwright-smoke-"
    )
    storage_root = Path(storage_tempdir.name) / "artifact-storage"
    engine = build_engine(database_url)
    artifact_id: str | None = None
    artifact_handoff_id: str | None = None
    try:
        session_factory = build_session_factory(engine)
        ae_app = base_playwright.build_ae_artifact_app(
            env=env,
            session_factory=session_factory,
            storage_root=storage_root,
            suffix=suffix,
            request_id=request_id,
            trace_id=trace_id,
        )
        client = TestClient(ae_app)
        headers = artifact_pg._auth_headers(request_id=request_id, trace_id=trace_id)
        created = collection_pg._create_artifact(
            client,
            headers,
            suffix=suffix,
            label="lifecycle-web",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            render=True,
        )
        artifact_id = created["artifact_id"]
        artifact_handoff_id = created["artifact_handoff_id"]
        materialized_file_count = sum(
            1 for path in storage_root.rglob("*") if path.is_file()
        )
        return PreparedArtifactLifecyclePlaywrightPostgresSmoke(
            profile=profile,
            request_id=request_id,
            trace_id=trace_id,
            database_env=database_env,
            redacted_database_url=redact_database_url(database_url),
            migration=base_auth._migration_evidence(migration),
            engine=engine,
            ae_app=ae_app,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            artifact_handoff_id=artifact_handoff_id,
            artifact_id=artifact_id,
            materialized_file_count=materialized_file_count,
            storage_tempdir=storage_tempdir,
        )
    except Exception:
        collection_pg._cleanup_smoke_rows(
            engine,
            artifact_ids=[artifact_id] if artifact_id else [],
            artifact_handoff_ids=[artifact_handoff_id] if artifact_handoff_id else [],
        )
        storage_tempdir.cleanup()
        engine.dispose()
        raise


def latest_artifact_lifecycle_observations(
    engine: Any,
    *,
    artifact_id: str,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
) -> dict[str, Any]:
    return lifecycle_pg._db_observations(
        engine,
        artifact_id=artifact_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
    )


def run_node_artifact_lifecycle_playwright_smoke(
    env: Mapping[str, str],
) -> dict[str, Any]:
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
    lifecycle: Mapping[str, Any],
    boundary: Mapping[str, Any],
    prepared: PreparedArtifactLifecyclePlaywrightPostgresSmoke,
    node_smoke: Mapping[str, Any],
    artifact_observations: Mapping[str, Any],
) -> dict[str, Any]:
    node_checks = _mapping(node_smoke.get("checks"))
    node_browser = _mapping(node_smoke.get("browser_observations"))
    checks = {
        "playwright_readiness_passed": readiness.get("status") == "PASS",
        "artifact_lifecycle_postgres_passed": lifecycle.get("status") == "PASS",
        "same_origin_boundary_passed": boundary.get("status") == "PASS",
        "node_playwright_smoke_passed": node_smoke.get("status") == "PASS",
        "playwright_browser_launched": (
            node_checks.get("playwright_browser_launched") is True
        ),
        "browser_artifact_lifecycle_shell_dom_present": (
            node_checks.get("artifact_lifecycle_shell_dom_present") is True
        ),
        "browser_artifact_detail_called": (
            node_checks.get("artifact_detail_called") is True
        ),
        "browser_artifact_lifecycle_post_called": (
            node_checks.get("artifact_lifecycle_post_called") is True
        ),
        "browser_request_secret_header_absent": (
            node_checks.get("browser_request_secret_header_absent") is True
        ),
        "browser_archive_restore_delete_applied": (
            node_checks.get("archive_transition_applied") is True
            and node_checks.get("restore_transition_applied") is True
            and node_checks.get("delete_transition_applied") is True
        ),
        "browser_final_artifact_deleted": (
            node_checks.get("final_artifact_deleted") is True
        ),
        "browser_deleted_restore_available": (
            node_checks.get("deleted_restore_available") is True
        ),
        "browser_lifecycle_metadata_only": (
            node_checks.get("lifecycle_metadata_only") is True
        ),
        "ae_test_database_connected": (
            artifact_observations.get("deleted_rows") == 1
            and artifact_observations.get("ready_rows") == 0
        ),
        "postgres_file_rows_retained": artifact_observations.get("file_rows", 0) >= 1,
        "postgres_link_rows_retained": artifact_observations.get("link_rows", 0) >= 2,
        "local_payload_written": prepared.materialized_file_count >= 1,
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
            "artifact_lifecycle_postgres": _source_status(
                lifecycle,
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
        "artifact_lifecycle": {
            "artifact_id": prepared.artifact_id,
            "tenant_id": prepared.tenant_id,
            "workspace_id": prepared.workspace_id,
            "owner_user_id": prepared.owner_user_id,
            "browser_summary": _mapping(node_smoke.get("lifecycle")),
            "browser_observations": node_browser,
        },
        "request_observations": _public_request_observations(
            _mapping(node_smoke.get("request_observations"))
        ),
        "db_observations": {
            "ready_rows": artifact_observations.get("ready_rows", 0),
            "archived_rows": artifact_observations.get("archived_rows", 0),
            "deleted_rows": artifact_observations.get("deleted_rows", 0),
            "file_rows": artifact_observations.get("file_rows", 0),
            "link_rows": artifact_observations.get("link_rows", 0),
        },
        "storage": {
            "storage_mode": "local",
            "materialized_file_count": prepared.materialized_file_count,
        },
        "checks": checks,
        "issues": [
            {"category": "check_failed", "subject": name}
            for name, passed in checks.items()
            if not passed
        ],
        "redaction": {
            "raw_lifecycle_comment_in_evidence": False,
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
    lifecycle: Mapping[str, Any] | None = None,
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
            "artifact_lifecycle_postgres": _source_status(
                lifecycle,
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
) -> dict[str, str]:
    node_env = {
        "NEX_AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_SMOKE_WEB_URL": web_url,
        "NEX_AE_WEB_ARTIFACT_LIFECYCLE_PLAYWRIGHT_SMOKE_ARTIFACT_ID": artifact_id,
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
    if "failure_code" in evidence:
        source["failure_code"] = evidence.get("failure_code")
    return source


def _safe_source_detail(evidence: Mapping[str, Any]) -> str:
    status = evidence.get("status", "UNKNOWN")
    failure_code = evidence.get("failure_code", "unknown")
    return f"source_status={status} source_failure_code={failure_code}"


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


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
            "AE Web artifact lifecycle Playwright PostgreSQL smoke evidence "
            f"contains unredacted environment value: {leaked[0]}"
        )
    for fragment in (
        "".join(("nuri", "1004")),
        "".join(("ed6", "@", "c496em")),
        "/data/" "nex-platform",
        "Move out of active view",
    ):
        if fragment in serialized_evidence:
            raise ValueError(
                "AE Web artifact lifecycle Playwright PostgreSQL smoke evidence "
                "contains server-only material."
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
            "ae_web_artifact_lifecycle_playwright_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        lifecycle = _mapping(evidence.get("artifact_lifecycle"))
        browser = _mapping(lifecycle.get("browser_observations"))
        db = _mapping(evidence.get("db_observations"))
        return (
            "ae_web_artifact_lifecycle_playwright_postgres_smoke=pass "
            f"profile={evidence['profile']} "
            f"artifact={lifecycle.get('artifact_id')} "
            f"archive={browser.get('archive_status')} "
            f"restore={browser.get('restore_status')} "
            f"delete={browser.get('delete_status')} "
            f"deleted_rows={db.get('deleted_rows')} "
            "live_db=true browser=playwright"
        )
    return (
        "ae_web_artifact_lifecycle_playwright_postgres_smoke=fail "
        f"reason={evidence.get('failure_code', 'checks_failed')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run protected AE Web artifact lifecycle Playwright PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_env_file(ROOT / ".env.local")
        evidence = run_ae_web_artifact_lifecycle_playwright_postgres_smoke()
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
            "ae_web_artifact_lifecycle_playwright_postgres_smoke=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
