from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
from typing import Any, Iterator

from .postgres_backup import PostgresBackupError
from .postgres_backup_catalog import quarantine_stale_partials
from .postgres_resilience import EXPECTED_SERVICE_IDS


BACKUP_WORKER_STATE_SCHEMA_VERSION = "postgres_backup_worker_state.v1"
SAFE_RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8,32}$")
TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED"})
RETRYABLE_ERROR_CODES = frozenset({"pg_dump_failed", "backup_source_unavailable"})


class PostgresBackupWorkerError(RuntimeError):
    pass


@dataclass(frozen=True)
class PostgresBackupWorkerResult:
    run_id: str
    state: str
    attempt_count: int
    service_states: dict[str, str]
    recovered_stale_run: bool
    quarantined_partial_count: int


Executor = Callable[[int], Mapping[str, str]]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


def run_postgres_backup_worker(
    *,
    run_id: str,
    state_root: Path,
    service_directories: Sequence[Path],
    executor: Executor,
    clock: Clock,
    sleeper: Sleeper = lambda _seconds: None,
    max_attempts: int = 3,
    stale_after: timedelta = timedelta(minutes=30),
) -> PostgresBackupWorkerResult:
    _validate_inputs(run_id, state_root, service_directories, max_attempts, stale_after)
    now = _aware(clock())
    with _exclusive_lock(state_root, run_id):
        state_path = state_root / f"{run_id}.json"
        state = _load_state(state_path, run_id=run_id)
        if state and state["state"] in TERMINAL_STATES:
            return _result(state)
        recovered = False
        quarantined = 0
        if state and state["state"] == "RUNNING":
            updated_at = _parse_timestamp(state["updated_at"])
            if now - updated_at < stale_after:
                raise PostgresBackupWorkerError("backup_run_active")
            quarantined = _quarantine_partials(
                service_directories, stale_before=now - stale_after
            )
            recovered = True
        elif state and state["state"] != "RETRY_WAIT":
            raise PostgresBackupWorkerError("backup_worker_state_invalid")

        started_at = state["started_at"] if state else _timestamp(now)
        attempts = int(state["attempt_count"]) if state else 0
        last_error: str | None = None
        while True:
            if attempts >= max_attempts:
                raise PostgresBackupWorkerError("backup_worker_state_invalid")
            attempts += 1
            running = _state_document(
                run_id=run_id,
                state="RUNNING",
                attempt_count=attempts,
                max_attempts=max_attempts,
                started_at=started_at,
                updated_at=_timestamp(_aware(clock())),
                completed_at=None,
                service_states={},
                error_code=None,
                recovered_stale_run=recovered,
                quarantined_partial_count=quarantined,
            )
            _write_state_atomic(state_path, running)
            try:
                service_states = _validate_service_states(executor(attempts))
            except PostgresBackupError as exc:
                last_error = str(exc)
                if last_error not in RETRYABLE_ERROR_CODES or attempts >= max_attempts:
                    failed = dict(running)
                    failed.update(
                        state="FAILED",
                        updated_at=_timestamp(_aware(clock())),
                        completed_at=_timestamp(_aware(clock())),
                        error_code=last_error,
                    )
                    _write_state_atomic(state_path, failed)
                    raise PostgresBackupWorkerError(last_error) from exc
                retrying = dict(running)
                retrying.update(
                    state="RETRY_WAIT",
                    updated_at=_timestamp(_aware(clock())),
                    error_code=last_error,
                )
                _write_state_atomic(state_path, retrying)
                sleeper(float(2 ** (attempts - 1)))
                continue
            except Exception as exc:
                failed = dict(running)
                failed.update(
                    state="FAILED",
                    updated_at=_timestamp(_aware(clock())),
                    completed_at=_timestamp(_aware(clock())),
                    error_code="backup_executor_failed",
                )
                _write_state_atomic(state_path, failed)
                raise PostgresBackupWorkerError("backup_executor_failed") from exc

            completed_at = _timestamp(_aware(clock()))
            succeeded = _state_document(
                run_id=run_id,
                state="SUCCEEDED",
                attempt_count=attempts,
                max_attempts=max_attempts,
                started_at=started_at,
                updated_at=completed_at,
                completed_at=completed_at,
                service_states=service_states,
                error_code=None,
                recovered_stale_run=recovered,
                quarantined_partial_count=quarantined,
            )
            _write_state_atomic(state_path, succeeded)
            return _result(succeeded)


