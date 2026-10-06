from __future__ import annotations

from collections import Counter
from datetime import datetime
import re
from typing import Any, Mapping, Sequence

TRACE_STAGE_SCHEMA_VERSION = "cross_service_trace_stage.v1"
TRACE_TIMELINE_SCHEMA_VERSION = "ag_cross_service_trace_e2e.v1"
TRACE_SOURCE_PROJECTION_SCHEMA_VERSION = "service_cross_service_trace_projection.v1"
TRACE_STAGE_FAMILIES = (
    "AUTH",
    "UPLOAD",
    "INGESTION",
    "RETRIEVAL",
    "GENERATION",
    "ARTIFACT",
    "ACCESS",
    "OPERATIONS",
)
TRACE_STAGE_STATUSES = (
    "STARTED",
    "SUCCEEDED",
    "FAILED",
    "BLOCKED",
    "SKIPPED",
    "RECOVERING",
)
TRACE_SOURCE_STATUSES = ("READY", "DEGRADED", "UNAVAILABLE")
TRACE_SERVICE_IDS = ("nex-oa", "nex-ae-api", "nex-cx", "nex-mo", "nex-ag")
TRACE_CORRELATION_FIELDS = frozenset(
    {
        "session_id",
        "upload_id",
        "source_file_id",
        "processing_run_id",
        "ingestion_run_id",
        "retrieval_package_id",
        "cx_generation_id",
        "response_id",
        "artifact_id",
        "render_job_id",
        "provider_request_id",
    }
)
TRACE_SAFE_ATTRIBUTE_FIELDS = frozenset(
    {
        "event_type",
        "result_code",
        "failure_code",
        "retryable",
        "attempt",
        "progress_percent",
        "confidence_state",
        "citation_status",
        "artifact_status",
        "provider_capability",
        "model_alias",
        "model_revision",
        "deployment_id",
        "provider_route_id",
        "provider_mode",
        "cleanup_residue_count",
    }
)
TRACE_FORBIDDEN_KEY_FRAGMENTS = (
    "prompt",
    "content",
    "source_text",
    "evidence_text",
    "generated_text",
    "draft",
    "vector",
    "token",
    "cookie",
    "password",
    "secret",
    "api_key",
    "provider_url",
    "database_url",
    "storage_ref",
    "file_path",
)
_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class CrossServiceTraceError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def build_cross_service_trace_stage(
    *,
    stage_id: str,
    trace_id: str,
    request_id: str,
    service_id: str,
    stage_family: str,
    stage_status: str,
    operation_timestamp: str,
    correlation_refs: Mapping[str, object] | None = None,
    safe_attributes: Mapping[str, object] | None = None,
    owner_digest: str | None = None,
) -> dict[str, Any]:
    normalized_stage_id = _identifier(stage_id, "stage_id")
    normalized_request_id = _identifier(request_id, "request_id")
    if not _TRACE_ID_PATTERN.fullmatch(trace_id):
        raise CrossServiceTraceError(
            "trace.trace_id_invalid",
            "trace_id must contain 32 lowercase hexadecimal characters",
        )
    if service_id not in TRACE_SERVICE_IDS:
        raise CrossServiceTraceError(
            "trace.service_id_invalid", "service_id is not a platform service"
        )
    if stage_family not in TRACE_STAGE_FAMILIES:
        raise CrossServiceTraceError(
            "trace.stage_family_invalid", "stage_family is not supported"
        )
    if stage_status not in TRACE_STAGE_STATUSES:
        raise CrossServiceTraceError(
            "trace.stage_status_invalid", "stage_status is not supported"
        )
    normalized_timestamp = _timestamp(operation_timestamp)
    normalized_refs = _correlation_refs(correlation_refs or {})
    normalized_attributes = _safe_attributes(safe_attributes or {})
    if owner_digest is not None and not _DIGEST_PATTERN.fullmatch(owner_digest):
        raise CrossServiceTraceError(
            "trace.owner_digest_invalid", "owner_digest must be a SHA-256 digest"
        )
    stage = {
        "stage_schema_version": TRACE_STAGE_SCHEMA_VERSION,
        "stage_id": normalized_stage_id,
        "trace_id": trace_id,
        "request_id": normalized_request_id,
        "service_id": service_id,
        "stage_family": stage_family,
        "stage_status": stage_status,
        "operation_timestamp": normalized_timestamp,
        "correlation_refs": normalized_refs,
        "safe_attributes": normalized_attributes,
        "private_payload_included": False,
    }
    if owner_digest is not None:
        stage["owner_digest"] = owner_digest
    return stage


def build_cross_service_trace_timeline(
    *,
    trace_id: str,
    stages: Sequence[Mapping[str, Any]],
    source_statuses: Mapping[str, str],
    checked_at: str,
) -> dict[str, Any]:
    if not _TRACE_ID_PATTERN.fullmatch(trace_id):
        raise CrossServiceTraceError(
            "trace.trace_id_invalid",
            "trace_id must contain 32 lowercase hexadecimal characters",
        )
    normalized_sources = _source_statuses(source_statuses)
    normalized_stages = [_validated_stage(stage, trace_id) for stage in stages]
    normalized_stages.sort(
        key=lambda item: (item["operation_timestamp"], item["stage_id"])
    )
    by_family = Counter(item["stage_family"] for item in normalized_stages)
    by_status = Counter(item["stage_status"] for item in normalized_stages)
    degraded = any(
        item["source_status"] != "READY" for item in normalized_sources
    ) or any(status in by_status for status in ("FAILED", "BLOCKED"))
    return {
        "projection_schema_version": TRACE_TIMELINE_SCHEMA_VERSION,
        "trace_id": trace_id,
        "projection_status": "DEGRADED" if degraded else "READY",
        "checked_at": _timestamp(checked_at),
        "source_statuses": normalized_sources,
        "timeline": normalized_stages,
        "summary": {
            "stage_count": len(normalized_stages),
            "source_count": len(normalized_sources),
            "by_family": dict(sorted(by_family.items())),
            "by_status": dict(sorted(by_status.items())),
            "private_payload_included": False,
        },
    }


