#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


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
import run_ae_artifact_export_postgres_smoke as export_pg  # noqa: E402
import run_ae_artifact_postgres_smoke as artifact_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
import run_ae_web_artifact_playwright_postgres_smoke as base_playwright  # noqa: E402
import run_ae_web_credential_login_playwright_postgres_smoke as login_pg  # noqa: E402


SCHEMA_VERSION = "ae_web_artifact_multiformat_playwright_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_WEB_ARTIFACT_MULTIFORMAT_PLAYWRIGHT_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_AE_WEB_ARTIFACT_MULTIFORMAT_PLAYWRIGHT_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
SERVICE_ID = artifact_pg.SERVICE_ID
EXPORT_FORMATS = export_pg.EXPORT_FORMATS

ProtectedRunner = Callable[[dict[str, str]], dict[str, Any]]
NodeRunner = Callable[[Mapping[str, str]], dict[str, Any]]
PortAllocator = Callable[[], int]
ArtifactObserver = Callable[..., dict[str, Any]]


@dataclass
class PreparedArtifactMultiformatPlaywrightPostgresSmoke:
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
    primary_artifact_file_id: str
    file_ids_by_format: dict[str, str]
    materialized_file_count: int
    materialized_extensions: list[str]
    db_observations: dict[str, Any]
    read_model_observations: dict[str, Any]
    storage_tempdir: tempfile.TemporaryDirectory[str]

    def cleanup(self) -> dict[str, Any]:
        deleted = artifact_pg._cleanup_smoke_rows(
            self.engine,
            artifact_id=self.artifact_id,
            artifact_handoff_id=self.artifact_handoff_id,
        )
        self.storage_tempdir.cleanup()
        return deleted


