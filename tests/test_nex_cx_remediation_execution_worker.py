from __future__ import annotations

import json
from typing import Any

import pytest

from nex_cx.generation import GenerationExecutionStore
from nex_cx.remediation_execution import (
    CX_REMEDIATION_EXECUTION_JOB_TYPE,
    RemediationExecutionStore,
    build_cx_remediation_execution_result,
    build_remediation_execution_job,
)
from nex_cx.remediation_execution_planning import (
    RUNNING,
    apply_remediation_execution_transition,
)
from nex_cx.remediation_execution_worker import (
    CX_REMEDIATION_EXECUTION_WORKER_ID,
    RemediationExecutionWorkerError,
    build_mock_repair_generation_record,
    build_remediation_execution_worker_handler,
    execute_claimed_remediation_execution_job,
    remediation_action_id_from_job,
    repair_generation_id_for_action,
    run_remediation_execution_worker_once,
)
from nex_runtime import InMemoryJobQueue, JobQueueError


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
NOW = "2026-08-26T00:00:00Z"


def remediation_request(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_schema_version": "cx_remediation_execution_request.v1",
        "remediation_action_id": "ag-remediation-action-001",
        "parent_cx_generation_id": "cx-gen-001",
        "tenant_id": "local-tenant",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "action_type": "citation_repair",
        "lineage_type": "repair",
        "reason_codes": ["citation_quality"],
        "source_refs": [
            {
                "source_service": "nex-ag",
                "ref_type": "operator_disposition",
                "ref_id": "ag-disposition-001",
                "relation": "recommended_by",
            }
        ],
        "evidence": {
            "evidence_hashes": [
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ],
            "raw_evidence_stored": False,
        },
        "execution_policy": {
            "parent_generation_mutation_allowed": False,
            "retrieval_package_policy": "reuse_or_expand_cited_evidence",
            "prompt_package_policy": "rebuild_with_citation_repair_instruction_ref",
            "provider_boundary": "cx_to_mo_service_api_only",
        },
        "idempotency_key": "cx-remediation-execution-001",
    }
    payload.update(overrides)
    return payload


def parent_generation_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_schema_version": "cx_generation_execution_record.v1",
        "cx_generation_id": "cx-gen-001",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "status": "COMPLETED",
    }
    record.update(overrides)
    return record


def accepted_execution_record(**overrides: Any) -> dict[str, Any]:
    payload = remediation_request(**overrides)
    return build_cx_remediation_execution_result(payload, created_at=NOW)


