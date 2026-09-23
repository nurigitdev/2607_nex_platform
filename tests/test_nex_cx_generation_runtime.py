from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

import nex_cx.generation_runtime as generation_runtime
from nex_cx.access_context import CxAccessContext
from nex_cx.generation import (
    GenerationExecutionStore,
    GenerationFacadeError,
    register_generation_routes,
)
from nex_cx.generation_repository import (
    GenerationRuntimeRepositoryError,
    SqlAlchemyGenerationRuntimeRepository,
)
from nex_cx.generation_runtime import (
    CX_GENERATION_ADMISSION_SCHEMA_VERSION,
    GenerationAdmissionRepository,
    GroundedGenerationRuntime,
    GroundedGenerationRuntimeError,
    InMemoryGenerationAdmissionRepository,
    SqlAlchemyGenerationAdmissionRepository,
    generation_execution_request_hash,
    generation_idempotency_key_hash,
)
from nex_cx.main import build_cx_generation_runtime
from nex_cx.private_content import sha256_private_text
from nex_cx.private_text_store import FileSystemCxPrivateTextStore
from nex_runtime import (
    PERSISTENCE_MODE_MEMORY,
    PERSISTENCE_MODE_POSTGRES,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


NOW = datetime(2026, 9, 23, 13, 0, tzinfo=UTC)
OUTPUT_TEXT = "Durable owner-private answer [1]."
OUTPUT_HASH = sha256_private_text(OUTPUT_TEXT)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _context(
    *, tenant_id: str = "tenant-0966", subject_id: str = "employee-0966"
) -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id=tenant_id,
        subject_id=subject_id,
        request_id="request-0966",
        trace_id="96600000000000000000000000000001",
        scopes=("service:call",),
    )


def _mo_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "request_schema_version": "cx_mo_generation_request.v1",
        "client_request_id": "client-0966",
        "trace_id": "96600000000000000000000000000001",
        "cx_generation_id": "pre-runtime-id",
        "provider_prompt_package_hash": "a" * 64,
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "workload_class": "LLM_INTERACTIVE",
        "generation_profile": "grounded-answer",
        "messages": [{"role": "user", "content": "private prompt"}],
        "prompt": None,
        "response_format": {"type": "text"},
        "max_output_tokens": 256,
        "temperature": 0.0,
        "stream": False,
        "timeout_ms": 60_000,
        "metadata": {
            "generation_request_hash": "b" * 64,
            "selected_evidence_count": 1,
        },
    }
    payload.update(overrides)
    return payload


