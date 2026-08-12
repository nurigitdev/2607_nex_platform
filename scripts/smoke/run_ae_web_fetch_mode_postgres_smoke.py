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
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError


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

import run_ae_web_fetch_mode_protected_smoke_boundary as boundary  # noqa: E402
from nex_ae_api.documents import (  # noqa: E402
    DocumentLibraryError,
    register_document_library_routes as register_ae_document_library_routes,
)
from nex_ae_api.retrieval import (  # noqa: E402
    RetrievalInteractionError,
    RetrievalInteractionStore,
    register_retrieval_routes as register_ae_retrieval_routes,
)
from nex_ae_api.uploads import (  # noqa: E402
    UploadHandoffError,
    UploadHandoffStore,
    register_upload_routes as register_ae_upload_routes,
)
from nex_cx.chunking import build_and_store_chunk_set  # noqa: E402
from nex_cx.embedding_index import build_and_store_embedding_index  # noqa: E402
from nex_cx.ingestion import (  # noqa: E402
    ContentIngestionStore,
    register_ingestion_routes,
    run_text_extraction_job,
)
from nex_cx.lexical_index import build_and_store_lexical_index  # noqa: E402
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_cx.retrieval import register_retrieval_routes as register_cx_retrieval_routes  # noqa: E402
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
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ae_web_fetch_mode_postgres_smoke.v1"
AE_SERVICE_ID = "nex-ae-api"
CX_SERVICE_ID = "nex-cx"
AE_SERVICE_SPEC = SERVICE_SPECS[AE_SERVICE_ID]
CX_SERVICE_SPEC = SERVICE_SPECS[CX_SERVICE_ID]
SECRET_SOURCE = "AE Web fetch-mode PostgreSQL smoke private source"


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


@dataclass
class TestClientCxRetrievalClient:
    client: TestClient
    calls: list[dict[str, object]] = field(default_factory=list)

    def create_retrieval_context(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/retrieval/context",
            json=payload,
            headers=_cx_service_headers(trace_id=trace_id, request_id=request_id),
        )
        self.calls.append(
            {
                "path": "/api/v1/retrieval/context",
                "status_code": response.status_code,
                "document_scope": payload.get("document_scope"),
            }
        )
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise RetrievalInteractionError(
                status_code=response.status_code,
                error_code=body.get("error_code", "cx.retrieval_request_failed"),
                detail=body.get("detail", "CX retrieval request failed."),
                retryable=body.get("retryable", False),
            )
        return response.json()


