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

from nex_cx.document_library import register_document_library_routes  # noqa: E402
from nex_cx.ingestion import ContentIngestionStore, register_ingestion_routes  # noqa: E402
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
    _delete_smoke_upload_rows,
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


SMOKE_ENV = "NEX_CX_DOCUMENT_LIBRARY_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_CX_DOCUMENT_LIBRARY_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
SCHEMA_VERSION = "cx_document_library_postgres_smoke.v1"
SECRET_OWNER_A_SOURCE = "CX document library PostgreSQL smoke owner A source"
SECRET_OWNER_B_SOURCE = "CX document library PostgreSQL smoke owner B source"


def run_cx_document_library_postgres_smoke(
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
        execution = _execute_document_library_smoke(
            database_env=database_env,
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
            "migration": _migration_evidence(migration_result),
            **execution,
        }
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_document_library_smoke(
    *,
    database_env: str,
    database_url: str,
    runtime_environ: dict[str, str],
) -> dict[str, object]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    owner_a_document_id: str | None = None
    owner_a_source_file_id: str | None = None
    owner_b_document_id: str | None = None
    owner_b_source_file_id: str | None = None
    result: dict[str, object] = {}
    engine = build_engine(database_url)
    with tempfile.TemporaryDirectory(prefix="nex-cx-document-library-smoke-") as temp_dir:
        storage_config = _storage_config(Path(temp_dir))
        app = build_service_app(SERVICE_SPEC)
        persistence = attach_service_persistence_runtime(
            app,
            SERVICE_SPEC,
            environ=runtime_environ,
        )
        if persistence.api_session_factory is None:
            raise RuntimeError(
                "CX PostgreSQL document library session factory is unavailable"
            )

        repository = SqlAlchemyCxContentRepository(
            persistence.api_session_factory,
            local_source_root=storage_config.source_root,
        )
        store = ContentIngestionStore(content_repository=repository)
        register_ingestion_routes(app, store=store, storage_config=storage_config)
        register_document_library_routes(
            app,
            store=store,
            database_env=database_env,
            redacted_database_url=redact_database_url(database_url),
            source_kind="postgres-read",
        )
        client = TestClient(app)
        try:
            suffix = request_id.split("-", maxsplit=1)[0]
            owner_a = f"owner-library-smoke-{suffix}-a"
            owner_b = f"owner-library-smoke-{suffix}-b"
            tenant_id = f"tenant-library-smoke-{suffix}"
            owner_a_payload = _upload_document(
                client,
                tenant_id=tenant_id,
                owner_user_id=owner_a,
                source_text=f"{SECRET_OWNER_A_SOURCE} request={request_id}",
                trace_id=trace_id,
                request_id=request_id,
            )
            owner_a_document_id = str(owner_a_payload["document_id"])
            owner_a_refs = store.get_content_ref(owner_a_document_id)
            owner_a_source_file_id = (
                owner_a_refs["source_file_id"] if owner_a_refs is not None else None
            )
            owner_b_payload = _upload_document(
                client,
                tenant_id=tenant_id,
                owner_user_id=owner_b,
                source_text=f"{SECRET_OWNER_B_SOURCE} request={request_id}",
                trace_id=trace_id,
                request_id=request_id,
            )
            owner_b_document_id = str(owner_b_payload["document_id"])
            owner_b_refs = store.get_content_ref(owner_b_document_id)
            owner_b_source_file_id = (
                owner_b_refs["source_file_id"] if owner_b_refs is not None else None
            )
            list_response = client.get(
                "/api/v1/documents",
                params={
                    "tenant_id": tenant_id,
                    "owner_user_id": owner_a,
                    "limit": 10,
                },
                headers=_service_headers(trace_id=trace_id, request_id=request_id),
            )
            list_response.raise_for_status()
            projection = list_response.json()
            persisted_owner_a_count = _count_active_owner_documents(
                engine,
                tenant_id=tenant_id,
                owner_user_id=owner_a,
            )
            persisted_owner_b_count = _count_active_owner_documents(
                engine,
                tenant_id=tenant_id,
                owner_user_id=owner_b,
            )
            returned_document_ids = [
                str(item["document_id"]) for item in projection.get("documents", [])
            ]
            checks = {
                "runtime_mode": persistence.mode == "postgres",
                "api_upload_status_created": owner_a_payload["document_id"] is not None
                and owner_b_payload["document_id"] is not None,
                "list_status_ok": list_response.status_code == 200,
                "source_metadata_uses_test_db": projection["source"]["database_env"]
                == database_env,
                "projection_schema_version": projection["projection_schema_version"]
                == "cx_document_library_projection.v1",
                "owner_scope_filtered": returned_document_ids == [owner_a_document_id],
                "other_owner_excluded": owner_b_document_id not in returned_document_ids,
                "persisted_owner_a_count": persisted_owner_a_count == 1,
                "persisted_owner_b_count": persisted_owner_b_count == 1,
                "raw_payload_absent": _redaction_safe(
                    projection,
                    forbidden_fragments=[
                        SECRET_OWNER_A_SOURCE,
                        SECRET_OWNER_B_SOURCE,
                        "source_storage_path",
                        str(storage_config.source_root),
                    ],
                ),
            }
            if not all(checks.values()):
                raise RuntimeError("CX document library PostgreSQL smoke checks failed")
            result = {
                "document_id": owner_a_document_id,
                "other_owner_document_id": owner_b_document_id,
                "returned_count": len(returned_document_ids),
                "db_observations": {
                    "owner_a_active_content_count": persisted_owner_a_count,
                    "owner_b_active_content_count": persisted_owner_b_count,
                    "listed_document_count": len(returned_document_ids),
                    "listed_document_ids": returned_document_ids,
                },
                "checks": checks,
            }
        finally:
            cleanup_observations = _delete_document_library_smoke_rows(
                engine,
                entries=[
                    {
                        "label": "owner_a",
                        "document_id": owner_a_document_id,
                        "source_file_id": owner_a_source_file_id,
                    },
                    {
                        "label": "owner_b",
                        "document_id": owner_b_document_id,
                        "source_file_id": owner_b_source_file_id,
                    },
                ],
            )
            result["cleanup_observations"] = cleanup_observations
    return result


def _upload_document(
    client: TestClient,
    *,
    tenant_id: str,
    owner_user_id: str,
    source_text: str,
    trace_id: str,
    request_id: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "cx-document-library-postgres-smoke.txt",
            "content_type": "text/plain",
            "content_text": source_text,
            "tenant_id": tenant_id,
            "owner_user_id": owner_user_id,
        },
        headers=_service_headers(trace_id=trace_id, request_id=request_id),
    )
    response.raise_for_status()
    return response.json()


