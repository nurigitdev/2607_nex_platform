from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from nex_runtime import (
    FAILED,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    JobQueue,
    JobQueueError,
    JobRetryDecision,
    JobRetryPolicy,
    build_job_error,
    plan_job_dead_letter,
    plan_job_retry,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .intake_contracts import WA_EVIDENCE_INGEST_JOB_TYPE

DEFAULT_STALE_JOB_SECONDS = 300
MIN_STALE_JOB_SECONDS = 60
MAX_STALE_JOB_SECONDS = 3600
WA_JOB_OWNERSHIP_LOST = "WA_JOB_OWNERSHIP_LOST"


@dataclass(frozen=True)
class WaJobClaim:
    job_id: str
    worker_id: str
    locked_at: str


class WaJobRecoveryError(JobQueueError):
    pass


class SqlAlchemyWaJobFenceStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def capture_claim(self, job_id: str, *, worker_id: str) -> WaJobClaim:
        with self._session_factory() as session:
            row = session.execute(
                text(
                    """
                    SELECT status, locked_by, locked_at
                    FROM service_jobs
                    WHERE job_id = :job_id
                    """
                ),
                {"job_id": job_id},
            ).mappings().first()
        if (
            row is None
            or row["status"] != RUNNING
            or row["locked_by"] != worker_id
            or row["locked_at"] is None
        ):
            raise _ownership_lost(job_id)
        return WaJobClaim(job_id, worker_id, _wire_timestamp(row["locked_at"]))

    def complete(self, claim: WaJobClaim, *, updated_at: str) -> None:
        self._settle(claim, status=SUCCEEDED, updated_at=updated_at)

    def fail(self, claim: WaJobClaim, *, updated_at: str) -> None:
        self._settle(claim, status=FAILED, updated_at=updated_at)

    def require_current(self, claim: WaJobClaim) -> None:
        with self._session_factory() as session:
            row = session.execute(
                text(
                    """
                    SELECT 1
                    FROM service_jobs
                    WHERE job_id = :job_id
                      AND job_type = :job_type
                      AND status = :running
                      AND locked_by = :worker_id
                      AND locked_at = :locked_at
                    """
                ),
                {
                    "job_id": claim.job_id,
                    "job_type": WA_EVIDENCE_INGEST_JOB_TYPE,
                    "running": RUNNING,
                    "worker_id": claim.worker_id,
                    "locked_at": claim.locked_at,
                },
            ).first()
        if row is None:
            raise _ownership_lost(claim.job_id)

    def apply_retry(self, claim: WaJobClaim, decision: JobRetryDecision) -> None:
        session = self._session_factory()
        try:
            error_expression = (
                "CAST(:error AS JSONB)"
                if session.get_bind().dialect.name == "postgresql"
                else ":error"
            )
            requeue = decision.action == "REQUEUE"
            result = session.execute(
                text(
                    f"""
                    UPDATE service_jobs
                    SET status = :status,
                        retryable = :retryable,
                        error = {error_expression},
                        available_at = :available_at,
                        completed_at = :completed_at,
                        locked_by = NULL,
                        locked_at = NULL,
                        updated_at = :updated_at
                    WHERE job_id = :job_id
                      AND job_type = :job_type
                      AND status = :running
                      AND locked_by = :worker_id
                      AND locked_at = :locked_at
                    """
                ),
                {
                    "job_id": claim.job_id,
                    "job_type": WA_EVIDENCE_INGEST_JOB_TYPE,
                    "running": RUNNING,
                    "worker_id": claim.worker_id,
                    "locked_at": claim.locked_at,
                    "status": QUEUED if requeue else FAILED,
                    "retryable": requeue,
                    "error": json.dumps(
                        decision.error,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "available_at": decision.available_at or decision.failed_at,
                    "completed_at": None if requeue else decision.failed_at,
                    "updated_at": decision.failed_at,
                },
            )
            if result.rowcount != 1:
                raise _ownership_lost(claim.job_id)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def recover_stale(
        self,
        *,
        observed_at: str,
        stale_after_seconds: int = DEFAULT_STALE_JOB_SECONDS,
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        stale_after = normalize_stale_job_seconds(stale_after_seconds)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise WaJobRecoveryError(
                "WA_JOB_RECOVERY_LIMIT_INVALID",
                "recovery limit must be an integer between 1 and 500",
                422,
            )
        observed = _timestamp(observed_at)
        cutoff = _wire_timestamp(observed - timedelta(seconds=stale_after))
        session = self._session_factory()
        try:
            lock_sql = (
                "FOR UPDATE OF j SKIP LOCKED"
                if session.get_bind().dialect.name == "postgresql"
                else ""
            )
            rows = session.execute(
                text(
                    f"""
                    SELECT j.job_id, j.locked_by, j.locked_at,
                           j.attempt_count, j.max_attempts, j.retryable
                    FROM service_jobs j
                    LEFT JOIN service_worker_heartbeats h
                      ON h.service_id = :service_id
                     AND h.worker_id = j.locked_by
                    WHERE j.job_type = :job_type
                      AND j.status = :running
                      AND j.locked_at < :cutoff
                      AND (h.worker_id IS NULL OR h.last_seen_at < :cutoff)
                    ORDER BY j.locked_at, j.job_id
                    LIMIT :limit
                    {lock_sql}
                    """
                ),
                {
                    "service_id": "nex-wa",
                    "job_type": WA_EVIDENCE_INGEST_JOB_TYPE,
                    "running": RUNNING,
                    "cutoff": cutoff,
                    "limit": limit,
                },
            ).mappings().all()
            recovered = tuple(
                self._recover_locked_row(session, row, observed_at=observed_at)
                for row in rows
            )
            session.commit()
            return recovered
        except WaJobRecoveryError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise WaJobRecoveryError(
                "WA_JOB_RECOVERY_UNAVAILABLE",
                "WA stale job recovery store is unavailable",
                503,
            ) from exc
        finally:
            session.close()

    def _recover_locked_row(
        self,
        session: Session,
        row: Any,
        *,
        observed_at: str,
    ) -> dict[str, Any]:
        requeue = bool(row["retryable"]) and int(row["attempt_count"]) < int(
            row["max_attempts"]
        )
        error = build_job_error(
            error_code="WA_JOB_STALE_RECOVERED",
            detail="stale RUNNING WA evidence job recovered after owner heartbeat loss",
            retryable=requeue,
            dead_lettered=not requeue,
        )
        error_expression = (
            "CAST(:error AS JSONB)"
            if session.get_bind().dialect.name == "postgresql"
            else ":error"
        )
        status = QUEUED if requeue else FAILED
        result = session.execute(
            text(
                f"""
                UPDATE service_jobs
                SET status = :status,
                    retryable = :retryable,
                    error = {error_expression},
                    available_at = :observed_at,
                    completed_at = :completed_at,
                    locked_by = NULL,
                    locked_at = NULL,
                    updated_at = :observed_at
                WHERE job_id = :job_id
                  AND status = :running
                  AND locked_by = :worker_id
                  AND locked_at = :locked_at
                """
            ),
            {
                "job_id": row["job_id"],
                "running": RUNNING,
                "worker_id": row["locked_by"],
                "locked_at": _wire_timestamp(row["locked_at"]),
                "status": status,
                "retryable": requeue,
                "error": json.dumps(error, sort_keys=True, separators=(",", ":")),
                "observed_at": observed_at,
                "completed_at": None if requeue else observed_at,
            },
        )
        if result.rowcount != 1:
            raise _ownership_lost(str(row["job_id"]))
        return {
            "job_id": str(row["job_id"]),
            "previous_worker_id": str(row["locked_by"]),
            "previous_locked_at": _wire_timestamp(row["locked_at"]),
            "status": status,
            "action": "REQUEUED" if requeue else "DEAD_LETTERED",
        }

    def _settle(self, claim: WaJobClaim, *, status: str, updated_at: str) -> None:
        session = self._session_factory()
        try:
            result = session.execute(
                text(
                    """
                    UPDATE service_jobs
                    SET status = :status,
                        completed_at = :updated_at,
                        locked_by = NULL,
                        locked_at = NULL,
                        updated_at = :updated_at
                    WHERE job_id = :job_id
                      AND job_type = :job_type
                      AND status = :running
                      AND locked_by = :worker_id
                      AND locked_at = :locked_at
                    """
                ),
                {
                    "job_id": claim.job_id,
                    "job_type": WA_EVIDENCE_INGEST_JOB_TYPE,
                    "running": RUNNING,
                    "worker_id": claim.worker_id,
                    "locked_at": claim.locked_at,
                    "status": status,
                    "updated_at": updated_at,
                },
            )
            if result.rowcount != 1:
                raise _ownership_lost(claim.job_id)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class WaFencedJobQueue:
    def __init__(self, queue: JobQueue, fence_store: SqlAlchemyWaJobFenceStore) -> None:
        self._queue = queue
        self._fence_store = fence_store
        self._claims: dict[str, WaJobClaim] = {}

    def enqueue(self, job: dict[str, Any]) -> dict[str, Any]:
        return self._queue.enqueue(job)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self._queue.get_job(job_id)

    def start_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        return self._queue.start_job(job_id, updated_at=updated_at)

    def complete_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        claim = self._require_claim(job_id)
        self._fence_store.complete(claim, updated_at=updated_at or _utc_now())
        self._claims.pop(job_id, None)
        return self._require_job(job_id)

    def fail_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        claim = self._require_claim(job_id)
        self._fence_store.fail(claim, updated_at=updated_at or _utc_now())
        self._claims.pop(job_id, None)
        return self._require_job(job_id)

    def retry_job(
        self,
        job_id: str,
        *,
        error: dict[str, Any] | None = None,
        failed_at: str | None = None,
        policy: JobRetryPolicy | None = None,
    ) -> dict[str, Any]:
        claim = self._require_claim(job_id)
        self._fence_store.require_current(claim)
        job = self._require_job(job_id)
        decision = plan_job_retry(
            job,
            error=error,
            failed_at=failed_at,
            policy=policy,
        )
        self._fence_store.apply_retry(claim, decision)
        self._claims.pop(job_id, None)
        return self._require_job(job_id)

    def dead_letter_job(
        self,
        job_id: str,
        *,
        error: dict[str, Any] | None = None,
        failed_at: str | None = None,
    ) -> dict[str, Any]:
        claim = self._require_claim(job_id)
        self._fence_store.require_current(claim)
        decision = plan_job_dead_letter(
            self._require_job(job_id), error=error, failed_at=failed_at
        )
        self._fence_store.apply_retry(claim, decision)
        self._claims.pop(job_id, None)
        return self._require_job(job_id)

    def cancel_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        return self._queue.cancel_job(job_id, updated_at=updated_at)

    def claim_next_job(
        self,
        worker_id: str,
        *,
        job_type: str | None = None,
        updated_at: str | None = None,
    ) -> dict[str, Any] | None:
        job = self._queue.claim_next_job(
            worker_id, job_type=job_type, updated_at=updated_at
        )
        if job is not None:
            self._claims[str(job["job_id"])] = self._fence_store.capture_claim(
                str(job["job_id"]), worker_id=worker_id
            )
        return job

    def list_jobs(
        self, *, job_type: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        return self._queue.list_jobs(job_type=job_type, status=status)

    def _require_claim(self, job_id: str) -> WaJobClaim:
        claim = self._claims.get(job_id)
        if claim is None:
            raise _ownership_lost(job_id)
        return claim

    def _require_job(self, job_id: str) -> dict[str, Any]:
        job = self._queue.get_job(job_id)
        if job is None:
            raise WaJobRecoveryError("WA_JOB_NOT_FOUND", "WA job was not found", 404)
        return job


def normalize_stale_job_seconds(value: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < MIN_STALE_JOB_SECONDS
        or value > MAX_STALE_JOB_SECONDS
    ):
        raise WaJobRecoveryError(
            "WA_STALE_JOB_SECONDS_INVALID",
            f"stale job seconds must be between {MIN_STALE_JOB_SECONDS} and {MAX_STALE_JOB_SECONDS}",
            422,
        )
    return value


def _ownership_lost(job_id: str) -> WaJobRecoveryError:
    return WaJobRecoveryError(
        WA_JOB_OWNERSHIP_LOST,
        f"WA job claim ownership was lost: {job_id}",
    )


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise WaJobRecoveryError(
                "WA_JOB_TIMESTAMP_INVALID", "job timestamp must be ISO-8601", 422
            ) from exc
    else:
        raise WaJobRecoveryError(
            "WA_JOB_TIMESTAMP_INVALID", "job timestamp must be ISO-8601", 422
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _wire_timestamp(value: object) -> str:
    return _timestamp(value).isoformat().replace("+00:00", "Z")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
