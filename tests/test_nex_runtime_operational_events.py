from __future__ import annotations

from typing import Any

import pytest

from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventError,
    build_operational_event,
    normalize_operational_event_limit,
    redact_operational_details,
    summarize_operational_events,
    validate_operational_event,
)

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
NOW = "2026-08-05T00:00:00Z"


def sample_event(**overrides: Any) -> dict[str, Any]:
    event = build_operational_event(
        service_id=overrides.pop("service_id", "nex-cx"),
        event_type=overrides.pop("event_type", "cx.processing.completed"),
        severity=overrides.pop("severity", "info"),
        message=overrides.pop("message", "Document processing completed."),
        trace_id=overrides.pop("trace_id", TRACE_ID),
        request_id=overrides.pop("request_id", REQUEST_ID),
        subject_ref=overrides.pop("subject_ref", {"type": "cx.document", "id": "doc-001"}),
        details=overrides.pop("details", {"pipeline_run_id": "run-001"}),
        created_at=overrides.pop("created_at", NOW),
        event_id=overrides.pop("event_id", "event-001"),
    )
    return {**event, **overrides}


def test_build_operational_event_redacts_sensitive_details_and_normalizes_severity() -> None:
    event = build_operational_event(
        service_id="nex-cx",
        event_type="cx.processing.failed",
        severity="warning",
        message="Document processing failed.",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        subject_ref={"type": "cx.document", "id": "doc-001"},
        details={
            "api_key": "secret-key",
            "nested": {
                "password": "secret-password",
                "safe_count": 2,
                "items": [{"raw_prompt": "private prompt"}],
            },
        },
        created_at=NOW,
    )

    assert event["severity"] == "WARNING"
    assert event["details"]["api_key"] == "<redacted>"
    assert event["details"]["nested"]["password"] == "<redacted>"
    assert event["details"]["nested"]["items"][0]["raw_prompt"] == "<redacted>"
    assert event["details"]["nested"]["safe_count"] == 2
    assert "secret-key" not in str(event)
    assert "private prompt" not in str(event)


def test_build_operational_event_allows_unscoped_trace_and_subject() -> None:
    event = build_operational_event(
        service_id="nex-ag",
        event_type="ag.operator.query",
        severity="DEBUG",
        message="Operator queried events.",
        details={},
        created_at=NOW,
    )

    assert event["trace_id"] is None
    assert event["request_id"] is None
    assert event["subject_ref"] is None


@pytest.mark.parametrize(
    ("mutator", "error_code"),
    [
        (lambda event: event.pop("event_id"), "operational_event.invalid"),
        (lambda event: event.__setitem__("event_schema_version", "other"), "operational_event.schema_version_invalid"),
        (lambda event: event.__setitem__("service_id", ""), "operational_event.field_invalid"),
        (lambda event: event.__setitem__("severity", "NOTICE"), "operational_event.severity_invalid"),
        (lambda event: event.__setitem__("message", "x" * 513), "operational_event.message_too_long"),
        (lambda event: event.__setitem__("trace_id", ""), "operational_event.field_invalid"),
        (lambda event: event.__setitem__("request_id", ""), "operational_event.field_invalid"),
        (lambda event: event.__setitem__("event_id", 123), "operational_event.field_invalid"),
        (lambda event: event.__setitem__("subject_ref", "doc-001"), "operational_event.subject_ref_invalid"),
        (lambda event: event.__setitem__("subject_ref", {"type": "", "id": "doc-001"}), "operational_event.field_invalid"),
        (lambda event: event.__setitem__("details", []), "operational_event.details_invalid"),
    ],
)
def test_validate_operational_event_rejects_invalid_shapes(
    mutator: Any,
    error_code: str,
) -> None:
    event = sample_event()
    mutator(event)

    with pytest.raises(OperationalEventError) as exc_info:
        validate_operational_event(event)

    assert exc_info.value.error_code == error_code
    assert str(exc_info.value)


def test_redact_operational_details_handles_lists_and_plain_values() -> None:
    assert redact_operational_details("plain") == "plain"
    assert redact_operational_details(
        [{"service_token": "abc"}, {"safe": ["ok", {"source_text": "hidden"}]}]
    ) == [{"service_token": "<redacted>"}, {"safe": ["ok", {"source_text": "<redacted>"}]}]


def test_in_memory_operational_event_store_filters_sorts_limits_and_returns_copies() -> None:
    store = InMemoryOperationalEventStore()
    store.append(sample_event(event_id="event-001", created_at="2026-08-05T00:00:00Z"))
    store.append(
        sample_event(
            event_id="event-002",
            service_id="nex-mo",
            severity="ERROR",
            event_type="mo.provider.failed",
            trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            created_at="2026-08-05T00:00:02Z",
        )
    )
    store.append(
        sample_event(
            event_id="event-003",
            severity="WARNING",
            event_type="cx.processing.failed",
            created_at="2026-08-05T00:00:01Z",
        )
    )

    first = store.get_event("event-001")
    assert first is not None
    first["severity"] = "CRITICAL"

    assert store.get_event("event-001")["severity"] == "INFO"
    assert [event["event_id"] for event in store.list_events(limit=2)] == [
        "event-002",
        "event-003",
    ]
    assert [event["event_id"] for event in store.list_events(service_id="nex-cx")] == [
        "event-003",
        "event-001",
    ]
    assert [event["event_id"] for event in store.list_events(severity="error")] == [
        "event-002"
    ]
    assert [event["event_id"] for event in store.list_events(event_type="cx.processing.failed")] == [
        "event-003"
    ]
    assert store.list_events(trace_id="missing") == []


def test_operational_event_store_is_idempotent_by_event_id_and_summarizes() -> None:
    store = InMemoryOperationalEventStore()
    first = store.append(sample_event(event_id="event-001", severity="INFO"))
    duplicate = store.append(sample_event(event_id="event-001", severity="ERROR"))

    assert duplicate == first
    assert store.summary()["by_severity"]["INFO"] == 1
    summary = summarize_operational_events(
        [*store.list_events(), {"service_id": "unknown-service", "severity": "NOTICE"}]
    )
    assert summary["by_service"] == {"nex-cx": 1, "unknown-service": 1}
    assert "NOTICE" not in summary["by_severity"]


def test_normalize_operational_event_limit_clamps_bounds() -> None:
    assert normalize_operational_event_limit(0) == 1
    assert normalize_operational_event_limit(10) == 10
    assert normalize_operational_event_limit(9999) == 500
