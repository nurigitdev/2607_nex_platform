from __future__ import annotations

import json
from typing import Any

from nex_cx.document_intelligence_observability import (
    CX_DOCUMENT_INTELLIGENCE_FAILED_EVENT,
    CX_DOCUMENT_INTELLIGENCE_READY_EVENT,
    CX_DOCUMENT_INTELLIGENCE_SIMILARITY_EVENT,
    observe_document_intelligence_failure,
    observe_document_intelligence_ready,
    observe_document_intelligence_similarity,
)
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter


DOCUMENT_ID = "00000000-0000-0000-0000-000000000096"
SUMMARY_ID = "00000000-0000-0000-0000-000000000196"
EMBEDDING_ID = "00000000-0000-0000-0000-000000000296"
TRACE_ID = "95800000000000000000000000000001"
REQUEST_ID = "request-0958"
SUMMARY_HASH = "a" * 64
EMBEDDING_HASH = "b" * 64
PROFILE_HASH = "c" * 64
PRIVATE_SUMMARY = "PRIVATE_S96_SUMMARY_TEXT"
PRIVATE_VECTOR = [0.1, 0.2, 0.3]


def _emitter() -> tuple[OperationalEventEmitter, InMemoryOperationalEventStore]:
    store = InMemoryOperationalEventStore()
    return OperationalEventEmitter(service_id="nex-cx", store=store), store


def _run_result() -> dict[str, Any]:
    return {
        "status": "READY",
        "summary": {
            "document_summary_id": SUMMARY_ID,
            "summary_text_sha256": SUMMARY_HASH,
            "summary_char_count": len(PRIVATE_SUMMARY),
            "summary_preview": PRIVATE_SUMMARY,
        },
        "summary_embedding": {
            "summary_embedding_id": EMBEDDING_ID,
            "provider_alias": "qwen3-embedding-4b",
            "model_revision": "Qwen3-Embedding-4B",
            "embedding_sha256": EMBEDDING_HASH,
            "vector_dimension": 2560,
            "embedding": PRIVATE_VECTOR,
        },
        "summary_vector": {
            "profile_fingerprint": PROFILE_HASH,
            "freshness": {"state": "READY", "usable": True},
        },
    }


def _similarity_result() -> dict[str, Any]:
    return {
        "source_document": {
            "document_summary_id": SUMMARY_ID,
            "summary_embedding_id": EMBEDDING_ID,
            "profile_fingerprint": PROFILE_HASH,
        },
        "freshness": {"state": "READY", "usable": True},
        "result": {
            "candidate_source": "postgresql_pgvector_summary",
            "candidate_count": 2,
            "minimum_score": 0.5,
            "query_vector": PRIVATE_VECTOR,
            "candidates": [{"summary_preview": PRIVATE_SUMMARY}],
        },
    }


def test_ready_event_is_deterministic_and_metadata_only() -> None:
    emitter, store = _emitter()

    first = observe_document_intelligence_ready(
        emitter,
        document_id=DOCUMENT_ID,
        result=_run_result(),
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )
    second = observe_document_intelligence_ready(
        emitter,
        document_id=DOCUMENT_ID,
        result=_run_result(),
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )

    events = store.list_events(event_type=CX_DOCUMENT_INTELLIGENCE_READY_EVENT)
    assert first.ok is True
    assert first.event == second.event
    assert len(events) == 1
    assert events[0]["subject_ref"] == {"type": "cx.document", "id": DOCUMENT_ID}
    assert events[0]["details"]["summary_char_count"] == len(PRIVATE_SUMMARY)
    assert events[0]["details"]["vector_dimension"] == 2560
    serialized = json.dumps(events)
    assert PRIVATE_SUMMARY not in serialized
    assert str(PRIVATE_VECTOR) not in serialized
    assert "summary_preview" not in serialized
    assert '"embedding":' not in serialized


def test_similarity_event_contains_only_safe_rollup_metadata() -> None:
    emitter, store = _emitter()

    result = observe_document_intelligence_similarity(
        emitter,
        document_id=DOCUMENT_ID,
        result=_similarity_result(),
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )

    events = store.list_events(
        event_type=CX_DOCUMENT_INTELLIGENCE_SIMILARITY_EVENT
    )
    assert result.ok is True
    assert events[0]["details"]["candidate_count"] == 2
    assert events[0]["details"]["minimum_score"] == 0.5
    serialized = json.dumps(events)
    assert PRIVATE_SUMMARY not in serialized
    assert "query_vector" not in serialized
    assert "candidates" not in serialized


def test_failure_event_redacts_detail_and_classifies_severity() -> None:
    emitter, store = _emitter()

    observe_document_intelligence_failure(
        emitter,
        document_id=DOCUMENT_ID,
        operation="run",
        error_code="CX_PROVIDER_UNAVAILABLE",
        status_code=503,
        retryable=True,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )
    observe_document_intelligence_failure(
        emitter,
        document_id=DOCUMENT_ID,
        operation="similarity",
        error_code="CX_REQUEST_INVALID",
        status_code=422,
        retryable=False,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )

    events = store.list_events(event_type=CX_DOCUMENT_INTELLIGENCE_FAILED_EVENT)
    by_operation = {event["details"]["operation"]: event for event in events}
    assert by_operation["run"]["severity"] == "ERROR"
    assert by_operation["similarity"]["severity"] == "WARNING"
    assert by_operation["run"]["details"]["retryable"] is True
    assert by_operation["similarity"]["details"]["retryable"] is False
    assert '"detail":' not in json.dumps(events)


def test_observability_normalizes_malformed_optional_metadata() -> None:
    emitter, store = _emitter()

    observe_document_intelligence_ready(
        emitter,
        document_id=DOCUMENT_ID,
        result={
            "status": " ",
            "summary": [],
            "summary_embedding": "invalid",
            "summary_vector": {"freshness": None},
        },
        trace_id=None,
        request_id=None,
    )
    observe_document_intelligence_similarity(
        emitter,
        document_id=DOCUMENT_ID,
        result={
            "source_document": None,
            "freshness": [],
            "result": {"candidate_count": True, "minimum_score": "high"},
        },
        trace_id=None,
        request_id=None,
    )
    observe_document_intelligence_failure(
        emitter,
        document_id=DOCUMENT_ID,
        operation=" ",
        error_code="",
        status_code=409,
        retryable=False,
        trace_id=None,
        request_id=None,
    )

    ready = store.list_events(event_type=CX_DOCUMENT_INTELLIGENCE_READY_EVENT)[0]
    similar = store.list_events(
        event_type=CX_DOCUMENT_INTELLIGENCE_SIMILARITY_EVENT
    )[0]
    failed = store.list_events(event_type=CX_DOCUMENT_INTELLIGENCE_FAILED_EVENT)[0]
    assert ready["details"]["status"] == "UNKNOWN"
    assert ready["details"]["summary_char_count"] == 0
    assert similar["details"]["candidate_count"] == 0
    assert similar["details"]["minimum_score"] is None
    assert failed["details"]["operation"] == "unknown"
    assert failed["details"]["error_code"] == "CX_DOCUMENT_INTELLIGENCE_FAILED"


def test_emit_failure_never_breaks_document_intelligence_response() -> None:
    class BrokenStore:
        def append(self, _event: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("storage unavailable")

    result = observe_document_intelligence_ready(
        OperationalEventEmitter(service_id="nex-cx", store=BrokenStore()),
        document_id=DOCUMENT_ID,
        result=_run_result(),
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )

    assert result.ok is False
    assert result.error_code == "operational_event.emit_failed"
