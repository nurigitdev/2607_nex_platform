from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

from nex_runtime import (
    ERROR,
    IDLE,
    STARTING,
    STOPPED,
    STOPPING,
    SqlAlchemyWorkerHeartbeatStore,
    WorkerHeartbeatEmitter,
    build_engine,
    build_session_factory,
    check_sqlalchemy_engine,
    database_pool_settings,
    required_database_url,
)
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from nex_eos.ae_outbox_transport import HttpAeEosOutboxTransport
from nex_eos.outbox_publication import (
    EosOutboxPublicationError,
    SqlAlchemyEosOutboxPublisher,
)

PROCESS_ID = "nex-eos-outbox-publisher"
SERVICE_ID = "nex-eos"
WORKER_TYPE = "eos.outbox.publisher"
PROCESS_SCHEMA_VERSION = "eos_outbox_publisher_process.v1"
PROCESS_READINESS_SCHEMA_VERSION = "eos_outbox_publisher_readiness.v1"
PROCESS_RUN_SCHEMA_VERSION = "eos_outbox_publisher_run.v1"
DEFAULT_WORKER_ID = "eos-outbox-publisher-1"
SUPPORTED_PROFILES = ("local_mock", "test")
DATABASE_ENVIRONMENTS = {"test": "NEX_EOS_TEST_DATABASE_URL"}
REQUIRED_TABLES = frozenset(
    {
        "schema_migrations",
        "service_worker_heartbeats",
        "eos_business_operation",
        "eos_idempotency",
        "eos_outbox",
    }
)
ROOT = Path(__file__).resolve().parents[3]


class EosOutboxPublisherProcessError(RuntimeError):
    pass


class EosOutboxPublisherShutdownToken:
    def __init__(self) -> None:
        self.requested = False
        self.reason_code: str | None = None

    def request(self, reason_code: str) -> None:
        reason = str(reason_code).strip()
        if not reason:
            raise EosOutboxPublisherProcessError(
                "shutdown reason_code is required"
            )
        if not self.requested:
            self.requested = True
            self.reason_code = reason


@dataclass
class InstalledEosOutboxPublisherProcess:
    profile: str
    database_environment: str
    engine: Engine
    sessions: sessionmaker[Session]
    heartbeat: WorkerHeartbeatEmitter
    publisher: SqlAlchemyEosOutboxPublisher
    transport: HttpAeEosOutboxTransport
    worker_id: str
    poll_interval_seconds: float

    def readiness(self) -> dict[str, Any]:
        database = _database_readiness(self.sessions)
        checks = {
            "database_connected": database["connected"],
            "eos_migrations_current": database["migrations_current"],
            "outbox_tables_present": not database["missing_tables"],
            "outbox_publisher_available": self.publisher is not None,
            "signed_ae_transport_configured": self.transport is not None,
            "heartbeat_available": self.heartbeat is not None,
        }
        ready = all(checks.values())
        return {
            "readiness_schema_version": PROCESS_READINESS_SCHEMA_VERSION,
            "status": "PASS" if ready else "FAIL",
            "readiness_status": "READY" if ready else "NOT_READY",
            "process_id": PROCESS_ID,
            "service_id": SERVICE_ID,
            "profile": self.profile,
            "database_environment": self.database_environment,
            "checks": checks,
            "database": database,
            "publication_path": "EOS_OUTBOX_TO_AE",
            "work_capability": "outbox_publishing",
            "content_included": False,
            "secret_included": False,
        }

    def queue_projection(self, *, probe: str) -> dict[str, Any]:
        with self.sessions() as session:
            row = (
                session.execute(
                    text(
                        "SELECT "
                        "count(*) FILTER (WHERE delivery_state = 'PENDING') "
                        "AS pending_count, "
                        "count(*) FILTER (WHERE delivery_state = 'PUBLISHED') "
                        "AS published_count FROM eos_outbox"
                    )
                )
                .mappings()
                .one()
            )
        return {
            "status": "IDLE",
            "probe": probe,
            "pending_outbox_count": int(row["pending_count"] or 0),
            "published_outbox_count": int(row["published_count"] or 0),
        }

    def run_once(self) -> dict[str, Any]:
        try:
            result = self.publisher.publish_next(self.transport)
        except EosOutboxPublicationError as exc:
            raise EosOutboxPublisherProcessError(
                "EOS outbox publication failed"
            ) from exc
        if result is None:
            return {
                "status": "IDLE",
                "claimed_count": 0,
                "published_count": 0,
                "failed_count": 0,
                "retry_required": False,
                "publication_error_code": None,
                "content_included": False,
                "secret_included": False,
            }
        failed = int(result.retry_required)
        return {
            "status": "WORK",
            "claimed_count": 1,
            "published_count": int(result.delivery_state == "PUBLISHED"),
            "failed_count": failed,
            "retry_required": result.retry_required,
            "publication_error_code": result.error_code,
            "delivery_state": result.delivery_state,
            "attempt_count": result.attempt_count,
            "content_included": False,
            "secret_included": False,
        }

    def close(self) -> None:
        self.engine.dispose()


