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
    REPLAY_ACTION_CREATE_NEW_JOB,
    RETRY_ACTION_DEAD_LETTER,
    RETRY_ACTION_REQUEUE,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    InMemoryJobQueue,
    JobReplayPolicy,
    JobRetryPolicy,
    JobQueueError,
    SqlAlchemyJobQueue,
    build_engine,
    build_common_job,
    build_job_error,
    build_session_factory,
    build_subject_ref,
    plan_dead_letter_replay,
    plan_job_retry,
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


def test_job_retry_policy_plans_requeue_and_dead_letter_decisions() -> None:
    policy = JobRetryPolicy(
        initial_delay_seconds=10,
        max_delay_seconds=25,
        backoff_multiplier=3,
    )
    running = sample_job(status=RUNNING, attempt_count=2, max_attempts=4)
    requeue = plan_job_retry(
        running,
        error=build_job_error(
            error_code="cx.processing_step_failed",
            detail="Document processing step failed.",
            retryable=True,
        ),
        failed_at=NOW,
        policy=policy,
    )
    exhausted = plan_job_retry(
        sample_job(status=RUNNING, attempt_count=2, max_attempts=2),
        failed_at=NOW,
        policy=policy,
    )
    non_retryable = plan_job_retry(
        sample_job(status=RUNNING, attempt_count=1, max_attempts=3, retryable=False),
        failed_at=NOW,
        policy=policy,
    )

    assert requeue.action == RETRY_ACTION_REQUEUE
    assert requeue.available_at == "2026-08-05T00:00:25Z"
    assert requeue.error["dead_lettered"] is False
    assert exhausted.action == RETRY_ACTION_DEAD_LETTER
    assert exhausted.error["dead_lettered"] is True
    assert exhausted.error["retryable"] is False
    assert non_retryable.action == RETRY_ACTION_DEAD_LETTER

    with pytest.raises(JobQueueError) as invalid_status:
        plan_job_retry(sample_job(status=QUEUED), failed_at=NOW)
    with pytest.raises(JobQueueError) as invalid_policy:
        JobRetryPolicy(initial_delay_seconds=10, max_delay_seconds=5)

    assert invalid_status.value.error_code == "job.retry_status_invalid"
    assert invalid_policy.value.error_code == "job_retry_policy.max_delay_invalid"


def test_plan_dead_letter_replay_creates_new_queued_job_with_lineage_and_payload_copy() -> None:
    source = sample_job(
        status=FAILED,
        retryable=False,
        attempt_count=2,
        max_attempts=2,
        payload={"source_file_id": "source-001", "nested": {"page_count": 3}},
        error=build_job_error(
            error_code="cx.processing_step_failed",
            detail="Private parser details are not copied into replay lineage.",
            retryable=False,
            dead_lettered=True,
        ),
    )

    decision = plan_dead_letter_replay(
        source,
        replay_job_id="job-001-replay-001",
        idempotency_key="idem-001-replay-001",
        requested_by="operator-001",
        reason="  fixed parser config  ",
        replayed_at=LATER,
    )
    decision_payload = decision.to_dict()

    assert decision.action == REPLAY_ACTION_CREATE_NEW_JOB
    assert decision.source_job_id == "job-001"
    assert decision.replayed_at == LATER
    assert decision.replay_job["job_id"] == "job-001-replay-001"
    assert decision.replay_job["status"] == QUEUED
    assert decision.replay_job["attempt_count"] == 0
    assert decision.replay_job["max_attempts"] == 2
    assert decision.replay_job["retryable"] is True
    assert decision.replay_job["payload"] == source["payload"]
    assert decision.replay_job["payload"] is not source["payload"]
    assert decision.lineage == {
        "lineage_schema_version": "job_replay_lineage.v1",
        "source_job_id": "job-001",
        "source_status": FAILED,
        "source_attempt_count": 2,
        "source_max_attempts": 2,
        "source_error_code": "cx.processing_step_failed",
        "requested_by": "operator-001",
        "reason": "fixed parser config",
        "replayed_at": LATER,
    }
    assert decision_payload["replay_job"] == decision.replay_job
    assert "Private parser details" not in str(decision.lineage)


