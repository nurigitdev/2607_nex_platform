from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence, TextIO
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import OperationalEventEmitter, WorkerHeartbeatEmitter

from nex_ag.operator_review_cases import (
    OperatorReviewCaseService,
    OperatorReviewCaseStore,
    OperatorReviewEscalationDispatchStore,
    OperatorReviewEscalationStore,
)
from nex_ag.operator_review_dispatch_execution import (
    DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT_ENV,
    DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV,
    DISPATCH_EXECUTION_DAEMON_ENABLED_ENV,
    build_dispatch_execution_daemon_loop_policy,
    build_dispatch_execution_daemon_policy,
    build_dispatch_execution_daemon_heartbeat,
    build_dispatch_execution_daemon_process_metadata,
    build_dispatch_execution_daemon_process_runtime_state,
    emit_dispatch_execution_daemon_lifecycle_event,
    run_dispatch_execution_daemon_bounded_loop,
    summarize_dispatch_execution_daemon_bounded_loop_result,
    assert_dispatch_execution_result_redacted,
)
from nex_ag.operator_reviews import optional_text


DISPATCH_EXECUTION_DAEMON_CLI_PLAN_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_daemon_cli_plan.v1"
)
DISPATCH_EXECUTION_DAEMON_CLI_RESULT_SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_execution_daemon_cli_result.v1"
)


