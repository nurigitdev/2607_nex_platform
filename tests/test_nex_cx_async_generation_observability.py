from __future__ import annotations

import json

import pytest
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter

from nex_cx import async_generation_observability as observability
from nex_cx.async_generation_observability import observe_async_generation_job


def _emitter():
    store = InMemoryOperationalEventStore()
    return OperationalEventEmitter(service_id="nex-cx", store=store), store


def _job(**overrides):
    value = {
        "job_id": "fd03436f-0a47-583f-845c-cb939bf57f45",
        "cx_generation_id": "generation-1",
        "status": "QUEUED",
        "attempt_count": 0,
        "max_attempts": 3,
        "retryable": True,
        "error": None,
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize(
    ("action", "event_type", "severity"),
    [
        ("ENQUEUED", "cx.async_generation.admitted", "INFO"),
        ("JOINED", "cx.async_generation.admitted", "INFO"),
        ("REPLAYED", "cx.async_generation.admitted", "INFO"),
        ("CANCELLED", "cx.async_generation.cancelled", "WARNING"),
    ],
)
def test_emits_metadata_only_lifecycle_events(action, event_type, severity) -> None:
    emitter, store = _emitter()
    job = _job(
        status="CANCELLED" if action == "CANCELLED" else "QUEUED",
        error={
            "error_code": "cancelled" if action == "CANCELLED" else None,
            "dead_lettered": False,
        },
    )

    result = observe_async_generation_job(
        emitter,
        job,
        action=action.lower(),
        trace_id="trace-1",
        request_id="request-1",
    )

    assert result.ok is True
    event = store.list_events()[0]
    assert event["event_type"] == event_type
    assert event["severity"] == severity
    assert event["details"]["action"] == action
    assert event["details"]["generation_id"] == "generation-1"
    serialized = json.dumps(event)
    assert "private prompt" not in serialized
    assert "tenant-1" not in serialized
    assert "user-1" not in serialized


def test_event_identity_is_deterministic_and_error_is_owner_safe() -> None:
    emitter, store = _emitter()
    job = _job(
        status="FAILED",
        attempt_count=3,
        error={
            "error_code": "mo.provider_timeout",
            "retryable": True,
            "dead_lettered": True,
            "detail": "private provider response",
        },
    )

    first = observe_async_generation_job(
        emitter, job, action="CANCELLED", trace_id=None, request_id=None
    )
    second = observe_async_generation_job(
        emitter, job, action="CANCELLED", trace_id=None, request_id=None
    )

    assert first.event["event_id"] == second.event["event_id"]
    details = store.list_events()[0]["details"]
    assert details["error_code"] == "mo.provider_timeout"
    assert details["dead_lettered"] is True
    assert "detail" not in details


@pytest.mark.parametrize(
    "job",
    [
        _job(job_id=""),
        _job(cx_generation_id=None),
        _job(status=[]),
    ],
)
def test_rejects_missing_event_identity(job) -> None:
    emitter, _ = _emitter()
    with pytest.raises(ValueError, match="non-empty string"):
        observe_async_generation_job(
            emitter, job, action="ENQUEUED", trace_id=None, request_id=None
        )


def test_rejects_unknown_action_and_normalizes_optional_values() -> None:
    emitter, store = _emitter()
    with pytest.raises(ValueError, match="unsupported"):
        observe_async_generation_job(
            emitter, _job(), action="started", trace_id=None, request_id=None
        )

    observe_async_generation_job(
        emitter,
        _job(attempt_count=True, max_attempts="3", error={"error_code": " "}),
        action="ENQUEUED",
        trace_id=None,
        request_id=None,
    )
    details = store.list_events()[0]["details"]
    assert details["attempt_count"] == 0
    assert details["max_attempts"] == 0
    assert details["error_code"] is None


def test_observability_constants_are_versioned() -> None:
    assert (
        observability.ASYNC_GENERATION_OBSERVABILITY_SCHEMA_VERSION
        == "cx_async_generation_observability.v1"
    )
