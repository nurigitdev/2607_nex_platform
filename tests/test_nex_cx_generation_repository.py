from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

import nex_cx.generation_repository as generation_repository
from nex_cx.access_context import CxAccessContext
from nex_cx.generation_repository import (
    CX_GENERATION_RUNTIME_TABLE,
    GenerationRuntimeRepository,
    GenerationRuntimeRepositoryError,
    SqlAlchemyGenerationRuntimeRepository,
    build_generation_runtime_persistence_record,
)
from nex_cx.generation_private_output import (
    GENERATION_PRIVATE_OUTPUT_SCHEMA_VERSION,
)
from nex_cx.private_content import sha256_private_text


NOW = datetime(2026, 9, 23, 9, 30, tzinfo=UTC)
OUTPUT_TEXT = "Owner-private grounded answer [1]."
OUTPUT_HASH = sha256_private_text(OUTPUT_TEXT)


def _context(
    *, tenant_id: str = "tenant-0965", subject_id: str = "employee-0965"
) -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id=tenant_id,
        subject_id=subject_id,
        request_id="request-0965",
        trace_id="96500000000000000000000000000001",
        scopes=("service:call",),
    )


def _execution_record(**overrides: Any) -> dict[str, Any]:
    record = {
        "record_schema_version": "cx_generation_execution_record.v1",
        "cx_generation_id": "cx-generation-0965",
        "status": "COMPLETED",
        "trace_id": "96500000000000000000000000000001",
        "request_id": "request-0965",
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "mo_generation_id": "mo-generation-0965",
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
            "output_preview": OUTPUT_TEXT,
        },
        "mo_runtime_metadata": {
            "provider_ms": 12,
            "provider_url": "http://private-provider",
        },
        "usage": {"input_tokens": 10, "output_tokens": 8, "total_tokens": 18},
        "created_at": NOW,
        "updated_at": NOW,
    }
    record.update(overrides)
    return record


def _failed_record() -> dict[str, Any]:
    return _execution_record(
        cx_generation_id="cx-generation-failed-0965",
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
    )


def _private_output(**overrides: Any) -> dict[str, Any]:
    metadata = {
        "private_output_schema_version": GENERATION_PRIVATE_OUTPUT_SCHEMA_VERSION,
        "output_storage_backend": "filesystem-text-v1",
        "output_storage_uri": (
            "cx-private://filesystem-text-v1/owner-digest/"
            "generation_output/content-digest"
        ),
        "output_sha256": OUTPUT_HASH,
        "output_size_bytes": len(OUTPUT_TEXT.encode("utf-8")),
    }
    metadata.update(overrides)
    return metadata


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'generation.db'}")
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