class SmokeEmbeddingClient:
    def create_embeddings(
        self,
        inputs: list[str],
        *,
        alias: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return {
            "object": "list",
            "alias": alias,
            "model_revision": "mock-embedding-slice-0229",
            "deployment_id": "mock-local-slice-0229",
            "data": [
                {
                    "object": "embedding",
                    "index": index,
                    "embedding": [0.1 + index / 1000, 0.2, 0.3],
                }
                for index, _ in enumerate(inputs)
            ],
            "usage": {
                "input_tokens": len(inputs),
                "output_tokens": 0,
                "total_tokens": len(inputs),
            },
        }


def run_ae_web_fetch_mode_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(boundary.SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{boundary.SMOKE_ENV} is not enabled.",
        }

    profile = env.get(boundary.PROFILE_ENV, boundary.DEFAULT_PROFILE)
    boundary_evidence = boundary.run_ae_web_fetch_mode_protected_smoke_boundary(
        env,
        browser_config=safe_fetch_mode_browser_config(),
    )
    if boundary_evidence["status"] == "FAIL":
        return _failure(
            "boundary_invalid",
            "AE Web fetch-mode protected boundary validation failed.",
            profile=profile,
            issues=boundary_evidence["issues"],
        )
    if profile != boundary.DEFAULT_PROFILE:
        return _failure(
            "profile_not_allowed",
            f"{boundary.PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
        )

    try:
        ae_database_url = _required_env(env, boundary.AE_DATABASE_URL_ENV)
        cx_database_url = _required_env(env, boundary.CX_DATABASE_URL_ENV)
        _require_test_database_url(ae_database_url, env_name=boundary.AE_DATABASE_URL_ENV)
        _require_test_database_url(cx_database_url, env_name=boundary.CX_DATABASE_URL_ENV)
        ae_migration = run_service_migrations(
            AE_SERVICE_ID,
            database_url=ae_database_url,
            profile=profile,
        )
        cx_migration = run_service_migrations(
            CX_SERVICE_ID,
            database_url=cx_database_url,
            profile=profile,
        )
        execution = _execute_fetch_mode_postgres_smoke(
            env=env,
            ae_database_url=ae_database_url,
            cx_database_url=cx_database_url,
        )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "profile": profile,
            "services": [AE_SERVICE_ID, CX_SERVICE_ID],
            "database_envs": {
                "ae": boundary.AE_DATABASE_URL_ENV,
                "cx": boundary.CX_DATABASE_URL_ENV,
            },
            "redacted_database_urls": {
                "ae": redact_database_url(ae_database_url),
                "cx": redact_database_url(cx_database_url),
            },
            "migrations": {
                "ae": _migration_evidence(ae_migration),
                "cx": _migration_evidence(cx_migration),
            },
            "boundary": {
                "schema_version": boundary_evidence["evidence_schema_version"],
                "status": boundary_evidence["status"],
                "phase_count": len(boundary_evidence["required_phases"]),
            },
            **execution,
        }
        assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_fetch_mode_postgres_smoke(
    *,
    env: dict[str, str],
    ae_database_url: str,
    cx_database_url: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    tenant_id = env[boundary.TENANT_ID_ENV]
    owner_user_id = env[boundary.OWNER_USER_ID_ENV]
    workspace_id = f"workspace-ae-web-fetch-smoke-{request_id.split('-', maxsplit=1)[0]}"
    ae_engine = build_engine(ae_database_url)
    cx_engine = build_engine(cx_database_url)
    ae_marker_id: str | None = None
    document_id: str | None = None
    source_file_id: str | None = None
    retrieval_package_id: str | None = None
    result: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="nex-ae-web-fetch-postgres-smoke-") as temp_dir:
        storage_config = _storage_config(Path(temp_dir))
        try:
            ae_marker_id = _write_ae_smoke_marker(
                ae_engine,
                request_id=request_id,
                trace_id=trace_id,
                owner_user_id=owner_user_id,
            )
            cx_app = build_service_app(CX_SERVICE_SPEC)
            cx_persistence = attach_service_persistence_runtime(
                cx_app,
                CX_SERVICE_SPEC,
                environ={
                    **env,
                    CX_SERVICE_SPEC.database_env: cx_database_url,
                    "NEX_CX_PERSISTENCE_MODE": "postgres",
                },
            )
            if cx_persistence.api_session_factory is None:
                raise RuntimeError("CX PostgreSQL session factory is unavailable")
            cx_repository = SqlAlchemyCxContentRepository(
                cx_persistence.api_session_factory,
                local_source_root=storage_config.source_root,
            )
            cx_store = ContentIngestionStore(content_repository=cx_repository)
            register_ingestion_routes(
                cx_app,
                store=cx_store,
                storage_config=storage_config,
                database_env=boundary.CX_DATABASE_URL_ENV,
                redacted_database_url=redact_database_url(cx_database_url),
                source_kind="postgres-read",
            )
            register_cx_retrieval_routes(cx_app, store=cx_store)
            cx_client = TestClient(cx_app)

            ae_app = build_service_app(AE_SERVICE_SPEC)
            ae_persistence = attach_service_persistence_runtime(
                ae_app,
                AE_SERVICE_SPEC,
                environ={
                    **env,
                    AE_SERVICE_SPEC.database_env: ae_database_url,
                    "NEX_AE_PERSISTENCE_MODE": "postgres",
                },
            )
            upload_store = UploadHandoffStore()
            retrieval_store = RetrievalInteractionStore()
            cx_upload_client = TestClientCxUploadClient(cx_client)
            cx_document_client = TestClientCxDocumentLibraryClient(cx_client)
            cx_retrieval_client = TestClientCxRetrievalClient(cx_client)
            register_ae_upload_routes(
                ae_app,
                store=upload_store,
                cx_client=cx_upload_client,
                owner_resolver_mode="disabled",
            )
            register_ae_document_library_routes(
                ae_app,
                upload_store=upload_store,
                cx_client=cx_document_client,
            )
            register_ae_retrieval_routes(
                ae_app,
                store=retrieval_store,
                cx_client=cx_retrieval_client,
            )
            ae_client = TestClient(ae_app)

            health_response = ae_client.get("/health")
            upload_response = ae_client.post(
                "/api/v1/uploads",
                json={
                    "workspace_id": workspace_id,
                    "filename": "ae-web-fetch-mode-postgres-smoke.txt",
                    "content_type": "text/plain",
                    "content_text": (
                        f"{SECRET_SOURCE} request={request_id}. "
                        "retrieval smoke evidence uses PostgreSQL readback."
                    ),
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
            _seed_retrieval_indexes(
                cx_store,
                document_id=document_id,
                storage_config=storage_config,
                request_id=request_id,
                trace_id=trace_id,
            )

            detail_response = ae_client.get(
                f"/api/v1/documents/{document_id}",
                headers=_ae_service_headers(trace_id=trace_id, request_id=request_id),
            )
            detail_response.raise_for_status()
            detail = detail_response.json()
            retrieval_response = ae_client.post(
                "/api/v1/retrieval/contexts",
                json={
                    "user_message": "retrieval smoke evidence PostgreSQL",
                    "trace_id": trace_id,
                    "retrieval": {
                        "query_text": "retrieval smoke evidence",
                        "document_scope": {"document_ids": [document_id]},
                        "top_k": 3,
                        "include_source_preview": False,
                        "purpose": "search",
                    },
                },
                headers=_ae_service_headers(trace_id=trace_id, request_id=request_id),
            )
            retrieval_response.raise_for_status()
            retrieval = retrieval_response.json()
            retrieval_package_id = str(retrieval["cx_retrieval_package_id"])
            persisted_owner_count = _count_active_owner_documents(
                cx_engine,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            current_document_rows = _count_current_document_rows(
                cx_engine,
                document_id=document_id,
            )
            persisted_retrieval = _read_persisted_retrieval_package(
                cx_engine,
                retrieval_package_id=retrieval_package_id,
            )
            ae_marker_rows = _count_ae_marker_rows(ae_engine, event_id=ae_marker_id)
            rendered = json.dumps(
                [upload, detail, retrieval, persisted_retrieval],
                default=str,
                ensure_ascii=False,
            )
            checks = {
                "ae_health_status_ok": health_response.status_code == 200,
                "ae_runtime_mode": ae_persistence.mode == "postgres",
                "cx_runtime_mode": cx_persistence.mode == "postgres",
                "ae_marker_write_readback": ae_marker_rows == 1,
                "upload_status_accepted": upload_response.status_code == 202,
                "cx_upload_called_once": len(cx_upload_client.calls) == 1,
                "detail_status_ok": detail_response.status_code == 200,
                "cx_detail_called_once": len(cx_document_client.calls) == 1,
                "retrieval_status_ok": retrieval_response.status_code == 200,
                "cx_retrieval_called_once": len(cx_retrieval_client.calls) == 1,
                "owner_scope_forwarded": (
                    cx_document_client.calls[0]["tenant_id"] == tenant_id
                    and cx_document_client.calls[0]["owner_user_id"] == owner_user_id
                ),
                "current_document_persisted": current_document_rows == 1,
                "retrieval_package_persisted": (
                    persisted_retrieval["retrieval_package_id"] == retrieval_package_id
                ),
                "retrieval_evidence_persisted": (
                    persisted_retrieval["stored_evidence_count"] >= 1
                ),
                "raw_payload_absent": _redaction_safe(
                    rendered,
                    forbidden_fragments=[
                        SECRET_SOURCE,
                        str(storage_config.source_root),
                        "source_storage_path",
                        ae_database_url,
                        cx_database_url,
                    ],
                ),
            }
            if not all(checks.values()):
                failed = ",".join(name for name, ok in checks.items() if not ok)
                raise RuntimeError(
                    "AE Web fetch-mode PostgreSQL smoke checks failed: "
                    f"{failed or 'unknown'}"
                )
            result = {
                "request_id": request_id,
                "trace_id": trace_id,
                "workspace_id": workspace_id,
                "document_id": document_id,
                "upload_handoff_id": upload["upload_handoff_id"],
                "retrieval_interaction_id": retrieval["retrieval_interaction_id"],
                "retrieval_package_id": retrieval_package_id,
                "db_observations": {
                    "ae_marker_rows": ae_marker_rows,
                    "cx_owner_active_content_count": persisted_owner_count,
                    "cx_current_document_rows": current_document_rows,
                    "cx_retrieval_evidence_count": persisted_retrieval[
                        "stored_evidence_count"
                    ],
                    "cx_retrieval_status": persisted_retrieval["status"],
                },
                "adapter_observations": {
                    "cx_upload_calls": len(cx_upload_client.calls),
                    "cx_detail_calls": len(cx_document_client.calls),
                    "cx_retrieval_calls": len(cx_retrieval_client.calls),
                },
                "checks": checks,
            }
        finally:
            result["cleanup_observations"] = {
                "ae_marker_rows_after_delete": _delete_ae_smoke_marker(
                    ae_engine,
                    event_id=ae_marker_id,
                ),
                "cx_retrieval_rows": _delete_retrieval_package_rows(
                    cx_engine,
                    retrieval_package_id=retrieval_package_id,
                ),
                "cx_rows": _delete_document_library_smoke_rows(
                    cx_engine,
                    entries=[
                        {
                            "label": "ae_web_fetch_mode",
                            "document_id": document_id,
                            "source_file_id": source_file_id,
                        }
                    ],
                ),
            }
    return result


def _delete_retrieval_package_rows(
    engine: object,
    *,
    retrieval_package_id: str | None,
) -> dict[str, int]:
    if retrieval_package_id is None:
        return {"evidence_rows_after_delete": 0, "package_rows_after_delete": 0}
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM cx_retrieval_evidence_items
                WHERE retrieval_package_id = :retrieval_package_id
                """
            ),
            {"retrieval_package_id": retrieval_package_id},
        )
        connection.execute(
            text(
                """
                DELETE FROM cx_retrieval_packages
                WHERE retrieval_package_id = :retrieval_package_id
                """
            ),
            {"retrieval_package_id": retrieval_package_id},
        )
        evidence_rows = int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM cx_retrieval_evidence_items
                    WHERE retrieval_package_id = :retrieval_package_id
                    """
                ),
                {"retrieval_package_id": retrieval_package_id},
            ).scalar_one()
        )
        package_rows = int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM cx_retrieval_packages
                    WHERE retrieval_package_id = :retrieval_package_id
                    """
                ),
                {"retrieval_package_id": retrieval_package_id},
            ).scalar_one()
        )
    return {
        "evidence_rows_after_delete": evidence_rows,
        "package_rows_after_delete": package_rows,
    }


def safe_fetch_mode_browser_config() -> dict[str, Any]:
    return {
        "config_schema_version": "ae_web_runtime_config.v1",
        "client_mode": "fetch",
        "ae_api_base_path": "/api",
        "features": {"fetch_clients_enabled": True},
        "document_detail_route": "/api/v1/documents/{document_id}",
        "upload_route": "/api/v1/uploads",
        "retrieval_route": "/api/v1/retrieval/contexts",
    }


def _seed_retrieval_indexes(
    store: ContentIngestionStore,
    *,
    document_id: str,
    storage_config: Any,
    request_id: str,
    trace_id: str,
) -> None:
    document = store.get_document(document_id)
    if document is None:
        raise RuntimeError("uploaded CX document was not found")
    extraction = run_text_extraction_job(
        document["extraction"]["job_id"],
        store=store,
        storage_config=storage_config,
        request_id=request_id,
        trace_id=trace_id,
    )
    chunk_set = build_and_store_chunk_set(
        extraction["document_id"],
        store=store,
        storage_config=storage_config,
        request_id=request_id,
        trace_id=trace_id,
    )
    build_and_store_lexical_index(
        chunk_set["document_id"],
        store=store,
        storage_config=storage_config,
        request_id=request_id,
        trace_id=trace_id,
    )
    build_and_store_embedding_index(
        chunk_set["document_id"],
        store=store,
        mo_client=SmokeEmbeddingClient(),
        embedding_alias="mock-embedding-slice-0229",
        request_id=request_id,
        trace_id=trace_id,
    )


def _write_ae_smoke_marker(
    engine: object,
    *,
    request_id: str,
    trace_id: str,
    owner_user_id: str,
) -> str:
    event_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO service_operational_events (
                    event_id,
                    service_id,
                    event_type,
                    severity,
                    trace_id,
                    request_id,
                    subject_type,
                    subject_id,
                    message,
                    details
                )
                VALUES (
                    :event_id,
                    'nex-ae-api',
                    'ae_web.fetch_mode_postgres_smoke',
                    'INFO',
                    :trace_id,
                    :request_id,
                    'smoke',
                    :owner_user_id,
                    'AE Web fetch-mode protected PostgreSQL smoke marker.',
                    CAST(:details AS jsonb)
                )
                """
            ),
            {
                "event_id": event_id,
                "trace_id": trace_id,
                "request_id": request_id,
                "owner_user_id": owner_user_id,
                "details": json.dumps(
                    {
                        "smoke_schema_version": SCHEMA_VERSION,
                        "test_database_marker": True,
                    },
                    sort_keys=True,
                ),
            },
        )
    return event_id


