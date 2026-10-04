from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol


class MigrationGate(Protocol):
    def __call__(self) -> Any: ...


class PoolLifecycle(Protocol):
    def engine_identity_tokens(self) -> frozenset[int]: ...

    def dispose(self) -> Mapping[str, Any]: ...


class ManagedRuntime(Protocol):
    def start(self) -> Mapping[str, Any]: ...

    def stop(self) -> Mapping[str, Any]: ...

    def check_running(self) -> Mapping[str, Any]: ...


PoolLifecycleFactory = Callable[[], PoolLifecycle]
RuntimeFactory = Callable[[], ManagedRuntime]


class PostgresRestartCoordinatorError(RuntimeError):
    def __init__(self, failure_code: str, status: Mapping[str, Any]) -> None:
        self.failure_code = failure_code
        self.status = dict(status)
        super().__init__(failure_code)


class PlatformPostgresRestartCoordinator:
    def __init__(
        self,
        *,
        migration_gate: MigrationGate,
        pool_factory: PoolLifecycleFactory,
        runtime_factory: RuntimeFactory,
    ) -> None:
        self._migration_gate = migration_gate
        self._pool_factory = pool_factory
        self._runtime_factory = runtime_factory
        self._pool: PoolLifecycle | None = None
        self._runtime: ManagedRuntime | None = None
        self._active_engine_tokens: frozenset[int] = frozenset()
        self._state = "NEW"
        self._generation = 0
        self._restart_count = 0
        self._migration_gate_count = 0
        self._fresh_engine_count = 0
        self._failure_code: str | None = None
        self._transitions = ["NEW"]
        self._last_shutdown_order: list[str] = []

    def start(self) -> dict[str, Any]:
        self._require_state("NEW", "coordinator_start_state_invalid")
        self._transition("STARTING")
        self._activate(previous_tokens=frozenset())
        return self.public_status()

    def restart(self) -> dict[str, Any]:
        self._require_state("RUNNING", "coordinator_restart_state_invalid")
        if self._restart_count >= 1:
            self._reject("coordinator_restart_limit_exceeded")
        self._restart_count += 1
        previous_tokens = self._active_engine_tokens
        self._transition("RESTARTING")
        self._shutdown_or_fail()
        self._activate(previous_tokens=previous_tokens)
        return self.public_status()

    def stop(self) -> dict[str, Any]:
        if self._state == "STOPPED":
            return self.public_status()
        self._require_state("RUNNING", "coordinator_stop_state_invalid")
        self._transition("STOPPING")
        self._shutdown_or_fail()
        self._transition("STOPPED")
        return self.public_status()

    def check_running(self) -> dict[str, Any]:
        self._require_state("RUNNING", "coordinator_check_state_invalid")
        assert self._runtime is not None
        try:
            status = self._runtime.check_running()
            if status.get("state") != "RUNNING":
                raise ValueError("runtime_not_running")
        except Exception as exc:
            self._cleanup_after_failure()
            self._fail("coordinator_runtime_health_failed", cause=exc)
        return self.public_status()

    def public_status(self) -> dict[str, Any]:
        return {
            "schema_version": "platform_postgres_restart_coordinator.v1",
            "requirement": "S133",
            "profile": "test",
            "state": self._state,
            "generation": self._generation,
            "restart_count": self._restart_count,
            "migration_gate_count": self._migration_gate_count,
            "active_engine_count": len(self._active_engine_tokens),
            "fresh_engine_count": self._fresh_engine_count,
            "failure_code": self._failure_code,
            "transitions": list(self._transitions),
            "last_shutdown_order": list(self._last_shutdown_order),
        }

    def _activate(self, *, previous_tokens: frozenset[int]) -> None:
        try:
            self._migration_gate_count += 1
            self._migration_gate()
        except Exception as exc:
            self._fail("coordinator_migration_gate_failed", cause=exc)

        try:
            pool = self._pool_factory()
            self._pool = pool
            tokens = pool.engine_identity_tokens()
            if not tokens:
                raise ValueError("pool_tokens_empty")
            if previous_tokens.intersection(tokens):
                raise ValueError("pool_engine_reused")
            self._active_engine_tokens = tokens
            self._fresh_engine_count = len(tokens.difference(previous_tokens))
        except Exception as exc:
            self._cleanup_after_failure()
            failure_code = (
                "coordinator_pool_freshness_failed"
                if str(exc) == "pool_engine_reused"
                else "coordinator_pool_start_failed"
            )
            self._fail(failure_code, cause=exc)

        try:
            runtime = self._runtime_factory()
            self._runtime = runtime
            status = runtime.start()
            if status.get("state") != "RUNNING":
                raise ValueError("runtime_not_running")
        except Exception as exc:
            self._cleanup_after_failure()
            self._fail("coordinator_runtime_start_failed", cause=exc)

        self._generation += 1
        self._transition("RUNNING")

    def _shutdown_or_fail(self) -> None:
        failures = self._shutdown()
        if failures:
            self._fail(failures[0])

    def _shutdown(self) -> list[str]:
        failures: list[str] = []
        self._last_shutdown_order = []
        if self._runtime is not None:
            self._last_shutdown_order.append("runtime_processes")
            try:
                status = self._runtime.stop()
                if status.get("state") != "STOPPED":
                    raise ValueError("runtime_not_stopped")
            except Exception:
                failures.append("coordinator_runtime_stop_failed")
            finally:
                self._runtime = None
        if self._pool is not None:
            self._last_shutdown_order.append("postgres_pools")
            try:
                status = self._pool.dispose()
                if status.get("state") != "DISPOSED":
                    raise ValueError("pool_not_disposed")
            except Exception:
                failures.append("coordinator_pool_disposal_failed")
            finally:
                self._pool = None
                self._active_engine_tokens = frozenset()
        return failures

    def _cleanup_after_failure(self) -> None:
        self._shutdown()

    def _require_state(self, expected: str, failure_code: str) -> None:
        if self._state != expected:
            self._reject(failure_code)

    def _reject(self, failure_code: str) -> None:
        status = self.public_status()
        status["failure_code"] = failure_code
        raise PostgresRestartCoordinatorError(failure_code, status)

    def _transition(self, state: str) -> None:
        self._state = state
        self._transitions.append(state)

    def _fail(self, failure_code: str, *, cause: Exception | None = None) -> None:
        self._failure_code = failure_code
        self._transition("FAILED")
        error = PostgresRestartCoordinatorError(failure_code, self.public_status())
        if cause is None:
            raise error
        raise error from cause
