from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import math
import re
import threading
import time
from typing import Any

from .preproduction_workload import WORKLOAD_PROFILE_SCHEMA_VERSION


LOAD_RESULT_SCHEMA_VERSION = "preproduction_load_result.v1"
OUTCOMES = frozenset({"SUCCESS", "ERROR", "TIMEOUT", "DENIED"})
SAFE_REASON = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
SAFE_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class LoadHarnessError(ValueError):
    pass


@dataclass(frozen=True)
class LoadRequest:
    request_id: str
    operation_id: str
    scheduled_offset_seconds: float


@dataclass(frozen=True)
class OperationOutcome:
    status: str
    reason_code: str
    saturation_ratio: float
    side_effect_digest: str | None = None
    isolation_violation: bool = False


OperationRunner = Callable[[LoadRequest], OperationOutcome]


def build_load_plan(
    admitted_profile: Mapping[str, Any],
    *,
    sample_count: int,
) -> tuple[LoadRequest, ...]:
    _validate_admitted_profile(admitted_profile)
    if (
        not isinstance(sample_count, int)
        or isinstance(sample_count, bool)
        or sample_count < 1
        or sample_count > int(admitted_profile["max_generated_records"])
    ):
        raise LoadHarnessError("sample_count is outside the admitted bound")
    operations = tuple(admitted_profile["operations"])
    weighted = _weighted_operation_ids(operations, sample_count)
    target_rps = float(admitted_profile["target_rps"])
    profile_id = str(admitted_profile["profile_id"])
    digest = str(admitted_profile["workload_digest"])
    return tuple(
        LoadRequest(
            request_id=_request_id(profile_id, digest, index),
            operation_id=operation_id,
            scheduled_offset_seconds=index / target_rps,
        )
        for index, operation_id in enumerate(weighted)
    )


def run_bounded_load(
    admitted_profile: Mapping[str, Any],
    requests: Sequence[LoadRequest],
    runner: OperationRunner,
    *,
    paced: bool = False,
) -> dict[str, Any]:
    _validate_admitted_profile(admitted_profile)
    if not requests:
        raise LoadHarnessError("at least one load request is required")
    if len(requests) > int(admitted_profile["max_generated_records"]):
        raise LoadHarnessError("load request count exceeds the admitted bound")
    request_ids = [item.request_id for item in requests]
    if len(request_ids) != len(set(request_ids)):
        raise LoadHarnessError("load request IDs must be unique")
    allowed_operations = {
        str(item["operation_id"]) for item in admitted_profile["operations"]
    }
    if any(item.operation_id not in allowed_operations for item in requests):
        raise LoadHarnessError("load request operation is not admitted")

    started = time.monotonic()
    lock = threading.Lock()
    active = 0
    peak_active = 0

    def execute(request: LoadRequest) -> dict[str, Any]:
        nonlocal active, peak_active
        if paced:
            delay = request.scheduled_offset_seconds - (time.monotonic() - started)
            if delay > 0:
                time.sleep(delay)
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        operation_started = time.monotonic()
        try:
            try:
                outcome = runner(request)
                _validate_outcome(outcome)
            except Exception:  # noqa: BLE001 - workload result must stay redacted
                outcome = OperationOutcome(
                    status="ERROR",
                    reason_code="runner_exception",
                    saturation_ratio=0.0,
                )
            latency_ms = max(0.0, (time.monotonic() - operation_started) * 1_000.0)
            return {
                "request_id": request.request_id,
                "operation_id": request.operation_id,
                "status": outcome.status,
                "reason_code": outcome.reason_code,
                "latency_ms": round(latency_ms, 6),
                "saturation_ratio": outcome.saturation_ratio,
                "side_effect_digest": outcome.side_effect_digest,
                "isolation_violation": outcome.isolation_violation,
            }
        finally:
            with lock:
                active -= 1

    concurrency = int(admitted_profile["concurrency"])
    completed: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(execute, request) for request in requests]
        for future in as_completed(futures):
            completed.append(future.result())
    elapsed = max(time.monotonic() - started, 0.000001)
    completed.sort(key=lambda item: item["request_id"])
    return summarize_load_results(
        admitted_profile,
        completed,
        elapsed_seconds=elapsed,
        peak_active=peak_active,
    )