def build_source_check() -> dict[str, Any]:
    return {
        "schema_version": PROCESS_SCHEMA_VERSION,
        "status": "PASS",
        "process_id": PROCESS_ID,
        "service_id": SERVICE_ID,
        "module": "nex_eos.outbox_publisher_process",
        "database_environments": dict(DATABASE_ENVIRONMENTS),
        "publication_path": "EOS_OUTBOX_TO_AE",
        "publisher_type": SqlAlchemyEosOutboxPublisher.__name__,
        "transport_type": HttpAeEosOutboxTransport.__name__,
        "work_capability": "outbox_publishing",
        "runtime_ready": False,
        "content_included": False,
        "secret_included": False,
    }


def build_installed_eos_outbox_publisher_process(
    profile: str,
    *,
    environ: Mapping[str, str] | None = None,
    engine_factory: Callable[..., Engine] = build_engine,
    engine_checker: Callable[[Engine], bool] = check_sqlalchemy_engine,
    session_factory_builder: Callable[
        [Engine], sessionmaker[Session]
    ] = build_session_factory,
) -> InstalledEosOutboxPublisherProcess:
    selected = _profile(profile)
    if selected not in DATABASE_ENVIRONMENTS:
        raise EosOutboxPublisherProcessError(
            "local_mock provides package admission only; protected execution "
            "requires the test profile"
        )
    env = os.environ if environ is None else environ
    database_environment = DATABASE_ENVIRONMENTS[selected]
    worker_id = _required_environment(
        env, "NEX_EOS_OUTBOX_PUBLISHER_WORKER_ID", DEFAULT_WORKER_ID
    )
    base_url = _ae_base_url(env)
    service_token = _required_environment(env, "NEX_EOS_TO_AE_SERVICE_TOKEN")
    timeout_seconds = _bounded_float(
        env.get("NEX_EOS_AE_OUTBOX_TIMEOUT_SECONDS", "10"),
        "NEX_EOS_AE_OUTBOX_TIMEOUT_SECONDS",
        minimum=0.001,
        maximum=120,
    )
    poll_interval_seconds = _bounded_float(
        env.get("NEX_EOS_OUTBOX_PUBLISH_POLL_SECONDS", "1"),
        "NEX_EOS_OUTBOX_PUBLISH_POLL_SECONDS",
        minimum=0.001,
        maximum=300,
    )
    engine: Engine | None = None
    try:
        database_url = required_database_url(database_environment, env)
        engine = engine_factory(
            database_url,
            pool_settings=database_pool_settings(
                SERVICE_ID, workload="worker", environ=env
            ),
        )
        if not engine_checker(engine):
            raise EosOutboxPublisherProcessError(
                "EOS outbox database readiness failed"
            )
        sessions = session_factory_builder(engine)
        heartbeat = WorkerHeartbeatEmitter(
            service_id=SERVICE_ID,
            worker_id=worker_id,
            worker_type=WORKER_TYPE,
            store=SqlAlchemyWorkerHeartbeatStore(sessions),
            metadata={
                "process_id": PROCESS_ID,
                "pool_workload": "worker",
                "evidence_classification": "PROTECTED_COMPONENT",
            },
        )
        return InstalledEosOutboxPublisherProcess(
            profile=selected,
            database_environment=database_environment,
            engine=engine,
            sessions=sessions,
            heartbeat=heartbeat,
            publisher=SqlAlchemyEosOutboxPublisher(sessions),
            transport=HttpAeEosOutboxTransport(
                base_url=base_url,
                service_token=service_token,
                timeout_seconds=timeout_seconds,
            ),
            worker_id=worker_id,
            poll_interval_seconds=poll_interval_seconds,
        )
    except Exception as exc:
        if engine is not None:
            engine.dispose()
        if isinstance(exc, EosOutboxPublisherProcessError):
            raise
        raise EosOutboxPublisherProcessError(
            "installed EOS outbox publisher process is unavailable"
        ) from exc


