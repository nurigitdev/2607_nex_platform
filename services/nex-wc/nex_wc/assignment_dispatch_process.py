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
    ServiceLogEmitter,
    SqlAlchemyJobQueue,
    SqlAlchemyServiceLogStore,
    SqlAlchemyWorkerHeartbeatStore,
    WorkerHeartbeatEmitter,
    build_engine,
    build_session_factory,
    check_sqlalchemy_engine,
    database_pool_settings,
    required_database_url,
)
from nex_runtime.runtime_package_admission import (
    build_runtime_package_check,
    runtime_package_check_requested,
)
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from nex_wc.assignment_dispatch import (
    CLAIM,
    ROUTE,
    WC_ASSIGNMENT_DISPATCH_JOB_TYPE,
    WC_ASSIGNMENT_DISPATCH_WORKER_TYPE,
    enqueue_claimable_assignment_jobs,
    run_assignment_dispatch_worker_once,
)
from nex_wc.coordination import (
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.coordination_clients import (
    HttpAgentCandidateSource,
    HttpAuthorizationSource,
)

PROCESS_ID = "nex-wc-assignment-dispatch-worker"
SERVICE_ID = "nex-wc"
PROCESS_SCHEMA_VERSION = "wc_assignment_dispatch_process.v1"
PROCESS_READINESS_SCHEMA_VERSION = "wc_assignment_dispatch_readiness.v1"
PROCESS_RUN_SCHEMA_VERSION = "wc_assignment_dispatch_run.v1"
DEFAULT_WORKER_ID = "wc-assignment-dispatch-worker-1"
DEFAULT_SCAN_LIMIT = 100
DEFAULT_CLAIM_LEASE_SECONDS = 600
SUPPORTED_PROFILES = ("local_mock", "test", "staging_live", "production")
DATABASE_ENVIRONMENTS = {
    "test": "NEX_WC_TEST_DATABASE_URL",
    "staging_live": "NEX_WC_DATABASE_URL",
    "production": "NEX_WC_DATABASE_URL",
}
REQUIRED_TABLES = frozenset(
    {
        "schema_migrations",
        "service_jobs",
        "service_log_entries",
        "service_worker_heartbeats",
        "wc_assignment",
        "wc_claim",
        "wc_event_outbox",
        "wc_routing_decision",
        "wc_work_item",
    }
)
ROOT = Path(__file__).resolve().parents[3]


class WcAssignmentDispatchProcessError(RuntimeError):
    pass


class WcAssignmentDispatchShutdownToken:
    def __init__(self) -> None:
        self.requested = False
        self.reason_code: str | None = None

    def request(self, reason_code: str) -> None:
        reason = str(reason_code).strip()
        if not reason:
            raise WcAssignmentDispatchProcessError("shutdown reason_code is required")
        if not self.requested:
            self.requested = True
            self.reason_code = reason


@dataclass
class InstalledWcAssignmentDispatchProcess:
    profile: str
    database_environment: str
    engine: Engine
    sessions: sessionmaker[Session]
    heartbeat: WorkerHeartbeatEmitter
    service_log: ServiceLogEmitter
    queue: SqlAlchemyJobQueue
    repository: SqlAlchemyCoordinationRepository
    service: WorkCoordinationService
    candidate_source: HttpAgentCandidateSource
    authorization_source: HttpAuthorizationSource
    worker_id: str
    poll_interval_seconds: float
    scan_limit: int
    claim_lease_seconds: int = DEFAULT_CLAIM_LEASE_SECONDS

    def readiness(self) -> dict[str, Any]:
        database = _database_readiness(self.sessions)
        checks = {
            "database_connected": database["connected"],
            "wc_migrations_current": database["migrations_current"],
            "dispatch_tables_present": not database["missing_tables"],
            "job_queue_available": self.queue is not None,
            "coordination_repository_available": self.repository is not None,
            "coordination_service_available": self.service is not None,
            "ae_registry_transport_configured": self.candidate_source is not None,
            "oa_authorization_transport_configured": (
                self.authorization_source is not None
            ),
            "heartbeat_available": self.heartbeat is not None,
            "service_log_available": self.service_log is not None,
            "claim_lease_configured": 30 <= self.claim_lease_seconds <= 3600,
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
            "dispatch_paths": ["CREATED_TO_ROUTED", "ROUTED_TO_ASSIGNED"],
            "work_capability": "assignment_dispatching",
            "claim_lease_seconds": self.claim_lease_seconds,
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
                        "(SELECT count(*) FROM wc_work_item "
                        "WHERE state = 'CREATED') AS created_items, "
                        "(SELECT count(*) FROM wc_work_item "
                        "WHERE state = 'ROUTED') AS routed_items"
                    ),
                    {"job_type": WC_ASSIGNMENT_DISPATCH_JOB_TYPE},
                )
                .mappings()
                .one()
            )
        active_jobs = int(row["active_jobs"] or 0)
        created_items = int(row["created_items"] or 0)
        routed_items = int(row["routed_items"] or 0)
        return {
            "status": (
                "WORK" if active_jobs or created_items or routed_items else "IDLE"
            ),
            "probe": probe,
            "active_job_count": active_jobs,
            "created_work_item_count": created_items,
            "routed_work_item_count": routed_items,
            "content_included": False,
            "secret_included": False,
        }

    def run_once(self) -> dict[str, Any]:
        route_scan = enqueue_claimable_assignment_jobs(
            repository=self.repository,
            queue=self.queue,
            state="CREATED",
            limit=self.scan_limit,
        )
        route_execution = self._run_worker_once()
        claim_scan = enqueue_claimable_assignment_jobs(
            repository=self.repository,
            queue=self.queue,
            state="ROUTED",
            limit=self.scan_limit,
        )
        claim_execution = self._run_worker_once()
        executions = (route_execution, claim_execution)
        claimed_count = sum(execution.job is not None for execution in executions)
        succeeded_count = sum(
            execution.status == "SUCCEEDED" for execution in executions
        )
        failed_count = sum(execution.status == "FAILED" for execution in executions)
        work = bool(
            route_scan["scanned_count"] or claim_scan["scanned_count"] or claimed_count
        )
        return {
            "status": "WORK" if work else "IDLE",
            "route_scanned_count": route_scan["scanned_count"],
            "route_enqueued_count": route_scan["enqueued_count"],
            "claim_scanned_count": claim_scan["scanned_count"],
            "claim_enqueued_count": claim_scan["enqueued_count"],
            "claimed_job_count": claimed_count,
            "succeeded_count": succeeded_count,
            "failed_count": failed_count,
            "execution_statuses": [execution.status for execution in executions],
            "content_included": False,
            "secret_included": False,
        }

    def _run_worker_once(self):
        return run_assignment_dispatch_worker_once(
            queue=self.queue,
            heartbeat_emitter=self.heartbeat,
            service_log_emitter=self.service_log,
            repository=self.repository,
            service=self.service,
            worker_id=self.worker_id,
        )

    def close(self) -> None:
        self.engine.dispose()


