from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from nex_runtime import (
    BUSY,
    ERROR,
    IDLE,
    STARTING,
    STOPPED,
    STOPPING,
    WorkerHeartbeatEmitter,
    WorkerHeartbeatStore,
    worker_heartbeat_is_stale,
)


CX_WORKER_READINESS_SCHEMA_VERSION = "cx_worker_readiness.v1"
READY = "READY"
NOT_READY = "NOT_READY"


@dataclass(frozen=True)
class CxWorkerLifecycleError(Exception):
    error_code: str
    detail: str
    status_code: int = 409

    def __str__(self) -> str:
        return self.detail


class CxWorkerLifecycleController:
    def __init__(
        self,
        *,
        emitter: WorkerHeartbeatEmitter,
        store: WorkerHeartbeatStore,
    ) -> None:
        if emitter.store is not store:
            raise CxWorkerLifecycleError(
                error_code="cx.worker_lifecycle.store_mismatch",
                detail="The lifecycle emitter and readiness store must match.",
                status_code=422,
            )
        self.emitter = emitter
        self.store = store
        self._shutdown_requested = False
        self._emissions: list[dict[str, Any]] = []

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    @property
    def can_claim(self) -> bool:
        return not self._shutdown_requested

    @property
    def emissions(self) -> tuple[dict[str, Any], ...]:
        return tuple(deepcopy(self._emissions))

    def starting(self, *, observed_at: str | None = None) -> dict[str, Any]:
        return self._emit(STARTING, observed_at=observed_at)

    def idle(self, *, observed_at: str | None = None) -> dict[str, Any]:
        if self._shutdown_requested:
            return self.stopping(observed_at=observed_at)
        return self._emit(IDLE, observed_at=observed_at)

    def busy(
        self,
        *,
        job_id: str,
        trace_id: str,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        if self._shutdown_requested:
            raise CxWorkerLifecycleError(
                error_code="cx.worker_lifecycle.shutdown_in_progress",
                detail="A stopping worker cannot claim another job.",
            )
        return self._emit(
            BUSY,
            active_job_id=_required_string(job_id, "job_id"),
            trace_id=_required_string(trace_id, "trace_id"),
            observed_at=observed_at,
        )

    def request_shutdown(
        self,
        *,
        reason_code: str = "operator_requested",
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        self._shutdown_requested = True
        return self._emit(
            STOPPING,
            metadata={"reason_code": _required_string(reason_code, "reason_code")},
            observed_at=observed_at,
        )

    def stopping(self, *, observed_at: str | None = None) -> dict[str, Any]:
        self._shutdown_requested = True
        return self._emit(STOPPING, observed_at=observed_at)

    def stopped(self, *, observed_at: str | None = None) -> dict[str, Any]:
        self._shutdown_requested = True
        return self._emit(STOPPED, observed_at=observed_at)

    def failed(
        self,
        *,
        error_code: str,
        job_id: str | None = None,
        trace_id: str | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        return self._emit(
            ERROR,
            active_job_id=job_id,
            trace_id=trace_id,
            metadata={"error_code": _required_string(error_code, "error_code")},
            observed_at=observed_at,
        )

    def readiness(
        self,
        *,
        stale_after_seconds: int = 60,
        checked_at: str | None = None,
    ) -> dict[str, Any]:
        heartbeat = self.store.get_heartbeat(
            self.emitter.service_id,
            self.emitter.worker_id,
        )
        return project_worker_readiness(
            heartbeat,
            stale_after_seconds=stale_after_seconds,
            checked_at=checked_at,
        )

    def _emit(
        self,
        status: str,
        *,
        active_job_id: str | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        result = self.emitter.safe_emit(
            status=status,
            active_job_id=active_job_id,
            trace_id=trace_id,
            metadata=metadata,
            observed_at=observed_at,
        ).to_summary()
        self._emissions.append(result)
        return deepcopy(result)


def project_worker_readiness(
    heartbeat: dict[str, Any] | None,
    *,
    stale_after_seconds: int = 60,
    checked_at: str | None = None,
) -> dict[str, Any]:
    if heartbeat is None:
        return {
            "readiness_schema_version": CX_WORKER_READINESS_SCHEMA_VERSION,
            "readiness": NOT_READY,
            "reason_code": "heartbeat_missing",
            "worker_id": None,
            "worker_type": None,
            "status": None,
            "active_job_id": None,
            "last_seen_at": None,
        }
    stale = worker_heartbeat_is_stale(
        heartbeat,
        stale_after_seconds=stale_after_seconds,
        checked_at=checked_at,
    )
    status = str(heartbeat["status"])
    if stale:
        readiness = NOT_READY
        reason_code = "heartbeat_stale"
    elif status in {IDLE, BUSY}:
        readiness = READY
        reason_code = "worker_available" if status == IDLE else "worker_busy"
    else:
        readiness = NOT_READY
        reason_code = f"worker_{status.lower()}"
    return {
        "readiness_schema_version": CX_WORKER_READINESS_SCHEMA_VERSION,
        "readiness": readiness,
        "reason_code": reason_code,
        "worker_id": str(heartbeat["worker_id"]),
        "worker_type": str(heartbeat["worker_type"]),
        "status": status,
        "active_job_id": heartbeat.get("active_job_id"),
        "last_seen_at": str(heartbeat["last_seen_at"]),
    }


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CxWorkerLifecycleError(
            error_code="cx.worker_lifecycle.field_invalid",
            detail=f"{field_name} must be a non-empty string.",
            status_code=422,
        )
    return value.strip()