def build_live_check(
    profile: str,
    *,
    environ: Mapping[str, str] | None = None,
    process_builder: Callable[..., InstalledEosOutboxPublisherProcess] = (
        build_installed_eos_outbox_publisher_process
    ),
) -> dict[str, Any]:
    if _profile(profile) == "local_mock":
        return build_source_check()
    process = process_builder(profile, environ=environ)
    try:
        return process.readiness()
    finally:
        process.close()


def run_installed_eos_outbox_publisher_process(
    process: InstalledEosOutboxPublisherProcess,
    *,
    max_cycles: int | None = None,
    should_stop: Callable[[], bool] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
    out: TextIO | None = None,
) -> dict[str, Any]:
    if max_cycles is not None and (
        isinstance(max_cycles, bool)
        or not isinstance(max_cycles, int)
        or not 1 <= max_cycles <= 100_000
    ):
        raise EosOutboxPublisherProcessError(
            "max_cycles must be between 1 and 100000"
        )
    readiness = process.readiness()
    if readiness["readiness_status"] != "READY":
        raise EosOutboxPublisherProcessError(
            "EOS outbox publisher process is not ready"
        )
    stop = should_stop or (lambda: False)
    stream = out or sys.stdout
    started_at = _timestamp(clock())
    process.heartbeat.emit(status=STARTING, observed_at=started_at)
    recovery = process.queue_projection(probe="RECOVERY")
    completed_cycles = 0
    work_cycles = 0
    published_count = 0
    failed_count = 0
    try:
        while not stop() and (
            max_cycles is None or completed_cycles < max_cycles
        ):
            result = process.run_once()
            completed_cycles += 1
            work_cycles += result["status"] == "WORK"
            published_count += int(result["published_count"])
            failed_count += int(result["failed_count"])
            process.heartbeat.safe_emit(
                status=IDLE if not result["failed_count"] else ERROR,
                observed_at=_timestamp(clock()),
                metadata={
                    "cycle_status": result["status"],
                    "completed_cycles": completed_cycles,
                    "published_count": result["published_count"],
                    "failed_count": result["failed_count"],
                },
            )
            if not stop() and (
                max_cycles is None or completed_cycles < max_cycles
            ):
                sleeper(process.poll_interval_seconds)
    except Exception as exc:
        process.heartbeat.safe_emit(
            status=ERROR,
            observed_at=_timestamp(clock()),
            metadata={"failure_type": exc.__class__.__name__},
        )
        if isinstance(exc, EosOutboxPublisherProcessError):
            raise
        raise EosOutboxPublisherProcessError(
            "EOS outbox publisher process loop failed"
        ) from exc
    stop_reason = "SHUTDOWN_REQUESTED" if stop() else "MAX_CYCLES"
    process.heartbeat.safe_emit(
        status=STOPPING,
        observed_at=_timestamp(clock()),
        metadata={"stop_reason": stop_reason},
    )
    process.heartbeat.safe_emit(
        status=STOPPED,
        observed_at=_timestamp(clock()),
        metadata={"stop_reason": stop_reason},
    )
    record = {
        "schema_version": PROCESS_RUN_SCHEMA_VERSION,
        "status": "STOPPED",
        "process_id": PROCESS_ID,
        "service_id": SERVICE_ID,
        "stop_reason": stop_reason,
        "completed_cycles": completed_cycles,
        "work_cycles": work_cycles,
        "published_count": published_count,
        "failed_count": failed_count,
        "recovery": recovery,
        "started_at": started_at,
        "completed_at": _timestamp(clock()),
        "content_included": False,
        "secret_included": False,
    }
    print(json.dumps(record, sort_keys=True), file=stream)
    return record


def run_live(
    profile: str,
    *,
    environ: Mapping[str, str] | None = None,
    max_cycles: int | None = None,
    process_builder: Callable[..., InstalledEosOutboxPublisherProcess] = (
        build_installed_eos_outbox_publisher_process
    ),
    out: TextIO | None = None,
) -> dict[str, Any]:
    process = process_builder(profile, environ=environ)
    token = EosOutboxPublisherShutdownToken()
    previous = install_signal_handlers(token)
    try:
        return run_installed_eos_outbox_publisher_process(
            process,
            max_cycles=max_cycles,
            should_stop=lambda: token.requested,
            out=out,
        )
    finally:
        restore_signal_handlers(previous)
        process.close()


