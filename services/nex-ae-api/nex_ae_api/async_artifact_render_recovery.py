from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Mapping, Protocol

from nex_runtime import JobQueue, JobQueueError

from nex_ae_api.async_artifact_rendering import (
    ASYNC_ARTIFACT_RENDER_JOB_TYPE,
    AeAsyncArtifactRenderError,
)


AE_ASYNC_ARTIFACT_RENDER_RECOVERY_SCHEMA_VERSION = (
    "ae_async_artifact_render_recovery.v1"
)
AE_ASYNC_ARTIFACT_RENDER_RECONCILIATION_SCHEMA_VERSION = (
    "ae_async_artifact_render_reconciliation.v1"
)

NO_ACTION = "NO_ACTION"
WAIT_FOR_WORKER = "WAIT_FOR_WORKER"
WAIT_FOR_RETRY = "WAIT_FOR_RETRY"
REPEAT_ADMISSION = "REPEAT_ADMISSION"
RESET_RENDER_TO_QUEUED = "RESET_RENDER_TO_QUEUED"
MARK_RENDER_RUNNING = "MARK_RENDER_RUNNING"
MARK_RENDER_CANCELLED = "MARK_RENDER_CANCELLED"
MARK_RENDER_FAILED = "MARK_RENDER_FAILED"
MANUAL_REVIEW = "MANUAL_REVIEW"

_MUTATING_ACTIONS = frozenset(
    {
        RESET_RENDER_TO_QUEUED,
        MARK_RENDER_RUNNING,
        MARK_RENDER_CANCELLED,
        MARK_RENDER_FAILED,
    }
)


class AsyncArtifactRenderRecoveryStore(Protocol):
    def get(self, artifact_id: str) -> dict[str, Any] | None: ...

    def save(self, record: dict[str, Any]) -> dict[str, Any]: ...

    def get_render_job(self, render_job_id: str) -> dict[str, Any] | None: ...

    def save_render_job_state(
        self,
        render_job: dict[str, Any],
    ) -> dict[str, Any]: ...


def inspect_async_artifact_render_recovery(
    *,
    render_job_id: str,
    artifact_store: AsyncArtifactRenderRecoveryStore,
    job_queue: JobQueue,
) -> dict[str, Any]:
    normalized_id = _required_text(render_job_id, "render_job_id")
    render_job = artifact_store.get_render_job(normalized_id)
    try:
        queue_job = job_queue.get_job(normalized_id)
    except JobQueueError as exc:
        raise _queue_unavailable(exc) from exc
    if render_job is None and queue_job is None:
        raise AeAsyncArtifactRenderError(
            error_code="ae.async_artifact_render.not_found",
            detail="Asynchronous artifact render job was not found.",
            status_code=404,
        )
    return build_async_artifact_render_recovery_plan(
        render_job_id=normalized_id,
        render_job=render_job,
        queue_job=queue_job,
    )


def build_async_artifact_render_recovery_plan(
    *,
    render_job_id: str,
    render_job: Mapping[str, Any] | None,
    queue_job: Mapping[str, Any] | None,
) -> dict[str, Any]:
    normalized_id = _required_text(render_job_id, "render_job_id")
    render = deepcopy(dict(render_job)) if isinstance(render_job, Mapping) else None
    queue = deepcopy(dict(queue_job)) if isinstance(queue_job, Mapping) else None
    if render_job is not None and render is None:
        raise _invalid("Artifact render recovery state is invalid.")
    if queue_job is not None and queue is None:
        raise _invalid("Artifact render queue recovery state is invalid.")

    artifact_id = _artifact_id(normalized_id, render, queue)
    render_status = _render_status(normalized_id, render)
    queue_status = _queue_status(normalized_id, queue)
    action, recovery_status, reason_code = _recovery_decision(
        render_status,
        queue_status,
        queue,
    )
    attempt_count, max_attempts = _attempts(queue)
    queue_error = queue.get("error") if queue is not None else None
    failure_code = (
        str(queue_error.get("error_code"))
        if isinstance(queue_error, Mapping) and queue_error.get("error_code")
        else None
    )
    dead_lettered = bool(
        queue_status == "FAILED"
        and isinstance(queue_error, Mapping)
        and queue_error.get("dead_lettered") is True
    )
    next_retry_at = (
        _optional_text(queue.get("available_at"), "available_at")
        if queue_status == "QUEUED" and queue is not None
        else None
    )
    return {
        "recovery_schema_version": AE_ASYNC_ARTIFACT_RENDER_RECOVERY_SCHEMA_VERSION,
        "render_job_id": normalized_id,
        "artifact_id": artifact_id,
        "recovery_status": recovery_status,
        "action": action,
        "reason_code": reason_code,
        "render_job_status": render_status,
        "queue_job_status": queue_status,
        "attempt_count": attempt_count,
        "max_attempts": max_attempts,
        "attempts_remaining": max(max_attempts - attempt_count, 0),
        "next_retry_at": next_retry_at,
        "failure_code": failure_code,
        "dead_lettered": dead_lettered,
        "mutation_required": action in _MUTATING_ACTIONS,
        "owner_scope_enforced": True,
        "content_included": False,
    }


