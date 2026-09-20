from __future__ import annotations

import base64
import binascii
import json
import os
import threading
from collections.abc import Mapping, Sequence
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


@dataclass
class AgStablePaginationError(ValueError):
    error_code: str
    detail: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.detail


@dataclass
class AgAdmissionRejectedError(RuntimeError):
    error_code: str
    detail: str
    retry_after_ms: int
    status_code: int = 503

    def __str__(self) -> str:
        return self.detail


class AgConcurrencyAdmissionGuard:
    def __init__(self, *, max_in_flight: int, wait_timeout_ms: int) -> None:
        if isinstance(max_in_flight, bool) or max_in_flight < 1:
            raise ValueError("max_in_flight must be greater than 0")
        if isinstance(wait_timeout_ms, bool) or wait_timeout_ms < 1:
            raise ValueError("wait_timeout_ms must be greater than 0")
        self.max_in_flight = max_in_flight
        self.wait_timeout_ms = wait_timeout_ms
        self._semaphore = threading.BoundedSemaphore(max_in_flight)
        self._metrics_lock = threading.Lock()
        self._in_flight = 0
        self._peak_in_flight = 0
        self._admitted_total = 0
        self._rejected_total = 0

    def admit(self, operation: str) -> _AgAdmissionLease:
        if not isinstance(operation, str) or not operation.strip():
            raise ValueError("operation must be a non-empty string")
        return _AgAdmissionLease(self)

    def _acquire(self) -> None:
        acquired = self._semaphore.acquire(
            timeout=self.wait_timeout_ms / 1000.0
        )
        if not acquired:
            with self._metrics_lock:
                self._rejected_total += 1
            raise AgAdmissionRejectedError(
                error_code="ag.resilience.admission_capacity_exhausted",
                detail="AG operation capacity is temporarily exhausted; retry later.",
                retry_after_ms=self.wait_timeout_ms,
            )
        with self._metrics_lock:
            self._in_flight += 1
            self._admitted_total += 1
            self._peak_in_flight = max(
                self._peak_in_flight,
                self._in_flight,
            )

    def _release(self) -> None:
        with self._metrics_lock:
            self._in_flight -= 1
        self._semaphore.release()

    def snapshot(self) -> dict[str, Any]:
        with self._metrics_lock:
            return {
                "schema_version": "ag_concurrency_admission_snapshot.v1",
                "max_in_flight": self.max_in_flight,
                "wait_timeout_ms": self.wait_timeout_ms,
                "in_flight": self._in_flight,
                "peak_in_flight": self._peak_in_flight,
                "admitted_total": self._admitted_total,
                "rejected_total": self._rejected_total,
                "process_local": True,
            }


class _AgAdmissionLease:
    def __init__(self, guard: AgConcurrencyAdmissionGuard) -> None:
        self._guard = guard

    def __enter__(self) -> None:
        self._guard._acquire()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self._guard._release()
        return False


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


def build_ag_concurrency_admission_guard(
    environ: Mapping[str, str] | None = None,
) -> AgConcurrencyAdmissionGuard:
    policy = build_ag_resilience_performance_policy(environ)
    admission = policy["admission"]
    return AgConcurrencyAdmissionGuard(
        max_in_flight=admission["max_in_flight"],
        wait_timeout_ms=admission["wait_timeout_ms"],
    )


def build_stable_keyset_page(
    records: Sequence[Mapping[str, Any]],
    *,
    limit: int,
    cursor: str | None,
    timestamp_field: str,
    identity_field: str,
    sort: str = "desc",
    max_limit: int = HARD_MAX_PAGE_SIZE,
) -> dict[str, Any]:
    normalized_limit = _page_limit(limit, max_limit=max_limit)
    normalized_sort = sort.strip().lower() if isinstance(sort, str) else ""
    if normalized_sort not in {"asc", "desc"}:
        raise AgStablePaginationError(
            error_code="ag.resilience.pagination_sort_invalid",
            detail="Pagination sort must be asc or desc.",
        )
    anchor = _decode_cursor(cursor, expected_sort=normalized_sort)
    keyed_records: list[tuple[tuple[str, str], Mapping[str, Any]]] = []
    invalid_record_count = 0
    for record in records:
        key = _record_key(
            record,
            timestamp_field=timestamp_field,
            identity_field=identity_field,
        )
        if key is None:
            invalid_record_count += 1
            continue
        if anchor is not None:
            is_after = key > anchor if normalized_sort == "asc" else key < anchor
            if not is_after:
                continue
        keyed_records.append((key, record))
    keyed_records.sort(
        key=lambda item: item[0],
        reverse=normalized_sort == "desc",
    )
    selected = keyed_records[: normalized_limit + 1]
    has_more = len(selected) > normalized_limit
    page_records = selected[:normalized_limit]
    next_cursor = None
    if has_more and page_records:
        next_cursor = _encode_cursor(page_records[-1][0], sort=normalized_sort)
    return {
        "items": [dict(item[1]) for item in page_records],
        "pagination": {
            "limit": normalized_limit,
            "returned": len(page_records),
            "has_more": has_more,
            "next_cursor": next_cursor,
            "sort": normalized_sort,
            "stable_ordering": [timestamp_field, identity_field],
            "invalid_record_count": invalid_record_count,
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


def _page_limit(value: int, *, max_limit: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AgStablePaginationError(
            error_code="ag.resilience.pagination_limit_invalid",
            detail="Pagination limit must be an integer.",
        )
    if max_limit < 1 or value < 1 or value > max_limit:
        raise AgStablePaginationError(
            error_code="ag.resilience.pagination_limit_invalid",
            detail=f"Pagination limit must be between 1 and {max_limit}.",
        )
    return value


def _record_key(
    record: Mapping[str, Any],
    *,
    timestamp_field: str,
    identity_field: str,
) -> tuple[str, str] | None:
    timestamp = record.get(timestamp_field)
    identity = record.get(identity_field)
    if not isinstance(timestamp, str) or not timestamp.strip():
        return None
    if not isinstance(identity, str) or not identity.strip():
        return None
    return timestamp.strip(), identity.strip()


def _encode_cursor(key: tuple[str, str], *, sort: str) -> str:
    payload = json.dumps(
        {
            "identity": key[1],
            "sort": sort,
            "timestamp": key[0],
            "version": 1,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(
    value: str | None,
    *,
    expected_sort: str,
) -> tuple[str, str] | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    if len(normalized) > 1024:
        raise _cursor_error()
    padding = "=" * (-len(normalized) % 4)
    try:
        decoded = base64.b64decode(
            normalized + padding,
            altchars=b"-_",
            validate=True,
        ).decode("utf-8")
        payload = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _cursor_error() from exc
    if not isinstance(payload, Mapping) or set(payload) != {
        "identity",
        "sort",
        "timestamp",
        "version",
    }:
        raise _cursor_error()
    if payload.get("version") != 1 or payload.get("sort") != expected_sort:
        raise _cursor_error()
    timestamp = payload.get("timestamp")
    identity = payload.get("identity")
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise _cursor_error()
    if not isinstance(identity, str) or not identity.strip():
        raise _cursor_error()
    return timestamp.strip(), identity.strip()


def _cursor_error() -> AgStablePaginationError:
    return AgStablePaginationError(
        error_code="ag.resilience.pagination_cursor_invalid",
        detail="Pagination cursor is invalid or incompatible.",
    )
