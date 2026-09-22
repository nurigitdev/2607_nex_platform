from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)
from nex_cx.hybrid_retrieval_package import HybridRetrievalPackageError
from nex_cx.ingestion import ContentIngestionStore
from nex_cx.retrieval import register_retrieval_routes
from nex_cx.retrieval_observability import (
    CX_RETRIEVAL_PACKAGE_FAILED_EVENT,
    CX_RETRIEVAL_PACKAGE_OBSERVED_EVENT,
    _failure_event_id,
    _outcome_event_id,
    observe_retrieval_failure,
    observe_retrieval_package,
)


TRACE_ID = "94800000000000000000000000000001"
PRIVATE_QUERY = "PRIVATE_S95_QUERY"
PRIVATE_EVIDENCE = "PRIVATE_S95_EVIDENCE"


class _Runtime:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result

    def build_package(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _FailingStore(ContentIngestionStore):
    def save_retrieval_package(self, package: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError(f"storage failed: {package['query_text']}")


class _ExplodingEventStore:
    def append(self, _event: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("SECRET_EVENT_STORE")


def test_success_event_is_metadata_only_and_deterministic() -> None:
    client, events = _client(_Runtime(_package()))

    response = client.post(
        "/api/v1/retrieval/context",
        headers=_headers(),
        json=_payload(),
    )

    assert response.status_code == 200
    observed = events.list_events(event_type=CX_RETRIEVAL_PACKAGE_OBSERVED_EVENT)
    assert len(observed) == 1
    event = observed[0]
    assert event["severity"] == "INFO"
    assert event["subject_ref"] == {
        "type": "cx.retrieval_package",
        "id": "package-0948",
    }
    assert event["details"] == {
        "observability_schema_version": "cx_retrieval_observability.v1",
        "retrieval_status": "READY",
        "runtime_schema_version": "cx_hybrid_retrieval_runtime.v1",
        "policy_id": "weighted_rrf_vector_bm25_v1",
        "permission_policy_version": "cx.private_owner_active.v1",
        "rerank_state": "APPLIED",
        "evidence_count": 1,
        "document_count": 1,
        "candidate_count": 2,
        "warning_count": 0,
        "no_answer_reason": None,
    }
    assert event["event_id"] == _outcome_event_id(
        package_id="package-0948",
        status="READY",
    )
    serialized = json.dumps(event)
    assert PRIVATE_QUERY not in serialized
    assert PRIVATE_EVIDENCE not in serialized
    assert "owner-one" not in serialized
    assert "document-one" not in serialized


def test_known_failure_emits_redacted_retry_evidence() -> None:
    error = HybridRetrievalPackageError(
        status_code=503,
        error_code="CX_HYBRID_CANDIDATE_PROVIDER_UNAVAILABLE",
        detail="provider SECRET failed",
        retryable=True,
    )
    client, events = _client(_Runtime(error))

    response = client.post(
        "/api/v1/retrieval/context",
        headers=_headers(),
        json=_payload(),
    )

    assert response.status_code == 503
    failures = events.list_events(event_type=CX_RETRIEVAL_PACKAGE_FAILED_EVENT)
    assert len(failures) == 1
    event = failures[0]
    assert event["severity"] == "ERROR"
    assert event["subject_ref"] is None
    assert event["details"] == {
        "observability_schema_version": "cx_retrieval_observability.v1",
        "error_code": "CX_HYBRID_CANDIDATE_PROVIDER_UNAVAILABLE",
        "status_code": 503,
        "retryable": True,
        "failure_stage": "package_build",
        "runtime_mode": "hardened",
    }
    assert "SECRET" not in json.dumps(event)


def test_persistence_failure_is_redacted_and_observed() -> None:
    client, events = _client(_Runtime(_package()), store=_FailingStore())

    response = client.post(
        "/api/v1/retrieval/context",
        headers=_headers(),
        json=_payload(),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "CX_RETRIEVAL_PERSISTENCE_UNAVAILABLE"
    assert PRIVATE_QUERY not in response.text
    failure = events.list_events(event_type=CX_RETRIEVAL_PACKAGE_FAILED_EVENT)[0]
    assert failure["details"]["failure_stage"] == "persistence"
    assert failure["details"]["retryable"] is True


def test_unexpected_runtime_failure_is_redacted_and_observed() -> None:
    client, events = _client(_Runtime(RuntimeError(f"failed: {PRIVATE_QUERY}")))

    response = client.post(
        "/api/v1/retrieval/context",
        headers=_headers(),
        json=_payload(),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "CX_RETRIEVAL_RUNTIME_UNAVAILABLE"
    assert PRIVATE_QUERY not in response.text
    failure = events.list_events(event_type=CX_RETRIEVAL_PACKAGE_FAILED_EVENT)[0]
    assert failure["details"]["failure_stage"] == "package_build"
    assert failure["details"]["error_code"] == "CX_RETRIEVAL_RUNTIME_UNAVAILABLE"


def test_observability_store_failure_never_fails_retrieval() -> None:
    emitter = OperationalEventEmitter(
        service_id="nex-cx",
        store=_ExplodingEventStore(),  # type: ignore[arg-type]
    )
    client, _events = _client(_Runtime(_package()), emitter=emitter)

    response = client.post(
        "/api/v1/retrieval/context",
        headers=_headers(),
        json=_payload(),
    )

    assert response.status_code == 200
    assert response.json()["retrieval_package_id"] == "package-0948"


def test_observability_helpers_normalize_sparse_metadata_and_warning_severity() -> None:
    events = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=events)

    result = observe_retrieval_package(
        emitter,
        {
            "retrieval_package_id": None,
            "status": "low_confidence",
            "retrieval_profile": "bad",
            "score_summary": None,
            "source_summary": {
                "document_count": True,
                "chunk_count": "bad",
            },
            "permission_snapshot": [],
            "evidence_items": "bad",
            "warnings": None,
            "trace_id": 1,
            "request_id": " ",
        },
    )

    assert result.ok is True
    event = events.list_events()[0]
    assert event["severity"] == "WARNING"
    assert event["subject_ref"]["id"] == "unknown"
    assert event["trace_id"] is None
    assert event["details"]["evidence_count"] == 0
    assert event["details"]["document_count"] == 0
    assert event["details"]["policy_id"] is None


def test_failure_helper_normalizes_empty_values_and_warning_severity() -> None:
    events = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=events)

    first = observe_retrieval_failure(
        emitter,
        error_code=" ",
        status_code=422,
        retryable=False,
        stage=" ",
        runtime_mode=" ",
        trace_id=None,
        request_id=None,
    )
    second = observe_retrieval_failure(
        emitter,
        error_code=" ",
        status_code=422,
        retryable=False,
        stage=" ",
        runtime_mode=" ",
        trace_id=None,
        request_id=None,
    )

    assert first.ok is True
    assert second.event == first.event
    event = events.list_events()[0]
    assert event["severity"] == "WARNING"
    assert event["details"]["error_code"] == "CX_RETRIEVAL_FAILED"
    assert event["details"]["failure_stage"] == "unknown"
    assert event["details"]["runtime_mode"] == "unknown"
    assert event["event_id"] == _failure_event_id(
        error_code="CX_RETRIEVAL_FAILED",
        stage="unknown",
        runtime_mode="unknown",
        trace_id=None,
        request_id=None,
    )


def test_authentication_failure_does_not_emit_untrusted_event() -> None:
    client, events = _client(_Runtime(_package()))

    response = client.post("/api/v1/retrieval/context", json=_payload())

    assert response.status_code == 401
    assert events.list_events() == []


def _client(
    runtime: _Runtime,
    *,
    store: ContentIngestionStore | None = None,
    emitter: OperationalEventEmitter | None = None,
) -> tuple[TestClient, InMemoryOperationalEventStore]:
    events = InMemoryOperationalEventStore()
    selected_emitter = emitter or OperationalEventEmitter(
        service_id="nex-cx",
        store=events,
    )
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_retrieval_routes(
        app,
        store=store or ContentIngestionStore(),
        hybrid_runtime=runtime,
        event_emitter=selected_emitter,
    )
    return TestClient(app), events


def _payload() -> dict[str, Any]:
    return {
        "query_text": PRIVATE_QUERY,
        "document_scope": {"document_ids": ["document-one"]},
    }


def _package() -> dict[str, Any]:
    return {
        "retrieval_package_id": "package-0948",
        "retrieval_runtime_schema_version": "cx_hybrid_retrieval_runtime.v1",
        "status": "READY",
        "trace_id": TRACE_ID,
        "request_id": "request-0948",
        "query_text": PRIVATE_QUERY,
        "retrieval_profile": {
            "quality_policy": {"policy_id": "weighted_rrf_vector_bm25_v1"}
        },
        "permission_snapshot": {
            "actor_id": "owner-one",
            "policy_version": "cx.private_owner_active.v1",
        },
        "score_summary": {"rerank_state": "APPLIED"},
        "source_summary": {"document_count": 1, "chunk_count": 2},
        "evidence_items": [
            {
                "content_object_id": "document-one",
                "text": PRIVATE_EVIDENCE,
            }
        ],
        "warnings": [],
        "no_answer_reason": None,
    }


def _headers() -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-NEX-Tenant-ID": "tenant-one",
        "X-NEX-Subject-ID": "owner-one",
        "X-Request-ID": "request-0948",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }
