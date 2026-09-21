from __future__ import annotations

from dataclasses import dataclass

import pytest

from nex_runtime import (
    InMemoryJobQueue,
    JobQueueError,
    build_common_job,
    build_subject_ref,
)
from nex_cx.ingestion_coordinator import IngestionStepResult
from nex_cx.ingestion_orchestration import (
    INGESTION_PIPELINE_STEPS,
    IngestionOrchestrationPolicy,
    build_ingestion_run,
    claim_ingestion_run,
)
from nex_cx.ingestion_orchestration_repository import (
    InMemoryIngestionRunRepository,
    IngestionRunRepositoryError,
)
from nex_cx.ingestion_worker import (
    CX_INGESTION_JOB_TYPE,
    IngestionWorkerError,
    IngestionWorkerPolicy,
    _dependency_error,
    _timestamp,
    execute_claimed_ingestion_job,
    recover_expired_ingestion_job,
    run_ingestion_worker_once,
)


NOW = "2026-09-21T00:00:00Z"
RETRY_READY = "2026-09-21T00:00:31Z"


def queue_and_repository(*, max_attempts: int = 3):
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    job = queue.enqueue(
        build_common_job(
            job_id="job-1",
            job_type=CX_INGESTION_JOB_TYPE,
            trace_id="trace-1",
            request_id="request-1",
            subject_ref=build_subject_ref("cx.document", "document-1"),
            idempotency_key="upload-1",
            max_attempts=max_attempts,
            retryable=True,
            links={"document": "/api/v1/documents/document-1"},
            created_at=NOW,
        )
    )
    run = repository.create(
        build_ingestion_run(
            document_id="document-1",
            job_id="job-1",
            idempotency_key="upload-1",
            tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
            owner_subject_ref={"type": "oa.user", "id": "user-a"},
            trace_id="trace-1",
            request_id="request-1",
            created_at=NOW,
            policy=IngestionOrchestrationPolicy(max_attempts=max_attempts),
        )
    )
    return queue, repository, job, run


def successful_handlers():
    return {
        step_id: (
            lambda run, selected=step_id: IngestionStepResult(
                output_ref=f"cx.{selected}:{run['document_id']}"
            )
        )
        for step_id in INGESTION_PIPELINE_STEPS
    }


@dataclass(frozen=True)
class StepFailure(Exception):
    error_code: str = "provider.timeout"
    detail: str = "provider timeout"
    retryable: bool = True
    status_code: int = 503


def failing_handlers(*, retryable: bool = True):
    def fail(_run):
        raise StepFailure(retryable=retryable)

    return {"extraction": fail}


def test_worker_completes_job_and_all_durable_checkpoints() -> None:
    queue, repository, _, _ = queue_and_repository()
    result = run_ingestion_worker_once(
        job_queue=queue,
        run_repository=repository,
        step_handlers=successful_handlers(),
        worker_id="worker-1",
        clock=lambda: NOW,
    )
    assert result["status"] == "SUCCEEDED"
    assert result["job_status"] == "SUCCEEDED"
    assert result["run_status"] == "SUCCEEDED"
    assert result["checkpoint_version"] == 7
    assert result["recovered"] is False


def test_worker_schedules_retry_then_resumes_same_failed_step() -> None:
    queue, repository, _, _ = queue_and_repository()
    failed = run_ingestion_worker_once(
        job_queue=queue,
        run_repository=repository,
        step_handlers=failing_handlers(),
        worker_id="worker-1",
        clock=lambda: NOW,
    )
    assert failed["status"] == "RETRY_SCHEDULED"
    assert failed["job_status"] == "QUEUED"
    assert failed["run_status"] == "WAITING_RETRY"
    assert failed["retry_at"] == "2026-09-21T00:00:30Z"
    assert failed["error_code"] == "provider.timeout"
    assert failed["failed_step"] == "extraction"
    assert queue.get_job("job-1")["error"]["detail"] == (
        "CX ingestion checkpoint execution failed."
    )
    assert "provider timeout" not in str(queue.get_job("job-1"))

    completed = run_ingestion_worker_once(
        job_queue=queue,
        run_repository=repository,
        step_handlers=successful_handlers(),
        worker_id="worker-2",
        clock=lambda: RETRY_READY,
    )
    assert completed["status"] == "SUCCEEDED"
    assert completed["checkpoint_version"] == 10
    saved = repository.find_by_job_id("job-1")
    assert saved["attempt_count"] == 2
    assert saved["step_states"]["extraction"]["attempt_count"] == 2


