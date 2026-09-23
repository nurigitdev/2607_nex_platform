from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from nex_cx.access_context import CxAccessContext
from nex_cx.generation import GenerationExecutionStore, register_generation_routes
from nex_cx.generation_private_output import persist_generation_output
from nex_cx.generation_read_model import (
    CX_GENERATION_CONTENT_SCHEMA_VERSION,
    CX_GENERATION_READ_MODEL_SCHEMA_VERSION,
    GenerationReadModel,
    GenerationReadModelError,
    project_generation_read_model,
)
from nex_cx.generation_repository import (
    GenerationRuntimeRepositoryError,
    SqlAlchemyGenerationRuntimeRepository,
)
from nex_cx.main import build_cx_generation_read_model
from nex_cx.private_content import build_private_payload_key, sha256_private_text
from nex_cx.private_text_store import FileSystemCxPrivateTextStore
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)
OUTPUT_TEXT = "Restart-safe owner-private grounded answer [1]."
OUTPUT_HASH = sha256_private_text(OUTPUT_TEXT)


def _context(
    *, tenant_id: str = "tenant-0967", subject_id: str = "employee-0967"
) -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id=tenant_id,
        subject_id=subject_id,
        request_id="request-0967",
        trace_id="96700000000000000000000000000001",
        scopes=("service:call",),
    )


