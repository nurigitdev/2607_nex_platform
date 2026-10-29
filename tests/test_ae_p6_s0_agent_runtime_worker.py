from __future__ import annotations

import io
from collections.abc import Sequence
from typing import Any

import pytest
from nex_ae_api import agent_runtime_worker as worker_module
from nex_ae_api.agent_runtime_worker import (
    AE_AGENT_RUNTIME_WORKER_TYPE,
    LOCAL_SKILL_EXECUTOR,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
    AgentRuntimeAssignment,
    AgentRuntimeShutdownToken,
    AgentRuntimeWorkerConfig,
    AgentRuntimeWorkerError,
    AgentRuntimeWorkerLifecycle,
    build_agent_runtime_worker_check,
    build_agent_runtime_worker_profile,
    install_agent_runtime_worker_signal_handlers,
    load_agent_runtime_worker_config,
    main,
    project_agent_runtime_worker_readiness,
    restore_agent_runtime_worker_signal_handlers,
    run_bounded_agent_runtime_worker,
    validate_agent_runtime_assignment,
    validate_agent_runtime_worker_profile,
    validate_agent_runtime_worker_startup,
)
from nex_ae_api.nsl_backend_profiles import NSL_V01_IN_PROCESS_BACKEND
from nex_ae_api.runtime_jobs import RuntimeJobClaim
from nex_runtime import (
    BUSY,
    ERROR,
    IDLE,
    STARTING,
    STOPPED,
    STOPPING,
    InMemoryWorkerHeartbeatStore,
    WorkerHeartbeatEmitter,
    WorkerHeartbeatError,
)

NOW = "2026-10-14T09:00:00Z"
LATER = "2026-10-14T09:00:10Z"
TENANT = "tenant-p6"
JOB_ID = "22222222-2222-4222-8222-222222222222"


class IncrementingClock:
    def __init__(self) -> None:
        self._tick = 0

    def __call__(self) -> str:
        value = f"2026-10-14T09:00:{self._tick:02d}Z"
        self._tick += 1
        return value


class SequenceSource:
    def __init__(self, assignments: Sequence[AgentRuntimeAssignment | None]) -> None:
        self.assignments = list(assignments)
        self.calls: list[dict[str, Any]] = []

    def claim_next(self, **kwargs: Any) -> AgentRuntimeAssignment | None:
        self.calls.append(kwargs)
        return self.assignments.pop(0) if self.assignments else None


def _profile(**overrides: Any):
    values = {
        "worker_id": "ae-runtime-worker-1",
        "declared_at": NOW,
        "supported_backend_profiles": (NSL_V01_PROCESS_ISOLATED_BACKEND,),
        "process_isolation_required": True,
    }
    return build_agent_runtime_worker_profile(**{**values, **overrides})


def _config(**overrides: Any):
    values = {
        "mode": "enabled",
        "profile": _profile(),
        "lease_seconds": 60,
        "poll_interval_seconds": 0,
        "heartbeat_stale_after_seconds": 60,
    }
    return AgentRuntimeWorkerConfig(**{**values, **overrides})


def _claim(**job_overrides: Any) -> RuntimeJobClaim:
    job = {
        "tenant_id": TENANT,
        "runtime_job_id": JOB_ID,
        "state": "RUNNING",
        "lease_owner": "ae-runtime-worker-1",
        "lease_token": "lease-1",
        "attempt_no": 1,
    }
    return RuntimeJobClaim(
        job={**job, **job_overrides},
        attempt={"attempt_id": "attempt-1", "outcome": "RUNNING"},
    )


def _assignment(**overrides: Any) -> AgentRuntimeAssignment:
    values = {
        "tenant_id": TENANT,
        "executor_kind": LOCAL_SKILL_EXECUTOR,
        "backend_profile": NSL_V01_PROCESS_ISOLATED_BACKEND,
        "claim": _claim(),
    }
    return AgentRuntimeAssignment(**{**values, **overrides})


def _lifecycle(profile=None, store=None):
    resolved_profile = profile or _profile()
    resolved_store = store or InMemoryWorkerHeartbeatStore()
    emitter = WorkerHeartbeatEmitter(
        service_id="nex-ae-api",
        worker_id=resolved_profile.worker_id,
        worker_type=AE_AGENT_RUNTIME_WORKER_TYPE,
        store=resolved_store,
        started_at=NOW,
    )
    return AgentRuntimeWorkerLifecycle(
        profile=resolved_profile,
        emitter=emitter,
        store=resolved_store,
    )