def run_ae_web_artifact_multiformat_playwright_postgres_smoke(
    environ: dict[str, str] | None = None,
    *,
    readiness_runner: ProtectedRunner = run_ae_web_playwright_readiness,
    api_export_runner: ProtectedRunner = export_pg.run_ae_artifact_export_postgres_smoke,
    boundary_runner: ProtectedRunner = run_ae_web_same_origin_runtime_boundary,
    prepare_runner: Callable[
        [dict[str, str], str],
        PreparedArtifactMultiformatPlaywrightPostgresSmoke,
    ] = lambda env, profile: prepare_artifact_multiformat_playwright_postgres_smoke(
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
    node_runner = node_runner or base_playwright.run_node_playwright_artifact_smoke
    artifact_observer = artifact_observer or latest_multiformat_artifact_observations
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

    api_export_env = dict(env)
    api_export_env[export_pg.SMOKE_ENV] = "1"
    api_export_env[export_pg.SMOKE_PROFILE_ENV] = profile
    api_export = api_export_runner(api_export_env)
    if api_export.get("status") != "PASS":
        return _failure(
            "api_export_postgres_failed",
            profile=profile,
            env=api_export_env,
            readiness=readiness,
            api_export=api_export,
            detail=_safe_source_detail(api_export),
        )

    prepared: PreparedArtifactMultiformatPlaywrightPostgresSmoke | None = None
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
                api_export=api_export,
                boundary=boundary,
            )

        node_smoke = node_runner(
            base_playwright._node_environ(
                env,
                web_url=web_server.url,
                artifact_id=prepared.artifact_id,
                artifact_file_id=prepared.primary_artifact_file_id,
            )
        )
        artifact_observations = artifact_observer(
            prepared.engine,
            artifact_handoff_id=prepared.artifact_handoff_id,
            artifact_id=prepared.artifact_id,
            artifact_version_id=prepared.artifact_version_id,
            render_job_id=prepared.render_job_id,
        )
        evidence = _pass_or_fail_evidence(
            profile=profile,
            env={**env, PROXY_TARGET_ENV: api_server.url},
            readiness=readiness,
            api_export=api_export,
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
            api_export=api_export,
        )
    except Exception as exc:
        return _failure(
            "execution_failed",
            profile=profile,
            env=env,
            detail=exc.__class__.__name__,
            readiness=readiness,
            api_export=api_export,
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


def prepare_artifact_multiformat_playwright_postgres_smoke(
    env: dict[str, str],
    *,
    profile: str,
) -> PreparedArtifactMultiformatPlaywrightPostgresSmoke:  # pragma: no cover
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
        prefix="nex-ae-web-artifact-multiformat-playwright-smoke-"
    )
    storage_root = Path(storage_tempdir.name) / "artifact-storage"
    engine = build_engine(database_url)
    artifact_handoff_id: str | None = None
    artifact_id: str | None = None
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

        handoff_response = client.post(
            "/api/v1/artifact-handoffs",
            json={
                **artifact_pg._artifact_handoff_payload(suffix),
                "target_formats": list(EXPORT_FORMATS),
            },
            headers={
                **headers,
                "Idempotency-Key": f"artifact-multiformat-handoff-{suffix}",
            },
        )
        handoff_response.raise_for_status()
        artifact_handoff_id = handoff_response.json()["artifact_handoff_id"]

        artifact_response = client.post(
            "/api/v1/artifacts",
            json={"artifact_handoff_id": artifact_handoff_id},
            headers={
                **headers,
                "Idempotency-Key": f"artifact-multiformat-create-{suffix}",
            },
        )
        artifact_response.raise_for_status()
        artifact = artifact_response.json()
        artifact_id = artifact["artifact_id"]

        render_response = client.post(
            f"/api/v1/artifacts/{artifact_id}/render-jobs",
            json={"target_formats": list(EXPORT_FORMATS)},
            headers={
                **headers,
                "Idempotency-Key": f"artifact-multiformat-render-{suffix}",
            },
        )
        render_response.raise_for_status()
        rendered = render_response.json()
        rendered_artifact = rendered["artifact"]
        render_job = rendered["render_job"]
        artifact_version_id = rendered_artifact["current_version_id"]
        file_ids_by_format = {
            str(artifact_file["format"]): str(artifact_file["artifact_file_id"])
            for artifact_file in rendered_artifact["files"]
        }
        primary_artifact_file_id = file_ids_by_format.get("MD") or next(
            iter(file_ids_by_format.values())
        )
        artifact_readback = client.get(f"/api/v1/artifacts/{artifact_id}", headers=headers)
        versions_readback = client.get(
            f"/api/v1/artifacts/{artifact_id}/versions",
            headers=headers,
        )
        render_job_readback = client.get(
            f"/api/v1/artifact-render-jobs/{render_job['render_job_id']}",
            headers=headers,
        )
        read_model_observations = export_pg._read_model_observations(
            artifact_payload=export_pg._response_payload(artifact_readback),
            versions_payload=export_pg._response_payload(versions_readback),
            render_job_payload=export_pg._response_payload(render_job_readback),
            artifact_status_code=artifact_readback.status_code,
            versions_status_code=versions_readback.status_code,
            render_job_status_code=render_job_readback.status_code,
            artifact_version_id=artifact_version_id,
        )
        db_observations = latest_multiformat_artifact_observations(
            engine,
            artifact_handoff_id=artifact_handoff_id,
            artifact_id=artifact_id,
            artifact_version_id=artifact_version_id,
            render_job_id=render_job["render_job_id"],
        )
        storage_files = [
            path for path in storage_root.rglob("*") if path.is_file() and path.suffix
        ]
        return PreparedArtifactMultiformatPlaywrightPostgresSmoke(
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
            primary_artifact_file_id=primary_artifact_file_id,
            file_ids_by_format=file_ids_by_format,
            materialized_file_count=len(storage_files),
            materialized_extensions=sorted(path.suffix.lstrip(".") for path in storage_files),
            db_observations=db_observations,
            read_model_observations=read_model_observations,
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


def latest_multiformat_artifact_observations(
    engine: Any,
    *,
    artifact_handoff_id: str,
    artifact_id: str,
    artifact_version_id: str,
    render_job_id: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        row_counts = {
            "handoffs": _scalar_count(
                connection,
                """
                SELECT count(*) FROM ae_artifact_handoffs
                WHERE artifact_handoff_id = :artifact_handoff_id
                """,
                {"artifact_handoff_id": artifact_handoff_id},
            ),
            "artifacts": _scalar_count(
                connection,
                "SELECT count(*) FROM ae_artifacts WHERE artifact_id = :artifact_id",
                {"artifact_id": artifact_id},
            ),
            "source_refs": _scalar_count(
                connection,
                "SELECT count(*) FROM ae_artifact_source_refs WHERE artifact_id = :artifact_id",
                {"artifact_id": artifact_id},
            ),
            "versions": _scalar_count(
                connection,
                """
                SELECT count(*) FROM ae_artifact_versions
                WHERE artifact_version_id = :artifact_version_id
                """,
                {"artifact_version_id": artifact_version_id},
            ),
            "render_jobs": _scalar_count(
                connection,
                """
                SELECT count(*) FROM ae_artifact_render_jobs
                WHERE render_job_id = :render_job_id
                """,
                {"render_job_id": render_job_id},
            ),
            "files": _scalar_count(
                connection,
                """
                SELECT count(*) FROM ae_artifact_files
                WHERE artifact_version_id = :artifact_version_id
                """,
                {"artifact_version_id": artifact_version_id},
            ),
            "links": _scalar_count(
                connection,
                """
                SELECT count(*)
                FROM ae_artifact_links
                WHERE artifact_file_id IN (
                    SELECT artifact_file_id
                    FROM ae_artifact_files
                    WHERE artifact_version_id = :artifact_version_id
                )
                """,
                {"artifact_version_id": artifact_version_id},
            ),
        }
        rendered_formats = connection.execute(
            text(
                """
                SELECT rendered_formats
                FROM ae_artifact_versions
                WHERE artifact_version_id = :artifact_version_id
                """
            ),
            {"artifact_version_id": artifact_version_id},
        ).scalar_one()
        file_rows = (
            connection.execute(
                text(
                    """
                    SELECT format, artifact_file_id, mime_type, file_size_bytes
                    FROM ae_artifact_files
                    WHERE artifact_version_id = :artifact_version_id
                    ORDER BY CASE format
                        WHEN 'MD' THEN 1
                        WHEN 'HTML_PREVIEW' THEN 2
                        WHEN 'DOCX' THEN 3
                        WHEN 'PDF' THEN 4
                        ELSE 99
                    END
                    """
                ),
                {"artifact_version_id": artifact_version_id},
            )
            .mappings()
            .all()
        )
        link_type_counts = dict(
            connection.execute(
                text(
                    """
                    SELECT link_type, count(*) AS count
                    FROM ae_artifact_links
                    WHERE artifact_file_id IN (
                        SELECT artifact_file_id
                        FROM ae_artifact_files
                        WHERE artifact_version_id = :artifact_version_id
                    )
                    GROUP BY link_type
                    """
                ),
                {"artifact_version_id": artifact_version_id},
            ).all()
        )
    return {
        "row_counts": row_counts,
        "rendered_formats": _json_array(rendered_formats),
        "file_formats": [str(row["format"]) for row in file_rows],
        "file_count": len(file_rows),
        "link_count": row_counts["links"],
        "download_link_count": int(link_type_counts.get("download", 0)),
        "preview_link_count": int(link_type_counts.get("preview", 0)),
        "file_ids_by_format": {
            str(row["format"]): str(row["artifact_file_id"]) for row in file_rows
        },
        "mime_types": {str(row["format"]): str(row["mime_type"]) for row in file_rows},
        "file_size_bytes": {
            str(row["format"]): int(row["file_size_bytes"]) for row in file_rows
        },
    }


def _pass_or_fail_evidence(
    *,
    profile: str,
    env: Mapping[str, str],
    readiness: Mapping[str, Any],
    api_export: Mapping[str, Any],
    boundary: Mapping[str, Any],
    prepared: PreparedArtifactMultiformatPlaywrightPostgresSmoke,
    node_smoke: Mapping[str, Any],
    artifact_observations: Mapping[str, Any],
) -> dict[str, Any]:
    node_checks = _mapping(node_smoke.get("checks"))
    node_artifact = _mapping(node_smoke.get("artifact"))
    browser_summary = _mapping(node_artifact.get("summary"))
    version_panel = _mapping(node_artifact.get("version_panel"))
    download_selector = _mapping(node_artifact.get("download_selector"))
    export_result = _mapping(node_artifact.get("export_result"))
    row_counts = dict(artifact_observations.get("row_counts", {}))
    expected_row_counts = {
        "handoffs": 1,
        "artifacts": 1,
        "source_refs": 1,
        "versions": 1,
        "render_jobs": 1,
        "files": len(EXPORT_FORMATS),
        "links": len(EXPORT_FORMATS) * 2,
    }
    checks = {
        "playwright_readiness_passed": readiness.get("status") == "PASS",
        "api_export_postgres_passed": api_export.get("status") == "PASS",
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
        "browser_file_save_prepared": (
            node_checks.get("browser_file_save_prepared") is True
        ),
        "browser_download_body_not_rendered": (
            node_checks.get("raw_download_retrieved_but_not_rendered") is True
        ),
        "browser_download_selector_ready": (
            node_checks.get("artifact_download_selector_ready") is True
        ),
        "browser_download_selector_multiformat": (
            int(download_selector.get("enabled_option_count") or 0)
            >= len(EXPORT_FORMATS)
            and download_selector.get("selected_route_present") is True
        ),
        "browser_artifact_summary_multiformat": (
            int(browser_summary.get("download_route_count") or 0) >= len(EXPORT_FORMATS)
            and int(browser_summary.get("available_format_count") or 0)
            >= len(EXPORT_FORMATS)
        ),
        "browser_version_panel_multiformat": (
            int(version_panel.get("file_count") or 0) >= len(EXPORT_FORMATS)
            and int(version_panel.get("download_route_count") or 0)
            >= len(EXPORT_FORMATS)
            and int(version_panel.get("format_count") or 0) >= len(EXPORT_FORMATS)
        ),
        "browser_export_result_multiformat": (
            int(export_result.get("downloadable_format_count") or 0)
            >= len(EXPORT_FORMATS)
        ),
        "ae_test_database_connected": sum(row_counts.values()) >= 17,
        "postgres_multiformat_rows_persisted": row_counts == expected_row_counts,
        "postgres_rendered_formats_persisted": artifact_observations.get(
            "rendered_formats"
        )
        == list(EXPORT_FORMATS),
        "postgres_file_formats_persisted": artifact_observations.get("file_formats")
        == list(EXPORT_FORMATS),
        "postgres_download_links_persisted": artifact_observations.get(
            "download_link_count"
        )
        == len(EXPORT_FORMATS),
        "postgres_preview_links_persisted": artifact_observations.get(
            "preview_link_count"
        )
        == len(EXPORT_FORMATS),
        "local_payloads_written": prepared.materialized_file_count == len(EXPORT_FORMATS),
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
            "api_export_postgres": _source_status(
                api_export,
                version_key="smoke_schema_version",
            ),
            "same_origin_boundary": _source_status(
                boundary,
                version_key="boundary_schema_version",
            ),
            "node_playwright": _source_status(
                node_smoke,
                version_key="smoke_schema_version",
            ),
        },
        "database_env": prepared.database_env,
        "redacted_database_url": prepared.redacted_database_url,
        "migration": prepared.migration,
        "artifact": {
            "artifact_id": prepared.artifact_id,
            "artifact_version_id": prepared.artifact_version_id,
            "render_job_id": prepared.render_job_id,
            "primary_artifact_file_id": prepared.primary_artifact_file_id,
            "formats": list(EXPORT_FORMATS),
            "file_ids_by_format": dict(prepared.file_ids_by_format),
            "browser_summary": browser_summary,
            "version_panel": version_panel,
            "download_selector": download_selector,
            "download_save": _mapping(node_artifact.get("download_save")),
            "export_result": export_result,
        },
        "browser_observations": _mapping(node_smoke.get("browser_observations")),
        "request_observations": base_playwright._public_request_observations(
            _mapping(node_smoke.get("request_observations"))
        ),
        "db_observations": {
            "row_counts": row_counts,
            "rendered_formats": artifact_observations.get("rendered_formats", []),
            "file_formats": artifact_observations.get("file_formats", []),
            "file_count": artifact_observations.get("file_count", 0),
            "link_count": artifact_observations.get("link_count", 0),
            "download_link_count": artifact_observations.get("download_link_count", 0),
            "preview_link_count": artifact_observations.get("preview_link_count", 0),
        },
        "read_model_observations": dict(prepared.read_model_observations),
        "storage": {
            "storage_mode": "local",
            "materialized_file_count": prepared.materialized_file_count,
            "materialized_extensions": list(prepared.materialized_extensions),
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
            "database_password_in_evidence": False,
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
    api_export: Mapping[str, Any] | None = None,
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
            "api_export_postgres": _source_status(
                api_export,
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
    if evidence.get("failure_code"):
        source["failure_code"] = evidence.get("failure_code")
    return source


def _safe_source_detail(evidence: Mapping[str, Any]) -> str:
    status = evidence.get("status", "UNKNOWN")
    failure_code = evidence.get("failure_code", "unknown")
    return f"source_status={status} source_failure_code={failure_code}"


def _scalar_count(connection: Any, sql: str, params: dict[str, str]) -> int:
    return int(connection.execute(text(sql), params).scalar() or 0)


def _json_array(value: Any) -> list[str]:
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    base_playwright.assert_smoke_evidence_redacted(serialized_evidence, environ)


def write_smoke_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    assert_smoke_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_web_artifact_multiformat_playwright_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        artifact = _mapping(evidence.get("artifact"))
        selector = _mapping(artifact.get("download_selector"))
        db = _mapping(evidence.get("db_observations"))
        row_counts = _mapping(db.get("row_counts"))
        return (
            "ae_web_artifact_multiformat_playwright_postgres_smoke=pass "
            f"profile={evidence['profile']} "
            f"artifact={artifact.get('artifact_id')} "
            f"selector={selector.get('status')} "
            f"enabled={selector.get('enabled_option_count')} "
            f"formats={len(artifact.get('formats', []))} "
            f"files={db.get('file_count')} "
            f"links={db.get('link_count')} "
            f"rows={sum(row_counts.values())} "
            "live_db=true browser=playwright"
        )
    return (
        "ae_web_artifact_multiformat_playwright_postgres_smoke=fail "
        f"reason={evidence.get('failure_code', 'checks_failed')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run protected AE Web multi-format artifact Playwright PostgreSQL smoke."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_env_file(ROOT / ".env.local")
        evidence = run_ae_web_artifact_multiformat_playwright_postgres_smoke()
        if args.output:
            write_smoke_evidence(args.output, evidence)
        print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
        return 1 if evidence["status"] == "FAIL" else 0
    except Exception as exc:
        print(
            "ae_web_artifact_multiformat_playwright_postgres_smoke=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