def install_signal_handlers(
    token: EosOutboxPublisherShutdownToken,
) -> dict[int, Any]:
    previous: dict[int, Any] = {}

    def request_shutdown(signum: int, _frame: Any) -> None:
        token.request(signal.Signals(signum).name)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, request_shutdown)
    return previous


def restore_signal_handlers(previous: Mapping[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    live_check: Callable[..., Mapping[str, Any]] = build_live_check,
    live_run: Callable[..., Mapping[str, Any]] = run_live,
) -> int:
    env = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(
        description="NeX EOS outbox publisher process"
    )
    parser.add_argument(
        "--profile",
        choices=SUPPORTED_PROFILES,
        default=str(env.get("NEX_PROFILE") or "local_mock").strip(),
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--max-cycles", type=int)
    args = parser.parse_args(list(argv) if argv is not None else None)
    output = stdout or sys.stdout
    try:
        record = (
            dict(live_check(args.profile, environ=env))
            if args.check
            else dict(
                live_run(
                    args.profile,
                    environ=env,
                    max_cycles=args.max_cycles,
                    out=output,
                )
            )
        )
        code = 0 if record.get("status") in {"PASS", "STOPPED"} else 2
    except (EosOutboxPublisherProcessError, ValueError) as exc:
        detail = str(exc)
        if "://" in detail:
            detail = "EOS outbox publisher configuration is unavailable"
        record = {
            "schema_version": PROCESS_SCHEMA_VERSION,
            "status": "BLOCKED",
            "process_id": PROCESS_ID,
            "failure_code": "eos.outbox_publisher_process.unavailable",
            "detail": detail,
            "content_included": False,
            "secret_included": False,
        }
        code = 2
    print(json.dumps(record, sort_keys=True), file=output)
    return code


def _database_readiness(
    sessions: sessionmaker[Session],
) -> dict[str, Any]:
    expected_migrations = tuple(
        path.stem
        for path in sorted((ROOT / "database/nex-eos/migrations").glob("*.sql"))
    )
    try:
        with sessions() as session:
            bind = session.get_bind()
            observed_tables = tuple(sorted(inspect(bind).get_table_names()))
            applied_migrations = (
                tuple(
                    sorted(
                        str(value)
                        for value in session.execute(
                            text("SELECT version FROM schema_migrations")
                        ).scalars()
                    )
                )
                if "schema_migrations" in observed_tables
                else ()
            )
            identity = (
                session.execute(
                    text("SELECT current_database(), current_user")
                ).one()
                if bind.dialect.name == "postgresql"
                else ("sqlite", "sqlite")
            )
    except Exception as exc:
        raise EosOutboxPublisherProcessError(
            "EOS outbox database check failed"
        ) from exc
    missing_tables = tuple(sorted(REQUIRED_TABLES - set(observed_tables)))
    missing_migrations = tuple(
        sorted(set(expected_migrations) - set(applied_migrations))
    )
    unexpected_migrations = tuple(
        sorted(set(applied_migrations) - set(expected_migrations))
    )
    return {
        "connected": True,
        "database_name": str(identity[0]),
        "database_user": str(identity[1]),
        "migration_count": len(applied_migrations),
        "expected_migration_count": len(expected_migrations),
        "migrations_current": not missing_migrations
        and not unexpected_migrations,
        "missing_migrations": list(missing_migrations),
        "unexpected_migrations": list(unexpected_migrations),
        "observed_tables": list(observed_tables),
        "missing_tables": list(missing_tables),
    }


def _profile(value: object) -> str:
    selected = str(value).strip()
    if selected not in SUPPORTED_PROFILES:
        raise EosOutboxPublisherProcessError(
            "unsupported EOS outbox publisher profile"
        )
    return selected


def _required_environment(
    environ: Mapping[str, str], name: str, default: str | None = None
) -> str:
    value = str(environ.get(name) or default or "").strip()
    if not value:
        raise EosOutboxPublisherProcessError(f"{name} is required")
    return value


def _ae_base_url(environ: Mapping[str, str]) -> str:
    value = _required_environment(environ, "NEX_AE_API_BASE_URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EosOutboxPublisherProcessError(
            "NEX_AE_API_BASE_URL must be an HTTP(S) URL"
        )
    return value.rstrip("/")


def _bounded_float(
    value: object,
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError) as exc:
        raise EosOutboxPublisherProcessError(f"{name} is invalid") from exc
    if not minimum <= parsed <= maximum:
        raise EosOutboxPublisherProcessError(f"{name} is invalid")
    return parsed


def _timestamp(value: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":  # pragma: no cover - packaged command boundary
    raise SystemExit(main())