def _count_ae_marker_rows(engine: object, *, event_id: str | None) -> int:
    if event_id is None:
        return 0
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM service_operational_events
                    WHERE event_id = :event_id
                      AND service_id = 'nex-ae-api'
                      AND event_type = 'ae_web.fetch_mode_postgres_smoke'
                    """
                ),
                {"event_id": event_id},
            ).scalar_one()
        )


def _delete_ae_smoke_marker(engine: object, *, event_id: str | None) -> int:
    if event_id is None:
        return 0
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_operational_events
                WHERE event_id = :event_id
                """
            ),
            {"event_id": event_id},
        )
    return _count_ae_marker_rows(engine, event_id=event_id)


def _read_persisted_retrieval_package(
    engine: object,
    *,
    retrieval_package_id: str,
) -> dict[str, Any]:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    package.retrieval_package_id,
                    package.status,
                    package.evidence_count,
                    count(evidence.evidence_id) AS stored_evidence_count
                FROM cx_retrieval_packages AS package
                LEFT JOIN cx_retrieval_evidence_items AS evidence
                  ON evidence.retrieval_package_id = package.retrieval_package_id
                WHERE package.retrieval_package_id = :retrieval_package_id
                GROUP BY
                    package.retrieval_package_id,
                    package.status,
                    package.evidence_count
                """
            ),
            {"retrieval_package_id": retrieval_package_id},
        ).mappings().first()
    if row is None:
        raise RuntimeError("CX retrieval package was not persisted")
    return {
        "retrieval_package_id": str(row["retrieval_package_id"]),
        "status": row["status"],
        "evidence_count": int(row["evidence_count"]),
        "stored_evidence_count": int(row["stored_evidence_count"] or 0),
    }


def _count_current_document_rows(engine: object, *, document_id: str | None) -> int:
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
                      AND lifecycle_status = 'ACTIVE'
                    """
                ),
                {"document_id": document_id},
            ).scalar_one()
        )


