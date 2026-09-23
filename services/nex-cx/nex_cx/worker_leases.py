from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_runtime import JobQueue, JobQueueError
from nex_cx.worker_contracts import (
    CURRENT_CX_WORKLOADS,
    CxWorkerContractError,
    build_cx_worker_execution,
)


CX_WORKER_LEASE_SCHEMA_VERSION = "cx_worker_lease.v1"
DEFAULT_LEASE_TTL_SECONDS = 120
MAX_LEASE_TTL_SECONDS = 86_400


@dataclass(frozen=True)
class CxWorkerLeaseError(Exception):
    error_code: str
    detail: str
    status_code: int = 409
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class CxWorkerLeasePolicy:
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS

    def __post_init__(self) -> None:
        if (
            not isinstance(self.ttl_seconds, int)
            or isinstance(self.ttl_seconds, bool)
            or self.ttl_seconds < 1
            or self.ttl_seconds > MAX_LEASE_TTL_SECONDS
        ):
            raise CxWorkerLeaseError(
                error_code="cx.worker_lease.ttl_invalid",
                detail=(
                    "ttl_seconds must be an integer between 1 and "
                    f"{MAX_LEASE_TTL_SECONDS}."
                ),
                status_code=422,
            )


class SqlAlchemyCxWorkerLeaseStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def inspect(
        self,
        job_id: str,
        *,
        policy: CxWorkerLeasePolicy | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any] | None:
        resolved_job_id = _required_string(job_id, "job_id")
        observed = _timestamp(observed_at or _utc_now(), "observed_at")
        resolved_policy = policy or CxWorkerLeasePolicy()
        try:
            with self._session_factory() as session:
                row = _select_lock(session, resolved_job_id)
        except SQLAlchemyError as exc:
            raise _store_unavailable() from exc
        if row is None:
            return None
        return _lease_projection(row, policy=resolved_policy, observed_at=observed)

    def require_active(
        self,
        job_id: str,
        *,
        worker_id: str,
        policy: CxWorkerLeasePolicy | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        lease = self.inspect(
            job_id,
            policy=policy,
            observed_at=observed_at,
        )
        if lease is None:
            raise CxWorkerLeaseError(
                error_code="cx.worker_lease.job_not_found",
                detail="The worker job was not found.",
                status_code=404,
            )
        expected_worker = _required_string(worker_id, "worker_id")
        if lease["job_status"] != "RUNNING":
            raise CxWorkerLeaseError(
                error_code="cx.worker_lease.job_not_running",
                detail="Only RUNNING jobs have an active worker lease.",
            )
        if lease["locked_at"] is None:
            raise CxWorkerLeaseError(
                error_code="cx.worker_lease.not_acquired",
                detail="The worker job does not have a durable lease timestamp.",
            )
        if lease["worker_id"] != expected_worker:
            raise CxWorkerLeaseError(
                error_code="cx.worker_lease.owner_mismatch",
                detail="The worker lease belongs to another worker.",
            )
        if lease["expired"]:
            raise CxWorkerLeaseError(
                error_code="cx.worker_lease.expired",
                detail="The worker lease has expired.",
                retryable=True,
            )
        return lease

    def renew(
        self,
        job_id: str,
        *,
        worker_id: str,
        expected_locked_at: str,
        observed_at: str | None = None,
        policy: CxWorkerLeasePolicy | None = None,
    ) -> dict[str, Any]:
        resolved_job_id = _required_string(job_id, "job_id")
        resolved_worker_id = _required_string(worker_id, "worker_id")
        expected = _timestamp(expected_locked_at, "expected_locked_at")
        observed = _timestamp(observed_at or _utc_now(), "observed_at")
        if observed < expected:
            raise CxWorkerLeaseError(
                error_code="cx.worker_lease.time_regression",
                detail="A worker lease cannot be renewed backwards in time.",
            )
        resolved_policy = policy or CxWorkerLeasePolicy()
        session = self._session_factory()
        try:
            try:
                result = session.execute(
                    text(
                        """
                        UPDATE service_jobs
                        SET locked_at = :observed_at,
                            updated_at = :observed_at
                        WHERE job_id = :job_id
                          AND status = 'RUNNING'
                          AND locked_by = :worker_id
                          AND locked_at = :expected_locked_at
                        """
                    ),
                    {
                        "job_id": resolved_job_id,
                        "worker_id": resolved_worker_id,
                        "expected_locked_at": _wire_timestamp(expected),
                        "observed_at": _wire_timestamp(observed),
                    },
                )
                if result.rowcount != 1:
                    current = _select_lock(session, resolved_job_id)
                    raise _renewal_conflict(current, resolved_worker_id)
                current = _select_lock(session, resolved_job_id)
                assert current is not None
                session.commit()
            except Exception:
                session.rollback()
                raise
        except CxWorkerLeaseError:
            raise
        except SQLAlchemyError as exc:
            raise _store_unavailable() from exc
        finally:
            session.close()
        return _lease_projection(
            current,
            policy=resolved_policy,
            observed_at=observed,
        )


def claim_next_worker_execution(
    *,
    job_queue: JobQueue,
    lease_store: SqlAlchemyCxWorkerLeaseStore,
    worker_id: str,
    worker_type: str,
    workload: str,
    policy: CxWorkerLeasePolicy | None = None,
    observed_at: str | None = None,
) -> dict[str, Any] | None:
    resolved_worker_id = _required_string(worker_id, "worker_id")
    resolved_workload = _required_string(workload, "workload")
    job_type = CURRENT_CX_WORKLOADS.get(resolved_workload)
    if job_type is None:
        raise CxWorkerLeaseError(
            error_code="cx.worker_lease.workload_invalid",
            detail="workload must name a registered CX worker workload.",
            status_code=422,
        )
    observed = _wire_timestamp(_timestamp(observed_at or _utc_now(), "observed_at"))
    resolved_policy = policy or CxWorkerLeasePolicy()
    try:
        job = job_queue.claim_next_job(
            resolved_worker_id,
            job_type=job_type,
            updated_at=observed,
        )
    except JobQueueError as exc:
        raise CxWorkerLeaseError(
            error_code="cx.worker_lease.claim_failed",
            detail=exc.detail,
            status_code=exc.status_code,
            retryable=exc.status_code >= 500,
        ) from exc
    if job is None:
        return None
    lease = lease_store.require_active(
        str(job["job_id"]),
        worker_id=resolved_worker_id,
        policy=resolved_policy,
        observed_at=observed,
    )
    try:
        return build_cx_worker_execution(
            job,
            worker_id=resolved_worker_id,
            worker_type=worker_type,
            workload=resolved_workload,
            lease_expires_at=str(lease["expires_at"]),
            observed_at=observed,
        )
    except CxWorkerContractError as exc:
        raise CxWorkerLeaseError(
            error_code="cx.worker_lease.execution_contract_invalid",
            detail=exc.detail,
            status_code=exc.status_code,
        ) from exc


def _select_lock(session: Session, job_id: str) -> Mapping[str, Any] | None:
    return session.execute(
        text(
            """
            SELECT job_id, job_type, status, locked_by, locked_at
            FROM service_jobs
            WHERE job_id = :job_id
            """
        ),
        {"job_id": job_id},
    ).mappings().first()


def _lease_projection(
    row: Mapping[str, Any],
    *,
    policy: CxWorkerLeasePolicy,
    observed_at: datetime,
) -> dict[str, Any]:
    locked_at_value = row.get("locked_at")
    locked_at = (
        _timestamp(locked_at_value, "locked_at")
        if locked_at_value is not None
        else None
    )
    expires_at = (
        locked_at + timedelta(seconds=policy.ttl_seconds)
        if locked_at is not None
        else None
    )
    status = str(row["status"])
    expired = expires_at is not None and expires_at <= observed_at
    return {
        "lease_schema_version": CX_WORKER_LEASE_SCHEMA_VERSION,
        "job_id": str(row["job_id"]),
        "job_type": str(row["job_type"]),
        "job_status": status,
        "worker_id": str(row["locked_by"]) if row.get("locked_by") else None,
        "locked_at": _wire_timestamp(locked_at) if locked_at else None,
        "expires_at": _wire_timestamp(expires_at) if expires_at else None,
        "ttl_seconds": policy.ttl_seconds,
        "active": bool(
            status == "RUNNING"
            and row.get("locked_by")
            and locked_at is not None
            and not expired
        ),
        "expired": expired,
        "observed_at": _wire_timestamp(observed_at),
    }


def _renewal_conflict(
    current: Mapping[str, Any] | None,
    worker_id: str,
) -> CxWorkerLeaseError:
    if current is None:
        return CxWorkerLeaseError(
            error_code="cx.worker_lease.job_not_found",
            detail="The worker job was not found.",
            status_code=404,
        )
    if current["status"] != "RUNNING":
        return CxWorkerLeaseError(
            error_code="cx.worker_lease.job_not_running",
            detail="Only RUNNING jobs can renew a worker lease.",
        )
    if current.get("locked_by") != worker_id:
        return CxWorkerLeaseError(
            error_code="cx.worker_lease.owner_mismatch",
            detail="The worker lease belongs to another worker.",
        )
    return CxWorkerLeaseError(
        error_code="cx.worker_lease.changed",
        detail="The worker lease changed before renewal.",
    )


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CxWorkerLeaseError(
            error_code="cx.worker_lease.field_invalid",
            detail=f"{field_name} must be a non-empty string.",
            status_code=422,
        )
    return value.strip()


def _timestamp(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CxWorkerLeaseError(
                error_code="cx.worker_lease.timestamp_invalid",
                detail=f"{field_name} must be an ISO-8601 timestamp.",
                status_code=422,
            ) from exc
    else:
        raise CxWorkerLeaseError(
            error_code="cx.worker_lease.timestamp_invalid",
            detail=f"{field_name} must be an ISO-8601 timestamp.",
            status_code=422,
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _wire_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _store_unavailable() -> CxWorkerLeaseError:
    return CxWorkerLeaseError(
        error_code="cx.worker_lease.store_unavailable",
        detail="The CX worker lease store is unavailable.",
        status_code=503,
        retryable=True,
    )
