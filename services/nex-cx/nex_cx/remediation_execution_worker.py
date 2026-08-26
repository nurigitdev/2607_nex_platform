from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Protocol
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import (
    InMemoryWorkerHeartbeatStore,
    JobQueue,
    JobQueueError,
    ServiceLogEmitter,
    WorkerBatchResult,
    WorkerHeartbeatEmitter,
    WorkerJobExecution,
    WorkerRunnerConfig,
    build_job_error,
    run_worker_batch,
    run_worker_once,
)
from nex_cx.remediation_execution import (
    CX_REMEDIATION_EXECUTION_JOB_TYPE,
    RemediationExecutionStoreProtocol,
    optional_text,
)
from nex_cx.remediation_execution_boundary import (
    assert_cx_remediation_execution_payload_redaction_safe,
)
from nex_cx.remediation_execution_planning import (
    ACCEPTED,
    FAILED,
    RUNNING,
    SUCCEEDED,
    RemediationExecutionPlanningError,
    apply_remediation_execution_transition,
    validate_remediation_execution_record_for_worker,
)


CX_REMEDIATION_EXECUTION_WORKER_ID = "cx-remediation-execution-worker"
CX_REMEDIATION_EXECUTION_WORKER_TYPE = "cx.remediation_execution.worker"
CX_REMEDIATION_MOCK_GENERATION_SCHEMA_VERSION = "cx_remediation_mock_generation.v1"


