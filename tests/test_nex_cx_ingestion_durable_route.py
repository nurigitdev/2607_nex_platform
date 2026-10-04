from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nex_runtime import (
    InMemoryJobQueue,
    PERSISTENCE_MODE_POSTGRES,
    build_engine,
    build_session_factory,
    issue_mock_service_token,
)
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    IngestionError,
    register_ingestion_routes,
)
from nex_cx.ingestion_orchestration_repository import (
    InMemoryIngestionRunRepository,
    SqlAlchemyIngestionRunRepository,
)
from nex_cx.main import (
    build_cx_content_repository,
    build_cx_ingestion_run_repository,
    build_cx_remediation_execution_store,
)
from nex_cx.remediation_execution import SqlAlchemyRemediationExecutionStore
from nex_cx.repository import (
    CxContentRepositoryError,
    InMemoryCxContentRepository,
    SqlAlchemyCxContentRepository,
)


def storage_config(tmp_path: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=tmp_path,
        source_root=tmp_path / "source-files",
        extracted_markdown_root=tmp_path / "extracted-markdown",
        extraction_temp_root=tmp_path / "temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def test_upload_route_admits_durable_job_and_run(tmp_path: Path) -> None:
    app = FastAPI()
    store = ContentIngestionStore()
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    register_ingestion_routes(
        app,
        store=store,
        storage_config=storage_config(tmp_path),
        job_queue=queue,
        ingestion_run_repository=repository,
    )
    payload = {
        "filename": "private.md",
        "content_type": "text/markdown",
        "content_text": "private durable ingestion text",
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
        "ownership_ref": {
            "ownership_schema_version": "cx_source_ownership_ref.v1",
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
            "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
            "uploaded_by_subject_ref": {"type": "oa.user", "id": "user-a"},
            "legacy": {"tenant_id": "tenant-a", "owner_user_id": "user-a"},
            "compatibility_mode": "legacy_owner_fields_mapped_to_oa_subject_refs",
        },
    }
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    headers = {
        "Authorization": f"Bearer {issued.access_token}",
        "X-NEX-Tenant-ID": "tenant-a",
        "X-NEX-Subject-ID": "user-a",
        "X-Request-ID": "request-1",
        "X-Trace-ID": "a" * 32,
    }

    response = TestClient(app).post(
        "/api/v1/documents/uploads", json=payload, headers=headers
    )
    assert response.status_code == 202
    body = response.json()
    assert len(queue.list_jobs(job_type="cx.document_ingestion")) == 1
    runs = repository.list_for_document(
        body["document_id"], tenant_id="tenant-a", owner_subject_id="user-a"
    )
    assert len(runs) == 1
    assert runs[0]["job_id"] == body["ingestion_job"]["job_id"]
    assert "ingestion_run" not in body


def test_restart_duplicate_reuses_durable_source_job_and_run_lineage(
    tmp_path: Path,
) -> None:
    content_repository = InMemoryCxContentRepository()
    queue = InMemoryJobQueue()
    run_repository = InMemoryIngestionRunRepository()
    payload = {
        "filename": "private.md",
        "content_type": "text/markdown",
        "content_text": "private durable ingestion text",
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
    }
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")

    def client_for(store: ContentIngestionStore) -> TestClient:
        app = FastAPI()
        register_ingestion_routes(
            app,
            store=store,
            storage_config=storage_config(tmp_path),
            job_queue=queue,
            ingestion_run_repository=run_repository,
        )
        return TestClient(app)

    first_store = ContentIngestionStore(content_repository=content_repository)
    first = client_for(first_store).post(
        "/api/v1/documents/uploads",
        json=payload,
        headers={
            "Authorization": f"Bearer {issued.access_token}",
            "X-NEX-Tenant-ID": "tenant-a",
            "X-NEX-Subject-ID": "user-a",
            "X-Request-ID": "request-before-restart",
            "X-Trace-ID": "a" * 32,
        },
    )

    restarted_store = ContentIngestionStore(content_repository=content_repository)
    duplicate = client_for(restarted_store).post(
        "/api/v1/documents/uploads",
        json={**payload, "filename": "renamed.md"},
        headers={
            "Authorization": f"Bearer {issued.access_token}",
            "X-NEX-Tenant-ID": "tenant-a",
            "X-NEX-Subject-ID": "user-a",
            "X-Request-ID": "request-after-restart",
            "X-Trace-ID": "b" * 32,
        },
    )

    assert first.status_code == 202
    assert duplicate.status_code == 200
    first_body = first.json()
    duplicate_body = duplicate.json()
    assert duplicate_body["dedupe"]["status"] == "ALREADY_EXISTS"
    assert duplicate_body["document_id"] == first_body["document_id"]
    assert duplicate_body["upload_id"] == first_body["upload_id"]
    assert duplicate_body["ingestion_job"] == first_body["ingestion_job"]
    assert duplicate_body["original_filename"] == "private.md"
    assert restarted_store.get_source_text(first_body["upload_id"]) == payload["content_text"]
    assert len(queue.list_jobs(job_type="cx.document_ingestion")) == 1
    assert len(run_repository.records) == 1


def test_durable_admission_binding_rejects_lineage_conflict() -> None:
    store = ContentIngestionStore()
    record = {
        "document_id": "document-a",
        "upload_id": "upload-a",
        "extraction": {"job_id": "job-a"},
    }
    with pytest.raises(IngestionError) as exc:
        store.bind_durable_ingestion_admission(
            record,
            {
                "document_id": "document-b",
                "upload_id": "upload-a",
                "job": {"job_id": "job-a"},
            },
        )
    assert exc.value.error_code == "cx.ingestion_admission.lineage_conflict"


def test_upload_route_maps_repository_and_binding_lineage_failures(
    tmp_path: Path,
) -> None:
    class UnavailableRepository(InMemoryCxContentRepository):
        def find_active_content_object(self, **kwargs):
            raise CxContentRepositoryError(
                error_code="cx.content_repository_unavailable",
                detail="repository unavailable",
                status_code=503,
            )

    class ConflictingStore(ContentIngestionStore):
        def bind_durable_ingestion_admission(self, record, admission):
            raise IngestionError(
                status_code=409,
                error_code="cx.ingestion_admission.lineage_conflict",
                detail="lineage conflict",
            )

    payload = {
        "filename": "private.md",
        "content_text": "private durable ingestion text",
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
    }
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    headers = {
        "Authorization": f"Bearer {issued.access_token}",
        "X-NEX-Tenant-ID": "tenant-a",
        "X-NEX-Subject-ID": "user-a",
        "X-Request-ID": "request-2",
        "X-Trace-ID": "c" * 32,
    }

    repository_app = FastAPI()
    register_ingestion_routes(
        repository_app,
        store=ContentIngestionStore(content_repository=UnavailableRepository()),
        storage_config=storage_config(tmp_path),
    )
    unavailable = TestClient(repository_app).post(
        "/api/v1/documents/uploads", json=payload, headers=headers
    )

    binding_app = FastAPI()
    register_ingestion_routes(
        binding_app,
        store=ConflictingStore(),
        storage_config=storage_config(tmp_path),
        job_queue=InMemoryJobQueue(),
        ingestion_run_repository=InMemoryIngestionRunRepository(),
    )
    conflict = TestClient(binding_app).post(
        "/api/v1/documents/uploads", json=payload, headers=headers
    )

    assert unavailable.status_code == 503, unavailable.text
    assert unavailable.json()["error_code"] == "cx.content_repository_unavailable"
    assert unavailable.json()["retryable"] is True
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "cx.ingestion_admission.lineage_conflict"


def test_route_configuration_requires_queue_and_repository_together(tmp_path: Path) -> None:
    app = FastAPI()
    try:
        register_ingestion_routes(
            app,
            store=ContentIngestionStore(),
            storage_config=storage_config(tmp_path),
            job_queue=InMemoryJobQueue(),
        )
    except ValueError as exc:
        assert "configured together" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("partial durable admission configuration was accepted")


def test_postgres_runtime_builders_select_sqlalchemy_adapters(tmp_path: Path) -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    runtime = SimpleNamespace(
        mode=PERSISTENCE_MODE_POSTGRES,
        api_session_factory=build_session_factory(engine),
        database_env="test",
        redacted_database_url="postgresql://***@127.0.0.1/nex_cx_test",
    )
    config = storage_config(tmp_path)

    assert isinstance(
        build_cx_content_repository(runtime, storage_config=config),
        SqlAlchemyCxContentRepository,
    )
    assert isinstance(
        build_cx_remediation_execution_store(runtime),
        SqlAlchemyRemediationExecutionStore,
    )
    assert isinstance(
        build_cx_ingestion_run_repository(runtime),
        SqlAlchemyIngestionRunRepository,
    )
