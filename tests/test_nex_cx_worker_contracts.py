from __future__ import annotations

from copy import deepcopy

import pytest

import nex_cx.worker_contracts as worker_contracts
from nex_runtime import InMemoryJobQueue, build_common_job, build_subject_ref
from nex_cx.worker_contracts import (
    CANCELLED,
    CANCELLATION_REQUESTED,
    CLAIMED,
    DEAD_LETTERED,
    RETRY_SCHEDULED,
    RUNNING,
    SUCCEEDED,
    CxWorkerContractError,
    CxWorkerExecutionPolicy,
    build_cx_worker_execution,
    project_cx_worker_execution,
    transition_cx_worker_execution,
    validate_cx_worker_execution,
)


NOW = "2026-09-23T00:00:00Z"
LATER = "2026-09-23T00:00:10Z"
LEASE = "2026-09-23T00:02:00Z"


def running_job(job_type: str = "cx.document_ingestion") -> dict:
    queue = InMemoryJobQueue()
    queue.enqueue(
        build_common_job(
            job_id="job-1",
            job_type=job_type,
            trace_id="a" * 32,
            request_id="request-1",
            subject_ref=build_subject_ref("cx.document", "document-1"),
            idempotency_key="private-key",
            created_at=NOW,
            max_attempts=3,
            links={"private": "/must/not/project"},
        )
    )
    return queue.claim_next_job("worker-1", updated_at=NOW)


def claimed_execution() -> dict:
    return build_cx_worker_execution(
        running_job(),
        worker_id="worker-1",
        worker_type="cx-ingestion",
        workload="document_ingestion",
        lease_expires_at=LEASE,
        observed_at=NOW,
    )


def test_builds_claimed_metadata_only_worker_execution() -> None:
    execution = claimed_execution()

    assert execution["execution_id"] == "job-1:1"
    assert execution["state"] == CLAIMED
    assert execution["state_version"] == 1
    assert execution["attempt_count"] == 1
    assert execution["lease_expires_at"] == LEASE
    projected = project_cx_worker_execution(execution)
    assert projected == execution
    assert "payload" not in projected
    assert "links" not in projected
    assert "idempotency_key" not in projected


@pytest.mark.parametrize(
    ("states", "error_code", "final_state"),
    [
        ((RUNNING, SUCCEEDED), None, SUCCEEDED),
        ((CANCELLATION_REQUESTED, CANCELLED), None, CANCELLED),
        ((RUNNING, RETRY_SCHEDULED), "provider.timeout", RETRY_SCHEDULED),
        ((RUNNING, DEAD_LETTERED), "provider.invalid", DEAD_LETTERED),
    ],
)
def test_allows_defined_worker_execution_lifecycles(
    states: tuple[str, ...],
    error_code: str | None,
    final_state: str,
) -> None:
    execution = claimed_execution()
    for index, state in enumerate(states, start=1):
        execution = transition_cx_worker_execution(
            execution,
            state,
            observed_at=f"2026-09-23T00:00:{index:02d}Z",
            error_code=error_code if state == final_state else None,
        )

    assert execution["state"] == final_state
    assert execution["state_version"] == len(states) + 1
    assert execution["completed_at"] is not None
    assert execution["lease_expires_at"] is None
    if CANCELLATION_REQUESTED in states:
        assert execution["cancellation_requested_at"] is not None


def test_rejects_invalid_or_regressive_transitions() -> None:
    execution = claimed_execution()
    assert transition_cx_worker_execution(execution, CLAIMED) == execution

    with pytest.raises(CxWorkerContractError) as invalid:
        transition_cx_worker_execution(execution, SUCCEEDED, observed_at=LATER)
    assert invalid.value.error_code == "cx.worker_execution.transition_invalid"

    running = transition_cx_worker_execution(
        execution,
        RUNNING,
        observed_at=LATER,
    )
    with pytest.raises(CxWorkerContractError) as regression:
        transition_cx_worker_execution(
            running,
            SUCCEEDED,
            observed_at=NOW,
        )
    assert regression.value.error_code == "cx.worker_execution.time_regression"

    with pytest.raises(CxWorkerContractError) as unexpected_error:
        transition_cx_worker_execution(
            running,
            SUCCEEDED,
            observed_at="2026-09-23T00:00:20Z",
            error_code="unexpected",
        )
    assert unexpected_error.value.error_code == (
        "cx.worker_execution.error_code_unexpected"
    )


