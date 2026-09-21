from __future__ import annotations

from copy import deepcopy

import pytest

from nex_runtime import (
    InMemoryJobQueue,
    JobQueueError,
    JobRetryPolicy,
    build_common_job,
    build_job_error,
    build_subject_ref,
)
from nex_cx.ingestion_coordinator import IngestionStepResult
from nex_cx.ingestion_orchestration import (
    INGESTION_PIPELINE_STEPS,
    build_ingestion_run,
    claim_ingestion_run,
    fail_ingestion_step,
)
from nex_cx.ingestion_orchestration_repository import (
    InMemoryIngestionRunRepository,
    IngestionRunRepositoryError,
)
from nex_cx.ingestion_read_model import (
    ACTIVE,
    READY,
    READY_RETRY,
    RECONCILE,
    RECOVER_EXPIRED_LEASE,
    TERMINAL,
    WAITING,
    IngestionReadModelError,
    _restart_action,
    _timestamp,
    bounded_ingestion_restart_limit,
    build_ingestion_restart_plan,
    get_ingestion_run_read_model,
    list_document_ingestion_run_read_models,
    project_ingestion_run,
)
from nex_cx.ingestion_worker import CX_INGESTION_JOB_TYPE, run_ingestion_worker_once


NOW = "2026-09-21T00:00:00Z"


def add_pair(
    queue: InMemoryJobQueue,
    repository: InMemoryIngestionRunRepository,
    *,
    suffix: str = "1",
    owner: str = "user-a",
):
    job = queue.enqueue(
        build_common_job(
            job_id=f"job-{suffix}",
            job_type=CX_INGESTION_JOB_TYPE,
            trace_id=f"trace-{suffix}",
            request_id=f"request-{suffix}",
            subject_ref=build_subject_ref("cx.document", f"document-{suffix}"),
            idempotency_key=f"upload-{suffix}",
            max_attempts=3,
            retryable=True,
            links={"document": f"/api/v1/documents/document-{suffix}"},
            created_at=NOW,
        )
    )
    run = repository.create(
        build_ingestion_run(
            document_id=f"document-{suffix}",
            job_id=f"job-{suffix}",
            idempotency_key=f"upload-{suffix}",
            tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
            owner_subject_ref={"type": "oa.user", "id": owner},
            trace_id=f"trace-{suffix}",
            request_id=f"request-{suffix}",
            created_at=NOW,
        )
    )
    return job, run


def successful_handlers():
    return {
        step_id: (
            lambda run, selected=step_id: IngestionStepResult(
                f"cx.{selected}:{run['document_id']}"
            )
        )
        for step_id in INGESTION_PIPELINE_STEPS
    }


def test_owner_scoped_detail_and_collection_read_models() -> None:
    repository = InMemoryIngestionRunRepository()
    queue = InMemoryJobQueue()
    _, run = add_pair(queue, repository)
    detail = get_ingestion_run_read_model(
        run["run_id"],
        tenant_id="tenant-a",
        owner_subject_id="user-a",
        run_repository=repository,
    )
    assert detail["status"] == "QUEUED"
    assert detail["step_total"] == 6
    assert detail["step_completed"] == 0
    assert "owner_subject_ref" not in detail
    assert "tenant_ref" not in detail

    collection = list_document_ingestion_run_read_models(
        "document-1",
        tenant_id="tenant-a",
        owner_subject_id="user-a",
        run_repository=repository,
    )
    assert collection["run_count"] == 1
    assert collection["status_counts"] == {"QUEUED": 1}
    assert get_ingestion_run_read_model(
        run["run_id"],
        tenant_id="tenant-a",
        owner_subject_id="user-b",
        run_repository=repository,
    ) is None
    assert list_document_ingestion_run_read_models(
        "document-1",
        tenant_id="tenant-a",
        owner_subject_id="user-b",
        run_repository=repository,
    )["runs"] == []


