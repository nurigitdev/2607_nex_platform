from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import signal
import time
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .database import (
    build_engine,
    build_session_factory,
    check_sqlalchemy_engine,
    database_pool_settings,
    required_database_url,
)
from .worker_heartbeats import (
    ERROR,
    IDLE,
    STARTING,
    STOPPED,
    STOPPING,
    SqlAlchemyWorkerHeartbeatStore,
    WorkerHeartbeatEmitter,
)


DEMO_PROCESS_RUN_SCHEMA_VERSION = "p8_demo_process_run.v1"


class DemoProcessRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DemoProcessRuntimeConfig:
    process_id: str
    service_id: str
    worker_id: str
    worker_type: str
    database_environment: str
    poll_interval_seconds: float = 1.0

    def __post_init__(self) -> None:
        for field in (
            "process_id",
            "service_id",
            "worker_id",
            "worker_type",
            "database_environment",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise DemoProcessRuntimeError(f"{field} must be a non-empty string")
        if (
            isinstance(self.poll_interval_seconds, bool)
            or not isinstance(self.poll_interval_seconds, (int, float))
            or self.poll_interval_seconds <= 0
            or self.poll_interval_seconds > 300
        ):
            raise DemoProcessRuntimeError(
                "poll_interval_seconds must be greater than 0 and at most 300"
            )


@dataclass
class DemoProcessDatabaseResource:
    config: DemoProcessRuntimeConfig
    engine: Engine
    sessions: sessionmaker[Session]
    heartbeat: WorkerHeartbeatEmitter

    def close(self) -> None:
        self.engine.dispose()


class DemoProcessShutdownToken:
    def __init__(self) -> None:
        self.requested = False
        self.reason_code: str | None = None

    def request(self, reason_code: str) -> None:
        reason = str(reason_code).strip()
        if not reason:
            raise DemoProcessRuntimeError("shutdown reason_code is required")
        if not self.requested:
            self.requested = True
            self.reason_code = reason


def build_demo_process_database_resource(
    config: DemoProcessRuntimeConfig,
    *,
    environ: Mapping[str, str],
    engine_factory: Callable[..., Engine] = build_engine,
    engine_checker: Callable[[Engine], bool] = check_sqlalchemy_engine,
    session_factory_builder: Callable[[Engine], sessionmaker[Session]] = build_session_factory,
) -> DemoProcessDatabaseResource:
    try:
        database_url = required_database_url(config.database_environment, environ)
        engine = engine_factory(
            database_url,
            pool_settings=database_pool_settings(
                config.service_id,
                workload="worker",
                environ=environ,
            ),
        )
        if not engine_checker(engine):
            raise DemoProcessRuntimeError("worker database readiness failed")
        sessions = session_factory_builder(engine)
        heartbeat = WorkerHeartbeatEmitter(
            service_id=config.service_id,
            worker_id=config.worker_id,
            worker_type=config.worker_type,
            store=SqlAlchemyWorkerHeartbeatStore(sessions),
            metadata={
                "process_id": config.process_id,
                "pool_workload": "worker",
                "demo_release": True,
            },
        )
        return DemoProcessDatabaseResource(config, engine, sessions, heartbeat)
    except Exception as exc:
        engine_value = locals().get("engine")
        if engine_value is not None:
            engine_value.dispose()
        if isinstance(exc, DemoProcessRuntimeError):
            raise
        raise DemoProcessRuntimeError(
            "protected worker database resource is unavailable"
        ) from exc


def demo_process_database_check(
    resource: DemoProcessDatabaseResource,
    *,
    required_tables: tuple[str, ...],
) -> dict[str, Any]:
    table_names = tuple(sorted({_identifier(item) for item in required_tables}))
    try:
        with resource.sessions() as session:
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                rows = session.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = current_schema() "
                        "AND table_name IN :table_names"
                    ).bindparams(bindparam("table_names", expanding=True)),
                    {"table_names": table_names},
                ).scalars()
            else:
                rows = session.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).scalars()
            observed = set(rows)
    except Exception as exc:
        raise DemoProcessRuntimeError("worker database check failed") from exc
    missing = sorted(set(table_names) - observed)
    if missing:
        raise DemoProcessRuntimeError(
            f"worker database tables are missing: {','.join(missing)}"
        )
    return {
        "schema_version": "p8_demo_process_database_check.v1",
        "status": "PASS",
        "process_id": resource.config.process_id,
        "service_id": resource.config.service_id,
        "database_environment": resource.config.database_environment,
        "pool_workload": "worker",
        "required_tables": list(table_names),
        "secret_included": False,
    }


