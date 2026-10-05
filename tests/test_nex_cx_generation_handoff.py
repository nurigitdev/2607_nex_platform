from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from nex_runtime import (
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)

from nex_cx.access_context import CxAccessContext
from nex_cx.async_generation_contracts import build_async_generation_job
from nex_cx.async_generation_operations import register_async_generation_operations_routes
from nex_cx.generation_handoff import (
    CX_GENERATION_HANDOFF_SCHEMA_VERSION,
    GenerationHandoffError,
    build_generation_handoff,
    validate_generation_handoff,
)
from nex_cx.generation_read_model import GenerationReadModelError
from nex_cx.private_text_store import FileSystemCxPrivateTextStore


GENERATION_ID = "cx-generation-0996"


def _context(subject_id: str = "employee-0996") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id="tenant-0996",
        subject_id=subject_id,
        request_id="request-0996",
        trace_id="99600000000000000000000000000001",
        scopes=("service:call",),
    )


def _job(
    *,
    generation_id: str = GENERATION_ID,
    admission_id: str = "admission-0996",
) -> dict:
    return build_async_generation_job(
        cx_generation_id=generation_id,
        admission_id=admission_id,
        access_context=_context(),
        request_envelope_sha256="a" * 64,
        request_envelope_size_bytes=100,
        trace_id="99600000000000000000000000000001",
        request_id="request-0996",
        created_at="2026-09-27T01:00:00Z",
    )


@dataclass
class StubReadModel:
    metadata: dict | None
    content: dict | None
    failure: GenerationReadModelError | None = None
    metadata_calls: int = 0
    content_calls: int = 0

    def get_metadata(self, cx_generation_id, *, access_context):
        self.metadata_calls += 1
        if self.failure is not None:
            raise self.failure
        return deepcopy(self.metadata)

    def get_content(self, cx_generation_id, *, access_context):
        self.content_calls += 1
        return deepcopy(self.content)


def _ready_read_model() -> StubReadModel:
    return StubReadModel(
        metadata={
            "read_model_schema_version": "cx_generation_read_model.v1",
            "cx_generation_id": GENERATION_ID,
            "status": "COMPLETED",
            "content_ref": {
                "available": True,
                "content_sha256": "b" * 64,
                "size_bytes": 25,
            },
        },
        content={
            "content_schema_version": "cx_generation_content.v1",
            "cx_generation_id": GENERATION_ID,
            "content_type": "text/plain; charset=utf-8",
            "content": "Owner grounded answer [1].",
            "content_sha256": "b" * 64,
            "size_bytes": 25,
            "owner_scope_enforced": True,
        },
    )


def _grounded_ready_read_model() -> StubReadModel:
    model = _ready_read_model()
    model.metadata["retrieval_package_id"] = "retrieval-1365"
    model.metadata["request_metadata"] = {
        "provider_prompt_package_hash": "d" * 64,
        "grounding_required": True,
        "retrieval_package_hash": "b" * 64,
        "selected_evidence_count": 1,
        "citation_repair": {
            "repair_schema_version": "cx_citation_repair.v1",
            "attempted": True,
            "attempt_count": 1,
            "max_attempts": 1,
            "trigger_error_code": "cx.citation_required_missing",
            "same_retrieval_package": True,
            "original_provider_prompt_package_hash": "c" * 64,
            "effective_provider_prompt_package_hash": "d" * 64,
            "invalid_output_included": False,
        },
        "grounding_lineage": {
            "lineage_schema_version": "cx_grounded_generation_lineage.v1",
            "retrieval_package_id": "retrieval-1365",
            "retrieval_package_hash": "b" * 64,
            "evidence_binding_hash": "e" * 64,
            "selected_evidence_count": 1,
            "citation_validation_status": "VALIDATED",
            "citation_repair_attempted": True,
            "citation_repair_attempt_count": 1,
            "original_provider_prompt_package_hash": "c" * 64,
            "effective_provider_prompt_package_hash": "d" * 64,
            "same_retrieval_package": True,
            "private_evidence_included": False,
        },
    }
    return model


