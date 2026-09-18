from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Sequence, TextIO
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import (
    DatabaseConfigError,
    build_engine,
    build_session_factory,
    database_pool_settings,
    required_database_url,
)

from .liveness_ack_expiry_automation import (
    build_liveness_ack_expiry_automation_policy,
    build_liveness_ack_expiry_automation_tick_plan,
    run_liveness_ack_expiry_automation_tick_once,
)
from .operator_review_liveness_ack import (
    OperatorReviewLivenessAckStateStore,
    SqlAlchemyOperatorReviewLivenessAckStateStore,
)


ACK_EXPIRY_AUTOMATION_CLI_RESULT_SCHEMA_VERSION = (
    "ag_ack_expiry_automation_cli_result.v1"
)
ACK_EXPIRY_AUTOMATION_DATABASE_ENV = "NEX_AG_DATABASE_URL"
ACK_EXPIRY_AUTOMATION_TEST_DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
ACK_EXPIRY_AUTOMATION_DATABASE_ENVS = (
    ACK_EXPIRY_AUTOMATION_DATABASE_ENV,
    ACK_EXPIRY_AUTOMATION_TEST_DATABASE_ENV,
)
ACK_EXPIRY_AUTOMATION_SERVICE_ID = "nex-ag"


def execute_liveness_ack_expiry_automation_cli(
    state_store: Any,
    *,
    action: str = "plan",
    environ: Mapping[str, str] | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    confirm_tick: bool = False,
    observed_at: object | None = None,
) -> dict[str, Any]:
    normalized_action = _normalize_action(action)
    env = os.environ if environ is None else environ
    policy = build_liveness_ack_expiry_automation_policy(env)
    resolved_observed_at = observed_at if observed_at is not None else _utc_now()
    resolved_request_id = request_id or _default_request_id(
        normalized_action,
        str(resolved_observed_at),
    )
    tick_result = None
    if normalized_action == "run_once":
        tick_result = run_liveness_ack_expiry_automation_tick_once(
            state_store,
            request_id=resolved_request_id,
            trace_id=trace_id,
            policy=policy,
            confirm_tick=confirm_tick,
            executed_at=resolved_observed_at,
        )
        plan = tick_result["plan"]
        result_status = (
            "BLOCKED" if tick_result["tick_status"] == "BLOCKED" else "EXECUTED"
        )
    else:
        plan = build_liveness_ack_expiry_automation_tick_plan(
            state_store,
            request_id=resolved_request_id,
            trace_id=trace_id,
            policy=policy,
            planned_at=resolved_observed_at,
        )
        result_status = "PLANNED"
    return {
        "automation_cli_result_schema_version": (
            ACK_EXPIRY_AUTOMATION_CLI_RESULT_SCHEMA_VERSION
        ),
        "result_status": result_status,
        "action": normalized_action,
        "request_id": resolved_request_id,
        "trace_id": trace_id,
        "confirm_tick": bool(confirm_tick),
        "database_bound": isinstance(
            state_store,
            SqlAlchemyOperatorReviewLivenessAckStateStore,
        ),
        "plan": plan,
        "tick_result": tick_result,
        "new_tables_required": False,
        "redaction": policy["redaction"],
    }


def build_liveness_ack_expiry_automation_runtime_store(
    *,
    database_env: str = ACK_EXPIRY_AUTOMATION_DATABASE_ENV,
    environ: Mapping[str, str] | None = None,
    engine_factory: Callable[..., Any] = build_engine,
    session_factory_builder: Callable[[Any], Any] = build_session_factory,
) -> tuple[SqlAlchemyOperatorReviewLivenessAckStateStore, Any]:
    if database_env not in ACK_EXPIRY_AUTOMATION_DATABASE_ENVS:
        raise DatabaseConfigError(
            f"unsupported acknowledgement expiry automation database env: {database_env}"
        )
    env = os.environ if environ is None else environ
    database_url = required_database_url(database_env, env)
    engine = engine_factory(
        database_url,
        pool_settings=database_pool_settings(
            ACK_EXPIRY_AUTOMATION_SERVICE_ID,
            workload="worker",
            environ=env,
        ),
    )
    return (
        SqlAlchemyOperatorReviewLivenessAckStateStore(
            session_factory_builder(engine)
        ),
        engine,
    )


def summary_line(result: Mapping[str, Any]) -> str:
    plan = result.get("plan") if isinstance(result.get("plan"), Mapping) else {}
    tick = (
        result.get("tick_result")
        if isinstance(result.get("tick_result"), Mapping)
        else {}
    )
    return (
        "ag_ack_expiry_automation_cli="
        f"{str(result.get('result_status') or 'UNKNOWN').lower()} "
        f"action={result.get('action')} "
        f"plan={plan.get('plan_status', 'UNKNOWN')} "
        f"tick={tick.get('tick_status', 'NONE')} "
        f"candidates={plan.get('candidate_count', 0)} "
        f"applied={tick.get('applied_count', 0)} "
        f"conflicts={tick.get('conflict_count', 0)} "
        f"database_bound={result.get('database_bound')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or run one AG acknowledgement expiry automation tick."
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--plan", action="store_true", help="Print a read-only plan.")
    action.add_argument(
        "--run-once",
        action="store_true",
        help="Run one bounded acknowledgement expiry reconciliation tick.",
    )
    parser.add_argument("--confirm-tick", action="store_true")
    parser.add_argument("--request-id")
    parser.add_argument("--trace-id")
    parser.add_argument("--observed-at")
    parser.add_argument(
        "--database-env",
        choices=ACK_EXPIRY_AUTOMATION_DATABASE_ENVS,
        default=ACK_EXPIRY_AUTOMATION_DATABASE_ENV,
    )
    parser.add_argument("--summary", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    stdout: TextIO | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    env = os.environ if environ is None else environ
    policy = build_liveness_ack_expiry_automation_policy(env)
    engine = None
    try:
        if policy["enabled"]:
            store, engine = build_liveness_ack_expiry_automation_runtime_store(
                database_env=args.database_env,
                environ=env,
            )
        else:
            store = OperatorReviewLivenessAckStateStore()
        result = execute_liveness_ack_expiry_automation_cli(
            store,
            action="run_once" if args.run_once else "plan",
            environ=env,
            request_id=args.request_id,
            trace_id=args.trace_id,
            confirm_tick=args.confirm_tick,
            observed_at=args.observed_at,
        )
    except DatabaseConfigError as exc:
        failure = {
            "automation_cli_result_schema_version": (
                ACK_EXPIRY_AUTOMATION_CLI_RESULT_SCHEMA_VERSION
            ),
            "result_status": "FAILED",
            "error_code": "database_configuration_invalid",
            "detail": str(exc),
            "database_env": args.database_env,
            "database_url_included": False,
        }
        print(json.dumps(failure), file=stdout)
        return 2
    finally:
        if engine is not None:
            engine.dispose()
    output = summary_line(result) if args.summary else json.dumps(result, default=str)
    print(output, file=stdout)
    return 0


def _normalize_action(action: str) -> str:
    normalized = str(action or "plan").replace("-", "_")
    if normalized not in {"plan", "run_once"}:
        raise ValueError(f"Unsupported acknowledgement expiry CLI action: {action}")
    return normalized


def _default_request_id(action: str, observed_at: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"nex-ag:ack-expiry-automation-cli:{action}:{observed_at}",
        )
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
