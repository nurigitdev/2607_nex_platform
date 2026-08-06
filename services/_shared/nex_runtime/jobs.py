from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

COMMON_JOB_SCHEMA_VERSION = "common_job.v1"
DEFAULT_JOB_LIMIT = 50
MAX_JOB_LIMIT = 500

QUEUED = "QUEUED"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

JOB_STATUSES = (QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED)
TERMINAL_JOB_STATUSES = (SUCCEEDED, FAILED, CANCELLED)
ACTIVE_JOB_STATUSES = (QUEUED, RUNNING)
RETRY_ACTION_REQUEUE = "REQUEUE"
RETRY_ACTION_DEAD_LETTER = "DEAD_LETTER"
JOB_RETRY_ACTIONS = (RETRY_ACTION_REQUEUE, RETRY_ACTION_DEAD_LETTER)
DEFAULT_RETRY_INITIAL_DELAY_SECONDS = 30
DEFAULT_RETRY_MAX_DELAY_SECONDS = 900
DEFAULT_RETRY_BACKOFF_MULTIPLIER = 2.0

VALID_JOB_TRANSITIONS: dict[str, tuple[str, ...]] = {
    QUEUED: (RUNNING, CANCELLED),
    RUNNING: (SUCCEEDED, FAILED, CANCELLED),
    SUCCEEDED: (),
    FAILED: (),
    CANCELLED: (),
}


@dataclass(frozen=True)
class JobQueueError(Exception):
    error_code: str
    detail: str
    status_code: int = 409

    def __str__(self) -> str:
        return self.detail