def test_dead_letter_replay_decision_can_be_enqueued_without_mutating_source_job() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(
        sample_job(
            max_attempts=1,
            payload={"source_file_id": "source-001"},
        )
    )
    queue.start_job("job-001", updated_at=NOW)
    source = queue.retry_job("job-001", failed_at=LATER)

    decision = plan_dead_letter_replay(
        source,
        replay_job_id="job-001-replay-001",
        idempotency_key="idem-001-replay-001",
        requested_by="operator-001",
        reason="operator approved replay",
        replayed_at="2026-08-05T00:00:02Z",
    )
    replay = queue.enqueue(decision.replay_job)
    duplicate = queue.enqueue(
        sample_job(
            job_id="other-replay-id",
            idempotency_key="idem-001-replay-001",
        )
    )
    claimed = queue.claim_next_job("worker-001", updated_at="2026-08-05T00:00:03Z")

    assert queue.get_job("job-001")["status"] == FAILED
    assert queue.get_job("job-001")["error"]["dead_lettered"] is True
    assert replay["job_id"] == "job-001-replay-001"
    assert duplicate["job_id"] == "job-001-replay-001"
    assert claimed["job_id"] == "job-001-replay-001"


def test_plan_dead_letter_replay_supports_policy_overrides() -> None:
    source = sample_job(
        status=FAILED,
        retryable=False,
        payload={"private": "payload"},
        error=build_job_error(
            error_code="cx.operator_failed",
            detail="failed without dead-letter flag",
            retryable=False,
            dead_lettered=False,
        ),
    )

    decision = plan_dead_letter_replay(
        source,
        replay_job_id="job-001-replay-001",
        idempotency_key="idem-001-replay-001",
        requested_by="operator-001",
        reason=" ",
        replayed_at=LATER,
        policy=JobReplayPolicy(
            require_dead_lettered=False,
            require_operator_reason=False,
            copy_payload=False,
        ),
    )

    assert decision.replay_job["status"] == QUEUED
    assert decision.lineage["reason"] == ""
    assert "payload" not in decision.replay_job


def test_plan_dead_letter_replay_rejects_invalid_sources_and_operator_input() -> None:
    dead_lettered = sample_job(
        status=FAILED,
        retryable=False,
        error=build_job_error(
            error_code="cx.processing_step_failed",
            detail="failed",
            retryable=False,
            dead_lettered=True,
        ),
    )
    failed_without_dead_letter = sample_job(
        status=FAILED,
        retryable=False,
        error=build_job_error(
            error_code="cx.processing_step_failed",
            detail="failed",
            retryable=False,
            dead_lettered=False,
        ),
    )

    with pytest.raises(JobQueueError) as invalid_status:
        plan_dead_letter_replay(
            sample_job(status=RUNNING),
            replay_job_id="replay",
            idempotency_key="idem-replay",
            requested_by="operator-001",
            reason="retry",
        )
    with pytest.raises(JobQueueError) as dead_letter_required:
        plan_dead_letter_replay(
            failed_without_dead_letter,
            replay_job_id="replay",
            idempotency_key="idem-replay",
            requested_by="operator-001",
            reason="retry",
        )
    with pytest.raises(JobQueueError) as missing_reason:
        plan_dead_letter_replay(
            dead_lettered,
            replay_job_id="replay",
            idempotency_key="idem-replay",
            requested_by="operator-001",
            reason=" ",
        )
    with pytest.raises(JobQueueError) as long_reason:
        plan_dead_letter_replay(
            dead_lettered,
            replay_job_id="replay",
            idempotency_key="idem-replay",
            requested_by="operator-001",
            reason="x" * 4,
            policy=JobReplayPolicy(max_reason_length=3),
        )
    with pytest.raises(JobQueueError) as invalid_reason:
        plan_dead_letter_replay(
            dead_lettered,
            replay_job_id="replay",
            idempotency_key="idem-replay",
            requested_by="operator-001",
            reason=7,
        )
    with pytest.raises(JobQueueError) as blank_requested_by:
        plan_dead_letter_replay(
            dead_lettered,
            replay_job_id="replay",
            idempotency_key="idem-replay",
            requested_by="",
            reason="retry",
        )

    assert invalid_status.value.error_code == "job_replay.status_invalid"
    assert dead_letter_required.value.error_code == "job_replay.dead_letter_required"
    assert missing_reason.value.error_code == "job_replay.reason_required"
    assert long_reason.value.error_code == "job_replay.reason_too_long"
    assert invalid_reason.value.error_code == "job_replay.reason_invalid"
    assert blank_requested_by.value.error_code == "job.field_invalid"


@pytest.mark.parametrize(
    ("policy_kwargs", "error_code"),
    [
        ({"require_dead_lettered": "yes"}, "job_replay_policy.require_dead_lettered_invalid"),
        ({"require_operator_reason": "no"}, "job_replay_policy.require_operator_reason_invalid"),
        ({"max_reason_length": 0}, "job_replay_policy.max_reason_length_invalid"),
        ({"copy_payload": "yes"}, "job_replay_policy.copy_payload_invalid"),
    ],
)
def test_job_replay_policy_rejects_invalid_values(
    policy_kwargs: dict[str, Any],
    error_code: str,
) -> None:
    with pytest.raises(JobQueueError) as exc_info:
        JobReplayPolicy(**policy_kwargs)

    assert exc_info.value.error_code == error_code
    assert exc_info.value.status_code == 422


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