def _record(**overrides: Any) -> dict[str, Any]:
    record = {
        "record_schema_version": "cx_generation_execution_record.v1",
        "cx_generation_id": "cx-generation-0967",
        "status": "COMPLETED",
        "trace_id": "96700000000000000000000000000001",
        "request_id": "request-0967",
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "mo_generation_id": "mo-generation-0967",
        "request_metadata": {
            "provider_prompt_package_hash": "a" * 64,
            "generation_request_hash": "b" * 64,
            "response_format_type": "text",
            "source_has_messages": True,
            "source_has_prompt": False,
            "grounding_required": True,
            "selected_evidence_count": 1,
        },
        "response_metadata": {
            "finish_reason": "STOP",
            "output_hash": OUTPUT_HASH,
        },
        "mo_runtime_metadata": {"provider_ms": 11},
        "usage": {"input_tokens": 12, "output_tokens": 9, "total_tokens": 21},
        "created_at": NOW,
        "updated_at": NOW,
    }
    record.update(overrides)
    return record


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'read-model.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_generation_executions (
                    cx_generation_id TEXT PRIMARY KEY,
                    record_schema_version TEXT NOT NULL,
                    tenant_ref_type TEXT NOT NULL,
                    tenant_ref_id TEXT NOT NULL,
                    owner_subject_ref_type TEXT NOT NULL,
                    owner_subject_ref_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retrieval_package_id TEXT,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    provider_capability TEXT NOT NULL,
                    mo_generation_id TEXT,
                    request_metadata TEXT NOT NULL,
                    response_metadata TEXT NOT NULL,
                    mo_runtime_metadata TEXT NOT NULL,
                    usage TEXT NOT NULL,
                    failure TEXT,
                    recovery_lineage TEXT,
                    private_output_schema_version TEXT,
                    output_storage_backend TEXT,
                    output_storage_uri TEXT UNIQUE,
                    output_sha256 TEXT,
                    output_size_bytes INTEGER,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """
            )
        )
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def persisted_read_model(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> GenerationReadModel:
    context = _context()
    private_store = FileSystemCxPrivateTextStore(tmp_path / "private-output")
    private_metadata = persist_generation_output(
        private_text_store=private_store,
        access_context=context,
        cx_generation_id="cx-generation-0967",
        output_text=OUTPUT_TEXT,
        expected_sha256=OUTPUT_HASH,
    )
    repository = SqlAlchemyGenerationRuntimeRepository(
        session_factory,
        source_kind="sqlite-regression",
    )
    repository.save(
        _record(),
        access_context=context,
        private_output_metadata=private_metadata,
    )
    return GenerationReadModel(
        repository=repository,
        private_output_store=private_store,
    )


def test_restart_safe_read_model_redacts_storage_and_reloads_verified_content(
    persisted_read_model: GenerationReadModel,
) -> None:
    metadata = persisted_read_model.get_metadata(
        "cx-generation-0967",
        access_context=_context(),
    )
    content = persisted_read_model.get_content(
        "cx-generation-0967",
        access_context=_context(),
    )

    assert metadata is not None
    assert metadata["read_model_schema_version"] == (
        CX_GENERATION_READ_MODEL_SCHEMA_VERSION
    )
    assert metadata["content_ref"] == {
        "available": True,
        "content_sha256": OUTPUT_HASH,
        "size_bytes": len(OUTPUT_TEXT.encode("utf-8")),
    }
    serialized = json.dumps(metadata, default=str)
    assert OUTPUT_TEXT not in serialized
    assert "output_storage_uri" not in serialized
    assert "output_storage_backend" not in serialized
    assert content == {
        "content_schema_version": CX_GENERATION_CONTENT_SCHEMA_VERSION,
        "cx_generation_id": "cx-generation-0967",
        "content_type": "text/plain; charset=utf-8",
        "content": OUTPUT_TEXT,
        "content_sha256": OUTPUT_HASH,
        "size_bytes": len(OUTPUT_TEXT.encode("utf-8")),
        "owner_scope_enforced": True,
    }


def test_read_model_hides_missing_and_cross_owner_records(
    persisted_read_model: GenerationReadModel,
) -> None:
    assert persisted_read_model.get_metadata(
        "missing",
        access_context=_context(),
    ) is None
    assert persisted_read_model.get_content(
        "cx-generation-0967",
        access_context=_context(subject_id="employee-other"),
    ) is None


def test_read_model_failed_and_inconsistent_content_fail_closed(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    repository = SqlAlchemyGenerationRuntimeRepository(session_factory)
    private_store = FileSystemCxPrivateTextStore(tmp_path / "private")
    repository.save(
        _record(
            cx_generation_id="cx-generation-failed-0967",
            status="FAILED",
            mo_generation_id=None,
            response_metadata={"finish_reason": "ERROR", "output_hash": None},
            usage={},
            failure={
                "failure_code": "mo.provider_timeout",
                "failure_class": "PROVIDER_TIMEOUT",
                "owner_service": "nex-mo",
                "failed_stage": "GENERATING",
                "retryable": True,
            },
        ),
        access_context=_context(),
        private_output_metadata=None,
    )
    read_model = GenerationReadModel(repository, private_store)

    with pytest.raises(GenerationReadModelError) as failed:
        read_model.get_content(
            "cx-generation-failed-0967",
            access_context=_context(),
        )
    assert failed.value.error_code == "cx.generation_content_unavailable"

    inconsistent = project_generation_read_model(
        {**_record(), "private_output_metadata": None}
    )
    assert inconsistent["content_ref"] == {
        "available": False,
        "content_sha256": None,
        "size_bytes": None,
    }


def test_read_model_projection_allowlists_nested_metadata() -> None:
    projection = project_generation_read_model(
        {
            **_record(),
            "unexpected_top_level": "private",
            "request_metadata": {
                "generation_request_hash": "b" * 64,
                "raw_prompt": "private prompt",
            },
            "response_metadata": {
                "finish_reason": "STOP",
                "output_hash": OUTPUT_HASH,
                "output_preview": OUTPUT_TEXT,
                "output_storage_uri": "file:///private/output",
            },
            "mo_runtime_metadata": {
                "provider_ms": 11,
                "provider_url": "http://private-provider",
            },
            "usage": {"total_tokens": 21, "raw_usage": "private"},
            "private_output_metadata": None,
        }
    )

    serialized = json.dumps(projection, default=str)
    assert "unexpected_top_level" not in projection
    assert "raw_prompt" not in serialized
    assert "output_preview" not in serialized
    assert "output_storage_uri" not in serialized
    assert "provider_url" not in serialized
    assert "raw_usage" not in serialized

    empty_metadata = project_generation_read_model(
        {
            **_record(),
            "request_metadata": None,
            "response_metadata": None,
            "mo_runtime_metadata": None,
            "usage": None,
            "private_output_metadata": None,
        }
    )
    assert empty_metadata["request_metadata"] == {}
    assert empty_metadata["response_metadata"] == {}
    assert empty_metadata["mo_runtime_metadata"] == {}
    assert empty_metadata["usage"] == {}


def test_read_model_reports_missing_and_corrupt_private_payload(
    persisted_read_model: GenerationReadModel,
) -> None:
    private_store = persisted_read_model.private_output_store
    assert isinstance(private_store, FileSystemCxPrivateTextStore)
    context = _context()
    key = build_private_payload_key(
        context,
        payload_kind="generation_output",
        content_id="cx-generation-0967",
    )
    payload_path = private_store._payload_path(key)
    payload_path.unlink()
    with pytest.raises(GenerationReadModelError) as missing:
        persisted_read_model.get_content(
            "cx-generation-0967",
            access_context=context,
        )
    assert missing.value.status_code == 503
    assert missing.value.retryable is True

    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text("tampered", encoding="utf-8")
    with pytest.raises(GenerationReadModelError) as corrupted:
        persisted_read_model.get_content(
            "cx-generation-0967",
            access_context=context,
        )
    assert corrupted.value.error_code == "cx.generation_content_integrity_failed"
    assert corrupted.value.status_code == 409


class UnavailableRepository:
    def get(self, cx_generation_id: str, *, access_context: CxAccessContext):
        raise GenerationRuntimeRepositoryError(
            error_code="cx.generation_runtime.repository_unavailable",
            detail="CX generation runtime repository is unavailable.",
            status_code=503,
        )


class StaticRepository:
    def __init__(self, record: dict[str, Any] | None) -> None:
        self.record = record

    def get(self, cx_generation_id: str, *, access_context: CxAccessContext):
        return self.record


def test_read_model_maps_repository_failure(tmp_path: Path) -> None:
    read_model = GenerationReadModel(
        repository=UnavailableRepository(),  # type: ignore[arg-type]
        private_output_store=FileSystemCxPrivateTextStore(tmp_path / "private"),
    )
    with pytest.raises(GenerationReadModelError) as failure:
        read_model.get_metadata("cx-generation-0967", access_context=_context())
    assert failure.value.status_code == 503
    assert str(failure.value) == "CX generation runtime repository is unavailable."


def test_read_model_rejects_completed_record_without_content_reference(
    tmp_path: Path,
) -> None:
    read_model = GenerationReadModel(
        repository=StaticRepository(  # type: ignore[arg-type]
            {**_record(), "private_output_metadata": None}
        ),
        private_output_store=FileSystemCxPrivateTextStore(tmp_path / "private"),
    )
    with pytest.raises(GenerationReadModelError) as failure:
        read_model.get_content("cx-generation-0967", access_context=_context())
    assert failure.value.error_code == "cx.generation_content_reference_missing"


def _headers(*, subject_id: str = "employee-0967") -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-0967",
        "traceparent": "00-96700000000000000000000000000001-00f067aa0ba902b7-01",
        "X-NEX-Tenant-ID": "tenant-0967",
        "X-NEX-Subject-ID": subject_id,
    }


def test_generation_routes_read_durable_state_after_memory_restart(
    persisted_read_model: GenerationReadModel,
) -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_generation_routes(
        app,
        store=GenerationExecutionStore(),
        read_model=persisted_read_model,
    )
    client = TestClient(app)

    metadata = client.get(
        "/api/v1/generations/cx-generation-0967",
        headers=_headers(),
    )
    content = client.get(
        "/api/v1/generations/cx-generation-0967/content",
        headers=_headers(),
    )
    cross_owner = client.get(
        "/api/v1/generations/cx-generation-0967/content",
        headers=_headers(subject_id="employee-other"),
    )
    missing_auth = client.get(
        "/api/v1/generations/cx-generation-0967/content",
    )

    assert metadata.status_code == content.status_code == 200
    assert metadata.json()["content_ref"]["available"] is True
    assert OUTPUT_TEXT not in metadata.text
    assert content.json()["content"] == OUTPUT_TEXT
    assert cross_owner.status_code == 404
    assert missing_auth.status_code == 401


def test_content_route_requires_durable_read_model() -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_generation_routes(app, store=GenerationExecutionStore())
    response = TestClient(app).get(
        "/api/v1/generations/cx-generation-0967/content",
        headers=_headers(),
    )
    assert response.status_code == 503
    assert response.json()["error_code"] == "cx.generation_read_model_unavailable"


def test_metadata_route_maps_repository_unavailable(tmp_path: Path) -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_generation_routes(
        app,
        store=GenerationExecutionStore(),
        read_model=GenerationReadModel(
            repository=UnavailableRepository(),  # type: ignore[arg-type]
            private_output_store=FileSystemCxPrivateTextStore(tmp_path / "private"),
        ),
    )
    response = TestClient(app).get(
        "/api/v1/generations/cx-generation-0967",
        headers=_headers(),
    )
    assert response.status_code == 503
    assert response.json()["error_code"] == (
        "cx.generation_runtime.repository_unavailable"
    )


def test_generation_read_model_builder_reuses_runtime_dependencies(
    tmp_path: Path,
) -> None:
    assert build_cx_generation_read_model(None) is None
    execution_repository = UnavailableRepository()
    private_store = FileSystemCxPrivateTextStore(tmp_path / "private")
    runtime = SimpleNamespace(
        execution_repository=execution_repository,
        private_output_store=private_store,
    )

    built = build_cx_generation_read_model(runtime)  # type: ignore[arg-type]

    assert isinstance(built, GenerationReadModel)
    assert built.repository is execution_repository
    assert built.private_output_store is private_store