def _ae_service_headers(*, trace_id: str, request_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=AE_SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _cx_service_headers(*, trace_id: str, request_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id=AE_SERVICE_ID, audience=CX_SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        "X-Service-ID": AE_SERVICE_ID,
    }


def _safe_response_json(response: object) -> dict[str, Any]:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _required_env(env: dict[str, str], name: str) -> str:
    value = env.get(name)
    if not value:
        raise ValueError(f"{name} is required.")
    return value


def _require_test_database_url(database_url: str, *, env_name: str) -> None:
    try:
        parsed = make_url(database_url)
    except SQLAlchemyError as exc:
        raise ValueError(f"{env_name} is not a valid database URL.") from exc
    if not parsed.database or not parsed.database.endswith("_test"):
        raise ValueError(f"{env_name} must target a *_test database.")


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: dict[str, str],
) -> None:
    leaked = [
        key
        for key in boundary.PROTECTED_ENV_KEYS
        if _protected_env_value_leaked(serialized_evidence, environ.get(key))
    ]
    if leaked:
        raise ValueError(
            "AE Web fetch-mode PostgreSQL smoke evidence contains unredacted "
            f"environment value: {leaked[0]}"
        )


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "services": [AE_SERVICE_ID, CX_SERVICE_ID],
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }
    if issues is not None:
        evidence["issues"] = issues
    return evidence


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ae_web_fetch_mode_postgres_smoke=skipped reason={boundary.SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ae_web_fetch_mode_postgres_smoke=pass "
            f"profile={evidence['profile']} "
            f"ae_db={evidence['database_envs']['ae']} "
            f"cx_db={evidence['database_envs']['cx']} "
            f"retrieval_evidence={evidence['db_observations']['cx_retrieval_evidence_count']}"
        )
    return (
        "ae_web_fetch_mode_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE Web fetch-mode PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_web_fetch_mode_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False))
    return 1 if evidence["status"] == "FAIL" else 0


def _protected_env_value_leaked(
    serialized_evidence: str,
    value: str | None,
) -> bool:
    return bool(value) and len(value) >= 8 and value in serialized_evidence


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