def test_active_job_projects_pending_without_reading_private_result() -> None:
    read_model = _ready_read_model()

    handoff = build_generation_handoff(
        _job(), read_model=read_model, access_context=_context()
    )

    assert handoff["handoff_schema_version"] == CX_GENERATION_HANDOFF_SCHEMA_VERSION
    assert handoff["handoff_status"] == "PENDING"
    assert handoff["next_action"] == "POLL_GENERATION_JOB"
    assert handoff["generation"] is handoff["content"] is None
    assert read_model.metadata_calls == read_model.content_calls == 0


def test_succeeded_job_projects_owner_safe_generation_and_content() -> None:
    queue = InMemoryJobQueue()
    queued = queue.enqueue(_job())
    queue.start_job(queued["job_id"])
    succeeded = queue.complete_job(queued["job_id"])
    read_model = _ready_read_model()

    handoff = build_generation_handoff(
        succeeded, read_model=read_model, access_context=_context()
    )

    assert handoff["handoff_status"] == "READY"
    assert handoff["next_action"] == "PRESENT_GENERATION_TO_OWNER"
    assert handoff["generation"]["cx_generation_id"] == GENERATION_ID
    assert handoff["content"]["content"] == "Owner grounded answer [1]."
    assert handoff["owner_scope_enforced"] is True
    assert read_model.metadata_calls == read_model.content_calls == 1


def test_ready_handoff_preserves_exact_grounding_and_repair_lineage() -> None:
    job = _job()
    job["status"] = "SUCCEEDED"

    handoff = build_generation_handoff(
        job,
        read_model=_grounded_ready_read_model(),
        access_context=_context(),
    )

    lineage = handoff["generation"]["request_metadata"]["grounding_lineage"]
    assert lineage["evidence_binding_hash"] == "e" * 64
    assert lineage["citation_repair_attempted"] is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda metadata: metadata.pop("grounding_lineage"),
        lambda metadata: metadata["grounding_lineage"].update(
            evidence_binding_hash="bad"
        ),
        lambda metadata: metadata.update(retrieval_package_hash="f" * 64),
        lambda metadata: metadata.pop("citation_repair"),
        lambda metadata: metadata["citation_repair"].update(attempted=False),
        lambda metadata: metadata["citation_repair"].update(
            original_provider_prompt_package_hash="9" * 64
        ),
    ],
)
def test_ready_handoff_rejects_grounding_lineage_drift(mutate) -> None:
    job = _job()
    job["status"] = "SUCCEEDED"
    read_model = _grounded_ready_read_model()
    mutate(read_model.metadata["request_metadata"])

    with pytest.raises(GenerationHandoffError):
        build_generation_handoff(job, read_model=read_model, access_context=_context())


def test_ready_handoff_accepts_valid_no_repair_lineage() -> None:
    job = _job()
    job["status"] = "SUCCEEDED"
    read_model = _grounded_ready_read_model()
    metadata = read_model.metadata["request_metadata"]
    metadata.pop("citation_repair")
    metadata["grounding_lineage"].update(
        citation_repair_attempted=False,
        citation_repair_attempt_count=0,
        original_provider_prompt_package_hash="d" * 64,
    )

    handoff = build_generation_handoff(
        job, read_model=read_model, access_context=_context()
    )

    assert handoff["handoff_status"] == "READY"


