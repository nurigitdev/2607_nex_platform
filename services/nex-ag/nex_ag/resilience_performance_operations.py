from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


AG_RESILIENCE_PERFORMANCE_OPERATIONS_PATH = (
    "/admin/v1/operations/resilience-performance"
)
AG_RESILIENCE_PERFORMANCE_OPERATIONS_SCHEMA_VERSION = (
    "ag_resilience_performance_operations_projection.v1"
)


def build_ag_resilience_performance_operations_projection(
    *,
    policy: Mapping[str, Any],
    admission_snapshot: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    api_engine: Any | None = None,
    worker_engine: Any | None = None,
    request_trace_id: str | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    database_policy = policy["database"]
    database_pools = {
        "api": _pool_snapshot(
            api_engine,
            configured=database_policy["api"],
        ),
        "worker": _pool_snapshot(
            worker_engine,
            configured=database_policy["worker"],
        ),
    }
    attention_reasons = _attention_reasons(
        admission_snapshot=admission_snapshot,
        source_snapshot=source_snapshot,
        database_pools=database_pools,
    )
    projection_status = _projection_status(
        database_pools=database_pools,
        attention_reasons=attention_reasons,
    )
    return {
        "projection_schema_version": (
            AG_RESILIENCE_PERFORMANCE_OPERATIONS_SCHEMA_VERSION
        ),
        "projection_status": projection_status,
        "service_id": "nex-ag",
        "policy_id": policy["policy_id"],
        "checked_at": checked_at or _utc_now(),
        "request_trace_id": request_trace_id,
        "performance_budget": {
            "query": dict(policy["query"]),
            "admission": dict(policy["admission"]),
            "source_isolation": dict(policy["source_isolation"]),
            "bounded_smoke": dict(policy["bounded_smoke"]),
        },
        "runtime": {
            "admission": dict(admission_snapshot),
            "source_isolation": dict(source_snapshot),
            "database_pools": database_pools,
        },
        "attention_reasons": attention_reasons,
        "privacy": {
            "database_url_included": False,
            "credentials_included": False,
            "sql_included": False,
            "raw_errors_included": False,
        },
    }


def _pool_snapshot(
    engine: Any | None,
    *,
    configured: Mapping[str, Any],
) -> dict[str, Any]:
    base = {
        "workload": configured["workload"],
        "configured_pool_size": configured["pool_size"],
        "configured_max_overflow": configured["max_overflow"],
        "configured_capacity": configured["capacity"],
        "checked_out": None,
        "checked_in": None,
        "overflow_in_use": None,
        "available_capacity": None,
        "utilization_percent": None,
    }
    if engine is None:
        return {"status": "NOT_CONFIGURED", **base}
    try:
        pool = engine.pool
        checked_out = _non_negative_metric(pool.checkedout())
        checked_in = _non_negative_metric(pool.checkedin())
        overflow_in_use = max(0, _integer_metric(pool.overflow()))
        capacity = _positive_metric(configured["capacity"])
    except Exception:
        return {"status": "UNAVAILABLE", **base}

    available_capacity = max(0, capacity - checked_out)
    status = "ATTENTION" if available_capacity == 0 else "READY"
    return {
        "status": status,
        **base,
        "checked_out": checked_out,
        "checked_in": checked_in,
        "overflow_in_use": overflow_in_use,
        "available_capacity": available_capacity,
        "utilization_percent": round(checked_out * 100 / capacity, 2),
    }


def _attention_reasons(
    *,
    admission_snapshot: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    database_pools: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    for workload, snapshot in database_pools.items():
        if snapshot["status"] == "ATTENTION":
            reasons.append(f"DATABASE_{workload.upper()}_POOL_SATURATED")
        elif snapshot["status"] == "UNAVAILABLE":
            reasons.append(f"DATABASE_{workload.upper()}_POOL_METRICS_UNAVAILABLE")
    if admission_snapshot.get("rejected_total", 0) > 0:
        reasons.append("ADMISSION_REJECTIONS")
    if source_snapshot.get("timed_out_total", 0) > 0:
        reasons.append("SOURCE_TIMEOUTS")
    if source_snapshot.get("failed_total", 0) > 0:
        reasons.append("SOURCE_FAILURES")
    if source_snapshot.get("slow_total", 0) > 0:
        reasons.append("SOURCE_SLOW_OPERATIONS")
    return reasons


def _projection_status(
    *,
    database_pools: Mapping[str, Mapping[str, Any]],
    attention_reasons: list[str],
) -> str:
    statuses = {snapshot["status"] for snapshot in database_pools.values()}
    if "UNAVAILABLE" in statuses:
        return "DEGRADED"
    if attention_reasons or len(statuses) > 1:
        return "ATTENTION"
    if statuses == {"NOT_CONFIGURED"}:
        return "NOT_CONFIGURED"
    return "READY"


def _integer_metric(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("pool metric must be an integer")
    return value


def _non_negative_metric(value: object) -> int:
    metric = _integer_metric(value)
    if metric < 0:
        raise ValueError("pool metric cannot be negative")
    return metric


def _positive_metric(value: object) -> int:
    metric = _integer_metric(value)
    if metric < 1:
        raise ValueError("pool capacity must be positive")
    return metric


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "AG_RESILIENCE_PERFORMANCE_OPERATIONS_PATH",
    "AG_RESILIENCE_PERFORMANCE_OPERATIONS_SCHEMA_VERSION",
    "build_ag_resilience_performance_operations_projection",
]
