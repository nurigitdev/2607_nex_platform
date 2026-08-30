#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator, Mapping
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AE_PATH = ROOT / "services" / "nex-ae-api"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(SMOKE_PATH))

import run_ae_artifact_postgres_smoke as artifact_smoke  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifacts import register_artifact_handoff_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "ae_artifact_export_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ARTIFACT_EXPORT_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_ARTIFACT_EXPORT_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = artifact_smoke.SERVICE_ID
DEFAULT_PROFILE = artifact_smoke.DEFAULT_PROFILE
EXPORT_FORMATS = ("MD", "HTML_PREVIEW", "DOCX", "PDF")


def run_ae_artifact_export_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
            env=env,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        base_auth._require_test_database_url(database_url, env_name=database_env)
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_ae_artifact_export_smoke(
            database_url=database_url,
            database_env=database_env,
        )
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile, env=env)
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        return _failure("execution_failed", detail, profile=profile, env=env)

    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "service_id": SERVICE_ID,
        "profile": profile,
        "database_env": database_env,
        "redacted_database_url": redact_database_url(database_url),
        "migration": {
            "planned": list(migration.planned),
            "applied": list(migration.applied),
            "skipped": list(migration.skipped),
        },
        **execution,
    }
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _execute_ae_artifact_export_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    artifact_handoff_id: str | None = None
    artifact_id: str | None = None
    artifact_version_id: str | None = None
    render_job_id: str | None = None
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        with tempfile.TemporaryDirectory(
            prefix="nex-ae-artifact-export-smoke-"
        ) as storage_dir:
            storage_root = Path(storage_dir) / "artifact-storage"
            with _temporary_env("NEX_AE_ARTIFACT_STORAGE_ROOT", str(storage_root)):
                app = build_service_app(SERVICE_SPECS[SERVICE_ID])
                app.state.nex_persistence = SimpleNamespace(
                    api_session_factory=session_factory
                )
                cx_client = artifact_smoke.FakeCxArtifactSourceClient(
                    suffix=suffix,
                    request_id=request_id,
                    trace_id=trace_id,
                )
                register_artifact_handoff_routes(app, cx_client=cx_client)
                client = TestClient(app)
                headers = artifact_smoke._auth_headers(
                    request_id=request_id,
                    trace_id=trace_id,
                )

                handoff_response = client.post(
                    "/api/v1/artifact-handoffs",
                    json={
                        **artifact_smoke._artifact_handoff_payload(suffix),
                        "target_formats": list(EXPORT_FORMATS),
                    },
                    headers={
                        **headers,
                        "Idempotency-Key": f"artifact-export-handoff-{suffix}",
                    },
                )
                if handoff_response.status_code != 200:
                    raise RuntimeError("AE artifact export handoff route failed")
                artifact_handoff_id = handoff_response.json()["artifact_handoff_id"]

                artifact_response = client.post(
                    "/api/v1/artifacts",
                    json={"artifact_handoff_id": artifact_handoff_id},
                    headers={
                        **headers,
                        "Idempotency-Key": f"artifact-export-create-{suffix}",
                    },
                )
                if artifact_response.status_code != 200:
                    raise RuntimeError("AE artifact export create route failed")
                artifact = artifact_response.json()
                artifact_id = artifact["artifact_id"]

                render_response = client.post(
                    f"/api/v1/artifacts/{artifact_id}/render-jobs",
                    json={"target_formats": list(EXPORT_FORMATS)},
                    headers={
                        **headers,
                        "Idempotency-Key": f"artifact-export-render-{suffix}",
                    },
                )
                if render_response.status_code != 200:
                    raise RuntimeError("AE artifact export render route failed")
                rendered = render_response.json()
                rendered_artifact = rendered["artifact"]
                render_job = rendered["render_job"]
                artifact_version_id = rendered_artifact["current_version_id"]
                render_job_id = render_job["render_job_id"]
                files = list(rendered_artifact["files"])
                files_by_format = {artifact_file["format"]: artifact_file for artifact_file in files}

                file_readbacks = {
                    export_format: client.get(
                        f"/api/v1/artifact-files/{artifact_file['artifact_file_id']}",
                        headers=headers,
                    )
                    for export_format, artifact_file in files_by_format.items()
                }
                previews = {
                    export_format: client.get(
                        f"/api/v1/artifact-files/{artifact_file['artifact_file_id']}/preview",
                        headers=headers,
                    )
                    for export_format, artifact_file in files_by_format.items()
                }
                downloads = {
                    export_format: client.get(
                        f"/api/v1/artifact-files/{artifact_file['artifact_file_id']}/download",
                        headers=headers,
                    )
                    for export_format, artifact_file in files_by_format.items()
                }
                observations = _export_db_observations(
                    engine,
                    artifact_id=artifact_id,
                    artifact_version_id=artifact_version_id,
                    render_job_id=render_job_id,
                )
                storage_files = [
                    path
                    for path in storage_root.rglob("*")
                    if path.is_file() and path.suffix
                ]
                download_shapes = {
                    export_format: _download_shape(
                        export_format,
                        downloads[export_format].json(),
                    )
                    for export_format in files_by_format
                    if downloads[export_format].status_code == 200
                }
                checks = {
                    "handoff_created": handoff_response.status_code == 200,
                    "artifact_created": artifact_response.status_code == 200,
                    "render_completed": render_response.status_code == 200
                    and render_job["job_status"] == "COMPLETED",
                    "all_formats_rendered": sorted(files_by_format)
                    == sorted(EXPORT_FORMATS),
                    "render_stage_finalized": render_job["current_stage"]
                    == "FINALIZING",
                    "file_readbacks": all(
                        response.status_code == 200
                        for response in file_readbacks.values()
                    ),
                    "text_previews_available": all(
                        previews[export_format].status_code == 200
                        for export_format in ("MD", "HTML_PREVIEW")
                    ),
                    "binary_previews_blocked": all(
                        previews[export_format].status_code == 409
                        and previews[export_format].json()["error_code"]
                        == "ae.artifact_file_preview_unavailable"
                        for export_format in ("DOCX", "PDF")
                    ),
                    "downloads_available": all(
                        response.status_code == 200 for response in downloads.values()
                    ),
                    "download_payload_shapes": download_shapes
                    == {
                        "MD": "text",
                        "HTML_PREVIEW": "text",
                        "DOCX": "base64",
                        "PDF": "base64",
                    },
                    "db_rendered_formats": observations["rendered_formats"]
                    == list(EXPORT_FORMATS),
                    "db_file_rows": observations["file_formats"] == list(EXPORT_FORMATS),
                    "db_link_rows": observations["link_count"] == 8,
                    "local_payloads_written": len(storage_files) == 4,
                    "raw_sensitive_absent": _redaction_safe(
                        rendered,
                        observations,
                        download_shapes,
                        forbidden_fragments=[
                            database_url,
                            database_env,
                            "nuri1004",
                            str(storage_root),
                            "/data/nex-platform",
                            "hidden prompt",
                            "raw source",
                        ],
                    ),
                }
                failed_checks = [key for key, passed in checks.items() if not passed]
                if failed_checks:
                    raise RuntimeError(
                        "AE artifact export PostgreSQL smoke checks failed: "
                        f"{', '.join(failed_checks)}"
                    )
                cleanup = artifact_smoke._cleanup_smoke_rows(
                    engine,
                    artifact_id=artifact_id,
                    artifact_handoff_id=artifact_handoff_id,
                )
                return {
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "artifact_handoff_id": artifact_handoff_id,
                    "artifact_id": artifact_id,
                    "artifact_version_id": artifact_version_id,
                    "render_job_id": render_job_id,
                    "formats": list(EXPORT_FORMATS),
                    "file_ids": {
                        export_format: files_by_format[export_format][
                            "artifact_file_id"
                        ]
                        for export_format in EXPORT_FORMATS
                    },
                    "download_shapes": download_shapes,
                    "storage": {
                        "storage_mode": "local",
                        "materialized_file_count": len(storage_files),
                        "materialized_extensions": sorted(
                            path.suffix.lstrip(".") for path in storage_files
                        ),
                    },
                    "cx_client_call_count": len(cx_client.calls),
                    "db_observations": observations,
                    "checks": checks,
                    "cleanup": cleanup,
                }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        artifact_smoke._cleanup_smoke_rows(
            engine,
            artifact_id=artifact_id,
            artifact_handoff_id=artifact_handoff_id,
        )
        engine.dispose()