def _completed_record(admission, **overrides: Any) -> dict[str, Any]:
    record = {
        "record_schema_version": "cx_generation_execution_record.v1",
        "cx_generation_id": admission.mo_payload["cx_generation_id"],
        "status": "COMPLETED",
        "trace_id": "96600000000000000000000000000001",
        "request_id": "request-0966",
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "mo_generation_id": "mo-generation-0966",
        "request_metadata": {
            "provider_prompt_package_hash": "a" * 64,
            "generation_request_hash": admission.mo_payload["metadata"][
                "generation_request_hash"
            ],
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
        "mo_runtime_metadata": {"provider_ms": 12},
        "usage": {"input_tokens": 10, "output_tokens": 8, "total_tokens": 18},
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }
    record.update(overrides)
    return record


def _failed_record(admission) -> dict[str, Any]:
    return {
        **_completed_record(admission),
        "status": "FAILED",
        "mo_generation_id": None,
        "response_metadata": {"finish_reason": "ERROR", "output_hash": None},
        "usage": {},
        "failure": {
            "failure_code": "mo.provider_timeout",
            "failure_class": "PROVIDER_TIMEOUT",
            "owner_service": "nex-mo",
            "failed_stage": "GENERATING",
            "retryable": True,
        },
    }


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'runtime.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_gen_admissions (
                    admission_id TEXT PRIMARY KEY,
                    admission_schema_version TEXT NOT NULL,
                    tenant_ref_type TEXT NOT NULL,
                    tenant_ref_id TEXT NOT NULL,
                    owner_subject_ref_type TEXT NOT NULL,
                    owner_subject_ref_id TEXT NOT NULL,
                    idempotency_key_hash TEXT NOT NULL,
                    execution_request_hash TEXT NOT NULL,
                    cx_generation_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    lease_expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    completed_at TIMESTAMP,
                    UNIQUE (
                        tenant_ref_id,
                        owner_subject_ref_id,
                        idempotency_key_hash
                    )
                )
                """
            )
        )
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
def runtime(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> GroundedGenerationRuntime:
    return GroundedGenerationRuntime(
        admission_repository=SqlAlchemyGenerationAdmissionRepository(
            session_factory
        ),
        execution_repository=SqlAlchemyGenerationRuntimeRepository(
            session_factory,
            source_kind="sqlite-regression",
        ),
        private_output_store=FileSystemCxPrivateTextStore(tmp_path / "private"),
        clock=Clock(),
    )


def _admit(
    runtime: GroundedGenerationRuntime,
    *,
    context: CxAccessContext | None = None,
    key: str | None = "idem-0966",
    payload: dict[str, Any] | None = None,
):
    return runtime.admit(
        source_payload={"client_request_id": "client-0966"},
        mo_payload=payload or _mo_payload(),
        access_context=context or _context(),
        request_id="request-0966",
        trace_id="96600000000000000000000000000001",
        idempotency_key=key,
    )


def test_sql_runtime_persists_private_output_and_replays_exact_request(
    runtime: GroundedGenerationRuntime,
) -> None:
    admission = _admit(runtime)
    stored = runtime.persist_completed(
        admission=admission,
        execution_record=_completed_record(admission),
        output_text=OUTPUT_TEXT,
        access_context=_context(),
    )
    replay = _admit(runtime)

    assert admission.decision == "NEW"
    assert replay.decision == "REPLAY"
    assert replay.existing_record == stored
    assert stored["private_output_metadata"]["output_sha256"] == OUTPUT_HASH
    assert OUTPUT_TEXT not in json.dumps(stored, default=str)
    assert runtime.admission_repository.get(
        admission.admission["admission_id"], access_context=_context()
    )["status"] == "COMPLETED"


def test_runtime_rejects_in_progress_duplicate_and_payload_conflict(
    runtime: GroundedGenerationRuntime,
) -> None:
    _admit(runtime)

    with pytest.raises(GroundedGenerationRuntimeError) as in_progress:
        _admit(runtime)
    with pytest.raises(GroundedGenerationRuntimeError) as conflict:
        _admit(runtime, payload=_mo_payload(max_output_tokens=512))

    assert in_progress.value.error_code == "cx.generation_runtime.in_progress"
    assert in_progress.value.retryable is True
    assert conflict.value.error_code == (
        "cx.generation_runtime.idempotency_conflict"
    )


def test_runtime_reclaims_expired_lease_without_changing_identity(
    runtime: GroundedGenerationRuntime,
) -> None:
    first = _admit(runtime)
    clock = runtime.clock
    assert isinstance(clock, Clock)
    clock.value = NOW + timedelta(seconds=121)

    reclaimed = _admit(runtime)

    assert reclaimed.decision == "RECLAIMED"
    assert reclaimed.admission["admission_id"] == first.admission["admission_id"]
    assert reclaimed.mo_payload["cx_generation_id"] == first.mo_payload[
        "cx_generation_id"
    ]


def test_runtime_persists_and_replays_failed_execution(
    runtime: GroundedGenerationRuntime,
) -> None:
    admission = _admit(runtime)
    failed = runtime.persist_failed(
        admission=admission,
        execution_record=_failed_record(admission),
        access_context=_context(),
    )

    replay = _admit(runtime)

    assert failed["status"] == "FAILED"
    assert replay.existing_record["failure"]["failure_code"] == (
        "mo.provider_timeout"
    )


def test_runtime_owner_scope_changes_admission_and_generation_identity(
    runtime: GroundedGenerationRuntime,
) -> None:
    first = _admit(runtime)
    second = _admit(
        runtime,
        context=_context(subject_id="employee-other"),
    )

    assert first.admission["admission_id"] != second.admission["admission_id"]
    assert first.mo_payload["cx_generation_id"] != second.mo_payload[
        "cx_generation_id"
    ]
    assert runtime.admission_repository.get(
        first.admission["admission_id"],
        access_context=_context(subject_id="employee-other"),
    ) is None


def test_runtime_repairs_terminal_admission_after_partial_commit(
    runtime: GroundedGenerationRuntime,
) -> None:
    admission = _admit(runtime)
    private_output = generation_runtime.persist_generation_output(
        private_text_store=runtime.private_output_store,
        access_context=_context(),
        cx_generation_id=admission.mo_payload["cx_generation_id"],
        output_text=OUTPUT_TEXT,
        expected_sha256=OUTPUT_HASH,
    )
    runtime.execution_repository.save(
        _completed_record(admission),
        access_context=_context(),
        private_output_metadata=private_output,
    )

    replay = _admit(runtime)

    assert replay.is_replay is True
    repaired = runtime.admission_repository.get(
        admission.admission["admission_id"], access_context=_context()
    )
    assert repaired["status"] == "COMPLETED"


@pytest.mark.parametrize("key", ["", " ", "x" * 201, "bad\nkey", 7])
def test_idempotency_key_validation_fails_closed(key: object) -> None:
    with pytest.raises(GroundedGenerationRuntimeError) as caught:
        generation_idempotency_key_hash(key)

    assert caught.value.status_code == 422


def test_request_hash_ignores_transport_identity_but_tracks_semantics() -> None:
    first = generation_execution_request_hash(_mo_payload())
    transport_changed = generation_execution_request_hash(
        _mo_payload(
            trace_id="different-trace",
            client_request_id="different-client",
            cx_generation_id="different-generation",
        )
    )
    semantic_changed = generation_execution_request_hash(
        _mo_payload(max_output_tokens=512)
    )

    assert first == transport_changed
    assert first != semantic_changed


def test_in_memory_admission_repository_terminal_guards() -> None:
    repository = InMemoryGenerationAdmissionRepository()
    assert isinstance(repository, GenerationAdmissionRepository)
    runtime = GroundedGenerationRuntime(
        admission_repository=repository,
        execution_repository=SimpleNamespace(get=lambda *args, **kwargs: None),
        private_output_store=SimpleNamespace(),
        clock=Clock(),
    )
    admission = _admit(runtime)

    with pytest.raises(GroundedGenerationRuntimeError) as missing:
        repository.mark_terminal(
            "missing",
            access_context=_context(),
            cx_generation_id="missing",
            status="COMPLETED",
            observed_at=NOW,
        )
    repository.mark_terminal(
        admission.admission["admission_id"],
        access_context=_context(),
        cx_generation_id=admission.mo_payload["cx_generation_id"],
        status="COMPLETED",
        observed_at=NOW,
    )
    assert repository.mark_terminal(
        admission.admission["admission_id"],
        access_context=_context(),
        cx_generation_id=admission.mo_payload["cx_generation_id"],
        status="COMPLETED",
        observed_at=NOW,
    )["status"] == "COMPLETED"
    with pytest.raises(GroundedGenerationRuntimeError) as conflict:
        repository.mark_terminal(
            admission.admission["admission_id"],
            access_context=_context(),
            cx_generation_id=admission.mo_payload["cx_generation_id"],
            status="FAILED",
            observed_at=NOW,
        )

    assert missing.value.status_code == 404
    assert conflict.value.error_code == "cx.generation_runtime.admission_conflict"


def test_in_memory_repository_replays_reclaims_and_guards_generation_identity() -> None:
    repository = InMemoryGenerationAdmissionRepository()
    clock = Clock()
    runtime = GroundedGenerationRuntime(
        admission_repository=repository,
        execution_repository=SimpleNamespace(get=lambda *args, **kwargs: None),
        private_output_store=SimpleNamespace(),
        clock=clock,
    )
    first = _admit(runtime)
    with pytest.raises(GroundedGenerationRuntimeError):
        repository.mark_terminal(
            first.admission["admission_id"],
            access_context=_context(),
            cx_generation_id="different-generation",
            status="COMPLETED",
            observed_at=NOW,
        )
    assert repository.get(
        first.admission["admission_id"], access_context=_context()
    )["status"] == "IN_PROGRESS"

    clock.value = NOW + timedelta(seconds=121)
    reclaimed = _admit(runtime)
    assert reclaimed.decision == "RECLAIMED"


def test_runtime_detects_terminal_admission_without_execution_record() -> None:
    repository = InMemoryGenerationAdmissionRepository()
    runtime = GroundedGenerationRuntime(
        admission_repository=repository,
        execution_repository=SimpleNamespace(get=lambda *args, **kwargs: None),
        private_output_store=SimpleNamespace(),
        clock=Clock(),
    )
    first = _admit(runtime)
    repository.mark_terminal(
        first.admission["admission_id"],
        access_context=_context(),
        cx_generation_id=first.mo_payload["cx_generation_id"],
        status="COMPLETED",
        observed_at=NOW,
    )

    with pytest.raises(GroundedGenerationRuntimeError) as caught:
        _admit(runtime)

    assert caught.value.error_code == (
        "cx.generation_runtime.terminal_record_missing"
    )
    assert str(caught.value) == caught.value.detail


def test_runtime_maps_private_output_and_execution_repository_failures(
    tmp_path: Path,
) -> None:
    repository = InMemoryGenerationAdmissionRepository()
    good_execution = SimpleNamespace(get=lambda *args, **kwargs: None)
    runtime = GroundedGenerationRuntime(
        admission_repository=repository,
        execution_repository=good_execution,
        private_output_store=FileSystemCxPrivateTextStore(tmp_path / "private"),
        clock=Clock(),
    )
    admission = _admit(runtime)

    with pytest.raises(GroundedGenerationRuntimeError) as missing_hash:
        runtime.persist_completed(
            admission=admission,
            execution_record=_completed_record(
                admission,
                response_metadata={"finish_reason": "STOP", "output_hash": None},
            ),
            output_text=OUTPUT_TEXT,
            access_context=_context(),
        )
    with pytest.raises(GroundedGenerationRuntimeError) as hash_mismatch:
        runtime.persist_completed(
            admission=admission,
            execution_record=_completed_record(admission),
            output_text="different output",
            access_context=_context(),
        )

    unavailable = GenerationRuntimeRepositoryError(
        error_code="cx.generation_runtime.repository_unavailable",
        detail="unavailable",
        status_code=503,
    )

    class RaisingExecutionRepository:
        def get(self, *args, **kwargs):
            raise unavailable

        def save(self, *args, **kwargs):
            raise unavailable

    failing = GroundedGenerationRuntime(
        admission_repository=InMemoryGenerationAdmissionRepository(),
        execution_repository=RaisingExecutionRepository(),
        private_output_store=FileSystemCxPrivateTextStore(tmp_path / "other"),
        clock=Clock(),
    )
    failing_admission = _admit(failing)
    with pytest.raises(GroundedGenerationRuntimeError) as save_error:
        failing.persist_failed(
            admission=failing_admission,
            execution_record=_failed_record(failing_admission),
            access_context=_context(),
        )
    with pytest.raises(GroundedGenerationRuntimeError) as get_error:
        _admit(failing)

    assert missing_hash.value.status_code == 422
    assert hash_mismatch.value.error_code == "CX_GENERATION_OUTPUT_HASH_MISMATCH"
    assert save_error.value.retryable is True
    assert get_error.value.status_code == 503


def test_sql_admission_repository_maps_missing_table_to_unavailable(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'missing.db'}")
    repository = SqlAlchemyGenerationAdmissionRepository(sessionmaker(bind=engine))
    runtime = GroundedGenerationRuntime(
        admission_repository=repository,
        execution_repository=SimpleNamespace(),
        private_output_store=SimpleNamespace(),
        clock=Clock(),
    )

    with pytest.raises(GroundedGenerationRuntimeError) as caught:
        _admit(runtime)

    assert caught.value.status_code == 503

    with pytest.raises(GroundedGenerationRuntimeError) as get_error:
        repository.get("missing", access_context=_context())
    assert get_error.value.status_code == 503


def test_sql_admission_repository_terminal_conflict_paths(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyGenerationAdmissionRepository(session_factory)
    runtime = GroundedGenerationRuntime(
        admission_repository=repository,
        execution_repository=SimpleNamespace(get=lambda *args, **kwargs: None),
        private_output_store=SimpleNamespace(),
        clock=Clock(),
    )
    admission = _admit(runtime)

    with pytest.raises(GroundedGenerationRuntimeError) as missing:
        repository.mark_terminal(
            "missing",
            access_context=_context(),
            cx_generation_id="missing",
            status="COMPLETED",
            observed_at=NOW,
        )
    with pytest.raises(GroundedGenerationRuntimeError) as identity:
        repository.mark_terminal(
            admission.admission["admission_id"],
            access_context=_context(),
            cx_generation_id="different",
            status="COMPLETED",
            observed_at=NOW,
        )
    repository.mark_terminal(
        admission.admission["admission_id"],
        access_context=_context(),
        cx_generation_id=admission.mo_payload["cx_generation_id"],
        status="COMPLETED",
        observed_at=NOW,
    )
    assert repository.mark_terminal(
        admission.admission["admission_id"],
        access_context=_context(),
        cx_generation_id=admission.mo_payload["cx_generation_id"],
        status="COMPLETED",
        observed_at=NOW,
    )["status"] == "COMPLETED"
    with pytest.raises(GroundedGenerationRuntimeError) as terminal:
        repository.mark_terminal(
            admission.admission["admission_id"],
            access_context=_context(),
            cx_generation_id=admission.mo_payload["cx_generation_id"],
            status="FAILED",
            observed_at=NOW,
        )

    assert missing.value.status_code == 404
    assert identity.value.error_code == "cx.generation_runtime.admission_conflict"
    assert terminal.value.status_code == 409


class RouteMoClient:
    def __init__(self, *, failure: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.failure = failure

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(payload)
        if self.failure:
            raise GenerationFacadeError(
                status_code=504,
                error_code="mo.provider_timeout",
                detail="Provider timed out.",
                retryable=True,
            )
        return {
            "mo_generation_id": "mo-0966",
            "alias": payload["alias"],
            "model_revision": "mock-llm-v1",
            "deployment_id": "mock-generation-local",
            "provider_type": "mock-generation",
            "output": {"type": "text", "text": OUTPUT_TEXT},
            "finish_reason": "STOP",
            "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
            "runtime_metadata": {
                "request_id": request_id,
                "trace_id": trace_id,
                "provider_ms": 8,
            },
        }


def _auth_headers(key: str = "route-idem-0966") -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "request-route-0966",
        "traceparent": "00-96600000000000000000000000000002-00f067aa0ba902b7-01",
        "X-NEX-Tenant-ID": "tenant-0966",
        "X-NEX-Subject-ID": "employee-0966",
        "Idempotency-Key": key,
    }


def test_generation_route_replays_without_second_provider_call(
    runtime: GroundedGenerationRuntime,
) -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    client_adapter = RouteMoClient()
    store = GenerationExecutionStore()
    register_generation_routes(
        app,
        store=store,
        mo_client=client_adapter,
        execution_runtime=runtime,
    )
    client = TestClient(app)
    payload = {
        "prompt": "Private general generation prompt.",
        "generation_profile": "general-answer",
        "execution_mode": "GENERAL_ANSWER",
        "timeout_ms": 60_000,
    }

    first = client.post("/api/v1/generations", json=payload, headers=_auth_headers())
    replay = client.post("/api/v1/generations", json=payload, headers=_auth_headers())
    conflict = client.post(
        "/api/v1/generations",
        json={**payload, "max_output_tokens": 512},
        headers=_auth_headers(),
    )

    assert first.status_code == replay.status_code == 200, (
        first.json(),
        replay.json(),
    )
    assert first.json() == replay.json()
    assert len(client_adapter.calls) == 1
    assert "Private general generation prompt" not in first.text
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == (
        "cx.generation_runtime.idempotency_conflict"
    )


def test_generation_route_replays_failed_attempt_as_problem(
    runtime: GroundedGenerationRuntime,
) -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    client_adapter = RouteMoClient(failure=True)
    register_generation_routes(
        app,
        store=GenerationExecutionStore(),
        mo_client=client_adapter,
        execution_runtime=runtime,
    )
    client = TestClient(app)
    payload = {
        "prompt": "Private failure prompt.",
        "generation_profile": "general-answer",
        "execution_mode": "GENERAL_ANSWER",
    }

    first = client.post("/api/v1/generations", json=payload, headers=_auth_headers())
    replay = client.post("/api/v1/generations", json=payload, headers=_auth_headers())

    assert first.status_code == replay.status_code == 504
    assert replay.json()["error_code"] == "mo.provider_timeout"
    assert len(client_adapter.calls) == 1


def test_generation_runtime_builder_only_enables_postgres(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "nex_cx.main.build_generation_output_store",
        lambda: FileSystemCxPrivateTextStore(tmp_path / "builder"),
    )
    assert build_cx_generation_runtime(
        SimpleNamespace(mode=PERSISTENCE_MODE_MEMORY, api_session_factory=None)
    ) is None

    built = build_cx_generation_runtime(
        SimpleNamespace(
            mode=PERSISTENCE_MODE_POSTGRES,
            api_session_factory=session_factory,
            database_env="test",
            redacted_database_url="postgresql://redacted",
        )
    )

    assert isinstance(built, GroundedGenerationRuntime)
    assert isinstance(
        built.admission_repository, SqlAlchemyGenerationAdmissionRepository
    )


def test_generation_admission_migration_contract_and_short_identifiers() -> None:
    source = Path(
        "database/nex-cx/migrations/0966_cx_generation_admissions.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS cx_gen_admissions" in source
    assert "idempotency_key_hash TEXT NOT NULL" in source
    assert "execution_request_hash TEXT NOT NULL" in source
    assert "UNIQUE (" in source
    assert "cx_generation_admission.v1" in source
    assert "raw_idempotency_key" not in source
    assert max(
        len(token)
        for token in source.replace("(", " ").replace(")", " ").split()
        if token.startswith(("ck_", "ux_", "idx_", "cx_"))
    ) <= 63
    assert CX_GENERATION_ADMISSION_SCHEMA_VERSION in source


def test_generation_runtime_validation_helpers_cover_invalid_internal_state() -> None:
    with pytest.raises(GroundedGenerationRuntimeError):
        generation_runtime._build_admission(
            access_context=_context(),
            idempotency_key_hash="a" * 64,
            execution_request_hash="b" * 64,
            cx_generation_id="generation",
            trace_id="c" * 32,
            request_id="request",
            observed_at=NOW,
            lease_seconds=0,
        )
    admission = generation_runtime._build_admission(
        access_context=_context(),
        idempotency_key_hash="a" * 64,
        execution_request_hash="b" * 64,
        cx_generation_id="generation",
        trace_id="c" * 32,
        request_id="request",
        observed_at=NOW,
        lease_seconds=1,
    )
    with pytest.raises(GroundedGenerationRuntimeError):
        generation_runtime._validate_admission({**admission, "extra": True})
    with pytest.raises(GroundedGenerationRuntimeError):
        generation_runtime._validate_admission(
            {**admission, "admission_schema_version": "unsupported"}
        )
    with pytest.raises(GroundedGenerationRuntimeError):
        generation_runtime._validate_admission(
            {**admission, "status": "UNKNOWN"}
        )
    with pytest.raises(GroundedGenerationRuntimeError):
        generation_runtime._validate_admission(
            {**admission, "execution_request_hash": "not-a-hash"}
        )
    with pytest.raises(GroundedGenerationRuntimeError):
        generation_runtime._terminal_status("IN_PROGRESS")
    terminal = generation_runtime._validate_admission(
        {
            **admission,
            "status": "COMPLETED",
            "completed_at": "2026-09-23T13:00:01Z",
        }
    )
    assert terminal["completed_at"].tzinfo is UTC
    assert generation_runtime._utc_datetime(
        datetime(2026, 9, 23, 13, 0)
    ).tzinfo is UTC
    assert generation_runtime._optional_text(None) is None
