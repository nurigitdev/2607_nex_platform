from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TextIO

from nex_runtime import SqlAlchemyJobQueue, WorkerRunnerConfig, run_worker_once
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

from nex_wc.approval_event_delivery import (
    ApprovalEventDeliveryError,
    HttpAeApprovalEventClient,
    SqlAlchemyApprovalEventDeliveryStore,
    deliver_pending_approval_events,
)
from nex_wc.approvals import SqlAlchemyApprovalWorkItemRepository
from nex_wc.coordination import SqlAlchemyCoordinationRepository
from nex_wc.handoff_delivery import (
    WC_EVENT_DELIVERY_JOB_TYPE,
    HttpClaimHandoffClient,
    enqueue_pending_handoffs,
    run_handoff_delivery_job,
    run_handoff_delivery_worker_once,
)
from nex_wc.work_result_delivery import (
    HttpWorkResultEventClient,
    enqueue_pending_result_events,
    run_work_result_delivery_job,
)
from nex_wc.work_results import SqlAlchemyWorkResultRepository

PROCESS_ID = "nex-wc-event-delivery-worker"
COMPOSITION_MODE = "EXISTING_COMPONENT_COMPOSITION"
REQUIRED_DOMAIN_SECRETS = required_demo_domain_material(
    "nex-wc",
    database_environment_name="NEX_WC_DATABASE_URL",
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
        "schema_version": "p8_demo_wc_runtime_check.v2",
        "status": "PASS",
        "process_id": PROCESS_ID,
        "database_environment": "NEX_WC_DATABASE_URL",
        "pool_workload": "worker",
        "adapters": {
            "claim_handoff": run_handoff_delivery_worker_once.__name__,
            "work_result": run_work_result_delivery_job.__name__,
            "approval_outbox": SqlAlchemyApprovalWorkItemRepository.__name__,
        },
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
            required_tables=(
                "service_jobs",
                "service_worker_heartbeats",
                "wc_event_outbox",
                "wc_approval_outbox",
            ),
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
                (lambda: _delivery_cycle(resource, env))
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
    except (DemoDomainActivationError, DemoProcessRuntimeError, ValueError) as exc:
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
        process_id=PROCESS_ID,
        service_id="nex-wc",
        worker_id="wc-demo-event-delivery-1",
        worker_type="wc.event_delivery.worker",
        database_environment="NEX_WC_DATABASE_URL",
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
                    "SELECT "
                    "(SELECT count(*) FROM service_jobs WHERE status IN ('QUEUED','RUNNING')) "
                    "AS active_jobs, "
                    "(SELECT count(*) FROM wc_event_outbox WHERE delivery_state IN "
                    "('PENDING','ENQUEUED')) AS coordination_events, "
                    "(SELECT count(*) FROM wc_approval_outbox WHERE delivery_state IN "
                    "('PENDING','ENQUEUED')) AS approval_events"
                )
            )
            .mappings()
            .one()
        )
    return {
        "status": "IDLE",
        "probe": "RECOVERY" if recovery else "READINESS",
        "active_job_count": int(row["active_jobs"] or 0),
        "coordination_event_count": int(row["coordination_events"] or 0),
        "approval_event_count": int(row["approval_events"] or 0),
        "domain_claiming_enabled": domain_claiming_enabled,
    }


def _delivery_cycle(
    resource: DemoProcessDatabaseResource, environ: Mapping[str, str]
) -> dict[str, Any]:
    queue = SqlAlchemyJobQueue(resource.sessions)
    coordination = SqlAlchemyCoordinationRepository(resource.sessions)
    work_results = SqlAlchemyWorkResultRepository(resource.sessions)
    enqueued = [
        *enqueue_pending_handoffs(store=coordination, queue=queue),
        *enqueue_pending_result_events(store=work_results, queue=queue),
    ]
    token = str(environ.get("NEX_WC_TO_AE_SERVICE_TOKEN") or "")
    base_url = str(environ.get("NEX_WC_AE_BASE_URL") or "").strip()
    handoff_client = HttpClaimHandoffClient(base_url=base_url, service_token=token)
    result_client = HttpWorkResultEventClient(base_url=base_url, service_token=token)

    def deliver(job: Mapping[str, Any]) -> dict[str, Any]:
        payload = job.get("payload")
        if not isinstance(payload, Mapping):
            raise DemoProcessRuntimeError("WC delivery job payload is invalid")
        with resource.sessions() as session:
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
                job, store=coordination, client=handoff_client
            )
        if event_type == "WORK_RESULT_SUBMITTED":
            return run_work_result_delivery_job(
                job, store=work_results, client=result_client
            )
        raise DemoProcessRuntimeError("WC delivery event type is unsupported")

    execution = run_worker_once(
        config=WorkerRunnerConfig(
            service_id="nex-wc",
            worker_id="wc-demo-event-delivery-1",
            worker_type="wc.event_delivery.worker",
            job_type=WC_EVENT_DELIVERY_JOB_TYPE,
        ),
        queue=queue,
        heartbeat_emitter=resource.heartbeat,
        handler=deliver,
    )
    if execution.status == "FAILED":
        raise DemoProcessRuntimeError("WC domain event delivery failed")
    try:
        approval_delivery = deliver_pending_approval_events(
            store=SqlAlchemyApprovalEventDeliveryStore(resource.sessions),
            client=HttpAeApprovalEventClient(
                base_url=base_url,
                service_token=token,
                timeout_seconds=float(
                    str(environ.get("NEX_WC_AE_APPROVAL_TIMEOUT_SECONDS") or "15")
                ),
            ),
        )
    except ApprovalEventDeliveryError as exc:
        raise DemoProcessRuntimeError("WC approval event delivery failed") from exc
    return {
        "status": (
            "WORK"
            if execution.job is not None
            or enqueued
            or approval_delivery["delivered_count"]
            else "IDLE"
        ),
        "domain_claiming_enabled": True,
        "composition_mode": COMPOSITION_MODE,
        "enqueued_count": len(enqueued),
        "claimed_count": int(execution.job is not None),
        "delivery_status": execution.status,
        "approval_delivered_count": approval_delivery["delivered_count"],
    }


if __name__ == "__main__":  # pragma: no cover - exercised by packaged command
    raise SystemExit(main())
