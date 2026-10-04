from __future__ import annotations

from collections.abc import Callable

import pytest

from nex_runtime.postgres_restart_coordinator import (
    PlatformPostgresRestartCoordinator,
    PostgresRestartCoordinatorError,
)


class Pool:
    def __init__(
        self,
        tokens: frozenset[int],
        log: list[str],
        *,
        dispose_error: bool = False,
        dispose_state: str = "DISPOSED",
    ) -> None:
        self.tokens = tokens
        self.log = log
        self.dispose_error = dispose_error
        self.dispose_state = dispose_state
        self.dispose_count = 0

    def engine_identity_tokens(self) -> frozenset[int]:
        return self.tokens

    def dispose(self):
        self.log.append("pool.dispose")
        self.dispose_count += 1
        if self.dispose_error:
            raise RuntimeError("private pool detail")
        return {"state": self.dispose_state}


class Runtime:
    def __init__(
        self,
        log: list[str],
        *,
        start_error: bool = False,
        start_state: str = "RUNNING",
        stop_error: bool = False,
        stop_state: str = "STOPPED",
        check_error: bool = False,
        check_state: str = "RUNNING",
    ) -> None:
        self.log = log
        self.start_error = start_error
        self.start_state = start_state
        self.stop_error = stop_error
        self.stop_state = stop_state
        self.check_error = check_error
        self.check_state = check_state

    def start(self):
        self.log.append("runtime.start")
        if self.start_error:
            raise RuntimeError("private runtime detail")
        return {"state": self.start_state}

    def stop(self):
        self.log.append("runtime.stop")
        if self.stop_error:
            raise RuntimeError("private runtime detail")
        return {"state": self.stop_state}

    def check_running(self):
        self.log.append("runtime.check")
        if self.check_error:
            raise RuntimeError("private runtime detail")
        return {"state": self.check_state}


def coordinator(
    *,
    gate: Callable[[], object] = lambda: object(),
    pools: list[Pool] | None = None,
    runtimes: list[Runtime] | None = None,
):
    pool_items = pools or [Pool(frozenset(range(10)), [])]
    runtime_items = runtimes or [Runtime([])]
    return PlatformPostgresRestartCoordinator(
        migration_gate=gate,
        pool_factory=lambda: pool_items.pop(0),
        runtime_factory=lambda: runtime_items.pop(0),
    )


def test_start_check_restart_stop_enforces_order_and_fresh_resources() -> None:
    log: list[str] = []
    migrations: list[str] = []
    first_pool = Pool(frozenset(range(10)), log)
    second_pool = Pool(frozenset(range(10, 20)), log)
    first_runtime = Runtime(log)
    second_runtime = Runtime(log)
    runner = coordinator(
        gate=lambda: migrations.append("migration"),
        pools=[first_pool, second_pool],
        runtimes=[first_runtime, second_runtime],
    )

    started = runner.start()
    assert started["state"] == "RUNNING"
    assert started["generation"] == 1
    assert started["active_engine_count"] == 10
    assert runner.check_running()["state"] == "RUNNING"

    restarted = runner.restart()
    assert restarted["state"] == "RUNNING"
    assert restarted["generation"] == 2
    assert restarted["restart_count"] == 1
    assert restarted["migration_gate_count"] == 2
    assert restarted["fresh_engine_count"] == 10
    assert restarted["last_shutdown_order"] == [
        "runtime_processes",
        "postgres_pools",
    ]

    stopped = runner.stop()
    assert stopped["state"] == "STOPPED"
    assert stopped["active_engine_count"] == 0
    assert stopped["transitions"] == [
        "NEW",
        "STARTING",
        "RUNNING",
        "RESTARTING",
        "RUNNING",
        "STOPPING",
        "STOPPED",
    ]
    assert runner.stop() == stopped
    assert migrations == ["migration", "migration"]
    assert log == [
        "runtime.start",
        "runtime.check",
        "runtime.stop",
        "pool.dispose",
        "runtime.start",
        "runtime.stop",
        "pool.dispose",
    ]


@pytest.mark.parametrize(
    ("operation", "failure_code"),
    [
        ("restart", "coordinator_restart_state_invalid"),
        ("stop", "coordinator_stop_state_invalid"),
        ("check_running", "coordinator_check_state_invalid"),
    ],
)
def test_invalid_new_state_commands_are_rejected_without_state_mutation(
    operation: str,
    failure_code: str,
) -> None:
    runner = coordinator()

    with pytest.raises(PostgresRestartCoordinatorError) as raised:
        getattr(runner, operation)()

    assert raised.value.failure_code == failure_code
    assert raised.value.status["failure_code"] == failure_code
    assert runner.public_status()["state"] == "NEW"


