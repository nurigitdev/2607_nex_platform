from __future__ import annotations

from dataclasses import dataclass
import json

import pytest

import run_platform_postgres_restart_smoke as smoke
from nex_runtime.postgres_restoration import (
    PostgresRestorationBatchResult,
    PostgresRestorationError,
)


@dataclass(frozen=True)
class Service:
    migration_count: int


@dataclass(frozen=True)
class Migration:
    services: tuple[Service, ...] = (
        Service(17),
        Service(18),
        Service(20),
        Service(18),
        Service(16),
    )


class Pool:
    def __init__(self, generation: int) -> None:
        self.generation = generation

    def engine_identity_tokens(self):
        start = self.generation * 10
        return frozenset(range(start, start + 10))

    def dispose(self):
        return {"state": "DISPOSED"}


class Pools:
    count = 0

    @classmethod
    def build(cls, env):
        cls.count += 1
        return Pool(cls.count)


class Runtime:
    instances = []
    fail_start_generation: int | None = None
    fail_stop_generation: int | None = None

    def __init__(self, manifest, *, launcher, environ) -> None:
        del manifest, launcher, environ
        self.generation = len(self.instances) + 1
        self.state = "NEW"
        self.instances.append(self)

    @classmethod
    def reset(cls):
        cls.instances = []
        cls.fail_start_generation = None
        cls.fail_stop_generation = None

    def start(self):
        if self.generation == self.fail_start_generation:
            raise RuntimeError("private runtime failure")
        self.state = "RUNNING"
        return self.public_status()

    def check_running(self):
        return self.public_status()

    def stop(self):
        if self.generation == self.fail_stop_generation:
            raise RuntimeError("private stop failure")
        self.state = "STOPPED"
        return self.public_status()

    def public_status(self):
        return {
            "state": self.state,
            "process_counts": {
                "READY": smoke.EXPECTED_PROCESS_COUNT if self.state == "RUNNING" else 0
            },
        }


class Store:
    failure_phase: str | None = None
    calls: list[str] = []

    @classmethod
    def build(cls, env):
        cls.calls.append("build")
        return cls()

    @classmethod
    def reset(cls):
        cls.failure_phase = None
        cls.calls = []

    def _result(self, phase):
        self.calls.append(phase)
        if self.failure_phase == phase:
            raise PostgresRestorationError(f"{phase.lower()}_failed", "nex-cx")
        return PostgresRestorationBatchResult(phase, 5, 5)

    def write(self, run_id):
        return self._result("WRITE")

    def restore(self, run_id):
        return self._result("RESTORE")

    def cleanup(self, run_id):
        return self._result("CLEANUP")

    def confirm_absence(self, run_id):
        return self._result("ABSENCE")


def configure(monkeypatch, *, migration=None) -> None:
    Pools.count = 0
    Runtime.reset()
    Store.reset()
    monkeypatch.setattr(smoke, "PlatformPostgresPoolLifecycle", Pools)
    monkeypatch.setattr(smoke, "RuntimeOrchestrator", Runtime)
    monkeypatch.setattr(smoke, "PlatformPostgresRestorationStore", Store)
    monkeypatch.setattr(smoke, "build_platform_runtime_manifest", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        smoke,
        "run_platform_test_migration_readiness",
        migration or (lambda env: Migration()),
    )


def ports():
    value = 18000

    def allocate():
        nonlocal value
        value += 1
        return value

    return allocate


def test_skip_success_summary_and_complete_evidence(monkeypatch) -> None:
    assert smoke.run_smoke({})["status"] == "SKIPPED"
    configure(monkeypatch)

    result = smoke.run_smoke(
        {smoke.SMOKE_ENV: "1"}, port_allocator=ports()
    )

    assert result["status"] == "PASS"
    assert result["service_count"] == 5
    assert result["process_count"] == 13
    assert result["process_generation_count"] == 2
    assert result["pool_count_per_generation"] == 10
    assert result["fresh_pool_count"] == 10
    assert result["migration_gate_count"] == 2
    assert result["migration_count_per_generation"] == 89
    assert result["restart_count"] == 1
    assert result["restored_count"] == 5
    assert result["cleaned_count"] == 5
    assert result["absence_count"] == 5
    assert result["evidence_record_count"] == 60
    assert result["shutdown_order"] == ["runtime_processes", "postgres_pools"]
    assert Store.calls == ["build", "WRITE", "RESTORE", "CLEANUP", "ABSENCE"]
    assert smoke.summary_line(result) == (
        "platform_postgres_restart=pass services=5 processes=13x2 "
        "pools=10+10 restored=5 next=1331"
    )
    assert "s133-" not in str(result)
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skip")


def test_restart_environment_allocates_endpoints_and_preserves_trust(monkeypatch) -> None:
    first_trust = smoke.SIGNED_TRUST_ENV_NAMES[0]
    env = smoke._restart_environment({first_trust: "preserved"}, ports())

    assert env["NEX_PROFILE"] == "test"
    assert env[first_trust] == "preserved"
    assert all(env[name] for name in smoke.SIGNED_TRUST_ENV_NAMES)
    endpoint_names = [item[0] for item in smoke.SERVICE_ENDPOINTS.values()]
    assert len({env[name] for name in endpoint_names}) == len(endpoint_names)
    assert env["NEX_AE_WEB_BASE_URL"].startswith("http://127.0.0.1:")