def run_demo_process_loop(
    resource: DemoProcessDatabaseResource,
    *,
    recovery_probe: Callable[[], Mapping[str, Any]],
    cycle: Callable[[], Mapping[str, Any]],
    shutdown_token: DemoProcessShutdownToken | None = None,
    max_cycles: int | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    if max_cycles is not None and (
        isinstance(max_cycles, bool)
        or not isinstance(max_cycles, int)
        or not 1 <= max_cycles <= 100_000
    ):
        raise DemoProcessRuntimeError("max_cycles must be between 1 and 100000")
    token = shutdown_token or DemoProcessShutdownToken()
    observed_clock = clock or (lambda: datetime.now(UTC))
    started_at = _timestamp(observed_clock())
    completed_cycles = 0
    work_cycles = 0
    try:
        resource.heartbeat.emit(status=STARTING, observed_at=started_at)
        recovery = _record("recovery_probe", recovery_probe())
        resource.heartbeat.emit(
            status=IDLE,
            observed_at=_timestamp(observed_clock()),
            metadata={"recovery_status": recovery.get("status", "UNKNOWN")},
        )
        while not token.requested and (
            max_cycles is None or completed_cycles < max_cycles
        ):
            result = _record("cycle", cycle())
            status = result.get("status")
            if status not in {"IDLE", "WORK"}:
                raise DemoProcessRuntimeError("cycle status must be IDLE or WORK")
            completed_cycles += 1
            work_cycles += status == "WORK"
            resource.heartbeat.emit(
                status=IDLE,
                observed_at=_timestamp(observed_clock()),
                metadata={
                    "cycle_status": status,
                    "completed_cycles": completed_cycles,
                },
            )
            if not token.requested and (
                max_cycles is None or completed_cycles < max_cycles
            ):
                sleeper(resource.config.poll_interval_seconds)
        stop_reason = token.reason_code or "MAX_CYCLES"
        resource.heartbeat.emit(
            status=STOPPING,
            observed_at=_timestamp(observed_clock()),
            metadata={"stop_reason": stop_reason},
        )
        resource.heartbeat.emit(
            status=STOPPED,
            observed_at=_timestamp(observed_clock()),
            metadata={"stop_reason": stop_reason},
        )
        return {
            "schema_version": DEMO_PROCESS_RUN_SCHEMA_VERSION,
            "status": "STOPPED",
            "process_id": resource.config.process_id,
            "service_id": resource.config.service_id,
            "stop_reason": stop_reason,
            "completed_cycles": completed_cycles,
            "work_cycles": work_cycles,
            "recovery": recovery,
            "started_at": started_at,
            "completed_at": _timestamp(observed_clock()),
            "content_included": False,
            "secret_included": False,
        }
    except Exception as exc:
        resource.heartbeat.safe_emit(
            status=ERROR,
            observed_at=_timestamp(observed_clock()),
            metadata={"failure_type": exc.__class__.__name__},
        )
        if isinstance(exc, DemoProcessRuntimeError):
            raise
        raise DemoProcessRuntimeError("demo process loop failed") from exc


def install_demo_process_signal_handlers(
    token: DemoProcessShutdownToken,
) -> dict[int, Any]:
    previous: dict[int, Any] = {}

    def request_shutdown(signum: int, _frame: Any) -> None:
        token.request(signal.Signals(signum).name)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, request_shutdown)
    return previous


def restore_demo_process_signal_handlers(previous: Mapping[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _record(field: str, value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DemoProcessRuntimeError(f"{field} must return an object")
    return dict(value)


def _identifier(value: object) -> str:
    text_value = str(value).strip()
    if not text_value or not text_value.replace("_", "").isalnum():
        raise DemoProcessRuntimeError("database table name is invalid")
    return text_value


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DemoProcessRuntimeError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
