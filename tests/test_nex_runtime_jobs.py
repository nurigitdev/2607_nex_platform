from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from sqlalchemy import text

import nex_runtime.jobs as runtime_jobs
from nex_runtime import (
    CANCELLED,
    DatabasePoolSettings,
    FAILED,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    InMemoryJobQueue,
    JobQueueError,
    SqlAlchemyJobQueue,
    build_engine,
    build_common_job,
    build_session_factory,
    build_subject_ref,
    summarize_jobs,
    transition_common_job,
    validate_common_job,
)

NOW = "2026-08-05T00:00:00Z"
LATER = "2026-08-05T00:00:01Z"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def sample_job(**overrides: Any) -> dict[str, Any]:
    job = build_common_job(
        job_id=overrides.pop("job_id", "job-001"),
        job_type=overrides.pop("job_type", "cx.document_processing"),
        trace_id=overrides.pop("trace_id", TRACE_ID),
        request_id=overrides.pop("request_id", REQUEST_ID),
        subject_ref=overrides.pop("subject_ref", build_subject_ref("cx.document", "doc-001")),
        idempotency_key=overrides.pop("idempotency_key", "idem-001"),
        created_at=overrides.pop("created_at", NOW),
        max_attempts=overrides.pop("max_attempts", 2),
        retryable=overrides.pop("retryable", True),
        links=overrides.pop("links", {"document": "/api/v1/documents/doc-001"}),
        status=overrides.pop("status", QUEUED),
    )
    return {**job, **overrides}


