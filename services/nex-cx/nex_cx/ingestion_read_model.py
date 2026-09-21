from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nex_runtime import (
    CANCELLED as JOB_CANCELLED,
    FAILED as JOB_FAILED,
    QUEUED as JOB_QUEUED,
    RUNNING as JOB_RUNNING,
    SUCCEEDED as JOB_SUCCEEDED,
    JobQueue,
    JobQueueError,
)

from nex_cx.ingestion_orchestration import (
    CANCELLED,
    FAILED,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    WAITING_RETRY,
    validate_ingestion_run,
)
from nex_cx.ingestion_orchestration_repository import (
    IngestionRunRepository,
    IngestionRunRepositoryError,
)
from nex_cx.ingestion_worker import CX_INGESTION_JOB_TYPE


CX_INGESTION_READ_MODEL_SCHEMA_VERSION = "cx_ingestion_run_read_model.v1"
CX_INGESTION_RESTART_PLAN_SCHEMA_VERSION = "cx_ingestion_restart_plan.v1"
DEFAULT_INGESTION_RESTART_LIMIT = 100
MAX_INGESTION_RESTART_LIMIT = 500

READY = "READY"
READY_RETRY = "READY_RETRY"
WAITING = "WAITING_RETRY"
ACTIVE = "ACTIVE"
RECOVER_EXPIRED_LEASE = "RECOVER_EXPIRED_LEASE"
TERMINAL = "TERMINAL"
RECONCILE = "RECONCILE"
RESTART_ACTIONS = (
    READY,
    READY_RETRY,
    WAITING,
    ACTIVE,
    RECOVER_EXPIRED_LEASE,
    TERMINAL,
    RECONCILE,
)


@dataclass(frozen=True)
class IngestionReadModelError(Exception):
    error_code: str
    detail: str
    status_code: int = 500

    def __str__(self) -> str:
        return self.detail


def get_ingestion_run_read_model(
    run_id: str,
    *,
    tenant_id: str,
    owner_subject_id: str,
    run_repository: IngestionRunRepository,
) -> dict[str, Any] | None:
    try:
        run = run_repository.get(
            _required_string(run_id, "run_id"),
            tenant_id=_required_string(tenant_id, "tenant_id"),
            owner_subject_id=_required_string(
                owner_subject_id,
                "owner_subject_id",
            ),
        )
    except IngestionRunRepositoryError as exc:
        raise _repository_error(exc) from exc
    return project_ingestion_run(run) if run is not None else None


def list_document_ingestion_run_read_models(
    document_id: str,
    *,
    tenant_id: str,
    owner_subject_id: str,
    run_repository: IngestionRunRepository,
) -> dict[str, Any]:
    try:
        runs = run_repository.list_for_document(
            _required_string(document_id, "document_id"),
            tenant_id=_required_string(tenant_id, "tenant_id"),
            owner_subject_id=_required_string(
                owner_subject_id,
                "owner_subject_id",
            ),
        )
    except IngestionRunRepositoryError as exc:
        raise _repository_error(exc) from exc
    projected = [project_ingestion_run(run) for run in runs]
    return {
        "read_model_schema_version": CX_INGESTION_READ_MODEL_SCHEMA_VERSION,
        "document_id": document_id,
        "run_count": len(projected),
        "status_counts": _status_counts(projected),
        "runs": projected,
    }


