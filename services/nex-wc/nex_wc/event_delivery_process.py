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
    SqlAlchemyJobQueue,
    SqlAlchemyWorkerHeartbeatStore,
    WorkerHeartbeatEmitter,
    WorkerRunnerConfig,
    build_engine,
    build_session_factory,
    check_sqlalchemy_engine,
    database_pool_settings,
    required_database_url,
    run_worker_once,
)
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from nex_wc.approval_event_delivery import (
    ApprovalEventDeliveryError,
    HttpAeApprovalEventClient,
    SqlAlchemyApprovalEventDeliveryStore,
    deliver_pending_approval_events,
)
from nex_wc.coordination import SqlAlchemyCoordinationRepository
from nex_wc.handoff_delivery import (
    WC_EVENT_DELIVERY_JOB_TYPE,
    HttpClaimHandoffClient,
    enqueue_pending_handoffs,
    run_handoff_delivery_job,
)
from nex_wc.work_result_delivery import (
    HttpWorkResultEventClient,
    enqueue_pending_result_events,
    run_work_result_delivery_job,
)
from nex_wc.work_results import SqlAlchemyWorkResultRepository

PROCESS_ID = "nex-wc-event-delivery-worker"
SERVICE_ID = "nex-wc"
WORKER_TYPE = "wc.event_delivery.worker"
PROCESS_SCHEMA_VERSION = "wc_event_delivery_process.v1"
PROCESS_READINESS_SCHEMA_VERSION = "wc_event_delivery_readiness.v1"
PROCESS_RUN_SCHEMA_VERSION = "wc_event_delivery_run.v1"
DEFAULT_WORKER_ID = "wc-event-delivery-worker-1"
SUPPORTED_PROFILES = ("local_mock", "test")
DATABASE_ENVIRONMENTS = {"test": "NEX_WC_TEST_DATABASE_URL"}
REQUIRED_TABLES = frozenset(
    {
        "schema_migrations",
        "service_jobs",
        "service_worker_heartbeats",
        "wc_approval_outbox",
        "wc_event_outbox",
        "wc_work_item",
        "wc_work_result",
    }
)
ROOT = Path(__file__).resolve().parents[3]


class WcEventDeliveryProcessError(RuntimeError):
    pass


class WcEventDeliveryShutdownToken:
    def __init__(self) -> None:
        self.requested = False
        self.reason_code: str | None = None

    def request(self, reason_code: str) -> None:
        reason = str(reason_code).strip()
        if not reason:
            raise WcEventDeliveryProcessError("shutdown reason_code is required")
        if not self.requested:
            self.requested = True
            self.reason_code = reason


