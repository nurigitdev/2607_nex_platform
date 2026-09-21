from __future__ import annotations

from copy import deepcopy

import pytest

from nex_runtime import InMemoryJobQueue, JobQueueError
from nex_cx.ingestion import build_ingestion_job
from nex_cx.ingestion_admission import (
    DurableIngestionAdmissionError,
    admit_durable_ingestion,
)
from nex_cx.ingestion_orchestration import IngestionOrchestrationPolicy
from nex_cx.ingestion_orchestration_repository import (
    InMemoryIngestionRunRepository,
    IngestionRunRepositoryError,
)


NOW = "2026-09-21T00:00:00Z"


def registration(*, dedupe_status: str = "CREATED") -> dict:
    job = build_ingestion_job(
        document_id="11111111-1111-1111-1111-111111111111",
        upload_id="upload-1",
        request_id="request-1",
        trace_id="a" * 32,
        created_at=NOW,
    )
    return {
        "document_id": "11111111-1111-1111-1111-111111111111",
        "upload_id": "upload-1",
        "trace_id": "a" * 32,
        "request_id": "request-1",
        "created_at": NOW,
        "ownership_ref": {
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
            "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
        },
        "ingestion_job": job,
        "dedupe": {"status": dedupe_status},
    }


def test_admission_enqueues_job_and_creates_owner_scoped_run() -> None:
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    result = admit_durable_ingestion(
        registration(),
        job_queue=queue,
        run_repository=repository,
    )

    assert result["status"] == "ADMITTED"
    assert result["job"]["job_type"] == "cx.document_ingestion"
    assert result["job"]["max_attempts"] == 3
    assert result["ingestion_run"]["job_id"] == result["job"]["job_id"]
    assert result["ingestion_run"]["owner_subject_ref"]["id"] == "user-a"
    assert result["idempotent"] is False
    assert queue.get_job(result["job"]["job_id"]) == result["job"]


def test_admission_is_idempotent_for_duplicate_registration() -> None:
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    first = admit_durable_ingestion(
        registration(), job_queue=queue, run_repository=repository
    )
    duplicate = admit_durable_ingestion(
        registration(dedupe_status="ALREADY_EXISTS"),
        job_queue=queue,
        run_repository=repository,
    )

    assert duplicate["job"] == first["job"]
    assert duplicate["ingestion_run"] == first["ingestion_run"]
    assert duplicate["idempotent"] is True
    assert len(queue.list_jobs(job_type="cx.document_ingestion")) == 1
    assert len(repository.records) == 1


def test_admission_uses_explicit_policy() -> None:
    result = admit_durable_ingestion(
        registration(),
        job_queue=InMemoryJobQueue(),
        run_repository=InMemoryIngestionRunRepository(),
        policy=IngestionOrchestrationPolicy(max_attempts=5),
    )
    assert result["job"]["max_attempts"] == 5
    assert result["ingestion_run"]["max_attempts"] == 5


class FailingQueue(InMemoryJobQueue):
    def enqueue(self, job):
        raise JobQueueError("queue.failed", "queue failed", 503)


class ConflictingQueue(InMemoryJobQueue):
    def enqueue(self, job):
        return {**job, "job_id": "different-job"}


class FailingRepository(InMemoryIngestionRunRepository):
    def create(self, run):
        raise IngestionRunRepositoryError("repository.failed", "repository failed", 503)


class ConflictingRepository(InMemoryIngestionRunRepository):
    def create(self, run):
        return {**run, "job_id": "different-job"}


@pytest.mark.parametrize(
    ("queue", "repository", "error_code", "retryable"),
    [
        (
            FailingQueue(),
            InMemoryIngestionRunRepository(),
            "cx.ingestion_admission.job_queue_failed",
            True,
        ),
        (
            ConflictingQueue(),
            InMemoryIngestionRunRepository(),
            "cx.ingestion_admission.job_identity_conflict",
            False,
        ),
        (
            InMemoryJobQueue(),
            FailingRepository(),
            "cx.ingestion_admission.run_repository_failed",
            True,
        ),
        (
            InMemoryJobQueue(),
            ConflictingRepository(),
            "cx.ingestion_admission.run_identity_conflict",
            False,
        ),
    ],
)
def test_admission_maps_queue_repository_and_identity_failures(
    queue, repository, error_code: str, retryable: bool
) -> None:
    with pytest.raises(DurableIngestionAdmissionError) as exc:
        admit_durable_ingestion(
            registration(), job_queue=queue, run_repository=repository
        )
    assert exc.value.error_code == error_code
    assert exc.value.retryable is retryable


@pytest.mark.parametrize(
    "mutation",
    [
        lambda record: record.pop("document_id"),
        lambda record: record.update(ownership_ref=[]),
        lambda record: record["ownership_ref"].update(tenant_ref=[]),
        lambda record: record.update(ingestion_job=[]),
    ],
)
def test_admission_rejects_invalid_registration(mutation) -> None:
    record = deepcopy(registration())
    mutation(record)
    with pytest.raises(DurableIngestionAdmissionError) as exc:
        admit_durable_ingestion(
            record,
            job_queue=InMemoryJobQueue(),
            run_repository=InMemoryIngestionRunRepository(),
        )
    assert exc.value.error_code == "cx.ingestion_admission.registration_invalid"
    assert exc.value.status_code == 422
    assert exc.value.retryable is False


def test_admission_error_string() -> None:
    assert str(DurableIngestionAdmissionError("code", "detail")) == "detail"