def test_completed_projection_reports_steps_without_private_payload() -> None:
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    _, run = add_pair(queue, repository)
    result = run_ingestion_worker_once(
        job_queue=queue,
        run_repository=repository,
        step_handlers=successful_handlers(),
        clock=lambda: NOW,
    )
    projected = project_ingestion_run(repository.find_by_job_id("job-1"))
    assert result["status"] == "SUCCEEDED"
    assert projected["step_completed"] == 6
    assert projected["last_error"] is None
    assert all(step["output_ref"] for step in projected["steps"])
    serialized = str(projected).lower()
    assert "source_text" not in serialized
    assert "vector" not in serialized
    assert "prompt" not in serialized


def test_restart_plan_classifies_ready_active_expired_and_missing() -> None:
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    add_pair(queue, repository, suffix="1")
    _, active_run = add_pair(queue, repository, suffix="2")
    _, expired_run = add_pair(queue, repository, suffix="3")
    add_pair(queue, InMemoryIngestionRunRepository(), suffix="4")

    queue.start_job("job-2", updated_at=NOW)
    repository.save(
        claim_ingestion_run(
            active_run,
            worker_id="worker-active",
            lease_expires_at="2026-09-21T00:02:00Z",
            observed_at=NOW,
        ),
        expected_checkpoint_version=0,
    )
    queue.start_job("job-3", updated_at=NOW)
    repository.save(
        claim_ingestion_run(
            expired_run,
            worker_id="worker-expired",
            lease_expires_at="2026-09-21T00:00:10Z",
            observed_at=NOW,
        ),
        expected_checkpoint_version=0,
    )

    plan = build_ingestion_restart_plan(
        job_queue=queue,
        run_repository=repository,
        observed_at="2026-09-21T00:00:30Z",
    )
    actions = {item["job_id"]: item["action"] for item in plan["items"]}
    assert actions == {
        "job-1": READY,
        "job-2": ACTIVE,
        "job-3": RECOVER_EXPIRED_LEASE,
        "job-4": RECONCILE,
    }
    assert plan["mutation_performed"] is False
    assert plan["action_counts"][RECONCILE] == 1


def test_restart_plan_classifies_waiting_ready_retry_and_terminal() -> None:
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    _, run = add_pair(queue, repository)
    job = queue.claim_next_job("worker-1", updated_at=NOW)
    claimed = repository.save(
        claim_ingestion_run(
            run,
            worker_id="worker-1",
            lease_expires_at="2026-09-21T00:02:00Z",
            observed_at=NOW,
        ),
        expected_checkpoint_version=0,
    )
    failed = fail_ingestion_step(
        claimed,
        worker_id="worker-1",
        error_code="provider.timeout",
        retryable=True,
        retry_at="2026-09-21T00:01:00Z",
        observed_at=NOW,
    )
    repository.save(failed, expected_checkpoint_version=1)
    queue.retry_job(
        "job-1",
        error=build_job_error(
            error_code="provider.timeout",
            detail="safe",
            retryable=True,
        ),
        failed_at=NOW,
        policy=JobRetryPolicy(initial_delay_seconds=60, max_delay_seconds=60),
    )
    waiting = build_ingestion_restart_plan(
        job_queue=queue,
        run_repository=repository,
        observed_at="2026-09-21T00:00:30Z",
    )
    ready = build_ingestion_restart_plan(
        job_queue=queue,
        run_repository=repository,
        observed_at="2026-09-21T00:01:00Z",
    )
    assert job["status"] == "RUNNING"
    assert waiting["items"][0]["action"] == WAITING
    assert ready["items"][0]["action"] == READY_RETRY

    terminal_queue = InMemoryJobQueue()
    terminal_repository = InMemoryIngestionRunRepository()
    add_pair(terminal_queue, terminal_repository)
    run_ingestion_worker_once(
        job_queue=terminal_queue,
        run_repository=terminal_repository,
        step_handlers=successful_handlers(),
        clock=lambda: NOW,
    )
    terminal = build_ingestion_restart_plan(
        job_queue=terminal_queue,
        run_repository=terminal_repository,
        observed_at=NOW,
    )
    assert terminal["items"][0]["action"] == TERMINAL


