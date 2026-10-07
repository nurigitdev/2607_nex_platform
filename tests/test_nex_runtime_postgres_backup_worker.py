from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import pytest

import nex_runtime.postgres_backup_worker as worker_module
from nex_runtime.postgres_backup import PostgresBackupError
from nex_runtime.postgres_backup_worker import (
    BACKUP_WORKER_STATE_SCHEMA_VERSION,
    PostgresBackupWorkerError,
    backup_worker_public_projection,
    run_postgres_backup_worker,
)
from nex_runtime.postgres_resilience import EXPECTED_SERVICE_IDS


RUN_ID = "20261008T000000Z-1234abcd"
NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def _directories(tmp_path: Path) -> tuple[Path, ...]:
    return tuple(tmp_path / service_id for service_id in EXPECTED_SERVICE_IDS)


def _clock(start: datetime = NOW):
    tick = 0

    def current() -> datetime:
        nonlocal tick
        value = start + timedelta(seconds=tick)
        tick += 1
        return value

    return current


def _success(_attempt: int) -> dict[str, str]:
    return {service_id: "CREATED" for service_id in EXPECTED_SERVICE_IDS}


def _run(tmp_path: Path, **overrides):
    values = {
        "run_id": RUN_ID,
        "state_root": tmp_path / "state",
        "service_directories": _directories(tmp_path),
        "executor": _success,
        "clock": _clock(),
    }
    values.update(overrides)
    return run_postgres_backup_worker(**values)


def test_worker_persists_success_and_replays_without_execution(tmp_path: Path) -> None:
    result = _run(tmp_path)
    state_path = tmp_path / "state" / f"{RUN_ID}.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["schema_version"] == BACKUP_WORKER_STATE_SCHEMA_VERSION
    assert state["state"] == "SUCCEEDED"
    assert state["attempt_count"] == 1
    assert oct(state_path.stat().st_mode & 0o777) == "0o600"
    assert oct(state_path.parent.stat().st_mode & 0o777) == "0o700"

    replay = _run(
        tmp_path,
        executor=lambda _attempt: (_ for _ in ()).throw(AssertionError("replayed")),
    )
    assert replay == result
    projection = backup_worker_public_projection(result)
    assert projection["service_count"] == 5
    assert projection["state"] == "SUCCEEDED"
    assert "completed_at" not in projection


def test_worker_retries_only_retryable_errors_with_bounded_backoff(tmp_path: Path) -> None:
    attempts: list[int] = []
    sleeps: list[float] = []

    def executor(attempt: int):
        attempts.append(attempt)
        if attempt < 3:
            raise PostgresBackupError("pg_dump_failed")
        return {service_id: "VERIFIED" for service_id in EXPECTED_SERVICE_IDS}

    result = _run(tmp_path, executor=executor, sleeper=sleeps.append)
    assert result.attempt_count == 3
    assert attempts == [1, 2, 3]
    assert sleeps == [1.0, 2.0]


def test_worker_records_terminal_failure_without_unsafe_retry(tmp_path: Path) -> None:
    calls = 0

    def executor(_attempt: int):
        nonlocal calls
        calls += 1
        raise PostgresBackupError("backup_id_already_exists")

    with pytest.raises(PostgresBackupWorkerError, match="backup_id_already_exists"):
        _run(tmp_path, executor=executor)
    assert calls == 1
    state = json.loads((tmp_path / "state" / f"{RUN_ID}.json").read_text())
    assert state["state"] == "FAILED"
    assert state["error_code"] == "backup_id_already_exists"

    replay = _run(tmp_path, executor=lambda _attempt: pytest.fail("must not retry"))
    assert replay.state == "FAILED"
    assert replay.attempt_count == 1


