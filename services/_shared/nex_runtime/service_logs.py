from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Protocol
from uuid import NAMESPACE_URL, uuid5

from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .auth import DEFAULT_SERVICE_SCOPE, validate_authorization_header
from .problem import problem_response, request_id_from_headers, trace_id_from_headers


SERVICE_LOG_SCHEMA_VERSION = "service_log_entry.v1"
SERVICE_LOG_SEVERITIES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
SERVICE_IDS = ("nex-oa", "nex-ag", "nex-ae-api", "nex-cx", "nex-mo")
DEFAULT_SERVICE_LOG_LIMIT = 50
MAX_SERVICE_LOG_LIMIT = 500
MAX_SERVICE_LOG_MESSAGE_LENGTH = 512
MAX_SERVICE_LOGGER_NAME_LENGTH = 160
REDACTED_LOG_VALUE = "<redacted>"
SERVICE_LOG_RETENTION_EXECUTION_SCHEMA_VERSION = "service_log_retention_execution.v1"
SERVICE_LOG_RETENTION_EXECUTION_MODES = ("DRY_RUN", "EXECUTE")
SERVICE_LOG_RETENTION_EXECUTION_STATUSES = (
    "PLANNED",
    "SUCCEEDED",
    "BLOCKED",
    "FAILED",
)
SERVICE_LOG_RETENTION_POLICY_ID = "service-log-query-retention-v1"
DEFAULT_SERVICE_LOG_RETENTION_DAYS = 30
MIN_SERVICE_LOG_RETENTION_DAYS = 7
MAX_SERVICE_LOG_RETENTION_DAYS = 365
DEFAULT_SERVICE_LOG_RETENTION_MAX_DELETE_COUNT = 100
MAX_SERVICE_LOG_RETENTION_MAX_DELETE_COUNT = 500

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


