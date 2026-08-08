from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import nex_runtime.service_logs as runtime_logs
from nex_runtime import (
    DEFAULT_SERVICE_LOG_LIMIT,
    DEFAULT_SERVICE_LOG_RETENTION_HISTORY_LIMIT,
    MAX_SERVICE_LOG_LIMIT,
    MAX_SERVICE_LOG_RETENTION_HISTORY_LIMIT,
    SERVICE_LOG_SCHEMA_VERSION,
    SERVICE_LOG_SEVERITIES,
    DatabasePoolSettings,
    InMemoryServiceLogStore,
    REDACTED_LOG_VALUE,
    SERVICE_LOG_RETENTION_EXECUTION_SCHEMA_VERSION,
    SERVICE_LOG_RETENTION_HISTORY_ENTRY_SCHEMA_VERSION,
    SERVICE_LOG_RETENTION_POLICY_ID,
    SERVICE_SPECS,
    ServiceLogEmitter,
    ServiceLogEmitResult,
    ServiceLogError,
    SqlAlchemyServiceLogStore,
    build_engine,
    build_session_factory,
    build_service_app,
    build_service_log_entry,
    build_service_log_retention_execution,
    build_service_log_retention_history_entry,
    issue_mock_service_token,
    normalize_service_log_limit,
    normalize_service_log_retention_days,
    normalize_service_log_retention_delete_limit,
    normalize_service_log_retention_history_limit,
    redact_service_log_attributes,
    register_service_log_retention_routes,
    service_log_emitter_from_app,
    service_log_store_from_app,
    summarize_service_logs,
    validate_service_log_entry,
    validate_service_log_retention_execution,
    validate_service_log_retention_history_entry,
)


NOW = "2026-08-05T00:00:02Z"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def auth_headers(*, audience: str = "nex-cx") -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ag", audience=audience)
    return {"Authorization": f"Bearer {issued.access_token}"}


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


def test_build_service_log_retention_execution_matches_contract_schema() -> None:
    schema = json.loads(
        (
            Path(__file__).parents[1]
            / "contracts/schemas/common/service_log_retention_execution.v1.schema.json"
        ).read_text(encoding="utf-8")
    )

    execution = build_service_log_retention_execution(
        service_id="nex-cx",
        mode="dry_run",
        execution_status="planned",
        retention_days=1,
        retention_cutoff="2026-07-06T00:00:00+00:00",
        checked_at="2026-08-05T00:00:00Z",
        scan_limit=999,
        max_delete_count=999,
        candidate_count=2,
        idempotency_key="retention-dry-run-nex-cx-20260805",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )

    jsonschema.validate(instance=execution, schema=schema)
    assert execution["retention_execution_schema_version"] == (
        SERVICE_LOG_RETENTION_EXECUTION_SCHEMA_VERSION
    )
    assert execution["policy_id"] == SERVICE_LOG_RETENTION_POLICY_ID
    assert execution["mode"] == "DRY_RUN"
    assert execution["execution_status"] == "PLANNED"
    assert execution["retention_days"] == 7
    assert execution["scan_limit"] == 500
    assert execution["max_delete_count"] == 500
    assert execution["deleted_count"] == 0
    assert execution["requested_by"] == {
        "actor_type": "service",
        "actor_id": "nex-ag",
        "service_id": "nex-ag",
    }
    assert execution["audit"]["audit_event_type"] == "service_log.retention.execution"
    assert execution["audit"]["emitted"] is False
    assert validate_service_log_retention_execution(execution) is execution


