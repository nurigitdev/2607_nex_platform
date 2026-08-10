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


SMOKE_ENV = "NEX_CX_UPLOAD_DUPLICATE_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_CX_UPLOAD_DUPLICATE_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
SCHEMA_VERSION = "cx_upload_duplicate_postgres_smoke.v1"
SECRET_SOURCE_TEXT = "CX upload duplicate PostgreSQL smoke source should not leak"


def run_cx_upload_duplicate_postgres_smoke(
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
        run_service_migrations(SERVICE_ID, database_url=database_url, profile=profile)
        execution = _execute_upload_duplicate_smoke(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            **execution,
        }
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_upload_duplicate_smoke(
    *,
    database_url: str,
    runtime_environ: dict[str, str],
) -> dict[str, object]:
    run_id = str(uuid4())
    trace_id = uuid4().hex
    tenant_id = f"tenant-upload-dedupe-{run_id.split('-', maxsplit=1)[0]}"
    owner_a = f"owner-upload-dedupe-{run_id.split('-', maxsplit=1)[0]}-a"
    owner_b = f"owner-upload-dedupe-{run_id.split('-', maxsplit=1)[0]}-b"
    source_text = f"{SECRET_SOURCE_TEXT} request={run_id}"
    document_ids: list[str | None] = []
    source_file_ids: list[str | None] = []
    source_sha256: str | None = None
    engine = build_engine(database_url)
    with tempfile.TemporaryDirectory(prefix="nex-cx-upload-duplicate-smoke-") as temp_dir:
        storage_config = _storage_config(Path(temp_dir))
        app = build_service_app(SERVICE_SPEC)
        persistence = attach_service_persistence_runtime(
            app,
            SERVICE_SPEC,
            environ=runtime_environ,
        )
        if persistence.api_session_factory is None:
            raise RuntimeError(
                "CX PostgreSQL upload duplicate smoke session factory is unavailable"
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
        )
        client = TestClient(app)
        try:
            first_status, first_payload = _upload_document(
                client,
                tenant_id=tenant_id,
                owner_user_id=owner_a,
                filename="cx-upload-duplicate-first.txt",
                source_text=source_text,
                trace_id=trace_id,
                request_id=str(uuid4()),
            )
            duplicate_status, duplicate_payload = _upload_document(
                client,
                tenant_id=tenant_id,
                owner_user_id=owner_a,
                filename="cx-upload-duplicate-renamed.txt",
                source_text=source_text,
                trace_id=trace_id,
                request_id=str(uuid4()),
            )
            other_owner_status, other_owner_payload = _upload_document(
                client,
                tenant_id=tenant_id,
                owner_user_id=owner_b,
                filename="cx-upload-duplicate-other-owner.txt",
                source_text=source_text,
                trace_id=trace_id,
                request_id=str(uuid4()),
            )
            owner_a_document_id = str(first_payload["document_id"])
            duplicate_document_id = str(duplicate_payload["document_id"])
            owner_b_document_id = str(other_owner_payload["document_id"])
            document_ids.extend([owner_a_document_id, owner_b_document_id])
            source_sha256 = str(first_payload["source_sha256"])
            owner_a_refs = store.get_content_ref(owner_a_document_id)
            owner_b_refs = store.get_content_ref(owner_b_document_id)
            owner_a_source_file_id = (
                owner_a_refs["source_file_id"] if owner_a_refs is not None else None
            )
            owner_b_source_file_id = (
                owner_b_refs["source_file_id"] if owner_b_refs is not None else None
            )
            source_file_ids.extend([owner_a_source_file_id, owner_b_source_file_id])
            owner_a_count = _count_active_owner_source_documents(
                engine,
                tenant_id=tenant_id,
                owner_user_id=owner_a,
                source_sha256=source_sha256,
            )
            owner_b_count = _count_active_owner_source_documents(
                engine,
                tenant_id=tenant_id,
                owner_user_id=owner_b,
                source_sha256=source_sha256,
            )
            source_file_count = _count_source_files_for_sha(
                engine,
                source_sha256=source_sha256,
            )
            active_content_count = _count_active_source_documents(
                engine,
                tenant_id=tenant_id,
                source_sha256=source_sha256,
            )
            owner_acl_count = _count_owner_acl_rows_for_source(
                engine,
                tenant_id=tenant_id,
                source_sha256=source_sha256,
            )
            checks = {
                "runtime_mode": persistence.mode == "postgres",
                "first_upload_created": first_status == 202
                and first_payload["dedupe"]["status"] == "CREATED",
                "duplicate_upload_reused": duplicate_status == 200
                and duplicate_payload["dedupe"]["status"] == "ALREADY_EXISTS",
                "duplicate_document_id_reused": duplicate_document_id
                == owner_a_document_id,
                "duplicate_existing_document_reported": (
                    duplicate_payload["dedupe"]["existing_document_id"]
                    == owner_a_document_id
                ),
                "other_owner_created": other_owner_status == 202
                and other_owner_payload["dedupe"]["status"] == "CREATED",
                "other_owner_document_distinct": owner_b_document_id
                != owner_a_document_id,
                "source_file_reused_across_owners": owner_a_source_file_id
                == owner_b_source_file_id,
                "same_owner_active_content_count": owner_a_count == 1,
                "other_owner_active_content_count": owner_b_count == 1,
                "source_file_count": source_file_count == 1,
                "active_content_count": active_content_count == 2,
                "owner_acl_count": owner_acl_count == 2,
                "raw_payload_absent": _redaction_safe(
                    first_payload,
                    duplicate_payload,
                    other_owner_payload,
                    forbidden_fragments=[SECRET_SOURCE_TEXT],
                ),
            }
            if not all(checks.values()):
                raise RuntimeError("CX upload duplicate PostgreSQL smoke checks failed")
            return {
                "document_id": owner_a_document_id,
                "duplicate_document_id": duplicate_document_id,
                "other_owner_document_id": owner_b_document_id,
                "source_file_id": owner_a_source_file_id,
                "source_sha256": source_sha256,
                "checks": checks,
            }
        finally:
            _delete_upload_duplicate_smoke_rows(
                engine,
                document_ids=document_ids,
                source_file_ids=source_file_ids,
            )


def _upload_document(
    client: TestClient,
    *,
    tenant_id: str,
    owner_user_id: str,
    filename: str,
    source_text: str,
    trace_id: str,
    request_id: str,
) -> tuple[int, dict[str, Any]]:
    response = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": filename,
            "content_type": "text/plain",
            "content_text": source_text,
            "tenant_id": tenant_id,
            "owner_user_id": owner_user_id,
        },
        headers=_service_headers(trace_id=trace_id, request_id=request_id),
    )
    response.raise_for_status()
    return response.status_code, response.json()