def test_rejects_unclaimed_mismatched_unknown_and_expired_jobs() -> None:
    queued = build_common_job(
        job_id="job-2",
        job_type="cx.document_ingestion",
        trace_id="a" * 32,
        request_id="request-2",
        subject_ref=build_subject_ref("cx.document", "document-2"),
        idempotency_key="key-2",
        created_at=NOW,
    )
    with pytest.raises(CxWorkerContractError) as unclaimed:
        build_cx_worker_execution(
            queued,
            worker_id="worker-1",
            worker_type="cx-ingestion",
            workload="document_ingestion",
            lease_expires_at=LEASE,
            observed_at=NOW,
        )
    assert unclaimed.value.error_code == "cx.worker_execution.job_not_running"

    with pytest.raises(CxWorkerContractError) as mismatch:
        build_cx_worker_execution(
            running_job("cx.document_processing"),
            worker_id="worker-1",
            worker_type="cx-ingestion",
            workload="document_ingestion",
            lease_expires_at=LEASE,
            observed_at=NOW,
        )
    assert mismatch.value.error_code == "cx.worker_execution.job_type_mismatch"

    with pytest.raises(CxWorkerContractError) as unknown:
        build_cx_worker_execution(
            running_job(),
            worker_id="worker-1",
            worker_type="cx-ingestion",
            workload="unknown",
            lease_expires_at=LEASE,
            observed_at=NOW,
        )
    assert unknown.value.error_code == "cx.worker_execution.workload_invalid"

    with pytest.raises(CxWorkerContractError) as expired:
        build_cx_worker_execution(
            running_job(),
            worker_id="worker-1",
            worker_type="cx-ingestion",
            workload="document_ingestion",
            lease_expires_at=NOW,
            observed_at=NOW,
        )
    assert expired.value.error_code == "cx.worker_execution.lease_expired"


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (lambda value: value.pop("job_id"), "fields_missing"),
        (
            lambda value: value.update(execution_schema_version="v0"),
            "schema_version_invalid",
        ),
        (lambda value: value.update(state="UNKNOWN"), "state_invalid"),
        (lambda value: value.update(state_version=0), "integer_invalid"),
        (lambda value: value.update(attempt_count=4), "attempt_invalid"),
        (lambda value: value.update(retryable="yes"), "retryable_invalid"),
        (lambda value: value.update(subject_ref=[]), "subject_ref_invalid"),
        (lambda value: value.update(updated_at="bad"), "timestamp_invalid"),
        (lambda value: value.update(lease_expires_at=None), "lease_required"),
        (
            lambda value: value.update(
                state=CANCELLATION_REQUESTED,
                cancellation_requested_at=None,
            ),
            "cancellation_time_required",
        ),
        (
            lambda value: value.update(
                state=RETRY_SCHEDULED,
                lease_expires_at=None,
                completed_at=LATER,
                error_code=None,
            ),
            "error_code_required",
        ),
    ],
)
def test_validation_fails_closed(mutation, error_code: str) -> None:
    value = deepcopy(claimed_execution())
    mutation(value)

    with pytest.raises(CxWorkerContractError) as failure:
        validate_cx_worker_execution(value)
    assert failure.value.error_code.endswith(error_code)


def test_policy_validation_and_invalid_inputs() -> None:
    assert CxWorkerExecutionPolicy().max_batch_jobs == 10
    assert CxWorkerExecutionPolicy(max_batch_jobs=100).lease_ttl_seconds == 120

    for kwargs in (
        {"lease_ttl_seconds": 0},
        {"lease_ttl_seconds": True},
        {"cancellation_check_interval_seconds": 0},
        {"max_batch_jobs": 0},
        {"max_batch_jobs": 101},
    ):
        with pytest.raises(CxWorkerContractError):
            CxWorkerExecutionPolicy(**kwargs)

    with pytest.raises(CxWorkerContractError):
        validate_cx_worker_execution([])
    invalid_job = {"status": "RUNNING"}
    with pytest.raises(CxWorkerContractError) as invalid:
        build_cx_worker_execution(
            invalid_job,
            worker_id="worker-1",
            worker_type="cx-ingestion",
            workload="document_ingestion",
            lease_expires_at=LEASE,
            observed_at=NOW,
        )
    assert invalid.value.error_code == "cx.worker_execution.job_invalid"


def test_contract_helpers_cover_terminal_and_timestamp_edges() -> None:
    assert str(CxWorkerContractError("code", "detail")) == "detail"

    terminal_without_time = deepcopy(claimed_execution())
    terminal_without_time.update(
        state=SUCCEEDED,
        lease_expires_at=None,
        completed_at=None,
    )
    with pytest.raises(CxWorkerContractError) as missing_completion:
        validate_cx_worker_execution(terminal_without_time)
    assert missing_completion.value.error_code.endswith("completed_at_required")

    empty_worker = deepcopy(claimed_execution())
    empty_worker["worker_id"] = " "
    with pytest.raises(CxWorkerContractError) as invalid_string:
        validate_cx_worker_execution(empty_worker)
    assert invalid_string.value.error_code.endswith("field_invalid")

    non_string_time = deepcopy(claimed_execution())
    non_string_time["updated_at"] = 1
    with pytest.raises(CxWorkerContractError) as invalid_time:
        validate_cx_worker_execution(non_string_time)
    assert invalid_time.value.error_code.endswith("timestamp_invalid")

    naive = deepcopy(claimed_execution())
    naive["updated_at"] = "2026-09-23T00:00:00"
    assert validate_cx_worker_execution(naive)["updated_at"] == NOW

    assert worker_contracts._timestamp(
        worker_contracts._utc_now(), "now"
    ).tzinfo is not None
