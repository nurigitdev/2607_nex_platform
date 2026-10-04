from __future__ import annotations

from dataclasses import dataclass
import json

import pytest

import run_platform_postgres_restoration as smoke
from nex_runtime.postgres_restoration import (
    PostgresRestorationBatchResult,
    PostgresRestorationError,
)
from platform_test_migrations import PlatformMigrationReadinessError


@dataclass(frozen=True)
class Service:
    migration_count: int


@dataclass(frozen=True)
class Migration:
    services: tuple[Service, ...] = (Service(17), Service(18), Service(20), Service(18), Service(16))


class Store:
    failure_phase: str | None = None
    calls: list[str] = []

    @classmethod
    def build(cls, env):
        cls.calls.append("build")
        return cls()

    @classmethod
    def reset(cls, failure_phase=None):
        cls.failure_phase = failure_phase
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


def configure(monkeypatch, *, migration=None):
    monkeypatch.setattr(
        smoke,
        "run_platform_test_migration_readiness",
        migration or (lambda env: Migration()),
    )
    monkeypatch.setattr(smoke, "PlatformPostgresRestorationStore", Store)


def test_skip_success_summary_and_privacy(monkeypatch) -> None:
    assert smoke.run_smoke({})["status"] == "SKIPPED"

    Store.reset()
    configure(monkeypatch)
    result = smoke.run_smoke({smoke.SMOKE_ENV: "1"})

    assert result["status"] == "PASS"
    assert result["migration_count"] == 89
    assert result["fresh_connection_count"] == 20
    assert Store.calls == ["build", "WRITE", "RESTORE", "CLEANUP", "ABSENCE"]
    assert smoke.summary_line(result) == (
        "platform_postgres_restoration=pass services=5 restored=5 "
        "cleaned=5 connections=20 next=1330"
    )
    assert "run_id" not in str(result)
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skip")


def test_migration_and_unexpected_failures_are_normalized(monkeypatch) -> None:
    configure(
        monkeypatch,
        migration=lambda env: (_ for _ in ()).throw(
            PlatformMigrationReadinessError("migration_failed", "nex-mo")
        ),
    )
    failed = smoke.run_smoke({smoke.SMOKE_ENV: "1"})
    assert failed["failure_code"] == "migration_failed"
    assert failed["service_id"] == "nex-mo"

    monkeypatch.setattr(
        smoke,
        "run_platform_test_migration_readiness",
        lambda env: (_ for _ in ()).throw(RuntimeError("private detail")),
    )
    failed = smoke.run_smoke({smoke.SMOKE_ENV: "1"})
    assert failed["failure_code"] == "postgres_restoration_failed"
    assert failed["service_id"] == "RuntimeError"
    assert "private" not in str(failed)


@pytest.mark.parametrize("phase", ["WRITE", "RESTORE", "CLEANUP", "ABSENCE"])
def test_phase_failures_cleanup_when_a_write_may_exist(monkeypatch, phase) -> None:
    Store.reset(phase)
    configure(monkeypatch)

    failed = smoke.run_smoke({smoke.SMOKE_ENV: "1"})

    assert failed["status"] == "FAIL"
    assert failed["failure_code"] == f"{phase.lower()}_failed"
    if phase == "RESTORE":
        assert Store.calls[-2:] == ["CLEANUP", "ABSENCE"]
    if phase == "CLEANUP":
        assert Store.calls.count("CLEANUP") == 2


def test_best_effort_cleanup_failure_is_suppressed(monkeypatch) -> None:
    Store.reset("RESTORE")
    configure(monkeypatch)
    original = Store.cleanup

    def fail_cleanup(self, run_id):
        self.calls.append("CLEANUP")
        raise PostgresRestorationError("cleanup_failed", "nex-cx")

    monkeypatch.setattr(Store, "cleanup", fail_cleanup)
    failed = smoke.run_smoke({smoke.SMOKE_ENV: "1"})
    monkeypatch.setattr(Store, "cleanup", original)

    assert failed["failure_code"] == "restore_failed"


def test_main_json_summary_and_failure(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "service_count": 5,
        "restored_count": 5,
        "cleaned_count": 5,
        "fresh_connection_count": 20,
        "next_slice": "1330",
    }
    monkeypatch.setattr(smoke, "run_smoke", lambda: passing)
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    assert smoke.main(["--summary"]) == 0
    assert "connections=20" in capsys.readouterr().out

    monkeypatch.setattr(smoke, "run_smoke", lambda: {"status": "FAIL"})
    assert smoke.main([]) == 1
    assert "service=none" in smoke.summary_line({"status": "FAIL"})


@pytest.mark.skipif(
    smoke.os.getenv(smoke.SMOKE_ENV) != "1",
    reason=f"{smoke.SMOKE_ENV}=1 is required",
)
def test_actual_platform_postgres_restoration() -> None:
    result = smoke.run_smoke()

    assert result["status"] == "PASS", result
    assert result["service_count"] == 5
    assert result["restored_count"] == 5
    assert result["cleaned_count"] == 5
    assert result["absence_count"] == 5