def _available() -> dict[str, tuple[str, ...]]:
    return {
        "available_executor_kinds": (LOCAL_SKILL_EXECUTOR,),
        "available_backend_profiles": (NSL_V01_PROCESS_ISOLATED_BACKEND,),
    }


def test_profile_shape_is_canonical_and_hash_is_deterministic() -> None:
    first = _profile()
    second = _profile(
        supported_executor_kinds=(LOCAL_SKILL_EXECUTOR,),
        supported_backend_profiles=(NSL_V01_PROCESS_ISOLATED_BACKEND,),
    )

    assert first.to_record() == second.to_record()
    assert first.profile_hash == second.profile_hash
    assert first.profile_hash.startswith("sha256:")
    assert validate_agent_runtime_worker_profile(first.to_record()) == first.to_record()


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"worker_id": " "}, "worker_id"),
        ({"supported_executor_kinds": ()}, "must not be empty"),
        (
            {"supported_executor_kinds": (LOCAL_SKILL_EXECUTOR,) * 2},
            "duplicates",
        ),
        ({"max_concurrent_claims": 0}, "between 1"),
        ({"evidence_policy": "NONE"}, "unsupported"),
        ({"process_isolation_required": False}, "requires process isolation"),
        ({"declared_at": "not-time"}, "RFC3339"),
    ],
)
def test_profile_rejects_invalid_or_unsafe_values(overrides, detail) -> None:
    with pytest.raises(AgentRuntimeWorkerError) as failure:
        _profile(**overrides)
    assert detail in failure.value.detail


def test_profile_validator_rejects_schema_and_key_drift() -> None:
    record = _profile().to_record()
    with pytest.raises(AgentRuntimeWorkerError):
        validate_agent_runtime_worker_profile({**record, "extra": True})
    with pytest.raises(AgentRuntimeWorkerError):
        validate_agent_runtime_worker_profile({**record, "schema_version": "2.0"})
    with pytest.raises(AgentRuntimeWorkerError):
        validate_agent_runtime_worker_profile("invalid")  # type: ignore[arg-type]


def test_startup_fails_closed_for_missing_executor_or_backend() -> None:
    config = _config()
    with pytest.raises(AgentRuntimeWorkerError) as executor:
        validate_agent_runtime_worker_startup(
            config,
            available_executor_kinds=(),
            available_backend_profiles=(NSL_V01_PROCESS_ISOLATED_BACKEND,),
        )
    assert executor.value.error_code == "ae.agent_runtime_worker.executor_unavailable"

    with pytest.raises(AgentRuntimeWorkerError) as backend:
        validate_agent_runtime_worker_startup(
            config,
            available_executor_kinds=(LOCAL_SKILL_EXECUTOR,),
            available_backend_profiles=(),
        )
    assert backend.value.error_code == "ae.agent_runtime_worker.backend_unavailable"

    ready = validate_agent_runtime_worker_startup(config, **_available())
    assert ready["startup_ready"] is True

    disabled = validate_agent_runtime_worker_startup(
        _config(mode="disabled"),
        available_executor_kinds=(),
        available_backend_profiles=(),
    )
    assert disabled["startup_ready"] is False
    assert disabled["missing_executor_kinds"] == [LOCAL_SKILL_EXECUTOR]


def test_config_environment_defaults_and_validation() -> None:
    config = load_agent_runtime_worker_config({}, declared_at=NOW)
    assert config.mode == "disabled"
    assert config.profile.supported_executor_kinds == (LOCAL_SKILL_EXECUTOR,)
    assert config.profile.supported_backend_profiles == (NSL_V01_IN_PROCESS_BACKEND,)
    assert config.profile.process_isolation_required is False

    configured = load_agent_runtime_worker_config(
        {
            "NEX_AE_AGENT_WORKER_MODE": "ENABLED",
            "NEX_AE_AGENT_WORKER_ID": "worker-custom",
            "NEX_AE_AGENT_WORKER_MAX_CONCURRENT_CLAIMS": "2",
            "NEX_AE_AGENT_WORKER_LEASE_SECONDS": "90",
            "NEX_AE_AGENT_WORKER_POLL_INTERVAL_SECONDS": "0.5",
            "NEX_AE_AGENT_WORKER_HEARTBEAT_STALE_AFTER_SECONDS": "120",
        },
        declared_at=NOW,
    )
    assert configured.mode == "enabled"
    assert configured.profile.worker_id == "worker-custom"
    assert configured.profile.max_concurrent_claims == 2
    assert configured.lease_seconds == 90
    assert configured.poll_interval_seconds == 0.5

    for env in (
        {"NEX_AE_AGENT_WORKER_MODE": "invalid"},
        {"NEX_AE_AGENT_WORKER_LEASE_SECONDS": "NaN"},
        {"NEX_AE_AGENT_WORKER_POLL_INTERVAL_SECONDS": "NaN"},
        {"NEX_AE_AGENT_WORKER_EXECUTOR_KINDS": ","},
        {"NEX_AE_AGENT_WORKER_EXECUTOR_KINDS": 123},
    ):
        with pytest.raises(AgentRuntimeWorkerError):
            load_agent_runtime_worker_config(env, declared_at=NOW)  # type: ignore[arg-type]

    with pytest.raises(AgentRuntimeWorkerError):
        _config(poll_interval_seconds=True)