def enqueue_execution_job(
    *,
    queue: InMemoryJobQueue,
    execution_record: dict[str, Any],
    request_payload: dict[str, Any] | None = None,
    payload_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = request_payload or remediation_request()
    job = build_remediation_execution_job(
        execution_record=execution_record,
        request_payload=payload,
        created_at=NOW,
    )
    if payload_overrides:
        job["payload"].update(payload_overrides)
    return queue.enqueue(job)


def test_remediation_worker_claims_job_and_persists_mock_repair_generation() -> None:
    queue = InMemoryJobQueue()
    generation_store = GenerationExecutionStore()
    execution_store = RemediationExecutionStore()
    accepted = accepted_execution_record()
    generation_store.save(parent_generation_record())
    execution_store.save(accepted)
    enqueue_execution_job(queue=queue, execution_record=accepted)

    result = run_remediation_execution_worker_once(
        job_queue=queue,
        generation_store=generation_store,
        execution_store=execution_store,
        clock=lambda: NOW,
    )

    assert result["job_status"] == "SUCCEEDED"
    assert result["worker_id"] == CX_REMEDIATION_EXECUTION_WORKER_ID
    assert result["remediation_action_id"] == "ag-remediation-action-001"
    assert result["raw_content_included"] is False
    stored_execution = execution_store.get("ag-remediation-action-001")
    assert stored_execution is not None
    assert stored_execution["execution_status"] == "SUCCEEDED"
    assert stored_execution["result_ref"] == {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": "ag-remediation-action-001",
        "relation": "result_of",
    }
    repair_record = generation_store.get(stored_execution["repair_cx_generation_id"])
    assert repair_record is not None
    assert repair_record["status"] == "COMPLETED"
    assert repair_record["parent_cx_generation_id"] == "cx-gen-001"
    assert repair_record["source_ids"]["parent_status"] == "COMPLETED"
    assert repair_record["request_metadata"]["parent_generation_mutated"] is False
    assert generation_store.get("cx-gen-001") == parent_generation_record()
    assert queue.get_job(result["job_id"])["status"] == "SUCCEEDED"
    assert "hidden prompt" not in json.dumps(repair_record, sort_keys=True)


def test_remediation_worker_reports_idle_when_no_job_is_ready() -> None:
    result = run_remediation_execution_worker_once(
        job_queue=InMemoryJobQueue(),
        generation_store=GenerationExecutionStore(),
        execution_store=RemediationExecutionStore(),
        clock=lambda: NOW,
    )

    assert result["job_status"] == "IDLE"
    assert result["job_id"] is None
    assert result["observed_at"] == NOW


def test_remediation_worker_idle_uses_default_clock() -> None:
    result = run_remediation_execution_worker_once(
        job_queue=InMemoryJobQueue(),
        generation_store=GenerationExecutionStore(),
        execution_store=RemediationExecutionStore(),
    )

    assert result["job_status"] == "IDLE"
    assert str(result["observed_at"]).endswith("Z")


def test_remediation_worker_resumes_running_execution_and_subject_ref_fallback() -> None:
    queue = InMemoryJobQueue()
    generation_store = GenerationExecutionStore()
    execution_store = RemediationExecutionStore()
    accepted = accepted_execution_record()
    running = apply_remediation_execution_transition(
        accepted,
        RUNNING,
        observed_at=NOW,
    )
    generation_store.save(parent_generation_record())
    execution_store.save(running)
    job = build_remediation_execution_job(
        execution_record=running,
        request_payload=remediation_request(),
        created_at=NOW,
    )
    del job["payload"]["remediation_action_id"]
    queue.enqueue(job)

    result = run_remediation_execution_worker_once(
        job_queue=queue,
        generation_store=generation_store,
        execution_store=execution_store,
        clock=lambda: NOW,
    )

    assert remediation_action_id_from_job(job) == "ag-remediation-action-001"
    assert result["job_status"] == "SUCCEEDED"
    stored = execution_store.get("ag-remediation-action-001")
    assert stored["execution_status"] == "SUCCEEDED"
    assert stored["repair_cx_generation_id"] == repair_generation_id_for_action(
        "ag-remediation-action-001"
    )


def test_remediation_worker_fails_job_when_parent_generation_is_missing() -> None:
    queue = InMemoryJobQueue()
    generation_store = GenerationExecutionStore()
    execution_store = RemediationExecutionStore()
    accepted = accepted_execution_record()
    execution_store.save(accepted)
    enqueued = enqueue_execution_job(queue=queue, execution_record=accepted)

    result = run_remediation_execution_worker_once(
        job_queue=queue,
        generation_store=generation_store,
        execution_store=execution_store,
        clock=lambda: NOW,
    )

    assert result["job_id"] == enqueued["job_id"]
    assert result["job_status"] == "FAILED"
    assert result["error_code"] == (
        "cx.remediation_execution_worker.parent_generation_not_found"
    )
    stored = execution_store.get("ag-remediation-action-001")
    assert stored["execution_status"] == "FAILED"
    assert stored["failure"]["failure_class"] == "retrieval"
    assert stored["failure"]["retryable"] is False
    failed_job = queue.get_job(enqueued["job_id"])
    assert failed_job["status"] == "FAILED"
    assert failed_job["error"]["dead_lettered"] is True


def test_remediation_worker_fails_job_when_execution_record_is_missing() -> None:
    queue = InMemoryJobQueue()
    generation_store = GenerationExecutionStore()
    execution_store = RemediationExecutionStore()
    accepted = accepted_execution_record()
    generation_store.save(parent_generation_record())
    enqueued = enqueue_execution_job(queue=queue, execution_record=accepted)

    result = run_remediation_execution_worker_once(
        job_queue=queue,
        generation_store=generation_store,
        execution_store=execution_store,
        clock=lambda: NOW,
    )

    assert result["job_id"] == enqueued["job_id"]
    assert result["job_status"] == "FAILED"
    assert result["execution_record_updated"] is False
    assert result["error_code"] == (
        "cx.remediation_execution_worker.execution_record_not_found"
    )
    assert execution_store.get("ag-remediation-action-001") is None
    assert queue.get_job(enqueued["job_id"])["status"] == "FAILED"


def test_remediation_worker_fails_job_for_invalid_persisted_record_shape() -> None:
    queue = InMemoryJobQueue()
    generation_store = GenerationExecutionStore()
    execution_store = RemediationExecutionStore()
    accepted = accepted_execution_record()
    invalid_record = {**accepted, "result_schema_version": "old"}
    generation_store.save(parent_generation_record())
    execution_store.save(invalid_record)
    enqueued = enqueue_execution_job(queue=queue, execution_record=accepted)

    result = run_remediation_execution_worker_once(
        job_queue=queue,
        generation_store=generation_store,
        execution_store=execution_store,
        clock=lambda: NOW,
    )

    assert result["job_id"] == enqueued["job_id"]
    assert result["job_status"] == "FAILED"
    assert result["execution_record_updated"] is False
    assert result["error_code"] == (
        "cx.remediation_execution_worker.record_schema_invalid"
    )
    assert execution_store.get("ag-remediation-action-001") == invalid_record


def test_remediation_worker_does_not_rewrite_terminal_execution_on_failure() -> None:
    queue = InMemoryJobQueue()
    generation_store = GenerationExecutionStore()
    execution_store = RemediationExecutionStore()
    accepted = accepted_execution_record()
    terminal = {**accepted, "execution_status": "SUCCEEDED"}
    generation_store.save(parent_generation_record())
    execution_store.save(terminal)
    enqueued = enqueue_execution_job(queue=queue, execution_record=accepted)

    result = run_remediation_execution_worker_once(
        job_queue=queue,
        generation_store=generation_store,
        execution_store=execution_store,
        clock=lambda: NOW,
    )

    assert result["job_id"] == enqueued["job_id"]
    assert result["job_status"] == "FAILED"
    assert result["execution_record_updated"] is False
    assert result["error_code"] == (
        "cx.remediation_execution_worker.status_not_plannable"
    )
    assert execution_store.get("ag-remediation-action-001") == terminal


def test_remediation_worker_fails_on_parent_generation_mismatch() -> None:
    class MismatchedGenerationStore:
        def get(self, cx_generation_id: str) -> dict[str, Any] | None:
            return parent_generation_record(cx_generation_id="cx-gen-other")

        def save(
            self,
            record: dict[str, Any],
            *,
            structured_draft: dict[str, Any] | None = None,
            progress_events: list[dict[str, Any]] | None = None,
        ) -> dict[str, Any]:
            return record

    queue = InMemoryJobQueue()
    execution_store = RemediationExecutionStore()
    accepted = accepted_execution_record()
    execution_store.save(accepted)
    enqueued = enqueue_execution_job(queue=queue, execution_record=accepted)

    result = run_remediation_execution_worker_once(
        job_queue=queue,
        generation_store=MismatchedGenerationStore(),
        execution_store=execution_store,
        clock=lambda: NOW,
    )

    assert result["job_id"] == enqueued["job_id"]
    assert result["job_status"] == "FAILED"
    assert result["error_code"] == (
        "cx.remediation_execution_worker.parent_generation_mismatch"
    )
    assert execution_store.get("ag-remediation-action-001")["failure"][
        "failure_class"
    ] == "validation"


def test_remediation_worker_handler_executes_claimed_job_and_finalizes_queue() -> None:
    queue = InMemoryJobQueue()
    generation_store = GenerationExecutionStore()
    execution_store = RemediationExecutionStore()
    accepted = accepted_execution_record()
    generation_store.save(parent_generation_record())
    execution_store.save(accepted)
    enqueue_execution_job(queue=queue, execution_record=accepted)
    claimed = queue.claim_next_job(
        "worker-runner",
        job_type=CX_REMEDIATION_EXECUTION_JOB_TYPE,
        updated_at=NOW,
    )
    assert claimed is not None

    handler = build_remediation_execution_worker_handler(
        generation_store=generation_store,
        execution_store=execution_store,
        job_queue=queue,
        clock=lambda: NOW,
    )
    result = handler(claimed)

    assert result["job_status"] == "SUCCEEDED"
    assert queue.get_job(claimed["job_id"])["status"] == "SUCCEEDED"


def test_remediation_worker_raises_worker_error_when_claim_fails() -> None:
    class FailingClaimQueue:
        def claim_next_job(
            self,
            worker_id: str,
            *,
            job_type: str | None = None,
            updated_at: str | None = None,
        ) -> dict[str, Any] | None:
            raise JobQueueError(
                error_code="job.store_unavailable",
                detail="job store unavailable",
                status_code=503,
            )

    with pytest.raises(RemediationExecutionWorkerError) as exc_info:
        run_remediation_execution_worker_once(
            job_queue=FailingClaimQueue(),
            generation_store=GenerationExecutionStore(),
            execution_store=RemediationExecutionStore(),
            clock=lambda: NOW,
        )

    assert exc_info.value.error_code == "cx.remediation_execution_worker.claim_failed"
    assert exc_info.value.retryable is True
    assert str(exc_info.value) == "job store unavailable"


def test_remediation_worker_validates_ids_and_job_payload_edges() -> None:
    accepted = accepted_execution_record()
    parent = parent_generation_record()
    repair_id = repair_generation_id_for_action("ag-remediation-action-001")

    assert repair_id == repair_generation_id_for_action("ag-remediation-action-001")
    with pytest.raises(RemediationExecutionWorkerError):
        repair_generation_id_for_action(" ")

    direct_child = build_mock_repair_generation_record(
        parent_generation=parent,
        execution_record=accepted,
        repair_cx_generation_id=repair_id,
        created_at=NOW,
    )
    assert direct_child["cx_generation_id"] == repair_id

    with pytest.raises(RemediationExecutionWorkerError) as mutation_error:
        build_mock_repair_generation_record(
            parent_generation=parent,
            execution_record=accepted,
            repair_cx_generation_id="cx-gen-001",
            created_at=NOW,
        )
    assert mutation_error.value.error_code == (
        "cx.remediation_execution_worker.parent_mutation_forbidden"
    )


def test_remediation_worker_fails_claimed_job_with_missing_action_id() -> None:
    class FinalizingQueue:
        def retry_job(
            self,
            job_id: str,
            *,
            error: dict[str, Any] | None = None,
            failed_at: str | None = None,
            policy: object | None = None,
        ) -> dict[str, Any]:
            return {
                "job_id": job_id,
                "job_type": CX_REMEDIATION_EXECUTION_JOB_TYPE,
                "status": "FAILED",
                "error": error,
            }

        def fail_job(
            self,
            job_id: str,
            *,
            updated_at: str | None = None,
        ) -> dict[str, Any]:
            return {
                "job_id": job_id,
                "job_type": CX_REMEDIATION_EXECUTION_JOB_TYPE,
                "status": "FAILED",
            }

    job = {
        "job_id": "job-001",
        "job_type": CX_REMEDIATION_EXECUTION_JOB_TYPE,
        "status": "RUNNING",
        "subject_ref": {"type": "other", "id": "other-001"},
    }

    result = execute_claimed_remediation_execution_job(
        job,
        job_queue=FinalizingQueue(),
        generation_store=GenerationExecutionStore(),
        execution_store=RemediationExecutionStore(),
        observed_at=NOW,
    )

    assert result["job_status"] == "FAILED"
    assert result["remediation_action_id"] is None
    assert result["error_code"] == (
        "cx.remediation_execution_worker.job_action_id_required"
    )


def test_remediation_worker_failed_job_falls_back_when_retry_fails() -> None:
    class RetryFailingQueue:
        def retry_job(
            self,
            job_id: str,
            *,
            error: dict[str, Any] | None = None,
            failed_at: str | None = None,
            policy: object | None = None,
        ) -> dict[str, Any]:
            raise JobQueueError(
                error_code="job.retry_unavailable",
                detail="retry unavailable",
                status_code=503,
            )

        def fail_job(
            self,
            job_id: str,
            *,
            updated_at: str | None = None,
        ) -> dict[str, Any]:
            return {
                "job_id": job_id,
                "job_type": CX_REMEDIATION_EXECUTION_JOB_TYPE,
                "status": "FAILED",
                "updated_at": updated_at,
            }

    result = execute_claimed_remediation_execution_job(
        {
            "job_id": "job-002",
            "job_type": CX_REMEDIATION_EXECUTION_JOB_TYPE,
            "status": "RUNNING",
            "subject_ref": {"type": "other", "id": "other-001"},
        },
        job_queue=RetryFailingQueue(),
        generation_store=GenerationExecutionStore(),
        execution_store=RemediationExecutionStore(),
        observed_at=NOW,
    )

    assert result["job_id"] == "job-002"
    assert result["job_status"] == "FAILED"
    assert result["observed_at"] == NOW