def test_duplicate_start_and_second_restart_are_rejected_but_runtime_survives() -> None:
    pools = [Pool(frozenset({1}), []), Pool(frozenset({2}), [])]
    runner = coordinator(pools=pools, runtimes=[Runtime([]), Runtime([])])
    runner.start()

    with pytest.raises(PostgresRestartCoordinatorError, match="start_state_invalid"):
        runner.start()
    assert runner.public_status()["state"] == "RUNNING"

    runner.restart()
    with pytest.raises(PostgresRestartCoordinatorError, match="restart_limit_exceeded"):
        runner.restart()
    assert runner.public_status()["state"] == "RUNNING"
    runner.stop()


def test_migration_and_pool_start_failures_are_normalized_and_private() -> None:
    runner = coordinator(
        gate=lambda: (_ for _ in ()).throw(RuntimeError("secret migration"))
    )
    with pytest.raises(PostgresRestartCoordinatorError) as migration_failure:
        runner.start()
    assert migration_failure.value.failure_code == "coordinator_migration_gate_failed"
    assert "secret" not in str(migration_failure.value.status)

    runner = PlatformPostgresRestartCoordinator(
        migration_gate=lambda: None,
        pool_factory=lambda: (_ for _ in ()).throw(RuntimeError("secret pool")),
        runtime_factory=lambda: Runtime([]),
    )
    with pytest.raises(PostgresRestartCoordinatorError) as pool_failure:
        runner.start()
    assert pool_failure.value.failure_code == "coordinator_pool_start_failed"
    assert "secret" not in str(pool_failure.value.status)


@pytest.mark.parametrize("tokens", [frozenset(), frozenset({7})])
def test_empty_and_reused_pool_tokens_fail_closed_and_dispose(tokens) -> None:
    first_pool = Pool(frozenset({7}), [])
    second_pool = Pool(tokens, [])
    runner = coordinator(
        pools=[first_pool, second_pool],
        runtimes=[Runtime([]), Runtime([])],
    )
    runner.start()

    with pytest.raises(PostgresRestartCoordinatorError) as raised:
        runner.restart()

    expected = (
        "coordinator_pool_start_failed"
        if not tokens
        else "coordinator_pool_freshness_failed"
    )
    assert raised.value.failure_code == expected
    assert second_pool.dispose_count == 1
    assert runner.public_status()["state"] == "FAILED"


@pytest.mark.parametrize(
    "runtime",
    [Runtime([], start_error=True), Runtime([], start_state="STARTING")],
)
def test_runtime_start_failure_disposes_pool(runtime: Runtime) -> None:
    pool = Pool(frozenset({1}), [])
    runner = coordinator(pools=[pool], runtimes=[runtime])

    with pytest.raises(PostgresRestartCoordinatorError) as raised:
        runner.start()

    assert raised.value.failure_code == "coordinator_runtime_start_failed"
    assert pool.dispose_count == 1
    assert runner.public_status()["active_engine_count"] == 0


@pytest.mark.parametrize(
    "runtime",
    [Runtime([], check_error=True), Runtime([], check_state="STOPPED")],
)
def test_runtime_health_failure_cleans_runtime_and_pool(runtime: Runtime) -> None:
    pool = Pool(frozenset({1}), [])
    runner = coordinator(pools=[pool], runtimes=[runtime])
    runner.start()

    with pytest.raises(PostgresRestartCoordinatorError) as raised:
        runner.check_running()

    assert raised.value.failure_code == "coordinator_runtime_health_failed"
    assert pool.dispose_count == 1
    assert runner.public_status()["state"] == "FAILED"


@pytest.mark.parametrize(
    ("runtime", "pool", "failure_code"),
    [
        (
            Runtime([], stop_error=True),
            Pool(frozenset({1}), [], dispose_error=True),
            "coordinator_runtime_stop_failed",
        ),
        (
            Runtime([], stop_state="RUNNING"),
            Pool(frozenset({1}), []),
            "coordinator_runtime_stop_failed",
        ),
        (
            Runtime([]),
            Pool(frozenset({1}), [], dispose_state="READY"),
            "coordinator_pool_disposal_failed",
        ),
    ],
)
def test_shutdown_failures_attempt_both_layers_and_report_first_failure(
    runtime: Runtime,
    pool: Pool,
    failure_code: str,
) -> None:
    log: list[str] = []
    runtime.log = log
    pool.log = log
    runner = coordinator(pools=[pool], runtimes=[runtime])
    runner.start()

    with pytest.raises(PostgresRestartCoordinatorError) as raised:
        runner.stop()

    assert raised.value.failure_code == failure_code
    assert log[-2:] == ["runtime.stop", "pool.dispose"]
    assert runner.public_status()["state"] == "FAILED"