@pytest.mark.parametrize("retryable", [False, True])
def test_non_retryable_or_exhausted_failure_is_terminal(retryable: bool) -> None:
    max_attempts = 3 if not retryable else 1
    queue, repository, _, _ = queue_and_repository(max_attempts=max_attempts)
    result = run_ingestion_worker_once(
        job_queue=queue,
        run_repository=repository,
        step_handlers=failing_handlers(retryable=retryable),
        clock=lambda: NOW,
    )
    assert result["status"] == "FAILED"
    assert result["job_status"] == "FAILED"
    assert result["run_status"] == "FAILED"
    assert result["retry_at"] is None


def test_idle_worker_returns_metadata_only_result() -> None:
    result = run_ingestion_worker_once(
        job_queue=InMemoryJobQueue(),
        run_repository=InMemoryIngestionRunRepository(),
        step_handlers={},
        clock=lambda: NOW,
    )
    assert result["status"] == "IDLE"
    assert result["job_id"] is None
    assert result["run_id"] is None


def test_missing_run_fails_claimed_job_without_retry() -> None:
    queue, _, _, _ = queue_and_repository()
    result = run_ingestion_worker_once(
        job_queue=queue,
        run_repository=InMemoryIngestionRunRepository(),
        step_handlers={},
        clock=lambda: NOW,
    )
    assert result["status"] == "FAILED"
    assert result["error_code"] == "cx.ingestion_worker.run_not_found"
    assert result["run_id"] is None


def test_expired_lease_recovery_requeues_job_and_run() -> None:
    queue, repository, _, run = queue_and_repository()
    queue.claim_next_job("worker-dead", updated_at=NOW)
    claimed = claim_ingestion_run(
        run,
        worker_id="worker-dead",
        lease_expires_at="2026-09-21T00:00:10Z",
        observed_at=NOW,
    )
    repository.save(claimed, expected_checkpoint_version=0)

    recovered = recover_expired_ingestion_job(
        "job-1",
        job_queue=queue,
        run_repository=repository,
        observed_at="2026-09-21T00:00:11Z",
    )
    assert recovered["status"] == "RETRY_SCHEDULED"
    assert recovered["run_status"] == "WAITING_RETRY"
    assert recovered["job_status"] == "QUEUED"
    assert recovered["error_code"] == "cx.ingestion_worker.lease_expired"
    assert recovered["recovered"] is True


def test_recovery_rejects_missing_job_run_and_active_lease() -> None:
    with pytest.raises(IngestionWorkerError) as missing_job:
        recover_expired_ingestion_job(
            "missing",
            job_queue=InMemoryJobQueue(),
            run_repository=InMemoryIngestionRunRepository(),
            observed_at=NOW,
        )
    assert missing_job.value.error_code == "cx.ingestion_worker.job_not_found"

    queue, _, _, _ = queue_and_repository()
    queue.claim_next_job("worker-1", updated_at=NOW)
    with pytest.raises(IngestionWorkerError) as missing_run:
        recover_expired_ingestion_job(
            "job-1",
            job_queue=queue,
            run_repository=InMemoryIngestionRunRepository(),
            observed_at=NOW,
        )
    assert missing_run.value.error_code == "cx.ingestion_worker.run_not_found"

    queue, repository, _, run = queue_and_repository()
    queue.claim_next_job("worker-1", updated_at=NOW)
    repository.save(
        claim_ingestion_run(
            run,
            worker_id="worker-1",
            lease_expires_at="2026-09-21T00:02:00Z",
            observed_at=NOW,
        ),
        expected_checkpoint_version=0,
    )
    with pytest.raises(IngestionWorkerError) as active:
        recover_expired_ingestion_job(
            "job-1",
            job_queue=queue,
            run_repository=repository,
            observed_at="2026-09-21T00:01:00Z",
        )
    assert active.value.error_code == "cx.ingestion_worker.lease_not_expired"


class ClaimFailureQueue(InMemoryJobQueue):
    def claim_next_job(self, worker_id, *, job_type=None, updated_at=None):
        raise JobQueueError("queue.offline", "offline", 503)


class ReadFailureRepository(InMemoryIngestionRunRepository):
    def find_by_job_id(self, job_id):
        raise IngestionRunRepositoryError("repository.offline", "offline", 503)