def build_cross_service_trace_source_projection(
    *,
    service_id: str,
    trace_id: str,
    stages: Sequence[Mapping[str, Any]],
    source_status: str,
    checked_at: str,
) -> dict[str, Any]:
    if service_id not in TRACE_SERVICE_IDS:
        raise CrossServiceTraceError(
            "trace.source_service_invalid", "source service is not supported"
        )
    if source_status not in TRACE_SOURCE_STATUSES:
        raise CrossServiceTraceError(
            "trace.source_status_invalid", "source status is not supported"
        )
    timeline = build_cross_service_trace_timeline(
        trace_id=trace_id,
        stages=stages,
        source_statuses={service_id: source_status},
        checked_at=checked_at,
    )
    foreign_services = sorted(
        {
            stage["service_id"]
            for stage in timeline["timeline"]
            if stage["service_id"] != service_id
        }
    )
    if foreign_services:
        raise CrossServiceTraceError(
            "trace.source_stage_service_mismatch",
            "source projection stages must belong to the source service",
        )
    return {
        "projection_schema_version": TRACE_SOURCE_PROJECTION_SCHEMA_VERSION,
        "service_id": service_id,
        "trace_id": trace_id,
        "source_status": source_status,
        "checked_at": timeline["checked_at"],
        "stages": timeline["timeline"],
        "summary": {
            "stage_count": timeline["summary"]["stage_count"],
            "by_family": timeline["summary"]["by_family"],
            "by_status": timeline["summary"]["by_status"],
            "private_payload_included": False,
        },
    }


def _validated_stage(stage: Mapping[str, Any], trace_id: str) -> dict[str, Any]:
    try:
        rebuilt = build_cross_service_trace_stage(
            stage_id=stage["stage_id"],
            trace_id=stage["trace_id"],
            request_id=stage["request_id"],
            service_id=stage["service_id"],
            stage_family=stage["stage_family"],
            stage_status=stage["stage_status"],
            operation_timestamp=stage["operation_timestamp"],
            correlation_refs=stage.get("correlation_refs"),
            safe_attributes=stage.get("safe_attributes"),
            owner_digest=stage.get("owner_digest"),
        )
    except KeyError as exc:
        raise CrossServiceTraceError(
            "trace.stage_field_missing", f"stage field is required: {exc.args[0]}"
        ) from exc
    if rebuilt["trace_id"] != trace_id:
        raise CrossServiceTraceError(
            "trace.stage_trace_mismatch", "all stages must match the timeline trace"
        )
    return rebuilt


def _correlation_refs(values: Mapping[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in values.items():
        _reject_forbidden_key(key)
        if key not in TRACE_CORRELATION_FIELDS:
            raise CrossServiceTraceError(
                "trace.correlation_field_forbidden",
                f"correlation field is not allowed: {key}",
            )
        normalized[key] = _identifier(value, key)
    return dict(sorted(normalized.items()))


def _safe_attributes(values: Mapping[str, object]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in values.items():
        _reject_forbidden_key(key)
        if key not in TRACE_SAFE_ATTRIBUTE_FIELDS:
            raise CrossServiceTraceError(
                "trace.attribute_field_forbidden",
                f"safe attribute is not allowed: {key}",
            )
        if not isinstance(value, (str, int, float, bool)) or isinstance(value, bytes):
            raise CrossServiceTraceError(
                "trace.attribute_value_invalid",
                f"safe attribute must be scalar: {key}",
            )
        if isinstance(value, str) and (not value or len(value) > 128):
            raise CrossServiceTraceError(
                "trace.attribute_value_invalid",
                f"safe attribute string is invalid: {key}",
            )
        normalized[key] = value
    return dict(sorted(normalized.items()))


def _source_statuses(values: Mapping[str, str]) -> list[dict[str, str]]:
    statuses: list[dict[str, str]] = []
    for service_id, status in sorted(values.items()):
        if service_id not in TRACE_SERVICE_IDS:
            raise CrossServiceTraceError(
                "trace.source_service_invalid", "source service is not supported"
            )
        if status not in TRACE_SOURCE_STATUSES:
            raise CrossServiceTraceError(
                "trace.source_status_invalid", "source status is not supported"
            )
        statuses.append({"service_id": service_id, "source_status": status})
    return statuses


def _reject_forbidden_key(key: object) -> None:
    if not isinstance(key, str):
        raise CrossServiceTraceError(
            "trace.field_name_invalid", "trace field names must be strings"
        )
    lowered = key.lower()
    if any(fragment in lowered for fragment in TRACE_FORBIDDEN_KEY_FRAGMENTS):
        raise CrossServiceTraceError(
            "trace.private_field_forbidden", f"private field is forbidden: {key}"
        )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise CrossServiceTraceError(
            "trace.identifier_invalid", f"{field_name} must be a safe identifier"
        )
    return value


def _timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise CrossServiceTraceError(
            "trace.timestamp_invalid", "timestamp must be an ISO 8601 string"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CrossServiceTraceError(
            "trace.timestamp_invalid", "timestamp must be an ISO 8601 string"
        ) from exc
    if parsed.tzinfo is None:
        raise CrossServiceTraceError(
            "trace.timestamp_invalid", "timestamp must include a timezone"
        )
    return value