def test_sql_repository_saves_reloads_and_idempotently_reuses_completed_record(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyGenerationRuntimeRepository(
        session_factory,
        source_kind="sqlite-regression",
        database_env="test",
        redacted_database_url="sqlite:///generation.db",
    )

    first = repository.save(
        _execution_record(),
        access_context=_context(),
        private_output_metadata=_private_output(),
    )
    second = repository.save(
        _execution_record(),
        access_context=_context(),
        private_output_metadata=_private_output(),
    )
    reloaded = repository.get(
        "cx-generation-0965",
        access_context=_context(),
    )

    assert isinstance(repository, GenerationRuntimeRepository)
    assert first == second == reloaded
    assert first["tenant_ref_id"] == "tenant-0965"
    assert first["owner_subject_ref_id"] == "employee-0965"
    assert first["private_output_metadata"] == _private_output()
    assert first["response_metadata"] == {
        "finish_reason": "STOP",
        "output_hash": OUTPUT_HASH,
    }
    assert first["mo_runtime_metadata"] == {"provider_ms": 12}
    assert OUTPUT_TEXT not in json.dumps(first, default=str)
    assert repository.source_kind == "sqlite-regression"
    assert repository.database_env == "test"


def test_sql_repository_hides_cross_owner_and_missing_records(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyGenerationRuntimeRepository(session_factory)
    repository.save(
        _execution_record(),
        access_context=_context(),
        private_output_metadata=_private_output(),
    )

    assert repository.get(
        "cx-generation-0965",
        access_context=_context(subject_id="employee-other"),
    ) is None
    assert repository.get("missing", access_context=_context()) is None


def test_sql_repository_persists_failed_record_without_output_reference(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyGenerationRuntimeRepository(session_factory)

    stored = repository.save(
        _failed_record(),
        access_context=_context(),
        private_output_metadata=None,
    )

    assert stored["status"] == "FAILED"
    assert stored["failure"]["failure_code"] == "mo.provider_timeout"
    assert stored["private_output_metadata"] is None


def test_sql_repository_rejects_immutable_generation_conflict(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyGenerationRuntimeRepository(session_factory)
    repository.save(
        _execution_record(),
        access_context=_context(),
        private_output_metadata=_private_output(),
    )

    with pytest.raises(GenerationRuntimeRepositoryError) as changed:
        repository.save(
            _execution_record(alias="different-alias"),
            access_context=_context(),
            private_output_metadata=_private_output(),
        )
    with pytest.raises(GenerationRuntimeRepositoryError) as other_owner:
        repository.save(
            _execution_record(),
            access_context=_context(subject_id="employee-other"),
            private_output_metadata=_private_output(),
        )

    assert changed.value.error_code == "cx.generation_runtime.identity_conflict"
    assert other_owner.value.error_code == "cx.generation_runtime.identity_conflict"


@pytest.mark.parametrize(
    ("record", "metadata", "error_code"),
    [
        (
            _execution_record(),
            None,
            "cx.generation_runtime.private_output_required",
        ),
        (
            _failed_record(),
            _private_output(),
            "cx.generation_runtime.failed_output_forbidden",
        ),
        (
            _execution_record(),
            _private_output(output_sha256="c" * 64),
            "cx.generation_runtime.output_hash_mismatch",
        ),
        (
            _execution_record(),
            _private_output(output_storage_uri="file:///private"),
            "cx.generation_runtime.record_invalid",
        ),
        (
            _execution_record(status="RUNNING"),
            _private_output(),
            "cx.generation_runtime.record_invalid",
        ),
    ],
)
def test_generation_runtime_record_validation_fails_closed(
    record: dict[str, Any],
    metadata: dict[str, Any] | None,
    error_code: str,
) -> None:
    with pytest.raises(GenerationRuntimeRepositoryError) as caught:
        build_generation_runtime_persistence_record(
            record,
            access_context=_context(),
            private_output_metadata=metadata,
        )

    assert caught.value.error_code == error_code


def test_generation_runtime_record_rejects_invalid_owner_scope() -> None:
    with pytest.raises(GenerationRuntimeRepositoryError) as caught:
        build_generation_runtime_persistence_record(
            _execution_record(),
            access_context=_context(tenant_id="../tenant"),
            private_output_metadata=_private_output(),
        )

    assert caught.value.error_code == "cx.generation_runtime.record_invalid"


def test_sql_repository_maps_database_errors_to_unavailable(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'missing.db'}")
    repository = SqlAlchemyGenerationRuntimeRepository(sessionmaker(bind=engine))

    with pytest.raises(GenerationRuntimeRepositoryError) as save_error:
        repository.save(
            _execution_record(),
            access_context=_context(),
            private_output_metadata=_private_output(),
        )
    with pytest.raises(GenerationRuntimeRepositoryError) as get_error:
        repository.get("missing", access_context=_context())

    assert save_error.value.status_code == 503
    assert get_error.value.error_code == "cx.generation_runtime.repository_unavailable"
    assert str(save_error.value) == "CX generation runtime repository is unavailable."


def test_generation_repository_serialization_helpers_cover_dialect_and_types() -> None:
    class _Dialect:
        name = "postgresql"

    class _Bind:
        dialect = _Dialect()

    class _Session:
        def get_bind(self):
            return _Bind()

    assert generation_repository._json_expression(  # type: ignore[arg-type]
        _Session(), "metadata"
    ) == "CAST(:metadata AS JSONB)"
    assert generation_repository._json_value({"safe": [1]}, {}) == {"safe": [1]}
    assert generation_repository._datetime_value(NOW) == NOW
    assert generation_repository._datetime_value(
        datetime(2026, 9, 23, 9, 30)
    ) == NOW
    assert generation_repository._datetime_value("2026-09-23T09:30:00") == NOW
    canonical = generation_repository._canonical_record(
        {"at": NOW, "values": (1, {"nested": True})}
    )
    assert canonical == (
        '{"at":"2026-09-23T09:30:00+00:00",'
        '"values":[1,{"nested":true}]}'
    )


def test_generation_runtime_migration_is_bounded_and_raw_safe() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "database/nex-cx/migrations/0965_cx_grounded_generation_runtime.sql"
    )
    migration = " ".join(migration_path.read_text(encoding="utf-8").split()).lower()

    assert migration.startswith("begin;")
    assert migration.endswith("commit;")
    assert "alter table cx_generation_executions" in migration
    for column in (
        "private_output_schema_version",
        "output_storage_backend",
        "output_storage_uri",
        "output_sha256",
        "output_size_bytes",
    ):
        assert f"add column if not exists {column}" in migration
    assert "ck_cx_gen_private_output" in migration
    assert "ux_cx_gen_output_uri" in migration
    assert "0965_cx_grounded_generation_runtime" in migration
    assert len(CX_GENERATION_RUNTIME_TABLE) <= 63
    assert OUTPUT_TEXT.lower() not in migration