class RecoveryReadFailureQueue(InMemoryJobQueue):
    def get_job(self, job_id):
        raise JobQueueError("queue.offline", "offline", 503)


class CompletionFailureQueue(InMemoryJobQueue):
    def complete_job(self, job_id, *, updated_at=None):
        raise JobQueueError("queue.complete_failed", "offline", 503)


class FailureSaveRepository(InMemoryIngestionRunRepository):
    save_count = 0

    def save(self, run, *, expected_checkpoint_version):
        self.save_count += 1
        if self.save_count > 1:
            raise IngestionRunRepositoryError("repository.save_failed", "offline", 503)
        return super().save(run, expected_checkpoint_version=expected_checkpoint_version)


class MissingRunFailureQueue(InMemoryJobQueue):
    def fail_job(self, job_id, *, updated_at=None):
        raise JobQueueError("queue.fail_failed", "offline", 503)


class VanishingRunRepository(InMemoryIngestionRunRepository):
    read_count = 0

    def find_by_job_id(self, job_id):
        self.read_count += 1
        if self.read_count > 1:
            return None
        return super().find_by_job_id(job_id)


def test_dependency_failures_are_normalized() -> None:
    with pytest.raises(IngestionWorkerError) as claim_failed:
        run_ingestion_worker_once(
            job_queue=ClaimFailureQueue(),
            run_repository=InMemoryIngestionRunRepository(),
            step_handlers={},
            clock=lambda: NOW,
        )
    assert claim_failed.value.error_code == "cx.ingestion_worker.claim_failed"

    queue, _, _, _ = queue_and_repository()
    with pytest.raises(IngestionWorkerError) as read_failed:
        run_ingestion_worker_once(
            job_queue=queue,
            run_repository=ReadFailureRepository(),
            step_handlers={},
            clock=lambda: NOW,
        )
    assert read_failed.value.error_code == "cx.ingestion_worker.run_read_failed"

    with pytest.raises(IngestionWorkerError) as recovery_read:
        recover_expired_ingestion_job(
            "job-1",
            job_queue=RecoveryReadFailureQueue(),
            run_repository=InMemoryIngestionRunRepository(),
            observed_at=NOW,
        )
    assert recovery_read.value.error_code == (
        "cx.ingestion_worker.recovery_job_read_failed"
    )


def test_execution_and_failure_persistence_errors_are_normalized() -> None:
    base_queue, repository, job, _ = queue_and_repository()
    queue = CompletionFailureQueue(
        jobs=base_queue.jobs,
        idempotency_index=base_queue.idempotency_index,
    )
    with pytest.raises(IngestionWorkerError) as completion:
        run_ingestion_worker_once(
            job_queue=queue,
            run_repository=repository,
            step_handlers=successful_handlers(),
            clock=lambda: NOW,
        )
    assert completion.value.error_code == (
        "cx.ingestion_worker.execution_persistence_failed"
    )

    queue, _, _, run = queue_and_repository()
    failing_repository = FailureSaveRepository()
    failing_repository.create(run)
    with pytest.raises(IngestionWorkerError) as failure_save:
        run_ingestion_worker_once(
            job_queue=queue,
            run_repository=failing_repository,
            step_handlers=failing_handlers(),
            clock=lambda: NOW,
        )
    assert failure_save.value.error_code == (
        "cx.ingestion_worker.failure_persistence_failed"
    )

    base_queue, _, _, _ = queue_and_repository()
    missing_queue = MissingRunFailureQueue(
        jobs=base_queue.jobs,
        idempotency_index=base_queue.idempotency_index,
    )
    with pytest.raises(IngestionWorkerError) as missing_failure:
        run_ingestion_worker_once(
            job_queue=missing_queue,
            run_repository=InMemoryIngestionRunRepository(),
            step_handlers={},
            clock=lambda: NOW,
        )
    assert missing_failure.value.error_code == (
        "cx.ingestion_worker.missing_run_job_failure_failed"
    )


