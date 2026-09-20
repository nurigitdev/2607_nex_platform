from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from nex_runtime import DatabaseConfigError, database_pool_settings


AG_RESILIENCE_PERFORMANCE_POLICY_SCHEMA_VERSION = (
    "ag_resilience_performance_policy.v1"
)
AG_RESILIENCE_PERFORMANCE_POLICY_ID = "ag-resilience-performance-v1"
HARD_MAX_PAGE_SIZE = 500


@dataclass
class AgResiliencePerformancePolicyError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_ag_resilience_performance_policy(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    try:
        api_pool = database_pool_settings("nex-ag", workload="api", environ=env)
        worker_pool = database_pool_settings(
            "nex-ag", workload="worker", environ=env
        )
    except DatabaseConfigError as exc:
        raise AgResiliencePerformancePolicyError(
            error_code="ag.resilience.pool_config_invalid",
            detail=str(exc),
        ) from exc

    api_capacity = api_pool.pool_size + api_pool.max_overflow
    default_max_in_flight = min(8, api_capacity)
    max_in_flight = _positive_int_env(
        env, "NEX_AG_PERF_MAX_IN_FLIGHT", default_max_in_flight
    )
    default_smoke_concurrency = min(4, max_in_flight)
    values = {
        "default_page_size": _positive_int_env(
            env, "NEX_AG_PERF_DEFAULT_PAGE_SIZE", 50
        ),
        "max_page_size": _positive_int_env(
            env, "NEX_AG_PERF_MAX_PAGE_SIZE", HARD_MAX_PAGE_SIZE
        ),
        "max_in_flight": max_in_flight,
        "admission_wait_ms": _positive_int_env(
            env, "NEX_AG_PERF_ADMISSION_WAIT_MS", 100
        ),
        "source_timeout_ms": _positive_int_env(
            env, "NEX_AG_PERF_SOURCE_TIMEOUT_MS", 2000
        ),
        "slow_operation_ms": _positive_int_env(
            env, "NEX_AG_PERF_SLOW_OPERATION_MS", 1000
        ),
        "smoke_request_count": _positive_int_env(
            env, "NEX_AG_PERF_SMOKE_REQUEST_COUNT", 25
        ),
        "smoke_concurrency": _positive_int_env(
            env,
            "NEX_AG_PERF_SMOKE_CONCURRENCY",
            default_smoke_concurrency,
        ),
        "smoke_p95_budget_ms": _positive_int_env(
            env, "NEX_AG_PERF_SMOKE_P95_BUDGET_MS", 1500
        ),
    }
    _validate_policy_relationships(
        values,
        api_capacity=api_capacity,
        api_statement_timeout_ms=api_pool.statement_timeout_ms,
    )
    return {
        "policy_schema_version": (
            AG_RESILIENCE_PERFORMANCE_POLICY_SCHEMA_VERSION
        ),
        "policy_id": AG_RESILIENCE_PERFORMANCE_POLICY_ID,
        "service_id": "nex-ag",
        "query": {
            "default_page_size": values["default_page_size"],
            "max_page_size": values["max_page_size"],
            "hard_max_page_size": HARD_MAX_PAGE_SIZE,
            "stable_ordering_required": True,
            "slow_operation_ms": values["slow_operation_ms"],
        },
        "admission": {
            "max_in_flight": values["max_in_flight"],
            "wait_timeout_ms": values["admission_wait_ms"],
            "overflow_action": "reject_retryable_503",
        },
        "source_isolation": {
            "timeout_ms": values["source_timeout_ms"],
            "failure_action": "degraded_partial_projection",
            "raw_error_exposure": False,
        },
        "database": {
            "api": _pool_projection(api_pool),
            "worker": _pool_projection(worker_pool),
        },
        "bounded_smoke": {
            "request_count": values["smoke_request_count"],
            "concurrency": values["smoke_concurrency"],
            "p95_budget_ms": values["smoke_p95_budget_ms"],
            "destructive": False,
        },
    }


def _validate_policy_relationships(
    values: Mapping[str, int],
    *,
    api_capacity: int,
    api_statement_timeout_ms: int,
) -> None:
    if values["default_page_size"] > values["max_page_size"]:
        raise _policy_error(
            "page_size_order_invalid",
            "Default page size cannot exceed maximum page size.",
        )
    if values["max_page_size"] > HARD_MAX_PAGE_SIZE:
        raise _policy_error(
            "page_size_cap_exceeded",
            f"Maximum page size cannot exceed {HARD_MAX_PAGE_SIZE}.",
        )
    if values["max_in_flight"] > api_capacity:
        raise _policy_error(
            "admission_exceeds_pool_capacity",
            "Maximum in-flight work cannot exceed API pool capacity.",
        )
    if values["smoke_concurrency"] > values["max_in_flight"]:
        raise _policy_error(
            "smoke_concurrency_exceeds_admission",
            "Smoke concurrency cannot exceed admission capacity.",
        )
    if values["smoke_request_count"] < values["smoke_concurrency"]:
        raise _policy_error(
            "smoke_request_count_too_small",
            "Smoke request count cannot be smaller than smoke concurrency.",
        )
    if values["slow_operation_ms"] > values["source_timeout_ms"]:
        raise _policy_error(
            "slow_threshold_exceeds_timeout",
            "Slow-operation threshold cannot exceed source timeout.",
        )
    if (
        api_statement_timeout_ms > 0
        and values["source_timeout_ms"] >= api_statement_timeout_ms
    ):
        raise _policy_error(
            "source_timeout_exceeds_statement_timeout",
            "Source timeout must be lower than the API statement timeout.",
        )


def _pool_projection(settings: Any) -> dict[str, Any]:
    return {
        "workload": settings.workload,
        "pool_size": settings.pool_size,
        "max_overflow": settings.max_overflow,
        "capacity": settings.pool_size + settings.max_overflow,
        "pool_timeout_seconds": settings.pool_timeout_seconds,
        "pool_recycle_seconds": settings.pool_recycle_seconds,
        "pool_pre_ping": settings.pool_pre_ping,
        "statement_timeout_ms": settings.statement_timeout_ms,
    }


def _positive_int_env(
    env: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw_value = env.get(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise AgResiliencePerformancePolicyError(
            error_code="ag.resilience.performance_value_invalid",
            detail=f"{name} must be an integer.",
        ) from exc
    if value < 1:
        raise AgResiliencePerformancePolicyError(
            error_code="ag.resilience.performance_value_invalid",
            detail=f"{name} must be greater than 0.",
        )
    return value


def _policy_error(suffix: str, detail: str) -> AgResiliencePerformancePolicyError:
    return AgResiliencePerformancePolicyError(
        error_code=f"ag.resilience.{suffix}",
        detail=detail,
    )
