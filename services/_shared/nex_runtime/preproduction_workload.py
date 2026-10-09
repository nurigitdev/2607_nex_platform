from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re


WORKLOAD_PROFILE_SCHEMA_VERSION = "preproduction_workload_profile.v1"
WORKLOAD_CLASSES = frozenset({"baseline", "concurrency", "soak"})
REQUIRED_OPERATIONS = (
    "auth_trust",
    "document_ingestion",
    "hybrid_retrieval",
    "grounded_generation",
    "artifact_access",
    "ag_operations",
    "readiness_probe",
)
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
MAX_CONCURRENCY = 64
MAX_TARGET_RPS = 100.0
MAX_MEASUREMENT_SECONDS = 86_400
MAX_GENERATED_RECORDS = 100_000


class WorkloadProfileError(ValueError):
    pass


@dataclass(frozen=True)
class OperationMix:
    operation_id: str
    weight: float
    timeout_seconds: float


@dataclass(frozen=True)
class WorkloadBudget:
    max_error_rate: float
    max_p95_latency_ms: float
    min_throughput_rps: float
    max_saturation_ratio: float
    max_duplicate_side_effects: int = 0
    max_isolation_violations: int = 0


@dataclass(frozen=True)
class WorkloadProfile:
    profile_id: str
    release_candidate_id: str
    workload_class: str
    concurrency: int
    target_rps: float
    warmup_seconds: int
    measurement_seconds: int
    cooldown_seconds: int
    max_generated_records: int
    operations: tuple[OperationMix, ...]
    budget: WorkloadBudget


def build_default_workload_profiles(
    release_candidate_id: str,
) -> tuple[WorkloadProfile, ...]:
    _safe_id(release_candidate_id, "release_candidate_id")
    operations = tuple(
        OperationMix(operation_id=item, weight=1.0 / 7.0, timeout_seconds=60.0)
        for item in REQUIRED_OPERATIONS
    )
    definitions = (
        ("baseline", 1, 1.0, 5, 30, 5, 500, 0.01, 3_000.0, 0.5, 0.70),
        ("concurrency", 8, 8.0, 10, 120, 10, 5_000, 0.02, 8_000.0, 4.0, 0.85),
        ("soak", 4, 4.0, 30, 1_800, 30, 20_000, 0.02, 8_000.0, 2.0, 0.80),
    )
    return tuple(
        WorkloadProfile(
            profile_id=f"s149.{workload_class}.v1",
            release_candidate_id=release_candidate_id,
            workload_class=workload_class,
            concurrency=concurrency,
            target_rps=target_rps,
            warmup_seconds=warmup,
            measurement_seconds=measurement,
            cooldown_seconds=cooldown,
            max_generated_records=max_records,
            operations=operations,
            budget=WorkloadBudget(
                max_error_rate=max_error,
                max_p95_latency_ms=max_p95,
                min_throughput_rps=min_throughput,
                max_saturation_ratio=max_saturation,
            ),
        )
        for (
            workload_class,
            concurrency,
            target_rps,
            warmup,
            measurement,
            cooldown,
            max_records,
            max_error,
            max_p95,
            min_throughput,
            max_saturation,
        ) in definitions
    )


def admit_workload_profile(
    profile: WorkloadProfile,
    *,
    expected_release_candidate_id: str,
) -> dict[str, object]:
    _safe_id(expected_release_candidate_id, "expected_release_candidate_id")
    _safe_id(profile.profile_id, "profile_id")
    _safe_id(profile.release_candidate_id, "release_candidate_id")
    if profile.release_candidate_id != expected_release_candidate_id:
        raise WorkloadProfileError("release candidate binding mismatch")
    if profile.workload_class not in WORKLOAD_CLASSES:
        raise WorkloadProfileError("unsupported workload class")
    _bounded_integer(profile.concurrency, "concurrency", minimum=1, maximum=MAX_CONCURRENCY)
    _bounded_number(profile.target_rps, "target_rps", minimum=0.01, maximum=MAX_TARGET_RPS)
    _bounded_integer(profile.warmup_seconds, "warmup_seconds", minimum=0, maximum=3_600)
    _bounded_integer(
        profile.measurement_seconds,
        "measurement_seconds",
        minimum=1,
        maximum=MAX_MEASUREMENT_SECONDS,
    )
    _bounded_integer(profile.cooldown_seconds, "cooldown_seconds", minimum=0, maximum=3_600)
    _bounded_integer(
        profile.max_generated_records,
        "max_generated_records",
        minimum=1,
        maximum=MAX_GENERATED_RECORDS,
    )
    _validate_operations(profile.operations)
    _validate_budget(profile.budget)
    payload = {
        "profile_schema_version": WORKLOAD_PROFILE_SCHEMA_VERSION,
        **asdict(profile),
    }
    digest = _digest(payload)
    return {
        **payload,
        "workload_digest": digest,
        "admission": "ADMITTED",
        "production_capacity_claimed": False,
    }


def _validate_operations(operations: tuple[OperationMix, ...]) -> None:
    if not operations:
        raise WorkloadProfileError("operation mix is required")
    operation_ids = [item.operation_id for item in operations]
    if len(operation_ids) != len(set(operation_ids)):
        raise WorkloadProfileError("operation IDs must be unique")
    if set(operation_ids) != set(REQUIRED_OPERATIONS):
        raise WorkloadProfileError("operation mix must contain every required operation")
    for operation in operations:
        _safe_id(operation.operation_id, "operation_id")
        _bounded_number(operation.weight, "operation weight", minimum=0.000001, maximum=1.0)
        _bounded_number(
            operation.timeout_seconds,
            "operation timeout",
            minimum=0.1,
            maximum=300.0,
        )
    if not math.isclose(sum(item.weight for item in operations), 1.0, abs_tol=1e-6):
        raise WorkloadProfileError("operation weights must sum to one")


def _validate_budget(budget: WorkloadBudget) -> None:
    _bounded_number(budget.max_error_rate, "max_error_rate", minimum=0.0, maximum=1.0)
    _bounded_number(
        budget.max_p95_latency_ms,
        "max_p95_latency_ms",
        minimum=1.0,
        maximum=600_000.0,
    )
    _bounded_number(
        budget.min_throughput_rps,
        "min_throughput_rps",
        minimum=0.0,
        maximum=MAX_TARGET_RPS,
    )
    _bounded_number(
        budget.max_saturation_ratio,
        "max_saturation_ratio",
        minimum=0.0,
        maximum=1.0,
    )
    _bounded_integer(
        budget.max_duplicate_side_effects,
        "max_duplicate_side_effects",
        minimum=0,
        maximum=1_000,
    )
    _bounded_integer(
        budget.max_isolation_violations,
        "max_isolation_violations",
        minimum=0,
        maximum=0,
    )


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or SAFE_ID.fullmatch(value) is None:
        raise WorkloadProfileError(f"{field} is invalid")
    return value


def _bounded_integer(value: object, field: str, *, minimum: int, maximum: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > maximum
    ):
        raise WorkloadProfileError(f"{field} is outside the allowed range")
    return value


def _bounded_number(
    value: object,
    field: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < minimum
        or float(value) > maximum
    ):
        raise WorkloadProfileError(f"{field} is outside the allowed range")
    return float(value)


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