def reconcile_async_artifact_render(
    *,
    render_job_id: str,
    artifact_store: AsyncArtifactRenderRecoveryStore,
    job_queue: JobQueue,
    observed_at: str | None = None,
) -> dict[str, Any]:
    before = inspect_async_artifact_render_recovery(
        render_job_id=render_job_id,
        artifact_store=artifact_store,
        job_queue=job_queue,
    )
    action = before["action"]
    if action in _MUTATING_ACTIONS:
        render_job = artifact_store.get_render_job(before["render_job_id"])
        try:
            queue_job = job_queue.get_job(before["render_job_id"])
        except JobQueueError as exc:
            raise _queue_unavailable(exc) from exc
        current = build_async_artifact_render_recovery_plan(
            render_job_id=before["render_job_id"],
            render_job=render_job,
            queue_job=queue_job,
        )
        if current["action"] == action:
            _apply_recovery_action(
                action=action,
                render_job=render_job,
                queue_job=queue_job,
                artifact_store=artifact_store,
                observed_at=observed_at or _utc_now(),
            )
            result = "RECONCILED"
        else:
            result = "ALREADY_SETTLED"
    elif action == MANUAL_REVIEW:
        result = "MANUAL_REVIEW_REQUIRED"
    elif action == REPEAT_ADMISSION:
        result = "READMISSION_REQUIRED"
    else:
        result = "NO_ACTION"
    after = inspect_async_artifact_render_recovery(
        render_job_id=render_job_id,
        artifact_store=artifact_store,
        job_queue=job_queue,
    )
    return {
        "reconciliation_schema_version": (
            AE_ASYNC_ARTIFACT_RENDER_RECONCILIATION_SCHEMA_VERSION
        ),
        "result": result,
        "applied_action": action if result == "RECONCILED" else None,
        "before": before,
        "after": after,
        "owner_scope_enforced": True,
        "content_included": False,
    }


def _apply_recovery_action(
    *,
    action: str,
    render_job: Mapping[str, Any] | None,
    queue_job: Mapping[str, Any] | None,
    artifact_store: AsyncArtifactRenderRecoveryStore,
    observed_at: str,
) -> None:
    if render_job is None or queue_job is None:
        raise _invalid("Recoverable artifact render state is incomplete.")
    updated = dict(render_job)
    if action == RESET_RENDER_TO_QUEUED:
        updated.update(
            job_status="QUEUED",
            current_stage="QUEUED",
            progress_percent=0,
            retryable=True,
            failure_code=None,
            completed_at=None,
        )
    elif action == MARK_RENDER_RUNNING:
        updated.update(
            job_status="RUNNING",
            current_stage="HANDOFF_VALIDATING",
            progress_percent=max(int(updated.get("progress_percent", 0)), 10),
            retryable=True,
            failure_code=None,
            started_at=updated.get("started_at") or observed_at,
            completed_at=None,
        )
    elif action == MARK_RENDER_CANCELLED:
        updated.update(
            job_status="CANCELLED",
            current_stage="CANCELLED",
            retryable=False,
            failure_code=None,
            completed_at=observed_at,
        )
    elif action == MARK_RENDER_FAILED:
        queue_error = queue_job.get("error")
        failure_code = (
            queue_error.get("error_code")
            if isinstance(queue_error, Mapping)
            else None
        )
        updated.update(
            job_status="FAILED",
            current_stage="FAILED",
            retryable=False,
            failure_code=_required_text(failure_code, "failure_code"),
            completed_at=observed_at,
        )
    else:
        raise _invalid("Artifact render recovery action is invalid.")
    updated["updated_at"] = observed_at
    artifact_store.save_render_job_state(updated)
    if action == MARK_RENDER_FAILED:
        artifact = artifact_store.get(str(updated["artifact_id"]))
        if artifact is not None:
            artifact_store.save(
                {
                    **artifact,
                    "artifact_status": "FAILED",
                    "updated_at": observed_at,
                }
            )


