from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
import hashlib

from .preproduction_load import LoadRequest
from .preproduction_workload import (
    OperationMix,
    WorkloadBudget,
    WorkloadProfile,
    WorkloadProfileError,
    build_default_workload_profiles,
)


PROTECTED_LIVE_PROFILE_ID = "s149.protected-live-soak.v1"
PROTECTED_LIVE_REQUEST_COUNT = 7_200
PROTECTED_LIVE_OPERATION_COUNTS: dict[str, int] = {
    "readiness_probe": 2_400,
    "auth_trust": 1_440,
    "ag_operations": 1_440,
    "document_ingestion": 720,
    "artifact_access": 720,
    "hybrid_retrieval": 450,
    "grounded_generation": 30,
}
PROTECTED_LIVE_PROVIDER_CALL_CAPS: dict[str, int] = {
    "embedding": 450,
    "reranking": 450,
    "generation": 30,
}
_OPERATION_TIMEOUTS = {
    "auth_trust": 10.0,
    "document_ingestion": 15.0,
    "hybrid_retrieval": 45.0,
    "grounded_generation": 90.0,
    "artifact_access": 10.0,
    "ag_operations": 10.0,
    "readiness_probe": 10.0,
}


def build_protected_live_soak_profile(release_candidate_id: str) -> WorkloadProfile:
    baseline = build_default_workload_profiles(release_candidate_id)[2]
    operations = tuple(
        OperationMix(
            operation_id=operation.operation_id,
            weight=(
                PROTECTED_LIVE_OPERATION_COUNTS[operation.operation_id]
                / PROTECTED_LIVE_REQUEST_COUNT
            ),
            timeout_seconds=_OPERATION_TIMEOUTS[operation.operation_id],
        )
        for operation in baseline.operations
    )
    return replace(
        baseline,
        profile_id=PROTECTED_LIVE_PROFILE_ID,
        max_generated_records=PROTECTED_LIVE_REQUEST_COUNT,
        operations=operations,
        budget=WorkloadBudget(
            max_error_rate=0.02,
            max_p95_latency_ms=8_000.0,
            min_throughput_rps=2.0,
            max_saturation_ratio=0.80,
            max_duplicate_side_effects=0,
            max_isolation_violations=0,
        ),
    )


def build_protected_live_load_plan(
    admitted_profile: Mapping[str, object],
) -> tuple[LoadRequest, ...]:
    if admitted_profile.get("admission") != "ADMITTED":
        raise WorkloadProfileError("an admitted protected-live profile is required")
    if admitted_profile.get("profile_id") != PROTECTED_LIVE_PROFILE_ID:
        raise WorkloadProfileError("protected-live profile identity mismatch")
    if admitted_profile.get("workload_class") != "soak":
        raise WorkloadProfileError("protected-live workload class must be soak")
    target_rps = admitted_profile.get("target_rps")
    if not isinstance(target_rps, (int, float)) or isinstance(target_rps, bool):
        raise WorkloadProfileError("protected-live target RPS is invalid")
    digest = str(admitted_profile.get("workload_digest") or "")
    profile_id = str(admitted_profile["profile_id"])
    operation_ids = _smooth_weighted_operation_ids(
        PROTECTED_LIVE_OPERATION_COUNTS
    )
    return tuple(
        LoadRequest(
            request_id=_request_id(profile_id, digest, index),
            operation_id=operation_id,
            scheduled_offset_seconds=index / float(target_rps),
        )
        for index, operation_id in enumerate(operation_ids)
    )


def protected_live_plan_summary(
    requests: Sequence[LoadRequest],
) -> dict[str, object]:
    counts = Counter(item.operation_id for item in requests)
    checks = {
        "target_request_count_exact": len(requests)
        == PROTECTED_LIVE_REQUEST_COUNT,
        "operation_counts_exact": dict(counts)
        == PROTECTED_LIVE_OPERATION_COUNTS,
        "expensive_provider_caps_explicit": PROTECTED_LIVE_PROVIDER_CALL_CAPS
        == {
            "embedding": counts["hybrid_retrieval"],
            "reranking": counts["hybrid_retrieval"],
            "generation": counts["grounded_generation"],
        },
        "operations_interleaved": _operations_interleaved(requests),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "request_count": len(requests),
        "operation_counts": {
            name: counts[name] for name in PROTECTED_LIVE_OPERATION_COUNTS
        },
        "provider_call_caps": dict(PROTECTED_LIVE_PROVIDER_CALL_CAPS),
    }


def _smooth_weighted_operation_ids(counts: Mapping[str, int]) -> list[str]:
    if dict(counts) != PROTECTED_LIVE_OPERATION_COUNTS:
        raise WorkloadProfileError("protected-live operation counts are immutable")
    total = sum(counts.values())
    current = {name: 0 for name in counts}
    selected: list[str] = []
    for _ in range(total):
        for name, weight in counts.items():
            current[name] += weight
        chosen = max(counts, key=lambda name: current[name])
        current[chosen] -= total
        selected.append(chosen)
    return selected


def _operations_interleaved(requests: Sequence[LoadRequest]) -> bool:
    expensive = {"hybrid_retrieval", "grounded_generation"}
    positions = [
        index
        for index, request in enumerate(requests)
        if request.operation_id in expensive
    ]
    if not positions:
        return False
    return positions[0] < len(requests) // 4 and positions[-1] >= len(requests) * 3 // 4


def _request_id(profile_id: str, workload_digest: str, index: int) -> str:
    value = f"{profile_id}:{workload_digest}:{index}:protected-live".encode("utf-8")
    return f"load:{hashlib.sha256(value).hexdigest()[:24]}"