@dataclass
class InstalledWcEventDeliveryProcess:
    profile: str
    database_environment: str
    engine: Engine
    sessions: sessionmaker[Session]
    heartbeat: WorkerHeartbeatEmitter
    queue: SqlAlchemyJobQueue
    coordination: SqlAlchemyCoordinationRepository
    work_results: SqlAlchemyWorkResultRepository
    approval_store: SqlAlchemyApprovalEventDeliveryStore
    handoff_client: HttpClaimHandoffClient
    result_client: HttpWorkResultEventClient
    approval_client: HttpAeApprovalEventClient
    worker_id: str
    poll_interval_seconds: float

    def readiness(self) -> dict[str, Any]:
        database = _database_readiness(self.sessions)
        checks = {
            "database_connected": database["connected"],
            "wc_migrations_current": database["migrations_current"],
            "delivery_tables_present": not database["missing_tables"],
            "job_queue_available": self.queue is not None,
            "handoff_delivery_available": self.coordination is not None,
            "work_result_delivery_available": self.work_results is not None,
            "approval_delivery_available": self.approval_store is not None,
            "signed_ae_transport_configured": all(
                (
                    self.handoff_client is not None,
                    self.result_client is not None,
                    self.approval_client is not None,
                )
            ),
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
            "delivery_paths": ["CLAIM_HANDOFF", "WORK_RESULT", "APPROVAL_EVENT"],
            "work_capability": "event_delivering",
            "content_included": False,
            "secret_included": False,
        }

    def queue_projection(self, *, probe: str) -> dict[str, Any]:
        with self.sessions() as session:
            row = (
                session.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM service_jobs "
                        "WHERE job_type = :job_type "
                        "AND status IN ('QUEUED','RUNNING')) AS active_jobs, "
                        "(SELECT count(*) FROM wc_event_outbox "
                        "WHERE delivery_state IN ('PENDING','ENQUEUED')) "
                        "AS coordination_events, "
                        "(SELECT count(*) FROM wc_approval_outbox "
                        "WHERE delivery_state IN ('PENDING','ENQUEUED')) "
                        "AS approval_events"
                    ),
                    {"job_type": WC_EVENT_DELIVERY_JOB_TYPE},
                )
                .mappings()
                .one()
            )
        return {
            "status": "IDLE",
            "probe": probe,
            "active_job_count": int(row["active_jobs"] or 0),
            "coordination_event_count": int(row["coordination_events"] or 0),
            "approval_event_count": int(row["approval_events"] or 0),
        }

    def run_once(self) -> dict[str, Any]:
        enqueued = [
            *enqueue_pending_handoffs(store=self.coordination, queue=self.queue),
            *enqueue_pending_result_events(store=self.work_results, queue=self.queue),
        ]
        execution = run_worker_once(
            config=WorkerRunnerConfig(
                service_id=SERVICE_ID,
                worker_id=self.worker_id,
                worker_type=WORKER_TYPE,
                job_type=WC_EVENT_DELIVERY_JOB_TYPE,
            ),
            queue=self.queue,
            heartbeat_emitter=self.heartbeat,
            handler=self._deliver_job,
        )
        try:
            approval = deliver_pending_approval_events(
                store=self.approval_store,
                client=self.approval_client,
            )
        except ApprovalEventDeliveryError as exc:
            raise WcEventDeliveryProcessError(
                "WC approval event delivery failed"
            ) from exc
        claimed = int(execution.job is not None)
        failed = int(execution.status == "FAILED")
        work = bool(enqueued or claimed or approval["delivered_count"])
        return {
            "status": "WORK" if work else "IDLE",
            "enqueued_count": len(enqueued),
            "claimed_count": claimed,
            "delivered_count": int(execution.status == "SUCCEEDED"),
            "failed_count": failed,
            "delivery_status": execution.status,
            "delivery_error_code": execution.error_code,
            "approval_delivered_count": approval["delivered_count"],
            "content_included": False,
            "secret_included": False,
        }

    def _deliver_job(self, job: Mapping[str, Any]) -> dict[str, Any]:
        payload = job.get("payload")
        if not isinstance(payload, Mapping):
            raise WcEventDeliveryProcessError(
                "WC delivery job payload is invalid"
            )
        with self.sessions() as session:
            event_type = session.execute(
                text(
                    "SELECT event_type FROM wc_event_outbox "
                    "WHERE outbox_id = :outbox_id AND event_id = :event_id"
                ),
                {
                    "outbox_id": payload.get("outbox_id"),
                    "event_id": payload.get("event_id"),
                },
            ).scalar_one_or_none()
        if event_type == "CLAIM_EXECUTION_HANDOFF":
            return run_handoff_delivery_job(
                job, store=self.coordination, client=self.handoff_client
            )
        if event_type == "WORK_RESULT_SUBMITTED":
            return run_work_result_delivery_job(
                job, store=self.work_results, client=self.result_client
            )
        raise WcEventDeliveryProcessError(
            "WC delivery event type is unsupported"
        )

    def close(self) -> None:
        self.engine.dispose()