def _recovery_decision(
    render_status: str | None,
    queue_status: str | None,
    queue: Mapping[str, Any] | None,
) -> tuple[str, str, str]:
    if queue_status is None:
        return REPEAT_ADMISSION, "RECOVERY_REQUIRED", "queue_state_missing"
    if render_status is None:
        return MANUAL_REVIEW, "BLOCKED", "render_state_missing"
    expected = {
        "QUEUED": "QUEUED",
        "RUNNING": "RUNNING",
        "SUCCEEDED": "COMPLETED",
        "FAILED": "FAILED",
        "CANCELLED": "CANCELLED",
    }[queue_status]
    if render_status == expected:
        if queue_status == "QUEUED":
            retry_scheduled = isinstance(queue.get("error"), Mapping)
            return (
                (WAIT_FOR_RETRY, "RETRY_SCHEDULED", "bounded_retry_scheduled")
                if retry_scheduled
                else (WAIT_FOR_WORKER, "HEALTHY", "awaiting_worker")
            )
        if queue_status == "RUNNING":
            return WAIT_FOR_WORKER, "HEALTHY", "worker_running"
        if queue_status == "FAILED":
            return MANUAL_REVIEW, "BLOCKED", "dead_lettered"
        return NO_ACTION, "TERMINAL", f"render_{queue_status.lower()}"
    if queue_status == "QUEUED" and render_status in {"RUNNING", "FAILED"}:
        return RESET_RENDER_TO_QUEUED, "RECOVERY_REQUIRED", "retry_state_drift"
    if queue_status == "RUNNING" and render_status == "QUEUED":
        return MARK_RENDER_RUNNING, "RECOVERY_REQUIRED", "claim_state_drift"
    if queue_status == "CANCELLED" and render_status in {
        "QUEUED",
        "RUNNING",
        "FAILED",
    }:
        return MARK_RENDER_CANCELLED, "RECOVERY_REQUIRED", "cancel_state_drift"
    if queue_status == "FAILED" and render_status in {"QUEUED", "RUNNING"}:
        return MARK_RENDER_FAILED, "RECOVERY_REQUIRED", "failure_state_drift"
    return MANUAL_REVIEW, "BLOCKED", "unsafe_state_drift"


def _artifact_id(
    render_job_id: str,
    render: Mapping[str, Any] | None,
    queue: Mapping[str, Any] | None,
) -> str:
    if render is not None:
        return _required_text(render.get("artifact_id"), "artifact_id")
    if queue is not None:
        subject = queue.get("subject_ref")
        if not isinstance(subject, Mapping) or subject.get("type") != "artifact":
            raise _invalid("Artifact render queue subject is invalid.")
        return _required_text(subject.get("id"), "artifact_id")
    raise AeAsyncArtifactRenderError(
        error_code="ae.async_artifact_render.not_found",
        detail=f"Asynchronous artifact render job was not found: {render_job_id}",
        status_code=404,
    )


def _render_status(
    render_job_id: str,
    render: Mapping[str, Any] | None,
) -> str | None:
    if render is None:
        return None
    if render.get("render_job_id") != render_job_id:
        raise _invalid("Artifact render recovery lineage is invalid.")
    status = render.get("job_status")
    if status not in {"QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"}:
        raise _invalid("Artifact render recovery status is invalid.")
    return str(status)


def _queue_status(
    render_job_id: str,
    queue: Mapping[str, Any] | None,
) -> str | None:
    if queue is None:
        return None
    if (
        queue.get("job_id") != render_job_id
        or queue.get("job_type") != ASYNC_ARTIFACT_RENDER_JOB_TYPE
    ):
        raise _invalid("Artifact render queue recovery lineage is invalid.")
    status = queue.get("status")
    if status not in {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"}:
        raise _invalid("Artifact render queue recovery status is invalid.")
    return str(status)


def _attempts(queue: Mapping[str, Any] | None) -> tuple[int, int]:
    if queue is None:
        return 0, 0
    attempt_count = queue.get("attempt_count")
    max_attempts = queue.get("max_attempts")
    if (
        isinstance(attempt_count, bool)
        or not isinstance(attempt_count, int)
        or attempt_count < 0
        or isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or max_attempts < 1
        or attempt_count > max_attempts
    ):
        raise _invalid("Artifact render recovery attempt counts are invalid.")
    return attempt_count, max_attempts


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field_name} must be a non-empty string.")
    return value.strip()


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _invalid(detail: str) -> AeAsyncArtifactRenderError:
    return AeAsyncArtifactRenderError(
        error_code="ae.async_artifact_render.recovery_invalid",
        detail=detail,
        status_code=422,
    )


def _queue_unavailable(exc: JobQueueError) -> AeAsyncArtifactRenderError:
    return AeAsyncArtifactRenderError(
        error_code="ae.async_artifact_render.queue_unavailable",
        detail="Artifact render queue is unavailable.",
        status_code=503 if exc.status_code >= 500 else exc.status_code,
        retryable=exc.status_code >= 500,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