def build_source_check() -> dict[str, Any]:
    return {
        "schema_version": PROCESS_SCHEMA_VERSION,
        "status": "PASS",
        "process_id": PROCESS_ID,
        "service_id": SERVICE_ID,
        "module": "nex_wc.assignment_dispatch_process",
        "database_environments": dict(DATABASE_ENVIRONMENTS),
        "job_type": WC_ASSIGNMENT_DISPATCH_JOB_TYPE,
        "worker_type": WC_ASSIGNMENT_DISPATCH_WORKER_TYPE,
        "dispatch_actions": [ROUTE, CLAIM],
        "dispatch_paths": ["CREATED_TO_ROUTED", "ROUTED_TO_ASSIGNED"],
        "queue_type": SqlAlchemyJobQueue.__name__,
        "work_capability": "assignment_dispatching",
        "default_claim_lease_seconds": DEFAULT_CLAIM_LEASE_SECONDS,
        "runtime_ready": False,
        "content_included": False,
        "secret_included": False,
    }


def build_installed_wc_assignment_dispatch_process(
    profile: str,
    *,
    environ: Mapping[str, str] | None = None,
    engine_factory: Callable[..., Engine] = build_engine,
    engine_checker: Callable[[Engine], bool] = check_sqlalchemy_engine,
    session_factory_builder: Callable[
        [Engine], sessionmaker[Session]
    ] = build_session_factory,
) -> InstalledWcAssignmentDispatchProcess:
    selected = _profile(profile)
    if selected not in DATABASE_ENVIRONMENTS:
        raise WcAssignmentDispatchProcessError(
            "local_mock provides package admission only; protected execution "
            "requires the test profile"
        )
    env = os.environ if environ is None else environ
    database_environment = DATABASE_ENVIRONMENTS[selected]
    worker_id = _required_environment(
        env, "NEX_WC_ASSIGNMENT_DISPATCH_WORKER_ID", DEFAULT_WORKER_ID
    )
    ae_base_url = _http_base_url(env, "NEX_WC_AE_BASE_URL")
    oa_base_url = _http_base_url(env, "NEX_WC_OA_BASE_URL")
    ae_service_token = _required_environment(env, "NEX_WC_TO_AE_SERVICE_TOKEN")
    oa_service_token = _required_environment(env, "NEX_WC_TO_OA_SERVICE_TOKEN")
    ae_timeout_seconds = _bounded_float(
        env.get("NEX_WC_ASSIGNMENT_AE_TIMEOUT_SECONDS", "15"),
        "NEX_WC_ASSIGNMENT_AE_TIMEOUT_SECONDS",
        minimum=0.001,
        maximum=120,
    )
    oa_timeout_seconds = _bounded_float(
        env.get("NEX_WC_ASSIGNMENT_OA_TIMEOUT_SECONDS", "15"),
        "NEX_WC_ASSIGNMENT_OA_TIMEOUT_SECONDS",
        minimum=0.001,
        maximum=120,
    )
    poll_interval_seconds = _bounded_float(
        env.get("NEX_WC_ASSIGNMENT_DISPATCH_POLL_SECONDS", "1"),
        "NEX_WC_ASSIGNMENT_DISPATCH_POLL_SECONDS",
        minimum=0.001,
        maximum=300,
    )
    scan_limit = _bounded_int(
        env.get("NEX_WC_ASSIGNMENT_DISPATCH_SCAN_LIMIT", str(DEFAULT_SCAN_LIMIT)),
        "NEX_WC_ASSIGNMENT_DISPATCH_SCAN_LIMIT",
        minimum=1,
        maximum=500,
    )
    claim_lease_seconds = _bounded_int(
        env.get(
            "NEX_WC_CLAIM_LEASE_SECONDS",
            str(DEFAULT_CLAIM_LEASE_SECONDS),
        ),
        "NEX_WC_CLAIM_LEASE_SECONDS",
        minimum=30,
        maximum=3600,
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
            raise WcAssignmentDispatchProcessError(
                "WC assignment-dispatch database readiness failed"
            )
        sessions = session_factory_builder(engine)
        repository = SqlAlchemyCoordinationRepository(sessions)
        candidate_source = HttpAgentCandidateSource(
            base_url=ae_base_url,
            service_token=ae_service_token,
            timeout_seconds=ae_timeout_seconds,
        )
        authorization_source = HttpAuthorizationSource(
            base_url=oa_base_url,
            service_token=oa_service_token,
            timeout_seconds=oa_timeout_seconds,
        )
        heartbeat = WorkerHeartbeatEmitter(
            service_id=SERVICE_ID,
            worker_id=worker_id,
            worker_type=WC_ASSIGNMENT_DISPATCH_WORKER_TYPE,
            store=SqlAlchemyWorkerHeartbeatStore(sessions),
            metadata={
                "process_id": PROCESS_ID,
                "pool_workload": "worker",
                "evidence_classification": "PROTECTED_COMPONENT",
            },
        )
        service_log = ServiceLogEmitter(
            service_id=SERVICE_ID,
            logger_name="nex_wc.assignment_dispatch_process",
            store=SqlAlchemyServiceLogStore(sessions),
            default_attributes={"process_id": PROCESS_ID},
        )
        return InstalledWcAssignmentDispatchProcess(
            profile=selected,
            database_environment=database_environment,
            engine=engine,
            sessions=sessions,
            heartbeat=heartbeat,
            service_log=service_log,
            queue=SqlAlchemyJobQueue(sessions),
            repository=repository,
            service=WorkCoordinationService(
                repository,
                candidate_source=candidate_source,
                authorization_source=authorization_source,
                lease_seconds=claim_lease_seconds,
            ),
            candidate_source=candidate_source,
            authorization_source=authorization_source,
            worker_id=worker_id,
            poll_interval_seconds=poll_interval_seconds,
            scan_limit=scan_limit,
            claim_lease_seconds=claim_lease_seconds,
        )
    except Exception as exc:
        if engine is not None:
            engine.dispose()
        if isinstance(exc, WcAssignmentDispatchProcessError):
            raise
        raise WcAssignmentDispatchProcessError(
            "installed WC assignment-dispatch process is unavailable"
        ) from exc


def build_live_check(
    profile: str,
    *,
    environ: Mapping[str, str] | None = None,
    process_builder: Callable[..., InstalledWcAssignmentDispatchProcess] = (
        build_installed_wc_assignment_dispatch_process
    ),
) -> dict[str, Any]:
    if _profile(profile) == "local_mock":
        return build_source_check()
    process = process_builder(profile, environ=environ)
    try:
        return process.readiness()
    finally:
        process.close()


def run_installed_wc_assignment_dispatch_process(
    process: InstalledWcAssignmentDispatchProcess,
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
        raise WcAssignmentDispatchProcessError(
            "max_cycles must be between 1 and 100000"
        )
    readiness = process.readiness()
    if readiness["readiness_status"] != "READY":
        raise WcAssignmentDispatchProcessError(
            "WC assignment-dispatch process is not ready"
        )
    stop = should_stop or (lambda: False)
    stream = out or sys.stdout
    started_at = _timestamp(clock())
    process.heartbeat.emit(status=STARTING, observed_at=started_at)
    process.service_log.safe_emit(
        severity="INFO",
        message="WC assignment-dispatch process started.",
        observed_at=started_at,
    )
    recovery = process.queue_projection(probe="RECOVERY")
    completed_cycles = 0
    work_cycles = 0
    failed_count = 0
    try:
        while not stop() and (max_cycles is None or completed_cycles < max_cycles):
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
            if not stop() and (max_cycles is None or completed_cycles < max_cycles):
                sleeper(process.poll_interval_seconds)
    except Exception as exc:
        observed_at = _timestamp(clock())
        process.heartbeat.safe_emit(
            status=ERROR,
            observed_at=observed_at,
            metadata={"failure_type": exc.__class__.__name__},
        )
        process.service_log.safe_emit(
            severity="ERROR",
            message="WC assignment-dispatch process cycle failed.",
            attributes={"failure_type": exc.__class__.__name__},
            observed_at=observed_at,
        )
        if isinstance(exc, WcAssignmentDispatchProcessError):
            raise
        raise WcAssignmentDispatchProcessError(
            "WC assignment-dispatch process loop failed"
        ) from exc
    stop_reason = "SHUTDOWN_REQUESTED" if stop() else "MAX_CYCLES"
    completed_at = _timestamp(clock())
    process.heartbeat.safe_emit(
        status=STOPPING,
        observed_at=completed_at,
        metadata={"stop_reason": stop_reason},
    )
    process.heartbeat.safe_emit(
        status=STOPPED,
        observed_at=completed_at,
        metadata={"stop_reason": stop_reason},
    )
    process.service_log.safe_emit(
        severity="INFO",
        message="WC assignment-dispatch process stopped.",
        attributes={"stop_reason": stop_reason},
        observed_at=completed_at,
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
        "completed_at": completed_at,
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
    process_builder: Callable[..., InstalledWcAssignmentDispatchProcess] = (
        build_installed_wc_assignment_dispatch_process
    ),
    out: TextIO | None = None,
) -> dict[str, Any]:
    process = process_builder(profile, environ=environ)
    token = WcAssignmentDispatchShutdownToken()
    previous = install_signal_handlers(token)
    try:
        return run_installed_wc_assignment_dispatch_process(
            process,
            max_cycles=max_cycles,
            should_stop=lambda: token.requested,
            out=out,
        )
    finally:
        restore_signal_handlers(previous)
        process.close()


def install_signal_handlers(
    token: WcAssignmentDispatchShutdownToken,
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
        description="NeX WC assignment-dispatch worker process"
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
        if args.check and runtime_package_check_requested(env):
            record = build_runtime_package_check(build_source_check())
        else:
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
    except (WcAssignmentDispatchProcessError, ValueError) as exc:
        detail = str(exc)
        if "://" in detail:
            detail = "WC assignment-dispatch process configuration is unavailable"
        record = {
            "schema_version": PROCESS_SCHEMA_VERSION,
            "status": "BLOCKED",
            "process_id": PROCESS_ID,
            "failure_code": "wc.assignment_dispatch_process.unavailable",
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
                session.execute(text("SELECT current_database(), current_user")).one()
                if bind.dialect.name == "postgresql"
                else ("sqlite", "sqlite")
            )
    except Exception as exc:
        raise WcAssignmentDispatchProcessError(
            "WC assignment-dispatch database check failed"
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
        "migrations_current": not missing_migrations and not unexpected_migrations,
        "missing_migrations": list(missing_migrations),
        "unexpected_migrations": list(unexpected_migrations),
        "observed_tables": list(observed_tables),
        "missing_tables": list(missing_tables),
    }


def _profile(value: object) -> str:
    selected = str(value).strip()
    if selected not in SUPPORTED_PROFILES:
        raise WcAssignmentDispatchProcessError(
            "unsupported WC assignment-dispatch profile"
        )
    return selected


def _required_environment(
    environ: Mapping[str, str], name: str, default: str | None = None
) -> str:
    value = str(environ.get(name) or default or "").strip()
    if not value:
        raise WcAssignmentDispatchProcessError(f"{name} is required")
    return value


def _http_base_url(environ: Mapping[str, str], name: str) -> str:
    value = _required_environment(environ, name)
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WcAssignmentDispatchProcessError(f"{name} must be an HTTP(S) URL")
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
        raise WcAssignmentDispatchProcessError(f"{name} is invalid") from exc
    if not minimum <= parsed <= maximum:
        raise WcAssignmentDispatchProcessError(f"{name} is invalid")
    return parsed


def _bounded_int(
    value: object,
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        if isinstance(value, bool):
            raise TypeError
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise WcAssignmentDispatchProcessError(f"{name} is invalid") from exc
    if not minimum <= parsed <= maximum:
        raise WcAssignmentDispatchProcessError(f"{name} is invalid")
    return parsed


def _timestamp(value: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":  # pragma: no cover - packaged command boundary
    raise SystemExit(main())