def test_in_memory_job_queue_retries_with_backoff_then_dead_letters() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(sample_job(max_attempts=2))
    running = queue.claim_next_job("worker-001", updated_at=LATER)

    assert running is not None
    retry = queue.retry_job(
        running["job_id"],
        error=build_job_error(
            error_code="cx.processing_step_failed",
            detail="Document processing step failed.",
            retryable=True,
        ),
        failed_at="2026-08-05T00:00:02Z",
        policy=JobRetryPolicy(initial_delay_seconds=5, max_delay_seconds=10),
    )
    too_early = queue.claim_next_job(
        "worker-001",
        job_type="cx.document_processing",
        updated_at="2026-08-05T00:00:06Z",
    )
    second = queue.claim_next_job(
        "worker-001",
        job_type="cx.document_processing",
        updated_at="2026-08-05T00:00:07Z",
    )
    dead_lettered = queue.retry_job(
        second["job_id"],
        failed_at="2026-08-05T00:00:08Z",
    )

    assert retry["status"] == QUEUED
    assert retry["available_at"] == "2026-08-05T00:00:07Z"
    assert retry["error"]["error_code"] == "cx.processing_step_failed"
    assert too_early is None
    assert second["attempt_count"] == 2
    assert dead_lettered["status"] == FAILED
    assert dead_lettered["retryable"] is False
    assert dead_lettered["error"]["dead_lettered"] is True


def test_in_memory_job_queue_claim_returns_none_and_rejects_blank_worker() -> None:
    queue = InMemoryJobQueue()

    assert queue.claim_next_job("worker-001") is None

    with pytest.raises(JobQueueError, match="worker_id"):
        queue.claim_next_job("")


def test_sqlalchemy_job_queue_enqueues_idempotently_and_returns_copies() -> None:
    queue = sqlite_job_queue()
    first = queue.enqueue(sample_job(payload={"source_file_id": "source-001"}))
    first["status"] = FAILED

    duplicate = queue.enqueue(sample_job(job_id="job-duplicate", idempotency_key="idem-001"))

    assert duplicate["job_id"] == "job-001"
    assert duplicate["status"] == QUEUED
    assert duplicate["payload"] == {"source_file_id": "source-001"}
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


def test_sqlalchemy_job_queue_retries_with_available_at_and_dead_letters() -> None:
    queue = sqlite_job_queue()
    queue.enqueue(sample_job(max_attempts=2, payload={"source_file_id": "source-001"}))
    running = queue.claim_next_job("worker-001", updated_at=LATER)

    assert running is not None
    retry = queue.retry_job(
        running["job_id"],
        error=build_job_error(
            error_code="cx.processing_step_failed",
            detail="Document processing step failed.",
            retryable=True,
        ),
        failed_at="2026-08-05T00:00:02Z",
        policy=JobRetryPolicy(initial_delay_seconds=5, max_delay_seconds=10),
    )
    too_early = queue.claim_next_job(
        "worker-001",
        job_type="cx.document_processing",
        updated_at="2026-08-05T00:00:06Z",
    )
    second = queue.claim_next_job(
        "worker-001",
        job_type="cx.document_processing",
        updated_at="2026-08-05T00:00:07Z",
    )
    dead_lettered = queue.retry_job(
        second["job_id"],
        failed_at="2026-08-05T00:00:08Z",
    )

    assert retry["status"] == QUEUED
    assert retry["available_at"] == "2026-08-05T00:00:07Z"
    assert retry["error"]["error_code"] == "cx.processing_step_failed"
    assert too_early is None
    assert second["attempt_count"] == 2
    assert dead_lettered["status"] == FAILED
    assert dead_lettered["retryable"] is False
    assert dead_lettered["error"]["dead_lettered"] is True
    replay_decision = plan_dead_letter_replay(
        dead_lettered,
        replay_job_id="job-001-replay-001",
        idempotency_key="idem-001-replay-001",
        requested_by="operator-001",
        reason="operator approved replay",
        replayed_at="2026-08-05T00:00:09Z",
    )
    assert replay_decision.replay_job["payload"] == {"source_file_id": "source-001"}
    assert queue.get_job("missing") is None
    with pytest.raises(JobQueueError) as missing:
        queue.retry_job("missing")
    with pytest.raises(JobQueueError) as invalid_status:
        queue.retry_job(dead_lettered["job_id"])
    assert missing.value.error_code == "job.not_found"
    assert invalid_status.value.error_code == "job.retry_status_invalid"


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
