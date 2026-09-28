from __future__ import annotations

from typing import Any

import pytest

from nex_ae_api.async_generation import build_async_generation_projection
from nex_ae_api.generation_lifecycle_observability import (
    AE_GENERATION_LIFECYCLE_EVENT,
    AE_GENERATION_LIFECYCLE_OBSERVABILITY_SCHEMA_VERSION,
    observe_generation_lifecycle_action,
)
from nex_ae_api.generation_progress import build_generation_progress_projection
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter


def _job(status: str, *, retryable: bool = True) -> dict[str, Any]:
    error = None
    if status in {"FAILED", "CANCELLED"}:
        error = {
            "error_code": "cx.provider.private-detail-omitted",
            "retryable": retryable,
            "dead_lettered": not retryable,
        }
    return {
        "job_id": "job-observe",
        "cx_generation_id": "generation-observe",
        "status": status,
        "attempt_count": 1 if status != "QUEUED" else 0,
        "max_attempts": 3,
        "retryable": retryable,
        "links": {
            "generation": "/api/v1/generations/generation-observe",
            "async_job": "/api/v1/generation-jobs/job-observe",
        },
        "error": error,
    }


def _progress(status: str = "RUNNING", *, retryable: bool = True) -> dict[str, Any]:
    projection = build_async_generation_projection(
        {
            "admission_status": "ENQUEUED",
            "job": _job(status, retryable=retryable),
            "generation": None,
        }
    )
    return build_generation_progress_projection(
        interaction_id="interaction-observe",
        async_generation=projection,
    )


@pytest.mark.parametrize(
    "action",
    [
        "PROGRESS_OBSERVED",
        "CANCELLATION_ACCEPTED",
        "CANCELLATION_RECONCILED",
        "RECOVERY_PLANNED",
        "RETRY_ADMITTED",
    ],
)
def test_lifecycle_observability_emits_metadata_only_actions(action: str) -> None:
    store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ae-api", store=store)

    result = observe_generation_lifecycle_action(
        emitter,
        action=action,
        progress=_progress(),
        request_id=" request-observe ",
        trace_id="a" * 32,
    )

    assert result.ok is True
    event = result.event
    assert event["event_type"] == AE_GENERATION_LIFECYCLE_EVENT
    assert event["details"]["observability_schema_version"] == (
        AE_GENERATION_LIFECYCLE_OBSERVABILITY_SCHEMA_VERSION
    )
    assert event["details"]["action"] == action
    assert event["details"]["prompt_content_included"] is False
    assert event["details"]["response_content_included"] is False
    assert event["details"]["owner_identity_included"] is False
    assert event["request_id"] == "request-observe"


def test_lifecycle_observability_warns_for_failed_state_and_is_idempotent() -> None:
    store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ae-api", store=store)
    progress = _progress("FAILED")

    first = observe_generation_lifecycle_action(
        emitter,
        action="RECOVERY_PLANNED",
        progress=progress,
        request_id=None,
        trace_id=" ",
    )
    second = observe_generation_lifecycle_action(
        emitter,
        action="RECOVERY_PLANNED",
        progress=progress,
        request_id=None,
        trace_id=" ",
    )

    assert first.event["severity"] == "WARNING"
    assert first.event["event_id"] == second.event["event_id"]
    assert len(store.events) == 1
    assert "private-detail-omitted" not in str(first.event)


def test_lifecycle_observability_rejects_unknown_action_and_bad_progress() -> None:
    emitter = OperationalEventEmitter(
        service_id="nex-ae-api",
        store=InMemoryOperationalEventStore(),
    )
    with pytest.raises(ValueError, match="unsupported"):
        observe_generation_lifecycle_action(
            emitter,
            action="UNKNOWN",
            progress=_progress(),
            request_id=None,
            trace_id=None,
        )
    with pytest.raises(ValueError):
        observe_generation_lifecycle_action(
            emitter,
            action="PROGRESS_OBSERVED",
            progress={},
            request_id=None,
            trace_id=None,
        )


def test_lifecycle_observability_store_failure_is_non_blocking() -> None:
    class BrokenStore:
        def append(self, event):
            raise RuntimeError("private persistence detail")

    result = observe_generation_lifecycle_action(
        OperationalEventEmitter(service_id="nex-ae-api", store=BrokenStore()),
        action="PROGRESS_OBSERVED",
        progress=_progress(),
        request_id=None,
        trace_id=None,
    )

    assert result.ok is False
    assert "private persistence detail" not in str(result)