def test_ready_handoff_rejects_top_level_retrieval_identity_drift() -> None:
    job = _job()
    job["status"] = "SUCCEEDED"
    read_model = _grounded_ready_read_model()
    read_model.metadata["retrieval_package_id"] = "other"

    with pytest.raises(GenerationHandoffError, match="identity changed"):
        build_generation_handoff(job, read_model=read_model, access_context=_context())


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED"])
def test_failed_or_cancelled_job_projects_blocked_without_private_content(status) -> None:
    job = _job()
    job["status"] = status
    job["error"] = {
        "error_code": "mo.provider_timeout",
        "detail": "private provider detail",
        "retryable": status == "FAILED",
        "dead_lettered": status == "FAILED",
    }

    handoff = build_generation_handoff(
        job, read_model=_ready_read_model(), access_context=_context()
    )

    assert handoff["handoff_status"] == "BLOCKED"
    assert handoff["generation"] is handoff["content"] is None
    assert handoff["job"]["error"] == {
        "error_code": "mo.provider_timeout",
        "retryable": status == "FAILED",
        "dead_lettered": status == "FAILED",
    }


def test_succeeded_job_fails_retryably_until_durable_result_is_consistent() -> None:
    job = _job()
    job["status"] = "SUCCEEDED"
    with pytest.raises(GenerationHandoffError) as unavailable:
        build_generation_handoff(job, read_model=None, access_context=_context())
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True

    pending = _ready_read_model()
    pending.metadata["status"] = "RUNNING"
    with pytest.raises(GenerationHandoffError) as inconsistent:
        build_generation_handoff(job, read_model=pending, access_context=_context())
    assert inconsistent.value.error_code == "cx.generation_handoff.result_pending"

    missing = _ready_read_model()
    missing.content = None
    with pytest.raises(GenerationHandoffError) as content_pending:
        build_generation_handoff(job, read_model=missing, access_context=_context())
    assert content_pending.value.error_code == "cx.generation_handoff.content_pending"


def test_read_model_failure_is_mapped_without_losing_retryability() -> None:
    job = _job()
    job["status"] = "SUCCEEDED"
    read_model = _ready_read_model()
    read_model.failure = GenerationReadModelError(
        "cx.generation_content_integrity_failed",
        "integrity failed",
        status_code=503,
        retryable=True,
    )

    with pytest.raises(GenerationHandoffError) as raised:
        build_generation_handoff(job, read_model=read_model, access_context=_context())

    assert raised.value.error_code == "cx.generation_content_integrity_failed"
    assert raised.value.retryable is True
    assert str(raised.value) == "integrity failed"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra="x"),
        lambda value: value.update(handoff_schema_version="old"),
        lambda value: value.update(handoff_status="UNKNOWN"),
        lambda value: value.update(next_action="RETRY"),
        lambda value: value.update(owner_scope_enforced=False),
        lambda value: value.update(job=None),
        lambda value: value.update(handoff_status="READY", next_action="PRESENT_GENERATION_TO_OWNER"),
    ],
)
def test_handoff_contract_rejects_invalid_shapes(mutation) -> None:
    value = build_generation_handoff(
        _job(), read_model=_ready_read_model(), access_context=_context()
    )
    mutation(value)

    with pytest.raises(GenerationHandoffError):
        validate_generation_handoff(value)


def test_handoff_contract_rejects_content_in_non_ready_and_invalid_ready_payloads() -> None:
    pending = build_generation_handoff(
        _job(), read_model=_ready_read_model(), access_context=_context()
    )
    pending["content"] = {"content": "must not leak"}
    with pytest.raises(GenerationHandoffError):
        validate_generation_handoff(pending)

    job = _job()
    job["status"] = "SUCCEEDED"
    ready = build_generation_handoff(
        job, read_model=_ready_read_model(), access_context=_context()
    )
    bad_metadata = deepcopy(ready)
    bad_metadata["generation"]["cx_generation_id"] = "other"
    with pytest.raises(GenerationHandoffError):
        validate_generation_handoff(bad_metadata)

    bad_content = deepcopy(ready)
    bad_content["content"]["owner_scope_enforced"] = False
    with pytest.raises(GenerationHandoffError):
        validate_generation_handoff(bad_content)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("async_generation_schema_version", "old"),
        ("job_id", ""),
        ("status", "UNKNOWN"),
        ("attempt_count", True),
        ("attempt_count", -1),
        ("max_attempts", True),
        ("max_attempts", 0),
        ("attempt_count", 4),
        ("retryable", "yes"),
        ("links", []),
        ("error", {"error_code": "bad"}),
    ],
)
def test_handoff_contract_rejects_invalid_job_projection(field, value) -> None:
    handoff = build_generation_handoff(
        _job(), read_model=_ready_read_model(), access_context=_context()
    )
    handoff["job"][field] = value

    with pytest.raises(GenerationHandoffError):
        validate_generation_handoff(handoff)


