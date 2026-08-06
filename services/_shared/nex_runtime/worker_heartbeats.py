from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Protocol

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


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


class WorkerHeartbeatStore(Protocol):
    def upsert_heartbeat(self, heartbeat: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_heartbeat(self, service_id: str, worker_id: str) -> dict[str, Any] | None:
        ...

    def list_heartbeats(
        self,
        *,
        service_id: str | None = None,
        worker_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class WorkerHeartbeatEmitResult:
    ok: bool
    heartbeat: dict[str, Any] | None = None
    error_code: str | None = None
    detail: str | None = None
    status_code: int | None = None

    @classmethod
    def emitted(cls, heartbeat: dict[str, Any]) -> WorkerHeartbeatEmitResult:
        return cls(ok=True, heartbeat=deepcopy(heartbeat))

    @classmethod
    def failed(
        cls,
        *,
        error_code: str,
        detail: str,
        status_code: int,
    ) -> WorkerHeartbeatEmitResult:
        return cls(
            ok=False,
            error_code=error_code,
            detail=detail,
            status_code=status_code,
        )

    def to_summary(self) -> dict[str, Any]:
        if self.ok and self.heartbeat is not None:
            return {
                "ok": True,
                "service_id": self.heartbeat["service_id"],
                "worker_id": self.heartbeat["worker_id"],
                "worker_type": self.heartbeat["worker_type"],
                "status": self.heartbeat["status"],
                "active_job_id": self.heartbeat["active_job_id"],
            }
        return {
            "ok": False,
            "error_code": self.error_code,
            "detail": self.detail,
            "status_code": self.status_code,
        }


class WorkerHeartbeatEmitter:
    def __init__(
        self,
        *,
        service_id: str,
        worker_id: str,
        worker_type: str,
        store: WorkerHeartbeatStore,
        started_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        observed_started_at = started_at or _utc_now()
        self.service_id = _validate_service_id(service_id)
        self.worker_id = _required_string(worker_id, "worker_id")
        self.worker_type = _required_string(worker_type, "worker_type")
        self.store = store
        self.started_at = observed_started_at
        self.metadata = deepcopy(metadata) if metadata is not None else {}
        build_worker_heartbeat(
            service_id=self.service_id,
            worker_id=self.worker_id,
            worker_type=self.worker_type,
            status=IDLE,
            active_job_id=None,
            started_at=self.started_at,
            last_seen_at=self.started_at,
            metadata=self.metadata,
        )

    def emit(
        self,
        *,
        status: str,
        active_job_id: str | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        heartbeat = build_worker_heartbeat(
            service_id=self.service_id,
            worker_id=self.worker_id,
            worker_type=self.worker_type,
            status=status,
            active_job_id=active_job_id,
            trace_id=trace_id,
            started_at=self.started_at,
            last_seen_at=observed_at,
            metadata=self._merged_metadata(metadata),
        )
        return self.store.upsert_heartbeat(heartbeat)

    def safe_emit(
        self,
        *,
        status: str,
        active_job_id: str | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> WorkerHeartbeatEmitResult:
        try:
            return WorkerHeartbeatEmitResult.emitted(
                self.emit(
                    status=status,
                    active_job_id=active_job_id,
                    trace_id=trace_id,
                    metadata=metadata,
                    observed_at=observed_at,
                )
            )
        except WorkerHeartbeatError as exc:
            return WorkerHeartbeatEmitResult.failed(
                error_code=exc.error_code,
                detail=exc.detail,
                status_code=exc.status_code,
            )
        except Exception:
            return WorkerHeartbeatEmitResult.failed(
                error_code="worker_heartbeat.emit_failed",
                detail="worker heartbeat emission failed",
                status_code=503,
            )

    def starting(
        self,
        *,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        return self.emit(
            status=STARTING,
            trace_id=trace_id,
            metadata=metadata,
            observed_at=observed_at,
        )

    def idle(
        self,
        *,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        return self.emit(
            status=IDLE,
            trace_id=trace_id,
            metadata=metadata,
            observed_at=observed_at,
        )

    def busy(
        self,
        *,
        active_job_id: str,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        return self.emit(
            status=BUSY,
            active_job_id=active_job_id,
            trace_id=trace_id,
            metadata=metadata,
            observed_at=observed_at,
        )

    def stopping(
        self,
        *,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        return self.emit(
            status=STOPPING,
            trace_id=trace_id,
            metadata=metadata,
            observed_at=observed_at,
        )

    def stopped(
        self,
        *,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        return self.emit(
            status=STOPPED,
            trace_id=trace_id,
            metadata=metadata,
            observed_at=observed_at,
        )

    def error(
        self,
        *,
        active_job_id: str | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        return self.emit(
            status=ERROR,
            active_job_id=active_job_id,
            trace_id=trace_id,
            metadata=metadata,
            observed_at=observed_at,
        )

    def _merged_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        merged = deepcopy(self.metadata)
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise WorkerHeartbeatError(
                    error_code="worker_heartbeat.metadata_invalid",
                    detail="metadata must be an object",
                )
            merged.update(deepcopy(metadata))
        return merged


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


@dataclass
class InMemoryWorkerHeartbeatStore:
    heartbeats: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def upsert_heartbeat(self, heartbeat: dict[str, Any]) -> dict[str, Any]:
        normalized = validate_worker_heartbeat(heartbeat)
        key = (normalized["service_id"], normalized["worker_id"])
        self.heartbeats[key] = deepcopy(normalized)
        return deepcopy(self.heartbeats[key])

    def get_heartbeat(self, service_id: str, worker_id: str) -> dict[str, Any] | None:
        _validate_service_id(service_id)
        _required_string(worker_id, "worker_id")
        heartbeat = self.heartbeats.get((service_id, worker_id))
        return deepcopy(heartbeat) if heartbeat is not None else None

    def list_heartbeats(
        self,
        *,
        service_id: str | None = None,
        worker_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_service_id = _validate_service_id(service_id) if service_id is not None else None
        normalized_worker_type = _required_string(worker_type, "worker_type") if worker_type is not None else None
        normalized_status = _validate_status(status) if status is not None else None
        heartbeats = [
            deepcopy(heartbeat)
            for heartbeat in self.heartbeats.values()
            if (normalized_service_id is None or heartbeat["service_id"] == normalized_service_id)
            and (normalized_worker_type is None or heartbeat["worker_type"] == normalized_worker_type)
            and (normalized_status is None or heartbeat["status"] == normalized_status)
        ]
        return sorted(
            heartbeats,
            key=lambda heartbeat: (
                heartbeat["service_id"],
                heartbeat["worker_type"],
                heartbeat["worker_id"],
            ),
        )

    def summary(self) -> dict[str, Any]:
        return summarize_worker_heartbeats(self.list_heartbeats())


class SqlAlchemyWorkerHeartbeatStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert_heartbeat(self, heartbeat: dict[str, Any]) -> dict[str, Any]:
        heartbeat_to_store = deepcopy(validate_worker_heartbeat(heartbeat))
        try:
            return self._run_in_transaction(
                lambda session: self._upsert_heartbeat(session, heartbeat_to_store)
            )
        except WorkerHeartbeatError:
            raise
        except SQLAlchemyError as exc:
            raise _heartbeat_store_unavailable() from exc

    def get_heartbeat(self, service_id: str, worker_id: str) -> dict[str, Any] | None:
        _validate_service_id(service_id)
        _required_string(worker_id, "worker_id")
        try:
            with self._session_factory() as session:
                return self._select_heartbeat(session, service_id, worker_id)
        except SQLAlchemyError as exc:
            raise _heartbeat_store_unavailable() from exc

    def list_heartbeats(
        self,
        *,
        service_id: str | None = None,
        worker_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_service_id = _validate_service_id(service_id) if service_id is not None else None
        normalized_worker_type = _required_string(worker_type, "worker_type") if worker_type is not None else None
        normalized_status = _validate_status(status) if status is not None else None
        where_clauses: list[str] = []
        params: dict[str, Any] = {}
        if normalized_service_id is not None:
            where_clauses.append("service_id = :service_id")
            params["service_id"] = normalized_service_id
        if normalized_worker_type is not None:
            where_clauses.append("worker_type = :worker_type")
            params["worker_type"] = normalized_worker_type
        if normalized_status is not None:
            where_clauses.append("status = :status")
            params["status"] = normalized_status
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(
                        f"""
                        SELECT {_HEARTBEAT_SELECT_COLUMNS}
                        FROM service_worker_heartbeats
                        {where_sql}
                        ORDER BY service_id, worker_type, worker_id
                        """
                    ),
                    params,
                ).mappings()
                return [_heartbeat_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _heartbeat_store_unavailable() from exc

    def summary(self) -> dict[str, Any]:
        return summarize_worker_heartbeats(self.list_heartbeats())

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

    def _upsert_heartbeat(self, session: Session, heartbeat: dict[str, Any]) -> dict[str, Any]:
        existing = self._select_heartbeat(
            session,
            str(heartbeat["service_id"]),
            str(heartbeat["worker_id"]),
        )
        if existing is None:
            self._insert_heartbeat(session, heartbeat)
        else:
            self._update_heartbeat(session, heartbeat)
        stored = self._select_heartbeat(
            session,
            str(heartbeat["service_id"]),
            str(heartbeat["worker_id"]),
        )
        assert stored is not None
        return stored

    def _select_heartbeat(
        self,
        session: Session,
        service_id: str,
        worker_id: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_HEARTBEAT_SELECT_COLUMNS}
                FROM service_worker_heartbeats
                WHERE service_id = :service_id AND worker_id = :worker_id
                """
            ),
            {"service_id": service_id, "worker_id": worker_id},
        ).mappings().first()
        return _heartbeat_from_row(row) if row is not None else None

    def _insert_heartbeat(self, session: Session, heartbeat: dict[str, Any]) -> None:
        metadata_expression = _metadata_sql_expression(session)
        session.execute(
            text(
                f"""
                INSERT INTO service_worker_heartbeats (
                    service_id,
                    worker_id,
                    heartbeat_schema_version,
                    worker_type,
                    status,
                    active_job_id,
                    trace_id,
                    started_at,
                    last_seen_at,
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (
                    :service_id,
                    :worker_id,
                    :heartbeat_schema_version,
                    :worker_type,
                    :status,
                    :active_job_id,
                    :trace_id,
                    :started_at,
                    :last_seen_at,
                    {metadata_expression},
                    :created_at,
                    :updated_at
                )
                """
            ),
            _heartbeat_params(heartbeat),
        )

    def _update_heartbeat(self, session: Session, heartbeat: dict[str, Any]) -> None:
        metadata_expression = _metadata_sql_expression(session)
        session.execute(
            text(
                f"""
                UPDATE service_worker_heartbeats
                SET heartbeat_schema_version = :heartbeat_schema_version,
                    worker_type = :worker_type,
                    status = :status,
                    active_job_id = :active_job_id,
                    trace_id = :trace_id,
                    started_at = :started_at,
                    last_seen_at = :last_seen_at,
                    metadata = {metadata_expression},
                    updated_at = :updated_at
                WHERE service_id = :service_id AND worker_id = :worker_id
                """
            ),
            _heartbeat_params(heartbeat),
        )


def worker_heartbeat_store_from_app(app: Any) -> WorkerHeartbeatStore:
    state = getattr(app, "state", None)
    persistence = getattr(state, "nex_persistence", None) if state is not None else None
    store = getattr(persistence, "worker_heartbeat_store", None)
    if store is not None:
        return store
    if state is None:
        return InMemoryWorkerHeartbeatStore()
    fallback_store = getattr(state, "_nex_worker_heartbeat_store", None)
    if fallback_store is None:
        fallback_store = InMemoryWorkerHeartbeatStore()
        setattr(state, "_nex_worker_heartbeat_store", fallback_store)
    return fallback_store


def worker_heartbeat_emitter_from_app(
    app: Any,
    *,
    service_id: str,
    worker_id: str,
    worker_type: str,
    store: WorkerHeartbeatStore | None = None,
    started_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> WorkerHeartbeatEmitter:
    return WorkerHeartbeatEmitter(
        service_id=service_id,
        worker_id=worker_id,
        worker_type=worker_type,
        store=store if store is not None else worker_heartbeat_store_from_app(app),
        started_at=started_at,
        metadata=metadata,
    )


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.field_invalid",
            detail=f"{field_name} must be a non-empty string",
        )
    return value


def _validate_service_id(service_id: str) -> str:
    _required_string(service_id, "service_id")
    if service_id not in SERVICE_IDS:
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.service_invalid",
            detail=f"unknown service_id: {service_id}",
        )
    return service_id


def _validate_status(status: str) -> str:
    normalized_status = _required_string(status, "status").upper()
    if normalized_status not in WORKER_HEARTBEAT_STATUSES:
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.status_invalid",
            detail=f"unknown worker heartbeat status: {status}",
        )
    return normalized_status


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


_HEARTBEAT_SELECT_COLUMNS = """
    service_id,
    worker_id,
    heartbeat_schema_version,
    worker_type,
    status,
    active_job_id,
    trace_id,
    started_at,
    last_seen_at,
    metadata
"""


def _heartbeat_params(heartbeat: dict[str, Any]) -> dict[str, Any]:
    timestamp = _utc_now()
    return {
        "service_id": heartbeat["service_id"],
        "worker_id": heartbeat["worker_id"],
        "heartbeat_schema_version": heartbeat["heartbeat_schema_version"],
        "worker_type": heartbeat["worker_type"],
        "status": heartbeat["status"],
        "active_job_id": heartbeat["active_job_id"],
        "trace_id": heartbeat["trace_id"],
        "started_at": heartbeat["started_at"],
        "last_seen_at": heartbeat["last_seen_at"],
        "metadata": _json_dumps(heartbeat["metadata"]),
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _heartbeat_from_row(row: Any) -> dict[str, Any]:
    return validate_worker_heartbeat(
        {
            "heartbeat_schema_version": row["heartbeat_schema_version"],
            "service_id": row["service_id"],
            "worker_id": row["worker_id"],
            "worker_type": row["worker_type"],
            "status": row["status"],
            "active_job_id": row["active_job_id"],
            "trace_id": row["trace_id"],
            "started_at": _timestamp_to_wire(row["started_at"]),
            "last_seen_at": _timestamp_to_wire(row["last_seen_at"]),
            "metadata": _json_loads(row["metadata"], default={}),
        }
    )


def _metadata_sql_expression(session: Session) -> str:
    if _dialect_name(session) == "postgresql":
        return "CAST(:metadata AS JSONB)"
    return ":metadata"


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


def _heartbeat_store_unavailable() -> WorkerHeartbeatError:
    return WorkerHeartbeatError(
        error_code="worker_heartbeat.store_unavailable",
        detail="worker heartbeat store is unavailable",
        status_code=503,
    )
