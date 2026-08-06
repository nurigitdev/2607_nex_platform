from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import nex_runtime.operational_events as runtime_events
from nex_runtime import (
    AG_JOB_CONTROL_EVENT_FAILED,
    AG_JOB_CONTROL_EVENT_SUCCEEDED,
    CX_PROCESSING_EVENT_FAILED,
    CX_PROCESSING_EVENT_STARTED,
    CX_PROCESSING_EVENT_SUCCEEDED,
    CX_WORKER_LIFECYCLE_EVENT_BUSY,
    CX_WORKER_LIFECYCLE_EVENT_ERROR,
    CX_WORKER_LIFECYCLE_EVENT_IDLE,
    DEFAULT_OPERATIONAL_EVENT_TAXONOMY,
    DatabasePoolSettings,
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    OperationalEventError,
    OperationalEventEmitResult,
    OperationalEventTypeSpec,
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_session_factory,
    build_operational_event,
    list_operational_event_taxonomy,
    normalize_operational_event_limit,
    operational_event_emitter_from_app,
    operational_event_taxonomy_by_type,
    redact_operational_details,
    summarize_operational_event_taxonomy,
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


def sqlite_event_store() -> SqlAlchemyOperationalEventStore:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_operational_events (
                    event_id TEXT PRIMARY KEY,
                    event_schema_version TEXT NOT NULL DEFAULT 'operational_event.v1',
                    service_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    trace_id TEXT,
                    request_id TEXT,
                    subject_type TEXT,
                    subject_id TEXT,
                    message TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
        )
    return SqlAlchemyOperationalEventStore(build_session_factory(engine))


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

    observed = build_operational_event(
        service_id="nex-ag",
        event_type="ag.operator.query",
        severity="DEBUG",
        message="Operator queried events.",
    )
    assert observed["created_at"].endswith("Z")


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


def test_operational_event_taxonomy_lists_filters_and_summarizes_cx_specs() -> None:
    taxonomy = list_operational_event_taxonomy()
    ag_taxonomy = list_operational_event_taxonomy(service_id="nex-ag")
    cx_taxonomy = list_operational_event_taxonomy(service_id="nex-cx")
    failed = list_operational_event_taxonomy(event_type=CX_PROCESSING_EVENT_FAILED)
    by_type = operational_event_taxonomy_by_type()
    summary = summarize_operational_event_taxonomy(taxonomy)

    assert [item["event_type"] for item in cx_taxonomy] == [
        CX_PROCESSING_EVENT_FAILED,
        CX_PROCESSING_EVENT_STARTED,
        CX_PROCESSING_EVENT_SUCCEEDED,
        CX_WORKER_LIFECYCLE_EVENT_BUSY,
        CX_WORKER_LIFECYCLE_EVENT_ERROR,
        CX_WORKER_LIFECYCLE_EVENT_IDLE,
    ]
    assert [item["event_type"] for item in ag_taxonomy] == [
        AG_JOB_CONTROL_EVENT_FAILED,
        AG_JOB_CONTROL_EVENT_SUCCEEDED,
    ]
    assert failed == [by_type[CX_PROCESSING_EVENT_FAILED]]
    assert by_type[AG_JOB_CONTROL_EVENT_SUCCEEDED]["subject_type"] == "job"
    assert by_type[AG_JOB_CONTROL_EVENT_FAILED]["default_severity"] == "ERROR"
    assert by_type[CX_PROCESSING_EVENT_STARTED]["default_severity"] == "INFO"
    assert by_type[CX_PROCESSING_EVENT_SUCCEEDED]["detail_keys"] == [
        "pipeline_run_id",
        "job_id",
        "job_status",
        "step_summary",
    ]
    assert by_type[CX_WORKER_LIFECYCLE_EVENT_ERROR]["subject_type"] == "worker"
    assert by_type[CX_WORKER_LIFECYCLE_EVENT_ERROR]["detail_keys"] == [
        "worker_id",
        "worker_type",
        "worker_status",
        "active_job_id",
        "pipeline_run_id",
        "document_id",
        "job_id",
        "job_status",
        "step_summary",
        "failed_step",
        "heartbeat_emit_ok",
        "heartbeat_error_code",
    ]
    assert summary["total"] == len(DEFAULT_OPERATIONAL_EVENT_TAXONOMY)
    assert summary["by_service"] == {"nex-ag": 2, "nex-cx": 6}
    assert summary["by_severity"]["INFO"] == 5
    assert summary["by_severity"]["ERROR"] == 3
    assert summary["by_subject_type"] == {"cx.document": 3, "job": 2, "worker": 3}


def test_operational_event_taxonomy_rejects_invalid_or_sensitive_shapes() -> None:
    with pytest.raises(OperationalEventError) as bad_severity:
        OperationalEventTypeSpec(
            service_id="nex-cx",
            event_type="cx.bad",
            default_severity="NOTICE",
            subject_type="cx.document",
            detail_keys=(),
            description="Bad severity.",
        )
    with pytest.raises(OperationalEventError) as bad_detail_key:
        OperationalEventTypeSpec(
            service_id="nex-cx",
            event_type="cx.bad",
            default_severity="INFO",
            subject_type="cx.document",
            detail_keys=("api_key",),
            description="Bad detail key.",
        )
    with pytest.raises(OperationalEventError) as empty_detail_key:
        OperationalEventTypeSpec(
            service_id="nex-cx",
            event_type="cx.bad",
            default_severity="INFO",
            subject_type="cx.document",
            detail_keys=("",),
            description="Bad detail key.",
        )

    assert bad_severity.value.error_code == "operational_event_taxonomy.severity_invalid"
    assert bad_detail_key.value.error_code == "operational_event_taxonomy.detail_key_sensitive"
    assert empty_detail_key.value.error_code == "operational_event_taxonomy.detail_key_invalid"


def test_operational_event_emit_result_summarizes_success_and_failure() -> None:
    source_event = sample_event()
    success = OperationalEventEmitResult.emitted(source_event)
    failure = OperationalEventEmitResult.failed(
        error_code="operational_event.store_unavailable",
        detail="store unavailable",
        status_code=503,
    )

    assert success.to_summary() == {
        "ok": True,
        "event_id": "event-001",
        "service_id": "nex-cx",
        "event_type": "cx.processing.completed",
        "severity": "INFO",
    }
    assert failure.to_summary() == {
        "ok": False,
        "error_code": "operational_event.store_unavailable",
        "detail": "store unavailable",
        "status_code": 503,
    }

    source_event["severity"] = "CRITICAL"
    assert success.event is not None
    assert success.event["severity"] == "INFO"


def test_operational_event_emitter_emits_service_scoped_redacted_events() -> None:
    store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=store)

    event = emitter.emit(
        event_type="cx.processing.completed",
        severity="info",
        message="Document processing completed.",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        subject_ref={"type": "cx.document", "id": "doc-001"},
        details={"safe": "yes", "password": "hidden"},
        created_at=NOW,
        event_id="emitted-event-001",
    )

    assert event["service_id"] == "nex-cx"
    assert event["severity"] == "INFO"
    assert event["details"] == {"safe": "yes", "password": "<redacted>"}
    assert store.get_event("emitted-event-001") == event


