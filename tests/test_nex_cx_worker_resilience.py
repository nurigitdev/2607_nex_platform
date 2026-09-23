from __future__ import annotations

from typing import Any

import pytest

from nex_runtime import (
    InMemoryJobQueue,
    JobQueueError,
    build_common_job,
    build_subject_ref,
)
from nex_cx.worker_resilience import (
    PERMANENT,
    POISON,
    TRANSIENT,
    CxWorkerResilienceError,
    CxWorkerResiliencePolicy,
    classify_worker_failure,
    project_dead_letter_job,
    safe_failure_code,
    settle_worker_failure,
)


NOW = "2026-09-23T03:00:00Z"


def _job(*, max_attempts: int = 3) -> dict[str, Any]:
    return build_common_job(
        job_id="job-0976",
        job_type="cx.document_processing",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        request_id="09760000-0000-4000-8000-000000000001",
        subject_ref=build_subject_ref("cx.document", "doc-0976"),
        idempotency_key="idem-0976",
        created_at=NOW,
        max_attempts=max_attempts,
    )


def _running_queue(*, max_attempts: int = 3) -> tuple[InMemoryJobQueue, dict[str, Any]]:
    queue = InMemoryJobQueue()
    queue.enqueue(_job(max_attempts=max_attempts))
    running = queue.claim_next_job("worker-a", updated_at=NOW)
    assert running is not None
    return queue, running


def test_classifies_transient_permanent_and_poison_failures() -> None:
    class ValidationFailure(Exception):
        error_code = "cx.document.invalid"
        failure_class = "validation"
        status_code = 422

    class ExplicitNonRetryable(Exception):
        error_code = "cx.document.rejected"
        retryable = False

    class PoisonFailure(Exception):
        error_code = "cx.worker.payload_corrupt"

    assert classify_worker_failure(RuntimeError())["failure_class"] == TRANSIENT
    assert classify_worker_failure(ValidationFailure())["failure_class"] == PERMANENT
    assert classify_worker_failure(ExplicitNonRetryable())["failure_class"] == PERMANENT
    assert classify_worker_failure(PoisonFailure())["failure_class"] == POISON


def test_transient_failure_uses_bounded_backoff() -> None:
    queue, running = _running_queue()

    class TransientFailure(Exception):
        error_code = "cx.provider.timeout"
        retryable = True
        status_code = 503

    result = settle_worker_failure(
        job_queue=queue,
        job=running,
        failure=TransientFailure("private provider detail"),
        failed_at=NOW,
        policy=CxWorkerResiliencePolicy(
            initial_delay_seconds=10,
            max_delay_seconds=20,
            backoff_multiplier=2,
        ),
    )

    persisted = queue.get_job("job-0976")
    assert result["action"] == "RETRY_SCHEDULED"
    assert result["failure_class"] == TRANSIENT
    assert result["retry_at"] == "2026-09-23T03:00:10Z"
    assert persisted["error"]["detail"] == "CX worker execution failed."


@pytest.mark.parametrize(
    ("failure", "expected_class"),
    [
        (
            type(
                "PermanentFailure",
                (Exception,),
                {"error_code": "cx.document.invalid", "status_code": 422},
            )(),
            PERMANENT,
        ),
        (
            type(
                "PoisonFailure",
                (Exception,),
                {"error_code": "cx.worker.poison"},
            )(),
            POISON,
        ),
    ],
)
def test_permanent_and_poison_failures_dead_letter_immediately(
    failure: Exception,
    expected_class: str,
) -> None:
    queue, running = _running_queue(max_attempts=5)

    result = settle_worker_failure(
        job_queue=queue,
        job=running,
        failure=failure,
        failed_at=NOW,
    )
    projected = project_dead_letter_job(queue.get_job("job-0976"))

    assert result["action"] == "DEAD_LETTERED"
    assert result["failure_class"] == expected_class
    assert result["dead_lettered"] is True
    assert projected["dead_lettered"] is True
    assert "payload" not in projected


def test_exhausted_transient_attempt_dead_letters() -> None:
    queue, running = _running_queue(max_attempts=1)
    result = settle_worker_failure(
        job_queue=queue,
        job=running,
        failure=RuntimeError("private"),
        failed_at=NOW,
    )
    assert result["action"] == "DEAD_LETTERED"
    assert result["failure_class"] == TRANSIENT
    assert result["retry_at"] is None


def test_policy_projection_and_settlement_validation_fail_closed() -> None:
    with pytest.raises(CxWorkerResilienceError) as invalid_policy:
        CxWorkerResiliencePolicy(initial_delay_seconds=5, max_delay_seconds=4)
    assert invalid_policy.value.error_code == (
        "cx.worker_resilience.retry_policy_invalid"
    )
    with pytest.raises(CxWorkerResilienceError) as invalid_codes:
        CxWorkerResiliencePolicy(poison_error_codes=("",))
    assert invalid_codes.value.error_code == (
        "cx.worker_resilience.poison_codes_invalid"
    )
    with pytest.raises(CxWorkerResilienceError) as not_dead:
        project_dead_letter_job(_job())
    assert not_dead.value.error_code == (
        "cx.worker_resilience.dead_letter_required"
    )
    with pytest.raises(CxWorkerResilienceError) as missing_id:
        settle_worker_failure(
            job_queue=InMemoryJobQueue(),
            job={},
            failure=RuntimeError(),
            failed_at=NOW,
        )
    assert missing_id.value.error_code == "cx.worker_resilience.field_invalid"


def test_settlement_dependency_failure_is_typed() -> None:
    class BrokenQueue(InMemoryJobQueue):
        def retry_job(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise JobQueueError("job.store_unavailable", "offline", 503)

    with pytest.raises(CxWorkerResilienceError) as unavailable:
        settle_worker_failure(
            job_queue=BrokenQueue(),
            job={"job_id": "job"},
            failure=RuntimeError(),
            failed_at=NOW,
        )
    assert unavailable.value.error_code == "cx.worker_resilience.settlement_failed"
    assert unavailable.value.retryable is True


def test_safe_failure_code_and_error_string() -> None:
    long_code = "x" * 200
    failure = type("Failure", (Exception,), {"error_code": long_code})()
    assert len(safe_failure_code(failure)) == 160
    assert safe_failure_code(RuntimeError()) == (
        "cx.worker_resilience.handler_failed"
    )
    assert str(CxWorkerResilienceError("code", "detail")) == "detail"
