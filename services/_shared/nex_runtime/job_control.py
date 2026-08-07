from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime.auth import DEFAULT_SERVICE_SCOPE, validate_authorization_header
from nex_runtime.jobs import (
    ACTIVE_JOB_STATUSES,
    FAILED,
    RUNNING,
    TERMINAL_JOB_STATUSES,
    JobReplayDecision,
    JobRetryPolicy,
    JobQueue,
    JobQueueError,
    build_job_error,
    plan_dead_letter_replay,
    validate_common_job,
)
from nex_runtime.problem import problem_response


SERVICE_JOB_CONTROL_SCHEMA_VERSION = "service_job_control.v1"


def register_service_job_control_routes(
    app: FastAPI,
    *,
    service_id: str,
    job_queue: JobQueue,
    expected_audience: str | None = None,
    retry_policy: JobRetryPolicy | None = None,
) -> None:
    audience = expected_audience or service_id

    @app.get("/internal/v1/jobs/{job_id}", response_model=None)
    def get_service_job(
        job_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_request(
            request,
            authorization,
            expected_audience=audience,
        )
        if auth_problem is not None:
            return auth_problem
        job = job_queue.get_job(job_id)
        if job is None:
            return _job_control_problem_response(
                request,
                JobQueueError(
                    error_code="job.not_found",
                    detail=f"job was not found: {job_id}",
                    status_code=404,
                ),
            )
        return build_service_job_control_response(
            service_id=service_id,
            action="read",
            job=job,
        )

    @app.post("/internal/v1/jobs/{job_id}/cancel", response_model=None)
    def cancel_service_job(
        job_id: str,
        request: Request,
        payload: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_request(
            request,
            authorization,
            expected_audience=audience,
        )
        if auth_problem is not None:
            return auth_problem
        try:
            cancelled = job_queue.cancel_job(job_id, updated_at=_optional_timestamp(payload))
        except JobQueueError as exc:
            return _job_control_problem_response(request, exc)
        return build_service_job_control_response(
            service_id=service_id,
            action="cancel",
            job=cancelled,
        )

    @app.post("/internal/v1/jobs/{job_id}/retry", response_model=None)
    def retry_service_job(
        job_id: str,
        request: Request,
        payload: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_request(
            request,
            authorization,
            expected_audience=audience,
        )
        if auth_problem is not None:
            return auth_problem
        try:
            retried = job_queue.retry_job(
                job_id,
                error=_manual_retry_error(payload),
                failed_at=_optional_timestamp(payload),
                policy=retry_policy,
            )
        except JobQueueError as exc:
            return _job_control_problem_response(request, exc)
        return build_service_job_control_response(
            service_id=service_id,
            action="retry",
            job=retried,
        )

    @app.post("/internal/v1/jobs/{job_id}/replay", response_model=None)
    def replay_service_job(
        job_id: str,
        request: Request,
        payload: dict[str, Any] | None = Body(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_request(
            request,
            authorization,
            expected_audience=audience,
        )
        if auth_problem is not None:
            return auth_problem
        try:
            source_job = job_queue.get_job(job_id)
            if source_job is None:
                raise JobQueueError(
                    error_code="job.not_found",
                    detail=f"job was not found: {job_id}",
                    status_code=404,
                )
            decision = plan_dead_letter_replay(
                source_job,
                replay_job_id=_required_payload_string(payload, "replay_job_id"),
                idempotency_key=_required_payload_string(payload, "idempotency_key"),
                requested_by=_required_payload_string(payload, "requested_by"),
                reason=_required_payload_string(payload, "reason"),
                replayed_at=_optional_timestamp(payload),
            )
            replay_job = job_queue.enqueue(decision.replay_job)
        except JobQueueError as exc:
            return _job_control_problem_response(request, exc)
        return build_service_job_replay_response(
            service_id=service_id,
            source_job=source_job,
            replay_job=replay_job,
            decision=decision,
        )


def build_service_job_control_response(
    *,
    service_id: str,
    action: str,
    job: dict[str, Any],
) -> dict[str, Any]:
    projected_job = project_service_job_control_job(service_id=service_id, job=job)
    return {
        "job_control_schema_version": SERVICE_JOB_CONTROL_SCHEMA_VERSION,
        "service_id": service_id,
        "action": action,
        "job": projected_job,
        "controls": build_service_job_controls(projected_job),
    }


def build_service_job_replay_response(
    *,
    service_id: str,
    source_job: dict[str, Any],
    replay_job: dict[str, Any],
    decision: JobReplayDecision,
) -> dict[str, Any]:
    response = build_service_job_control_response(
        service_id=service_id,
        action="replay",
        job=replay_job,
    )
    response["replay"] = {
        "action": decision.action,
        "source_job": _project_replay_source_job(service_id=service_id, job=source_job),
        "source_job_id": decision.source_job_id,
        "replay_job_id": replay_job["job_id"],
        "lineage": deepcopy(decision.lineage),
    }
    return response


def _project_replay_source_job(
    *,
    service_id: str,
    job: dict[str, Any],
) -> dict[str, Any]:
    projected = project_service_job_control_job(service_id=service_id, job=job)
    error = projected.get("error")
    return {
        "service_id": service_id,
        "job_id": projected["job_id"],
        "job_type": projected["job_type"],
        "status": projected["status"],
        "trace_id": projected["trace_id"],
        "request_id": projected["request_id"],
        "subject_ref": deepcopy(projected["subject_ref"]),
        "attempt_count": projected["attempt_count"],
        "max_attempts": projected["max_attempts"],
        "retryable": projected["retryable"],
        "source_error_code": (
            str(error.get("error_code"))
            if isinstance(error, dict) and error.get("error_code")
            else None
        ),
        "dead_lettered": bool(isinstance(error, dict) and error.get("dead_lettered")),
    }


def project_service_job_control_job(
    *,
    service_id: str,
    job: dict[str, Any],
) -> dict[str, Any]:
    normalized = validate_common_job(deepcopy(job))
    return {
        "service_id": service_id,
        "job_schema_version": normalized["job_schema_version"],
        "job_id": normalized["job_id"],
        "job_type": normalized["job_type"],
        "status": normalized["status"],
        "trace_id": normalized["trace_id"],
        "request_id": normalized["request_id"],
        "subject_ref": deepcopy(normalized["subject_ref"]),
        "attempt_count": normalized["attempt_count"],
        "max_attempts": normalized["max_attempts"],
        "retryable": normalized["retryable"],
        "links": deepcopy(normalized["links"]),
        "error": deepcopy(normalized.get("error")),
        "available_at": normalized.get("available_at"),
        "created_at": normalized["created_at"],
        "updated_at": normalized["updated_at"],
    }


def build_service_job_controls(job: dict[str, Any]) -> dict[str, Any]:
    status = str(job["status"])
    error = job.get("error")
    dead_lettered = bool(isinstance(error, dict) and error.get("dead_lettered"))
    can_cancel = status in ACTIVE_JOB_STATUSES
    can_retry = status == RUNNING
    can_replay = status == FAILED and dead_lettered
    return {
        "can_cancel": can_cancel,
        "can_retry": can_retry,
        "can_replay": can_replay,
        "terminal": status in TERMINAL_JOB_STATUSES,
        "dead_lettered": status == FAILED and dead_lettered,
        "allowed_actions": _allowed_actions(
            can_cancel=can_cancel,
            can_retry=can_retry,
            can_replay=can_replay,
        ),
    }


def _allowed_actions(
    *,
    can_cancel: bool,
    can_retry: bool,
    can_replay: bool,
) -> list[str]:
    actions = ["read"]
    if can_cancel:
        actions.append("cancel")
    if can_retry:
        actions.append("retry")
    if can_replay:
        actions.append("replay")
    return actions


def _manual_retry_error(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload or {}
    return build_job_error(
        error_code=str(source.get("error_code", "job.manual_retry_requested")),
        detail=str(source.get("detail", "Manual retry requested.")),
        retryable=True,
    )


def _optional_timestamp(payload: dict[str, Any] | None) -> str | None:
    if not payload or payload.get("observed_at") is None:
        return None
    observed_at = payload["observed_at"]
    if not isinstance(observed_at, str) or not observed_at:
        raise JobQueueError(
            error_code="job_control.observed_at_invalid",
            detail="observed_at must be a non-empty string when supplied.",
            status_code=422,
        )
    return observed_at


def _required_payload_string(payload: dict[str, Any] | None, key: str) -> str:
    if payload is None or key not in payload:
        raise JobQueueError(
            error_code="job_control.replay_payload_invalid",
            detail=f"{key} must be a non-empty string.",
            status_code=422,
        )
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise JobQueueError(
            error_code="job_control.replay_payload_invalid",
            detail=f"{key} must be a non-empty string.",
            status_code=422,
        )
    return value


def _authorize_request(
    request: Request,
    authorization: str | None,
    *,
    expected_audience: str,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience=expected_audience,
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None
    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or f"{expected_audience} requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _job_control_problem_response(request: Request, exc: JobQueueError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Job control request failed",
        detail=exc.detail,
        retryable=exc.status_code >= 500,
        type_uri="https://nex-platform.local/problems/job-control-request-failed",
    )