def test_assignment_validation_is_capability_and_tenant_safe() -> None:
    profile = _profile()
    assert (
        validate_agent_runtime_assignment(_assignment(), profile).runtime_job_id
        == JOB_ID
    )

    failures = (
        _assignment(executor_kind="UNKNOWN"),
        _assignment(backend_profile="UNKNOWN"),
        _assignment(tenant_id="tenant-other"),
        _assignment(claim=_claim(state="QUEUED")),
        _assignment(claim=_claim(lease_token=None)),
    )
    for assignment in failures:
        with pytest.raises(AgentRuntimeWorkerError):
            validate_agent_runtime_assignment(assignment, profile)


def test_lifecycle_tracks_readiness_capacity_drain_and_lease_safe_stop() -> None:
    profile = _profile()
    lifecycle = _lifecycle(profile)

    assert lifecycle.readiness(checked_at=NOW)["reason_code"] == "heartbeat_missing"
    lifecycle.starting(observed_at=NOW)
    assert lifecycle.readiness(checked_at=NOW)["reason_code"] == "worker_starting"
    lifecycle.idle(observed_at=NOW)
    assert lifecycle.readiness(checked_at=NOW)["readiness"] == "READY"

    lifecycle.begin_assignment(_assignment(), observed_at=LATER)
    assert lifecycle.active_claim_count == 1
    assert lifecycle.can_claim is False
    assert lifecycle.readiness(checked_at=LATER)["status"] == BUSY
    with pytest.raises(AgentRuntimeWorkerError) as capacity:
        lifecycle.begin_assignment(
            _assignment(claim=_claim(runtime_job_id="job-2")), observed_at=LATER
        )
    assert capacity.value.error_code == "ae.agent_runtime_worker.capacity_exhausted"

    lifecycle.request_shutdown(reason_code="SIGTERM", observed_at=LATER)
    assert lifecycle.can_claim is False
    with pytest.raises(AgentRuntimeWorkerError) as active:
        lifecycle.stopped(observed_at=LATER)
    assert active.value.error_code == "ae.agent_runtime_worker.active_claims_remain"
    lifecycle.finish_assignment(JOB_ID, observed_at=LATER)
    lifecycle.stopped(observed_at=LATER)
    assert [item["status"] for item in lifecycle.emissions] == [
        STARTING,
        IDLE,
        BUSY,
        STOPPING,
        STOPPING,
        STOPPED,
    ]


def test_lifecycle_rejects_identity_mismatch_and_missing_active_claim() -> None:
    profile = _profile()
    store = InMemoryWorkerHeartbeatStore()
    wrong = WorkerHeartbeatEmitter(
        service_id="nex-cx",
        worker_id=profile.worker_id,
        worker_type=AE_AGENT_RUNTIME_WORKER_TYPE,
        store=store,
        started_at=NOW,
    )
    with pytest.raises(AgentRuntimeWorkerError):
        AgentRuntimeWorkerLifecycle(profile=profile, emitter=wrong, store=store)

    other_store = InMemoryWorkerHeartbeatStore()
    mismatched_store = WorkerHeartbeatEmitter(
        service_id="nex-ae-api",
        worker_id=profile.worker_id,
        worker_type=AE_AGENT_RUNTIME_WORKER_TYPE,
        store=store,
        started_at=NOW,
    )
    with pytest.raises(AgentRuntimeWorkerError):
        AgentRuntimeWorkerLifecycle(
            profile=profile, emitter=mismatched_store, store=other_store
        )

    wrong_worker = WorkerHeartbeatEmitter(
        service_id="nex-ae-api",
        worker_id="other-worker",
        worker_type=AE_AGENT_RUNTIME_WORKER_TYPE,
        store=store,
        started_at=NOW,
    )
    with pytest.raises(AgentRuntimeWorkerError):
        AgentRuntimeWorkerLifecycle(profile=profile, emitter=wrong_worker, store=store)

    wrong_type = WorkerHeartbeatEmitter(
        service_id="nex-ae-api",
        worker_id=profile.worker_id,
        worker_type="ae.other.worker",
        store=store,
        started_at=NOW,
    )
    with pytest.raises(AgentRuntimeWorkerError):
        AgentRuntimeWorkerLifecycle(profile=profile, emitter=wrong_type, store=store)

    lifecycle = _lifecycle(profile)
    with pytest.raises(AgentRuntimeWorkerError):
        lifecycle.finish_assignment("missing", observed_at=NOW)
    with pytest.raises(AgentRuntimeWorkerError):
        lifecycle.fail_assignment("missing", error_code="failure", observed_at=NOW)