def _count_active_owner_documents(
    engine: object,
    *,
    tenant_id: str,
    owner_user_id: str,
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
                      AND lifecycle_status = 'ACTIVE'
                    """
                ),
                {"tenant_id": tenant_id, "owner_user_id": owner_user_id},
            ).scalar_one()
        )


def _delete_document_library_smoke_rows(
    engine: object,
    *,
    entries: list[dict[str, str | None]],
) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    for entry in entries:
        document_id = entry.get("document_id")
        source_file_id = entry.get("source_file_id")
        observation = {
            "label": entry.get("label"),
            "document_id": document_id,
            "source_file_id": source_file_id,
            "content_rows_before_delete": _count_content_object_by_id(
                engine,
                document_id=document_id,
            ),
            "source_rows_before_delete": _count_source_file_by_id(
                engine,
                source_file_id=source_file_id,
            ),
        }
        _delete_smoke_upload_rows(
            engine,
            document_id=document_id,
            source_file_id=source_file_id,
        )
        observation["content_rows_after_delete"] = _count_content_object_by_id(
            engine,
            document_id=document_id,
        )
        observation["source_rows_after_delete"] = _count_source_file_by_id(
            engine,
            source_file_id=source_file_id,
        )
        observations.append(observation)
    return observations


def _count_content_object_by_id(
    engine: object,
    *,
    document_id: str | None,
) -> int:
    if document_id is None:
        return 0
    with engine.begin() as connection:
        return int(
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


def _count_source_file_by_id(
    engine: object,
    *,
    source_file_id: str | None,
) -> int:
    if source_file_id is None:
        return 0
    with engine.begin() as connection:
        return int(
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


def _migration_evidence(migration_result: object) -> dict[str, object]:
    planned = tuple(getattr(migration_result, "planned", ()))
    applied = tuple(getattr(migration_result, "applied", ()))
    skipped = tuple(getattr(migration_result, "skipped", ()))
    return {
        "service_id": getattr(migration_result, "service_id", SERVICE_ID),
        "profile": getattr(migration_result, "profile", DEFAULT_PROFILE),
        "planned_count": len(planned),
        "applied_count": len(applied),
        "skipped_count": len(skipped),
        "dry_run": bool(getattr(migration_result, "dry_run", False)),
    }


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
        return f"cx_document_library_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "cx_document_library_postgres_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']}"
        )
    return (
        "cx_document_library_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional CX document library PostgreSQL smoke."
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
    evidence = run_cx_document_library_postgres_smoke()
    output = (
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False)
    )
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
