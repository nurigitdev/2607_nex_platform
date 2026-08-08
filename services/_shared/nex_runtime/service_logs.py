from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5


SERVICE_LOG_SCHEMA_VERSION = "service_log_entry.v1"
SERVICE_LOG_SEVERITIES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
SERVICE_IDS = ("nex-oa", "nex-ag", "nex-ae-api", "nex-cx", "nex-mo")
MAX_SERVICE_LOG_MESSAGE_LENGTH = 512
MAX_SERVICE_LOGGER_NAME_LENGTH = 160
REDACTED_LOG_VALUE = "<redacted>"

SENSITIVE_LOG_ATTRIBUTE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "passwd",
    "raw_prompt",
    "raw_user_message",
    "secret",
    "source_text",
    "token",
)


@dataclass(frozen=True)
class ServiceLogError(Exception):
    error_code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:
        return self.detail


def build_service_log_entry(
    *,
    service_id: str,
    severity: str,
    logger_name: str,
    message: str,
    trace_id: str | None = None,
    request_id: str | None = None,
    job_id: str | None = None,
    subject_ref: dict[str, str] | None = None,
    attributes: dict[str, Any] | None = None,
    observed_at: str | None = None,
    log_id: str | None = None,
) -> dict[str, Any]:
    observed = observed_at or _utc_now()
    normalized_severity = severity.upper()
    redaction = redact_service_log_attributes(attributes)
    entry = {
        "service_log_schema_version": SERVICE_LOG_SCHEMA_VERSION,
        "log_id": log_id
        or _service_log_id(
            service_id=service_id,
            severity=normalized_severity,
            logger_name=logger_name,
            message=message,
            trace_id=trace_id,
            request_id=request_id,
            job_id=job_id,
            subject_ref=subject_ref,
            observed_at=observed,
        ),
        "service_id": service_id,
        "severity": normalized_severity,
        "logger_name": logger_name,
        "message": message,
        "trace_id": trace_id,
        "request_id": request_id,
        "job_id": job_id,
        "subject_ref": deepcopy(subject_ref) if subject_ref is not None else None,
        "attributes": redaction["attributes"],
        "redacted_attribute_keys": redaction["redacted_attribute_keys"],
        "observed_at": observed,
    }
    return validate_service_log_entry(entry)