def _export_db_observations(
    engine: Any,
    *,
    artifact_id: str,
    artifact_version_id: str,
    render_job_id: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
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
                    SELECT format, mime_type, file_size_bytes
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
        link_count = int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM ae_artifact_links
                    WHERE artifact_file_id IN (
                        SELECT artifact_file_id
                        FROM ae_artifact_files
                        WHERE artifact_version_id = :artifact_version_id
                    )
                    """
                ),
                {"artifact_version_id": artifact_version_id},
            ).scalar()
            or 0
        )
        render_job_status = connection.execute(
            text(
                """
                SELECT job_status
                FROM ae_artifact_render_jobs
                WHERE render_job_id = :render_job_id
                """
            ),
            {"render_job_id": render_job_id},
        ).scalar_one()
        artifact_status = connection.execute(
            text(
                """
                SELECT artifact_status
                FROM ae_artifacts
                WHERE artifact_id = :artifact_id
                """
            ),
            {"artifact_id": artifact_id},
        ).scalar_one()
    return {
        "artifact_status": artifact_status,
        "render_job_status": render_job_status,
        "rendered_formats": _json_array(rendered_formats),
        "file_formats": [str(row["format"]) for row in file_rows],
        "file_count": len(file_rows),
        "link_count": link_count,
        "mime_types": {
            str(row["format"]): str(row["mime_type"]) for row in file_rows
        },
        "file_size_bytes": {
            str(row["format"]): int(row["file_size_bytes"]) for row in file_rows
        },
    }


def _json_array(value: Any) -> list[str]:
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _download_shape(export_format: str, payload: Mapping[str, Any]) -> str:
    if export_format in {"MD", "HTML_PREVIEW"}:
        return "text" if isinstance(payload.get("content"), str) else "invalid"
    content_base64 = payload.get("content_base64")
    if payload.get("content_encoding") != "base64" or not isinstance(
        content_base64,
        str,
    ):
        return "invalid"
    decoded = base64.b64decode(content_base64.encode("ascii"))
    if export_format == "DOCX" and decoded.startswith(b"PK"):
        return "base64"
    if export_format == "PDF" and decoded.startswith(b"%PDF-1.4"):
        return "base64"
    return "invalid"


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    env: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": _safe_detail(detail, env),
    }


def _redaction_safe(
    *payloads: Any,
    forbidden_fragments: list[str],
) -> bool:
    serialized = json.dumps(payloads, ensure_ascii=False, sort_keys=True, default=str)
    return all(fragment not in serialized for fragment in forbidden_fragments)


def _safe_detail(detail: str, env: Mapping[str, str]) -> str:
    safe = detail
    for key in (
        service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE),
        "NEX_AE_ARTIFACT_STORAGE_ROOT",
    ):
        value = env.get(key)
        if value:
            safe = safe.replace(value, f"<redacted:{key}>")
    return safe.replace("nuri1004", "***")


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    for key in (
        service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE),
        "NEX_AE_ARTIFACT_STORAGE_ROOT",
    ):
        value = environ.get(key)
        if value and value in serialized_evidence:
            raise ValueError(f"AE artifact export smoke contains raw {key}.")
    if "nuri1004" in serialized_evidence:
        raise ValueError("AE artifact export smoke contains a database password.")
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError("AE artifact export smoke contains a local data path.")


@contextmanager
def _temporary_env(key: str, value: str) -> Iterator[None]:
    previous = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ae_artifact_export_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_export_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"artifact_id={evidence['artifact_id']} "
            f"version_id={evidence['artifact_version_id']} "
            f"formats={','.join(evidence['formats'])} "
            f"files={evidence['db_observations']['file_count']} "
            f"links={evidence['db_observations']['link_count']} "
            f"storage_files={evidence['storage']['materialized_file_count']} "
            f"deleted_artifacts={evidence['cleanup']['artifacts']} "
            f"deleted_handoffs={evidence['cleanup']['handoffs']}"
        )
    return (
        "ae_artifact_export_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE multi-format artifact export PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_artifact_export_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
