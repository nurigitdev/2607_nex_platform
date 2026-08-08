from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from nex_runtime import (
    SERVICE_LOG_SCHEMA_VERSION,
    SERVICE_LOG_SEVERITIES,
    REDACTED_LOG_VALUE,
    ServiceLogError,
    build_service_log_entry,
    redact_service_log_attributes,
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
    assert summary["total"] == 3
    assert summary["by_severity"]["INFO"] == 1
    assert summary["by_severity"]["ERROR"] == 1
    assert summary["by_service"]["nex-cx"] == 1
    assert summary["by_service"]["unknown"] == 1
    assert summary["redacted_attribute_count"] == 2