def validate_service_log_entry(entry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ServiceLogError(
            error_code="service_log.invalid",
            detail="service log entry must be an object",
        )
    for field_name in (
        "service_log_schema_version",
        "log_id",
        "service_id",
        "severity",
        "logger_name",
        "message",
        "trace_id",
        "request_id",
        "job_id",
        "subject_ref",
        "attributes",
        "redacted_attribute_keys",
        "observed_at",
    ):
        if field_name not in entry:
            raise ServiceLogError(
                error_code="service_log.invalid",
                detail=f"missing service log field: {field_name}",
            )
    if entry["service_log_schema_version"] != SERVICE_LOG_SCHEMA_VERSION:
        raise ServiceLogError(
            error_code="service_log.schema_version_invalid",
            detail="service_log_schema_version must be service_log_entry.v1",
        )
    for field_name in ("log_id", "service_id", "logger_name", "message", "observed_at"):
        _required_string(entry[field_name], field_name)
    if entry["service_id"] not in SERVICE_IDS:
        raise ServiceLogError(
            error_code="service_log.service_id_invalid",
            detail=f"unsupported service id: {entry['service_id']}",
        )
    if entry["severity"] not in SERVICE_LOG_SEVERITIES:
        raise ServiceLogError(
            error_code="service_log.severity_invalid",
            detail=f"unsupported service log severity: {entry['severity']}",
        )
    if len(entry["logger_name"]) > MAX_SERVICE_LOGGER_NAME_LENGTH:
        raise ServiceLogError(
            error_code="service_log.logger_name_too_long",
            detail=f"logger_name must be {MAX_SERVICE_LOGGER_NAME_LENGTH} characters or fewer",
        )
    if len(entry["message"]) > MAX_SERVICE_LOG_MESSAGE_LENGTH:
        raise ServiceLogError(
            error_code="service_log.message_too_long",
            detail=f"message must be {MAX_SERVICE_LOG_MESSAGE_LENGTH} characters or fewer",
        )
    if entry["trace_id"] is not None and not _is_trace_id(entry["trace_id"]):
        raise ServiceLogError(
            error_code="service_log.trace_id_invalid",
            detail="trace_id must be 32 lowercase hex characters",
        )
    for field_name in ("request_id", "job_id"):
        if entry[field_name] is not None:
            _required_string(entry[field_name], field_name)
    subject_ref = entry["subject_ref"]
    if subject_ref is not None:
        if not isinstance(subject_ref, dict):
            raise ServiceLogError(
                error_code="service_log.subject_ref_invalid",
                detail="subject_ref must be an object",
            )
        _required_string(subject_ref.get("type"), "subject_ref.type")
        _required_string(subject_ref.get("id"), "subject_ref.id")
    if not isinstance(entry["attributes"], dict):
        raise ServiceLogError(
            error_code="service_log.attributes_invalid",
            detail="attributes must be an object",
        )
    sensitive_keys = [
        str(key)
        for key in entry["attributes"]
        if _is_sensitive_log_attribute_key(str(key))
    ]
    if sensitive_keys:
        raise ServiceLogError(
            error_code="service_log.attribute_key_sensitive",
            detail=f"attributes must omit sensitive keys: {', '.join(sensitive_keys)}",
        )
    if not isinstance(entry["redacted_attribute_keys"], list):
        raise ServiceLogError(
            error_code="service_log.redacted_keys_invalid",
            detail="redacted_attribute_keys must be a list",
        )
    for key in entry["redacted_attribute_keys"]:
        _required_string(key, "redacted_attribute_keys[]")
    if len(set(entry["redacted_attribute_keys"])) != len(entry["redacted_attribute_keys"]):
        raise ServiceLogError(
            error_code="service_log.redacted_keys_duplicate",
            detail="redacted_attribute_keys must be unique",
        )
    return entry


def redact_service_log_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    if attributes is None:
        return {"attributes": {}, "redacted_attribute_keys": []}
    if not isinstance(attributes, dict):
        raise ServiceLogError(
            error_code="service_log.attributes_invalid",
            detail="attributes must be an object",
        )
    redacted_keys: list[str] = []
    safe_attributes: dict[str, Any] = {}
    for key, value in attributes.items():
        key_text = str(key)
        if _is_sensitive_log_attribute_key(key_text):
            redacted_keys.append(key_text)
            continue
        safe_attributes[key_text] = _redact_nested_log_attribute(
            value,
            redacted_keys=redacted_keys,
            path=key_text,
        )
    return {
        "attributes": safe_attributes,
        "redacted_attribute_keys": sorted(set(redacted_keys)),
    }


def summarize_service_logs(logs: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {severity: 0 for severity in SERVICE_LOG_SEVERITIES}
    service_counts: dict[str, int] = {}
    redacted_attribute_count = 0
    for entry in logs:
        severity = str(entry.get("severity", ""))
        if severity in counts:
            counts[severity] += 1
        service_id = str(entry.get("service_id", "unknown"))
        service_counts[service_id] = service_counts.get(service_id, 0) + 1
        redacted_attribute_count += len(entry.get("redacted_attribute_keys", []))
    return {
        "total": len(logs),
        "by_severity": counts,
        "by_service": service_counts,
        "redacted_attribute_count": redacted_attribute_count,
    }


def _redact_nested_log_attribute(
    value: Any,
    *,
    redacted_keys: list[str],
    path: str,
) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            key_path = f"{path}.{key_text}"
            if _is_sensitive_log_attribute_key(key_text):
                redacted[key_text] = REDACTED_LOG_VALUE
                redacted_keys.append(key_path)
            else:
                redacted[key_text] = _redact_nested_log_attribute(
                    item,
                    redacted_keys=redacted_keys,
                    path=key_path,
                )
        return redacted
    if isinstance(value, list):
        return [
            _redact_nested_log_attribute(
                item,
                redacted_keys=redacted_keys,
                path=f"{path}[]",
            )
            for item in value
        ]
    return deepcopy(value)


def _service_log_id(
    *,
    service_id: str,
    severity: str,
    logger_name: str,
    message: str,
    trace_id: str | None,
    request_id: str | None,
    job_id: str | None,
    subject_ref: dict[str, str] | None,
    observed_at: str,
) -> str:
    subject_type = subject_ref.get("type") if isinstance(subject_ref, dict) else ""
    subject_id = subject_ref.get("id") if isinstance(subject_ref, dict) else ""
    return str(
        uuid5(
            NAMESPACE_URL,
            "|".join(
                [
                    SERVICE_LOG_SCHEMA_VERSION,
                    service_id,
                    severity,
                    logger_name,
                    message,
                    trace_id or "",
                    request_id or "",
                    job_id or "",
                    str(subject_type),
                    str(subject_id),
                    observed_at,
                ]
            ),
        )
    )


def _is_trace_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 32
        and all(character in "0123456789abcdef" for character in value)
    )


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ServiceLogError(
            error_code="service_log.field_invalid",
            detail=f"{field_name} must be a non-empty string",
        )
    return value


def _is_sensitive_log_attribute_key(key: str) -> bool:
    normalized_key = key.lower()
    return any(part in normalized_key for part in SENSITIVE_LOG_ATTRIBUTE_KEY_PARTS)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
