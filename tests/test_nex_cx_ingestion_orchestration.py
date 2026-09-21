from __future__ import annotations

from copy import deepcopy

import pytest

from nex_cx.ingestion_orchestration import (
    CANCELLED,
    FAILED,
    INGESTION_PIPELINE_STEPS,
    IngestionOrchestrationError,
    IngestionOrchestrationPolicy,
    PENDING,
    QUEUED,
    RUNNING,
    STEP_FAILED,
    STEP_RUNNING,
    STEP_SKIPPED,
    STEP_SUCCEEDED,
    SUCCEEDED,
    WAITING_RETRY,
    build_ingestion_run,
    cancel_ingestion_run,
    claim_ingestion_run,
    complete_ingestion_step,
    fail_ingestion_step,
    requeue_ingestion_run,
    validate_ingestion_run,
)


NOW = "2026-09-21T00:00:00Z"
LATER = "2026-09-21T00:02:00Z"


def make_run(**overrides):
    values = {
        "document_id": "document-1",
        "job_id": "job-1",
        "idempotency_key": "upload-1",
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
        "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
        "trace_id": "trace-1",
        "request_id": "request-1",
        "created_at": NOW,
    }
    values.update(overrides)
    return build_ingestion_run(**values)


def claim(run=None, *, version=0):
    return claim_ingestion_run(
        run or make_run(),
        worker_id="worker-1",
        lease_expires_at=LATER,
        observed_at=NOW,
        expected_checkpoint_version=version,
    )


def test_build_run_is_deterministic_owner_scoped_and_metadata_only() -> None:
    first = make_run()
    second = make_run()

    assert first == second
    assert first["status"] == QUEUED
    assert first["checkpoint_version"] == 0
    assert first["current_step"] == "extraction"
    assert list(first["step_states"]) == list(INGESTION_PIPELINE_STEPS)
    assert {step["status"] for step in first["step_states"].values()} == {PENDING}
    assert first["tenant_ref"]["id"] == "tenant-a"
    assert "payload" not in first
    assert "text" not in str(first).lower()
    assert "vector" not in str(first).lower()


def test_claim_and_complete_all_steps_with_checkpoint_versions() -> None:
    run = claim()
    assert run["status"] == RUNNING
    assert run["attempt_count"] == 1
    assert run["checkpoint_version"] == 1
    assert run["step_states"]["extraction"]["status"] == STEP_RUNNING

    for index, step_id in enumerate(INGESTION_PIPELINE_STEPS, start=1):
        run = complete_ingestion_step(
            run,
            worker_id="worker-1",
            output_ref=f"{step_id}-metadata-id",
            observed_at=LATER,
            skipped=step_id == "summary",
            expected_checkpoint_version=index,
        )

    assert run["status"] == SUCCEEDED
    assert run["current_step"] is None
    assert run["checkpoint_version"] == 7
    assert run["lease_owner"] is None
    assert run["completed_at"] == LATER
    assert run["step_states"]["summary"]["status"] == STEP_SKIPPED
    assert run["step_states"]["summary_embedding"]["status"] == STEP_SUCCEEDED


def test_retryable_failure_requeues_same_step_and_preserves_attempt_history() -> None:
    run = claim()
    failed = fail_ingestion_step(
        run,
        worker_id="worker-1",
        error_code="provider.timeout",
        retryable=True,
        retry_at=LATER,
        observed_at=NOW,
        expected_checkpoint_version=1,
    )
    assert failed["status"] == WAITING_RETRY
    assert failed["step_states"]["extraction"]["status"] == STEP_FAILED
    assert failed["last_error"]["retryable"] is True
    assert failed["lease_owner"] is None

    queued = requeue_ingestion_run(
        failed,
        observed_at=LATER,
        expected_checkpoint_version=2,
    )
    assert queued["status"] == QUEUED
    assert queued["step_states"]["extraction"]["status"] == PENDING
    reclaimed = claim_ingestion_run(
        queued,
        worker_id="worker-2",
        lease_expires_at="2026-09-21T00:04:00Z",
        observed_at=LATER,
        expected_checkpoint_version=3,
    )
    assert reclaimed["attempt_count"] == 2
    assert reclaimed["step_states"]["extraction"]["attempt_count"] == 2