def test_operational_event_emitter_safe_emit_returns_success_result() -> None:
    store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=store)

    result = emitter.safe_emit(
        event_type="cx.processing.completed",
        severity="info",
        message="Document processing completed.",
        details={"source_text": "private document text"},
        created_at=NOW,
        event_id="safe-event-001",
    )

    assert result.ok is True
    assert result.error_code is None
    assert result.event is not None
    assert result.event["details"]["source_text"] == "<redacted>"
    assert "private document text" not in str(result)
    assert store.get_event("safe-event-001") == result.event


def test_operational_event_emitter_safe_emit_reports_validation_failure_without_storing() -> None:
    store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=store)

    result = emitter.safe_emit(
        event_type="cx.processing.completed",
        severity="notice",
        message="Document processing completed.",
        created_at=NOW,
        event_id="invalid-event-001",
    )

    assert result.ok is False
    assert result.error_code == "operational_event.severity_invalid"
    assert result.status_code == 422
    assert store.get_event("invalid-event-001") is None


def test_operational_event_emitter_safe_emit_reports_store_failures() -> None:
    class BrokenStore:
        def append(self, event: dict[str, Any]) -> dict[str, Any]:
            raise OperationalEventError(
                error_code="operational_event.store_unavailable",
                detail="operational event store is unavailable",
                status_code=503,
            )

        def get_event(self, event_id: str) -> dict[str, Any] | None:
            return None

        def list_events(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

    emitter = OperationalEventEmitter(service_id="nex-cx", store=BrokenStore())

    result = emitter.safe_emit(
        event_type="cx.processing.completed",
        severity="info",
        message="Document processing completed.",
        created_at=NOW,
        event_id="broken-event-001",
    )

    assert result.to_summary() == {
        "ok": False,
        "error_code": "operational_event.store_unavailable",
        "detail": "operational event store is unavailable",
        "status_code": 503,
    }


def test_operational_event_emitter_safe_emit_hides_unexpected_exception_detail() -> None:
    class ExplodingStore:
        def append(self, event: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("connection failed with secret-token")

        def get_event(self, event_id: str) -> dict[str, Any] | None:
            return None

        def list_events(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

    emitter = OperationalEventEmitter(service_id="nex-cx", store=ExplodingStore())

    result = emitter.safe_emit(
        event_type="cx.processing.completed",
        severity="info",
        message="Document processing completed.",
        created_at=NOW,
        event_id="exploding-event-001",
    )

    assert result.ok is False
    assert result.error_code == "operational_event.emit_failed"
    assert result.detail == "operational event emission failed"
    assert "secret-token" not in str(result.to_summary())


def test_operational_event_emitter_from_app_uses_persistence_store_and_explicit_override() -> None:
    persistence_store = InMemoryOperationalEventStore()
    explicit_store = InMemoryOperationalEventStore()
    app = SimpleNamespace(
        state=SimpleNamespace(
            nex_persistence=SimpleNamespace(operational_event_store=persistence_store)
        )
    )

    persisted_emitter = operational_event_emitter_from_app(app, service_id="nex-cx")
    override_emitter = operational_event_emitter_from_app(
        app,
        service_id="nex-cx",
        store=explicit_store,
    )

    persisted_emitter.emit(
        event_type="cx.processing.started",
        severity="info",
        message="Document processing started.",
        created_at=NOW,
        event_id="persisted-event-001",
    )
    override_emitter.emit(
        event_type="cx.processing.started",
        severity="info",
        message="Document processing started.",
        created_at=NOW,
        event_id="override-event-001",
    )

    assert persistence_store.get_event("persisted-event-001") is not None
    assert persistence_store.get_event("override-event-001") is None
    assert explicit_store.get_event("override-event-001") is not None


def test_operational_event_emitter_from_app_keeps_memory_fallback_on_state() -> None:
    app = SimpleNamespace(state=SimpleNamespace())
    first = operational_event_emitter_from_app(app, service_id="nex-cx")
    second = operational_event_emitter_from_app(app, service_id="nex-cx")

    first.emit(
        event_type="cx.processing.started",
        severity="info",
        message="Document processing started.",
        created_at=NOW,
        event_id="fallback-event-001",
    )

    assert second.store.get_event("fallback-event-001") is not None


def test_operational_event_emitter_from_app_without_state_uses_private_memory_store() -> None:
    emitter = operational_event_emitter_from_app(SimpleNamespace(), service_id="nex-cx")

    event = emitter.emit(
        event_type="cx.processing.started",
        severity="info",
        message="Document processing started.",
        created_at=NOW,
        event_id="stateless-event-001",
    )

    assert emitter.store.get_event("stateless-event-001") == event


def test_sqlalchemy_operational_event_store_filters_sorts_limits_and_returns_copies() -> None:
    store = sqlite_event_store()
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

    assert store.get_event("missing") is None
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
    assert store.summary()["by_service"] == {"nex-mo": 1, "nex-cx": 2}


def test_sqlalchemy_operational_event_store_is_idempotent_by_event_id() -> None:
    store = sqlite_event_store()
    first = store.append(sample_event(event_id="event-001", severity="INFO"))
    duplicate = store.append(sample_event(event_id="event-001", severity="ERROR"))

    assert duplicate == first
    assert store.summary()["by_severity"]["INFO"] == 1


def test_sqlalchemy_operational_event_store_allows_unscoped_events_and_reports_store_failure() -> None:
    store = sqlite_event_store()
    event = store.append(
        build_operational_event(
            service_id="nex-ag",
            event_type="ag.operator.query",
            severity="DEBUG",
            message="Operator queried events.",
            details={},
            created_at=NOW,
            event_id="event-unscoped",
        )
    )

    assert event["trace_id"] is None
    assert event["request_id"] is None
    assert event["subject_ref"] is None

    broken = SqlAlchemyOperationalEventStore(
        build_session_factory(build_engine("sqlite+pysqlite:///:memory:"))
    )
    with pytest.raises(OperationalEventError) as unavailable:
        broken.get_event("event-001")
    assert unavailable.value.error_code == "operational_event.store_unavailable"
    assert unavailable.value.status_code == 503

    with pytest.raises(OperationalEventError) as list_unavailable:
        broken.list_events()
    assert list_unavailable.value.error_code == "operational_event.store_unavailable"


def test_sqlalchemy_operational_event_store_maps_append_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = sample_event(event_id="event-001")
    store = sqlite_event_store()

    def raise_integrity_error(session: object, event_to_store: dict[str, Any]) -> None:
        raise IntegrityError("insert", {}, Exception("duplicate"))

    monkeypatch.setattr(store, "_append_event", raise_integrity_error)
    monkeypatch.setattr(store, "get_event", lambda event_id: event)

    assert store.append(event) == event

    store_without_existing = sqlite_event_store()
    monkeypatch.setattr(store_without_existing, "_append_event", raise_integrity_error)
    with pytest.raises(OperationalEventError) as duplicate_unavailable:
        store_without_existing.append(event)
    assert duplicate_unavailable.value.error_code == "operational_event.store_unavailable"

    store_with_sql_error = sqlite_event_store()

    def raise_sqlalchemy_error(session: object, event_to_store: dict[str, Any]) -> None:
        raise SQLAlchemyError("boom")

    monkeypatch.setattr(store_with_sql_error, "_append_event", raise_sqlalchemy_error)
    with pytest.raises(OperationalEventError) as unavailable:
        store_with_sql_error.append(event)
    assert unavailable.value.error_code == "operational_event.store_unavailable"


def test_sqlalchemy_operational_event_helpers_cover_backend_edges() -> None:
    postgres_engine = build_engine(
        "postgresql://user:secret@localhost/nex_cx_dev",
        pool_settings=DatabasePoolSettings(
            service_id="nex-cx",
            env_prefix="NEX_CX",
            workload="api",
            statement_timeout_ms=0,
        ),
    )
    postgres_session = build_session_factory(postgres_engine)()
    try:
        assert runtime_events._details_sql_expression(postgres_session) == "CAST(:details AS JSONB)"
    finally:
        postgres_session.close()

    assert runtime_events._json_loads(None, default={"fallback": "yes"}) == {"fallback": "yes"}
    assert runtime_events._json_loads({"already": "dict"}, default={}) == {"already": "dict"}
    assert runtime_events._json_loads(b'{"from":"bytes"}', default={}) == {"from": "bytes"}
    assert runtime_events._json_loads(123, default={"fallback": "yes"}) == {"fallback": "yes"}
    assert runtime_events._timestamp_to_wire(datetime(2026, 8, 5, 0, 0, 0)) == (
        "2026-08-05T00:00:00Z"
    )
    assert runtime_events._timestamp_to_wire(datetime(2026, 8, 5, 0, 0, 0, tzinfo=UTC)) == (
        "2026-08-05T00:00:00Z"
    )


def test_normalize_operational_event_limit_clamps_bounds() -> None:
    assert normalize_operational_event_limit(0) == 1
    assert normalize_operational_event_limit(10) == 10
    assert normalize_operational_event_limit(9999) == 500