def build_dispatch_execution_daemon_cli_plan(
    *,
    action: str = "plan",
    environ: Mapping[str, str] | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    worker_id: str = "ag-dispatch-execution-daemon",
    confirm_tick: bool = False,
    dry_run: bool | None = None,
    cycle_limit: int | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    normalized_action = _normalize_cli_action(action)
    now = started_at or _utc_now()
    runtime_env = _daemon_cli_environ(
        environ,
        dry_run=dry_run,
        cycle_limit=cycle_limit,
    )
    resolved_request_id = optional_text(request_id) or _default_request_id(
        normalized_action,
        worker_id,
        now,
    )
    policy = build_dispatch_execution_daemon_policy(runtime_env)
    loop_policy = build_dispatch_execution_daemon_loop_policy(policy=policy)
    metadata = build_dispatch_execution_daemon_process_metadata(
        worker_id=worker_id,
        policy=policy,
        loop_policy=loop_policy,
        started_at=now,
    )
    plan = {
        "daemon_cli_plan_schema_version": (
            DISPATCH_EXECUTION_DAEMON_CLI_PLAN_SCHEMA_VERSION
        ),
        "action": normalized_action,
        "command_mode": "bounded_loop",
        "will_execute": normalized_action == "run_once",
        "request_id": resolved_request_id,
        "trace_id": optional_text(trace_id),
        "worker_id": worker_id,
        "confirm_tick": bool(confirm_tick),
        "dry_run": bool(loop_policy.get("dry_run")),
        "requires_confirm_tick": bool(loop_policy.get("requires_confirm_tick")),
        "policy": policy,
        "loop_policy": loop_policy,
        "process_metadata": metadata,
        "new_tables_required": False,
        "redaction": policy["redaction"],
    }
    assert_dispatch_execution_result_redacted(plan)
    return plan


def execute_dispatch_execution_daemon_cli(
    *,
    action: str = "plan",
    service: OperatorReviewCaseService | None = None,
    environ: Mapping[str, str] | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    worker_id: str = "ag-dispatch-execution-daemon",
    confirm_tick: bool = False,
    dry_run: bool | None = None,
    cycle_limit: int | None = None,
    started_at: str | None = None,
    lifecycle_emitter: OperationalEventEmitter | None = None,
    heartbeat_emitter: WorkerHeartbeatEmitter | None = None,
) -> dict[str, Any]:
    plan = build_dispatch_execution_daemon_cli_plan(
        action=action,
        environ=environ,
        request_id=request_id,
        trace_id=trace_id,
        worker_id=worker_id,
        confirm_tick=confirm_tick,
        dry_run=dry_run,
        cycle_limit=cycle_limit,
        started_at=started_at,
    )
    loop_result = None
    lifecycle_events = []
    heartbeat_events = []
    if plan["action"] == "run_once":
        if heartbeat_emitter is not None:
            heartbeat_events.append(
                heartbeat_emitter.safe_emit(
                    status="STARTING",
                    trace_id=optional_text(plan.get("trace_id")),
                    metadata=build_dispatch_execution_daemon_heartbeat(
                        plan["process_metadata"],
                        status="STARTING",
                        trace_id=optional_text(plan.get("trace_id")),
                        observed_at=started_at,
                    )["metadata"],
                    observed_at=started_at,
                ).to_summary()
            )
            heartbeat_events.append(
                heartbeat_emitter.safe_emit(
                    status="BUSY",
                    active_job_id=_heartbeat_active_job_id(plan),
                    trace_id=optional_text(plan.get("trace_id")),
                    metadata=build_dispatch_execution_daemon_heartbeat(
                        plan["process_metadata"],
                        status="BUSY",
                        active_job_id=_heartbeat_active_job_id(plan),
                        trace_id=optional_text(plan.get("trace_id")),
                        observed_at=started_at,
                    )["metadata"],
                    observed_at=started_at,
                ).to_summary()
            )
        if lifecycle_emitter is not None:
            lifecycle_events.append(
                emit_dispatch_execution_daemon_lifecycle_event(
                    lifecycle_emitter,
                    process_metadata=plan["process_metadata"],
                    event_name="started",
                    request_id=str(plan["request_id"]),
                    trace_id=optional_text(plan.get("trace_id")),
                    occurred_at=started_at,
                ).to_summary()
            )
        loop_result = build_dispatch_execution_daemon_bounded_loop_result(
            service or _empty_operator_review_service(),
            plan,
            confirm_tick=confirm_tick,
            dry_run=dry_run,
            started_at=started_at,
        )
    runtime_state = build_dispatch_execution_daemon_process_runtime_state(
        plan["process_metadata"],
        loop_result=loop_result,
        observed_at=started_at,
    )
    if loop_result is not None and heartbeat_emitter is not None:
        final_status = (
            "ERROR" if runtime_state["state_status"] == "DEGRADED" else "STOPPED"
        )
        heartbeat_events.append(
            heartbeat_emitter.safe_emit(
                status=final_status,
                trace_id=optional_text(plan.get("trace_id")),
                metadata=build_dispatch_execution_daemon_heartbeat(
                    plan["process_metadata"],
                    runtime_state=runtime_state,
                    status=final_status,
                    trace_id=optional_text(plan.get("trace_id")),
                    observed_at=started_at,
                )["metadata"],
                observed_at=started_at,
            ).to_summary()
        )
    if loop_result is not None and lifecycle_emitter is not None:
        lifecycle_events.append(
            emit_dispatch_execution_daemon_lifecycle_event(
                lifecycle_emitter,
                process_metadata=plan["process_metadata"],
                event_name="completed",
                loop_result=loop_result,
                runtime_state=runtime_state,
                request_id=str(plan["request_id"]),
                trace_id=optional_text(plan.get("trace_id")),
                occurred_at=started_at,
            ).to_summary()
        )
    result = {
        "daemon_cli_result_schema_version": (
            DISPATCH_EXECUTION_DAEMON_CLI_RESULT_SCHEMA_VERSION
        ),
        "result_status": "EXECUTED" if loop_result is not None else "PLANNED",
        "plan": plan,
        "loop_result": loop_result,
        "loop_summary": summarize_dispatch_execution_daemon_bounded_loop_result(
            loop_result
        )
        if loop_result is not None
        else None,
        "lifecycle_events": lifecycle_events,
        "heartbeat_events": heartbeat_events,
        "runtime_state": runtime_state,
        "new_tables_required": False,
        "redaction": plan["redaction"],
    }
    assert_dispatch_execution_result_redacted(result)
    return result


def build_dispatch_execution_daemon_bounded_loop_result(
    service: OperatorReviewCaseService,
    plan: Mapping[str, Any],
    *,
    confirm_tick: bool,
    dry_run: bool | None,
    started_at: str | None,
) -> dict[str, Any]:
    return run_dispatch_execution_daemon_bounded_loop(
        service,
        request_id=str(plan["request_id"]),
        trace_id=optional_text(plan.get("trace_id")),
        worker_id=str(plan["worker_id"]),
        policy=plan["policy"],
        loop_policy=plan["loop_policy"],
        confirm_tick=confirm_tick,
        dry_run=dry_run,
        started_at=started_at,
    )


def summary_line(result: Mapping[str, Any]) -> str:
    plan = result.get("plan") if isinstance(result.get("plan"), Mapping) else {}
    loop_summary = (
        result.get("loop_summary")
        if isinstance(result.get("loop_summary"), Mapping)
        else {}
    )
    runtime_state = (
        result.get("runtime_state")
        if isinstance(result.get("runtime_state"), Mapping)
        else {}
    )
    return (
        "ag_dispatch_execution_daemon_cli="
        f"{str(result.get('result_status') or 'UNKNOWN').lower()} "
        f"action={plan.get('action')} "
        f"state={runtime_state.get('state_status')} "
        f"loop={loop_summary.get('loop_status', 'NONE')} "
        f"heartbeats={len(result.get('heartbeat_events') or [])} "
        f"stop={loop_summary.get('stop_reason', 'none')} "
        f"new_tables={result.get('new_tables_required')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the AG operator review escalation dispatch daemon facade."
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--plan", action="store_true", help="Print a safe run plan.")
    action.add_argument(
        "--run-once",
        action="store_true",
        help="Execute one bounded daemon loop against the configured service facade.",
    )
    parser.add_argument("--request-id")
    parser.add_argument("--trace-id")
    parser.add_argument("--worker-id", default="ag-dispatch-execution-daemon")
    parser.add_argument("--confirm-tick", action="store_true")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true")
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    parser.set_defaults(dry_run=None)
    parser.add_argument("--cycle-limit", type=int)
    parser.add_argument("--started-at")
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None, stdout: TextIO | None = None) -> int:
    args = build_parser().parse_args(argv)
    action = "run_once" if args.run_once else "plan"
    result = execute_dispatch_execution_daemon_cli(
        action=action,
        request_id=args.request_id,
        trace_id=args.trace_id,
        worker_id=args.worker_id,
        confirm_tick=args.confirm_tick,
        dry_run=args.dry_run,
        cycle_limit=args.cycle_limit,
        started_at=args.started_at,
    )
    output = summary_line(result) if args.summary else json.dumps(result, default=str)
    print(output, file=stdout)
    return 0


def _daemon_cli_environ(
    environ: Mapping[str, str] | None,
    *,
    dry_run: bool | None,
    cycle_limit: int | None,
) -> dict[str, str]:
    runtime_env = dict(os.environ if environ is None else environ)
    if dry_run is not None:
        runtime_env[DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV] = "1" if dry_run else "0"
    if cycle_limit is not None:
        runtime_env[DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT_ENV] = str(cycle_limit)
    return runtime_env


def _empty_operator_review_service() -> OperatorReviewCaseService:
    return OperatorReviewCaseService(
        OperatorReviewCaseStore(),
        escalation_store=OperatorReviewEscalationStore(),
        dispatch_store=OperatorReviewEscalationDispatchStore(),
    )


def _normalize_cli_action(action: str) -> str:
    normalized = str(action or "plan").replace("-", "_")
    if normalized not in {"plan", "run_once"}:
        raise ValueError(f"Unsupported dispatch daemon CLI action: {action}")
    return normalized


def _heartbeat_active_job_id(plan: Mapping[str, Any]) -> str:
    return f"dispatch-daemon-loop:{plan['request_id']}"


def _default_request_id(action: str, worker_id: str, started_at: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ag-dispatch-execution-daemon-cli:{action}:{worker_id}:{started_at}",
        )
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
