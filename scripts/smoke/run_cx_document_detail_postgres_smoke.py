#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
CX_PATH = ROOT / "services" / "nex-cx"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(CX_PATH))
sys.path.insert(0, str(SMOKE_PATH))

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
from run_cx_document_library_postgres_smoke import (  # noqa: E402
    _count_active_owner_documents,
    _delete_document_library_smoke_rows,
    _migration_evidence,
    _upload_document,
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


SMOKE_ENV = "NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
SCHEMA_VERSION = "cx_document_detail_postgres_smoke.v1"
SECRET_SOURCE = "CX document detail PostgreSQL smoke private source"


def run_cx_document_detail_postgres_smoke(
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
        execution = _execute_document_detail_smoke(
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


def _execute_document_detail_smoke(
    *,
    database_env: str,
    database_url: str,
    runtime_environ: dict[str, str],
) -> dict[str, object]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    document_id: str | None = None
    source_file_id: str | None = None
    result: dict[str, object] = {}
    engine = build_engine(database_url)
    with tempfile.TemporaryDirectory(prefix="nex-cx-document-detail-smoke-") as temp_dir:
        storage_config = _storage_config(Path(temp_dir))
        app = build_service_app(SERVICE_SPEC)
        persistence = attach_service_persistence_runtime(
            app,
            SERVICE_SPEC,
            environ=runtime_environ,
        )
        if persistence.api_session_factory is None:
            raise RuntimeError(
                "CX PostgreSQL document detail session factory is unavailable"
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
            database_env=database_env,
            redacted_database_url=redact_database_url(database_url),
            source_kind="postgres-read",
        )
        client = TestClient(app)
        try:
            suffix = request_id.split("-", maxsplit=1)[0]
            tenant_id = f"tenant-detail-smoke-{suffix}"
            owner_user_id = f"owner-detail-smoke-{suffix}"
            other_owner_user_id = f"owner-detail-smoke-{suffix}-other"
            upload = _upload_document(
                client,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                source_text=f"{SECRET_SOURCE} request={request_id}",
                trace_id=trace_id,
                request_id=request_id,
            )
            document_id = str(upload["document_id"])
            refs = store.get_content_ref(document_id)
            source_file_id = refs["source_file_id"] if refs is not None else None
            detail_response = client.get(
                f"/api/v1/documents/{document_id}",
                params={"tenant_id": tenant_id, "owner_user_id": owner_user_id},
                headers=_service_headers(trace_id=trace_id, request_id=request_id),
            )
            detail_response.raise_for_status()
            detail = detail_response.json()
            wrong_owner_response = client.get(
                f"/api/v1/documents/{document_id}",
                params={
                    "tenant_id": tenant_id,
                    "owner_user_id": other_owner_user_id,
                },
                headers=_service_headers(trace_id=trace_id, request_id=request_id),
            )
            persisted_owner_count = _count_active_owner_documents(
                engine,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            checks = {
                "runtime_mode": persistence.mode == "postgres",
                "api_upload_status_created": upload["document_id"] is not None,
                "detail_status_ok": detail_response.status_code == 200,
                "wrong_owner_collapsed_not_found": (
                    wrong_owner_response.status_code == 404
                    and wrong_owner_response.json().get("error_code")
                    == "cx.document_not_found"
                ),
                "source_metadata_uses_test_db": (
                    detail["source"]["database_env"] == database_env
                    and detail["source"]["source_kind"] == "postgres-read"
                ),
                "projection_schema_version": detail["projection_schema_version"]
                == "cx_document_detail_projection.v1",
                "document_id_matches": detail["document"]["document_id"]
                == document_id,
                "owner_scope_matches": (
                    detail["filters"]["tenant_ref"]["id"] == tenant_id
                    and detail["filters"]["owner_subject_ref"]["id"]
                    == owner_user_id
                ),
                "persisted_owner_count": persisted_owner_count == 1,
                "raw_payload_absent": _redaction_safe(
                    {
                        "detail": detail,
                        "wrong_owner": wrong_owner_response.json(),
                    },
                    forbidden_fragments=[
                        SECRET_SOURCE,
                        "source_storage_path",
                        str(storage_config.source_root),
                    ],
                ),
            }
            if not all(checks.values()):
                raise RuntimeError("CX document detail PostgreSQL smoke checks failed")
            result = {
                "document_id": document_id,
                "wrong_owner_status": wrong_owner_response.status_code,
                "db_observations": {
                    "owner_active_content_count": persisted_owner_count,
                    "detail_projection_document_id": detail["document"]["document_id"],
                    "detail_projection_schema_version": detail[
                        "projection_schema_version"
                    ],
                    "detail_source_kind": detail["source"]["source_kind"],
                },
                "checks": checks,
            }
        finally:
            result["cleanup_observations"] = _delete_document_library_smoke_rows(
                engine,
                entries=[
                    {
                        "label": "detail",
                        "document_id": document_id,
                        "source_file_id": source_file_id,
                    },
                ],
            )
    return result


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
        return f"cx_document_detail_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "cx_document_detail_postgres_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']}"
        )
    return (
        "cx_document_detail_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional CX document detail PostgreSQL smoke."
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
    evidence = run_cx_document_detail_postgres_smoke()
    output = (
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False)
    )
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