def backup_worker_public_projection(result: PostgresBackupWorkerResult) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "state": result.state,
        "attempt_count": result.attempt_count,
        "service_count": len(result.service_states),
        "service_states": dict(result.service_states),
        "recovered_stale_run": result.recovered_stale_run,
        "quarantined_partial_count": result.quarantined_partial_count,
    }


def _validate_inputs(
    run_id: str,
    state_root: Path,
    service_directories: Sequence[Path],
    max_attempts: int,
    stale_after: timedelta,
) -> None:
    if not SAFE_RUN_ID.fullmatch(run_id):
        raise PostgresBackupWorkerError("backup_run_id_invalid")
    if state_root.is_symlink():
        raise PostgresBackupWorkerError("backup_state_root_symlink")
    if len(service_directories) != len(EXPECTED_SERVICE_IDS):
        raise PostgresBackupWorkerError("backup_service_directories_incomplete")
    if isinstance(max_attempts, bool) or not 1 <= max_attempts <= 3:
        raise PostgresBackupWorkerError("backup_max_attempts_invalid")
    if stale_after < timedelta(minutes=5) or stale_after > timedelta(hours=6):
        raise PostgresBackupWorkerError("backup_stale_window_invalid")


@contextmanager
def _exclusive_lock(state_root: Path, run_id: str) -> Iterator[None]:
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state_root, 0o700)
    lock_path = state_root / f"{run_id}.lock"
    with lock_path.open("a+b") as lock:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PostgresBackupWorkerError("backup_worker_lock_held") from exc
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _load_state(path: Path, *, run_id: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink():
        raise PostgresBackupWorkerError("backup_worker_state_invalid")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PostgresBackupWorkerError("backup_worker_state_invalid") from exc
    required = {
        "schema_version", "run_id", "state", "attempt_count", "max_attempts",
        "started_at", "updated_at", "completed_at", "service_states",
        "error_code", "recovered_stale_run", "quarantined_partial_count",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != required
        or value.get("schema_version") != BACKUP_WORKER_STATE_SCHEMA_VERSION
        or value.get("run_id") != run_id
        or isinstance(value.get("attempt_count"), bool)
        or not isinstance(value.get("attempt_count"), int)
        or not isinstance(value.get("max_attempts"), int)
        or not isinstance(value.get("service_states"), Mapping)
    ):
        raise PostgresBackupWorkerError("backup_worker_state_invalid")
    _parse_timestamp(str(value["started_at"]))
    _parse_timestamp(str(value["updated_at"]))
    return dict(value)


def _state_document(**values: Any) -> dict[str, Any]:
    return {"schema_version": BACKUP_WORKER_STATE_SCHEMA_VERSION, **values}


def _write_state_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    partial = path.with_name(f".{path.name}.{os.getpid()}.partial")
    try:
        with partial.open("x", encoding="utf-8") as output:
            os.chmod(partial, 0o600)
            json.dump(dict(payload), output, ensure_ascii=True, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(partial, path)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _quarantine_partials(
    service_directories: Sequence[Path], *, stale_before: datetime
) -> int:
    count = 0
    for directory in service_directories:
        if directory.exists():
            count += len(
                quarantine_stale_partials(directory, stale_before=stale_before)
            )
    return count


def _validate_service_states(value: Mapping[str, str]) -> dict[str, str]:
    states = dict(value)
    if tuple(sorted(states)) != tuple(sorted(EXPECTED_SERVICE_IDS)) or any(
        state not in {"CREATED", "VERIFIED"} for state in states.values()
    ):
        raise PostgresBackupWorkerError("backup_service_results_invalid")
    return states


def _result(state: Mapping[str, Any]) -> PostgresBackupWorkerResult:
    return PostgresBackupWorkerResult(
        run_id=str(state["run_id"]),
        state=str(state["state"]),
        attempt_count=int(state["attempt_count"]),
        service_states={
            str(key): str(value)
            for key, value in dict(state["service_states"]).items()
        },
        recovered_stale_run=bool(state["recovered_stale_run"]),
        quarantined_partial_count=int(state["quarantined_partial_count"]),
    )


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PostgresBackupWorkerError("backup_worker_timestamp_invalid") from exc
    return _aware(parsed)


def _timestamp(value: datetime) -> str:
    return _aware(value).isoformat().replace("+00:00", "Z")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PostgresBackupWorkerError("backup_worker_timestamp_not_timezone_aware")
    return value.astimezone(timezone.utc)
