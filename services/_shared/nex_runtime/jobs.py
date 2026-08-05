from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

COMMON_JOB_SCHEMA_VERSION = "common_job.v1"

QUEUED = "QUEUED"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

JOB_STATUSES = (QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED)
TERMINAL_JOB_STATUSES = (SUCCEEDED, FAILED, CANCELLED)
ACTIVE_JOB_STATUSES = (QUEUED, RUNNING)

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

    def cancel_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        ...

    def list_jobs(
        self,
        *,
        job_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        ...


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

    def cancel_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        return self._transition(job_id, CANCELLED, updated_at=updated_at)

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
