#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

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
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "ae_artifact_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ARTIFACT_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_ARTIFACT_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = "nex-ae-api"
DEFAULT_PROFILE = "test"
MIGRATION_VERSION = "0406_ae_artifact_handoff_trace_request_columns"
EXPECTED_TABLES = {
    "ae_artifact_handoffs",
    "ae_artifacts",
    "ae_artifact_source_refs",
    "ae_artifact_versions",
    "ae_artifact_render_jobs",
    "ae_artifact_files",
    "ae_artifact_links",
}
EXPECTED_INDEXES = {
    "ux_ae_artifact_handoffs_request",
    "idx_ae_artifact_handoffs_owner_time",
    "idx_ae_artifact_handoffs_generation",
    "ux_ae_artifacts_request",
    "idx_ae_artifacts_owner_time",
    "idx_ae_artifacts_status_time",
    "ux_ae_artifact_versions_artifact_no",
    "idx_ae_artifact_files_hash",
    "ux_ae_artifact_links_file_type",
}
EXPECTED_JSONB_TYPES = {
    "artifact_target_formats": "jsonb",
    "owner_actor_ref": "jsonb",
    "source_quality_summary": "jsonb",
    "rendered_formats": "jsonb",
    "created_by_actor_ref": "jsonb",
}
EXPECTED_HANDOFF_CORRELATION_COLUMNS = ("request_id", "trace_id")


class FakeCxArtifactSourceClient:
    def __init__(
        self,
        *,
        suffix: str,
        request_id: str,
        trace_id: str,
    ) -> None:
        self.suffix = suffix
        self.request_id = request_id
        self.trace_id = trace_id
        self.calls: list[tuple[str, str]] = []

    def get_generation(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("generation", cx_generation_id))
        return _generation_record(
            suffix=self.suffix,
            request_id=request_id,
            trace_id=trace_id,
        )

    def get_structured_draft(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("draft", cx_generation_id))
        return _structured_draft(
            suffix=self.suffix,
            request_id=request_id,
            trace_id=trace_id,
        )