class JobQueue(Protocol):
    def enqueue(self, job: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        ...

    def start_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        ...

    def complete_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        ...

    def fail_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        ...

    def retry_job(
        self,
        job_id: str,
        *,
        error: dict[str, Any] | None = None,
        failed_at: str | None = None,
        policy: JobRetryPolicy | None = None,
    ) -> dict[str, Any]:
        ...

    def cancel_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        ...

    def claim_next_job(
        self,
        worker_id: str,
        *,
        job_type: str | None = None,
        updated_at: str | None = None,
    ) -> dict[str, Any] | None:
        ...

    def list_jobs(
        self,
        *,
        job_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class JobRetryPolicy:
    initial_delay_seconds: int = DEFAULT_RETRY_INITIAL_DELAY_SECONDS
    max_delay_seconds: int = DEFAULT_RETRY_MAX_DELAY_SECONDS
    backoff_multiplier: float = DEFAULT_RETRY_BACKOFF_MULTIPLIER

    def __post_init__(self) -> None:
        if not isinstance(self.initial_delay_seconds, int) or self.initial_delay_seconds < 0:
            raise JobQueueError(
                error_code="job_retry_policy.initial_delay_invalid",
                detail="initial_delay_seconds must be a non-negative integer",
                status_code=422,
            )
        if not isinstance(self.max_delay_seconds, int) or self.max_delay_seconds < 0:
            raise JobQueueError(
                error_code="job_retry_policy.max_delay_invalid",
                detail="max_delay_seconds must be a non-negative integer",
                status_code=422,
            )
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise JobQueueError(
                error_code="job_retry_policy.max_delay_invalid",
                detail="max_delay_seconds must be greater than or equal to initial_delay_seconds",
                status_code=422,
            )
        if not isinstance(self.backoff_multiplier, (int, float)) or self.backoff_multiplier < 1:
            raise JobQueueError(
                error_code="job_retry_policy.multiplier_invalid",
                detail="backoff_multiplier must be greater than or equal to 1",
                status_code=422,
            )


@dataclass(frozen=True)
class JobRetryDecision:
    action: str
    failed_at: str
    available_at: str | None
    error: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "failed_at": self.failed_at,
            "available_at": self.available_at,
            "error": deepcopy(self.error),
        }


def build_common_job(
    *,
    job_id: str,
    job_type: str,
    trace_id: str,
    request_id: str,
    subject_ref: dict[str, str],
    idempotency_key: str,
    created_at: str | None = None,
    max_attempts: int = 1,
    retryable: bool = True,
    links: dict[str, str] | None = None,
    status: str = QUEUED,
) -> dict[str, Any]:
    now = created_at or _utc_now()
    job = {
        "job_schema_version": COMMON_JOB_SCHEMA_VERSION,
        "job_id": job_id,
        "job_type": job_type,
        "status": status,
        "trace_id": trace_id,
        "request_id": request_id,
        "subject_ref": subject_ref,
        "idempotency_key": idempotency_key,
        "attempt_count": 0,
        "max_attempts": max_attempts,
        "retryable": retryable,
        "links": links or {},
        "created_at": now,
        "updated_at": now,
    }
    return validate_common_job(job)


def build_job_error(
    *,
    error_code: str,
    detail: str,
    retryable: bool,
    dead_lettered: bool = False,
) -> dict[str, Any]:
    return {
        "error_code": _required_string(error_code, "error.error_code"),
        "detail": _required_string(detail, "error.detail"),
        "retryable": bool(retryable),
        "dead_lettered": bool(dead_lettered),
    }


def plan_job_retry(
    job: dict[str, Any],
    *,
    error: dict[str, Any] | None = None,
    failed_at: str | None = None,
    policy: JobRetryPolicy | None = None,
) -> JobRetryDecision:
    normalized = validate_common_job(job)
    if normalized["status"] != RUNNING:
        raise JobQueueError(
            error_code="job.retry_status_invalid",
            detail="only RUNNING jobs can be retried",
            status_code=409,
        )
    observed_failed_at = failed_at or _utc_now()
    retryable = (
        bool(normalized["retryable"])
        and int(normalized["attempt_count"]) < int(normalized["max_attempts"])
    )
    safe_error = _normalize_job_error(error, retryable=retryable)
    if not retryable:
        return JobRetryDecision(
            action=RETRY_ACTION_DEAD_LETTER,
            failed_at=observed_failed_at,
            available_at=None,
            error={**safe_error, "retryable": False, "dead_lettered": True},
        )
    retry_policy = policy or JobRetryPolicy()
    delay_seconds = _retry_delay_seconds(
        attempt_count=int(normalized["attempt_count"]),
        policy=retry_policy,
    )
    return JobRetryDecision(
        action=RETRY_ACTION_REQUEUE,
        failed_at=observed_failed_at,
        available_at=_add_seconds(observed_failed_at, delay_seconds),
        error={**safe_error, "retryable": True, "dead_lettered": False},
    )


def build_subject_ref(subject_type: str, subject_id: str) -> dict[str, str]:
    return {
        "type": _required_string(subject_type, "subject_ref.type"),
        "id": _required_string(subject_id, "subject_ref.id"),
    }


def validate_common_job(job: dict[str, Any]) -> dict[str, Any]:
    missing = [
        field_name
        for field_name in (
            "job_schema_version",
            "job_id",
            "job_type",
            "status",
            "trace_id",
            "request_id",
            "subject_ref",
            "idempotency_key",
            "attempt_count",
            "max_attempts",
            "retryable",
            "links",
            "created_at",
            "updated_at",
        )
        if field_name not in job
    ]
    if missing:
        raise JobQueueError(
            error_code="job.invalid",
            detail=f"missing job fields: {', '.join(missing)}",
            status_code=422,
        )
    if job["job_schema_version"] != COMMON_JOB_SCHEMA_VERSION:
        raise JobQueueError(
            error_code="job.schema_version_invalid",
            detail="job_schema_version must be common_job.v1",
            status_code=422,
        )
    _required_string(job["job_id"], "job_id")
    _required_string(job["job_type"], "job_type")
    _required_string(job["trace_id"], "trace_id")
    _required_string(job["request_id"], "request_id")
    _required_string(job["idempotency_key"], "idempotency_key")
    if job["status"] not in JOB_STATUSES:
        raise JobQueueError(
            error_code="job.status_invalid",
            detail=f"unsupported job status: {job['status']}",
            status_code=422,
        )
    subject_ref = job["subject_ref"]
    if not isinstance(subject_ref, dict):
        raise JobQueueError(
            error_code="job.subject_ref_invalid",
            detail="subject_ref must be an object",
            status_code=422,
        )
    _required_string(str(subject_ref.get("type", "")), "subject_ref.type")
    _required_string(str(subject_ref.get("id", "")), "subject_ref.id")
    if not isinstance(job["attempt_count"], int) or job["attempt_count"] < 0:
        raise JobQueueError(
            error_code="job.attempt_count_invalid",
            detail="attempt_count must be a non-negative integer",
            status_code=422,
        )
    if not isinstance(job["max_attempts"], int) or job["max_attempts"] < 1:
        raise JobQueueError(
            error_code="job.max_attempts_invalid",
            detail="max_attempts must be a positive integer",
            status_code=422,
        )
    if job["attempt_count"] > job["max_attempts"]:
        raise JobQueueError(
            error_code="job.attempts_exhausted",
            detail="attempt_count cannot exceed max_attempts",
            status_code=422,
        )
    if not isinstance(job["retryable"], bool):
        raise JobQueueError(
            error_code="job.retryable_invalid",
            detail="retryable must be a boolean",
            status_code=422,
        )
    if not isinstance(job["links"], dict):
        raise JobQueueError(
            error_code="job.links_invalid",
            detail="links must be an object",
            status_code=422,
        )
    return job


def transition_common_job(
    job: dict[str, Any],
    status: str,
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    validate_common_job(job)
    if status not in JOB_STATUSES:
        raise JobQueueError(
            error_code="job.status_invalid",
            detail=f"unsupported job status: {status}",
            status_code=422,
        )
    current_status = str(job["status"])
    if current_status == status:
        return deepcopy(job)
    if status not in VALID_JOB_TRANSITIONS[current_status]:
        raise JobQueueError(
            error_code="job.transition_invalid",
            detail=f"cannot transition job from {current_status} to {status}",
            status_code=409,
        )
    updated = deepcopy(job)
    if status == RUNNING:
        if updated["attempt_count"] >= updated["max_attempts"]:
            raise JobQueueError(
                error_code="job.attempts_exhausted",
                detail="job has no remaining attempts",
                status_code=409,
            )
        updated["attempt_count"] += 1
    updated["status"] = status
    updated["updated_at"] = updated_at or _utc_now()
    return updated


def summarize_jobs(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {status: 0 for status in JOB_STATUSES}
    for job in jobs:
        status = str(job.get("status", ""))
        if status in counts:
            counts[status] += 1
    return {
        "total": len(jobs),
        "active": counts[QUEUED] + counts[RUNNING],
        "terminal": counts[SUCCEEDED] + counts[FAILED] + counts[CANCELLED],
        "statuses": counts,
    }


def normalize_job_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > MAX_JOB_LIMIT:
        return MAX_JOB_LIMIT
    return limit


@dataclass
class InMemoryJobQueue:
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    idempotency_index: dict[tuple[str, str], str] = field(default_factory=dict)

    def enqueue(self, job: dict[str, Any]) -> dict[str, Any]:
        validate_common_job(job)
        if job["status"] != QUEUED:
            raise JobQueueError(
                error_code="job.enqueue_status_invalid",
                detail="only QUEUED jobs can be enqueued",
                status_code=422,
            )
        index_key = (str(job["job_type"]), str(job["idempotency_key"]))
        existing_job_id = self.idempotency_index.get(index_key)
        if existing_job_id is not None:
            return deepcopy(self.jobs[existing_job_id])
        job_id = str(job["job_id"])
        if job_id in self.jobs:
            raise JobQueueError(
                error_code="job.duplicate_id",
                detail=f"job already exists: {job_id}",
                status_code=409,
            )
        self.jobs[job_id] = deepcopy(job)
        self.idempotency_index[index_key] = job_id
        return deepcopy(self.jobs[job_id])

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        return deepcopy(job) if job is not None else None

    def start_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        return self._transition(job_id, RUNNING, updated_at=updated_at)

    def complete_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        return self._transition(job_id, SUCCEEDED, updated_at=updated_at)

    def fail_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        return self._transition(job_id, FAILED, updated_at=updated_at)

    def retry_job(
        self,
        job_id: str,
        *,
        error: dict[str, Any] | None = None,
        failed_at: str | None = None,
        policy: JobRetryPolicy | None = None,
    ) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if job is None:
            raise JobQueueError(
                error_code="job.not_found",
                detail=f"job was not found: {job_id}",
                status_code=404,
            )
        decision = plan_job_retry(job, error=error, failed_at=failed_at, policy=policy)
        updated = deepcopy(job)
        updated["updated_at"] = decision.failed_at
        updated["error"] = decision.error
        if decision.action == RETRY_ACTION_REQUEUE:
            updated["status"] = QUEUED
            updated["available_at"] = decision.available_at
        else:
            updated["status"] = FAILED
            updated["retryable"] = False
            updated["available_at"] = decision.failed_at
        self.jobs[job_id] = updated
        return deepcopy(updated)

    def cancel_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        return self._transition(job_id, CANCELLED, updated_at=updated_at)

    def claim_next_job(
        self,
        worker_id: str,
        *,
        job_type: str | None = None,
        updated_at: str | None = None,
    ) -> dict[str, Any] | None:
        _required_string(worker_id, "worker_id")
        observed_at = updated_at or _utc_now()
        candidates = [
            job
            for job in self.jobs.values()
            if job["status"] == QUEUED
            and job["attempt_count"] < job["max_attempts"]
            and _available_at_is_ready(str(job.get("available_at", job["created_at"])), observed_at)
            and (job_type is None or job["job_type"] == job_type)
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda job: (
                str(job.get("available_at", job["created_at"])),
                str(job["created_at"]),
                str(job["job_id"]),
            )
        )
        return self.start_job(str(candidates[0]["job_id"]), updated_at=observed_at)

    def list_jobs(
        self,
        *,
        job_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            deepcopy(job)
            for job in self.jobs.values()
            if (job_type is None or job["job_type"] == job_type)
            and (status is None or job["status"] == status)
        ]

    def summary(self) -> dict[str, Any]:
        return summarize_jobs(self.list_jobs())

    def _transition(
        self,
        job_id: str,
        status: str,
        *,
        updated_at: str | None,
    ) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if job is None:
            raise JobQueueError(
                error_code="job.not_found",
                detail=f"job was not found: {job_id}",
                status_code=404,
            )
        updated = transition_common_job(job, status, updated_at=updated_at)
        self.jobs[job_id] = updated
        return deepcopy(updated)


class SqlAlchemyJobQueue:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def enqueue(self, job: dict[str, Any]) -> dict[str, Any]:
        validate_common_job(job)
        if job["status"] != QUEUED:
            raise JobQueueError(
                error_code="job.enqueue_status_invalid",
                detail="only QUEUED jobs can be enqueued",
                status_code=422,
        )
        job_to_store = deepcopy(job)
        try:
            return self._run_in_transaction(lambda session: self._enqueue(session, job_to_store))
        except JobQueueError:
            raise
        except IntegrityError as exc:
            raise JobQueueError(
                error_code="job.duplicate_id",
                detail=f"job already exists: {job_to_store['job_id']}",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise _job_store_unavailable() from exc

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_job(session, job_id)
        except SQLAlchemyError as exc:
            raise _job_store_unavailable() from exc

    def start_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        return self._transition(job_id, RUNNING, updated_at=updated_at)

    def complete_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        return self._transition(job_id, SUCCEEDED, updated_at=updated_at)

    def fail_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        return self._transition(job_id, FAILED, updated_at=updated_at)

    def retry_job(
        self,
        job_id: str,
        *,
        error: dict[str, Any] | None = None,
        failed_at: str | None = None,
        policy: JobRetryPolicy | None = None,
    ) -> dict[str, Any]:
        try:
            return self._run_in_transaction(
                lambda session: self._retry_job(
                    session,
                    job_id=job_id,
                    error=error,
                    failed_at=failed_at,
                    policy=policy,
                )
            )
        except JobQueueError:
            raise
        except SQLAlchemyError as exc:
            raise _job_store_unavailable() from exc

    def cancel_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        return self._transition(job_id, CANCELLED, updated_at=updated_at)

    def claim_next_job(
        self,
        worker_id: str,
        *,
        job_type: str | None = None,
        updated_at: str | None = None,
    ) -> dict[str, Any] | None:
        _required_string(worker_id, "worker_id")
        now = updated_at or _utc_now()
        try:
            return self._run_in_transaction(
                lambda session: self._claim_next_job(
                    session,
                    worker_id=worker_id,
                    job_type=job_type,
                    updated_at=now,
                )
            )
        except JobQueueError:
            raise
        except SQLAlchemyError as exc:
            raise _job_store_unavailable() from exc

    def list_jobs(
        self,
        *,
        job_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        where_clauses: list[str] = []
        params: dict[str, Any] = {}
        if job_type is not None:
            where_clauses.append("job_type = :job_type")
            params["job_type"] = job_type
        if status is not None:
            where_clauses.append("status = :status")
            params["status"] = status
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(
                        f"""
                        SELECT {_JOB_SELECT_COLUMNS}
                        FROM service_jobs
                        {where_sql}
                        ORDER BY created_at, job_id
                        """
                    ),
                    params,
                ).mappings()
                return [_job_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _job_store_unavailable() from exc

    def summary(self) -> dict[str, Any]:
        return summarize_jobs(self.list_jobs())

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

    def _enqueue(self, session: Session, job: dict[str, Any]) -> dict[str, Any]:
        existing = self._select_idempotent_job(
            session,
            job_type=str(job["job_type"]),
            idempotency_key=str(job["idempotency_key"]),
        )
        if existing is not None:
            return existing
        duplicate_id = self._select_job(session, str(job["job_id"]))
        if duplicate_id is not None:
            raise JobQueueError(
                error_code="job.duplicate_id",
                detail=f"job already exists: {job['job_id']}",
                status_code=409,
            )
        self._insert_job(session, job)
        stored = self._select_job(session, str(job["job_id"]))
        assert stored is not None
        return stored

    def _claim_next_job(
        self,
        session: Session,
        *,
        worker_id: str,
        job_type: str | None,
        updated_at: str,
    ) -> dict[str, Any] | None:
        job = self._select_claim_candidate(
            session,
            job_type=job_type,
            available_at=updated_at,
        )
        if job is None:
            return None
        updated = transition_common_job(job, RUNNING, updated_at=updated_at)
        self._update_job_transition(
            session,
            updated,
            locked_by=worker_id,
            locked_at=updated_at,
        )
        stored = self._select_job(session, str(updated["job_id"]))
        assert stored is not None
        return stored

    def _transition(
        self,
        job_id: str,
        status: str,
        *,
        updated_at: str | None,
    ) -> dict[str, Any]:
        try:
            return self._run_in_transaction(
                lambda session: self._transition_job(
                    session,
                    job_id=job_id,
                    status=status,
                    updated_at=updated_at,
                )
            )
        except JobQueueError:
            raise
        except SQLAlchemyError as exc:
            raise _job_store_unavailable() from exc

    def _transition_job(
        self,
        session: Session,
        *,
        job_id: str,
        status: str,
        updated_at: str | None,
    ) -> dict[str, Any]:
        job = self._select_job(session, job_id, for_update=True)
        if job is None:
            raise JobQueueError(
                error_code="job.not_found",
                detail=f"job was not found: {job_id}",
                status_code=404,
            )
        updated = transition_common_job(job, status, updated_at=updated_at)
        if updated == job:
            return updated
        self._update_job_transition(session, updated)
        stored = self._select_job(session, job_id)
        assert stored is not None
        return stored

    def _retry_job(
        self,
        session: Session,
        *,
        job_id: str,
        error: dict[str, Any] | None,
        failed_at: str | None,
        policy: JobRetryPolicy | None,
    ) -> dict[str, Any]:
        job = self._select_job(session, job_id, for_update=True)
        if job is None:
            raise JobQueueError(
                error_code="job.not_found",
                detail=f"job was not found: {job_id}",
                status_code=404,
            )
        decision = plan_job_retry(job, error=error, failed_at=failed_at, policy=policy)
        self._update_job_retry_decision(session, job, decision)
        stored = self._select_job(session, job_id)
        assert stored is not None
        return stored

    def _select_idempotent_job(
        self,
        session: Session,
        *,
        job_type: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_JOB_SELECT_COLUMNS}
                FROM service_jobs
                WHERE job_type = :job_type AND idempotency_key = :idempotency_key
                """
            ),
            {"job_type": job_type, "idempotency_key": idempotency_key},
        ).mappings().first()
        return _job_from_row(row) if row is not None else None

    def _select_job(
        self,
        session: Session,
        job_id: str,
        *,
        for_update: bool = False,
    ) -> dict[str, Any] | None:
        lock_sql = " FOR UPDATE" if for_update and _dialect_name(session) == "postgresql" else ""
        row = session.execute(
            text(
                f"""
                SELECT {_JOB_SELECT_COLUMNS}
                FROM service_jobs
                WHERE job_id = :job_id
                {lock_sql}
                """
            ),
            {"job_id": job_id},
        ).mappings().first()
        return _job_from_row(row) if row is not None else None

    def _select_claim_candidate(
        self,
        session: Session,
        *,
        job_type: str | None,
        available_at: str,
    ) -> dict[str, Any] | None:
        where_clauses = [
            "status = :status",
            "available_at <= :available_at",
            "attempt_count < max_attempts",
        ]
        params: dict[str, Any] = {
            "status": QUEUED,
            "available_at": available_at,
        }
        if job_type is not None:
            where_clauses.append("job_type = :job_type")
            params["job_type"] = job_type
        lock_sql = (
            "FOR UPDATE SKIP LOCKED"
            if _dialect_name(session) == "postgresql"
            else ""
        )
        row = session.execute(
            text(
                f"""
                SELECT {_JOB_SELECT_COLUMNS}
                FROM service_jobs
                WHERE {' AND '.join(where_clauses)}
                ORDER BY available_at, created_at, job_id
                LIMIT 1
                {lock_sql}
                """
            ),
            params,
        ).mappings().first()
        return _job_from_row(row) if row is not None else None

    def _insert_job(self, session: Session, job: dict[str, Any]) -> None:
        json_links, json_payload, json_error = _json_sql_expressions(session)
        session.execute(
            text(
                f"""
                INSERT INTO service_jobs (
                    job_id,
                    job_schema_version,
                    job_type,
                    status,
                    trace_id,
                    request_id,
                    subject_type,
                    subject_id,
                    idempotency_key,
                    attempt_count,
                    max_attempts,
                    retryable,
                    links,
                    payload,
                    error,
                    available_at,
                    locked_at,
                    locked_by,
                    started_at,
                    completed_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    :job_id,
                    :job_schema_version,
                    :job_type,
                    :status,
                    :trace_id,
                    :request_id,
                    :subject_type,
                    :subject_id,
                    :idempotency_key,
                    :attempt_count,
                    :max_attempts,
                    :retryable,
                    {json_links},
                    {json_payload},
                    {json_error},
                    :available_at,
                    :locked_at,
                    :locked_by,
                    :started_at,
                    :completed_at,
                    :created_at,
                    :updated_at
                )
                """
            ),
            _job_insert_params(job),
        )

    def _update_job_transition(
        self,
        session: Session,
        job: dict[str, Any],
        *,
        locked_by: str | None = None,
        locked_at: str | None = None,
    ) -> None:
        status = str(job["status"])
        updated_at = str(job["updated_at"])
        terminal_completed_at = updated_at if status in TERMINAL_JOB_STATUSES else None
        running_started_at = updated_at if status == RUNNING else None
        active_locked_by = locked_by if status not in TERMINAL_JOB_STATUSES else None
        active_locked_at = locked_at if status not in TERMINAL_JOB_STATUSES else None
        session.execute(
            text(
                """
                UPDATE service_jobs
                SET status = :status,
                    attempt_count = :attempt_count,
                    updated_at = :updated_at,
                    started_at = COALESCE(started_at, :started_at),
                    completed_at = COALESCE(:completed_at, completed_at),
                    locked_by = :locked_by,
                    locked_at = :locked_at
                WHERE job_id = :job_id
                """
            ),
            {
                "job_id": job["job_id"],
                "status": status,
                "attempt_count": job["attempt_count"],
                "updated_at": updated_at,
                "started_at": running_started_at,
                "completed_at": terminal_completed_at,
                "locked_by": active_locked_by,
                "locked_at": active_locked_at,
            },
        )

    def _update_job_retry_decision(
        self,
        session: Session,
        job: dict[str, Any],
        decision: JobRetryDecision,
    ) -> None:
        _, _, json_error = _json_sql_expressions(session)
        if decision.action == RETRY_ACTION_REQUEUE:
            status = QUEUED
            retryable = True
            available_at = decision.available_at
            completed_at = None
        else:
            status = FAILED
            retryable = False
            available_at = decision.failed_at
            completed_at = decision.failed_at
        session.execute(
            text(
                f"""
                UPDATE service_jobs
                SET status = :status,
                    retryable = :retryable,
                    error = {json_error},
                    available_at = :available_at,
                    locked_by = NULL,
                    locked_at = NULL,
                    completed_at = :completed_at,
                    updated_at = :updated_at
                WHERE job_id = :job_id
                """
            ),
            {
                "job_id": job["job_id"],
                "status": status,
                "retryable": retryable,
                "error": _json_dumps(decision.error),
                "available_at": available_at,
                "completed_at": completed_at,
                "updated_at": decision.failed_at,
            },
        )


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise JobQueueError(
            error_code="job.field_invalid",
            detail=f"{field_name} must be a non-empty string",
            status_code=422,
        )
    return value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalize_job_error(error: dict[str, Any] | None, *, retryable: bool) -> dict[str, Any]:
    if error is None:
        return build_job_error(
            error_code="job.execution_failed",
            detail="job execution failed",
            retryable=retryable,
        )
    return build_job_error(
        error_code=str(error.get("error_code", "job.execution_failed")),
        detail=str(error.get("detail", "job execution failed")),
        retryable=retryable,
        dead_lettered=bool(error.get("dead_lettered", False)),
    )


def _retry_delay_seconds(*, attempt_count: int, policy: JobRetryPolicy) -> int:
    exponent = max(attempt_count - 1, 0)
    raw_delay = policy.initial_delay_seconds * (float(policy.backoff_multiplier) ** exponent)
    return min(int(raw_delay), policy.max_delay_seconds)


def _add_seconds(timestamp: str, seconds: int) -> str:
    observed = _parse_wire_datetime(timestamp)
    return (observed + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _parse_wire_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    observed = datetime.fromisoformat(normalized)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed.astimezone(UTC)


def _available_at_is_ready(available_at: str, observed_at: str) -> bool:
    return _parse_wire_datetime(available_at) <= _parse_wire_datetime(observed_at)


_JOB_SELECT_COLUMNS = """
    job_id,
    job_schema_version,
    job_type,
    status,
    trace_id,
    request_id,
    subject_type,
    subject_id,
    idempotency_key,
    attempt_count,
    max_attempts,
    retryable,
    links,
    error,
    available_at,
    created_at,
    updated_at
"""


def _job_insert_params(job: dict[str, Any]) -> dict[str, Any]:
    subject_ref = job["subject_ref"]
    return {
        "job_id": job["job_id"],
        "job_schema_version": job["job_schema_version"],
        "job_type": job["job_type"],
        "status": job["status"],
        "trace_id": job["trace_id"],
        "request_id": job["request_id"],
        "subject_type": subject_ref["type"],
        "subject_id": subject_ref["id"],
        "idempotency_key": job["idempotency_key"],
        "attempt_count": job["attempt_count"],
        "max_attempts": job["max_attempts"],
        "retryable": job["retryable"],
        "links": _json_dumps(job["links"]),
        "payload": _json_dumps(job.get("payload", {})),
        "error": _json_dumps(job["error"]) if job.get("error") is not None else None,
        "available_at": job.get("available_at", job["created_at"]),
        "locked_at": job.get("locked_at"),
        "locked_by": job.get("locked_by"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


def _job_from_row(row: Any) -> dict[str, Any]:
    return validate_common_job(
        {
            "job_schema_version": row["job_schema_version"],
            "job_id": row["job_id"],
            "job_type": row["job_type"],
            "status": row["status"],
            "trace_id": row["trace_id"],
            "request_id": row["request_id"],
            "subject_ref": {
                "type": row["subject_type"],
                "id": row["subject_id"],
            },
            "idempotency_key": row["idempotency_key"],
            "attempt_count": int(row["attempt_count"]),
            "max_attempts": int(row["max_attempts"]),
            "retryable": bool(row["retryable"]),
            "links": _json_loads(row["links"], default={}),
            "error": _json_loads(row["error"], default=None),
            "available_at": _timestamp_to_wire(row["available_at"]),
            "created_at": _timestamp_to_wire(row["created_at"]),
            "updated_at": _timestamp_to_wire(row["updated_at"]),
        }
    )


def _json_sql_expressions(session: Session) -> tuple[str, str, str]:
    if _dialect_name(session) == "postgresql":
        return (
            "CAST(:links AS JSONB)",
            "CAST(:payload AS JSONB)",
            "CAST(:error AS JSONB)",
        )
    return (":links", ":payload", ":error")


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


def _job_store_unavailable() -> JobQueueError:
    return JobQueueError(
        error_code="job.store_unavailable",
        detail="job queue store is unavailable",
        status_code=503,
    )
