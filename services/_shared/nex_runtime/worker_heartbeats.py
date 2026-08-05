from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any


WORKER_HEARTBEAT_SCHEMA_VERSION = "worker_heartbeat.v1"

STARTING = "STARTING"
IDLE = "IDLE"
BUSY = "BUSY"
STOPPING = "STOPPING"
STOPPED = "STOPPED"
ERROR = "ERROR"

WORKER_HEARTBEAT_STATUSES = (
    STARTING,
    IDLE,
    BUSY,
    STOPPING,
    STOPPED,
    ERROR,
)
ACTIVE_WORKER_HEARTBEAT_STATUSES = (STARTING, IDLE, BUSY)
TERMINAL_WORKER_HEARTBEAT_STATUSES = (STOPPED, ERROR)

SERVICE_IDS = ("nex-oa", "nex-ag", "nex-ae-api", "nex-cx", "nex-mo")

DEFAULT_WORKER_STALE_AFTER_SECONDS = 60
MAX_WORKER_STALE_AFTER_SECONDS = 86_400


class WorkerHeartbeatError(Exception):
    def __init__(self, *, error_code: str, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code


def build_worker_heartbeat(
    *,
    service_id: str,
    worker_id: str,
    worker_type: str,
    status: str = IDLE,
    active_job_id: str | None = None,
    trace_id: str | None = None,
    started_at: str | None = None,
    last_seen_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    heartbeat = {
        "heartbeat_schema_version": WORKER_HEARTBEAT_SCHEMA_VERSION,
        "service_id": service_id,
        "worker_id": worker_id,
        "worker_type": worker_type,
        "status": status,
        "active_job_id": active_job_id,
        "trace_id": trace_id,
        "started_at": started_at or now,
        "last_seen_at": last_seen_at or now,
        "metadata": deepcopy(metadata) if metadata is not None else {},
    }
    return validate_worker_heartbeat(heartbeat)


def validate_worker_heartbeat(heartbeat: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(heartbeat, dict):
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.invalid",
            detail="worker heartbeat must be an object",
        )

    required_fields = {
        "heartbeat_schema_version",
        "service_id",
        "worker_id",
        "worker_type",
        "status",
        "active_job_id",
        "trace_id",
        "started_at",
        "last_seen_at",
        "metadata",
    }
    if required_fields - heartbeat.keys():
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.invalid",
            detail="worker heartbeat is missing required fields",
        )
    if heartbeat["heartbeat_schema_version"] != WORKER_HEARTBEAT_SCHEMA_VERSION:
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.schema_version_invalid",
            detail="worker heartbeat schema version is invalid",
        )

    _required_string(heartbeat["worker_id"], "worker_id")
    _required_string(heartbeat["worker_type"], "worker_type")

    if heartbeat["service_id"] not in SERVICE_IDS:
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.service_invalid",
            detail=f"unknown service_id: {heartbeat['service_id']}",
        )
    if heartbeat["status"] not in WORKER_HEARTBEAT_STATUSES:
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.status_invalid",
            detail=f"unknown worker heartbeat status: {heartbeat['status']}",
        )
    if heartbeat["trace_id"] is not None and not _is_trace_id(heartbeat["trace_id"]):
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.trace_id_invalid",
            detail="trace_id must be null or a 32-character lowercase hex string",
        )
    active_job_id = heartbeat["active_job_id"]
    if active_job_id is not None and not isinstance(active_job_id, str):
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.active_job_id_invalid",
            detail="active_job_id must be null or a non-empty string",
        )
    if isinstance(active_job_id, str) and not active_job_id:
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.active_job_id_invalid",
            detail="active_job_id must be null or a non-empty string",
        )
    if heartbeat["status"] == BUSY and active_job_id is None:
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.active_job_required",
            detail="BUSY worker heartbeats require active_job_id",
        )
    if not isinstance(heartbeat["metadata"], dict):
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.metadata_invalid",
            detail="metadata must be an object",
        )

    started_at = _parse_wire_datetime(heartbeat["started_at"], "started_at")
    last_seen_at = _parse_wire_datetime(heartbeat["last_seen_at"], "last_seen_at")
    if last_seen_at < started_at:
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.timestamp_order_invalid",
            detail="last_seen_at must be greater than or equal to started_at",
        )

    return deepcopy(heartbeat)


def worker_heartbeat_is_stale(
    heartbeat: dict[str, Any],
    *,
    stale_after_seconds: int = DEFAULT_WORKER_STALE_AFTER_SECONDS,
    checked_at: str | None = None,
) -> bool:
    normalized = validate_worker_heartbeat(heartbeat)
    stale_after = normalize_worker_stale_after_seconds(stale_after_seconds)
    observed_at = _parse_wire_datetime(normalized["last_seen_at"], "last_seen_at")
    if checked_at is None:
        now = datetime.now(UTC)
    else:
        now = _parse_wire_datetime(checked_at, "checked_at")
    return (now - observed_at).total_seconds() > stale_after


def summarize_worker_heartbeats(
    heartbeats: list[dict[str, Any]],
    *,
    stale_after_seconds: int = DEFAULT_WORKER_STALE_AFTER_SECONDS,
    checked_at: str | None = None,
) -> dict[str, Any]:
    counts = {status: 0 for status in WORKER_HEARTBEAT_STATUSES}
    services = {service_id: 0 for service_id in SERVICE_IDS}
    stale_count = 0
    active_count = 0
    for heartbeat in heartbeats:
        normalized = validate_worker_heartbeat(heartbeat)
        status = normalized["status"]
        counts[status] += 1
        services[normalized["service_id"]] += 1
        if status in ACTIVE_WORKER_HEARTBEAT_STATUSES:
            active_count += 1
        if worker_heartbeat_is_stale(
            normalized,
            stale_after_seconds=stale_after_seconds,
            checked_at=checked_at,
        ):
            stale_count += 1

    return {
        "total": len(heartbeats),
        "active": active_count,
        "stale": stale_count,
        "statuses": counts,
        "services": services,
    }


def normalize_worker_stale_after_seconds(stale_after_seconds: int) -> int:
    if stale_after_seconds < 1:
        return 1
    if stale_after_seconds > MAX_WORKER_STALE_AFTER_SECONDS:
        return MAX_WORKER_STALE_AFTER_SECONDS
    return stale_after_seconds


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.field_invalid",
            detail=f"{field_name} must be a non-empty string",
        )
    return value


def _is_trace_id(value: object) -> bool:
    return isinstance(value, str) and len(value) == 32 and all(char in "0123456789abcdef" for char in value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_wire_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.timestamp_invalid",
            detail=f"{field_name} must be a date-time string",
        )
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.timestamp_invalid",
            detail=f"{field_name} must be a valid date-time string",
        ) from exc
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed.astimezone(UTC)
