from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import nex_runtime.service_logs as runtime_logs
from nex_runtime import (
    DEFAULT_SERVICE_LOG_LIMIT,
    MAX_SERVICE_LOG_LIMIT,
    SERVICE_LOG_SCHEMA_VERSION,
    SERVICE_LOG_SEVERITIES,
    DatabasePoolSettings,
    InMemoryServiceLogStore,
    REDACTED_LOG_VALUE,
    ServiceLogError,
    SqlAlchemyServiceLogStore,
    build_engine,
    build_session_factory,
    build_service_log_entry,
    normalize_service_log_limit,
    redact_service_log_attributes,
    service_log_store_from_app,
    summarize_service_logs,
    validate_service_log_entry,
)


NOW = "2026-08-05T00:00:02Z"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def sample_log(**overrides: Any) -> dict[str, Any]:
    log = build_service_log_entry(
        service_id=overrides.pop("service_id", "nex-cx"),
        severity=overrides.pop("severity", "info"),
        logger_name=overrides.pop("logger_name", "nex_cx.processing"),
        message=overrides.pop("message", "Document processing job claimed."),
        trace_id=overrides.pop("trace_id", TRACE_ID),
        request_id=overrides.pop("request_id", REQUEST_ID),
        job_id=overrides.pop("job_id", "job-001"),
        subject_ref=overrides.pop("subject_ref", {"type": "cx.document", "id": "doc-001"}),
        attributes=overrides.pop(
            "attributes",
            {
                "job_type": "cx.document_processing",
                "worker_id": "cx-worker-001",
                "attempt_count": 1,
            },
        ),
        observed_at=overrides.pop("observed_at", NOW),
        log_id=overrides.pop("log_id", "log-001"),
    )
    return {**log, **overrides}


