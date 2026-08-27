from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nex_ag.generation_remediation_execution import (
    GenerationRemediationExecutionError,
    GenerationRemediationTaskExecutionStore,
    sync_generation_remediation_execution_status,
)
from nex_ag.generation_remediation_handoff import CxRemediationExecutionStatusClient
from nex_ag.remediation_execution_status_sync_jobs import (
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_PAYLOAD_SCHEMA_VERSION,
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE,
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_READY_STATES,
    RemediationExecutionStatusSyncJobPlanningError,
    assert_remediation_execution_status_sync_job_redaction_safe,
)
from nex_runtime import (
    JobQueue,
    ServiceLogEmitter,
    WorkerBatchResult,
    WorkerHeartbeatEmitter,
    WorkerJobExecution,
    WorkerRunnerConfig,
    run_worker_batch,
    run_worker_once,
)


AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_TYPE = (
    "ag.remediation_execution.status_sync.worker"
)
AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_RESULT_SCHEMA_VERSION = (
    "ag_remediation_execution_status_sync_worker_result.v1"
)
AG_REMEDIATION_EXECUTION_STATUS_SYNC_DEFAULT_WORKER_ID = (
    "ag-remediation-execution-status-sync-worker-001"
)


@dataclass(frozen=True)
class RemediationExecutionStatusSyncWorkerError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def build_remediation_execution_status_sync_worker_config(
    *,
    worker_id: str = AG_REMEDIATION_EXECUTION_STATUS_SYNC_DEFAULT_WORKER_ID,
    max_jobs: int = 1,
) -> WorkerRunnerConfig:
    return WorkerRunnerConfig(
        service_id="nex-ag",
        worker_id=_required_text({"worker_id": worker_id}, "worker_id"),
        worker_type=AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_TYPE,
        job_type=AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE,
        max_jobs=max_jobs,
    )


def run_remediation_execution_status_sync_job(
    job: Mapping[str, Any],
    *,
    store: GenerationRemediationTaskExecutionStore,
    cx_status_client: CxRemediationExecutionStatusClient,
    observed_at: str | None = None,
) -> dict[str, Any]:
    normalized_job = _validate_status_sync_job(job)
    payload = normalized_job["payload"]
    try:
        sync = sync_generation_remediation_execution_status(
            store=store,
            cx_status_client=cx_status_client,
            remediation_action_id=payload["remediation_action_id"],
            cx_generation_id=payload["cx_generation_id"],
            request_id=payload["request_id"],
            trace_id=payload["trace_id"],
            observed_at=observed_at or payload.get("requested_at") or _utc_now(),
        )
    except GenerationRemediationExecutionError as exc:
        raise RemediationExecutionStatusSyncWorkerError(
            status_code=exc.status_code,
            error_code=exc.error_code,
            detail=exc.detail,
            retryable=exc.retryable,
        ) from exc

    return _worker_result(normalized_job, sync)


def run_remediation_execution_status_sync_worker_once(
    *,
    queue: JobQueue,
    store: GenerationRemediationTaskExecutionStore,
    cx_status_client: CxRemediationExecutionStatusClient,
    heartbeat_emitter: WorkerHeartbeatEmitter,
    service_log_emitter: ServiceLogEmitter | None = None,
    worker_id: str = AG_REMEDIATION_EXECUTION_STATUS_SYNC_DEFAULT_WORKER_ID,
    clock=None,
) -> WorkerJobExecution:
    return run_worker_once(
        config=build_remediation_execution_status_sync_worker_config(
            worker_id=worker_id
        ),
        queue=queue,
        heartbeat_emitter=heartbeat_emitter,
        service_log_emitter=service_log_emitter,
        handler=lambda job: run_remediation_execution_status_sync_job(
            job,
            store=store,
            cx_status_client=cx_status_client,
        ),
        clock=clock,
    )


def run_remediation_execution_status_sync_worker_batch(
    *,
    queue: JobQueue,
    store: GenerationRemediationTaskExecutionStore,
    cx_status_client: CxRemediationExecutionStatusClient,
    heartbeat_emitter: WorkerHeartbeatEmitter,
    service_log_emitter: ServiceLogEmitter | None = None,
    worker_id: str = AG_REMEDIATION_EXECUTION_STATUS_SYNC_DEFAULT_WORKER_ID,
    max_jobs: int = 1,
    stop_on_failure: bool = True,
    clock=None,
) -> WorkerBatchResult:
    return run_worker_batch(
        config=build_remediation_execution_status_sync_worker_config(
            worker_id=worker_id,
            max_jobs=max_jobs,
        ),
        queue=queue,
        heartbeat_emitter=heartbeat_emitter,
        service_log_emitter=service_log_emitter,
        handler=lambda job: run_remediation_execution_status_sync_job(
            job,
            store=store,
            cx_status_client=cx_status_client,
        ),
        stop_on_failure=stop_on_failure,
        clock=clock,
    )