def run_ae_artifact_postgres_smoke(
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
    if profile != "test":
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
            env=env,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_ae_artifact_smoke(
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


def _execute_ae_artifact_smoke(
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
    artifact_file_id: str | None = None
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        with tempfile.TemporaryDirectory(prefix="nex-ae-artifact-smoke-") as storage_dir:
            storage_root = Path(storage_dir) / "artifact-storage"
            with _temporary_env("NEX_AE_ARTIFACT_STORAGE_ROOT", str(storage_root)):
                app = build_service_app(SERVICE_SPECS[SERVICE_ID])
                app.state.nex_persistence = SimpleNamespace(
                    api_session_factory=session_factory
                )
                cx_client = FakeCxArtifactSourceClient(
                    suffix=suffix,
                    request_id=request_id,
                    trace_id=trace_id,
                )
                register_artifact_handoff_routes(app, cx_client=cx_client)
                client = TestClient(app)
                headers = _auth_headers(request_id=request_id, trace_id=trace_id)

                handoff_response = client.post(
                    "/api/v1/artifact-handoffs",
                    json=_artifact_handoff_payload(suffix),
                    headers={
                        **headers,
                        "Idempotency-Key": f"artifact-handoff-request-{suffix}",
                    },
                )
                if handoff_response.status_code != 200:
                    raise RuntimeError("AE artifact handoff create route failed")
                handoff = handoff_response.json()
                artifact_handoff_id = handoff["artifact_handoff_id"]

                handoff_readback = client.get(
                    f"/api/v1/artifact-handoffs/{artifact_handoff_id}",
                    headers=headers,
                )
                artifact_response = client.post(
                    "/api/v1/artifacts",
                    json={"artifact_handoff_id": artifact_handoff_id},
                    headers={
                        **headers,
                        "Idempotency-Key": f"artifact-create-request-{suffix}",
                    },
                )
                if artifact_response.status_code != 200:
                    raise RuntimeError("AE artifact create route failed")
                artifact = artifact_response.json()
                artifact_id = artifact["artifact_id"]

                artifact_readback = client.get(
                    f"/api/v1/artifacts/{artifact_id}",
                    headers=headers,
                )
                versions_before = client.get(
                    f"/api/v1/artifacts/{artifact_id}/versions",
                    headers=headers,
                )
                render_response = client.post(
                    f"/api/v1/artifacts/{artifact_id}/render-jobs",
                    json={},
                    headers={
                        **headers,
                        "Idempotency-Key": f"artifact-render-request-{suffix}",
                    },
                )
                if render_response.status_code != 200:
                    raise RuntimeError("AE artifact render route failed")
                rendered = render_response.json()
                rendered_artifact = rendered["artifact"]
                render_job = rendered["render_job"]
                artifact_version_id = rendered_artifact["current_version_id"]
                render_job_id = render_job["render_job_id"]
                artifact_file = rendered_artifact["files"][0]
                artifact_file_id = artifact_file["artifact_file_id"]

                versions_after = client.get(
                    f"/api/v1/artifacts/{artifact_id}/versions",
                    headers=headers,
                )
                render_job_readback = client.get(
                    f"/api/v1/artifact-render-jobs/{render_job_id}",
                    headers=headers,
                )
                file_readback = client.get(
                    f"/api/v1/artifact-files/{artifact_file_id}",
                    headers=headers,
                )
                preview_response = client.get(
                    f"/api/v1/artifact-files/{artifact_file_id}/preview",
                    headers=headers,
                )
                download_response = client.get(
                    f"/api/v1/artifact-files/{artifact_file_id}/download",
                    headers=headers,
                )

                observations = _db_observations(
                    engine,
                    artifact_handoff_id=artifact_handoff_id,
                    artifact_id=artifact_id,
                    artifact_version_id=artifact_version_id,
                    render_job_id=render_job_id,
                    artifact_file_id=artifact_file_id,
                )
                storage_file_count = sum(1 for _ in storage_root.rglob("*.md"))
                checks = {
                    "handoff_created": handoff_response.status_code == 200,
                    "handoff_readback": handoff_readback.status_code == 200
                    and handoff_readback.json()["artifact_handoff_id"]
                    == artifact_handoff_id,
                    "artifact_created": artifact_response.status_code == 200,
                    "artifact_readback": artifact_readback.status_code == 200
                    and artifact_readback.json()["artifact_id"] == artifact_id,
                    "versions_empty_before_render": versions_before.status_code == 200
                    and versions_before.json()["versions"] == [],
                    "render_completed": render_response.status_code == 200
                    and render_job["job_status"] == "COMPLETED",
                    "versions_ready_after_render": versions_after.status_code == 200
                    and len(versions_after.json()["versions"]) == 1,
                    "render_job_readback": render_job_readback.status_code == 200
                    and render_job_readback.json()["render_job_id"] == render_job_id,
                    "file_readback": file_readback.status_code == 200
                    and file_readback.json()["artifact_file_id"] == artifact_file_id,
                    "preview_readback": preview_response.status_code == 200
                    and "Grounded answer" in preview_response.json()["text_preview"],
                    "download_readback": download_response.status_code == 200
                    and download_response.json()["content"].startswith("# Artifact"),
                    "local_payload_written": storage_file_count == 1,
                    "table_family_present": observations["tables_present"]
                    == sorted(EXPECTED_TABLES),
                    "migration_recorded": observations["migration_recorded"] is True,
                    "row_counts": observations["row_counts"]
                    == {
                        "handoffs": 1,
                        "artifacts": 1,
                        "source_refs": 1,
                        "versions": 1,
                        "render_jobs": 1,
                        "files": 1,
                        "links": 2,
                    },
                    "jsonb_columns": observations["jsonb_columns"]
                    == EXPECTED_JSONB_TYPES,
                    "handoff_correlation_columns": observations[
                        "handoff_correlation_columns"
                    ]
                    == list(EXPECTED_HANDOFF_CORRELATION_COLUMNS),
                    "indexes_present": observations["indexes_present"]
                    == sorted(EXPECTED_INDEXES),
                    "logical_storage_ref": observations["storage_ref"].startswith(
                        "ae://artifacts/"
                    ),
                    "raw_sensitive_absent": _redaction_safe(
                        handoff,
                        artifact,
                        rendered,
                        preview_response.json(),
                        file_readback.json(),
                        observations,
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
                        "AE artifact PostgreSQL smoke checks failed: "
                        f"{', '.join(failed_checks)}"
                    )
                cleanup = _cleanup_smoke_rows(
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
                    "artifact_file_id": artifact_file_id,
                    "storage": {
                        "storage_mode": "local",
                        "markdown_file_count": storage_file_count,
                        "logical_storage_ref": artifact_file["storage_ref"],
                    },
                    "cx_client_call_count": len(cx_client.calls),
                    "db_observations": observations,
                    "checks": checks,
                    "cleanup": cleanup,
                }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        _cleanup_smoke_rows(
            engine,
            artifact_id=artifact_id,
            artifact_handoff_id=artifact_handoff_id,
        )
        engine.dispose()


def _artifact_handoff_payload(suffix: str) -> dict[str, Any]:
    return {
        "cx_generation_id": f"cx-gen-artifact-smoke-{suffix}",
        "chat_document_id": f"chat-doc-artifact-smoke-{suffix}",
        "interaction_id": f"interaction-artifact-smoke-{suffix}",
        "workspace_id": f"workspace-artifact-smoke-{suffix}",
        "tenant_id": f"tenant-artifact-smoke-{suffix}",
        "owner_user_id": f"owner-artifact-smoke-{suffix}",
        "artifact_intent": "create_and_export",
        "target_formats": ["MD", "HTML_PREVIEW"],
        "artifact_title": f"Artifact Smoke {suffix}",
        "language": "ko",
        "actor_claims_ref": {
            "actor_type": "user",
            "actor_id": f"owner-artifact-smoke-{suffix}",
            "tenant_id": f"tenant-artifact-smoke-{suffix}",
        },
    }


def _generation_record(
    *,
    suffix: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    return {
        "cx_generation_id": f"cx-gen-artifact-smoke-{suffix}",
        "status": "COMPLETED",
        "trace_id": trace_id,
        "request_id": request_id,
        "request_metadata": {
            "structured_draft_id": f"draft-artifact-smoke-{suffix}",
            "grounding_required": True,
            "retrieval_package_id": f"retrieval-artifact-smoke-{suffix}",
            "retrieval_package_hash": "d" * 64,
            "selected_evidence_count": 2,
        },
    }


def _structured_draft(
    *,
    suffix: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    return {
        "structured_draft_schema_version": "cx_structured_draft.v1",
        "structured_draft_id": f"draft-artifact-smoke-{suffix}",
        "cx_generation_id": f"cx-gen-artifact-smoke-{suffix}",
        "status": "VALIDATED",
        "trace_id": trace_id,
        "request_id": request_id,
        "title": f"Artifact Smoke {suffix}",
        "summary": "Safe artifact summary.",
        "content_hash": "c" * 64,
        "sections": [
            {
                "section_id": f"section-artifact-smoke-{suffix}",
                "ordinal": 1,
                "heading": "Overview",
                "blocks": [
                    {
                        "block_id": f"block-artifact-smoke-{suffix}",
                        "block_type": "paragraph",
                        "text_hash": "e" * 64,
                        "text_preview": "Grounded answer [1].",
                    }
                ],
            }
        ],
        "citations": [
            {
                "citation_label": "[1]",
                "evidence_id": f"evidence-artifact-smoke-{suffix}",
                "retrieval_package_id": f"retrieval-artifact-smoke-{suffix}",
                "valid": True,
                "validation_error": None,
            }
        ],
        "validation": {
            "validator_profile_id": "mock-structured-draft-validator-v1",
            "citation_status": "VALIDATED",
            "errors": [],
            "warnings": [],
        },
    }


def _auth_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ag", audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _db_observations(
    engine: Any,
    *,
    artifact_handoff_id: str,
    artifact_id: str,
    artifact_version_id: str,
    render_job_id: str,
    artifact_file_id: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        tables_present = sorted(
            table_name
            for table_name in EXPECTED_TABLES
            if connection.execute(
                text(f"SELECT to_regclass('public.{table_name}')")
            ).scalar()
            == table_name
        )
        migration_recorded = connection.execute(
            text(
                """
                SELECT EXISTS(
                    SELECT 1 FROM schema_migrations WHERE version = :version
                )
                """
            ),
            {"version": MIGRATION_VERSION},
        ).scalar()
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
                """
                SELECT count(*) FROM ae_artifact_source_refs
                WHERE artifact_id = :artifact_id
                """,
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
                WHERE artifact_file_id = :artifact_file_id
                """,
                {"artifact_file_id": artifact_file_id},
            ),
            "links": _scalar_count(
                connection,
                """
                SELECT count(*)
                FROM ae_artifact_links
                WHERE artifact_file_id = :artifact_file_id
                """,
                {"artifact_file_id": artifact_file_id},
            ),
        }
        jsonb_row = (
            connection.execute(
                text(
                    """
                    SELECT
                        pg_typeof(a.target_formats)::text AS artifact_target_formats,
                        pg_typeof(a.owner_actor_ref)::text AS owner_actor_ref,
                        pg_typeof(s.quality_summary)::text AS source_quality_summary,
                        pg_typeof(v.rendered_formats)::text AS rendered_formats,
                        pg_typeof(l.created_by_actor_ref)::text AS created_by_actor_ref
                    FROM ae_artifacts a
                    JOIN ae_artifact_source_refs s ON s.artifact_id = a.artifact_id
                    JOIN ae_artifact_versions v ON v.artifact_id = a.artifact_id
                    JOIN ae_artifact_files f ON f.artifact_version_id = v.artifact_version_id
                    JOIN ae_artifact_links l ON l.artifact_file_id = f.artifact_file_id
                    WHERE a.artifact_id = :artifact_id
                    LIMIT 1
                    """
                ),
                {"artifact_id": artifact_id},
            )
            .mappings()
            .first()
        )
        indexes = (
            connection.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename IN (
                        'ae_artifact_handoffs',
                        'ae_artifacts',
                        'ae_artifact_versions',
                        'ae_artifact_files',
                        'ae_artifact_links'
                      )
                    ORDER BY indexname
                    """
                )
            )
            .scalars()
            .all()
        )
        handoff_correlation_columns = (
            connection.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'ae_artifact_handoffs'
                      AND column_name IN ('trace_id', 'request_id')
                    ORDER BY column_name
                    """
                )
            )
            .scalars()
            .all()
        )
        storage_ref = connection.execute(
            text(
                """
                SELECT storage_ref FROM ae_artifact_files
                WHERE artifact_file_id = :artifact_file_id
                """
            ),
            {"artifact_file_id": artifact_file_id},
        ).scalar_one()
    return {
        "tables_present": tables_present,
        "migration_recorded": bool(migration_recorded),
        "row_counts": row_counts,
        "jsonb_columns": dict(jsonb_row) if jsonb_row else {},
        "handoff_correlation_columns": list(handoff_correlation_columns),
        "indexes_present": sorted(set(indexes).intersection(EXPECTED_INDEXES)),
        "storage_ref": storage_ref,
    }


def _scalar_count(connection: Any, sql: str, params: dict[str, str]) -> int:
    return int(connection.execute(text(sql), params).scalar() or 0)


def _cleanup_smoke_rows(
    engine: Any,
    *,
    artifact_id: str | None,
    artifact_handoff_id: str | None,
) -> dict[str, int]:
    deleted = {"artifacts": 0, "handoffs": 0}
    try:
        with engine.begin() as connection:
            if artifact_id:
                result = connection.execute(
                    text("DELETE FROM ae_artifacts WHERE artifact_id = :artifact_id"),
                    {"artifact_id": artifact_id},
                )
                deleted["artifacts"] = int(result.rowcount or 0)
            if artifact_handoff_id:
                result = connection.execute(
                    text(
                        """
                        DELETE FROM ae_artifact_handoffs
                        WHERE artifact_handoff_id = :artifact_handoff_id
                        """
                    ),
                    {"artifact_handoff_id": artifact_handoff_id},
                )
                deleted["handoffs"] = int(result.rowcount or 0)
    except SQLAlchemyError:
        return deleted
    return deleted


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
            raise ValueError(f"AE artifact smoke contains raw {key}.")
    if "nuri1004" in serialized_evidence:
        raise ValueError("AE artifact smoke contains a database password.")
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError("AE artifact smoke contains a local data path.")


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
        return f"ae_artifact_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"artifact_id={evidence['artifact_id']} "
            f"rows={sum(evidence['db_observations']['row_counts'].values())} "
            f"markdown_files={evidence['storage']['markdown_file_count']} "
            f"deleted_artifacts={evidence['cleanup']['artifacts']} "
            f"deleted_handoffs={evidence['cleanup']['handoffs']}"
        )
    return (
        "ae_artifact_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE artifact PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_artifact_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
