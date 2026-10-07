from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass, field
import importlib
import json
import os
from pathlib import Path
import signal
import sys
import time
from typing import Any, Callable, Sequence, TextIO


ROOT = Path(__file__).resolve().parents[3]
SHARED_PATH = ROOT / "services" / "_shared"
BACKGROUND_MODULES = {
    "nex-ae-artifact-render-worker": (
        "nex-ae-api",
        "nex_ae_api.async_artifact_render_worker",
    ),
    "nex-ae-retention-daemon": (
        "nex-ae-api",
        "nex_ae_api.artifact_retention_scheduler_daemon",
    ),
    "nex-ag-remediation-sync-worker": (
        "nex-ag",
        "nex_ag.remediation_execution_status_sync_worker",
    ),
    "nex-ag-dispatch-daemon": (
        "nex-ag",
        "nex_ag.operator_review_dispatch_daemon",
    ),
    "nex-cx-async-generation-worker": (
        "nex-cx",
        "nex_cx.async_generation_worker",
    ),
    "nex-cx-ingestion-worker": ("nex-cx", "nex_cx.ingestion_worker"),
    "nex-cx-remediation-worker": (
        "nex-cx",
        "nex_cx.remediation_execution_worker",
    ),
}
BACKGROUND_DATABASE_ENVIRONMENTS = {
    "nex-ae-api": {
        "default": "NEX_AE_DATABASE_URL",
        "test": "NEX_AE_TEST_DATABASE_URL",
    },
    "nex-ag": {
        "default": "NEX_AG_DATABASE_URL",
        "test": "NEX_AG_TEST_DATABASE_URL",
    },
    "nex-cx": {
        "default": "NEX_CX_DATABASE_URL",
        "test": "NEX_CX_TEST_DATABASE_URL",
    },
}
ENABLED_BACKGROUND_PROFILES = ("local_mock", "test")
_STOP_REQUESTED = False


@dataclass
class BackgroundProcessResource:
    metadata: dict[str, object]
    engine: Any | None = field(default=None, repr=False)

    def close(self) -> None:
        if self.engine is None:
            return
        try:
            self.engine.dispose()
        except Exception as exc:
            raise ValueError("background persistence disposal failed") from exc
        self.engine = None


def prepare_background_process(
    process_id: str,
    profile: str,
    *,
    environ: Mapping[str, str] | None = None,
    engine_factory: Callable[..., Any] | None = None,
    engine_checker: Callable[[Any], bool] | None = None,
) -> BackgroundProcessResource:
    if process_id not in BACKGROUND_MODULES:
        raise ValueError(f"unsupported background process: {process_id}")
    if profile not in ENABLED_BACKGROUND_PROFILES:
        raise ValueError("background process profile is not enabled")
    service_id, module_name = BACKGROUND_MODULES[process_id]
    _configure_import_path(service_id)
    importlib.import_module(module_name)
    metadata: dict[str, object] = {
        "schema_version": "platform_background_process_shell.v2",
        "process_id": process_id,
        "service_id": service_id,
        "module": module_name,
        "profile": profile,
        "packaged_entrypoint": "nex_runtime.background_process",
        "work_claiming_enabled": False,
        "lifecycle_ready": True,
        "persistence_mode": "memory",
        "pool_workload": None,
    }
    if profile == "local_mock":
        return BackgroundProcessResource(metadata)

    from nex_runtime import build_engine, check_sqlalchemy_engine, database_pool_settings

    env = os.environ if environ is None else environ
    database_env = _database_environment(service_id, profile)
    engine = None
    try:
        database_url = _required_database_url(database_env, env)
        settings = database_pool_settings(
            service_id, workload="worker", environ=env
        )
        build = engine_factory or build_engine
        check = engine_checker or check_sqlalchemy_engine
        engine = build(database_url, pool_settings=settings)
        if not check(engine):
            raise ValueError("worker database readiness failed")
    except Exception as exc:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass
        raise ValueError("protected background persistence unavailable") from exc
    metadata.update(
        persistence_mode="postgres",
        pool_workload="worker",
        database_env=database_env,
    )
    return BackgroundProcessResource(metadata, engine)


