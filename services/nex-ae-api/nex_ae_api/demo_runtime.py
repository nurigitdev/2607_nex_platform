from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TextIO

from nex_runtime.demo_domain_activation import (
    DemoDomainActivationError,
    required_demo_domain_material,
    resolve_demo_domain_activation,
)
from nex_runtime.demo_process_runtime import (
    DemoProcessDatabaseResource,
    DemoProcessRuntimeConfig,
    DemoProcessRuntimeError,
    DemoProcessShutdownToken,
    build_demo_package_check,
    build_demo_process_database_resource,
    demo_package_check_requested,
    demo_process_database_check,
    install_demo_process_signal_handlers,
    restore_demo_process_signal_handlers,
    run_demo_process_loop,
)
from sqlalchemy import text

from nex_ae_api.agent_runtime_dispatcher import SqlAlchemyAgentRuntimeAssignmentSource
from nex_ae_api.agent_runtime_worker import run_bounded_agent_runtime_worker
from nex_ae_api.p8_demo_runtime_composition import (
    InstalledP8RuntimeComposition,
    build_installed_p8_runtime_composition,
)

PROCESS_ID = "nex-ae-agent-runtime-worker"
COMPOSITION_MODE = "EXISTING_COMPONENT_COMPOSITION"
REQUIRED_DOMAIN_SECRETS = required_demo_domain_material(
    "nex-ae-api",
    database_environment_name="NEX_AE_DATABASE_URL",
)


def build_source_check(
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    activation = resolve_demo_domain_activation(
        {} if environ is None else environ,
        process_id=PROCESS_ID,
        required_secret_names=REQUIRED_DOMAIN_SECRETS,
    )
    return {
        "schema_version": "p8_demo_ae_runtime_check.v3",
        "status": "PASS",
        "process_id": PROCESS_ID,
        "dispatcher_model": "EMBEDDED_DB_LEASE_ASSIGNMENT_SOURCE",
        "worker_runner": run_bounded_agent_runtime_worker.__name__,
        "assignment_source": SqlAlchemyAgentRuntimeAssignmentSource.__name__,
        "database_environment": "NEX_AE_DATABASE_URL",
        "pool_workload": "worker",
        "execution_enabled": True,
        "composition_mode": COMPOSITION_MODE,
        "new_business_behavior_added": False,
        "installed_execution_composition": "P6_P8_EXISTING_COMPONENTS",
        "domain_claiming_enabled": activation.enabled,
        "domain_claiming_activation": (
            "ACTIVE" if activation.enabled else "P8-DEMO-S10"
        ),
        "activation": activation.to_projection(),
    }


def build_live_check(
    environ: Mapping[str, str] | None = None,
    *,
    resource_builder: Callable[..., DemoProcessDatabaseResource] = (
        build_demo_process_database_resource
    ),
) -> dict[str, object]:
    resource = resource_builder(
        _config(), environ=os.environ if environ is None else environ
    )
    try:
        activation = resolve_demo_domain_activation(
            os.environ if environ is None else environ,
            process_id=PROCESS_ID,
            required_secret_names=REQUIRED_DOMAIN_SECRETS,
        )
        composition = (
            _build_composition(resource, os.environ if environ is None else environ)
            if activation.enabled
            else None
        )
        database = demo_process_database_check(
            resource,
            required_tables=(
                "ae_runtime_job",
                "ae_rt_dispatch_lease",
                "service_worker_heartbeats",
            ),
        )
        return {
            **build_source_check(os.environ if environ is None else environ),
            "database": database,
            "domain_claiming_enabled": activation.enabled,
            "installed_composition_ready": composition is not None,
        }
    finally:
        resource.close()


def run_live(
    environ: Mapping[str, str] | None = None,
    *,
    max_cycles: int | None = None,
    resource_builder: Callable[..., DemoProcessDatabaseResource] = (
        build_demo_process_database_resource
    ),
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    activation = resolve_demo_domain_activation(
        env,
        process_id=PROCESS_ID,
        required_secret_names=REQUIRED_DOMAIN_SECRETS,
    )
    resource = resource_builder(_config(), environ=env)
    composition = _build_composition(resource, env) if activation.enabled else None
    token = DemoProcessShutdownToken()
    previous = install_demo_process_signal_handlers(token)
    try:
        return run_demo_process_loop(
            resource,
            recovery_probe=lambda: _queue_projection(
                resource, recovery=True, domain_claiming_enabled=activation.enabled
            ),
            cycle=(
                composition.run_cycle
                if composition is not None
                else lambda: _queue_projection(
                    resource,
                    recovery=False,
                    domain_claiming_enabled=False,
                )
            ),
            shutdown_token=token,
            max_cycles=max_cycles,
        )
    finally:
        restore_demo_process_signal_handlers(previous)
        resource.close()


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
    live_check: Callable[[Mapping[str, str] | None], Mapping[str, Any]] = (
        build_live_check
    ),
    live_run: Callable[..., Mapping[str, Any]] = run_live,
) -> int:
    parser = argparse.ArgumentParser(description="NeX AE Demo runtime process")
    parser.add_argument("process", choices=("worker",))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--max-cycles", type=int)
    args = parser.parse_args(list(argv) if argv is not None else None)
    environment = os.environ if environ is None else environ
    try:
        record = (
            build_demo_package_check(build_source_check())
            if args.check and demo_package_check_requested(environment)
            else dict(live_check(environ))
            if args.check
            else dict(live_run(environ, max_cycles=args.max_cycles))
        )
        code = 0
    except (DemoDomainActivationError, DemoProcessRuntimeError, ValueError) as exc:
        record = {
            "schema_version": "p8_demo_ae_runtime_check.v3",
            "status": "BLOCKED",
            "process_id": "nex-ae-agent-runtime-worker",
            "failure_code": "p8_demo.ae_runtime.unavailable",
            "detail": str(exc),
            "secret_included": False,
        }
        code = 2
    print(json.dumps(record, sort_keys=True), file=stdout or sys.stdout)
    return code


def _config() -> DemoProcessRuntimeConfig:
    return DemoProcessRuntimeConfig(
        process_id=PROCESS_ID,
        service_id="nex-ae-api",
        worker_id="ae-demo-agent-runtime-1",
        worker_type="ae.agent_runtime.worker",
        database_environment="NEX_AE_DATABASE_URL",
    )


def _queue_projection(
    resource: DemoProcessDatabaseResource,
    *,
    recovery: bool,
    domain_claiming_enabled: bool = False,
) -> dict[str, Any]:
    with resource.sessions() as session:
        row = (
            session.execute(
                text(
                    "SELECT count(*) FILTER (WHERE state = 'QUEUED') AS queued, "
                    "count(*) FILTER (WHERE state = 'RUNNING' AND lease_until <= now()) "
                    "AS recoverable FROM ae_runtime_job"
                )
            )
            .mappings()
            .one()
        )
    return {
        "status": "IDLE",
        "probe": "RECOVERY" if recovery else "READINESS",
        "queued_count": int(row["queued"] or 0),
        "recoverable_lease_count": int(row["recoverable"] or 0),
        "domain_claiming_enabled": domain_claiming_enabled,
    }


def _build_composition(
    resource: DemoProcessDatabaseResource,
    environ: Mapping[str, str],
) -> InstalledP8RuntimeComposition:
    try:
        return build_installed_p8_runtime_composition(resource, environ)
    except Exception as exc:
        raise DemoProcessRuntimeError(
            "installed P6-P8 execution composition is unavailable"
        ) from exc


if __name__ == "__main__":  # pragma: no cover - exercised by packaged command
    raise SystemExit(main())