def sqlite_log_store() -> SqlAlchemyServiceLogStore:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_log_entries (
                    log_id TEXT PRIMARY KEY,
                    service_log_schema_version TEXT NOT NULL DEFAULT 'service_log_entry.v1',
                    service_id TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    logger_name TEXT NOT NULL,
                    message TEXT NOT NULL,
                    trace_id TEXT,
                    request_id TEXT,
                    job_id TEXT,
                    subject_type TEXT,
                    subject_id TEXT,
                    attributes TEXT NOT NULL DEFAULT '{}',
                    redacted_attribute_keys TEXT NOT NULL DEFAULT '[]',
                    observed_at TEXT NOT NULL
                )
                """
            )
        )
    return SqlAlchemyServiceLogStore(build_session_factory(engine))


def test_build_service_log_entry_matches_contract_schema() -> None:
    schema = json.loads(
        (
            Path(__file__).parents[1]
            / "contracts/schemas/common/service_log_entry.v1.schema.json"
        ).read_text(encoding="utf-8")
    )

    log = sample_log(log_id=None)

    jsonschema.validate(instance=log, schema=schema)
    assert log["service_log_schema_version"] == SERVICE_LOG_SCHEMA_VERSION
    assert log["severity"] == "INFO"
    assert log["log_id"]
    assert log["attributes"]["job_type"] == "cx.document_processing"


def test_build_service_log_entry_redacts_sensitive_attribute_keys() -> None:
    log = sample_log(
        log_id=None,
        attributes={
            "worker_id": "cx-worker-001",
            "api_key": "private",
            "provider": {
                "authorization": "Bearer private",
                "mode": "mock",
            },
            "attempts": [
                {"token": "private-token", "count": 1},
                {"count": 2},
            ],
        },
    )

    assert "api_key" not in log["attributes"]
    assert log["attributes"]["provider"]["authorization"] == REDACTED_LOG_VALUE
    assert log["attributes"]["attempts"][0]["token"] == REDACTED_LOG_VALUE
    assert log["redacted_attribute_keys"] == [
        "api_key",
        "attempts[].token",
        "provider.authorization",
    ]
    assert "private" not in str(log)


@pytest.mark.parametrize(
    ("mutator", "error_code"),
    [
        (lambda log: log.pop("service_id"), "service_log.invalid"),
        (
            lambda log: log.__setitem__("service_log_schema_version", "other"),
            "service_log.schema_version_invalid",
        ),
        (lambda log: log.__setitem__("service_id", "nex-unknown"), "service_log.service_id_invalid"),
        (lambda log: log.__setitem__("severity", "BROKEN"), "service_log.severity_invalid"),
        (lambda log: log.__setitem__("trace_id", "bad"), "service_log.trace_id_invalid"),
        (lambda log: log.__setitem__("request_id", ""), "service_log.field_invalid"),
        (lambda log: log.__setitem__("subject_ref", "doc-001"), "service_log.subject_ref_invalid"),
        (lambda log: log.__setitem__("attributes", []), "service_log.attributes_invalid"),
        (
            lambda log: log["attributes"].__setitem__("raw_prompt", "private"),
            "service_log.attribute_key_sensitive",
        ),
        (
            lambda log: log.__setitem__("redacted_attribute_keys", "api_key"),
            "service_log.redacted_keys_invalid",
        ),
        (
            lambda log: log.__setitem__("redacted_attribute_keys", ["api_key", "api_key"]),
            "service_log.redacted_keys_duplicate",
        ),
    ],
)
def test_validate_service_log_entry_rejects_invalid_shapes(
    mutator: Any,
    error_code: str,
) -> None:
    log = sample_log()
    mutator(log)

    with pytest.raises(ServiceLogError) as exc_info:
        validate_service_log_entry(log)

    assert exc_info.value.error_code == error_code


def test_service_log_helpers_cover_edges_and_summaries() -> None:
    assert SERVICE_LOG_SEVERITIES == ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    assert redact_service_log_attributes(None) == {
        "attributes": {},
        "redacted_attribute_keys": [],
    }
    with pytest.raises(ServiceLogError) as bad_attributes:
        redact_service_log_attributes(["not", "object"])  # type: ignore[arg-type]
    with pytest.raises(ServiceLogError) as bad_entry:
        validate_service_log_entry(["not", "object"])  # type: ignore[arg-type]
    with pytest.raises(ServiceLogError) as long_message:
        sample_log(message="x" * 513)
    with pytest.raises(ServiceLogError) as long_logger:
        sample_log(logger_name="x" * 161)
    unscoped = build_service_log_entry(
        service_id="nex-ag",
        severity="debug",
        logger_name="nex_ag.operations",
        message="Operator opened log search.",
    )

    summary = summarize_service_logs(
        [
            sample_log(service_id="nex-cx", severity="INFO"),
            sample_log(service_id="nex-ag", severity="ERROR", attributes={"secret": "private"}),
            {"service_id": "unknown", "severity": "CUSTOM", "redacted_attribute_keys": ["x"]},
        ]
    )

    assert bad_attributes.value.error_code == "service_log.attributes_invalid"
    assert bad_entry.value.error_code == "service_log.invalid"
    assert long_message.value.error_code == "service_log.message_too_long"
    assert long_logger.value.error_code == "service_log.logger_name_too_long"
    assert str(long_logger.value) == long_logger.value.detail
    assert unscoped["trace_id"] is None
    assert unscoped["request_id"] is None
    assert unscoped["job_id"] is None
    assert unscoped["subject_ref"] is None
    assert unscoped["observed_at"].endswith("Z")
    assert summary["total"] == 3
    assert summary["by_severity"]["INFO"] == 1
    assert summary["by_severity"]["ERROR"] == 1
    assert summary["by_service"]["nex-cx"] == 1
    assert summary["by_service"]["unknown"] == 1
    assert summary["redacted_attribute_count"] == 2


def test_in_memory_service_log_store_filters_sorts_limits_and_returns_copies() -> None:
    store = InMemoryServiceLogStore()
    store.append(sample_log(log_id="log-001", observed_at="2026-08-05T00:00:00Z"))
    store.append(
        sample_log(
            log_id="log-002",
            service_id="nex-ag",
            severity="ERROR",
            logger_name="nex_ag.operations",
            request_id="request-002",
            job_id="job-002",
            subject_ref={"type": "ag.job", "id": "job-002"},
            observed_at="2026-08-05T00:00:02Z",
        )
    )
    store.append(
        sample_log(
            log_id="log-003",
            severity="WARNING",
            trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            observed_at="2026-08-05T00:00:01Z",
        )
    )
    duplicate = store.append(
        sample_log(log_id="log-001", message="This duplicate should not replace.")
    )

    first = store.get_log("log-001")
    assert first is not None
    first["severity"] = "CRITICAL"

    assert duplicate["message"] == "Document processing job claimed."
    assert store.get_log("log-001")["severity"] == "INFO"
    assert [entry["log_id"] for entry in store.list_logs(limit=2)] == ["log-002", "log-003"]
    assert [entry["log_id"] for entry in store.list_logs(service_id="nex-cx")] == [
        "log-003",
        "log-001",
    ]
    assert [entry["log_id"] for entry in store.list_logs(severity="error")] == ["log-002"]
    assert [entry["log_id"] for entry in store.list_logs(logger_name="nex_ag.operations")] == [
        "log-002"
    ]
    assert [entry["log_id"] for entry in store.list_logs(trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")] == [
        "log-003"
    ]
    assert [entry["log_id"] for entry in store.list_logs(request_id="request-002")] == [
        "log-002"
    ]
    assert [entry["log_id"] for entry in store.list_logs(job_id="job-002")] == ["log-002"]
    assert [entry["log_id"] for entry in store.list_logs(subject_type="ag.job")] == [
        "log-002"
    ]
    assert [entry["log_id"] for entry in store.list_logs(subject_id="job-002")] == [
        "log-002"
    ]
    assert store.list_logs(trace_id="missing") == []
    assert store.summary()["total"] == 3


def test_sqlalchemy_service_log_store_persists_filters_and_reads_back_json() -> None:
    store = sqlite_log_store()
    first = store.append(
        sample_log(
            log_id="log-001",
            observed_at="2026-08-05T00:00:00Z",
            attributes={
                "worker_id": "cx-worker-001",
                "nested": {"password": "private", "safe": True},
            },
        )
    )
    second = store.append(
        sample_log(
            log_id="log-002",
            severity="ERROR",
            logger_name="nex_cx.processing.worker",
            trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            request_id="request-002",
            job_id="job-002",
            subject_ref={"type": "cx.job", "id": "job-002"},
            observed_at="2026-08-05T00:00:02Z",
        )
    )
    unscoped = store.append(
        sample_log(
            log_id="log-003",
            request_id=None,
            job_id=None,
            subject_ref=None,
            observed_at="2026-08-05T00:00:03Z",
        )
    )
    duplicate = store.append({**second, "message": "duplicate ignored"})

    read_back = store.get_log("log-001")
    assert read_back is not None
    assert first["attributes"]["nested"]["password"] == REDACTED_LOG_VALUE
    assert read_back["attributes"]["nested"]["safe"] is True
    assert read_back["redacted_attribute_keys"] == ["nested.password"]
    assert unscoped["subject_ref"] is None
    assert store.get_log("log-003")["request_id"] is None
    assert duplicate["message"] == second["message"]
    assert store.get_log("missing") is None
    assert [entry["log_id"] for entry in store.list_logs()] == [
        "log-003",
        "log-002",
        "log-001",
    ]
    assert [entry["log_id"] for entry in store.list_logs(severity="error")] == ["log-002"]
    assert [entry["log_id"] for entry in store.list_logs(logger_name="nex_cx.processing.worker")] == [
        "log-002"
    ]
    assert [entry["log_id"] for entry in store.list_logs(trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")] == [
        "log-002"
    ]
    assert [entry["log_id"] for entry in store.list_logs(request_id="request-002")] == [
        "log-002"
    ]
    assert [entry["log_id"] for entry in store.list_logs(job_id="job-002")] == ["log-002"]
    assert [entry["log_id"] for entry in store.list_logs(subject_type="cx.job")] == [
        "log-002"
    ]
    assert [entry["log_id"] for entry in store.list_logs(subject_id="job-002")] == [
        "log-002"
    ]
    assert store.summary()["by_service"]["nex-cx"] == 3


def test_service_log_store_helpers_cover_backend_edges() -> None:
    assert normalize_service_log_limit(0) == 1
    assert normalize_service_log_limit(DEFAULT_SERVICE_LOG_LIMIT) == DEFAULT_SERVICE_LOG_LIMIT
    assert normalize_service_log_limit(MAX_SERVICE_LOG_LIMIT + 1) == MAX_SERVICE_LOG_LIMIT

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
        assert runtime_logs._json_sql_expression(postgres_session, "attributes") == (
            "CAST(:attributes AS JSONB)"
        )
    finally:
        postgres_session.close()

    assert runtime_logs._json_loads(None, default={"fallback": True}) == {"fallback": True}
    assert runtime_logs._json_loads({"already": "dict"}, default={}) == {"already": "dict"}
    assert runtime_logs._json_loads(b'["from-bytes"]', default=[]) == ["from-bytes"]
    assert runtime_logs._json_loads(123, default=[]) == []
    assert runtime_logs._timestamp_to_wire(datetime(2026, 8, 5, 0, 0, 0)) == (
        "2026-08-05T00:00:00Z"
    )
    assert runtime_logs._timestamp_to_wire(datetime(2026, 8, 5, 0, 0, 0, tzinfo=UTC)) == (
        "2026-08-05T00:00:00Z"
    )


def test_service_log_store_from_app_uses_persistence_or_state_fallback() -> None:
    injected = InMemoryServiceLogStore()
    app = SimpleNamespace(state=SimpleNamespace(nex_persistence=SimpleNamespace(service_log_store=injected)))

    assert service_log_store_from_app(app) is injected

    fallback_app = SimpleNamespace(state=SimpleNamespace())
    first = service_log_store_from_app(fallback_app)
    second = service_log_store_from_app(fallback_app)
    assert isinstance(first, InMemoryServiceLogStore)
    assert first is second
    assert isinstance(service_log_store_from_app(SimpleNamespace()), InMemoryServiceLogStore)


def test_sqlalchemy_service_log_store_reports_store_unavailable() -> None:
    class FailingSession:
        def __enter__(self) -> FailingSession:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, *args: object, **kwargs: object) -> object:
            raise SQLAlchemyError("boom")

    store = SqlAlchemyServiceLogStore(lambda: FailingSession())  # type: ignore[arg-type]

    with pytest.raises(ServiceLogError) as exc_info:
        store.get_log("log-001")

    with pytest.raises(ServiceLogError) as list_exc:
        store.list_logs()

    assert exc_info.value.error_code == "service_log.store_unavailable"
    assert list_exc.value.error_code == "service_log.store_unavailable"


def test_sqlalchemy_service_log_store_rolls_back_failed_transaction() -> None:
    class FailingTransactionSession:
        rolled_back = False
        closed = False

        def execute(self, *args: object, **kwargs: object) -> object:
            raise SQLAlchemyError("boom")

        def commit(self) -> None:
            raise AssertionError("commit should not run")

        def rollback(self) -> None:
            self.rolled_back = True

        def close(self) -> None:
            self.closed = True

    session = FailingTransactionSession()
    store = SqlAlchemyServiceLogStore(lambda: session)  # type: ignore[arg-type]

    with pytest.raises(ServiceLogError) as exc_info:
        store.append(sample_log())

    assert exc_info.value.error_code == "service_log.store_unavailable"
    assert session.rolled_back is True
    assert session.closed is True