def background_process_metadata(
    process_id: str,
    profile: str,
    *,
    environ: Mapping[str, str] | None = None,
    engine_factory: Callable[..., Any] | None = None,
    engine_checker: Callable[[Any], bool] | None = None,
) -> dict[str, object]:
    resource = prepare_background_process(
        process_id,
        profile,
        environ=environ,
        engine_factory=engine_factory,
        engine_checker=engine_checker,
    )
    try:
        return dict(resource.metadata)
    finally:
        resource.close()


def run_background_process_shell(
    process_id: str,
    profile: str,
    *,
    poll_interval_seconds: float = 0.25,
    should_stop: Callable[[], bool] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    out: TextIO | None = None,
    enable_work_claiming: bool = False,
) -> int:
    stream = out or sys.stdout
    work_process = None
    if enable_work_claiming and process_id == "nex-cx-ingestion-worker":
        work_process = _build_ingestion_work_process(profile)
        resource = BackgroundProcessResource(work_process.metadata())
    else:
        resource = prepare_background_process(process_id, profile)
    metadata = resource.metadata
    print(json.dumps({**metadata, "state": "STARTED"}, sort_keys=True), file=stream)
    try:
        stop = should_stop or (lambda: _STOP_REQUESTED)
        if work_process is not None:
            startup = work_process.startup()
            print(
                json.dumps(
                    {"process_id": process_id, "state": "RECOVERED", **startup},
                    sort_keys=True,
                ),
                file=stream,
            )
        while not stop():
            if work_process is not None:
                result = work_process.run_once()
                if result["status"] != "IDLE":
                    print(
                        json.dumps(
                            {"process_id": process_id, "state": "WORK", **result},
                            sort_keys=True,
                        ),
                        file=stream,
                    )
            sleeper(poll_interval_seconds)
    finally:
        if work_process is not None:
            work_process.close()
        resource.close()
    print(
        json.dumps({**metadata, "state": "STOPPED"}, sort_keys=True),
        file=stream,
    )
    return 0


def main(argv: Sequence[str] | None = None, out: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("process_id", choices=sorted(BACKGROUND_MODULES))
    parser.add_argument("--profile", default="local_mock")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--poll-interval-seconds", type=float, default=0.25)
    args = parser.parse_args(argv)
    try:
        if args.check:
            metadata = background_process_metadata(args.process_id, args.profile)
            print(json.dumps(metadata, sort_keys=True), file=out or sys.stdout)
            return 0
        if args.poll_interval_seconds <= 0:
            raise ValueError("poll interval must be positive")
        return run_background_process_shell(
            args.process_id,
            args.profile,
            poll_interval_seconds=args.poll_interval_seconds,
            out=out,
            enable_work_claiming=True,
        )
    except ValueError as exc:
        print(
            json.dumps({"status": "BLOCKED", "detail": str(exc)}),
            file=out or sys.stdout,
        )
        return 2


def install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, _handle_stop_signal)
    signal.signal(signal.SIGINT, _handle_stop_signal)


def _configure_import_path(service_id: str) -> None:
    for path in (SHARED_PATH, ROOT / "services" / service_id):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def _database_environment(service_id: str, profile: str) -> str:
    names = BACKGROUND_DATABASE_ENVIRONMENTS[service_id]
    return names["test"] if profile == "test" else names["default"]


def _required_database_url(name: str, environ: Mapping[str, str]) -> str:
    value = str(environ.get(name) or "").strip()
    if not value:
        raise ValueError(f"required database URL is missing: {name}")
    return value


def _build_ingestion_work_process(profile: str):
    _configure_import_path("nex-cx")
    from nex_cx.ingestion_worker_process import (
        IngestionWorkerProcessError,
        build_default_ingestion_worker_process,
    )

    try:
        return build_default_ingestion_worker_process(profile)
    except IngestionWorkerProcessError as exc:
        raise ValueError(str(exc)) from exc


def _handle_stop_signal(signum: int, frame: object) -> None:
    del signum, frame
    global _STOP_REQUESTED
    _STOP_REQUESTED = True


if __name__ == "__main__":  # pragma: no cover
    install_signal_handlers()
    raise SystemExit(main())