def test_build_service_log_retention_history_entry_matches_contract_schema() -> None:
    schema = json.loads(
        (
            Path(__file__).parents[1]
            / "contracts/schemas/common/service_log_retention_history_entry.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    execution = build_service_log_retention_execution(
        service_id="nex-cx",
        mode="EXECUTE",
        execution_status="SUCCEEDED",
        retention_days=30,
        retention_cutoff="2026-07-06T00:00:00Z",
        checked_at="2026-08-05T00:00:00Z",
        candidate_count=3,
        deleted_count=2,
        delete_enabled=True,
        idempotency_key="retention-execute-nex-cx-20260805",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )

    history = build_service_log_retention_history_entry(
        execution,
        recorded_at="2026-08-05T00:00:03+00:00",
    )

    jsonschema.validate(instance=history, schema=schema)
    assert history["retention_history_schema_version"] == (
        SERVICE_LOG_RETENTION_HISTORY_ENTRY_SCHEMA_VERSION
    )
    assert history["execution_id"] == execution["execution_id"]
    assert history["service_id"] == "nex-cx"
    assert history["mode"] == "EXECUTE"
    assert history["execution_status"] == "SUCCEEDED"
    assert history["recorded_at"] == "2026-08-05T00:00:03Z"
    assert history["execution"] == execution
    assert validate_service_log_retention_history_entry(history) is history


def test_service_log_retention_history_entry_rejects_mismatch_and_invalid_shape() -> None:
    execution = build_service_log_retention_execution(
        service_id="nex-cx",
        retention_cutoff="2026-07-06T00:00:00Z",
        checked_at="2026-08-05T00:00:00Z",
    )
    history = build_service_log_retention_history_entry(execution)
    bad_service = json.loads(json.dumps(history))
    bad_service["service_id"] = "nex-ag"
    bad_schema = json.loads(json.dumps(history))
    bad_schema["retention_history_schema_version"] = "other"
    missing = json.loads(json.dumps(history))
    missing.pop("execution_id")

    assert normalize_service_log_retention_history_limit(0) == 1
    assert normalize_service_log_retention_history_limit(
        DEFAULT_SERVICE_LOG_RETENTION_HISTORY_LIMIT
    ) == DEFAULT_SERVICE_LOG_RETENTION_HISTORY_LIMIT
    assert normalize_service_log_retention_history_limit(9999) == (
        MAX_SERVICE_LOG_RETENTION_HISTORY_LIMIT
    )
    with pytest.raises(ServiceLogError) as mismatch_exc:
        validate_service_log_retention_history_entry(bad_service)
    with pytest.raises(ServiceLogError) as schema_exc:
        validate_service_log_retention_history_entry(bad_schema)
    with pytest.raises(ServiceLogError) as missing_exc:
        validate_service_log_retention_history_entry(missing)
    with pytest.raises(ServiceLogError) as object_exc:
        validate_service_log_retention_history_entry(["bad"])  # type: ignore[arg-type]
    with pytest.raises(ServiceLogError) as bad_timestamp:
        build_service_log_retention_history_entry(execution, recorded_at="not-a-time")

    assert mismatch_exc.value.error_code == (
        "service_log_retention_history.execution_mismatch"
    )
    assert schema_exc.value.error_code == (
        "service_log_retention_history.schema_version_invalid"
    )
    assert missing_exc.value.error_code == "service_log_retention_history.invalid"
    assert object_exc.value.error_code == "service_log_retention_history.invalid"
    assert bad_timestamp.value.error_code == "service_log_retention.recorded_at_invalid"


def test_service_log_retention_execution_supports_execute_and_blocked_shapes() -> None:
    succeeded = build_service_log_retention_execution(
        service_id="nex-cx",
        mode="EXECUTE",
        execution_status="SUCCEEDED",
        retention_days=30,
        retention_cutoff="2026-07-06T00:00:00Z",
        checked_at="2026-08-05T00:00:00Z",
        candidate_count=3,
        deleted_count=2,
        delete_enabled=True,
        requested_by={
            "actor_type": "service",
            "actor_id": "nex-ag",
            "service_id": "nex-ag",
        },
    )
    blocked = build_service_log_retention_execution(
        service_id="nex-cx",
        mode="EXECUTE",
        execution_status="BLOCKED",
        retention_days=30,
        retention_cutoff="2026-07-06T00:00:00Z",
        checked_at="2026-08-05T00:00:00Z",
        candidate_count=3,
        blocked_reason="delete_not_enabled",
    )
    failed = build_service_log_retention_execution(
        service_id="nex-cx",
        mode="EXECUTE",
        execution_status="FAILED",
        retention_days=30,
        retention_cutoff="2026-07-06T00:00:00Z",
        checked_at="2026-08-05T00:00:00Z",
        candidate_count=3,
        error={"error_code": "retention.failed", "detail": "retention failed"},
    )

    assert succeeded["delete_enabled"] is True
    assert succeeded["deleted_count"] == 2
    assert blocked["execution_status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "delete_not_enabled"
    assert failed["error"]["error_code"] == "retention.failed"


def test_service_log_retention_execution_rejects_unsafe_or_invalid_shapes() -> None:
    base = {
        "service_id": "nex-cx",
        "retention_cutoff": "2026-07-06T00:00:00Z",
        "checked_at": "2026-08-05T00:00:00Z",
    }

    assert normalize_service_log_retention_days(1) == 7
    assert normalize_service_log_retention_days(30) == 30
    assert normalize_service_log_retention_days(9999) == 365
    assert normalize_service_log_retention_delete_limit(0) == 1
    assert normalize_service_log_retention_delete_limit(100) == 100
    assert normalize_service_log_retention_delete_limit(9999) == 500
    with pytest.raises(ServiceLogError) as bad_dry_run:
        build_service_log_retention_execution(**base, delete_enabled=True)
    with pytest.raises(ServiceLogError) as bad_execute:
        build_service_log_retention_execution(
            **base,
            mode="EXECUTE",
            execution_status="SUCCEEDED",
        )
    with pytest.raises(ServiceLogError) as bad_deleted_count:
        build_service_log_retention_execution(
            **base,
            candidate_count=1,
            deleted_count=2,
            delete_enabled=False,
        )
    with pytest.raises(ServiceLogError) as bad_timestamp:
        build_service_log_retention_execution(
            service_id="nex-cx",
            retention_cutoff="not-a-time",
            checked_at="2026-08-05T00:00:00Z",
        )
    with pytest.raises(ServiceLogError) as bad_requested_by:
        build_service_log_retention_execution(
            **base,
            requested_by={"actor_type": "service", "actor_id": "ag", "service_id": "bad"},
        )
    with pytest.raises(ServiceLogError) as bad_error:
        build_service_log_retention_execution(
            **base,
            error={"error_code": "retention.failed"},
        )
    invalid = build_service_log_retention_execution(**base)
    invalid["audit"]["emitted"] = "no"
    with pytest.raises(ServiceLogError) as bad_audit:
        validate_service_log_retention_execution(invalid)
    with pytest.raises(ServiceLogError) as bad_object:
        validate_service_log_retention_execution(["not", "object"])  # type: ignore[arg-type]
    naive_timestamp = build_service_log_retention_execution(
        service_id="nex-cx",
        retention_cutoff="2026-07-06T00:00:00",
        checked_at="2026-08-05T00:00:00",
    )

    assert bad_dry_run.value.error_code == (
        "service_log_retention.dry_run_delete_enabled_invalid"
    )
    assert bad_execute.value.error_code == "service_log_retention.execute_not_enabled"
    assert bad_deleted_count.value.error_code == (
        "service_log_retention.deleted_count_invalid"
    )
    assert bad_timestamp.value.error_code == (
        "service_log_retention.retention_cutoff_invalid"
    )
    assert bad_requested_by.value.error_code == (
        "service_log_retention.requested_by_service_invalid"
    )
    assert bad_error.value.error_code == "service_log.field_invalid"
    assert bad_audit.value.error_code == "service_log_retention.audit_emitted_invalid"
    assert bad_object.value.error_code == "service_log_retention.invalid"
    assert naive_timestamp["retention_cutoff"] == "2026-07-06T00:00:00Z"
    assert naive_timestamp["checked_at"] == "2026-08-05T00:00:00Z"


def test_validate_service_log_retention_execution_rejects_contract_edges() -> None:
    valid = build_service_log_retention_execution(
        service_id="nex-cx",
        retention_cutoff="2026-07-06T00:00:00Z",
        checked_at="2026-08-05T00:00:00Z",
    )

    def assert_invalid(
        field_name: str,
        value: object,
        error_code: str,
    ) -> None:
        payload = json.loads(json.dumps(valid))
        if "." in field_name:
            first, second = field_name.split(".", 1)
            payload[first][second] = value
        else:
            payload[field_name] = value
        with pytest.raises(ServiceLogError) as exc_info:
            validate_service_log_retention_execution(payload)
        assert exc_info.value.error_code == error_code

    missing = json.loads(json.dumps(valid))
    missing.pop("service_id")
    with pytest.raises(ServiceLogError) as missing_exc:
        validate_service_log_retention_execution(missing)

    assert missing_exc.value.error_code == "service_log_retention.invalid"
    assert_invalid(
        "retention_execution_schema_version",
        "other",
        "service_log_retention.schema_version_invalid",
    )
    assert_invalid("policy_id", "other", "service_log_retention.policy_id_invalid")
    assert_invalid("service_id", "bad", "service_log_retention.service_id_invalid")
    assert_invalid("mode", "DELETE", "service_log_retention.mode_invalid")
    assert_invalid("execution_status", "DONE", "service_log_retention.status_invalid")
    assert_invalid(
        "delete_enabled",
        "yes",
        "service_log_retention.delete_enabled_invalid",
    )
    assert_invalid(
        "candidate_count",
        -1,
        "service_log_retention.candidate_count_invalid",
    )
    assert_invalid("trace_id", "bad", "service_log_retention.trace_id_invalid")
    assert_invalid(
        "requested_by",
        ["bad"],
        "service_log_retention.requested_by_invalid",
    )
    assert_invalid("error", "bad", "service_log_retention.error_invalid")
    assert_invalid("audit", "bad", "service_log_retention.audit_invalid")
    assert_invalid(
        "audit.audit_event_type",
        "other",
        "service_log_retention.audit_event_type_invalid",
    )


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


def test_service_log_emit_result_summarizes_success_and_failure_with_copies() -> None:
    source_log = sample_log(log_id="summary-log-001")
    success = ServiceLogEmitResult.emitted(source_log)
    failure = ServiceLogEmitResult.failed(
        error_code="service_log.store_unavailable",
        detail="service log store is unavailable",
        status_code=503,
    )

    assert success.to_summary() == {
        "ok": True,
        "log_id": "summary-log-001",
        "service_id": "nex-cx",
        "severity": "INFO",
        "logger_name": "nex_cx.processing",
    }
    assert failure.to_summary() == {
        "ok": False,
        "error_code": "service_log.store_unavailable",
        "detail": "service log store is unavailable",
        "status_code": 503,
    }

    source_log["severity"] = "CRITICAL"
    assert success.entry is not None
    assert success.entry["severity"] == "INFO"


def test_service_log_emitter_emits_service_scoped_redacted_logs() -> None:
    store = InMemoryServiceLogStore()
    emitter = ServiceLogEmitter(
        service_id="nex-cx",
        logger_name="nex_cx.processing.worker",
        store=store,
        default_attributes={"component": "worker", "provider": {"mode": "mock"}},
    )

    entry = emitter.emit(
        severity="info",
        message="Document processing worker claimed a job.",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        job_id="job-001",
        subject_ref={"type": "cx.document", "id": "doc-001"},
        attributes={"attempt_count": 1, "provider": {"api_key": "private", "mode": "live"}},
        observed_at=NOW,
        log_id="emitted-log-001",
    )

    assert entry["service_id"] == "nex-cx"
    assert entry["severity"] == "INFO"
    assert entry["attributes"]["component"] == "worker"
    assert entry["attributes"]["provider"]["mode"] == "live"
    assert entry["attributes"]["provider"]["api_key"] == REDACTED_LOG_VALUE
    assert entry["redacted_attribute_keys"] == ["provider.api_key"]
    assert store.get_log("emitted-log-001") == entry


def test_service_log_emitter_safe_emit_returns_success_result() -> None:
    store = InMemoryServiceLogStore()
    emitter = ServiceLogEmitter(
        service_id="nex-cx",
        logger_name="nex_cx.processing.worker",
        store=store,
    )

    result = emitter.safe_emit(
        severity="warning",
        message="Document processing worker retried a job.",
        attributes={"source_text": "private document text", "retry_count": 1},
        observed_at=NOW,
        log_id="safe-log-001",
    )

    assert result.ok is True
    assert result.error_code is None
    assert result.entry is not None
    assert "source_text" not in result.entry["attributes"]
    assert "private document text" not in str(result)
    assert store.get_log("safe-log-001") == result.entry


def test_service_log_emitter_safe_emit_reports_validation_failure_without_storing() -> None:
    store = InMemoryServiceLogStore()
    emitter = ServiceLogEmitter(
        service_id="nex-cx",
        logger_name="nex_cx.processing.worker",
        store=store,
    )

    result = emitter.safe_emit(
        severity="notice",
        message="Document processing worker claimed a job.",
        observed_at=NOW,
        log_id="invalid-log-001",
    )

    assert result.ok is False
    assert result.error_code == "service_log.severity_invalid"
    assert result.status_code == 422
    assert store.get_log("invalid-log-001") is None


def test_service_log_emitter_safe_emit_reports_store_failures() -> None:
    class BrokenStore:
        def append(self, entry: dict[str, Any]) -> dict[str, Any]:
            raise ServiceLogError(
                error_code="service_log.store_unavailable",
                detail="service log store is unavailable",
                status_code=503,
            )

        def get_log(self, log_id: str) -> dict[str, Any] | None:
            return None

        def list_logs(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

    emitter = ServiceLogEmitter(
        service_id="nex-cx",
        logger_name="nex_cx.processing.worker",
        store=BrokenStore(),
    )

    result = emitter.safe_emit(
        severity="info",
        message="Document processing worker claimed a job.",
        observed_at=NOW,
        log_id="broken-log-001",
    )

    assert result.to_summary() == {
        "ok": False,
        "error_code": "service_log.store_unavailable",
        "detail": "service log store is unavailable",
        "status_code": 503,
    }


def test_service_log_emitter_safe_emit_hides_unexpected_exception_detail() -> None:
    class ExplodingStore:
        def append(self, entry: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("connection failed with secret-token")

        def get_log(self, log_id: str) -> dict[str, Any] | None:
            return None

        def list_logs(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

    emitter = ServiceLogEmitter(
        service_id="nex-cx",
        logger_name="nex_cx.processing.worker",
        store=ExplodingStore(),
    )

    result = emitter.safe_emit(
        severity="info",
        message="Document processing worker claimed a job.",
        observed_at=NOW,
        log_id="exploding-log-001",
    )

    assert result.ok is False
    assert result.error_code == "service_log.emit_failed"
    assert result.detail == "service log emission failed"
    assert "secret-token" not in str(result.to_summary())


def test_service_log_emitter_rejects_invalid_default_and_call_attributes() -> None:
    with pytest.raises(ServiceLogError) as default_exc:
        ServiceLogEmitter(
            service_id="nex-cx",
            logger_name="nex_cx.processing.worker",
            store=InMemoryServiceLogStore(),
            default_attributes=["bad"],  # type: ignore[arg-type]
        )

    emitter = ServiceLogEmitter(
        service_id="nex-cx",
        logger_name="nex_cx.processing.worker",
        store=InMemoryServiceLogStore(),
    )
    result = emitter.safe_emit(
        severity="info",
        message="Document processing worker claimed a job.",
        attributes=["bad"],  # type: ignore[arg-type]
        observed_at=NOW,
        log_id="bad-attributes-log-001",
    )

    assert default_exc.value.error_code == "service_log.attributes_invalid"
    assert result.ok is False
    assert result.error_code == "service_log.attributes_invalid"


def test_service_log_emitter_from_app_uses_persistence_store_and_explicit_override() -> None:
    persistence_store = InMemoryServiceLogStore()
    explicit_store = InMemoryServiceLogStore()
    app = SimpleNamespace(
        state=SimpleNamespace(nex_persistence=SimpleNamespace(service_log_store=persistence_store))
    )

    persisted_emitter = service_log_emitter_from_app(
        app,
        service_id="nex-cx",
        logger_name="nex_cx.processing.worker",
    )
    override_emitter = service_log_emitter_from_app(
        app,
        service_id="nex-cx",
        logger_name="nex_cx.processing.worker",
        store=explicit_store,
    )

    persisted_emitter.emit(
        severity="info",
        message="Document processing worker claimed a job.",
        observed_at=NOW,
        log_id="persisted-log-001",
    )
    override_emitter.emit(
        severity="info",
        message="Document processing worker claimed a job.",
        observed_at=NOW,
        log_id="override-log-001",
    )

    assert persistence_store.get_log("persisted-log-001") is not None
    assert persistence_store.get_log("override-log-001") is None
    assert explicit_store.get_log("override-log-001") is not None


def test_service_log_emitter_from_app_keeps_memory_fallback_on_state() -> None:
    app = SimpleNamespace(state=SimpleNamespace())
    first = service_log_emitter_from_app(
        app,
        service_id="nex-cx",
        logger_name="nex_cx.processing.worker",
    )
    second = service_log_emitter_from_app(
        app,
        service_id="nex-cx",
        logger_name="nex_cx.processing.worker",
    )

    first.emit(
        severity="info",
        message="Document processing worker claimed a job.",
        observed_at=NOW,
        log_id="fallback-log-001",
    )

    assert second.store.get_log("fallback-log-001") is not None


def test_service_log_emitter_from_app_without_state_uses_private_memory_store() -> None:
    emitter = service_log_emitter_from_app(
        SimpleNamespace(),
        service_id="nex-cx",
        logger_name="nex_cx.processing.worker",
    )

    entry = emitter.emit(
        severity="info",
        message="Document processing worker claimed a job.",
        observed_at=NOW,
        log_id="stateless-log-001",
    )

    assert emitter.store.get_log("stateless-log-001") == entry


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


def test_in_memory_service_log_store_purges_retention_candidates_with_guardrails() -> None:
    store = InMemoryServiceLogStore()
    for log_id, observed_at in (
        ("log-old-001", "2026-06-01T00:00:00Z"),
        ("log-old-002", "2026-06-02T00:00:00Z"),
        ("log-fresh", "2026-08-04T00:00:00Z"),
        ("log-mo-old", "2026-06-01T00:00:00Z"),
    ):
        store.append(
            sample_log(
                log_id=log_id,
                service_id="nex-mo" if log_id == "log-mo-old" else "nex-cx",
                observed_at=observed_at,
            )
        )

    dry_run = store.purge_retention_candidates(
        service_id="nex-cx",
        retention_cutoff="2026-07-06T00:00:00Z",
        checked_at="2026-08-05T00:00:00Z",
        dry_run=True,
        max_delete_count=1,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )
    blocked = store.purge_retention_candidates(
        service_id="nex-cx",
        retention_cutoff="2026-07-06T00:00:00Z",
        checked_at="2026-08-05T00:00:00Z",
        dry_run=False,
    )
    executed = store.purge_retention_candidates(
        service_id="nex-cx",
        retention_cutoff="2026-07-06T00:00:00Z",
        checked_at="2026-08-05T00:00:00Z",
        dry_run=False,
        delete_enabled=True,
        max_delete_count=1,
        idempotency_key="execute-once",
    )

    assert dry_run["mode"] == "DRY_RUN"
    assert dry_run["execution_status"] == "SUCCEEDED"
    assert dry_run["candidate_count"] == 2
    assert dry_run["deleted_count"] == 0
    assert dry_run["trace_id"] == TRACE_ID
    assert blocked["execution_status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "delete_not_enabled"
    assert executed["execution_status"] == "SUCCEEDED"
    assert executed["delete_enabled"] is True
    assert executed["candidate_count"] == 2
    assert executed["deleted_count"] == 1
    assert store.get_log("log-old-001") is None
    assert store.get_log("log-old-002") is not None
    assert store.get_log("log-fresh") is not None
    assert store.get_log("log-mo-old") is not None


def test_in_memory_service_log_store_rejects_bad_retention_purge_inputs() -> None:
    store = InMemoryServiceLogStore()

    with pytest.raises(ServiceLogError) as bad_service:
        store.purge_retention_candidates(
            service_id="bad",
            retention_cutoff="2026-07-06T00:00:00Z",
        )
    with pytest.raises(ServiceLogError) as bad_cutoff:
        store.purge_retention_candidates(
            service_id="nex-cx",
            retention_cutoff="not-a-time",
        )

    assert bad_service.value.error_code == "service_log_retention.service_id_invalid"
    assert bad_cutoff.value.error_code == (
        "service_log_retention.retention_cutoff_invalid"
    )


def test_service_log_retention_route_requires_claim_and_runs_dry_run() -> None:
    store = InMemoryServiceLogStore()
    store.append(
        sample_log(log_id="log-old", observed_at="2026-06-01T00:00:00Z")
    )
    store.append(
        sample_log(log_id="log-fresh", observed_at="2026-08-04T00:00:00Z")
    )
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_service_log_retention_routes(app, service_id="nex-cx", store=store)
    client = TestClient(app)

    missing_auth = client.post(
        "/internal/v1/service-logs/retention/purge",
        json={"retention_cutoff": "2026-07-06T00:00:00Z"},
    )
    wrong_audience = client.post(
        "/internal/v1/service-logs/retention/purge",
        json={"retention_cutoff": "2026-07-06T00:00:00Z"},
        headers=auth_headers(audience="nex-mo"),
    )
    response = client.post(
        "/internal/v1/service-logs/retention/purge",
        json={
            "retention_cutoff": "2026-07-06T00:00:00Z",
            "checked_at": "2026-08-05T00:00:00Z",
            "retention_days": 30,
            "max_delete_count": 10,
            "idempotency_key": "dry-run-001",
        },
        headers={
            **auth_headers(),
            "X-Request-ID": REQUEST_ID,
            "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert wrong_audience.status_code == 401
    assert wrong_audience.json()["error_code"] == "TOKEN_AUDIENCE_INVALID"
    assert response.status_code == 200
    payload = response.json()
    assert payload["retention_execution_schema_version"] == (
        SERVICE_LOG_RETENTION_EXECUTION_SCHEMA_VERSION
    )
    assert payload["mode"] == "DRY_RUN"
    assert payload["execution_status"] == "SUCCEEDED"
    assert payload["candidate_count"] == 1
    assert payload["deleted_count"] == 0
    assert payload["request_id"] == REQUEST_ID
    assert payload["trace_id"] == TRACE_ID
    assert store.get_log("log-old") is not None


def test_service_log_retention_route_blocks_or_executes_with_explicit_enable() -> None:
    store = InMemoryServiceLogStore()
    for log_id, observed_at in (
        ("log-old-001", "2026-06-01T00:00:00Z"),
        ("log-old-002", "2026-06-02T00:00:00Z"),
    ):
        store.append(sample_log(log_id=log_id, observed_at=observed_at))
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_service_log_retention_routes(app, service_id="nex-cx", store=store)
    client = TestClient(app)
    base_payload = {
        "retention_cutoff": "2026-07-06T00:00:00Z",
        "checked_at": "2026-08-05T00:00:00Z",
        "dry_run": False,
        "max_delete_count": 1,
        "requested_by": {
            "actor_type": "service",
            "actor_id": "nex-ag",
            "service_id": "nex-ag",
        },
    }

    blocked = client.post(
        "/internal/v1/service-logs/retention/purge",
        json=base_payload,
        headers=auth_headers(),
    )
    executed = client.post(
        "/internal/v1/service-logs/retention/purge",
        json={**base_payload, "delete_enabled": True},
        headers=auth_headers(),
    )
    invalid = client.post(
        "/internal/v1/service-logs/retention/purge",
        json={
            "retention_cutoff": "2026-07-06T00:00:00Z",
            "dry_run": True,
            "delete_enabled": True,
        },
        headers=auth_headers(),
    )

    assert blocked.status_code == 200
    assert blocked.json()["execution_status"] == "BLOCKED"
    assert blocked.json()["blocked_reason"] == "delete_not_enabled"
    assert executed.status_code == 200
    assert executed.json()["mode"] == "EXECUTE"
    assert executed.json()["execution_status"] == "SUCCEEDED"
    assert executed.json()["deleted_count"] == 1
    assert store.get_log("log-old-001") is None
    assert store.get_log("log-old-002") is not None
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "service_log_retention.delete_enabled_invalid"


def test_service_log_retention_route_reports_store_unavailable() -> None:
    class BrokenRetentionStore:
        def append(self, entry):
            raise AssertionError("not used")

        def get_log(self, log_id):
            raise AssertionError("not used")

        def list_logs(self, **kwargs):
            raise AssertionError("not used")

        def purge_retention_candidates(self, **kwargs):
            raise ServiceLogError(
                error_code="service_log.store_unavailable",
                detail="service log store is unavailable",
                status_code=503,
            )

    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_service_log_retention_routes(
        app,
        service_id="nex-cx",
        store=BrokenRetentionStore(),  # type: ignore[arg-type]
    )

    response = TestClient(app).post(
        "/internal/v1/service-logs/retention/purge",
        json={"retention_cutoff": "2026-07-06T00:00:00Z"},
        headers=auth_headers(),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "service_log.store_unavailable"
    assert response.json()["retryable"] is True


def test_service_log_retention_route_payload_helpers_reject_edges() -> None:
    assert runtime_logs._retention_payload_object(None) == {}

    with pytest.raises(ServiceLogError) as bad_shape:
        runtime_logs._retention_payload_object(["not", "object"])
    with pytest.raises(ServiceLogError) as missing_required:
        runtime_logs._retention_payload_required_string({}, "retention_cutoff")
    with pytest.raises(ServiceLogError) as bad_string:
        runtime_logs._retention_payload_optional_string({"checked_at": ""}, "checked_at")
    with pytest.raises(ServiceLogError) as bad_bool:
        runtime_logs._retention_payload_bool({"dry_run": "yes"}, "dry_run", default=True)
    with pytest.raises(ServiceLogError) as bad_int:
        runtime_logs._retention_payload_int(
            {"retention_days": "30"},
            "retention_days",
            default=30,
        )
    with pytest.raises(ServiceLogError) as bad_object:
        runtime_logs._retention_payload_optional_object(
            {"requested_by": "nex-ag"},
            "requested_by",
        )

    assert bad_shape.value.error_code == "service_log_retention.payload_invalid"
    assert missing_required.value.detail == "retention_cutoff must be a non-empty string."
    assert bad_string.value.detail == "checked_at must be a non-empty string."
    assert bad_bool.value.detail == "dry_run must be a boolean."
    assert bad_int.value.detail == "retention_days must be an integer."
    assert bad_object.value.detail == "requested_by must be an object."


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


def test_sqlalchemy_service_log_store_purges_retention_candidates_with_guardrails() -> None:
    store = sqlite_log_store()
    for log_id, observed_at in (
        ("sql-log-old-001", "2026-06-01T00:00:00Z"),
        ("sql-log-old-002", "2026-06-02T00:00:00Z"),
        ("sql-log-fresh", "2026-08-04T00:00:00Z"),
        ("sql-log-mo-old", "2026-06-01T00:00:00Z"),
    ):
        store.append(
            sample_log(
                log_id=log_id,
                service_id="nex-mo" if log_id == "sql-log-mo-old" else "nex-cx",
                observed_at=observed_at,
            )
        )

    dry_run = store.purge_retention_candidates(
        service_id="nex-cx",
        retention_cutoff="2026-07-06T00:00:00Z",
        checked_at="2026-08-05T00:00:00Z",
        dry_run=True,
        max_delete_count=1,
    )
    blocked = store.purge_retention_candidates(
        service_id="nex-cx",
        retention_cutoff="2026-07-06T00:00:00Z",
        checked_at="2026-08-05T00:00:00Z",
        dry_run=False,
    )
    executed = store.purge_retention_candidates(
        service_id="nex-cx",
        retention_cutoff="2026-07-06T00:00:00Z",
        checked_at="2026-08-05T00:00:00Z",
        dry_run=False,
        delete_enabled=True,
        max_delete_count=1,
    )

    assert dry_run["candidate_count"] == 2
    assert dry_run["deleted_count"] == 0
    assert blocked["execution_status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "delete_not_enabled"
    assert executed["execution_status"] == "SUCCEEDED"
    assert executed["candidate_count"] == 2
    assert executed["deleted_count"] == 1
    assert store.get_log("sql-log-old-001") is None
    assert store.get_log("sql-log-old-002") is not None
    assert store.get_log("sql-log-fresh") is not None
    assert store.get_log("sql-log-mo-old") is not None


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

        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

    store = SqlAlchemyServiceLogStore(lambda: FailingSession())  # type: ignore[arg-type]

    with pytest.raises(ServiceLogError) as exc_info:
        store.get_log("log-001")

    with pytest.raises(ServiceLogError) as list_exc:
        store.list_logs()
    with pytest.raises(ServiceLogError) as purge_exc:
        store.purge_retention_candidates(
            service_id="nex-cx",
            retention_cutoff="2026-07-06T00:00:00Z",
        )

    assert exc_info.value.error_code == "service_log.store_unavailable"
    assert list_exc.value.error_code == "service_log.store_unavailable"
    assert purge_exc.value.error_code == "service_log.store_unavailable"


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
