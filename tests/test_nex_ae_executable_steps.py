from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import nex_ae_api.executable_steps as step_module
import pytest
from nex_ae_api.chat_application import ChatApplicationService
from nex_ae_api.executable_steps import (
    EXECUTABLE_STEP_STATES,
    P4_STEP_KIND,
    CompatibilityChatRuntime,
    CompatibilityStepOutcome,
    ExecutableStepError,
    SqlAlchemyExecutableStepRepository,
    compatibility_outcome,
)
from nex_ae_api.runtime_jobs import RuntimeJobError, SqlAlchemyRuntimeJobQueue
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from starlette.responses import JSONResponse, Response

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database/nex-ae-api/migrations/2005_ae_executable_step.sql"
TENANT = "tenant-a"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
INTERACTION_ID = "22222222-2222-4222-8222-222222222222"
STEP_ID = "33333333-3333-4333-8333-333333333333"
START_JOB_ID = "44444444-4444-4444-8444-444444444444"
CONTINUE_JOB_ID = "55555555-5555-4555-8555-555555555555"
NOW_DT = datetime(2026, 10, 13, 3, 0, 0, tzinfo=UTC)
NOW = "2026-10-13T03:00:00Z"


def _session_factory(*, with_schema: bool = True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if with_schema:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE ae_agent_execution (
                        tenant_id TEXT NOT NULL,
                        agent_execution_id TEXT NOT NULL,
                        legacy_interaction_id TEXT NOT NULL,
                        correlation_id TEXT NOT NULL,
                        PRIMARY KEY (tenant_id, agent_execution_id)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE ae_executable_step (
                        tenant_id TEXT NOT NULL, executable_step_id TEXT NOT NULL,
                        agent_execution_id TEXT NOT NULL, step_kind TEXT NOT NULL,
                        state TEXT NOT NULL, version INTEGER NOT NULL,
                        legacy_interaction_id TEXT NOT NULL,
                        retrieval_package_ref TEXT, retrieval_package_hash TEXT,
                        cx_generation_id TEXT, cx_job_id TEXT,
                        generated_response_id TEXT, result_ref TEXT, error_ref TEXT,
                        correlation_id TEXT NOT NULL, causation_id TEXT,
                        invocation_started_at TEXT, completed_at TEXT,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        PRIMARY KEY (tenant_id, executable_step_id),
                        UNIQUE (tenant_id, agent_execution_id, step_kind)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE ae_runtime_job (
                        tenant_id TEXT NOT NULL, runtime_job_id TEXT NOT NULL,
                        job_type TEXT NOT NULL, execution_id TEXT NOT NULL,
                        executable_step_id TEXT, wait_id TEXT,
                        reconciliation_id TEXT, result_delivery_id TEXT,
                        publication_reconciliation_id TEXT, state TEXT NOT NULL,
                        dedup_key TEXT NOT NULL, attempt_no INTEGER NOT NULL,
                        run_after TEXT NOT NULL, lease_owner TEXT,
                        lease_token TEXT, lease_until TEXT, payload_json TEXT NOT NULL,
                        correlation_id TEXT NOT NULL, causation_id TEXT,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        PRIMARY KEY (tenant_id, runtime_job_id),
                        UNIQUE (tenant_id, dedup_key)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE ae_runtime_job_attempt (
                        attempt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                        runtime_job_id TEXT NOT NULL, attempt_no INTEGER NOT NULL,
                        worker_id TEXT NOT NULL, lease_token TEXT NOT NULL,
                        started_at TEXT NOT NULL, ended_at TEXT, outcome TEXT NOT NULL,
                        error_ref TEXT, retry_disposition_ref TEXT,
                        UNIQUE (tenant_id, runtime_job_id, attempt_no)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    "INSERT INTO ae_agent_execution VALUES "
                    "(:tenant, :execution, :interaction, :correlation)"
                ),
                {
                    "tenant": TENANT,
                    "execution": EXECUTION_ID,
                    "interaction": INTERACTION_ID,
                    "correlation": "correlation-a",
                },
            )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _ids(*values: str):
    items = iter(values)
    return lambda: next(items)


def _execution(**overrides):
    values = {
        "tenant_id": TENANT,
        "agent_execution_id": EXECUTION_ID,
        "legacy_interaction_id": INTERACTION_ID,
        "correlation_id": "correlation-a",
        "causation_id": None,
    }
    return {**values, **overrides}


def _components(
    *,
    mode: str = "required",
    sessions=None,
    runtime_ids=(STEP_ID, START_JOB_ID),
    queue_ids=("lease-a", "attempt-a", "lease-b", "attempt-b"),
):
    sessions = sessions or _session_factory()
    steps = SqlAlchemyExecutableStepRepository(sessions)
    jobs = SqlAlchemyRuntimeJobQueue(sessions, id_factory=_ids(*queue_ids))
    runtime = CompatibilityChatRuntime(
        steps=steps,
        jobs=jobs,
        application=ChatApplicationService(),
        mode=mode,
        id_factory=_ids(*runtime_ids),
        clock=lambda: NOW_DT,
    )
    return sessions, steps, jobs, runtime


def _create_step(repository, **overrides):
    values = {
        "tenant_id": TENANT,
        "executable_step_id": STEP_ID,
        "agent_execution_id": EXECUTION_ID,
        "legacy_interaction_id": INTERACTION_ID,
        "correlation_id": "correlation-a",
        "causation_id": None,
        "now": NOW,
    }
    return repository.create_or_get(**{**values, **overrides})


def _sync_result(**overrides):
    values = {
        "interaction_id": INTERACTION_ID,
        "status": "COMPLETED",
        "retrieval": {
            "cx_retrieval_package_id": "retrieval-a",
            "cx_package_hash": "sha256:retrieval",
        },
        "cx_generation_id": "generation-a",
        "generation": {
            "generated_response_ref": {"generated_response_id": "response-a"}
        },
        "artifact_refs": [{"artifact_id": "artifact-a"}],
    }
    return {**values, **overrides}


def _async_result(*, status: str = "PENDING", **overrides):
    values = {
        "interaction_id": INTERACTION_ID,
        "status": status,
        "cx_generation_id": "generation-a",
        "generation": {
            "async_generation": {
                "job_id": "cx-job-a",
                "cx_generation_id": "generation-a",
            }
        },
        "retrieval": None,
    }
    return {**values, **overrides}


def _claim(jobs, *, worker="worker-a", now=NOW):
    return jobs.claim(
        tenant_id=TENANT,
        worker_id=worker,
        lease_seconds=60,
        now=now,
    )


def test_repository_creates_one_canonical_step_per_execution() -> None:
    _, steps, _, _ = _components()
    created = _create_step(steps)
    duplicate = _create_step(
        steps,
        executable_step_id="99999999-9999-4999-8999-999999999999",
    )

    assert duplicate == created
    assert created["step_kind"] == P4_STEP_KIND
    assert created["state"] == "READY"
    assert created["version"] == 1
    assert created["legacy_interaction_id"] == INTERACTION_ID
    assert created["invocation_started_at"] is None
    assert steps.get(TENANT, STEP_ID) == created


def test_repository_rejects_orphan_lineage_and_semantic_reuse() -> None:
    _, steps, _, _ = _components()
    with pytest.raises(ExecutableStepError) as orphan:
        _create_step(steps, agent_execution_id="missing")
    assert orphan.value.error_code == "ae.executable_step_execution_not_found"

    for overrides in (
        {"legacy_interaction_id": "other"},
        {"correlation_id": "other"},
    ):
        with pytest.raises(ExecutableStepError) as mismatch:
            _create_step(steps, **overrides)
        assert mismatch.value.error_code == "ae.executable_step_execution_mismatch"

    _create_step(steps)
    with pytest.raises(ExecutableStepError) as conflict:
        _create_step(steps, causation_id="different")
    assert conflict.value.error_code == "ae.executable_step_identity_conflict"


def test_sync_start_invokes_chat_once_and_preserves_only_references() -> None:
    _, steps, jobs, runtime = _components()
    step, job = runtime.enqueue_start(execution=_execution())
    assert step["executable_step_id"] == STEP_ID
    assert job["runtime_job_id"] == START_JOB_ID
    assert job["executable_step_id"] == STEP_ID
    claim = _claim(jobs)
    calls = 0

    def callback():
        nonlocal calls
        calls += 1
        return _sync_result()

    result = runtime.run_start(claim=claim, callback=callback)

    assert calls == 1
    assert result.result["artifact_refs"][0]["artifact_id"] == "artifact-a"
    assert result.step is not None
    assert result.step["state"] == "SUCCEEDED"
    assert result.step["retrieval_package_ref"] == "retrieval-a"
    assert result.step["retrieval_package_hash"] == "sha256:retrieval"
    assert result.step["cx_generation_id"] == "generation-a"
    assert result.step["generated_response_id"] == "response-a"
    assert result.step["result_ref"] == f"ae-chat://interaction/{INTERACTION_ID}"
    assert "artifact-a" not in str(result.step)
    assert jobs.get(TENANT, START_JOB_ID)["state"] == "DONE"
    assert steps.get(TENANT, STEP_ID)["invocation_started_at"] == NOW


def test_async_start_waits_and_continuation_never_replays_generation() -> None:
    _, steps, jobs, runtime = _components(runtime_ids=(STEP_ID, START_JOB_ID))
    runtime.enqueue_start(execution=_execution())
    start_claim = _claim(jobs)
    calls = 0

    def callback():
        nonlocal calls
        calls += 1
        return _async_result()

    started = runtime.run_start(claim=start_claim, callback=callback)
    assert calls == 1
    assert started.step["state"] == "WAITING"
    assert started.step["cx_job_id"] == "cx-job-a"
    terminal = _async_result(
        status="COMPLETED",
        generation={
            "async_generation": {"job_id": "cx-job-a"},
            "generated_response_id": "response-a",
        },
    )
    continuation = runtime.enqueue_continuation(
        tenant_id=TENANT,
        executable_step_id=STEP_ID,
        terminal_result=terminal,
        runtime_job_id=CONTINUE_JOB_ID,
    )
    duplicate = runtime.enqueue_continuation(
        tenant_id=TENANT,
        executable_step_id=STEP_ID,
        terminal_result=terminal,
        runtime_job_id="66666666-6666-4666-8666-666666666666",
    )
    assert duplicate == continuation
    assert continuation["job_type"] == "CONTINUE_EXECUTION"

    continue_claim = _claim(jobs, worker="worker-b")
    completed = runtime.run_continue(
        claim=continue_claim,
        terminal_result=terminal,
    )
    assert completed["state"] == "SUCCEEDED"
    assert completed["generated_response_id"] == "response-a"
    assert calls == 1
    assert jobs.get(TENANT, CONTINUE_JOB_ID)["state"] == "DONE"
    assert [item["state"] for item in (steps.get(TENANT, STEP_ID),)] == [
        "SUCCEEDED"
    ]


@pytest.mark.parametrize(
    ("status", "expected_state"),
    (
        ("NO_ANSWER", "BLOCKED"),
        ("FAILED", "FAILED"),
        ("CANCELLED", "CANCELLED"),
    ),
)
def test_terminal_chat_status_mapping(status: str, expected_state: str) -> None:
    failure = {"error_code": "chat.failed"} if status == "FAILED" else None
    outcome = compatibility_outcome(
        _sync_result(status=status, failure=failure),
        expected_interaction_id=INTERACTION_ID,
    )
    assert outcome.state == expected_state
    assert outcome.error_ref == ("chat.failed" if failure else None)


def test_shadow_pre_invocation_failure_falls_back_once() -> None:
    _, _, _, runtime = _components(mode="shadow")
    calls = 0

    def callback():
        nonlocal calls
        calls += 1
        return _sync_result()

    result = runtime.run_start(claim=None, callback=callback)
    assert calls == 1
    assert result.step is None
    assert result.canonical_error_code == "ae.executable_step_invalid"
    assert result.result["status"] == "COMPLETED"


def test_required_pre_invocation_failure_does_not_call_legacy() -> None:
    _, _, _, runtime = _components()
    calls = 0

    def callback():
        nonlocal calls
        calls += 1
        return _sync_result()

    with pytest.raises(ExecutableStepError):
        runtime.run_start(claim=None, callback=callback)
    assert calls == 0


def test_required_post_invocation_mapping_failure_never_replays() -> None:
    _, _, jobs, runtime = _components()
    runtime.enqueue_start(execution=_execution())
    claim = _claim(jobs)
    calls = 0

    def callback():
        nonlocal calls
        calls += 1
        return _sync_result(interaction_id="other")

    with pytest.raises(ExecutableStepError):
        runtime.run_start(claim=claim, callback=callback)
    assert calls == 1


def test_shadow_post_invocation_failure_returns_result_without_replay(
    monkeypatch,
) -> None:
    _, steps, jobs, runtime = _components(mode="shadow")
    runtime.enqueue_start(execution=_execution())
    claim = _claim(jobs)
    calls = 0

    def callback():
        nonlocal calls
        calls += 1
        return _sync_result()

    def fail_outcome(**kwargs):
        raise ExecutableStepError("ae.step.persist_failed", "failed", True)

    monkeypatch.setattr(steps, "record_outcome", fail_outcome)
    result = runtime.run_start(claim=claim, callback=callback)
    assert calls == 1
    assert result.result["status"] == "COMPLETED"
    assert result.step is None
    assert result.canonical_error_code == "ae.step.persist_failed"


def test_callback_failure_marks_step_and_job_failed_without_replay() -> None:
    _, steps, jobs, runtime = _components()
    runtime.enqueue_start(execution=_execution())
    claim = _claim(jobs)
    calls = 0

    def callback():
        nonlocal calls
        calls += 1
        raise ValueError("provider failure")

    with pytest.raises(ValueError, match="provider failure"):
        runtime.run_start(claim=claim, callback=callback)
    assert calls == 1
    assert steps.get(TENANT, STEP_ID)["state"] == "FAILED"
    assert steps.get(TENANT, STEP_ID)["error_ref"] == "python:ValueError"
    assert jobs.get(TENANT, START_JOB_ID)["state"] == "FAILED"


def test_reclaimed_start_cannot_reinvoke_started_step() -> None:
    _, steps, jobs, runtime = _components(
        queue_ids=("lease-a", "attempt-a", "lease-b", "attempt-b")
    )
    runtime.enqueue_start(execution=_execution())
    first = jobs.claim(
        tenant_id=TENANT, worker_id="worker-a", lease_seconds=1, now=NOW
    )
    ready = steps.get(TENANT, STEP_ID)
    steps.begin_invocation(
        tenant_id=TENANT,
        executable_step_id=STEP_ID,
        expected_version=ready["version"],
        now=NOW,
    )
    reclaimed = jobs.claim(
        tenant_id=TENANT,
        worker_id="worker-b",
        lease_seconds=60,
        now="2026-10-13T03:00:02Z",
    )
    calls = 0

    def callback():
        nonlocal calls
        calls += 1
        return _sync_result()

    assert first is not None and reclaimed is not None
    with pytest.raises(ExecutableStepError) as stale:
        runtime.run_start(claim=reclaimed, callback=callback)
    assert stale.value.error_code == "ae.executable_step_state_conflict"
    assert calls == 0


def test_disabled_mode_invokes_legacy_only_and_rejects_queue_creation() -> None:
    _, _, _, runtime = _components(mode="disabled")
    result = runtime.run_start(claim=None, callback=lambda: _sync_result())
    assert result.step is None
    assert result.canonical_error_code is None
    with pytest.raises(ExecutableStepError):
        runtime.enqueue_start(execution=_execution())
    with pytest.raises(ExecutableStepError):
        runtime.enqueue_continuation(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            terminal_result=_sync_result(),
        )


def test_continuation_requires_existing_waiting_step_and_terminal_result() -> None:
    _, _, jobs, runtime = _components()
    with pytest.raises(ExecutableStepError) as missing:
        runtime.enqueue_continuation(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            terminal_result=_sync_result(),
        )
    assert missing.value.error_code == "ae.executable_step_not_found"

    runtime.enqueue_start(execution=_execution())
    claim = _claim(jobs)
    runtime.run_start(claim=claim, callback=lambda: _async_result())
    with pytest.raises(ExecutableStepError):
        runtime.enqueue_continuation(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            terminal_result=_async_result(),
        )

    continuation = runtime.enqueue_continuation(
        tenant_id=TENANT,
        executable_step_id=STEP_ID,
        terminal_result=_async_result(status="FAILED"),
        runtime_job_id=CONTINUE_JOB_ID,
    )
    continue_claim = _claim(jobs, worker="worker-b")
    with pytest.raises(ExecutableStepError):
        runtime.run_continue(
            claim=continue_claim,
            terminal_result=_async_result(),
        )
    assert continuation["state"] == "QUEUED"


def test_continue_claim_lineage_mismatch_fails_closed() -> None:
    sessions, steps, jobs, runtime = _components()
    runtime.enqueue_start(execution=_execution())
    start_claim = _claim(jobs)
    runtime.run_start(claim=start_claim, callback=lambda: _async_result())
    runtime.enqueue_continuation(
        tenant_id=TENANT,
        executable_step_id=STEP_ID,
        terminal_result=_async_result(status="COMPLETED"),
        runtime_job_id=CONTINUE_JOB_ID,
    )
    claim = _claim(jobs, worker="worker-b")
    with sessions.begin() as session:
        session.execute(
            text("UPDATE ae_executable_step SET state='SUCCEEDED'")
        )
    with pytest.raises(ExecutableStepError) as mismatch:
        runtime.run_continue(
            claim=claim,
            terminal_result=_async_result(status="COMPLETED"),
        )
    assert mismatch.value.error_code == "ae.executable_step_continuation_mismatch"
    assert steps.get(TENANT, STEP_ID)["state"] == "SUCCEEDED"


@pytest.mark.parametrize(
    "terminal",
    (
        _async_result(
            status="COMPLETED",
            generation={"async_generation": {"job_id": "other-job"}},
        ),
        _async_result(status="COMPLETED", cx_generation_id="other-generation"),
    ),
)
def test_continuation_rejects_mismatched_cx_lineage(terminal) -> None:
    _, _, jobs, runtime = _components()
    runtime.enqueue_start(execution=_execution())
    runtime.run_start(claim=_claim(jobs), callback=lambda: _async_result())
    with pytest.raises(ExecutableStepError) as mismatch:
        runtime.enqueue_continuation(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            terminal_result=terminal,
            runtime_job_id=CONTINUE_JOB_ID,
        )
    assert mismatch.value.error_code == (
        "ae.executable_step_continuation_lineage_mismatch"
    )


def test_outcome_accepts_json_response_and_rejects_bad_shapes() -> None:
    outcome = compatibility_outcome(
        JSONResponse(_sync_result()),
        expected_interaction_id=INTERACTION_ID,
    )
    assert outcome.state == "SUCCEEDED"

    bad_values = (
        Response(content=b"not-json"),
        Response(content=b"[]"),
        object(),
        _sync_result(interaction_id="other"),
        _sync_result(status="UNKNOWN"),
        _sync_result(status=""),
    )
    for value in bad_values:
        with pytest.raises(ExecutableStepError) as invalid:
            compatibility_outcome(value, expected_interaction_id=INTERACTION_ID)
        assert invalid.value.error_code == "ae.executable_step_invalid"


def test_repository_state_guards_and_frozen_vocabulary() -> None:
    _, steps, _, _ = _components()
    ready = _create_step(steps)
    running = steps.begin_invocation(
        tenant_id=TENANT,
        executable_step_id=STEP_ID,
        expected_version=ready["version"],
        now=NOW,
    )
    with pytest.raises(ExecutableStepError) as stale:
        steps.begin_invocation(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            expected_version=ready["version"],
            now=NOW,
        )
    assert stale.value.error_code == "ae.executable_step_state_conflict"
    assert stale.value.retryable is True

    with pytest.raises(ExecutableStepError) as wrong_interaction:
        steps.record_outcome(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            expected_version=running["version"],
            expected_state="RUNNING",
            outcome=CompatibilityStepOutcome(
                state="SUCCEEDED", legacy_interaction_id="other"
            ),
            now=NOW,
        )
    assert wrong_interaction.value.error_code == "ae.executable_step_state_conflict"

    with pytest.raises(ExecutableStepError):
        steps.record_outcome(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            expected_version=running["version"],
            expected_state="WAITING",
            outcome=CompatibilityStepOutcome(
                state="WAITING", legacy_interaction_id=INTERACTION_ID
            ),
            now=NOW,
        )
    with pytest.raises(ExecutableStepError):
        steps._transition(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            expected_version=True,
            expected_state="RUNNING",
            target_state="SUCCEEDED",
            now=NOW,
            outcome=None,
        )

    with pytest.raises(ExecutableStepError) as missing:
        steps._transition(
            tenant_id=TENANT,
            executable_step_id="missing",
            expected_version=1,
            expected_state="READY",
            target_state="RUNNING",
            now=NOW,
            outcome=None,
        )
    assert missing.value.error_code == "ae.executable_step_not_found"

    with pytest.raises(ExecutableStepError) as failure_missing:
        steps.record_invocation_failure(
            tenant_id=TENANT,
            executable_step_id="missing",
            expected_version=1,
            error_ref="error-a",
            now=NOW,
        )
    assert failure_missing.value.error_code == "ae.executable_step_not_found"
    with pytest.raises(ExecutableStepError):
        steps._transition(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            expected_version=2,
            expected_state="RUNNING",
            target_state="UNKNOWN",
            now=NOW,
            outcome=None,
        )


def test_repository_failures_and_post_write_reload_are_typed(monkeypatch) -> None:
    unavailable = SqlAlchemyExecutableStepRepository(
        _session_factory(with_schema=False)
    )
    with pytest.raises(ExecutableStepError) as read_failure:
        unavailable.get(TENANT, STEP_ID)
    assert read_failure.value.error_code == "ae.executable_step_store_unavailable"
    assert read_failure.value.retryable is True
    assert str(read_failure.value) == "AE ExecutableStep store is unavailable."
    with pytest.raises(ExecutableStepError):
        _create_step(unavailable)
    with pytest.raises(ExecutableStepError):
        unavailable.begin_invocation(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            expected_version=1,
            now=NOW,
        )

    _, steps, _, _ = _components()
    monkeypatch.setattr(step_module, "_load_by_execution", lambda *args: None)
    with pytest.raises(ExecutableStepError) as create_reload:
        _create_step(steps)
    assert create_reload.value.error_code == "ae.executable_step_write_conflict"

    monkeypatch.undo()
    _, steps, _, _ = _components()
    ready = _create_step(steps)
    real_load = step_module._load_step
    calls = 0

    def disappear_after_update(*args):
        nonlocal calls
        calls += 1
        return None if calls == 1 else real_load(*args)

    monkeypatch.setattr(step_module, "_load_step", disappear_after_update)
    with pytest.raises(ExecutableStepError) as transition_reload:
        steps.begin_invocation(
            tenant_id=TENANT,
            executable_step_id=STEP_ID,
            expected_version=ready["version"],
            now=NOW,
        )
    assert transition_reload.value.error_code == "ae.executable_step_write_conflict"


def test_callback_failure_keeps_original_error_when_canonical_cleanup_fails(
    monkeypatch,
) -> None:
    _, steps, jobs, runtime = _components()
    runtime.enqueue_start(execution=_execution())
    claim = _claim(jobs)

    def cleanup_failure(**kwargs):
        raise ExecutableStepError("ae.cleanup.failed", "cleanup failed")

    monkeypatch.setattr(steps, "record_invocation_failure", cleanup_failure)
    with pytest.raises(ValueError, match="original"):
        runtime.run_start(
            claim=claim,
            callback=lambda: (_ for _ in ()).throw(ValueError("original")),
        )


def test_invalid_runtime_claim_and_mode_fail_closed() -> None:
    _, _, jobs, runtime = _components()
    runtime.enqueue_start(execution=_execution())
    unclaimed = jobs.get(TENANT, START_JOB_ID)
    assert unclaimed is not None
    fake_claim = type("Claim", (), {"job": unclaimed, "attempt": {}})()
    with pytest.raises(ExecutableStepError):
        runtime.run_start(claim=fake_claim, callback=lambda: _sync_result())
    with pytest.raises(ExecutableStepError):
        CompatibilityChatRuntime(
            steps=runtime._steps,
            jobs=jobs,
            mode="invalid",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("job_type", "CONTINUE_EXECUTION"),
        ("state", "QUEUED"),
        ("lease_owner", None),
        ("lease_token", None),
        ("executable_step_id", None),
    ),
)
def test_each_invalid_start_claim_boundary_is_rejected(field, value) -> None:
    _, _, jobs, runtime = _components()
    runtime.enqueue_start(execution=_execution())
    claimed = _claim(jobs)
    invalid_job = {**claimed.job, field: value}
    fake_claim = type("Claim", (), {"job": invalid_job, "attempt": {}})()
    with pytest.raises(ExecutableStepError):
        runtime.run_start(claim=fake_claim, callback=lambda: _sync_result())


def test_claim_with_missing_step_is_rejected_before_callback() -> None:
    sessions, _, jobs, runtime = _components()
    runtime.enqueue_start(execution=_execution())
    claimed = _claim(jobs)
    with sessions.begin() as session:
        session.execute(text("DELETE FROM ae_executable_step"))
    calls = 0

    def callback():
        nonlocal calls
        calls += 1
        return _sync_result()

    with pytest.raises(ExecutableStepError) as mismatch:
        runtime.run_start(claim=claimed, callback=callback)
    assert mismatch.value.error_code == "ae.executable_step_claim_mismatch"
    assert calls == 0


@pytest.mark.parametrize(
    "now",
    (None, "not-a-time", "2026-10-13T03:00:00"),
)
def test_repository_rejects_invalid_timestamps(now) -> None:
    _, steps, _, _ = _components()
    with pytest.raises(ExecutableStepError) as invalid:
        _create_step(steps, now=now)
    assert invalid.value.error_code == "ae.executable_step_invalid"


def test_get_validation_error_is_preserved() -> None:
    _, steps, _, _ = _components()
    with pytest.raises(ExecutableStepError) as invalid:
        steps.get("", STEP_ID)
    assert invalid.value.error_code == "ae.executable_step_invalid"


def test_migration_uses_frozen_states_and_compact_table_name() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS ae_executable_step" in sql
    assert "UNIQUE (tenant_id, agent_execution_id, step_kind)" in sql
    assert "P4_CHAT_RAG_COMPATIBILITY" in sql
    assert "2005_ae_executable_step" in sql
    for state in EXECUTABLE_STEP_STATES:
        assert f"'{state}'" in sql
    assert len("ae_executable_step") <= 30
    assert "prompt" not in sql.lower()
    assert "response_content" not in sql.lower()
