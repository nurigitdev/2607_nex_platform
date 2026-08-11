#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
AE_PATH = ROOT / "services" / "nex-ae-api"
CX_PATH = ROOT / "services" / "nex-cx"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(CX_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_ae_api.documents import (  # noqa: E402
    DocumentLibraryError,
    register_document_library_routes,
)
from nex_ae_api.uploads import (  # noqa: E402
    UploadHandoffError,
    UploadHandoffStore,
    register_upload_routes,
)
from nex_cx.ingestion import ContentIngestionStore, register_ingestion_routes  # noqa: E402
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_engine,
    build_service_app,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_cx_document_library_postgres_smoke import (  # noqa: E402
    _count_active_owner_documents,
    _delete_document_library_smoke_rows,
    _migration_evidence,
)
from run_cx_upload_ownership_postgres_smoke import (  # noqa: E402
    _redaction_safe,
    _storage_config,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SMOKE_ENV = "NEX_AE_DOCUMENT_DETAIL_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_DOCUMENT_DETAIL_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-ae-api"
CX_SERVICE_ID = "nex-cx"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
CX_SERVICE_SPEC = SERVICE_SPECS[CX_SERVICE_ID]
SCHEMA_VERSION = "ae_document_detail_postgres_smoke.v1"
SECRET_SOURCE = "AE document detail PostgreSQL smoke private source"


@dataclass
class TestClientCxUploadClient:
    client: TestClient
    calls: list[dict[str, object]] = field(default_factory=list)

    def register_upload(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/documents/uploads",
            json=payload,
            headers=_cx_service_headers(trace_id=trace_id, request_id=request_id),
        )
        self.calls.append(
            {
                "path": "/api/v1/documents/uploads",
                "status_code": response.status_code,
                "tenant_id": payload.get("tenant_id"),
                "owner_user_id": payload.get("owner_user_id"),
            }
        )
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise UploadHandoffError(
                status_code=response.status_code,
                error_code=body.get("error_code", "cx.upload_request_failed"),
                detail=body.get("detail", "CX upload registration failed."),
                retryable=body.get("retryable", False),
            )
        return response.json()


@dataclass
class TestClientCxDocumentLibraryClient:
    client: TestClient
    calls: list[dict[str, object]] = field(default_factory=list)
    last_detail: dict[str, Any] | None = None

    def get_document(
        self,
        document_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.get(
            f"/api/v1/documents/{document_id}",
            params={
                "tenant_id": tenant_id,
                "owner_user_id": owner_user_id,
            },
            headers=_cx_service_headers(trace_id=trace_id, request_id=request_id),
        )
        self.calls.append(
            {
                "path": f"/api/v1/documents/{document_id}",
                "status_code": response.status_code,
                "tenant_id": tenant_id,
                "owner_user_id": owner_user_id,
            }
        )
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise DocumentLibraryError(
                status_code=response.status_code,
                error_code=body.get("error_code", "cx.document_detail_failed"),
                detail=body.get("detail", "CX document detail failed."),
                retryable=body.get("retryable", False),
            )
        self.last_detail = response.json()
        return self.last_detail

    def get_summary(
        self,
        document_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return None

    def get_summary_embedding(
        self,
        document_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return None


def run_ae_document_detail_postgres_smoke(
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
        database_env = service_database_env(CX_SERVICE_ID, profile=profile)
        database_url = service_database_url(
            CX_SERVICE_ID,
            profile=profile,
            environ=env,
        )
        migration_result = run_service_migrations(
            CX_SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_ae_document_detail_smoke(
            database_env=database_env,
            database_url=database_url,
            runtime_environ={
                **env,
                CX_SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "cx_service_id": CX_SERVICE_ID,
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


def _execute_ae_document_detail_smoke(
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
    with tempfile.TemporaryDirectory(prefix="nex-ae-document-detail-smoke-") as temp_dir:
        storage_config = _storage_config(Path(temp_dir))
        cx_app = build_service_app(CX_SERVICE_SPEC)
        persistence = attach_service_persistence_runtime(
            cx_app,
            CX_SERVICE_SPEC,
            environ=runtime_environ,
        )
        if persistence.api_session_factory is None:
            raise RuntimeError("CX PostgreSQL document detail session factory is unavailable")

        repository = SqlAlchemyCxContentRepository(
            persistence.api_session_factory,
            local_source_root=storage_config.source_root,
        )
        cx_store = ContentIngestionStore(content_repository=repository)
        register_ingestion_routes(
            cx_app,
            store=cx_store,
            storage_config=storage_config,
            database_env=database_env,
            redacted_database_url=redact_database_url(database_url),
            source_kind="postgres-read",
        )
        cx_client = TestClient(cx_app)

        ae_upload_store = UploadHandoffStore()
        cx_upload_client = TestClientCxUploadClient(cx_client)
        cx_document_client = TestClientCxDocumentLibraryClient(cx_client)
        ae_app = build_service_app(SERVICE_SPEC)
        register_upload_routes(
            ae_app,
            store=ae_upload_store,
            cx_client=cx_upload_client,
        )
        register_document_library_routes(
            ae_app,
            upload_store=ae_upload_store,
            cx_client=cx_document_client,
        )
        ae_client = TestClient(ae_app)

        try:
            suffix = request_id.split("-", maxsplit=1)[0]
            tenant_id = f"tenant-ae-detail-smoke-{suffix}"
            owner_user_id = f"owner-ae-detail-smoke-{suffix}"
            workspace_id = f"workspace-ae-detail-smoke-{suffix}"
            upload_response = ae_client.post(
                "/api/v1/uploads",
                json={
                    "workspace_id": workspace_id,
                    "filename": "ae-document-detail-postgres-smoke.txt",
                    "content_type": "text/plain",
                    "content_text": f"{SECRET_SOURCE} request={request_id}",
                    "tenant_id": tenant_id,
                    "owner_user_id": owner_user_id,
                },
                headers=_ae_service_headers(trace_id=trace_id, request_id=request_id),
            )
            upload_response.raise_for_status()
            upload = upload_response.json()
            document_id = str(upload["cx_document_ref"]["document_id"])
            refs = cx_store.get_content_ref(document_id)
            source_file_id = refs["source_file_id"] if refs is not None else None

            detail_response = ae_client.get(
                f"/api/v1/documents/{document_id}",
                headers=_ae_service_headers(trace_id=trace_id, request_id=request_id),
            )
            detail_response.raise_for_status()
            detail = detail_response.json()
            missing_response = ae_client.get(
                "/api/v1/documents/missing",
                headers=_ae_service_headers(trace_id=trace_id, request_id=request_id),
            )
            persisted_owner_count = _count_active_owner_documents(
                engine,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            cx_detail = cx_document_client.last_detail or {}
            checks = {
                "cx_runtime_mode": persistence.mode == "postgres",
                "ae_upload_status_accepted": upload_response.status_code == 202,
                "ae_handoff_recorded": (
                    ae_upload_store.get_by_document_id(document_id) is not None
                ),
                "cx_upload_called_once": len(cx_upload_client.calls) == 1,
                "cx_detail_called_once": len(cx_document_client.calls) == 1,
                "cx_detail_owner_scope_forwarded": (
                    cx_document_client.calls[0]["tenant_id"] == tenant_id
                    and cx_document_client.calls[0]["owner_user_id"] == owner_user_id
                ),
                "ae_detail_status_ok": detail_response.status_code == 200,
                "ae_projection_schema_version": (
                    detail["projection_schema_version"]
                    == "ae_document_detail_projection.v1"
                ),
                "ae_document_id_matches": detail["document"]["document_id"] == document_id,
                "ae_owner_scope_matches": (
                    detail["tenant_id"] == tenant_id
                    and detail["owner_user_id"] == owner_user_id
                ),
                "cx_source_kind_postgres": detail["cx"]["source_kind"] == "postgres-read",
                "cx_source_metadata_uses_test_db": (
                    cx_detail.get("source", {}).get("database_env") == database_env
                ),
                "persisted_owner_count": persisted_owner_count == 1,
                "missing_handoff_not_found_without_cx_call": (
                    missing_response.status_code == 404
                    and missing_response.json().get("error_code")
                    == "ae.document_not_found"
                    and len(cx_document_client.calls) == 1
                ),
                "raw_payload_absent": _redaction_safe(
                    upload,
                    detail,
                    missing_response.json(),
                    forbidden_fragments=[
                        SECRET_SOURCE,
                        "source_storage_path",
                        str(storage_config.source_root),
                    ],
                ),
            }
            if not all(checks.values()):
                raise RuntimeError("AE document detail PostgreSQL smoke checks failed")
            result = {
                "document_id": document_id,
                "upload_handoff_id": upload["upload_handoff_id"],
                "workspace_id": workspace_id,
                "missing_handoff_status": missing_response.status_code,
                "db_observations": {
                    "owner_active_content_count": persisted_owner_count,
                    "ae_detail_document_id": detail["document"]["document_id"],
                    "ae_projection_schema_version": detail[
                        "projection_schema_version"
                    ],
                    "cx_detail_source_kind": detail["cx"]["source_kind"],
                    "cx_detail_database_env": cx_detail.get("source", {}).get(
                        "database_env"
                    ),
                },
                "adapter_observations": {
                    "cx_upload_calls": len(cx_upload_client.calls),
                    "cx_detail_calls": len(cx_document_client.calls),
                },
                "checks": checks,
            }
        finally:
            result["cleanup_observations"] = _delete_document_library_smoke_rows(
                engine,
                entries=[
                    {
                        "label": "ae_detail",
                        "document_id": document_id,
                        "source_file_id": source_file_id,
                    },
                ],
            )
    return result


def _ae_service_headers(*, trace_id: str, request_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _cx_service_headers(*, trace_id: str, request_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id=SERVICE_ID, audience=CX_SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        "X-Service-ID": SERVICE_ID,
    }


def _safe_response_json(response: object) -> dict[str, Any]:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


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
        "cx_service_id": CX_SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ae_document_detail_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ae_document_detail_postgres_smoke=pass "
            f"service={evidence['service_id']} cx_db_env={evidence['database_env']}"
        )
    return (
        "ae_document_detail_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE document detail PostgreSQL smoke."
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
    evidence = run_ae_document_detail_postgres_smoke()
    output = (
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False)
    )
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