def summarize_load_results(
    admitted_profile: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    *,
    elapsed_seconds: float,
    peak_active: int,
) -> dict[str, Any]:
    _validate_admitted_profile(admitted_profile)
    if not results:
        raise LoadHarnessError("load results are required")
    if not math.isfinite(elapsed_seconds) or elapsed_seconds <= 0.0:
        raise LoadHarnessError("elapsed_seconds must be positive and finite")
    if not isinstance(peak_active, int) or isinstance(peak_active, bool) or peak_active < 1:
        raise LoadHarnessError("peak_active must be a positive integer")
    normalized = [_normalize_result(item) for item in results]
    request_ids = [item["request_id"] for item in normalized]
    if len(request_ids) != len(set(request_ids)):
        raise LoadHarnessError("result request IDs must be unique")
    success_count = sum(item["status"] == "SUCCESS" for item in normalized)
    error_count = len(normalized) - success_count
    latencies = sorted(float(item["latency_ms"]) for item in normalized)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    side_effects = [
        item["side_effect_digest"]
        for item in normalized
        if item["side_effect_digest"] is not None
    ]
    duplicate_count = len(side_effects) - len(set(side_effects))
    isolation_count = sum(item["isolation_violation"] for item in normalized)
    metrics = {
        "request_count": len(normalized),
        "success_count": success_count,
        "error_count": error_count,
        "error_rate": error_count / len(normalized),
        "p95_latency_ms": latencies[p95_index],
        "throughput_rps": len(normalized) / elapsed_seconds,
        "max_saturation_ratio": max(
            float(item["saturation_ratio"]) for item in normalized
        ),
        "peak_active": peak_active,
        "duplicate_side_effect_count": duplicate_count,
        "isolation_violation_count": isolation_count,
    }
    budget = admitted_profile["budget"]
    checks = {
        "error_rate_within_budget": metrics["error_rate"]
        <= float(budget["max_error_rate"]),
        "p95_latency_within_budget": metrics["p95_latency_ms"]
        <= float(budget["max_p95_latency_ms"]),
        "throughput_within_budget": metrics["throughput_rps"]
        >= float(budget["min_throughput_rps"]),
        "saturation_within_budget": metrics["max_saturation_ratio"]
        <= float(budget["max_saturation_ratio"]),
        "duplicates_within_budget": duplicate_count
        <= int(budget["max_duplicate_side_effects"]),
        "isolation_within_budget": isolation_count
        <= int(budget["max_isolation_violations"]),
        "concurrency_bound_respected": peak_active
        <= int(admitted_profile["concurrency"]),
    }
    passed = all(checks.values())
    return {
        "result_schema_version": LOAD_RESULT_SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "workload_digest": admitted_profile["workload_digest"],
        "workload_class": admitted_profile["workload_class"],
        "checks": checks,
        "failed_checks": sorted(name for name, value in checks.items() if not value),
        "metrics": metrics,
        "outcome_counts": {
            status: sum(item["status"] == status for item in normalized)
            for status in sorted(OUTCOMES)
        },
    }


def _weighted_operation_ids(
    operations: Sequence[Mapping[str, Any]],
    sample_count: int,
) -> list[str]:
    cumulative: list[tuple[float, str]] = []
    running = 0.0
    for operation in operations:
        running += float(operation["weight"])
        cumulative.append((running, str(operation["operation_id"])))
    selected: list[str] = []
    for index in range(sample_count):
        point = (index + 0.5) / sample_count
        selected.append(next(name for boundary, name in cumulative if point <= boundary))
    return selected


def _validate_admitted_profile(profile: Mapping[str, Any]) -> None:
    if (
        profile.get("profile_schema_version") != WORKLOAD_PROFILE_SCHEMA_VERSION
        or profile.get("admission") != "ADMITTED"
        or not SAFE_DIGEST.fullmatch(str(profile.get("workload_digest") or ""))
    ):
        raise LoadHarnessError("an admitted workload profile is required")


def _validate_outcome(outcome: OperationOutcome) -> None:
    if not isinstance(outcome, OperationOutcome):
        raise LoadHarnessError("runner returned an invalid outcome")
    if outcome.status not in OUTCOMES:
        raise LoadHarnessError("runner outcome status is invalid")
    if SAFE_REASON.fullmatch(outcome.reason_code) is None:
        raise LoadHarnessError("runner reason code is invalid")
    if (
        not math.isfinite(outcome.saturation_ratio)
        or not 0.0 <= outcome.saturation_ratio <= 1.0
    ):
        raise LoadHarnessError("runner saturation is invalid")
    if outcome.side_effect_digest is not None and SAFE_DIGEST.fullmatch(
        outcome.side_effect_digest
    ) is None:
        raise LoadHarnessError("runner side-effect digest is invalid")
    if not isinstance(outcome.isolation_violation, bool):
        raise LoadHarnessError("runner isolation flag is invalid")


def _normalize_result(value: Mapping[str, Any]) -> dict[str, Any]:
    request_id = str(value.get("request_id") or "")
    operation_id = str(value.get("operation_id") or "")
    status = str(value.get("status") or "")
    reason_code = str(value.get("reason_code") or "")
    if not request_id or not operation_id or status not in OUTCOMES:
        raise LoadHarnessError("load result identity or status is invalid")
    if SAFE_REASON.fullmatch(reason_code) is None:
        raise LoadHarnessError("load result reason code is invalid")
    latency = value.get("latency_ms")
    saturation = value.get("saturation_ratio")
    if (
        not isinstance(latency, (int, float))
        or isinstance(latency, bool)
        or not math.isfinite(float(latency))
        or float(latency) < 0.0
    ):
        raise LoadHarnessError("load result latency is invalid")
    if (
        not isinstance(saturation, (int, float))
        or isinstance(saturation, bool)
        or not math.isfinite(float(saturation))
        or not 0.0 <= float(saturation) <= 1.0
    ):
        raise LoadHarnessError("load result saturation is invalid")
    digest = value.get("side_effect_digest")
    if digest is not None and SAFE_DIGEST.fullmatch(str(digest)) is None:
        raise LoadHarnessError("load result side-effect digest is invalid")
    isolation = value.get("isolation_violation")
    if not isinstance(isolation, bool):
        raise LoadHarnessError("load result isolation flag is invalid")
    return {
        "request_id": request_id,
        "operation_id": operation_id,
        "status": status,
        "reason_code": reason_code,
        "latency_ms": float(latency),
        "saturation_ratio": float(saturation),
        "side_effect_digest": digest,
        "isolation_violation": isolation,
    }


def _request_id(profile_id: str, workload_digest: str, index: int) -> str:
    value = f"{profile_id}:{workload_digest}:{index}".encode("utf-8")
    return f"load:{hashlib.sha256(value).hexdigest()[:24]}"