def test_state_mismatch_limit_and_timestamp_paths() -> None:
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    _, run = add_pair(queue, repository)
    running_job = queue.claim_next_job("worker-1", updated_at=NOW)
    action, reason = _restart_action(running_job, run, observed_at=NOW)
    assert action == RECONCILE
    assert reason == "queue_run_state_mismatch"
    assert bounded_ingestion_restart_limit(None) == 100
    assert bounded_ingestion_restart_limit(0) == 1
    assert bounded_ingestion_restart_limit(999) == 500
    assert bounded_ingestion_restart_limit("2") == 2
    with pytest.raises(IngestionReadModelError) as limit:
        bounded_ingestion_restart_limit("bad")
    assert limit.value.error_code == "cx.ingestion_restart.limit_invalid"
    with pytest.raises(IngestionReadModelError) as timestamp:
        _timestamp("bad")
    assert timestamp.value.error_code == "cx.ingestion_restart.timestamp_invalid"
    assert _timestamp("2026-09-21T00:00:00").tzinfo is not None


class FailingQueue(InMemoryJobQueue):
    def list_jobs(self, *, job_type=None, status=None):
        raise JobQueueError("queue.offline", "offline", 503)


class FailingRepository(InMemoryIngestionRunRepository):
    def get(self, run_id, *, tenant_id, owner_subject_id):
        raise IngestionRunRepositoryError("repository.offline", "offline", 503)

    def list_for_document(self, document_id, *, tenant_id, owner_subject_id):
        raise IngestionRunRepositoryError("repository.offline", "offline", 503)

    def find_by_job_id(self, job_id):
        raise IngestionRunRepositoryError("repository.offline", "offline", 503)


def test_read_model_dependency_and_field_errors_are_normalized() -> None:
    with pytest.raises(IngestionReadModelError) as queue_error:
        build_ingestion_restart_plan(
            job_queue=FailingQueue(),
            run_repository=InMemoryIngestionRunRepository(),
        )
    assert queue_error.value.error_code == "cx.ingestion_restart.job_queue_unavailable"

    repository = FailingRepository()
    with pytest.raises(IngestionReadModelError) as get_error:
        get_ingestion_run_read_model(
            "run-1",
            tenant_id="tenant-a",
            owner_subject_id="user-a",
            run_repository=repository,
        )
    assert get_error.value.error_code == (
        "cx.ingestion_read_model.repository_unavailable"
    )
    with pytest.raises(IngestionReadModelError):
        list_document_ingestion_run_read_models(
            "document-1",
            tenant_id="tenant-a",
            owner_subject_id="user-a",
            run_repository=repository,
        )

    queue = InMemoryJobQueue()
    add_pair(queue, InMemoryIngestionRunRepository())
    with pytest.raises(IngestionReadModelError):
        build_ingestion_restart_plan(
            job_queue=queue,
            run_repository=repository,
            observed_at=NOW,
        )

    with pytest.raises(IngestionReadModelError) as field:
        get_ingestion_run_read_model(
            " ",
            tenant_id="tenant-a",
            owner_subject_id="user-a",
            run_repository=InMemoryIngestionRunRepository(),
        )
    assert field.value.error_code == "cx.ingestion_read_model.field_invalid"
    assert str(IngestionReadModelError("code", "detail")) == "detail"


def test_projection_rejects_invalid_run_shape() -> None:
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    _, run = add_pair(queue, repository)
    invalid = deepcopy(run)
    invalid["payload"] = {"source_text": "secret"}
    with pytest.raises(Exception):
        project_ingestion_run(invalid)