def test_execution_detects_disappearing_or_unclaimable_run() -> None:
    queue, _, _, run = queue_and_repository()
    repository = VanishingRunRepository()
    repository.create(run)
    with pytest.raises(IngestionWorkerError) as vanished:
        run_ingestion_worker_once(
            job_queue=queue,
            run_repository=repository,
            step_handlers=failing_handlers(),
            clock=lambda: NOW,
        )
    assert vanished.value.error_code == "cx.ingestion_worker.run_lost"

    queue, repository, _, run = queue_and_repository()
    running_job = queue.claim_next_job("worker-1", updated_at=NOW)
    repository.save(
        claim_ingestion_run(
            run,
            worker_id="worker-other",
            lease_expires_at="2026-09-21T00:02:00Z",
            observed_at=NOW,
        ),
        expected_checkpoint_version=0,
    )
    with pytest.raises(IngestionWorkerError) as not_claimable:
        execute_claimed_ingestion_job(
            running_job,
            job_queue=queue,
            run_repository=repository,
            step_handlers=successful_handlers(),
            worker_id="worker-1",
            observed_at=NOW,
        )
    assert not_claimable.value.error_code == (
        "cx.ingestion_worker.run_not_claimable"
    )


def test_claimed_job_validation_and_retry_readiness_fail_closed() -> None:
    queue, repository, job, _ = queue_and_repository()
    with pytest.raises(IngestionWorkerError) as unclaimed:
        execute_claimed_ingestion_job(
            job,
            job_queue=queue,
            run_repository=repository,
            step_handlers={},
            worker_id="worker-1",
        )
    assert unclaimed.value.error_code == "cx.ingestion_worker.job_not_running"

    wrong = build_common_job(
        job_id="wrong-job",
        job_type="cx.other",
        trace_id="trace-1",
        request_id="request-1",
        subject_ref=build_subject_ref("cx.document", "document-1"),
        idempotency_key="wrong",
        created_at=NOW,
    )
    wrong = {**wrong, "status": "RUNNING", "attempt_count": 1}
    with pytest.raises(IngestionWorkerError) as wrong_type:
        execute_claimed_ingestion_job(
            wrong,
            job_queue=queue,
            run_repository=repository,
            step_handlers={},
            worker_id="worker-1",
        )
    assert wrong_type.value.error_code == "cx.ingestion_worker.job_type_invalid"

    first = run_ingestion_worker_once(
        job_queue=queue,
        run_repository=repository,
        step_handlers=failing_handlers(),
        clock=lambda: NOW,
    )
    claimed_early = queue.start_job("job-1", updated_at="2026-09-21T00:00:01Z")
    with pytest.raises(IngestionWorkerError) as not_ready:
        execute_claimed_ingestion_job(
            claimed_early,
            job_queue=queue,
            run_repository=repository,
            step_handlers=successful_handlers(),
            worker_id="worker-2",
            observed_at="2026-09-21T00:00:01Z",
        )
    assert first["status"] == "RETRY_SCHEDULED"
    assert not_ready.value.error_code == "cx.ingestion_worker.retry_not_ready"


def test_policy_and_field_validation() -> None:
    with pytest.raises(IngestionWorkerError) as lease:
        IngestionWorkerPolicy(lease_ttl_seconds=0)
    assert lease.value.error_code == "cx.ingestion_worker.lease_ttl_invalid"
    with pytest.raises(JobQueueError):
        IngestionWorkerPolicy(retry_initial_delay_seconds=10, retry_max_delay_seconds=5)
    assert IngestionWorkerPolicy().job_retry_policy().initial_delay_seconds == 30
    assert str(IngestionWorkerError("code", "detail")) == "detail"

    with pytest.raises(IngestionWorkerError) as worker:
        run_ingestion_worker_once(
            job_queue=InMemoryJobQueue(),
            run_repository=InMemoryIngestionRunRepository(),
            step_handlers={},
            worker_id=" ",
            clock=lambda: NOW,
        )
    assert worker.value.error_code == "cx.ingestion_worker.field_invalid"

    invalid_job = {"job_id": "broken"}
    with pytest.raises(IngestionWorkerError) as invalid:
        execute_claimed_ingestion_job(
            invalid_job,
            job_queue=InMemoryJobQueue(),
            run_repository=InMemoryIngestionRunRepository(),
            step_handlers={},
            worker_id="worker-1",
        )
    assert invalid.value.error_code == "cx.ingestion_worker.job_invalid"

    with pytest.raises(IngestionWorkerError) as timestamp:
        _timestamp("not-a-timestamp")
    assert timestamp.value.error_code == "cx.ingestion_worker.timestamp_invalid"
    assert _timestamp("2026-09-21T00:00:00").tzinfo is not None

    fallback = _dependency_error("fallback", RuntimeError("boom"))
    assert fallback.detail == "Ingestion worker dependency failed."
    assert fallback.status_code == 503
