from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from nex_runtime import (
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

from nex_ae_api.agent_runtime_worker import (
    AE_AGENT_RUNTIME_WORKER_TYPE,
    AgentRuntimeShutdownToken,
    build_agent_runtime_worker_check,
    install_agent_runtime_worker_signal_handlers,
    restore_agent_runtime_worker_signal_handlers,
)
from nex_ae_api.nsl_backend_profiles import NSL_V01_PROCESS_ISOLATED_BACKEND
from nex_ae_api.product_runtime_profile import (
    build_product_runtime_executor_profile,
)
from nex_ae_api.runtime_composition import (
    InstalledRuntimeComposition,
    RuntimeExecutorProfile,
    build_installed_runtime_composition,
)
from nex_ae_api.step_executors import (
    P5DeterministicProjectionExecutor,
    P5StepExecutorRegistry,
)

PROCESS_ID = "nex-ae-agent-runtime-worker"
SERVICE_ID = "nex-ae-api"
PROCESS_SCHEMA_VERSION = "ae_agent_runtime_process.v1"
PROCESS_READINESS_SCHEMA_VERSION = "ae_agent_runtime_process_readiness.v1"
PROCESS_RUN_SCHEMA_VERSION = "ae_agent_runtime_process_run.v1"
DEFAULT_WORKER_ID = "ae-agent-runtime-worker-1"
SUPPORTED_PROFILES = ("local_mock", "test", "staging_live", "production")
DATABASE_ENVIRONMENTS = {
    "test": "NEX_AE_TEST_DATABASE_URL",
    "staging_live": "NEX_AE_DATABASE_URL",
    "production": "NEX_AE_DATABASE_URL",
}
REQUIRED_TABLES = frozenset(
    {
        "ae_executable_plan",
        "ae_executable_step",
        "ae_rt_dispatch_lease",
        "ae_runtime_job",
        "ae_runtime_job_attempt",
        "ae_step_result",
        "schema_migrations",
        "service_worker_heartbeats",
    }
)
ROOT = Path(__file__).resolve().parents[3]


class AgentRuntimeProcessError(RuntimeError):
    pass


@dataclass
class InstalledAgentRuntimeProcess:
    profile: str
    database_environment: str
    engine: Engine
    sessions: sessionmaker[Session]
    composition: InstalledRuntimeComposition

    def readiness(self) -> dict[str, Any]:
        database = _database_readiness(self.sessions)
        worker = build_agent_runtime_worker_check(
            self.composition.worker_config,
            available_executor_kinds=(self.composition.executor_profile.executor_kinds),
            available_backend_profiles=(
                self.composition.executor_profile.backend_profiles
            ),
            in_process_package_readiness=(
                self.composition.executor_profile.package_readiness
            ),
        )
        checks = {
            "database_connected": database["connected"],
            "ae_migrations_current": database["migrations_current"],
            "runtime_tables_present": not database["missing_tables"],
            "dispatcher_available": (
                "ae_rt_dispatch_lease" in database["observed_tables"]
                and self.composition.dispatcher is not None
            ),
            "worker_profile_valid": worker.get("status") == "PASS",
            "executor_registry_available": bool(
                self.composition.executor_profile.executor_kinds
            ),
            "configured_executor_kinds_available": not worker.get(
                "missing_executor_kinds", ["unknown"]
            ),
            "configured_backend_profiles_available": not worker.get(
                "missing_backend_profiles", ["unknown"]
            ),
            "package_readiness_satisfied": worker.get("in_process_package_status")
            in {"NOT_CONFIGURED", "PASS"},
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
            "worker": worker,
            "executor_kinds": list(self.composition.executor_profile.executor_kinds),
            "backend_profiles": list(
                self.composition.executor_profile.backend_profiles
            ),
            "work_capability": "job_claiming",
            "content_included": False,
            "secret_included": False,
        }

    def run_once(self) -> dict[str, Any]:
        return self.composition.run_cycle()

    def close(self) -> None:
        self.engine.dispose()


def build_deterministic_component_executor_profile() -> RuntimeExecutorProfile:
    projection = P5DeterministicProjectionExecutor()
    registry = P5StepExecutorRegistry(
        {
            "DETERMINISTIC_AGGREGATE": projection,
            "DETERMINISTIC_REPORT": projection,
        }
    )
    return RuntimeExecutorProfile(
        registry=registry,
        executor_backends={
            kind: NSL_V01_PROCESS_ISOLATED_BACKEND for kind in registry.registered_kinds
        },
    )


def build_source_check() -> dict[str, Any]:
    executor_profile = build_deterministic_component_executor_profile()
    return {
        "schema_version": PROCESS_SCHEMA_VERSION,
        "status": "PASS",
        "process_id": PROCESS_ID,
        "service_id": SERVICE_ID,
        "module": "nex_ae_api.agent_runtime_process",
        "composition_factory": build_installed_runtime_composition.__name__,
        "executor_kinds": list(executor_profile.executor_kinds),
        "backend_profiles": list(executor_profile.backend_profiles),
        "database_environments": dict(DATABASE_ENVIRONMENTS),
        "work_capability": "job_claiming",
        "runtime_ready": False,
        "content_included": False,
        "secret_included": False,
    }


def build_installed_agent_runtime_process(
    profile: str,
    *,
    environ: Mapping[str, str] | None = None,
    executor_profile: RuntimeExecutorProfile | None = None,
    engine_factory: Callable[..., Engine] = build_engine,
    engine_checker: Callable[[Engine], bool] = check_sqlalchemy_engine,
    session_factory_builder: Callable[
        [Engine], sessionmaker[Session]
    ] = build_session_factory,
) -> InstalledAgentRuntimeProcess:
    selected = _profile(profile)
    if selected not in DATABASE_ENVIRONMENTS:
        raise AgentRuntimeProcessError(
            "local_mock provides package admission only; protected execution "
            "requires a database-backed profile"
        )
    env = os.environ if environ is None else environ
    database_environment = DATABASE_ENVIRONMENTS[selected]
    worker_id = str(env.get("NEX_AE_AGENT_WORKER_ID") or DEFAULT_WORKER_ID).strip()
    if not worker_id:
        raise AgentRuntimeProcessError("Agent Runtime worker_id is required")
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
            raise AgentRuntimeProcessError("AE worker database readiness failed")
        sessions = session_factory_builder(engine)
        heartbeat = WorkerHeartbeatEmitter(
            service_id=SERVICE_ID,
            worker_id=worker_id,
            worker_type=AE_AGENT_RUNTIME_WORKER_TYPE,
            store=SqlAlchemyWorkerHeartbeatStore(sessions),
            metadata={
                "process_id": PROCESS_ID,
                "pool_workload": "worker",
                "evidence_classification": "PROTECTED_COMPONENT",
            },
        )
        selected_executor_profile = executor_profile
        if selected_executor_profile is None:
            selected_executor_profile = (
                build_product_runtime_executor_profile(sessions, env)
                if selected in {"staging_live", "production"}
                else build_deterministic_component_executor_profile()
            )
        composition = build_installed_runtime_composition(
            sessions=sessions,
            heartbeat_emitter=heartbeat,
            worker_id=worker_id,
            environ=env,
            executor_profile=selected_executor_profile,
        )
        return InstalledAgentRuntimeProcess(
            profile=selected,
            database_environment=database_environment,
            engine=engine,
            sessions=sessions,
            composition=composition,
        )
    except Exception as exc:
        if engine is not None:
            engine.dispose()
        if isinstance(exc, AgentRuntimeProcessError):
            raise
        raise AgentRuntimeProcessError(
            "installed AE Agent Runtime process is unavailable"
        ) from exc


def build_live_check(
    profile: str,
    *,
    environ: Mapping[str, str] | None = None,
    process_builder: Callable[..., InstalledAgentRuntimeProcess] = (
        build_installed_agent_runtime_process
    ),
) -> dict[str, Any]:
    if _profile(profile) == "local_mock":
        return build_source_check()
    process = process_builder(profile, environ=environ)
    try:
        return process.readiness()
    finally:
        process.close()


def run_installed_agent_runtime_process(
    process: InstalledAgentRuntimeProcess,
    *,
    max_cycles: int | None = None,
    should_stop: Callable[[], bool] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    out: TextIO | None = None,
) -> dict[str, Any]:
    if max_cycles is not None and (
        isinstance(max_cycles, bool)
        or not isinstance(max_cycles, int)
        or not 1 <= max_cycles <= 100_000
    ):
        raise AgentRuntimeProcessError("max_cycles must be between 1 and 100000")
    readiness = process.readiness()
    if readiness["readiness_status"] != "READY":
        raise AgentRuntimeProcessError("AE Agent Runtime process is not ready")
    stop = should_stop or (lambda: False)
    stream = out or sys.stdout
    completed_cycles = 0
    work_cycles = 0
    failed_count = 0
    print(
        json.dumps(
            {
                "schema_version": PROCESS_RUN_SCHEMA_VERSION,
                "process_id": PROCESS_ID,
                "state": "STARTED",
            },
            sort_keys=True,
        ),
        file=stream,
    )
    while not stop() and (max_cycles is None or completed_cycles < max_cycles):
        result = process.run_once()
        completed_cycles += 1
        work_cycles += result.get("status") == "WORK"
        failed_count += int(result.get("failed_count") or 0)
        if result.get("status") == "WORK":
            print(
                json.dumps(
                    {
                        "schema_version": PROCESS_RUN_SCHEMA_VERSION,
                        "process_id": PROCESS_ID,
                        "state": "WORK",
                        "execution_count": result.get("execution_count", 0),
                        "failed_count": result.get("failed_count", 0),
                    },
                    sort_keys=True,
                ),
                file=stream,
            )
        if not stop() and (max_cycles is None or completed_cycles < max_cycles):
            sleeper(process.composition.worker_config.poll_interval_seconds)
    stop_reason = "SHUTDOWN_REQUESTED" if stop() else "MAX_CYCLES"
    record = {
        "schema_version": PROCESS_RUN_SCHEMA_VERSION,
        "status": "STOPPED",
        "process_id": PROCESS_ID,
        "service_id": SERVICE_ID,
        "stop_reason": stop_reason,
        "completed_cycles": completed_cycles,
        "work_cycles": work_cycles,
        "failed_count": failed_count,
        "content_included": False,
        "secret_included": False,
    }
    print(json.dumps({**record, "state": "STOPPED"}, sort_keys=True), file=stream)
    return record


def run_live(
    profile: str,
    *,
    environ: Mapping[str, str] | None = None,
    max_cycles: int | None = None,
    process_builder: Callable[..., InstalledAgentRuntimeProcess] = (
        build_installed_agent_runtime_process
    ),
    out: TextIO | None = None,
) -> dict[str, Any]:
    process = process_builder(profile, environ=environ)
    token = AgentRuntimeShutdownToken()
    previous = install_agent_runtime_worker_signal_handlers(token)
    try:
        return run_installed_agent_runtime_process(
            process,
            max_cycles=max_cycles,
            should_stop=lambda: token.requested,
            out=out,
        )
    finally:
        restore_agent_runtime_worker_signal_handlers(previous)
        process.close()


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    live_check: Callable[..., Mapping[str, Any]] = build_live_check,
    live_run: Callable[..., Mapping[str, Any]] = run_live,
) -> int:
    env = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description="NeX AE Agent Runtime process")
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
    except (AgentRuntimeProcessError, ValueError) as exc:
        record = {
            "schema_version": PROCESS_SCHEMA_VERSION,
            "status": "BLOCKED",
            "process_id": PROCESS_ID,
            "failure_code": "ae.agent_runtime_process.unavailable",
            "detail": str(exc),
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
        for path in sorted((ROOT / "database/nex-ae-api/migrations").glob("*.sql"))
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
        raise AgentRuntimeProcessError("AE worker database check failed") from exc
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
        raise AgentRuntimeProcessError("unsupported AE Agent Runtime profile")
    return selected


if __name__ == "__main__":  # pragma: no cover - packaged command boundary
    raise SystemExit(main())
