from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import math
from typing import Any

from .preproduction_workload import WORKLOAD_PROFILE_SCHEMA_VERSION


SOAK_EVALUATION_SCHEMA_VERSION = "preproduction_soak_evaluation.v1"


class SoakEvaluationError(ValueError):
    pass


@dataclass(frozen=True)
class SoakPolicy:
    minimum_window_count: int = 3
    maximum_memory_growth_ratio: float = 0.10
    maximum_connection_growth: int = 2
    maximum_queue_age_growth_ms: float = 250.0
    maximum_tail_error_rate_delta: float = 0.005
    maximum_tail_p95_growth_ratio: float = 0.20


@dataclass(frozen=True)
class SoakWindow:
    window_id: str
    sequence: int
    duration_seconds: float
    request_count: int
    error_rate: float
    p95_latency_ms: float
    throughput_rps: float
    saturation_ratio: float
    process_memory_bytes: int
    open_connection_count: int
    queue_age_ms: float
    duplicate_side_effect_count: int = 0
    isolation_violation_count: int = 0


def evaluate_soak_windows(
    admitted_profile: Mapping[str, Any],
    windows: Sequence[SoakWindow],
    *,
    policy: SoakPolicy = SoakPolicy(),
) -> dict[str, Any]:
    _validate_profile(admitted_profile)
    _validate_policy(policy)
    if len(windows) < policy.minimum_window_count:
        raise SoakEvaluationError("insufficient soak windows")
    ordered = sorted(windows, key=lambda item: item.sequence)
    if [item.sequence for item in ordered] != list(range(len(ordered))):
        raise SoakEvaluationError("soak window sequence must be contiguous from zero")
    if len({item.window_id for item in ordered}) != len(ordered):
        raise SoakEvaluationError("soak window IDs must be unique")
    for item in ordered:
        _validate_window(item)

    budget = admitted_profile["budget"]
    first = ordered[0]
    last = ordered[-1]
    tail_previous = ordered[-2]
    duration = sum(item.duration_seconds for item in ordered)
    memory_growth_ratio = (
        (last.process_memory_bytes - first.process_memory_bytes)
        / first.process_memory_bytes
    )
    connection_growth = last.open_connection_count - first.open_connection_count
    queue_age_growth = last.queue_age_ms - first.queue_age_ms
    tail_error_delta = last.error_rate - tail_previous.error_rate
    tail_p95_growth_ratio = (
        (last.p95_latency_ms - tail_previous.p95_latency_ms)
        / max(tail_previous.p95_latency_ms, 1.0)
    )
    metrics = {
        "window_count": len(ordered),
        "duration_seconds": duration,
        "request_count": sum(item.request_count for item in ordered),
        "maximum_error_rate": max(item.error_rate for item in ordered),
        "maximum_p95_latency_ms": max(item.p95_latency_ms for item in ordered),
        "minimum_throughput_rps": min(item.throughput_rps for item in ordered),
        "maximum_saturation_ratio": max(item.saturation_ratio for item in ordered),
        "memory_growth_ratio": memory_growth_ratio,
        "connection_growth": connection_growth,
        "queue_age_growth_ms": queue_age_growth,
        "tail_error_rate_delta": tail_error_delta,
        "tail_p95_growth_ratio": tail_p95_growth_ratio,
        "duplicate_side_effect_count": sum(
            item.duplicate_side_effect_count for item in ordered
        ),
        "isolation_violation_count": sum(
            item.isolation_violation_count for item in ordered
        ),
    }
    checks = {
        "measurement_duration_satisfied": duration
        >= float(admitted_profile["measurement_seconds"]),
        "every_window_has_samples": all(item.request_count > 0 for item in ordered),
        "error_rate_within_budget": metrics["maximum_error_rate"]
        <= float(budget["max_error_rate"]),
        "p95_latency_within_budget": metrics["maximum_p95_latency_ms"]
        <= float(budget["max_p95_latency_ms"]),
        "throughput_within_budget": metrics["minimum_throughput_rps"]
        >= float(budget["min_throughput_rps"]),
        "saturation_within_budget": metrics["maximum_saturation_ratio"]
        <= float(budget["max_saturation_ratio"]),
        "memory_trend_stable": memory_growth_ratio
        <= policy.maximum_memory_growth_ratio,
        "connection_trend_stable": connection_growth
        <= policy.maximum_connection_growth,
        "queue_age_trend_stable": queue_age_growth
        <= policy.maximum_queue_age_growth_ms,
        "tail_error_stable": tail_error_delta
        <= policy.maximum_tail_error_rate_delta,
        "tail_latency_stable": tail_p95_growth_ratio
        <= policy.maximum_tail_p95_growth_ratio,
        "duplicates_within_budget": metrics["duplicate_side_effect_count"]
        <= int(budget["max_duplicate_side_effects"]),
        "isolation_within_budget": metrics["isolation_violation_count"]
        <= int(budget["max_isolation_violations"]),
    }
    passed = all(checks.values())
    return {
        "evaluation_schema_version": SOAK_EVALUATION_SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "workload_digest": admitted_profile["workload_digest"],
        "policy": asdict(policy),
        "checks": checks,
        "failed_checks": sorted(name for name, value in checks.items() if not value),
        "metrics": metrics,
    }


def _validate_profile(profile: Mapping[str, Any]) -> None:
    if (
        profile.get("profile_schema_version") != WORKLOAD_PROFILE_SCHEMA_VERSION
        or profile.get("admission") != "ADMITTED"
        or profile.get("workload_class") != "soak"
    ):
        raise SoakEvaluationError("an admitted soak workload profile is required")


def _validate_policy(policy: SoakPolicy) -> None:
    values = asdict(policy)
    if (
        not isinstance(policy.minimum_window_count, int)
        or isinstance(policy.minimum_window_count, bool)
        or policy.minimum_window_count < 2
    ):
        raise SoakEvaluationError("minimum_window_count must be at least two")
    for name, value in values.items():
        if name == "minimum_window_count":
            continue
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or float(value) < 0.0
        ):
            raise SoakEvaluationError(f"{name} must be finite and non-negative")


def _validate_window(window: SoakWindow) -> None:
    if not isinstance(window.window_id, str) or not window.window_id:
        raise SoakEvaluationError("window_id is required")
    integer_values = (
        window.sequence,
        window.request_count,
        window.process_memory_bytes,
        window.open_connection_count,
        window.duplicate_side_effect_count,
        window.isolation_violation_count,
    )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in integer_values
    ):
        raise SoakEvaluationError("window integer measurements must be non-negative")
    numeric_values = (
        window.duration_seconds,
        window.error_rate,
        window.p95_latency_ms,
        window.throughput_rps,
        window.saturation_ratio,
        window.queue_age_ms,
    )
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0.0
        for value in numeric_values
    ):
        raise SoakEvaluationError("window numeric measurements must be finite and non-negative")
    if window.duration_seconds <= 0.0 or window.process_memory_bytes <= 0:
        raise SoakEvaluationError("window duration and memory must be positive")
    if window.error_rate > 1.0 or window.saturation_ratio > 1.0:
        raise SoakEvaluationError("window ratios must not exceed one")