def _headers(subject_id: str = "employee-0996") -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-0996",
        "traceparent": (
            "00-99600000000000000000000000000001-00f067aa0ba902b7-01"
        ),
        "X-NEX-Tenant-ID": "tenant-0996",
        "X-NEX-Subject-ID": subject_id,
    }


def test_owner_handoff_route_polls_and_cross_owner_is_hidden(tmp_path) -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    queue = InMemoryJobQueue()
    queued = queue.enqueue(_job())
    register_async_generation_operations_routes(
        app,
        job_queue=queue,
        runtime=None,
        request_store=FileSystemCxPrivateTextStore(tmp_path / "requests"),
        read_model=_ready_read_model(),
    )
    client = TestClient(app)

    pending = client.get(
        f"/api/v1/generation-jobs/{queued['job_id']}/handoff",
        headers=_headers(),
    )
    hidden = client.get(
        f"/api/v1/generation-jobs/{queued['job_id']}/handoff",
        headers=_headers("employee-other"),
    )

    assert pending.status_code == 200
    assert pending.json()["handoff_status"] == "PENDING"
    assert hidden.status_code == 404


def test_handoff_route_requires_auth_and_reports_missing_read_model(tmp_path) -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    queue = InMemoryJobQueue()
    queued = queue.enqueue(_job())
    queue.start_job(queued["job_id"])
    queue.complete_job(queued["job_id"])
    register_async_generation_operations_routes(
        app,
        job_queue=queue,
        runtime=None,
        request_store=FileSystemCxPrivateTextStore(tmp_path / "requests"),
    )
    client = TestClient(app)

    assert client.get(
        f"/api/v1/generation-jobs/{queued['job_id']}/handoff"
    ).status_code == 401
    unavailable = client.get(
        f"/api/v1/generation-jobs/{queued['job_id']}/handoff",
        headers=_headers(),
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["retryable"] is True


def test_handoff_route_emits_metadata_only_success_and_failure_events(tmp_path) -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    queue = InMemoryJobQueue()
    pending_job = queue.enqueue(_job())
    succeeded_job = queue.enqueue(
        _job(
            generation_id="cx-generation-0999-failure",
            admission_id="admission-0999-failure",
        )
    )
    queue.start_job(succeeded_job["job_id"])
    queue.complete_job(succeeded_job["job_id"])
    events = InMemoryOperationalEventStore()
    register_async_generation_operations_routes(
        app,
        job_queue=queue,
        runtime=None,
        request_store=FileSystemCxPrivateTextStore(tmp_path / "requests"),
        event_emitter=OperationalEventEmitter(service_id="nex-cx", store=events),
    )
    client = TestClient(app)

    pending = client.get(
        f"/api/v1/generation-jobs/{pending_job['job_id']}/handoff",
        headers=_headers(),
    )
    failed = client.get(
        f"/api/v1/generation-jobs/{succeeded_job['job_id']}/handoff",
        headers=_headers(),
    )

    assert pending.status_code == 200
    assert failed.status_code == 503
    observed = events.list_events()
    assert {event["event_type"] for event in observed} == {
        "cx.generation_handoff.observed",
        "cx.generation_handoff.failed",
    }
    assert all("content" not in event["details"] for event in observed)