def test_lifecycle_blocks_drain_and_duplicate_assignment() -> None:
    draining = _lifecycle()
    draining.request_shutdown(reason_code="operator", observed_at=NOW)
    assert draining.idle(observed_at=NOW)["status"] == STOPPING
    with pytest.raises(AgentRuntimeWorkerError) as blocked:
        draining.begin_assignment(_assignment(), observed_at=NOW)
    assert blocked.value.error_code == "ae.agent_runtime_worker.draining"

    profile = _profile(max_concurrent_claims=2)
    lifecycle = _lifecycle(profile)
    lifecycle.begin_assignment(_assignment(), observed_at=NOW)
    with pytest.raises(AgentRuntimeWorkerError) as duplicate:
        lifecycle.begin_assignment(_assignment(), observed_at=NOW)
    assert "already active" in duplicate.value.detail


def test_lifecycle_fails_closed_when_heartbeat_store_is_unavailable() -> None:
    class BrokenStore(InMemoryWorkerHeartbeatStore):
        def upsert_heartbeat(self, heartbeat: dict[str, Any]) -> dict[str, Any]:
            raise WorkerHeartbeatError(
                error_code="worker_heartbeat.store_unavailable",
                detail="offline",
                status_code=503,
            )

    lifecycle = _lifecycle(store=BrokenStore())
    with pytest.raises(AgentRuntimeWorkerError) as failure:
        lifecycle.starting(observed_at=NOW)
    assert failure.value.error_code == "ae.agent_runtime_worker.heartbeat_unavailable"
    assert failure.value.retryable is True


def test_readiness_rejects_profile_mismatch_and_stale_heartbeat() -> None:
    profile = _profile()
    lifecycle = _lifecycle(profile)
    lifecycle.idle(observed_at=NOW)
    heartbeat = lifecycle.store.get_heartbeat("nex-ae-api", profile.worker_id)
    assert heartbeat is not None

    mismatch = project_agent_runtime_worker_readiness(
        heartbeat,
        expected_profile_hash="sha256:" + "f" * 64,
        checked_at=NOW,
    )
    stale = project_agent_runtime_worker_readiness(
        heartbeat,
        expected_profile_hash=profile.profile_hash,
        stale_after_seconds=5,
        checked_at="2026-10-14T09:00:06Z",
    )
    assert mismatch["reason_code"] == "capability_profile_mismatch"
    assert stale["reason_code"] == "heartbeat_stale"


def test_bounded_worker_executes_then_idles_and_stops_cleanly() -> None:
    config = _config()
    lifecycle = _lifecycle(config.profile)
    source = SequenceSource((_assignment(), None))
    handled: list[str] = []

    result = run_bounded_agent_runtime_worker(
        config=config,
        assignment_source=source,
        handler=lambda assignment: (
            handled.append(assignment.runtime_job_id) or {"outcome": "DONE"}
        ),
        lifecycle=lifecycle,
        max_cycles=2,
        clock=IncrementingClock(),
        sleeper=lambda _seconds: None,
        **_available(),
    )

    assert handled == [JOB_ID]
    assert result["stop_reason"] == "MAX_CYCLES"
    assert result["cycle_count"] == 2
    assert result["idle_cycle_count"] == 1
    assert result["claimed_count"] == 1
    assert result["succeeded_count"] == 1
    assert result["failed_count"] == 0
    assert result["heartbeat_statuses"] == [
        STARTING,
        IDLE,
        BUSY,
        IDLE,
        IDLE,
        STOPPING,
        STOPPED,
    ]
    assert source.calls[0]["supported_executor_kinds"] == (LOCAL_SKILL_EXECUTOR,)

    persistent_lifecycle = _lifecycle(config.profile)
    persistent = run_bounded_agent_runtime_worker(
        config=config,
        assignment_source=SequenceSource((None,)),
        handler=lambda _assignment: {},
        lifecycle=persistent_lifecycle,
        max_cycles=1,
        finalize_lifecycle=False,
        clock=IncrementingClock(),
        **_available(),
    )
    assert persistent["heartbeat_statuses"] == [STARTING, IDLE, IDLE]
    assert persistent_lifecycle.shutdown_requested is False


