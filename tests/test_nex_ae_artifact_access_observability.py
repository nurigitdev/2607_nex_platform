from __future__ import annotations

import pytest

from nex_ae_api.artifact_access_observability import observe_artifact_access
from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    OperationalEventError,
)


def test_artifact_access_observation_is_metadata_only_and_idempotent() -> None:
    store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ae-api", store=store)
    kwargs = {
        "action": "preview",
        "artifact_file_id": "artifact-file-1380",
        "artifact_id": "artifact-1380",
        "allowed": True,
        "request_id": "request-1380",
        "trace_id": "13801380138013801380138013801380",
    }

    first = observe_artifact_access(emitter, **kwargs)
    second = observe_artifact_access(emitter, **kwargs)

    assert first.ok is True
    assert second.ok is True
    assert first.event == second.event
    assert len(store.events) == 1
    event = first.event or {}
    assert event["event_type"] == "ae.artifact_access.preview.succeeded"
    assert event["details"] == {
        "access_type": "preview",
        "result_code": "SUCCEEDED",
        "artifact_id": "artifact-1380",
        "retryable": False,
        "private_payload_included": False,
    }


def test_blocked_download_and_optional_fields_are_recorded_safely() -> None:
    store = InMemoryOperationalEventStore()
    result = observe_artifact_access(
        OperationalEventEmitter(service_id="nex-ae-api", store=store),
        action="download",
        artifact_file_id="unknown-file-1380",
        artifact_id=None,
        allowed=False,
        request_id=" ",
        trace_id=None,
    )

    assert result.ok is True
    event = result.event or {}
    assert event["severity"] == "WARNING"
    assert event["request_id"] is None
    assert event["trace_id"] is None
    assert event["details"]["result_code"] == "BLOCKED"
    assert event["details"]["artifact_id"] is None


def test_invalid_action_is_rejected() -> None:
    with pytest.raises(ValueError, match="action is invalid"):
        observe_artifact_access(
            OperationalEventEmitter(
                service_id="nex-ae-api",
                store=InMemoryOperationalEventStore(),
            ),
            action="delete",
            artifact_file_id="artifact-file-1380",
            artifact_id=None,
            allowed=False,
            request_id=None,
            trace_id=None,
        )


class _BrokenStore(InMemoryOperationalEventStore):
    def append(self, event):
        del event
        raise OperationalEventError("event.store_unavailable", "unavailable", 503)


def test_store_failure_is_returned_without_private_detail() -> None:
    result = observe_artifact_access(
        OperationalEventEmitter(service_id="nex-ae-api", store=_BrokenStore()),
        action="preview",
        artifact_file_id="artifact-file-1380",
        artifact_id="artifact-1380",
        allowed=True,
        request_id="request-1380",
        trace_id="13801380138013801380138013801380",
    )

    assert result.ok is False
    assert result.error_code == "event.store_unavailable"
    assert result.status_code == 503
