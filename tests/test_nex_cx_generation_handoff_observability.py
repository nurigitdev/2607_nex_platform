from __future__ import annotations

import json

import pytest
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter

from nex_cx import generation_handoff_observability as observability
from nex_cx.generation_handoff_observability import (
    observe_generation_handoff,
    observe_generation_handoff_failure,
)


JOB_ID = "fd03436f-0a47-583f-845c-cb939bf57f45"
PRIVATE_CONTENT = "private owner answer [1]"


def _emitter():
    store = InMemoryOperationalEventStore()
    return OperationalEventEmitter(service_id="nex-cx", store=store), store


def _handoff(*, status: str = "READY") -> dict:
    ready = status == "READY"
    return {
        "handoff_status": status,
        "next_action": (
            "PRESENT_GENERATION_TO_OWNER" if ready else "POLL_GENERATION_JOB"
        ),
        "job": {
            "job_id": JOB_ID,
            "cx_generation_id": "generation-0999",
            "status": "SUCCEEDED" if ready else "RUNNING",
            "attempt_count": 1,
            "max_attempts": 3,
            "retryable": not ready,
        },
        "generation": {"status": "COMPLETED"} if ready else None,
        "content": (
            {"content": PRIVATE_CONTENT, "size_bytes": 24} if ready else None
        ),
    }


@pytest.mark.parametrize(
    ("status", "severity", "content_available"),
    [("READY", "INFO", True), ("PENDING", "WARNING", False)],
)
def test_handoff_observation_is_metadata_only(
    status: str,
    severity: str,
    content_available: bool,
) -> None:
    emitter, store = _emitter()

    first = observe_generation_handoff(
        emitter,
        _handoff(status=status),
        trace_id="trace-0999",
        request_id="request-0999",
    )
    second = observe_generation_handoff(
        emitter,
        _handoff(status=status),
        trace_id="trace-0999",
        request_id="request-0999",
    )

    assert first.event["event_id"] == second.event["event_id"]
    event = store.list_events()[0]
    assert event["event_type"] == "cx.generation_handoff.observed"
    assert event["severity"] == severity
    assert event["details"]["handoff_status"] == status
    assert event["details"]["content_available"] is content_available
    assert PRIVATE_CONTENT not in json.dumps(event)
    assert "content" not in event["details"]


@pytest.mark.parametrize("status_code", [409, 503])
def test_handoff_failure_is_classified_and_deterministic(status_code: int) -> None:
    emitter, store = _emitter()

    first = observe_generation_handoff_failure(
        emitter,
        job_id=JOB_ID,
        error_code="cx.generation_handoff.result_pending",
        status_code=status_code,
        retryable=status_code >= 500,
        trace_id=None,
        request_id=None,
    )
    second = observe_generation_handoff_failure(
        emitter,
        job_id=JOB_ID,
        error_code="cx.generation_handoff.result_pending",
        status_code=status_code,
        retryable=status_code >= 500,
        trace_id=None,
        request_id=None,
    )

    assert first.event["event_id"] == second.event["event_id"]
    event = store.list_events()[0]
    assert event["event_type"] == "cx.generation_handoff.failed"
    assert event["severity"] == ("ERROR" if status_code >= 500 else "WARNING")
    assert event["details"]["retryable"] is (status_code >= 500)


@pytest.mark.parametrize(
    "handoff",
    [
        {**_handoff(), "job": {}},
        {**_handoff(), "job": {**_handoff()["job"], "cx_generation_id": ""}},
        {**_handoff(), "handoff_status": []},
    ],
)
def test_handoff_observation_rejects_missing_identity(handoff: dict) -> None:
    emitter, _store = _emitter()
    with pytest.raises(ValueError, match="non-empty string"):
        observe_generation_handoff(
            emitter,
            handoff,
            trace_id=None,
            request_id=None,
        )


def test_handoff_observation_normalizes_optional_metadata() -> None:
    emitter, store = _emitter()
    handoff = _handoff(status="PENDING")
    handoff["next_action"] = []
    handoff["job"]["attempt_count"] = True
    handoff["job"]["max_attempts"] = "3"

    observe_generation_handoff(
        emitter,
        handoff,
        trace_id=None,
        request_id=None,
    )

    details = store.list_events()[0]["details"]
    assert details["next_action"] is None
    assert details["attempt_count"] == 0
    assert details["max_attempts"] == 0
    assert details["content_size_bytes"] is None


@pytest.mark.parametrize(("job_id", "error_code"), [("", "code"), (JOB_ID, " ")])
def test_handoff_failure_rejects_missing_identity(
    job_id: str,
    error_code: str,
) -> None:
    emitter, _store = _emitter()
    with pytest.raises(ValueError, match="non-empty string"):
        observe_generation_handoff_failure(
            emitter,
            job_id=job_id,
            error_code=error_code,
            status_code=500,
            retryable=True,
            trace_id=None,
            request_id=None,
        )


def test_handoff_observability_schema_is_versioned() -> None:
    assert observability.GENERATION_HANDOFF_OBSERVABILITY_SCHEMA_VERSION == (
        "cx_generation_handoff_observability.v1"
    )