def test_bounded_worker_records_handler_failure_without_settling_job_lease() -> None:
    config = _config()
    lifecycle = _lifecycle(config.profile)

    def fail(_assignment):
        raise AgentRuntimeWorkerError("ae.test.failed", "private failure")

    result = run_bounded_agent_runtime_worker(
        config=config,
        assignment_source=SequenceSource((_assignment(),)),
        handler=fail,
        lifecycle=lifecycle,
        max_cycles=2,
        clock=IncrementingClock(),
        **_available(),
    )

    assert result["stop_reason"] == "FAILURE"
    assert result["failed_count"] == 1
    assert result["executions"][0]["error_code"] == "ae.test.failed"
    assert ERROR in result["heartbeat_statuses"]
    assert lifecycle.active_claim_count == 0

    default_failure = run_bounded_agent_runtime_worker(
        config=config,
        assignment_source=SequenceSource((_assignment(),)),
        handler=lambda _assignment: (_ for _ in ()).throw(RuntimeError("private")),
        lifecycle=_lifecycle(config.profile),
        max_cycles=1,
        clock=IncrementingClock(),
        **_available(),
    )
    assert default_failure["executions"][0]["error_code"] == (
        "ae.agent_runtime_worker.assignment_failed"
    )


def test_bounded_worker_honors_shutdown_and_rejects_invalid_composition() -> None:
    token = AgentRuntimeShutdownToken()
    token.request("SIGTERM")
    config = _config()
    lifecycle = _lifecycle(config.profile)
    result = run_bounded_agent_runtime_worker(
        config=config,
        assignment_source=SequenceSource((_assignment(),)),
        handler=lambda _assignment: pytest.fail("handler must not run"),
        lifecycle=lifecycle,
        max_cycles=1,
        shutdown_token=token,
        clock=IncrementingClock(),
        **_available(),
    )
    assert result["stop_reason"] == "SIGTERM"
    assert result["claimed_count"] == 0

    with pytest.raises(AgentRuntimeWorkerError):
        run_bounded_agent_runtime_worker(
            config=_config(mode="disabled"),
            assignment_source=SequenceSource(()),
            handler=lambda _assignment: {},
            lifecycle=_lifecycle(config.profile),
            max_cycles=1,
            **_available(),
        )

    with pytest.raises(AgentRuntimeWorkerError):
        run_bounded_agent_runtime_worker(
            config=config,
            assignment_source=SequenceSource(()),
            handler=lambda _assignment: {},
            lifecycle=_lifecycle(config.profile),
            max_cycles=1,
            finalize_lifecycle="yes",  # type: ignore[arg-type]
            **_available(),
        )

    with pytest.raises(AgentRuntimeWorkerError):
        run_bounded_agent_runtime_worker(
            config=config,
            assignment_source=SequenceSource(()),
            handler=lambda _assignment: {},
            lifecycle=_lifecycle(_profile(worker_id="different-worker")),
            max_cycles=1,
            **_available(),
        )

    with pytest.raises(AgentRuntimeWorkerError):
        run_bounded_agent_runtime_worker(
            config=config,
            assignment_source=SequenceSource(()),
            handler=lambda _assignment: {},
            lifecycle=_lifecycle(config.profile),
            max_cycles=1,
            stop_on_failure="yes",  # type: ignore[arg-type]
            **_available(),
        )


