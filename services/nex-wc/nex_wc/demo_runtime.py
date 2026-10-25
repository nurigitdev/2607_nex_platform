from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TextIO

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

from nex_wc.approvals import SqlAlchemyApprovalWorkItemRepository
from nex_wc.handoff_delivery import run_handoff_delivery_worker_once
from nex_wc.work_result_delivery import run_work_result_delivery_job


def build_source_check() -> dict[str, object]:
    return {
        "schema_version": "p8_demo_wc_runtime_check.v2",
        "status": "PASS",
        "process_id": "nex-wc-event-delivery-worker",
        "database_environment": "NEX_WC_DATABASE_URL",
        "pool_workload": "worker",
        "adapters": {
            "claim_handoff": run_handoff_delivery_worker_once.__name__,
            "work_result": run_work_result_delivery_job.__name__,
            "approval_outbox": SqlAlchemyApprovalWorkItemRepository.__name__,
        },
        "execution_enabled": True,
        "domain_claiming_enabled": False,
        "domain_claiming_activation": "P8-DEMO-S10",
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
        database = demo_process_database_check(
            resource,
            required_tables=(
                "service_jobs",
                "service_worker_heartbeats",
                "wc_event_outbox",
                "wc_approval_outbox",
            ),
        )
        return {**build_source_check(), "database": database}
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
    resource = resource_builder(
        _config(), environ=os.environ if environ is None else environ
    )
    token = DemoProcessShutdownToken()
    previous = install_demo_process_signal_handlers(token)
    try:
        return run_demo_process_loop(
            resource,
            recovery_probe=lambda: _queue_projection(resource, recovery=True),
            cycle=lambda: _queue_projection(resource, recovery=False),
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
    parser = argparse.ArgumentParser(description="NeX WC Demo runtime process")
    parser.add_argument("process", choices=("events",))
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
    except (DemoProcessRuntimeError, ValueError) as exc:
        record = {
            "schema_version": "p8_demo_wc_runtime_check.v2",
            "status": "BLOCKED",
            "process_id": "nex-wc-event-delivery-worker",
            "failure_code": "p8_demo.wc_runtime.unavailable",
            "detail": str(exc),
            "secret_included": False,
        }
        code = 2
    print(json.dumps(record, sort_keys=True), file=stdout or sys.stdout)
    return code


def _config() -> DemoProcessRuntimeConfig:
    return DemoProcessRuntimeConfig(
        process_id="nex-wc-event-delivery-worker",
        service_id="nex-wc",
        worker_id="wc-demo-event-delivery-1",
        worker_type="wc.event_delivery.worker",
        database_environment="NEX_WC_DATABASE_URL",
    )


def _queue_projection(
    resource: DemoProcessDatabaseResource, *, recovery: bool
) -> dict[str, Any]:
    with resource.sessions() as session:
        row = session.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM service_jobs WHERE status IN ('QUEUED','RUNNING')) "
                "AS active_jobs, "
                "(SELECT count(*) FROM wc_event_outbox WHERE delivery_state IN "
                "('PENDING','ENQUEUED')) AS coordination_events, "
                "(SELECT count(*) FROM wc_approval_outbox WHERE delivery_state IN "
                "('PENDING','ENQUEUED')) AS approval_events"
            )
        ).mappings().one()
    return {
        "status": "IDLE",
        "probe": "RECOVERY" if recovery else "READINESS",
        "active_job_count": int(row["active_jobs"] or 0),
        "coordination_event_count": int(row["coordination_events"] or 0),
        "approval_event_count": int(row["approval_events"] or 0),
        "domain_claiming_enabled": False,
    }


if __name__ == "__main__":  # pragma: no cover - exercised by packaged command
    raise SystemExit(main())