def sqlite_job_queue() -> SqlAlchemyJobQueue:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_jobs (
                    job_id TEXT PRIMARY KEY,
                    job_schema_version TEXT NOT NULL DEFAULT 'common_job.v1',
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 1,
                    retryable INTEGER NOT NULL DEFAULT 1,
                    links TEXT NOT NULL DEFAULT '{}',
                    payload TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    available_at TEXT NOT NULL,
                    locked_at TEXT,
                    locked_by TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (job_type, idempotency_key)
                )
                """
            )
        )
    return SqlAlchemyJobQueue(build_session_factory(engine))


def test_build_common_job_matches_common_job_contract_schema() -> None:
    schema = json.loads(
        (Path(__file__).parents[1] / "contracts/schemas/common/common_job.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )

    job = sample_job()

    jsonschema.validate(instance=job, schema=schema)
    assert job["job_schema_version"] == "common_job.v1"
    assert job["status"] == QUEUED
    assert job["attempt_count"] == 0
    assert job["created_at"] == NOW
    assert job["updated_at"] == NOW


@pytest.mark.parametrize(
    ("mutator", "error_code"),
    [
        (lambda job: job.pop("job_id"), "job.invalid"),
        (lambda job: job.__setitem__("job_schema_version", "other"), "job.schema_version_invalid"),
        (lambda job: job.__setitem__("status", "BROKEN"), "job.status_invalid"),
        (lambda job: job.__setitem__("subject_ref", "doc-001"), "job.subject_ref_invalid"),
        (lambda job: job.__setitem__("job_type", ""), "job.field_invalid"),
        (lambda job: job.__setitem__("attempt_count", -1), "job.attempt_count_invalid"),
        (lambda job: job.__setitem__("max_attempts", 0), "job.max_attempts_invalid"),
        (lambda job: job.update({"attempt_count": 3, "max_attempts": 2}), "job.attempts_exhausted"),
        (lambda job: job.__setitem__("retryable", "yes"), "job.retryable_invalid"),
        (lambda job: job.__setitem__("links", []), "job.links_invalid"),
    ],
)
def test_validate_common_job_rejects_invalid_shapes(
    mutator: Any,
    error_code: str,
) -> None:
    job = sample_job()
    mutator(job)

    with pytest.raises(JobQueueError) as exc_info:
        validate_common_job(job)

    assert exc_info.value.error_code == error_code
    assert exc_info.value.status_code in {409, 422}


def test_transition_common_job_lifecycle_and_idempotent_same_status() -> None:
    queued = sample_job()
    running = transition_common_job(queued, RUNNING, updated_at=LATER)

    assert queued["attempt_count"] == 0
    assert running["status"] == RUNNING
    assert running["attempt_count"] == 1
    assert running["updated_at"] == LATER
    assert transition_common_job(running, RUNNING) == running

    succeeded = transition_common_job(running, SUCCEEDED)
    assert succeeded["status"] == SUCCEEDED

    with pytest.raises(JobQueueError, match="cannot transition"):
        transition_common_job(succeeded, RUNNING)


def test_transition_common_job_rejects_invalid_status_and_exhausted_attempts() -> None:
    with pytest.raises(JobQueueError) as bad_status:
        transition_common_job(sample_job(), "BROKEN")

    assert bad_status.value.error_code == "job.status_invalid"

    exhausted = sample_job(max_attempts=1, attempt_count=1)
    with pytest.raises(JobQueueError) as exc_info:
        transition_common_job(exhausted, RUNNING)

    assert exc_info.value.error_code == "job.attempts_exhausted"


def test_in_memory_job_queue_enqueues_idempotently_and_returns_copies() -> None:
    queue = InMemoryJobQueue()
    job = sample_job()

    first = queue.enqueue(job)
    first["status"] = FAILED
    duplicate = queue.enqueue(sample_job(job_id="job-duplicate", idempotency_key="idem-001"))

    assert duplicate["job_id"] == "job-001"
    assert duplicate["status"] == QUEUED
    assert queue.get_job("job-001")["status"] == QUEUED


def test_in_memory_job_queue_rejects_duplicate_id_and_non_queued_enqueue() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(sample_job())

    with pytest.raises(JobQueueError) as duplicate:
        queue.enqueue(sample_job(job_id="job-001", idempotency_key="idem-other"))
    assert duplicate.value.error_code == "job.duplicate_id"

    with pytest.raises(JobQueueError) as non_queued:
        queue.enqueue(sample_job(job_id="job-002", idempotency_key="idem-002", status=RUNNING))
    assert non_queued.value.error_code == "job.enqueue_status_invalid"


def test_in_memory_job_queue_transitions_filters_and_summarizes() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(sample_job(job_id="job-001", idempotency_key="idem-001"))
    queue.enqueue(sample_job(job_id="job-002", idempotency_key="idem-002"))
    queue.enqueue(
        sample_job(
            job_id="job-003",
            job_type="ae.artifact_render",
            subject_ref=build_subject_ref("ae.artifact", "artifact-001"),
            idempotency_key="idem-003",
        )
    )

    queue.complete_job(queue.start_job("job-001")["job_id"])
    queue.fail_job(queue.start_job("job-002")["job_id"])
    queue.cancel_job("job-003")

    assert [job["job_id"] for job in queue.list_jobs(job_type="cx.document_processing")] == [
        "job-001",
        "job-002",
    ]
    assert [job["job_id"] for job in queue.list_jobs(status=FAILED)] == ["job-002"]
    assert queue.summary() == {
        "total": 3,
        "active": 0,
        "terminal": 3,
        "statuses": {
            QUEUED: 0,
            RUNNING: 0,
            SUCCEEDED: 1,
            FAILED: 1,
            CANCELLED: 1,
        },
    }


def test_in_memory_job_queue_reports_missing_and_invalid_transitions() -> None:
    queue = InMemoryJobQueue()

    assert queue.get_job("missing") is None
    with pytest.raises(JobQueueError) as missing:
        queue.start_job("missing")
    assert missing.value.status_code == 404

    queue.enqueue(sample_job())
    with pytest.raises(JobQueueError) as invalid:
        queue.complete_job("job-001")
    assert invalid.value.error_code == "job.transition_invalid"


def test_in_memory_job_queue_claims_next_matching_queued_job() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(
        sample_job(
            job_id="job-later",
            idempotency_key="idem-later",
            available_at="2026-08-05T00:00:05Z",
        )
    )
    queue.enqueue(sample_job(job_id="job-ready", idempotency_key="idem-ready", available_at=NOW))
    queue.enqueue(
        sample_job(
            job_id="job-ae",
            job_type="ae.artifact_render",
            subject_ref=build_subject_ref("ae.artifact", "artifact-001"),
            idempotency_key="idem-ae",
            available_at=NOW,
        )
    )

    claimed = queue.claim_next_job("worker-001", job_type="cx.document_processing", updated_at=LATER)

    assert claimed is not None
    assert claimed["job_id"] == "job-ready"
    assert claimed["status"] == RUNNING
    assert claimed["attempt_count"] == 1


def test_in_memory_job_queue_claim_returns_none_and_rejects_blank_worker() -> None:
    queue = InMemoryJobQueue()

    assert queue.claim_next_job("worker-001") is None

    with pytest.raises(JobQueueError, match="worker_id"):
        queue.claim_next_job("")


def test_sqlalchemy_job_queue_enqueues_idempotently_and_returns_copies() -> None:
    queue = sqlite_job_queue()
    first = queue.enqueue(sample_job())
    first["status"] = FAILED

    duplicate = queue.enqueue(sample_job(job_id="job-duplicate", idempotency_key="idem-001"))

    assert duplicate["job_id"] == "job-001"
    assert duplicate["status"] == QUEUED
    assert queue.get_job("job-001")["status"] == QUEUED


def test_sqlalchemy_job_queue_rejects_duplicate_id_and_non_queued_enqueue() -> None:
    queue = sqlite_job_queue()
    queue.enqueue(sample_job())

    with pytest.raises(JobQueueError) as duplicate:
        queue.enqueue(sample_job(job_id="job-001", idempotency_key="idem-other"))
    assert duplicate.value.error_code == "job.duplicate_id"

    with pytest.raises(JobQueueError) as non_queued:
        queue.enqueue(sample_job(job_id="job-002", idempotency_key="idem-002", status=RUNNING))
    assert non_queued.value.error_code == "job.enqueue_status_invalid"


def test_sqlalchemy_job_queue_transitions_filters_and_summarizes() -> None:
    queue = sqlite_job_queue()
    queue.enqueue(sample_job(job_id="job-001", idempotency_key="idem-001"))
    queue.enqueue(sample_job(job_id="job-002", idempotency_key="idem-002"))
    queue.enqueue(
        sample_job(
            job_id="job-003",
            job_type="ae.artifact_render",
            subject_ref=build_subject_ref("ae.artifact", "artifact-001"),
            idempotency_key="idem-003",
        )
    )

    assert queue.start_job("job-001", updated_at=LATER)["attempt_count"] == 1
    assert queue.start_job("job-001")["attempt_count"] == 1
    queue.complete_job("job-001", updated_at="2026-08-05T00:00:02Z")
    queue.fail_job(queue.start_job("job-002", updated_at=LATER)["job_id"])
    queue.cancel_job("job-003")

    assert [job["job_id"] for job in queue.list_jobs(job_type="cx.document_processing")] == [
        "job-001",
        "job-002",
    ]
    assert [job["job_id"] for job in queue.list_jobs(status=FAILED)] == ["job-002"]
    assert queue.summary()["statuses"][SUCCEEDED] == 1
    assert queue.summary()["statuses"][FAILED] == 1
    assert queue.summary()["statuses"][CANCELLED] == 1


def test_sqlalchemy_job_queue_reports_missing_invalid_transition_and_store_failure() -> None:
    queue = sqlite_job_queue()

    assert queue.get_job("missing") is None
    with pytest.raises(JobQueueError) as missing:
        queue.start_job("missing")
    assert missing.value.status_code == 404

    queue.enqueue(sample_job())
    with pytest.raises(JobQueueError) as invalid:
        queue.complete_job("job-001")
    assert invalid.value.error_code == "job.transition_invalid"

    broken = SqlAlchemyJobQueue(build_session_factory(build_engine("sqlite+pysqlite:///:memory:")))
    with pytest.raises(JobQueueError) as unavailable:
        broken.get_job("job-001")
    assert unavailable.value.error_code == "job.store_unavailable"
    assert unavailable.value.status_code == 503

    with pytest.raises(JobQueueError) as list_unavailable:
        broken.list_jobs()
    assert list_unavailable.value.error_code == "job.store_unavailable"


def test_sqlalchemy_job_queue_claims_next_available_job_and_skips_exhausted_attempts() -> None:
    queue = sqlite_job_queue()
    queue.enqueue(
        sample_job(
            job_id="job-later",
            idempotency_key="idem-later",
            available_at="2026-08-05T00:00:05Z",
        )
    )
    queue.enqueue(
        sample_job(
            job_id="job-exhausted",
            idempotency_key="idem-exhausted",
            available_at=NOW,
            attempt_count=1,
            max_attempts=1,
        )
    )
    queue.enqueue(sample_job(job_id="job-ready", idempotency_key="idem-ready", available_at=NOW))
    queue.enqueue(
        sample_job(
            job_id="job-ae",
            job_type="ae.artifact_render",
            subject_ref=build_subject_ref("ae.artifact", "artifact-001"),
            idempotency_key="idem-ae",
            available_at=NOW,
        )
    )

    claimed = queue.claim_next_job("worker-001", job_type="cx.document_processing", updated_at=LATER)

    assert claimed is not None
    assert claimed["job_id"] == "job-ready"
    assert claimed["status"] == RUNNING
    assert claimed["attempt_count"] == 1
    assert queue.claim_next_job("worker-001", job_type="cx.document_processing", updated_at=LATER) is None

    any_type = queue.claim_next_job("worker-002", updated_at=LATER)
    assert any_type is not None
    assert any_type["job_id"] == "job-ae"

    with pytest.raises(JobQueueError, match="worker_id"):
        queue.claim_next_job("")


def test_sqlalchemy_job_queue_json_and_timestamp_helpers_cover_backend_edges() -> None:
    postgres_engine = build_engine(
        "postgresql://user:secret@localhost/nex_cx_dev",
        pool_settings=DatabasePoolSettings(
            service_id="nex-cx",
            env_prefix="NEX_CX",
            workload="api",
            statement_timeout_ms=0,
        ),
    )
    postgres_session = build_session_factory(postgres_engine)()
    try:
        assert runtime_jobs._json_sql_expressions(postgres_session) == (
            "CAST(:links AS JSONB)",
            "CAST(:payload AS JSONB)",
            "CAST(:error AS JSONB)",
        )
    finally:
        postgres_session.close()

    assert runtime_jobs._json_loads(None, default={"fallback": "yes"}) == {"fallback": "yes"}
    assert runtime_jobs._json_loads({"already": "dict"}, default={}) == {"already": "dict"}
    assert runtime_jobs._json_loads(b'{"from":"bytes"}', default={}) == {"from": "bytes"}
    assert runtime_jobs._json_loads(123, default={"fallback": "yes"}) == {"fallback": "yes"}
    assert runtime_jobs._timestamp_to_wire(datetime(2026, 8, 5, 0, 0, 0)) == (
        "2026-08-05T00:00:00Z"
    )
    assert runtime_jobs._timestamp_to_wire(datetime(2026, 8, 5, 0, 0, 0, tzinfo=UTC)) == (
        "2026-08-05T00:00:00Z"
    )


def test_summarize_jobs_ignores_unknown_statuses_for_counts() -> None:
    summary = summarize_jobs([sample_job(), {**sample_job(job_id="job-002"), "status": "UNKNOWN"}])

    assert summary["total"] == 2
    assert summary["active"] == 1
    assert summary["statuses"][QUEUED] == 1