def test_bounded_worker_continues_after_untyped_failure_and_sleeps() -> None:
    config = _config(poll_interval_seconds=0.25)
    lifecycle = _lifecycle(config.profile)
    sleeps: list[float] = []
    result = run_bounded_agent_runtime_worker(
        config=config,
        assignment_source=SequenceSource((_assignment(), None)),
        handler=lambda _assignment: None,  # type: ignore[return-value]
        lifecycle=lifecycle,
        max_cycles=2,
        stop_on_failure=False,
        clock=IncrementingClock(),
        sleeper=sleeps.append,
        **_available(),
    )

    assert result["failed_count"] == 1
    assert result["executions"][0]["error_code"] == ("ae.agent_runtime_worker.invalid")
    assert result["idle_cycle_count"] == 1
    assert sleeps == []

    idle_result = run_bounded_agent_runtime_worker(
        config=config,
        assignment_source=SequenceSource((None, None)),
        handler=lambda _assignment: {},
        lifecycle=_lifecycle(config.profile),
        max_cycles=2,
        clock=IncrementingClock(),
        sleeper=sleeps.append,
        **_available(),
    )
    assert idle_result["idle_cycle_count"] == 2
    assert sleeps == [0.25]


def test_worker_check_and_cli_are_fail_closed_until_composition_exists() -> None:
    disabled = build_agent_runtime_worker_check(_config(mode="disabled"))
    assert disabled["status"] == "PASS"
    assert disabled["execution_composed"] is False

    enabled = build_agent_runtime_worker_check(_config(), **_available())
    assert enabled["status"] == "PASS"
    assert enabled["execution_composed"] is True

    missing = build_agent_runtime_worker_check(_config())
    assert missing["status"] == "FAIL"
    assert missing["failure_code"] == "ae.agent_runtime_worker.executor_unavailable"

    output = io.StringIO()
    assert main(["--check", "--summary"], environ={}, stdout=output) == 0
    assert "p6_s0_agent_runtime_worker=pass" in output.getvalue()

    output = io.StringIO()
    assert main([], environ={}, stdout=output) == 2
    assert "execution_handler_unavailable" in output.getvalue()

    output = io.StringIO()
    assert (
        main(
            ["--check"],
            environ={
                "NEX_AE_AGENT_WORKER_MODE": "enabled",
                "NEX_AE_AGENT_WORKER_BACKEND_PROFILES": (
                    NSL_V01_PROCESS_ISOLATED_BACKEND
                ),
            },
            stdout=output,
            **_available(),
        )
        == 0
    )
    assert '"status": "PASS"' in output.getvalue()

    output = io.StringIO()
    assert (
        main(
            ["--check"],
            environ={"NEX_AE_AGENT_WORKER_LEASE_SECONDS": "invalid"},
            stdout=output,
        )
        == 2
    )
    assert (
        "config_invalid" not in output.getvalue()
        or '"status": "FAIL"' in output.getvalue()
    )


def test_signal_adapter_requests_shutdown_and_restores_handlers(monkeypatch) -> None:
    installed: dict[int, Any] = {}
    restored: dict[int, Any] = {}
    previous = {
        worker_module.signal.SIGINT: "old-int",
        worker_module.signal.SIGTERM: "old-term",
    }
    monkeypatch.setattr(
        worker_module.signal, "getsignal", lambda signum: previous[signum]
    )

    def set_handler(signum, handler):
        if callable(handler):
            installed[signum] = handler
        else:
            restored[signum] = handler

    monkeypatch.setattr(worker_module.signal, "signal", set_handler)
    token = AgentRuntimeShutdownToken()
    captured = install_agent_runtime_worker_signal_handlers(token)
    installed[worker_module.signal.SIGTERM](worker_module.signal.SIGTERM, None)

    assert token.requested is True
    assert token.reason_code == "SIGTERM"
    restore_agent_runtime_worker_signal_handlers(captured)
    assert restored == previous


def test_helper_validation_covers_invalid_types_and_hashes() -> None:
    record = _profile().to_record()
    for changed in (
        {**record, "supported_executor_kinds": "LOCAL_SKILL"},
        {**record, "process_isolation_required": "yes"},
        {**record, "declared_at": "2026-10-14T09:00:00"},
    ):
        with pytest.raises(AgentRuntimeWorkerError):
            validate_agent_runtime_worker_profile(changed)

    with pytest.raises(AgentRuntimeWorkerError):
        project_agent_runtime_worker_readiness(
            None, expected_profile_hash="sha256:not-a-hash"
        )
    with pytest.raises(AgentRuntimeWorkerError):
        project_agent_runtime_worker_readiness(
            None, expected_profile_hash="sha256:" + "z" * 64
        )
    with pytest.raises(AgentRuntimeWorkerError):
        validate_agent_runtime_assignment("invalid", _profile())  # type: ignore[arg-type]