def _count_active_owner_source_documents(
    engine: object,
    *,
    tenant_id: str,
    owner_user_id: str,
    source_sha256: str,
) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM cx_content_objects
                    WHERE tenant_ref_type = 'oa.tenant'
                      AND tenant_ref_id = :tenant_id
                      AND owner_subject_ref_type = 'oa.user'
                      AND owner_subject_ref_id = :owner_user_id
                      AND source_sha256 = :source_sha256
                      AND lifecycle_status = 'ACTIVE'
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "owner_user_id": owner_user_id,
                    "source_sha256": source_sha256,
                },
            ).scalar_one()
        )


def _count_active_source_documents(
    engine: object,
    *,
    tenant_id: str,
    source_sha256: str,
) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM cx_content_objects
                    WHERE tenant_ref_type = 'oa.tenant'
                      AND tenant_ref_id = :tenant_id
                      AND source_sha256 = :source_sha256
                      AND lifecycle_status = 'ACTIVE'
                    """
                ),
                {"tenant_id": tenant_id, "source_sha256": source_sha256},
            ).scalar_one()
        )


def _count_source_files_for_sha(
    engine: object,
    *,
    source_sha256: str,
) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM cx_source_files
                    WHERE source_sha256 = :source_sha256
                    """
                ),
                {"source_sha256": source_sha256},
            ).scalar_one()
        )


def _count_owner_acl_rows_for_source(
    engine: object,
    *,
    tenant_id: str,
    source_sha256: str,
) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM cx_content_acl_entries AS acl
                    JOIN cx_content_objects AS content
                      ON content.content_object_id = acl.content_object_id
                    WHERE content.tenant_ref_type = 'oa.tenant'
                      AND content.tenant_ref_id = :tenant_id
                      AND content.source_sha256 = :source_sha256
                      AND content.lifecycle_status = 'ACTIVE'
                      AND acl.permission = 'owner'
                    """
                ),
                {"tenant_id": tenant_id, "source_sha256": source_sha256},
            ).scalar_one()
        )


def _delete_upload_duplicate_smoke_rows(
    engine: object,
    *,
    document_ids: list[str | None],
    source_file_ids: list[str | None],
) -> None:
    unique_document_ids = _unique_present_values(document_ids)
    unique_source_file_ids = _unique_present_values(source_file_ids)
    with engine.begin() as connection:
        for document_id in unique_document_ids:
            connection.execute(
                text(
                    """
                    DELETE FROM cx_content_acl_entries
                    WHERE content_object_id = :document_id
                    """
                ),
                {"document_id": document_id},
            )
        for document_id in unique_document_ids:
            connection.execute(
                text(
                    """
                    DELETE FROM cx_content_objects
                    WHERE content_object_id = :document_id
                    """
                ),
                {"document_id": document_id},
            )
        for source_file_id in unique_source_file_ids:
            connection.execute(
                text(
                    """
                    DELETE FROM cx_source_files
                    WHERE source_file_id = :source_file_id
                      AND NOT EXISTS (
                        SELECT 1
                        FROM cx_content_objects
                        WHERE cx_content_objects.source_file_id = :source_file_id
                      )
                    """
                ),
                {"source_file_id": source_file_id},
            )


def _unique_present_values(values: list[str | None]) -> list[str]:
    unique_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None or value in seen:
            continue
        unique_values.append(value)
        seen.add(value)
    return unique_values


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
        return f"cx_upload_duplicate_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "cx_upload_duplicate_postgres_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']}"
        )
    return (
        "cx_upload_duplicate_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional CX upload duplicate PostgreSQL smoke."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_cx_upload_duplicate_postgres_smoke()
    output = (
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False)
    )
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