def test_non_retryable_and_exhausted_failures_are_terminal() -> None:
    non_retryable = fail_ingestion_step(
        claim(),
        worker_id="worker-1",
        error_code="extract.unsupported",
        retryable=False,
        observed_at=NOW,
    )
    assert non_retryable["status"] == FAILED
    assert non_retryable["completed_at"] == NOW
    assert non_retryable["last_error"]["retryable"] is False

    one_attempt = make_run(policy=IngestionOrchestrationPolicy(max_attempts=1))
    exhausted = fail_ingestion_step(
        claim(one_attempt),
        worker_id="worker-1",
        error_code="provider.timeout",
        retryable=True,
        observed_at=NOW,
    )
    assert exhausted["status"] == FAILED
    assert exhausted["last_error"]["retryable"] is False


@pytest.mark.parametrize("start", [QUEUED, RUNNING, WAITING_RETRY])
def test_cancel_active_run_releases_lease(start: str) -> None:
    run = make_run()
    if start in {RUNNING, WAITING_RETRY}:
        run = claim(run)
    if start == WAITING_RETRY:
        run = fail_ingestion_step(
            run,
            worker_id="worker-1",
            error_code="temporary",
            retryable=True,
            retry_at=LATER,
            observed_at=NOW,
        )
    cancelled = cancel_ingestion_run(run, observed_at=LATER)
    assert cancelled["status"] == CANCELLED
    assert cancelled["lease_owner"] is None
    assert cancelled["completed_at"] == LATER


def test_transition_and_version_conflicts_fail_closed() -> None:
    with pytest.raises(IngestionOrchestrationError) as conflict:
        claim_ingestion_run(
            make_run(),
            worker_id="worker-1",
            lease_expires_at=LATER,
            expected_checkpoint_version=9,
        )
    assert conflict.value.error_code == "cx.ingestion_run.checkpoint_conflict"

    running = claim()
    with pytest.raises(IngestionOrchestrationError) as duplicate_claim:
        claim_ingestion_run(
            running,
            worker_id="worker-2",
            lease_expires_at=LATER,
        )
    assert duplicate_claim.value.error_code == "cx.ingestion_run.transition_invalid"

    with pytest.raises(IngestionOrchestrationError) as owner:
        complete_ingestion_step(
            running,
            worker_id="worker-2",
            output_ref="artifact-1",
        )
    assert owner.value.error_code == "cx.ingestion_run.lease_owner_mismatch"


def test_failure_and_requeue_validation_paths() -> None:
    running = claim()
    with pytest.raises(IngestionOrchestrationError) as missing_retry_at:
        fail_ingestion_step(
            running,
            worker_id="worker-1",
            error_code="temporary",
            retryable=True,
        )
    assert missing_retry_at.value.error_code == "cx.ingestion_retry.retry_at_required"

    with pytest.raises(IngestionOrchestrationError) as requeue:
        requeue_ingestion_run(make_run())
    assert requeue.value.error_code == "cx.ingestion_run.transition_invalid"

    with pytest.raises(IngestionOrchestrationError) as completed:
        complete_ingestion_step(
            {**running, "step_states": {**running["step_states"], "extraction": {
                **running["step_states"]["extraction"], "status": PENDING
            }}},
            worker_id="worker-1",
            output_ref="artifact-1",
        )
    assert completed.value.error_code == "cx.ingestion_step.complete_invalid"


@pytest.mark.parametrize(
    ("mutator", "error_code"),
    [
        (lambda value: value.update(payload={"text": "secret"}), "cx.ingestion_run.shape_invalid"),
        (lambda value: value.update(run_schema_version="other"), "cx.ingestion_run.schema_version_invalid"),
        (lambda value: value.update(status="UNKNOWN"), "cx.ingestion_run.status_invalid"),
        (lambda value: value.update(current_step="unknown"), "cx.ingestion_run.current_step_invalid"),
        (lambda value: value.update(step_states={}), "cx.ingestion_run.steps_invalid"),
        (lambda value: value.update(attempt_count=-1), "cx.ingestion_run.field_invalid"),
        (lambda value: value.update(tenant_ref={"type": "oa.user", "id": "x"}), "cx.ingestion_run.tenant_ref_type_invalid"),
        (lambda value: value.update(last_error={"detail": "secret"}), "cx.ingestion_run.last_error_invalid"),
    ],
)
def test_validation_rejects_invalid_or_private_shapes(mutator, error_code: str) -> None:
    value = deepcopy(make_run())
    mutator(value)
    with pytest.raises(IngestionOrchestrationError) as exc:
        validate_ingestion_run(value)
    assert exc.value.error_code == error_code