def project_ingestion_run(run: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_ingestion_run(run)
    steps = [
        {
            "step_id": step_id,
            "status": state["status"],
            "attempt_count": state["attempt_count"],
            "output_ref": state["output_ref"],
            "error_code": state["error_code"],
            "started_at": state["started_at"],
            "completed_at": state["completed_at"],
        }
        for step_id, state in normalized["step_states"].items()
    ]
    return {
        "read_model_schema_version": CX_INGESTION_READ_MODEL_SCHEMA_VERSION,
        "run_id": normalized["run_id"],
        "document_id": normalized["document_id"],
        "job_id": normalized["job_id"],
        "status": normalized["status"],
        "current_step": normalized["current_step"],
        "attempt_count": normalized["attempt_count"],
        "max_attempts": normalized["max_attempts"],
        "checkpoint_version": normalized["checkpoint_version"],
        "trace_id": normalized["trace_id"],
        "request_id": normalized["request_id"],
        "lease_expires_at": normalized["lease_expires_at"],
        "retry_at": normalized["retry_at"],
        "last_error": dict(normalized["last_error"])
        if normalized["last_error"] is not None
        else None,
        "created_at": normalized["created_at"],
        "updated_at": normalized["updated_at"],
        "completed_at": normalized["completed_at"],
        "step_total": len(steps),
        "step_completed": sum(
            step["status"] in {"SUCCEEDED", "SKIPPED"} for step in steps
        ),
        "steps": steps,
    }


def build_ingestion_restart_plan(
    *,
    job_queue: JobQueue,
    run_repository: IngestionRunRepository,
    observed_at: str | None = None,
    limit: int | str | None = None,
) -> dict[str, Any]:
    observed = observed_at or _utc_now()
    resolved_limit = bounded_ingestion_restart_limit(limit)
    try:
        jobs = job_queue.list_jobs(job_type=CX_INGESTION_JOB_TYPE)
    except JobQueueError as exc:
        raise IngestionReadModelError(
            error_code="cx.ingestion_restart.job_queue_unavailable",
            detail=exc.detail,
            status_code=exc.status_code,
        ) from exc
    selected_jobs = sorted(
        jobs,
        key=lambda job: (str(job["updated_at"]), str(job["job_id"])),
    )[:resolved_limit]
    items = [
        _restart_item(
            job,
            run_repository=run_repository,
            observed_at=observed,
        )
        for job in selected_jobs
    ]
    action_counts = {
        action: sum(item["action"] == action for item in items)
        for action in RESTART_ACTIONS
    }
    return {
        "restart_plan_schema_version": CX_INGESTION_RESTART_PLAN_SCHEMA_VERSION,
        "observed_at": observed,
        "limit": resolved_limit,
        "job_count": len(items),
        "action_counts": {
            action: count for action, count in action_counts.items() if count
        },
        "mutation_performed": False,
        "items": items,
    }


def bounded_ingestion_restart_limit(limit: int | str | None) -> int:
    if limit is None:
        return DEFAULT_INGESTION_RESTART_LIMIT
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise IngestionReadModelError(
            error_code="cx.ingestion_restart.limit_invalid",
            detail="Restart hydration limit must be an integer.",
            status_code=422,
        ) from exc
    if value < 1:
        return 1
    return min(value, MAX_INGESTION_RESTART_LIMIT)


def _restart_item(
    job: Mapping[str, Any],
    *,
    run_repository: IngestionRunRepository,
    observed_at: str,
) -> dict[str, Any]:
    try:
        run = run_repository.find_by_job_id(str(job["job_id"]))
    except IngestionRunRepositoryError as exc:
        raise _repository_error(exc) from exc
    action, reason = _restart_action(job, run, observed_at=observed_at)
    return {
        "job_id": str(job["job_id"]),
        "run_id": str(run["run_id"]) if run is not None else None,
        "document_id": str(job["subject_ref"]["id"]),
        "job_status": str(job["status"]),
        "run_status": str(run["status"]) if run is not None else None,
        "current_step": run.get("current_step") if run is not None else None,
        "checkpoint_version": int(run["checkpoint_version"])
        if run is not None
        else None,
        "lease_expires_at": run.get("lease_expires_at")
        if run is not None
        else None,
        "retry_at": run.get("retry_at") if run is not None else None,
        "action": action,
        "reason": reason,
    }


def _restart_action(
    job: Mapping[str, Any],
    run: Mapping[str, Any] | None,
    *,
    observed_at: str,
) -> tuple[str, str]:
    if run is None:
        return RECONCILE, "durable_run_missing"
    job_status = str(job["status"])
    run_status = str(run["status"])
    if job_status == JOB_QUEUED and run_status == QUEUED:
        return READY, "queued_job_and_run"
    if job_status == JOB_QUEUED and run_status == WAITING_RETRY:
        job_ready = _timestamp_due(
            str(job.get("available_at", job["created_at"])),
            observed_at,
        )
        run_ready = _timestamp_due(str(run["retry_at"]), observed_at)
        return (
            (READY_RETRY, "retry_deadline_reached")
            if job_ready and run_ready
            else (WAITING, "retry_deadline_pending")
        )
    if job_status == JOB_RUNNING and run_status == RUNNING:
        if _timestamp_due(str(run["lease_expires_at"]), observed_at):
            return RECOVER_EXPIRED_LEASE, "worker_lease_expired"
        return ACTIVE, "worker_lease_active"
    terminal_pairs = {
        (JOB_SUCCEEDED, SUCCEEDED),
        (JOB_FAILED, FAILED),
        (JOB_CANCELLED, CANCELLED),
    }
    if (job_status, run_status) in terminal_pairs:
        return TERMINAL, "queue_and_run_terminal"
    return RECONCILE, "queue_run_state_mismatch"


def _status_counts(runs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in runs:
        status = str(run["status"])
        counts[status] = counts.get(status, 0) + 1
    return counts


def _repository_error(exc: IngestionRunRepositoryError) -> IngestionReadModelError:
    return IngestionReadModelError(
        error_code="cx.ingestion_read_model.repository_unavailable",
        detail=exc.detail,
        status_code=exc.status_code,
    )


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestionReadModelError(
            error_code="cx.ingestion_read_model.field_invalid",
            detail=f"{field_name} must be a non-empty string.",
            status_code=422,
        )
    return value.strip()


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise IngestionReadModelError(
            error_code="cx.ingestion_restart.timestamp_invalid",
            detail="Restart hydration timestamps must be ISO-8601 values.",
            status_code=422,
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _timestamp_due(value: str, observed_at: str) -> bool:
    return _timestamp(value) <= _timestamp(observed_at)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