class GenerationRecordStore(Protocol):
    def get(self, cx_generation_id: str) -> dict[str, Any] | None:
        ...

    def save(
        self,
        record: dict[str, Any],
        *,
        structured_draft: dict[str, Any] | None = None,
        progress_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        ...


WorkerClock = Callable[[], str]


@dataclass(frozen=True)
class RemediationExecutionWorkerError(Exception):
    error_code: str
    detail: str
    status_code: int = 500
    retryable: bool = True
    failure_class: str = "dependency"

    def __str__(self) -> str:
        return self.detail


def run_remediation_execution_worker_once(
    *,
    job_queue: JobQueue,
    generation_store: GenerationRecordStore,
    execution_store: RemediationExecutionStoreProtocol,
    worker_id: str = CX_REMEDIATION_EXECUTION_WORKER_ID,
    clock: WorkerClock | None = None,
) -> dict[str, Any]:
    observed_clock = clock or _utc_now
    observed_at = observed_clock()
    try:
        job = job_queue.claim_next_job(
            worker_id,
            job_type=CX_REMEDIATION_EXECUTION_JOB_TYPE,
            updated_at=observed_at,
        )
    except JobQueueError as exc:
        raise RemediationExecutionWorkerError(
            error_code="cx.remediation_execution_worker.claim_failed",
            detail=exc.detail,
            status_code=exc.status_code,
            retryable=exc.status_code >= 500,
            failure_class="dependency",
        ) from exc

    if job is None:
        return {
            "worker_result_schema_version": "cx_remediation_execution_worker_result.v1",
            "worker_id": worker_id,
            "worker_type": CX_REMEDIATION_EXECUTION_WORKER_TYPE,
            "job_status": "IDLE",
            "job_id": None,
            "remediation_action_id": None,
            "observed_at": observed_at,
        }

    return execute_claimed_remediation_execution_job(
        job,
        job_queue=job_queue,
        generation_store=generation_store,
        execution_store=execution_store,
        observed_at=observed_clock(),
    )


def execute_claimed_remediation_execution_job(
    job: Mapping[str, Any],
    *,
    job_queue: JobQueue,
    generation_store: GenerationRecordStore,
    execution_store: RemediationExecutionStoreProtocol,
    observed_at: str | None = None,
) -> dict[str, Any]:
    observed = observed_at or _utc_now()
    normalized_job = dict(job)
    try:
        action_id = remediation_action_id_from_job(normalized_job)
    except RemediationExecutionWorkerError as exc:
        failed_job = _finish_job_failed(
            job_queue,
            normalized_job,
            worker_error=exc,
            observed_at=observed,
        )
        return _worker_failure_result(
            job=failed_job,
            remediation_action_id=None,
            worker_error=exc,
            execution_record_updated=False,
            observed_at=observed,
        )

    execution_record = execution_store.get(action_id)
    if execution_record is None:
        worker_error = RemediationExecutionWorkerError(
            error_code="cx.remediation_execution_worker.execution_record_not_found",
            detail=f"CX remediation execution record was not found: {action_id}",
            status_code=404,
            retryable=False,
            failure_class="validation",
        )
        failed_job = _finish_job_failed(
            job_queue,
            normalized_job,
            worker_error=worker_error,
            observed_at=observed,
        )
        return _worker_failure_result(
            job=failed_job,
            remediation_action_id=action_id,
            worker_error=worker_error,
            execution_record_updated=False,
            observed_at=observed,
        )

    try:
        running_record = _ensure_execution_running(
            execution_store,
            execution_record,
            observed_at=observed,
        )
        parent_generation = _parent_generation_record(generation_store, running_record)
        repair_generation_id = repair_generation_id_for_action(action_id)
        repair_generation = build_mock_repair_generation_record(
            parent_generation=parent_generation,
            execution_record=running_record,
            repair_cx_generation_id=repair_generation_id,
            created_at=observed,
        )
        generation_store.save(repair_generation)
        succeeded_record = apply_remediation_execution_transition(
            running_record,
            SUCCEEDED,
            observed_at=observed,
            repair_cx_generation_id=repair_generation_id,
            result_ref=_repair_result_ref(action_id),
        )
        execution_store.save(succeeded_record)
        completed_job = job_queue.complete_job(
            str(normalized_job["job_id"]),
            updated_at=observed,
        )
        return _worker_success_result(
            job=completed_job,
            execution_record=succeeded_record,
            repair_generation=repair_generation,
            observed_at=observed,
        )
    except (RemediationExecutionPlanningError, RemediationExecutionWorkerError) as caught:
        exc = _worker_error_from_exception(caught)
        failed_record = _fail_execution_record(
            execution_store,
            execution_record,
            worker_error=exc,
            observed_at=observed,
        )
        failed_job = _finish_job_failed(
            job_queue,
            normalized_job,
            worker_error=exc,
            observed_at=observed,
        )
        return _worker_failure_result(
            job=failed_job,
            remediation_action_id=action_id,
            worker_error=exc,
            execution_record_updated=failed_record is not None,
            observed_at=observed,
        )


def build_remediation_execution_worker_handler(
    *,
    generation_store: GenerationRecordStore,
    execution_store: RemediationExecutionStoreProtocol,
    job_queue: JobQueue,
    clock: WorkerClock | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def handler(job: dict[str, Any]) -> dict[str, Any]:
        return execute_claimed_remediation_execution_job(
            job,
            job_queue=job_queue,
            generation_store=generation_store,
            execution_store=execution_store,
            observed_at=(clock or _utc_now)(),
        )

    return handler


def build_remediation_execution_worker_config(
    *,
    worker_id: str = CX_REMEDIATION_EXECUTION_WORKER_ID,
    max_jobs: int = 1,
) -> WorkerRunnerConfig:
    return WorkerRunnerConfig(
        service_id="nex-cx",
        worker_id=worker_id,
        worker_type=CX_REMEDIATION_EXECUTION_WORKER_TYPE,
        job_type=CX_REMEDIATION_EXECUTION_JOB_TYPE,
        max_jobs=max_jobs,
    )


def run_cx_remediation_execution_worker_once(
    *,
    job_queue: JobQueue,
    generation_store: GenerationRecordStore,
    execution_store: RemediationExecutionStoreProtocol,
    worker_id: str = CX_REMEDIATION_EXECUTION_WORKER_ID,
    worker_heartbeat_emitter: WorkerHeartbeatEmitter | None = None,
    service_log_emitter: ServiceLogEmitter | None = None,
    clock: WorkerClock | None = None,
) -> WorkerJobExecution:
    heartbeat_emitter = worker_heartbeat_emitter or _default_worker_heartbeat_emitter(
        worker_id=worker_id,
    )
    return run_worker_once(
        config=build_remediation_execution_worker_config(worker_id=worker_id),
        queue=job_queue,
        heartbeat_emitter=heartbeat_emitter,
        handler=build_remediation_execution_worker_handler(
            generation_store=generation_store,
            execution_store=execution_store,
            job_queue=job_queue,
            clock=clock,
        ),
        service_log_emitter=service_log_emitter,
        handler_finalizes_job=True,
        clock=clock,
    )


def run_cx_remediation_execution_worker_batch(
    *,
    job_queue: JobQueue,
    generation_store: GenerationRecordStore,
    execution_store: RemediationExecutionStoreProtocol,
    worker_id: str = CX_REMEDIATION_EXECUTION_WORKER_ID,
    max_jobs: int = 10,
    stop_on_failure: bool = True,
    worker_heartbeat_emitter: WorkerHeartbeatEmitter | None = None,
    service_log_emitter: ServiceLogEmitter | None = None,
    clock: WorkerClock | None = None,
) -> WorkerBatchResult:
    heartbeat_emitter = worker_heartbeat_emitter or _default_worker_heartbeat_emitter(
        worker_id=worker_id,
    )
    return run_worker_batch(
        config=build_remediation_execution_worker_config(
            worker_id=worker_id,
            max_jobs=max_jobs,
        ),
        queue=job_queue,
        heartbeat_emitter=heartbeat_emitter,
        handler=build_remediation_execution_worker_handler(
            generation_store=generation_store,
            execution_store=execution_store,
            job_queue=job_queue,
            clock=clock,
        ),
        service_log_emitter=service_log_emitter,
        handler_finalizes_job=True,
        stop_on_failure=stop_on_failure,
        clock=clock,
    )


def remediation_action_id_from_job(job: Mapping[str, Any]) -> str:
    payload = _mapping(job.get("payload"))
    payload_action_id = optional_text(payload.get("remediation_action_id"))
    if payload_action_id is not None:
        return payload_action_id
    subject_ref = _mapping(job.get("subject_ref"))
    subject_type = optional_text(subject_ref.get("type"))
    subject_id = optional_text(subject_ref.get("id"))
    if subject_type == "cx.remediation_execution" and subject_id is not None:
        return subject_id
    raise RemediationExecutionWorkerError(
        error_code="cx.remediation_execution_worker.job_action_id_required",
        detail="CX remediation execution worker job requires remediation_action_id.",
        status_code=422,
        retryable=False,
        failure_class="validation",
    )


def repair_generation_id_for_action(remediation_action_id: str) -> str:
    action_id = optional_text(remediation_action_id)
    if action_id is None:
        raise RemediationExecutionWorkerError(
            error_code="cx.remediation_execution_worker.action_id_required",
            detail="CX remediation execution worker requires remediation_action_id.",
            status_code=422,
            retryable=False,
            failure_class="validation",
        )
    return str(uuid5(NAMESPACE_URL, f"cx-remediation-repair-generation:{action_id}"))


def build_mock_repair_generation_record(
    *,
    parent_generation: Mapping[str, Any],
    execution_record: Mapping[str, Any],
    repair_cx_generation_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    normalized = validate_remediation_execution_record_for_worker(execution_record)
    parent_id = str(normalized["parent_cx_generation_id"])
    parent_record = dict(parent_generation)
    if optional_text(parent_record.get("cx_generation_id")) != parent_id:
        raise RemediationExecutionWorkerError(
            error_code="cx.remediation_execution_worker.parent_generation_mismatch",
            detail="Parent generation record does not match remediation execution.",
            status_code=409,
            retryable=False,
            failure_class="validation",
        )
    observed = created_at or _utc_now()
    action_id = normalized["remediation_action_id"]
    repair_id = repair_cx_generation_id or repair_generation_id_for_action(action_id)
    if repair_id == parent_id:
        raise RemediationExecutionWorkerError(
            error_code="cx.remediation_execution_worker.parent_mutation_forbidden",
            detail="Repair generation id cannot equal the parent generation id.",
            status_code=409,
            retryable=False,
            failure_class="validation",
        )
    child_record = {
        "record_schema_version": "cx_generation_execution_record.v1",
        "mock_generation_schema_version": CX_REMEDIATION_MOCK_GENERATION_SCHEMA_VERSION,
        "cx_generation_id": repair_id,
        "parent_cx_generation_id": parent_id,
        "root_cx_generation_id": (
            optional_text(normalized.get("root_cx_generation_id")) or parent_id
        ),
        "remediation_action_id": action_id,
        "action_type": normalized["action_type"],
        "lineage_type": normalized["lineage_type"],
        "status": "COMPLETED",
        "trace_id": normalized["trace_id"],
        "request_id": normalized["request_id"],
        "tenant_id": normalized.get("tenant_id"),
        "source": "cx_remediation_execution_worker_mock",
        "source_ids": {
            "parent_cx_generation_id": parent_id,
            "remediation_action_id": action_id,
            "parent_status": parent_record.get("status"),
        },
        "request_metadata": {
            "parent_generation_mutated": False,
            "worker_mode": "mock",
            "provider_boundary": "cx_to_mo_service_api_only",
            "raw_prompt_stored": False,
            "raw_generation_output_stored": False,
            "raw_source_document_text_stored": False,
            "raw_evidence_stored": False,
        },
        "response_metadata": {
            "finish_reason": "mock_succeeded",
            "output_hash": repair_generation_id_for_action(action_id),
            "output_preview": None,
        },
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
        "created_at": observed,
        "updated_at": observed,
    }
    assert_cx_remediation_execution_payload_redaction_safe(child_record)
    return child_record


def _ensure_execution_running(
    execution_store: RemediationExecutionStoreProtocol,
    execution_record: Mapping[str, Any],
    *,
    observed_at: str,
) -> dict[str, Any]:
    normalized = validate_remediation_execution_record_for_worker(
        execution_record,
        require_plannable=True,
    )
    if normalized["execution_status"] == ACCEPTED:
        running = apply_remediation_execution_transition(
            normalized,
            RUNNING,
            observed_at=observed_at,
        )
        return execution_store.save(running)
    return normalized


def _parent_generation_record(
    generation_store: GenerationRecordStore,
    execution_record: Mapping[str, Any],
) -> dict[str, Any]:
    parent_id = str(execution_record["parent_cx_generation_id"])
    parent_generation = generation_store.get(parent_id)
    if parent_generation is None:
        raise RemediationExecutionWorkerError(
            error_code="cx.remediation_execution_worker.parent_generation_not_found",
            detail=f"Parent CX generation record was not found: {parent_id}",
            status_code=404,
            retryable=False,
            failure_class="retrieval",
        )
    return parent_generation


def _fail_execution_record(
    execution_store: RemediationExecutionStoreProtocol,
    execution_record: Mapping[str, Any],
    *,
    worker_error: RemediationExecutionWorkerError,
    observed_at: str,
) -> dict[str, Any] | None:
    try:
        normalized = validate_remediation_execution_record_for_worker(execution_record)
        if normalized["execution_status"] == ACCEPTED:
            normalized = execution_store.save(
                apply_remediation_execution_transition(
                    normalized,
                    RUNNING,
                    observed_at=observed_at,
                )
            )
        if normalized["execution_status"] != RUNNING:
            return None
        failed = apply_remediation_execution_transition(
            normalized,
            FAILED,
            observed_at=observed_at,
            failure=_safe_failure_payload(worker_error),
        )
        return execution_store.save(failed)
    except (RemediationExecutionPlanningError, RemediationExecutionWorkerError):
        return None


def _finish_job_failed(
    job_queue: JobQueue,
    job: Mapping[str, Any],
    *,
    worker_error: RemediationExecutionWorkerError,
    observed_at: str,
) -> dict[str, Any]:
    job_id = str(job["job_id"])
    error = build_job_error(
        error_code=worker_error.error_code,
        detail=worker_error.detail,
        retryable=worker_error.retryable,
    )
    try:
        return job_queue.retry_job(job_id, error=error, failed_at=observed_at)
    except JobQueueError:
        return job_queue.fail_job(job_id, updated_at=observed_at)


def _safe_failure_payload(error: RemediationExecutionWorkerError) -> dict[str, Any]:
    failure = {
        "failure_code": error.error_code,
        "failure_class": error.failure_class,
        "retryable": error.retryable,
        "safe_message": error.detail,
    }
    assert_cx_remediation_execution_payload_redaction_safe(failure)
    return failure


def _repair_result_ref(remediation_action_id: str) -> dict[str, str]:
    return {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": remediation_action_id,
        "relation": "result_of",
    }


def _worker_success_result(
    *,
    job: Mapping[str, Any],
    execution_record: Mapping[str, Any],
    repair_generation: Mapping[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    return {
        "worker_result_schema_version": "cx_remediation_execution_worker_result.v1",
        "worker_id": CX_REMEDIATION_EXECUTION_WORKER_ID,
        "worker_type": CX_REMEDIATION_EXECUTION_WORKER_TYPE,
        "job_status": job["status"],
        "job_id": job["job_id"],
        "remediation_action_id": execution_record["remediation_action_id"],
        "parent_cx_generation_id": execution_record["parent_cx_generation_id"],
        "repair_cx_generation_id": repair_generation["cx_generation_id"],
        "execution_status": execution_record["execution_status"],
        "result_ref": deepcopy(execution_record.get("result_ref")),
        "raw_content_included": False,
        "observed_at": observed_at,
    }


def _worker_failure_result(
    *,
    job: Mapping[str, Any],
    remediation_action_id: str | None,
    worker_error: RemediationExecutionWorkerError,
    execution_record_updated: bool,
    observed_at: str,
) -> dict[str, Any]:
    return {
        "worker_result_schema_version": "cx_remediation_execution_worker_result.v1",
        "worker_id": CX_REMEDIATION_EXECUTION_WORKER_ID,
        "worker_type": CX_REMEDIATION_EXECUTION_WORKER_TYPE,
        "job_status": job["status"],
        "job_id": job["job_id"],
        "remediation_action_id": remediation_action_id,
        "execution_status": FAILED if execution_record_updated else None,
        "error_code": worker_error.error_code,
        "retryable": worker_error.retryable,
        "execution_record_updated": execution_record_updated,
        "raw_content_included": False,
        "observed_at": observed_at,
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _default_worker_heartbeat_emitter(
    *,
    worker_id: str,
) -> WorkerHeartbeatEmitter:
    return WorkerHeartbeatEmitter(
        service_id="nex-cx",
        worker_id=worker_id,
        worker_type=CX_REMEDIATION_EXECUTION_WORKER_TYPE,
        store=InMemoryWorkerHeartbeatStore(),
        metadata={
            "queue": CX_REMEDIATION_EXECUTION_JOB_TYPE,
            "runtime": "background",
        },
    )


def _worker_error_from_exception(
    exc: RemediationExecutionPlanningError | RemediationExecutionWorkerError,
) -> RemediationExecutionWorkerError:
    if isinstance(exc, RemediationExecutionWorkerError):
        return exc
    return RemediationExecutionWorkerError(
        error_code=exc.error_code,
        detail=exc.detail,
        status_code=exc.status_code,
        retryable=exc.retryable,
        failure_class="validation",
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
