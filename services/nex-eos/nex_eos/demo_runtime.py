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

from nex_eos.ae_outbox_transport import HttpAeEosOutboxTransport
from nex_eos.outbox_publication import SqlAlchemyEosOutboxPublisher

PROCESS_ID = "nex-eos-outbox-publisher"
COMPOSITION_MODE = "EXISTING_COMPONENT_COMPOSITION"
REQUIRED_DOMAIN_SECRETS = required_demo_domain_material(
    "nex-eos",
    database_environment_name="NEX_EOS_DATABASE_URL",
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
        "schema_version": "p8_demo_eos_runtime_check.v2",
        "status": "PASS",
        "process_id": PROCESS_ID,
        "publisher": SqlAlchemyEosOutboxPublisher.__name__,
        "database_environment": "NEX_EOS_DATABASE_URL",
        "pool_workload": "worker",
        "execution_enabled": True,
        "composition_mode": COMPOSITION_MODE,
        "new_business_behavior_added": False,
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
        database = demo_process_database_check(
            resource,
            required_tables=("eos_outbox", "service_worker_heartbeats"),
        )
        return {
            **build_source_check(os.environ if environ is None else environ),
            "database": database,
            "domain_claiming_enabled": activation.enabled,
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
    token = DemoProcessShutdownToken()
    previous = install_demo_process_signal_handlers(token)
    try:
        return run_demo_process_loop(
            resource,
            recovery_probe=lambda: _queue_projection(
                resource, recovery=True, domain_claiming_enabled=activation.enabled
            ),
            cycle=(
                (lambda: _publish_cycle(resource, env))
                if activation.enabled
                else (lambda: _queue_projection(resource, recovery=False))
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
    parser = argparse.ArgumentParser(description="NeX EOS Demo runtime process")
    parser.add_argument("process", choices=("outbox",))
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
            "schema_version": "p8_demo_eos_runtime_check.v2",
            "status": "BLOCKED",
            "process_id": "nex-eos-outbox-publisher",
            "failure_code": "p8_demo.eos_runtime.unavailable",
            "detail": str(exc),
            "secret_included": False,
        }
        code = 2
    print(json.dumps(record, sort_keys=True), file=stdout or sys.stdout)
    return code


def _config() -> DemoProcessRuntimeConfig:
    return DemoProcessRuntimeConfig(
        process_id=PROCESS_ID,
        service_id="nex-eos",
        worker_id="eos-demo-outbox-publisher-1",
        worker_type="eos.outbox.publisher",
        database_environment="NEX_EOS_DATABASE_URL",
    )


def _queue_projection(
    resource: DemoProcessDatabaseResource,
    *,
    recovery: bool,
    domain_claiming_enabled: bool = False,
) -> dict[str, Any]:
    with resource.sessions() as session:
        pending = session.execute(
            text("SELECT count(*) FROM eos_outbox WHERE delivery_state = 'PENDING'")
        ).scalar_one()
    return {
        "status": "IDLE",
        "probe": "RECOVERY" if recovery else "READINESS",
        "pending_outbox_count": int(pending or 0),
        "domain_claiming_enabled": domain_claiming_enabled,
    }


def _publish_cycle(
    resource: DemoProcessDatabaseResource, environ: Mapping[str, str]
) -> dict[str, Any]:
    publisher = SqlAlchemyEosOutboxPublisher(resource.sessions)
    transport = HttpAeEosOutboxTransport(
        base_url=str(environ.get("NEX_AE_API_BASE_URL") or "").strip(),
        service_token=str(environ.get("NEX_EOS_TO_AE_SERVICE_TOKEN") or ""),
        timeout_seconds=float(
            str(environ.get("NEX_EOS_AE_OUTBOX_TIMEOUT_SECONDS") or "10")
        ),
    )
    result = publisher.publish_next(transport)
    if result is None:
        return {
            "status": "IDLE",
            "domain_claiming_enabled": True,
            "published_count": 0,
        }
    return {
        "status": "WORK",
        "domain_claiming_enabled": True,
        "composition_mode": COMPOSITION_MODE,
        "published_count": int(result.delivery_state == "PUBLISHED"),
        "retry_required": result.retry_required,
        "delivery_state": result.delivery_state,
    }


if __name__ == "__main__":  # pragma: no cover - exercised by packaged command
    raise SystemExit(main())