def test_runtime_readiness_validation_rejects_state_and_count() -> None:
    class BadRuntime:
        def __init__(self, status):
            self.status = status

        def public_status(self):
            return self.status

    smoke._require_ready_runtime(
        BadRuntime({"state": "RUNNING", "process_counts": {"READY": 13}}),
        generation=1,
    )
    with pytest.raises(ValueError, match="generation_1_not_ready"):
        smoke._require_ready_runtime(
            BadRuntime({"state": "STOPPED", "process_counts": {"READY": 13}}),
            generation=1,
        )
    with pytest.raises(ValueError, match="generation_2_not_ready"):
        smoke._require_ready_runtime(
            BadRuntime({"state": "RUNNING", "process_counts": {"READY": 12}}),
            generation=2,
        )


def test_known_restoration_failure_stops_runtime_and_cleans_sentinel(monkeypatch) -> None:
    configure(monkeypatch)
    Store.failure_phase = "RESTORE"

    result = smoke.run_smoke(
        {smoke.SMOKE_ENV: "1"}, port_allocator=ports()
    )

    assert result == {
        "schema_version": "platform_postgres_restart_smoke.v1",
        "status": "FAIL",
        "failure_code": "restore_failed",
        "service_id": "nex-cx",
    }
    assert all(runtime.state == "STOPPED" for runtime in Runtime.instances)
    assert Store.calls[-2:] == ["CLEANUP", "ABSENCE"]
    assert smoke.summary_line(result).endswith("service=nex-cx code=restore_failed")


def test_runtime_start_and_unexpected_failures_are_normalized(monkeypatch) -> None:
    configure(monkeypatch)
    Runtime.fail_start_generation = 2
    failed = smoke.run_smoke(
        {smoke.SMOKE_ENV: "1"}, port_allocator=ports()
    )
    assert failed["failure_code"] == "coordinator_runtime_start_failed"
    assert Store.calls[-2:] == ["CLEANUP", "ABSENCE"]

    configure(monkeypatch)
    monkeypatch.setattr(
        smoke,
        "build_platform_runtime_manifest",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    failed = smoke.run_smoke(
        {smoke.SMOKE_ENV: "1"}, port_allocator=ports()
    )
    assert failed["failure_code"] == "coordinator_runtime_start_failed"
    assert "private" not in str(failed)


def test_store_build_and_best_effort_cleanup_failures(monkeypatch) -> None:
    configure(monkeypatch)
    original_build = Store.__dict__["build"]
    monkeypatch.setattr(
        Store,
        "build",
        classmethod(
            lambda cls, env: (_ for _ in ()).throw(
                PostgresRestorationError("configuration_invalid")
            )
        ),
    )
    failed = smoke.run_smoke(
        {smoke.SMOKE_ENV: "1"}, port_allocator=ports()
    )
    assert failed["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        Store,
        "build",
        classmethod(
            lambda cls, env: (_ for _ in ()).throw(RuntimeError("private"))
        ),
    )
    failed = smoke.run_smoke(
        {smoke.SMOKE_ENV: "1"}, port_allocator=ports()
    )
    assert failed["failure_code"] == "platform_postgres_restart_failed"
    assert failed["service_id"] == "RuntimeError"
    assert "private" not in str(failed)

    monkeypatch.setattr(Store, "build", original_build)
    configure(monkeypatch)
    Store.failure_phase = "RESTORE"
    original_cleanup = Store.cleanup
    monkeypatch.setattr(
        Store,
        "cleanup",
        lambda self, run_id: (_ for _ in ()).throw(
            PostgresRestorationError("cleanup_failed")
        ),
    )
    failed = smoke.run_smoke(
        {smoke.SMOKE_ENV: "1"}, port_allocator=ports()
    )
    monkeypatch.setattr(Store, "cleanup", original_cleanup)
    assert failed["failure_code"] == "restore_failed"


def test_best_effort_runtime_stop_failure_preserves_primary_failure(monkeypatch) -> None:
    configure(monkeypatch)
    Store.failure_phase = "RESTORE"
    Runtime.fail_stop_generation = 2

    failed = smoke.run_smoke(
        {smoke.SMOKE_ENV: "1"}, port_allocator=ports()
    )

    assert failed["failure_code"] == "restore_failed"


def test_free_port_failure_projection_and_main(monkeypatch, capsys) -> None:
    port = smoke._free_port()
    assert isinstance(port, int) and port > 0
    assert smoke._failure("failed", None)["status"] == "FAIL"
    assert smoke.summary_line({"status": "FAIL"}).endswith(
        "service=none code=failed"
    )

    passing = {
        "status": "PASS",
        "service_count": 5,
        "process_count": 13,
        "process_generation_count": 2,
        "pool_count_per_generation": 10,
        "fresh_pool_count": 10,
        "restored_count": 5,
        "next_slice": "1331",
    }
    monkeypatch.setattr(smoke, "run_smoke", lambda: passing)
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    assert smoke.main(["--summary"]) == 0
    assert "processes=13x2" in capsys.readouterr().out
    monkeypatch.setattr(smoke, "run_smoke", lambda: {"status": "FAIL"})
    assert smoke.main([]) == 1


@pytest.mark.skipif(
    smoke.os.getenv(smoke.SMOKE_ENV) != "1",
    reason=f"{smoke.SMOKE_ENV}=1 is required",
)
def test_actual_platform_postgres_restart() -> None:
    result = smoke.run_smoke()

    assert result["status"] == "PASS", result
    assert result["service_count"] == 5
    assert result["process_generation_count"] == 2
    assert result["pool_count_per_generation"] == 10
    assert result["fresh_pool_count"] == 10
    assert result["migration_gate_count"] == 2
    assert result["restored_count"] == 5
    assert result["cleaned_count"] == 5