class ServiceLogStore(Protocol):
    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_log(self, log_id: str) -> dict[str, Any] | None:
        ...

    def list_logs(
        self,
        *,
        service_id: str | None = None,
        severity: str | None = None,
        logger_name: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        limit: int = DEFAULT_SERVICE_LOG_LIMIT,
    ) -> list[dict[str, Any]]:
        ...

    def purge_retention_candidates(
        self,
        *,
        service_id: str,
        retention_cutoff: str,
        retention_days: int = DEFAULT_SERVICE_LOG_RETENTION_DAYS,
        checked_at: str | None = None,
        dry_run: bool = True,
        delete_enabled: bool = False,
        max_delete_count: int = DEFAULT_SERVICE_LOG_RETENTION_MAX_DELETE_COUNT,
        requested_by: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ServiceLogEmitResult:
    ok: bool
    entry: dict[str, Any] | None = None
    error_code: str | None = None
    detail: str | None = None
    status_code: int | None = None

    @classmethod
    def emitted(cls, entry: dict[str, Any]) -> ServiceLogEmitResult:
        return cls(ok=True, entry=deepcopy(entry))

    @classmethod
    def failed(
        cls,
        *,
        error_code: str,
        detail: str,
        status_code: int,
    ) -> ServiceLogEmitResult:
        return cls(
            ok=False,
            error_code=error_code,
            detail=detail,
            status_code=status_code,
        )

    def to_summary(self) -> dict[str, Any]:
        if self.ok and self.entry is not None:
            return {
                "ok": True,
                "log_id": self.entry["log_id"],
                "service_id": self.entry["service_id"],
                "severity": self.entry["severity"],
                "logger_name": self.entry["logger_name"],
            }
        return {
            "ok": False,
            "error_code": self.error_code,
            "detail": self.detail,
            "status_code": self.status_code,
        }


class ServiceLogEmitter:
    def __init__(
        self,
        *,
        service_id: str,
        logger_name: str,
        store: ServiceLogStore,
        default_attributes: dict[str, Any] | None = None,
    ) -> None:
        self.service_id = _required_string(service_id, "service_id")
        self.logger_name = _required_string(logger_name, "logger_name")
        self.store = store
        if default_attributes is not None and not isinstance(default_attributes, dict):
            raise ServiceLogError(
                error_code="service_log.attributes_invalid",
                detail="default_attributes must be an object",
            )
        self.default_attributes = deepcopy(default_attributes) if default_attributes else {}

    def emit(
        self,
        *,
        severity: str,
        message: str,
        trace_id: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        subject_ref: dict[str, str] | None = None,
        attributes: dict[str, Any] | None = None,
        observed_at: str | None = None,
        log_id: str | None = None,
    ) -> dict[str, Any]:
        entry = build_service_log_entry(
            service_id=self.service_id,
            severity=severity,
            logger_name=self.logger_name,
            message=message,
            trace_id=trace_id,
            request_id=request_id,
            job_id=job_id,
            subject_ref=subject_ref,
            attributes=self._merged_attributes(attributes),
            observed_at=observed_at,
            log_id=log_id,
        )
        return self.store.append(entry)

    def safe_emit(
        self,
        *,
        severity: str,
        message: str,
        trace_id: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        subject_ref: dict[str, str] | None = None,
        attributes: dict[str, Any] | None = None,
        observed_at: str | None = None,
        log_id: str | None = None,
    ) -> ServiceLogEmitResult:
        try:
            return ServiceLogEmitResult.emitted(
                self.emit(
                    severity=severity,
                    message=message,
                    trace_id=trace_id,
                    request_id=request_id,
                    job_id=job_id,
                    subject_ref=subject_ref,
                    attributes=attributes,
                    observed_at=observed_at,
                    log_id=log_id,
                )
            )
        except ServiceLogError as exc:
            return ServiceLogEmitResult.failed(
                error_code=exc.error_code,
                detail=exc.detail,
                status_code=exc.status_code,
            )
        except Exception:
            return ServiceLogEmitResult.failed(
                error_code="service_log.emit_failed",
                detail="service log emission failed",
                status_code=503,
            )

    def _merged_attributes(self, attributes: dict[str, Any] | None) -> dict[str, Any]:
        if attributes is not None and not isinstance(attributes, dict):
            raise ServiceLogError(
                error_code="service_log.attributes_invalid",
                detail="attributes must be an object",
            )
        merged = deepcopy(self.default_attributes)
        if attributes:
            merged.update(deepcopy(attributes))
        return merged


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


def normalize_service_log_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > MAX_SERVICE_LOG_LIMIT:
        return MAX_SERVICE_LOG_LIMIT
    return limit


def normalize_service_log_retention_days(value: int) -> int:
    if value < MIN_SERVICE_LOG_RETENTION_DAYS:
        return MIN_SERVICE_LOG_RETENTION_DAYS
    if value > MAX_SERVICE_LOG_RETENTION_DAYS:
        return MAX_SERVICE_LOG_RETENTION_DAYS
    return value


def normalize_service_log_retention_delete_limit(value: int) -> int:
    if value < 1:
        return 1
    if value > MAX_SERVICE_LOG_RETENTION_MAX_DELETE_COUNT:
        return MAX_SERVICE_LOG_RETENTION_MAX_DELETE_COUNT
    return value


def build_service_log_retention_execution(
    *,
    service_id: str,
    retention_cutoff: str,
    mode: str = "DRY_RUN",
    execution_status: str = "PLANNED",
    retention_days: int = DEFAULT_SERVICE_LOG_RETENTION_DAYS,
    checked_at: str | None = None,
    scan_limit: int = MAX_SERVICE_LOG_LIMIT,
    max_delete_count: int = DEFAULT_SERVICE_LOG_RETENTION_MAX_DELETE_COUNT,
    candidate_count: int = 0,
    deleted_count: int = 0,
    delete_enabled: bool = False,
    requested_by: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    blocked_reason: str | None = None,
    error: dict[str, Any] | None = None,
    execution_id: str | None = None,
) -> dict[str, Any]:
    observed_checked_at = _normalize_iso_timestamp(
        checked_at or _utc_now(),
        field_name="checked_at",
    )
    normalized_execution_id = execution_id or _service_log_retention_execution_id(
        service_id=service_id,
        mode=mode,
        execution_status=execution_status,
        retention_cutoff=retention_cutoff,
        checked_at=observed_checked_at,
        idempotency_key=idempotency_key,
    )
    normalized = {
        "retention_execution_schema_version": (
            SERVICE_LOG_RETENTION_EXECUTION_SCHEMA_VERSION
        ),
        "execution_id": normalized_execution_id,
        "policy_id": SERVICE_LOG_RETENTION_POLICY_ID,
        "service_id": service_id,
        "mode": mode.upper(),
        "execution_status": execution_status.upper(),
        "delete_enabled": bool(delete_enabled),
        "retention_days": normalize_service_log_retention_days(retention_days),
        "retention_cutoff": _normalize_iso_timestamp(
            retention_cutoff,
            field_name="retention_cutoff",
        ),
        "checked_at": observed_checked_at,
        "scan_limit": normalize_service_log_limit(scan_limit),
        "max_delete_count": normalize_service_log_retention_delete_limit(
            max_delete_count
        ),
        "candidate_count": _non_negative_int(candidate_count, "candidate_count"),
        "deleted_count": _non_negative_int(deleted_count, "deleted_count"),
        "requested_by": _normalize_retention_requested_by(requested_by),
        "idempotency_key": idempotency_key,
        "trace_id": trace_id,
        "request_id": request_id,
        "blocked_reason": blocked_reason,
        "error": deepcopy(error) if error is not None else None,
        "audit": {
            "audit_event_type": "service_log.retention.execution",
            "audit_event_id": _service_log_retention_audit_id(normalized_execution_id),
            "emitted": False,
        },
    }
    return validate_service_log_retention_execution(normalized)


def validate_service_log_retention_execution(
    execution: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(execution, dict):
        raise ServiceLogError(
            error_code="service_log_retention.invalid",
            detail="service log retention execution must be an object",
        )
    for field_name in (
        "retention_execution_schema_version",
        "execution_id",
        "policy_id",
        "service_id",
        "mode",
        "execution_status",
        "delete_enabled",
        "retention_days",
        "retention_cutoff",
        "checked_at",
        "scan_limit",
        "max_delete_count",
        "candidate_count",
        "deleted_count",
        "requested_by",
        "idempotency_key",
        "trace_id",
        "request_id",
        "blocked_reason",
        "error",
        "audit",
    ):
        if field_name not in execution:
            raise ServiceLogError(
                error_code="service_log_retention.invalid",
                detail=f"missing service log retention execution field: {field_name}",
            )
    if (
        execution["retention_execution_schema_version"]
        != SERVICE_LOG_RETENTION_EXECUTION_SCHEMA_VERSION
    ):
        raise ServiceLogError(
            error_code="service_log_retention.schema_version_invalid",
            detail=(
                "retention_execution_schema_version must be "
                "service_log_retention_execution.v1"
            ),
        )
    for field_name in ("execution_id", "policy_id", "service_id"):
        _required_string(execution[field_name], field_name)
    if execution["policy_id"] != SERVICE_LOG_RETENTION_POLICY_ID:
        raise ServiceLogError(
            error_code="service_log_retention.policy_id_invalid",
            detail=f"policy_id must be {SERVICE_LOG_RETENTION_POLICY_ID}",
        )
    if execution["service_id"] not in SERVICE_IDS:
        raise ServiceLogError(
            error_code="service_log_retention.service_id_invalid",
            detail=f"unsupported service id: {execution['service_id']}",
        )
    if execution["mode"] not in SERVICE_LOG_RETENTION_EXECUTION_MODES:
        raise ServiceLogError(
            error_code="service_log_retention.mode_invalid",
            detail="mode must be DRY_RUN or EXECUTE",
        )
    if execution["execution_status"] not in SERVICE_LOG_RETENTION_EXECUTION_STATUSES:
        raise ServiceLogError(
            error_code="service_log_retention.status_invalid",
            detail="execution_status is not supported",
        )
    if not isinstance(execution["delete_enabled"], bool):
        raise ServiceLogError(
            error_code="service_log_retention.delete_enabled_invalid",
            detail="delete_enabled must be a boolean",
        )
    if execution["mode"] == "DRY_RUN" and execution["delete_enabled"]:
        raise ServiceLogError(
            error_code="service_log_retention.dry_run_delete_enabled_invalid",
            detail="dry-run retention execution cannot enable deletes",
        )
    if (
        execution["mode"] == "EXECUTE"
        and execution["execution_status"] == "SUCCEEDED"
        and not execution["delete_enabled"]
    ):
        raise ServiceLogError(
            error_code="service_log_retention.execute_not_enabled",
            detail="successful execute retention requires delete_enabled=true",
        )
    for field_name in (
        "retention_days",
        "scan_limit",
        "max_delete_count",
        "candidate_count",
        "deleted_count",
    ):
        if not isinstance(execution[field_name], int) or execution[field_name] < 0:
            raise ServiceLogError(
                error_code=f"service_log_retention.{field_name}_invalid",
                detail=f"{field_name} must be a non-negative integer",
            )
    if execution["deleted_count"] > execution["candidate_count"]:
        raise ServiceLogError(
            error_code="service_log_retention.deleted_count_invalid",
            detail="deleted_count cannot exceed candidate_count",
        )
    _normalize_iso_timestamp(execution["retention_cutoff"], field_name="retention_cutoff")
    _normalize_iso_timestamp(execution["checked_at"], field_name="checked_at")
    if execution["trace_id"] is not None and not _is_trace_id(execution["trace_id"]):
        raise ServiceLogError(
            error_code="service_log_retention.trace_id_invalid",
            detail="trace_id must be 32 lowercase hex characters",
        )
    for field_name in ("idempotency_key", "request_id", "blocked_reason"):
        value = execution[field_name]
        if value is not None:
            _required_string(value, field_name)
    _normalize_retention_requested_by(execution["requested_by"])
    _validate_retention_error(execution["error"])
    _validate_retention_audit(execution["audit"])
    return execution


@dataclass
class InMemoryServiceLogStore:
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        normalized = deepcopy(validate_service_log_entry(entry))
        log_id = str(normalized["log_id"])
        if log_id not in self.entries:
            self.entries[log_id] = normalized
        return deepcopy(self.entries[log_id])

    def get_log(self, log_id: str) -> dict[str, Any] | None:
        _required_string(log_id, "log_id")
        entry = self.entries.get(log_id)
        return deepcopy(entry) if entry is not None else None

    def list_logs(
        self,
        *,
        service_id: str | None = None,
        severity: str | None = None,
        logger_name: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        limit: int = DEFAULT_SERVICE_LOG_LIMIT,
    ) -> list[dict[str, Any]]:
        normalized_limit = normalize_service_log_limit(limit)
        normalized_severity = severity.upper() if severity is not None else None
        logs = [
            deepcopy(entry)
            for entry in self.entries.values()
            if (service_id is None or entry["service_id"] == service_id)
            and (normalized_severity is None or entry["severity"] == normalized_severity)
            and (logger_name is None or entry["logger_name"] == logger_name)
            and (trace_id is None or entry.get("trace_id") == trace_id)
            and (request_id is None or entry.get("request_id") == request_id)
            and (job_id is None or entry.get("job_id") == job_id)
            and (
                subject_type is None
                or (
                    entry.get("subject_ref") is not None
                    and entry["subject_ref"].get("type") == subject_type
                )
            )
            and (
                subject_id is None
                or (
                    entry.get("subject_ref") is not None
                    and entry["subject_ref"].get("id") == subject_id
                )
            )
        ]
        logs.sort(key=lambda entry: (entry["observed_at"], entry["log_id"]), reverse=True)
        return logs[:normalized_limit]

    def summary(self) -> dict[str, Any]:
        return summarize_service_logs(self.list_logs(limit=MAX_SERVICE_LOG_LIMIT))

    def purge_retention_candidates(
        self,
        *,
        service_id: str,
        retention_cutoff: str,
        retention_days: int = DEFAULT_SERVICE_LOG_RETENTION_DAYS,
        checked_at: str | None = None,
        dry_run: bool = True,
        delete_enabled: bool = False,
        max_delete_count: int = DEFAULT_SERVICE_LOG_RETENTION_MAX_DELETE_COUNT,
        requested_by: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_retention_purge_inputs(
            service_id=service_id,
            retention_cutoff=retention_cutoff,
            checked_at=checked_at,
            max_delete_count=max_delete_count,
        )
        candidates = _retention_candidate_entries(
            self.entries.values(),
            service_id=normalized["service_id"],
            retention_cutoff=normalized["retention_cutoff"],
        )
        selected = candidates[: normalized["max_delete_count"]]
        if dry_run:
            return build_service_log_retention_execution(
                service_id=normalized["service_id"],
                mode="DRY_RUN",
                execution_status="SUCCEEDED",
                retention_days=retention_days,
                retention_cutoff=normalized["retention_cutoff"],
                checked_at=normalized["checked_at"],
                max_delete_count=normalized["max_delete_count"],
                candidate_count=len(candidates),
                deleted_count=0,
                delete_enabled=False,
                requested_by=requested_by,
                idempotency_key=idempotency_key,
                trace_id=trace_id,
                request_id=request_id,
            )
        if not delete_enabled:
            return build_service_log_retention_execution(
                service_id=normalized["service_id"],
                mode="EXECUTE",
                execution_status="BLOCKED",
                retention_days=retention_days,
                retention_cutoff=normalized["retention_cutoff"],
                checked_at=normalized["checked_at"],
                max_delete_count=normalized["max_delete_count"],
                candidate_count=len(candidates),
                deleted_count=0,
                delete_enabled=False,
                requested_by=requested_by,
                idempotency_key=idempotency_key,
                trace_id=trace_id,
                request_id=request_id,
                blocked_reason="delete_not_enabled",
            )
        for entry in selected:
            self.entries.pop(str(entry["log_id"]), None)
        return build_service_log_retention_execution(
            service_id=normalized["service_id"],
            mode="EXECUTE",
            execution_status="SUCCEEDED",
            retention_days=retention_days,
            retention_cutoff=normalized["retention_cutoff"],
            checked_at=normalized["checked_at"],
            max_delete_count=normalized["max_delete_count"],
            candidate_count=len(candidates),
            deleted_count=len(selected),
            delete_enabled=True,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            request_id=request_id,
        )


class SqlAlchemyServiceLogStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        entry_to_store = deepcopy(validate_service_log_entry(entry))
        try:
            return self._run_in_transaction(
                lambda session: self._append_log(session, entry_to_store)
            )
        except IntegrityError as exc:
            existing = self.get_log(str(entry_to_store["log_id"]))
            if existing is not None:
                return existing
            raise _service_log_store_unavailable() from exc
        except SQLAlchemyError as exc:
            raise _service_log_store_unavailable() from exc

    def get_log(self, log_id: str) -> dict[str, Any] | None:
        _required_string(log_id, "log_id")
        try:
            with self._session_factory() as session:
                return self._select_log(session, log_id)
        except SQLAlchemyError as exc:
            raise _service_log_store_unavailable() from exc

    def list_logs(
        self,
        *,
        service_id: str | None = None,
        severity: str | None = None,
        logger_name: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        limit: int = DEFAULT_SERVICE_LOG_LIMIT,
    ) -> list[dict[str, Any]]:
        normalized_limit = normalize_service_log_limit(limit)
        normalized_severity = severity.upper() if severity is not None else None
        where_clauses: list[str] = []
        params: dict[str, Any] = {"limit": normalized_limit}
        filters = {
            "service_id": service_id,
            "severity": normalized_severity,
            "logger_name": logger_name,
            "trace_id": trace_id,
            "request_id": request_id,
            "job_id": job_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
        }
        for field_name, value in filters.items():
            if value is not None:
                where_clauses.append(f"{field_name} = :{field_name}")
                params[field_name] = value
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(
                        f"""
                        SELECT {_LOG_SELECT_COLUMNS}
                        FROM service_log_entries
                        {where_sql}
                        ORDER BY observed_at DESC, log_id DESC
                        LIMIT :limit
                        """
                    ),
                    params,
                ).mappings()
                return [_log_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _service_log_store_unavailable() from exc

    def summary(self) -> dict[str, Any]:
        return summarize_service_logs(self.list_logs(limit=MAX_SERVICE_LOG_LIMIT))

    def purge_retention_candidates(
        self,
        *,
        service_id: str,
        retention_cutoff: str,
        retention_days: int = DEFAULT_SERVICE_LOG_RETENTION_DAYS,
        checked_at: str | None = None,
        dry_run: bool = True,
        delete_enabled: bool = False,
        max_delete_count: int = DEFAULT_SERVICE_LOG_RETENTION_MAX_DELETE_COUNT,
        requested_by: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_retention_purge_inputs(
            service_id=service_id,
            retention_cutoff=retention_cutoff,
            checked_at=checked_at,
            max_delete_count=max_delete_count,
        )
        try:
            return self._run_in_transaction(
                lambda session: self._purge_retention_candidates(
                    session,
                    service_id=normalized["service_id"],
                    retention_cutoff=normalized["retention_cutoff"],
                    checked_at=normalized["checked_at"],
                    retention_days=retention_days,
                    dry_run=dry_run,
                    delete_enabled=delete_enabled,
                    max_delete_count=normalized["max_delete_count"],
                    requested_by=requested_by,
                    idempotency_key=idempotency_key,
                    trace_id=trace_id,
                    request_id=request_id,
                )
            )
        except SQLAlchemyError as exc:
            raise _service_log_store_unavailable() from exc

    def _run_in_transaction(self, operation: Callable[[Session], Any]) -> Any:
        session = self._session_factory()
        try:
            try:
                result = operation(session)
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise
        finally:
            session.close()

    def _append_log(self, session: Session, entry: dict[str, Any]) -> dict[str, Any]:
        existing = self._select_log(session, str(entry["log_id"]))
        if existing is not None:
            return existing
        self._insert_log(session, entry)
        stored = self._select_log(session, str(entry["log_id"]))
        assert stored is not None
        return stored

    def _select_log(
        self,
        session: Session,
        log_id: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_LOG_SELECT_COLUMNS}
                FROM service_log_entries
                WHERE log_id = :log_id
                """
            ),
            {"log_id": log_id},
        ).mappings().first()
        return _log_from_row(row) if row is not None else None

    def _insert_log(self, session: Session, entry: dict[str, Any]) -> None:
        attributes_expression = _json_sql_expression(session, "attributes")
        redacted_keys_expression = _json_sql_expression(session, "redacted_attribute_keys")
        session.execute(
            text(
                f"""
                INSERT INTO service_log_entries (
                    log_id,
                    service_log_schema_version,
                    service_id,
                    severity,
                    logger_name,
                    message,
                    trace_id,
                    request_id,
                    job_id,
                    subject_type,
                    subject_id,
                    attributes,
                    redacted_attribute_keys,
                    observed_at
                )
                VALUES (
                    :log_id,
                    :service_log_schema_version,
                    :service_id,
                    :severity,
                    :logger_name,
                    :message,
                    :trace_id,
                    :request_id,
                    :job_id,
                    :subject_type,
                    :subject_id,
                    {attributes_expression},
                    {redacted_keys_expression},
                    :observed_at
                )
                """
            ),
            _log_insert_params(entry),
        )

    def _purge_retention_candidates(
        self,
        session: Session,
        *,
        service_id: str,
        retention_cutoff: str,
        checked_at: str,
        retention_days: int,
        dry_run: bool,
        delete_enabled: bool,
        max_delete_count: int,
        requested_by: dict[str, Any] | None,
        idempotency_key: str | None,
        trace_id: str | None,
        request_id: str | None,
    ) -> dict[str, Any]:
        candidate_count = int(
            session.execute(
                text(
                    """
                    SELECT COUNT(*) AS candidate_count
                    FROM service_log_entries
                    WHERE service_id = :service_id
                      AND observed_at < :retention_cutoff
                    """
                ),
                {
                    "service_id": service_id,
                    "retention_cutoff": retention_cutoff,
                },
            ).scalar_one()
        )
        if dry_run:
            return build_service_log_retention_execution(
                service_id=service_id,
                mode="DRY_RUN",
                execution_status="SUCCEEDED",
                retention_days=retention_days,
                retention_cutoff=retention_cutoff,
                checked_at=checked_at,
                max_delete_count=max_delete_count,
                candidate_count=candidate_count,
                deleted_count=0,
                delete_enabled=False,
                requested_by=requested_by,
                idempotency_key=idempotency_key,
                trace_id=trace_id,
                request_id=request_id,
            )
        if not delete_enabled:
            return build_service_log_retention_execution(
                service_id=service_id,
                mode="EXECUTE",
                execution_status="BLOCKED",
                retention_days=retention_days,
                retention_cutoff=retention_cutoff,
                checked_at=checked_at,
                max_delete_count=max_delete_count,
                candidate_count=candidate_count,
                deleted_count=0,
                delete_enabled=False,
                requested_by=requested_by,
                idempotency_key=idempotency_key,
                trace_id=trace_id,
                request_id=request_id,
                blocked_reason="delete_not_enabled",
            )
        rows = session.execute(
            text(
                """
                SELECT log_id
                FROM service_log_entries
                WHERE service_id = :service_id
                  AND observed_at < :retention_cutoff
                ORDER BY observed_at ASC, log_id ASC
                LIMIT :limit
                """
            ),
            {
                "service_id": service_id,
                "retention_cutoff": retention_cutoff,
                "limit": max_delete_count,
            },
        ).mappings()
        log_ids = [str(row["log_id"]) for row in rows]
        for log_id in log_ids:
            session.execute(
                text("DELETE FROM service_log_entries WHERE log_id = :log_id"),
                {"log_id": log_id},
            )
        return build_service_log_retention_execution(
            service_id=service_id,
            mode="EXECUTE",
            execution_status="SUCCEEDED",
            retention_days=retention_days,
            retention_cutoff=retention_cutoff,
            checked_at=checked_at,
            max_delete_count=max_delete_count,
            candidate_count=candidate_count,
            deleted_count=len(log_ids),
            delete_enabled=True,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            request_id=request_id,
        )


def service_log_store_from_app(app: Any) -> ServiceLogStore:
    state = getattr(app, "state", None)
    persistence = getattr(state, "nex_persistence", None) if state is not None else None
    store = getattr(persistence, "service_log_store", None)
    if store is not None:
        return store
    if state is None:
        return InMemoryServiceLogStore()
    fallback_store = getattr(state, "_nex_service_log_store", None)
    if fallback_store is None:
        fallback_store = InMemoryServiceLogStore()
        setattr(state, "_nex_service_log_store", fallback_store)
    return fallback_store


def service_log_emitter_from_app(
    app: Any,
    *,
    service_id: str,
    logger_name: str,
    store: ServiceLogStore | None = None,
    default_attributes: dict[str, Any] | None = None,
) -> ServiceLogEmitter:
    return ServiceLogEmitter(
        service_id=service_id,
        logger_name=logger_name,
        store=store if store is not None else service_log_store_from_app(app),
        default_attributes=default_attributes,
    )


def register_service_log_retention_routes(
    app: FastAPI,
    *,
    service_id: str,
    store: ServiceLogStore | None = None,
    expected_audience: str | None = None,
) -> None:
    audience = expected_audience or service_id

    @app.post("/internal/v1/service-logs/retention/purge", response_model=None)
    def purge_retention_candidates(
        request: Request,
        payload: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_service_log_retention_request(
            request,
            authorization,
            expected_audience=audience,
        )
        if auth_problem is not None:
            return auth_problem
        try:
            payload_object = _retention_payload_object(payload)
            dry_run = _retention_payload_bool(
                payload_object,
                "dry_run",
                default=True,
            )
            delete_enabled = _retention_payload_bool(
                payload_object,
                "delete_enabled",
                default=False,
            )
            if dry_run and delete_enabled:
                raise ServiceLogError(
                    error_code="service_log_retention.delete_enabled_invalid",
                    detail="delete_enabled cannot be true for dry-run retention purge.",
                    status_code=422,
                )
            target_store = store or service_log_store_from_app(request.app)
            return target_store.purge_retention_candidates(
                service_id=service_id,
                retention_cutoff=_retention_payload_required_string(
                    payload_object,
                    "retention_cutoff",
                ),
                retention_days=_retention_payload_int(
                    payload_object,
                    "retention_days",
                    default=DEFAULT_SERVICE_LOG_RETENTION_DAYS,
                ),
                checked_at=_retention_payload_optional_string(
                    payload_object,
                    "checked_at",
                ),
                dry_run=dry_run,
                delete_enabled=delete_enabled,
                max_delete_count=_retention_payload_int(
                    payload_object,
                    "max_delete_count",
                    default=DEFAULT_SERVICE_LOG_RETENTION_MAX_DELETE_COUNT,
                ),
                requested_by=_retention_payload_optional_object(
                    payload_object,
                    "requested_by",
                ),
                idempotency_key=_retention_payload_optional_string(
                    payload_object,
                    "idempotency_key",
                ),
                trace_id=trace_id_from_headers(request),
                request_id=request_id_from_headers(request),
            )
        except ServiceLogError as exc:
            return _service_log_retention_problem_response(request, exc)


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


def _service_log_retention_execution_id(
    *,
    service_id: str,
    mode: str,
    execution_status: str,
    retention_cutoff: str,
    checked_at: str,
    idempotency_key: str | None,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "|".join(
                [
                    SERVICE_LOG_RETENTION_EXECUTION_SCHEMA_VERSION,
                    service_id,
                    mode.upper(),
                    execution_status.upper(),
                    retention_cutoff,
                    checked_at,
                    idempotency_key or "",
                ]
            ),
        )
    )


def _service_log_retention_audit_id(execution_id: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "|".join(
                [
                    "service_log.retention.audit.v1",
                    execution_id,
                ]
            ),
        )
    )


def _normalize_iso_timestamp(value: object, *, field_name: str) -> str:
    text = _required_string(value, field_name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ServiceLogError(
            error_code=f"service_log_retention.{field_name}_invalid",
            detail=f"{field_name} must be an ISO-8601 timestamp",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _normalize_retention_purge_inputs(
    *,
    service_id: str,
    retention_cutoff: str,
    checked_at: str | None,
    max_delete_count: int,
) -> dict[str, Any]:
    normalized_service_id = _required_string(service_id, "service_id")
    if normalized_service_id not in SERVICE_IDS:
        raise ServiceLogError(
            error_code="service_log_retention.service_id_invalid",
            detail=f"unsupported service id: {normalized_service_id}",
        )
    return {
        "service_id": normalized_service_id,
        "retention_cutoff": _normalize_iso_timestamp(
            retention_cutoff,
            field_name="retention_cutoff",
        ),
        "checked_at": _normalize_iso_timestamp(
            checked_at or _utc_now(),
            field_name="checked_at",
        ),
        "max_delete_count": normalize_service_log_retention_delete_limit(
            max_delete_count
        ),
    }


def _retention_candidate_entries(
    entries: Any,
    *,
    service_id: str,
    retention_cutoff: str,
) -> list[dict[str, Any]]:
    cutoff_dt = _timestamp_to_datetime(retention_cutoff)
    candidates = [
        deepcopy(entry)
        for entry in entries
        if entry["service_id"] == service_id
        and _timestamp_to_datetime(entry["observed_at"]) < cutoff_dt
    ]
    candidates.sort(key=lambda entry: (entry["observed_at"], entry["log_id"]))
    return candidates


def _timestamp_to_datetime(value: object) -> datetime:
    normalized = _normalize_iso_timestamp(value, field_name="timestamp")
    return datetime.fromisoformat(normalized.replace("Z", "+00:00")).astimezone(UTC)


def _authorize_service_log_retention_request(
    request: Request,
    authorization: str | None,
    *,
    expected_audience: str,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience=expected_audience,
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None
    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or f"{expected_audience} requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _retention_payload_object(payload: object) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ServiceLogError(
            error_code="service_log_retention.payload_invalid",
            detail="retention purge payload must be an object",
            status_code=422,
        )
    return payload


def _retention_payload_required_string(payload: dict[str, Any], key: str) -> str:
    if key not in payload:
        raise ServiceLogError(
            error_code="service_log_retention.payload_invalid",
            detail=f"{key} must be a non-empty string.",
            status_code=422,
        )
    return _retention_payload_string(payload[key], key)


def _retention_payload_optional_string(
    payload: dict[str, Any],
    key: str,
) -> str | None:
    if key not in payload or payload[key] is None:
        return None
    return _retention_payload_string(payload[key], key)


def _retention_payload_string(value: object, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise ServiceLogError(
            error_code="service_log_retention.payload_invalid",
            detail=f"{key} must be a non-empty string.",
            status_code=422,
        )
    return value


def _retention_payload_bool(
    payload: dict[str, Any],
    key: str,
    *,
    default: bool,
) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ServiceLogError(
            error_code="service_log_retention.payload_invalid",
            detail=f"{key} must be a boolean.",
            status_code=422,
        )
    return value


def _retention_payload_int(
    payload: dict[str, Any],
    key: str,
    *,
    default: int,
) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int):
        raise ServiceLogError(
            error_code="service_log_retention.payload_invalid",
            detail=f"{key} must be an integer.",
            status_code=422,
        )
    return value


def _retention_payload_optional_object(
    payload: dict[str, Any],
    key: str,
) -> dict[str, Any] | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, dict):
        raise ServiceLogError(
            error_code="service_log_retention.payload_invalid",
            detail=f"{key} must be an object.",
            status_code=422,
        )
    return deepcopy(value)


def _service_log_retention_problem_response(
    request: Request,
    exc: ServiceLogError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Service log retention request failed",
        detail=exc.detail,
        retryable=exc.status_code >= 500,
        type_uri=(
            "https://nex-platform.local/problems/"
            "service-log-retention-request-failed"
        ),
    )


def _non_negative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ServiceLogError(
            error_code=f"service_log_retention.{field_name}_invalid",
            detail=f"{field_name} must be a non-negative integer",
        )
    return value


def _normalize_retention_requested_by(value: dict[str, Any] | None) -> dict[str, str]:
    requested_by = value or {
        "actor_type": "service",
        "actor_id": "nex-ag",
        "service_id": "nex-ag",
    }
    if not isinstance(requested_by, dict):
        raise ServiceLogError(
            error_code="service_log_retention.requested_by_invalid",
            detail="requested_by must be an object",
        )
    normalized = {
        "actor_type": _required_string(
            requested_by.get("actor_type"),
            "requested_by.actor_type",
        ),
        "actor_id": _required_string(
            requested_by.get("actor_id"),
            "requested_by.actor_id",
        ),
        "service_id": _required_string(
            requested_by.get("service_id"),
            "requested_by.service_id",
        ),
    }
    if normalized["service_id"] not in SERVICE_IDS:
        raise ServiceLogError(
            error_code="service_log_retention.requested_by_service_invalid",
            detail=f"unsupported requested_by service id: {normalized['service_id']}",
        )
    return normalized


def _validate_retention_error(error: object) -> None:
    if error is None:
        return
    if not isinstance(error, dict):
        raise ServiceLogError(
            error_code="service_log_retention.error_invalid",
            detail="error must be null or an object",
        )
    _required_string(error.get("error_code"), "error.error_code")
    _required_string(error.get("detail"), "error.detail")


def _validate_retention_audit(audit: object) -> None:
    if not isinstance(audit, dict):
        raise ServiceLogError(
            error_code="service_log_retention.audit_invalid",
            detail="audit must be an object",
        )
    if audit.get("audit_event_type") != "service_log.retention.execution":
        raise ServiceLogError(
            error_code="service_log_retention.audit_event_type_invalid",
            detail="audit_event_type must be service_log.retention.execution",
        )
    _required_string(audit.get("audit_event_id"), "audit.audit_event_id")
    if not isinstance(audit.get("emitted"), bool):
        raise ServiceLogError(
            error_code="service_log_retention.audit_emitted_invalid",
            detail="audit.emitted must be a boolean",
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


_LOG_SELECT_COLUMNS = """
    log_id,
    service_log_schema_version,
    service_id,
    severity,
    logger_name,
    message,
    trace_id,
    request_id,
    job_id,
    subject_type,
    subject_id,
    attributes,
    redacted_attribute_keys,
    observed_at
"""


def _log_insert_params(entry: dict[str, Any]) -> dict[str, Any]:
    subject_ref = entry.get("subject_ref")
    subject_type = subject_ref["type"] if subject_ref is not None else None
    subject_id = subject_ref["id"] if subject_ref is not None else None
    return {
        "log_id": entry["log_id"],
        "service_log_schema_version": entry["service_log_schema_version"],
        "service_id": entry["service_id"],
        "severity": entry["severity"],
        "logger_name": entry["logger_name"],
        "message": entry["message"],
        "trace_id": entry["trace_id"],
        "request_id": entry["request_id"],
        "job_id": entry["job_id"],
        "subject_type": subject_type,
        "subject_id": subject_id,
        "attributes": _json_dumps(entry["attributes"]),
        "redacted_attribute_keys": _json_dumps(entry["redacted_attribute_keys"]),
        "observed_at": entry["observed_at"],
    }


def _log_from_row(row: Any) -> dict[str, Any]:
    subject_ref = None
    if row["subject_type"] is not None or row["subject_id"] is not None:
        subject_ref = {
            "type": row["subject_type"],
            "id": row["subject_id"],
        }
    return validate_service_log_entry(
        {
            "service_log_schema_version": row["service_log_schema_version"],
            "log_id": row["log_id"],
            "service_id": row["service_id"],
            "severity": row["severity"],
            "logger_name": row["logger_name"],
            "message": row["message"],
            "trace_id": row["trace_id"],
            "request_id": row["request_id"],
            "job_id": row["job_id"],
            "subject_ref": subject_ref,
            "attributes": _json_loads(row["attributes"], default={}),
            "redacted_attribute_keys": _json_loads(
                row["redacted_attribute_keys"],
                default=[],
            ),
            "observed_at": _timestamp_to_wire(row["observed_at"]),
        }
    )


def _json_sql_expression(session: Session, param_name: str) -> str:
    if _dialect_name(session) == "postgresql":
        return f"CAST(:{param_name} AS JSONB)"
    return f":{param_name}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: Any, *, default: Any) -> Any:
    if value is None:
        return deepcopy(default)
    if isinstance(value, (dict, list)):
        return deepcopy(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return deepcopy(default)


def _timestamp_to_wire(value: Any) -> str:
    if isinstance(value, datetime):
        observed = value
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        return observed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _service_log_store_unavailable() -> ServiceLogError:
    return ServiceLogError(
        error_code="service_log.store_unavailable",
        detail="service log store is unavailable",
        status_code=503,
    )