def test_policy_rejects_invalid_values() -> None:
    for kwargs in (
        {"max_attempts": 0},
        {"lease_ttl_seconds": 0},
        {"retry_initial_delay_seconds": -1},
        {"retry_max_delay_seconds": -1},
        {"retry_initial_delay_seconds": 31, "retry_max_delay_seconds": 30},
    ):
        with pytest.raises(IngestionOrchestrationError):
            IngestionOrchestrationPolicy(**kwargs)


def test_validation_rejects_non_mapping_and_terminal_current_step() -> None:
    with pytest.raises(IngestionOrchestrationError) as invalid:
        validate_ingestion_run([])
    assert invalid.value.error_code == "cx.ingestion_run.invalid"

    run = make_run()
    run["status"] = SUCCEEDED
    with pytest.raises(IngestionOrchestrationError) as terminal:
        validate_ingestion_run(run)
    assert terminal.value.error_code == "cx.ingestion_run.terminal_step_invalid"

    run = make_run()
    run["status"] = RUNNING
    with pytest.raises(IngestionOrchestrationError) as lease:
        validate_ingestion_run(run)
    assert lease.value.error_code == "cx.ingestion_run.lease_required"


def test_terminal_run_cannot_be_cancelled() -> None:
    terminal = fail_ingestion_step(
        claim(),
        worker_id="worker-1",
        error_code="permanent",
        retryable=False,
        observed_at=NOW,
    )
    with pytest.raises(IngestionOrchestrationError) as exc:
        cancel_ingestion_run(terminal)
    assert exc.value.error_code == "cx.ingestion_run.transition_invalid"


def test_step_claim_and_failure_require_pending_and_running_states() -> None:
    queued = make_run()
    queued["step_states"]["extraction"]["status"] = STEP_FAILED
    with pytest.raises(IngestionOrchestrationError) as claim_error:
        claim_ingestion_run(
            queued,
            worker_id="worker-1",
            lease_expires_at=LATER,
        )
    assert claim_error.value.error_code == "cx.ingestion_step.claim_invalid"

    running = claim()
    running["step_states"]["extraction"]["status"] = PENDING
    with pytest.raises(IngestionOrchestrationError) as fail_error:
        fail_ingestion_step(
            running,
            worker_id="worker-1",
            error_code="invalid-state",
            retryable=False,
        )
    assert fail_error.value.error_code == "cx.ingestion_step.fail_invalid"


@pytest.mark.parametrize(
    ("mutator", "error_code"),
    [
        (
            lambda value: value["step_states"]["extraction"].update(extra=True),
            "cx.ingestion_step.shape_invalid",
        ),
        (
            lambda value: value["step_states"]["extraction"].update(
                status="UNKNOWN"
            ),
            "cx.ingestion_step.value_invalid",
        ),
        (
            lambda value: value.update(owner_subject_ref=[]),
            "cx.ingestion_run.owner_subject_ref_invalid",
        ),
        (
            lambda value: value.update(
                last_error={
                    "error_code": "failed",
                    "retryable": "yes",
                    "failed_step": "extraction",
                    "failed_at": NOW,
                }
            ),
            "cx.ingestion_run.last_error_invalid",
        ),
        (
            lambda value: value.update(request_id=" "),
            "cx.ingestion_run.field_invalid",
        ),
    ],
)
def test_nested_validation_failure_paths(mutator, error_code: str) -> None:
    value = deepcopy(make_run())
    mutator(value)
    with pytest.raises(IngestionOrchestrationError) as exc:
        validate_ingestion_run(value)
    assert exc.value.error_code == error_code


def test_missing_only_shape_and_inactive_lease_fail_closed() -> None:
    missing = make_run()
    missing.pop("job_id")
    with pytest.raises(IngestionOrchestrationError) as shape:
        validate_ingestion_run(missing)
    assert "missing=job_id" in str(shape.value)

    with pytest.raises(IngestionOrchestrationError) as lease:
        fail_ingestion_step(
            make_run(),
            worker_id="worker-1",
            error_code="not-running",
            retryable=False,
        )
    assert lease.value.error_code == "cx.ingestion_run.transition_invalid"


def test_error_string_and_default_timestamps() -> None:
    error = IngestionOrchestrationError("code", "detail")
    assert str(error) == "detail"
    run = build_ingestion_run(
        document_id="document-now",
        job_id="job-now",
        idempotency_key="upload-now",
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": "user-a"},
        trace_id="trace-now",
        request_id="request-now",
    )
    assert run["created_at"].endswith("Z")