def test_worker_recovers_stale_run_and_quarantines_old_partials(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    old = NOW - timedelta(hours=1)
    state = {
        "schema_version": BACKUP_WORKER_STATE_SCHEMA_VERSION,
        "run_id": RUN_ID,
        "state": "RUNNING",
        "attempt_count": 1,
        "max_attempts": 3,
        "started_at": old.isoformat(),
        "updated_at": old.isoformat(),
        "completed_at": None,
        "service_states": {},
        "error_code": None,
        "recovered_stale_run": False,
        "quarantined_partial_count": 0,
    }
    (state_root / f"{RUN_ID}.json").write_text(json.dumps(state), encoding="utf-8")
    services = _directories(tmp_path)
    services[0].mkdir()
    partial = services[0] / ".dump.partial"
    partial.write_bytes(b"partial")
    timestamp = old.timestamp()
    os.utime(partial, (timestamp, timestamp))

    result = _run(tmp_path, service_directories=services, clock=_clock(NOW))
    assert result.state == "SUCCEEDED"
    assert result.attempt_count == 2
    assert result.recovered_stale_run is True
    assert result.quarantined_partial_count == 1
    assert not partial.exists()


def test_worker_rejects_fresh_running_state(tmp_path: Path) -> None:
    _write_state(tmp_path, state="RUNNING", updated_at=NOW)
    with pytest.raises(PostgresBackupWorkerError, match="backup_run_active"):
        _run(tmp_path, clock=lambda: NOW + timedelta(minutes=1))


def test_worker_resumes_retry_wait_after_restart(tmp_path: Path) -> None:
    _write_state(tmp_path, state="RETRY_WAIT", updated_at=NOW, attempt_count=1)
    result = _run(tmp_path, clock=_clock(NOW + timedelta(minutes=1)))
    assert result.state == "SUCCEEDED"
    assert result.attempt_count == 2

    exhausted = tmp_path / "exhausted"
    _write_state(exhausted, state="RETRY_WAIT", updated_at=NOW, attempt_count=3)
    with pytest.raises(PostgresBackupWorkerError, match="backup_worker_state_invalid"):
        _run(exhausted, clock=_clock(NOW + timedelta(minutes=1)))


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"run_id": "bad"}, "backup_run_id_invalid"),
        ({"service_directories": ()}, "backup_service_directories_incomplete"),
        ({"max_attempts": 0}, "backup_max_attempts_invalid"),
        ({"max_attempts": True}, "backup_max_attempts_invalid"),
        ({"max_attempts": 4}, "backup_max_attempts_invalid"),
        ({"stale_after": timedelta(minutes=4)}, "backup_stale_window_invalid"),
        ({"stale_after": timedelta(hours=7)}, "backup_stale_window_invalid"),
    ],
)
def test_worker_rejects_invalid_inputs(tmp_path: Path, overrides: dict, code: str) -> None:
    with pytest.raises(PostgresBackupWorkerError, match=code):
        _run(tmp_path, **overrides)


def test_worker_rejects_symlink_state_root_and_held_lock(tmp_path: Path, monkeypatch) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(PostgresBackupWorkerError, match="backup_state_root_symlink"):
        _run(tmp_path, state_root=linked)

    def held(*_args):
        raise BlockingIOError

    monkeypatch.setattr(worker_module.fcntl, "flock", held)
    with pytest.raises(PostgresBackupWorkerError, match="backup_worker_lock_held"):
        _run(tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "[]",
        json.dumps({"schema_version": "wrong"}),
    ],
)
def test_worker_rejects_corrupt_state(tmp_path: Path, payload: str) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    (state_root / f"{RUN_ID}.json").write_text(payload, encoding="utf-8")
    with pytest.raises(PostgresBackupWorkerError, match="backup_worker_state_invalid"):
        _run(tmp_path)


def test_worker_rejects_state_symlink_invalid_transition_and_timestamp(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    external = tmp_path / "external"
    external.write_text("{}", encoding="utf-8")
    (state_root / f"{RUN_ID}.json").symlink_to(external)
    with pytest.raises(PostgresBackupWorkerError, match="backup_worker_state_invalid"):
        _run(tmp_path)

    (state_root / f"{RUN_ID}.json").unlink()
    _write_state(tmp_path, state="PLANNED", updated_at=NOW)
    with pytest.raises(PostgresBackupWorkerError, match="backup_worker_state_invalid"):
        _run(tmp_path)

    _write_state(tmp_path, state="RUNNING", updated_at="bad")
    with pytest.raises(PostgresBackupWorkerError, match="backup_worker_timestamp_invalid"):
        _run(tmp_path)


def test_worker_rejects_invalid_service_results_and_naive_clock(tmp_path: Path) -> None:
    with pytest.raises(PostgresBackupWorkerError, match="backup_executor_failed"):
        _run(tmp_path, executor=lambda _attempt: {"nex-oa": "CREATED"})
    assert json.loads((tmp_path / "state" / f"{RUN_ID}.json").read_text())["error_code"] == "backup_executor_failed"

    with pytest.raises(PostgresBackupWorkerError, match="timestamp_not_timezone_aware"):
        _run(tmp_path / "naive", clock=lambda: datetime(2026, 10, 8))


def test_worker_cleans_atomic_state_partial_on_write_failure(tmp_path: Path, monkeypatch) -> None:
    def fail_dump(*_args, **_kwargs):
        raise OSError("simulated")

    monkeypatch.setattr(worker_module.json, "dump", fail_dump)
    with pytest.raises(OSError, match="simulated"):
        _run(tmp_path)
    assert list((tmp_path / "state").glob(".*.partial")) == []


def _write_state(
    tmp_path: Path,
    *,
    state: str,
    updated_at: datetime | str,
    attempt_count: int = 1,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(parents=True, exist_ok=True)
    stamp = updated_at if isinstance(updated_at, str) else updated_at.isoformat()
    payload = {
        "schema_version": BACKUP_WORKER_STATE_SCHEMA_VERSION,
        "run_id": RUN_ID,
        "state": state,
        "attempt_count": attempt_count,
        "max_attempts": 3,
        "started_at": NOW.isoformat(),
        "updated_at": stamp,
        "completed_at": None,
        "service_states": {},
        "error_code": None,
        "recovered_stale_run": False,
        "quarantined_partial_count": 0,
    }
    (state_root / f"{RUN_ID}.json").write_text(json.dumps(payload), encoding="utf-8")