def _validate_status_sync_job(job: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(job, Mapping):
        raise RemediationExecutionStatusSyncWorkerError(
            status_code=422,
            error_code="ag.remediation_execution_status_sync_worker.job_invalid",
            detail="Status sync worker requires a common job object.",
        )
    if job.get("job_type") != AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE:
        raise RemediationExecutionStatusSyncWorkerError(
            status_code=422,
            error_code="ag.remediation_execution_status_sync_worker.job_type_invalid",
            detail="Status sync worker can run only AG status sync jobs.",
        )
    payload = job.get("payload")
    if not isinstance(payload, Mapping):
        raise RemediationExecutionStatusSyncWorkerError(
            status_code=422,
            error_code="ag.remediation_execution_status_sync_worker.payload_invalid",
            detail="Status sync worker job payload must be an object.",
        )
    if (
        payload.get("payload_schema_version")
        != AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_PAYLOAD_SCHEMA_VERSION
    ):
        raise RemediationExecutionStatusSyncWorkerError(
            status_code=422,
            error_code=(
                "ag.remediation_execution_status_sync_worker."
                "payload_schema_invalid"
            ),
            detail="Status sync worker job payload schema version is invalid.",
        )

    try:
        assert_remediation_execution_status_sync_job_redaction_safe(job)
    except RemediationExecutionStatusSyncJobPlanningError as exc:
        raise RemediationExecutionStatusSyncWorkerError(
            status_code=exc.status_code,
            error_code="ag.remediation_execution_status_sync_worker.sensitive_payload",
            detail=exc.detail,
        ) from exc

    normalized_payload = {
        "remediation_action_id": _required_text(payload, "remediation_action_id"),
        "cx_generation_id": _required_text(payload, "cx_generation_id"),
        "trace_id": _required_text(payload, "trace_id"),
        "request_id": _required_text(payload, "request_id"),
        "requested_at": _optional_text(payload.get("requested_at")),
        "status_sync_state": _required_text(payload, "status_sync_state"),
        "task_status": _optional_text(payload.get("task_status")),
        "execution_status": _optional_text(payload.get("execution_status")),
        "target_task_status": _optional_text(payload.get("target_task_status")),
    }
    if (
        normalized_payload["status_sync_state"]
        not in AG_REMEDIATION_EXECUTION_STATUS_SYNC_READY_STATES
    ):
        raise RemediationExecutionStatusSyncWorkerError(
            status_code=409,
            error_code="ag.remediation_execution_status_sync_worker.state_not_ready",
            detail="Status sync worker can run only SYNC_REQUIRED payloads.",
        )

    job_trace_id = _required_text(job, "trace_id")
    job_request_id = _required_text(job, "request_id")
    if (
        normalized_payload["trace_id"] != job_trace_id
        or normalized_payload["request_id"] != job_request_id
    ):
        raise RemediationExecutionStatusSyncWorkerError(
            status_code=409,
            error_code=(
                "ag.remediation_execution_status_sync_worker."
                "correlation_mismatch"
            ),
            detail="Status sync worker job correlation does not match payload.",
        )

    subject_ref = job.get("subject_ref")
    if not isinstance(subject_ref, Mapping):
        raise RemediationExecutionStatusSyncWorkerError(
            status_code=422,
            error_code="ag.remediation_execution_status_sync_worker.subject_invalid",
            detail="Status sync worker job subject_ref must be an object.",
        )
    if _optional_text(subject_ref.get("id")) != normalized_payload["remediation_action_id"]:
        raise RemediationExecutionStatusSyncWorkerError(
            status_code=409,
            error_code="ag.remediation_execution_status_sync_worker.subject_mismatch",
            detail="Status sync worker job subject does not match payload.",
        )

    normalized_job = deepcopy(dict(job))
    normalized_job["payload"] = normalized_payload
    return normalized_job


def _worker_result(job: Mapping[str, Any], sync: Mapping[str, Any]) -> dict[str, Any]:
    payload = job["payload"]
    return {
        "worker_result_schema_version": (
            AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_RESULT_SCHEMA_VERSION
        ),
        "job_id": job["job_id"],
        "job_type": job["job_type"],
        "remediation_action_id": payload["remediation_action_id"],
        "cx_generation_id": payload["cx_generation_id"],
        "trace_id": payload["trace_id"],
        "request_id": payload["request_id"],
        "sync_status": sync["sync_status"],
        "cx_execution_status": sync["cx_execution_status"],
        "previous_action_status": sync["previous_action_status"],
        "final_action_status": sync["final_action_status"],
        "status_update_count": sync["status_update_count"],
        "result_ref": deepcopy(sync["result_ref"]),
        "debug_paths": {
            "ag_remediation_task_path": job.get("links", {}).get(
                "ag_remediation_task"
            ),
            "cx_remediation_execution_path": job.get("links", {}).get(
                "cx_remediation_execution"
            ),
        },
        "redaction_summary": {
            "task_snapshot_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
            "raw_evidence_included": False,
            "provider_detail_included": False,
        },
    }


def _required_text(source: Mapping[str, Any], field_name: str) -> str:
    value = _optional_text(source.get(field_name))
    if value is None:
        raise RemediationExecutionStatusSyncWorkerError(
            status_code=422,
            error_code=(
                "ag.remediation_execution_status_sync_worker."
                f"{field_name}_required"
            ),
            detail=f"Status sync worker requires {field_name}.",
        )
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