def build_source_check() -> dict[str, Any]:
    return {
        "schema_version": PROCESS_SCHEMA_VERSION,
        "status": "PASS",
        "process_id": PROCESS_ID,
        "service_id": SERVICE_ID,
        "module": "nex_wc.event_delivery_process",
        "database_environments": dict(DATABASE_ENVIRONMENTS),
        "delivery_paths": ["CLAIM_HANDOFF", "WORK_RESULT", "APPROVAL_EVENT"],
        "queue_type": SqlAlchemyJobQueue.__name__,
        "work_capability": "event_delivering",
        "runtime_ready": False,
        "content_included": False,
        "secret_included": False,
    }


def build_installed_wc_event_delivery_process(
    profile: str,
    *,
    environ: Mapping[str, str] | None = None,
    engine_factory: Callable[..., Engine] = build_engine,
    engine_checker: Callable[[Engine], bool] = check_sqlalchemy_engine,
    session_factory_builder: Callable[
        [Engine], sessionmaker[Session]
    ] = build_session_factory,
) -> InstalledWcEventDeliveryProcess:
    selected = _profile(profile)
    if selected not in DATABASE_ENVIRONMENTS:
        raise WcEventDeliveryProcessError(
            "local_mock provides package admission only; protected execution "
            "requires the test profile"
        )
    env = os.environ if environ is None else environ
    database_environment = DATABASE_ENVIRONMENTS[selected]
    worker_id = _required_environment(
        env, "NEX_WC_EVENT_DELIVERY_WORKER_ID", DEFAULT_WORKER_ID
    )
    base_url = _ae_base_url(env)
    service_token = _required_environment(env, "NEX_WC_TO_AE_SERVICE_TOKEN")
    timeout_seconds = _bounded_float(
        env.get("NEX_WC_AE_DELIVERY_TIMEOUT_SECONDS", "15"),
        "NEX_WC_AE_DELIVERY_TIMEOUT_SECONDS",
        minimum=0.001,
        maximum=120,
    )
    approval_timeout_seconds = _bounded_float(
        env.get("NEX_WC_AE_APPROVAL_TIMEOUT_SECONDS", str(timeout_seconds)),
        "NEX_WC_AE_APPROVAL_TIMEOUT_SECONDS",
        minimum=0.001,
        maximum=120,
    )
    poll_interval_seconds = _bounded_float(
        env.get("NEX_WC_EVENT_DELIVERY_POLL_SECONDS", "1"),
        "NEX_WC_EVENT_DELIVERY_POLL_SECONDS",
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
            raise WcEventDeliveryProcessError(
                "WC event-delivery database readiness failed"
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
        return InstalledWcEventDeliveryProcess(
            profile=selected,
            database_environment=database_environment,
            engine=engine,
            sessions=sessions,
            heartbeat=heartbeat,
            queue=SqlAlchemyJobQueue(sessions),
            coordination=SqlAlchemyCoordinationRepository(sessions),
            work_results=SqlAlchemyWorkResultRepository(sessions),
            approval_store=SqlAlchemyApprovalEventDeliveryStore(sessions),
            handoff_client=HttpClaimHandoffClient(
                base_url=base_url,
                service_token=service_token,
                timeout_seconds=timeout_seconds,
            ),
            result_client=HttpWorkResultEventClient(
                base_url=base_url,
                service_token=service_token,
                timeout_seconds=timeout_seconds,
            ),
            approval_client=HttpAeApprovalEventClient(
                base_url=base_url,
                service_token=service_token,
                timeout_seconds=approval_timeout_seconds,
            ),
            worker_id=worker_id,
            poll_interval_seconds=poll_interval_seconds,
        )
    except Exception as exc:
        if engine is not None:
            engine.dispose()
        if isinstance(exc, WcEventDeliveryProcessError):
            raise
        raise WcEventDeliveryProcessError(
            "installed WC event-delivery process is unavailable"
        ) from exc


def build_live_check(
    profile: str,
    *,
    environ: Mapping[str, str] | None = None,
    process_builder: Callable[..., InstalledWcEventDeliveryProcess] = (
        build_installed_wc_event_delivery_process
    ),
) -> dict[str, Any]:
    if _profile(profile) == "local_mock":
        return build_source_check()
    process = process_builder(profile, environ=environ)
    try:
        return process.readiness()
    finally:
        process.close()


def run_installed_wc_event_delivery_process(
    process: InstalledWcEventDeliveryProcess,
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
        raise WcEventDeliveryProcessError(
            "max_cycles must be between 1 and 100000"
        )
    readiness = process.readiness()
    if readiness["readiness_status"] != "READY":
        raise WcEventDeliveryProcessError(
            "WC event-delivery process is not ready"
        )
    stop = should_stop or (lambda: False)
    stream = out or sys.stdout
    started_at = _timestamp(clock())
    process.heartbeat.emit(status=STARTING, observed_at=started_at)
    recovery = process.queue_projection(probe="RECOVERY")
    completed_cycles = 0
    work_cycles = 0
    failed_count = 0
    try:
        while not stop() and (
            max_cycles is None or completed_cycles < max_cycles
        ):
            result = process.run_once()
            completed_cycles += 1
            work_cycles += result["status"] == "WORK"
            failed_count += int(result["failed_count"])
            process.heartbeat.safe_emit(
                status=IDLE if not result["failed_count"] else ERROR,
                observed_at=_timestamp(clock()),
                metadata={
                    "cycle_status": result["status"],
                    "completed_cycles": completed_cycles,
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
        if isinstance(exc, WcEventDeliveryProcessError):
            raise
        raise WcEventDeliveryProcessError(
            "WC event-delivery process loop failed"
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
    process_builder: Callable[..., InstalledWcEventDeliveryProcess] = (
        build_installed_wc_event_delivery_process
    ),
    out: TextIO | None = None,
) -> dict[str, Any]:
    process = process_builder(profile, environ=environ)
    token = WcEventDeliveryShutdownToken()
    previous = install_signal_handlers(token)
    try:
        return run_installed_wc_event_delivery_process(
            process,
            max_cycles=max_cycles,
            should_stop=lambda: token.requested,
            out=out,
        )
    finally:
        restore_signal_handlers(previous)
        process.close()


def install_signal_handlers(
    token: WcEventDeliveryShutdownToken,
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
        description="NeX WC event-delivery worker process"
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
    except (WcEventDeliveryProcessError, ValueError) as exc:
        detail = str(exc)
        if "://" in detail:
            detail = "WC event-delivery process configuration is unavailable"
        record = {
            "schema_version": PROCESS_SCHEMA_VERSION,
            "status": "BLOCKED",
            "process_id": PROCESS_ID,
            "failure_code": "wc.event_delivery_process.unavailable",
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
        for path in sorted((ROOT / "database/nex-wc/migrations").glob("*.sql"))
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
        raise WcEventDeliveryProcessError(
            "WC event-delivery database check failed"
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
        raise WcEventDeliveryProcessError(
            "unsupported WC event-delivery profile"
        )
    return selected


def _required_environment(
    environ: Mapping[str, str], name: str, default: str | None = None
) -> str:
    value = str(environ.get(name) or default or "").strip()
    if not value:
        raise WcEventDeliveryProcessError(f"{name} is required")
    return value


def _ae_base_url(environ: Mapping[str, str]) -> str:
    value = _required_environment(environ, "NEX_WC_AE_BASE_URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WcEventDeliveryProcessError(
            "NEX_WC_AE_BASE_URL must be an HTTP(S) URL"
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
        raise WcEventDeliveryProcessError(f"{name} is invalid") from exc
    if not minimum <= parsed <= maximum:
        raise WcEventDeliveryProcessError(f"{name} is invalid")
    return parsed


def _timestamp(value: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":  # pragma: no cover - packaged command boundary
    raise SystemExit(main())
