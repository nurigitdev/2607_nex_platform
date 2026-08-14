#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
CX_PATH = ROOT / "services" / "nex-cx"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(CX_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_cx.ingestion import (  # noqa: E402
    UPLOAD_OWNER_RESOLVER_DISABLED,
    ContentIngestionStore,
    register_ingestion_routes,
)
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_engine,
    build_service_app,
    load_env_file,
    redact_database_url,
)
from run_cx_document_library_postgres_smoke import _migration_evidence  # noqa: E402
from run_cx_upload_ownership_postgres_smoke import (  # noqa: E402
    _redaction_safe,
    _service_headers,
    _storage_config,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SMOKE_ENV = "NEX_CX_UPLOADED_SOURCE_EXTRACTION_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_CX_UPLOADED_SOURCE_EXTRACTION_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
SCHEMA_VERSION = "cx_uploaded_source_extraction_postgres_smoke.v1"
SECRET_SOURCE_TEXT = (
    "CX uploaded source extraction PostgreSQL smoke source should not leak"
)


def run_cx_uploaded_source_extraction_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
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
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        migration_result = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_uploaded_source_extraction_smoke(
            database_env=database_env,
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            "migration": _migration_evidence(migration_result),
            **execution,
        }
        assert_evidence_redacted(evidence)
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_uploaded_source_extraction_smoke(
    *,
    database_env: str,
    database_url: str,
    runtime_environ: dict[str, str],
) -> dict[str, object]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.split("-", maxsplit=1)[0]
    tenant_id = f"tenant-uploaded-source-extraction-{suffix}"
    owner_user_id = f"owner-uploaded-source-extraction-{suffix}"
    source_text = f"{SECRET_SOURCE_TEXT} request={request_id}"
    document_id: str | None = None
    source_file_id: str | None = None
    result: dict[str, object] = {}
    engine = build_engine(database_url)
    with tempfile.TemporaryDirectory(prefix="nex-cx-uploaded-source-extraction-smoke-") as temp_dir:
        storage_config = _storage_config(Path(temp_dir))
        app = build_service_app(SERVICE_SPEC)
        persistence = attach_service_persistence_runtime(
            app,
            SERVICE_SPEC,
            environ=runtime_environ,
        )
        if persistence.api_session_factory is None:
            raise RuntimeError(
                "CX PostgreSQL uploaded-source extraction smoke session factory is unavailable"
            )

        repository = SqlAlchemyCxContentRepository(
            persistence.api_session_factory,
            local_source_root=storage_config.source_root,
        )
        store = ContentIngestionStore(content_repository=repository)
        register_ingestion_routes(
            app,
            store=store,
            storage_config=storage_config,
            owner_resolver_mode=UPLOAD_OWNER_RESOLVER_DISABLED,
            database_env=database_env,
            redacted_database_url=redact_database_url(database_url),
            source_kind="postgres-read",
        )
        client = TestClient(app)
        try:
            upload_response = client.post(
                "/api/v1/documents/uploads",
                json={
                    "filename": "cx-uploaded-source-extraction-smoke.txt",
                    "content_type": "text/plain",
                    "content_text": source_text,
                    "tenant_id": tenant_id,
                    "owner_user_id": owner_user_id,
                },
                headers=_service_headers(trace_id=trace_id, request_id=request_id),
            )
            upload_response.raise_for_status()
            upload = upload_response.json()
            document_id = str(upload["document_id"])
            upload_id = str(upload["upload_id"])
            refs = store.get_content_ref(document_id)
            source_file_id = refs["source_file_id"] if refs is not None else None
            source_path = Path(upload["storage"]["source_storage_path"])
            store.source_bytes.pop(upload_id, None)
            store.source_texts.pop(upload_id, None)

            extraction_response = client.post(
                f"/api/v1/jobs/{upload['extraction']['job_id']}/run",
                headers=_service_headers(trace_id=trace_id, request_id=str(uuid4())),
            )
            extraction_response.raise_for_status()
            extraction = extraction_response.json()
            source_reader = extraction.get("source_reader", {})
            artifact_observation = _read_extraction_artifact_observation(
                engine,
                document_id=document_id,
                source_file_id=source_file_id,
                markdown_sha256=extraction["extracted_markdown_sha256"],
            )
            source_observation = _read_source_file_observation(
                engine,
                source_file_id=source_file_id,
            )
            evidence_payload = {
                "source_reader": source_reader,
                "artifact_observation": artifact_observation,
                "source_observation": source_observation,
            }
            checks = {
                "runtime_mode": persistence.mode == "postgres",
                "upload_created": upload_response.status_code == 202
                and upload["dedupe"]["status"] == "CREATED",
                "runtime_source_bytes_evicted": not store.source_bytes_available(upload_id),
                "materialized_source_exists": source_path.exists(),
                "source_checksum_verified_in_db": (
                    source_observation["checksum_verified"] is True
                ),
                "extraction_status_ok": extraction_response.status_code == 200
                and extraction["status"] == "SUCCEEDED",
                "source_reader_fallback_used": (
                    isinstance(source_reader, dict)
                    and source_reader.get("source") == "materialized_local_source_file"
                    and source_reader.get("fallback_used") is True
                ),
                "source_reader_redacted": (
                    isinstance(source_reader, dict)
                    and source_reader.get("storage_key_included") is False
                    and source_reader.get("local_storage_path_included") is False
                    and source_reader.get("raw_source_included") is False
                ),
                "extraction_artifact_persisted": (
                    artifact_observation["artifact_count"] == 1
                ),
                "artifact_hash_matches_response": (
                    artifact_observation["markdown_sha256_matches"] is True
                ),
                "evidence_redacted": _redaction_safe(
                    evidence_payload,
                    forbidden_fragments=[
                        SECRET_SOURCE_TEXT,
                        str(storage_config.source_root),
                        "source_storage_path",
                    ],
                ),
            }
            if not all(checks.values()):
                raise RuntimeError(
                    "CX uploaded-source extraction PostgreSQL smoke checks failed"
                )
            result = {
                "document_id": document_id,
                "source_file_id": source_file_id,
                "extraction": {
                    "status": extraction["status"],
                    "source_reader": source_reader.get("source"),
                    "fallback_used": source_reader.get("fallback_used"),
                    "markdown_char_count": extraction["markdown_char_count"],
                },
                "db_observations": {
                    "source_checksum_verified": source_observation["checksum_verified"],
                    "extraction_artifact_count": artifact_observation["artifact_count"],
                },
                "checks": checks,
            }
        finally:
            result["cleanup_observations"] = _delete_uploaded_source_extraction_rows(
                engine,
                document_id=document_id,
                source_file_id=source_file_id,
            )
    return result


def _read_source_file_observation(
    engine: object,
    *,
    source_file_id: str | None,
) -> dict[str, object]:
    if source_file_id is None:
        return {"checksum_verified": False, "storage_backend": None}
    with engine.begin() as connection:
        row = (
            connection.execute(
                text(
                    """
                    SELECT storage_backend, checksum_verified_at
                    FROM cx_source_files
                    WHERE source_file_id = :source_file_id
                    """
                ),
                {"source_file_id": source_file_id},
            )
            .mappings()
            .first()
        )
    if row is None:
        return {"checksum_verified": False, "storage_backend": None}
    return {
        "checksum_verified": row["checksum_verified_at"] is not None,
        "storage_backend": row["storage_backend"],
    }


def _read_extraction_artifact_observation(
    engine: object,
    *,
    document_id: str | None,
    source_file_id: str | None,
    markdown_sha256: str,
) -> dict[str, object]:
    if document_id is None or source_file_id is None:
        return {"artifact_count": 0, "markdown_sha256_matches": False}
    with engine.begin() as connection:
        row = (
            connection.execute(
                text(
                    """
                    SELECT count(*) AS artifact_count
                    FROM cx_extraction_artifacts
                    WHERE content_object_id = :document_id
                      AND source_file_id = :source_file_id
                      AND markdown_sha256 = :markdown_sha256
                    """
                ),
                {
                    "document_id": document_id,
                    "source_file_id": source_file_id,
                    "markdown_sha256": markdown_sha256,
                },
            )
            .mappings()
            .one()
        )
    artifact_count = int(row["artifact_count"])
    return {
        "artifact_count": artifact_count,
        "markdown_sha256_matches": artifact_count == 1,
    }


def _delete_uploaded_source_extraction_rows(
    engine: object,
    *,
    document_id: str | None,
    source_file_id: str | None,
) -> dict[str, object]:
    before = _cleanup_counts(
        engine,
        document_id=document_id,
        source_file_id=source_file_id,
    )
    with engine.begin() as connection:
        if document_id is not None:
            connection.execute(
                text(
                    """
                    DELETE FROM cx_extraction_artifacts
                    WHERE content_object_id = :document_id
                    """
                ),
                {"document_id": document_id},
            )
            connection.execute(
                text(
                    """
                    DELETE FROM cx_content_acl_entries
                    WHERE content_object_id = :document_id
                    """
                ),
                {"document_id": document_id},
            )
            connection.execute(
                text(
                    """
                    DELETE FROM cx_content_objects
                    WHERE content_object_id = :document_id
                    """
                ),
                {"document_id": document_id},
            )
        if source_file_id is not None:
            connection.execute(
                text(
                    """
                    DELETE FROM cx_source_files
                    WHERE source_file_id = :source_file_id
                    """
                ),
                {"source_file_id": source_file_id},
            )
    after = _cleanup_counts(
        engine,
        document_id=document_id,
        source_file_id=source_file_id,
    )
    return {"before": before, "after": after}


def _cleanup_counts(
    engine: object,
    *,
    document_id: str | None,
    source_file_id: str | None,
) -> dict[str, int]:
    with engine.begin() as connection:
        extraction_count = (
            0
            if document_id is None
            else int(
                connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM cx_extraction_artifacts
                        WHERE content_object_id = :document_id
                        """
                    ),
                    {"document_id": document_id},
                ).scalar_one()
            )
        )
        content_count = (
            0
            if document_id is None
            else int(
                connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM cx_content_objects
                        WHERE content_object_id = :document_id
                        """
                    ),
                    {"document_id": document_id},
                ).scalar_one()
            )
        )
        source_count = (
            0
            if source_file_id is None
            else int(
                connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM cx_source_files
                        WHERE source_file_id = :source_file_id
                        """
                    ),
                    {"source_file_id": source_file_id},
                ).scalar_one()
            )
        )
    return {
        "extraction_artifact_rows": extraction_count,
        "content_object_rows": content_count,
        "source_file_rows": source_count,
    }


def assert_evidence_redacted(evidence: object) -> None:
    rendered = json.dumps(evidence, default=str, ensure_ascii=False)
    forbidden = [
        SECRET_SOURCE_TEXT,
        "source_storage_path",
        "nex-cx-uploaded-source-extraction-smoke-",
        "/data/nex-platform",
    ]
    for fragment in forbidden:
        if fragment in rendered:
            raise ValueError("CX uploaded-source extraction smoke evidence is not redacted.")


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
) -> dict[str, object]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"cx_uploaded_source_extraction_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        extraction = evidence.get("extraction", {})
        return (
            "cx_uploaded_source_extraction_postgres_smoke=pass "
            f"profile={evidence['profile']} "
            f"db_env={evidence['database_env']} "
            f"source_reader={extraction.get('source_reader') if isinstance(extraction, dict) else None} "
            f"artifact_count={evidence['db_observations']['extraction_artifact_count']}"
        )
    return (
        "cx_uploaded_source_extraction_postgres_smoke=fail "
        f"profile={evidence.get('profile')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the protected CX uploaded-source extraction PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_env_file(ROOT / ".env")
    args = build_parser().parse_args(argv)
    evidence = run_cx_uploaded_source_extraction_postgres_smoke()
    if args.output:
        serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{serialized}\n", encoding="utf-8")
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
