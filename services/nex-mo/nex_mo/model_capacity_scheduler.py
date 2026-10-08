from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from nex_mo.model_rollout import ModelCapacitySnapshot, ModelRolloutError

RESERVATION_STATES = frozenset({"RESERVED", "RELEASED"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class CapacityPolicy:
    minimum_memory_headroom_percent: float = 15.0
    maximum_gpu_utilization_percent: float = 85.0
    maximum_gpu_temperature_c: float = 85.0
    maximum_queue_depth: int = 8
    maximum_active_requests: int = 32

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_memory_headroom_percent < 100:
            raise ModelRolloutError(
                "mo.capacity_headroom_policy_invalid",
                "memory headroom policy must be between 0 and 100",
            )
        if not 1 <= self.maximum_gpu_utilization_percent <= 100:
            raise ModelRolloutError(
                "mo.capacity_utilization_policy_invalid",
                "GPU utilization ceiling must be between 1 and 100",
            )
        if not 1 <= self.maximum_gpu_temperature_c <= 150:
            raise ModelRolloutError(
                "mo.capacity_temperature_policy_invalid",
                "GPU temperature ceiling must be between 1 and 150",
            )
        if self.maximum_queue_depth < 0 or self.maximum_active_requests < 1:
            raise ModelRolloutError(
                "mo.capacity_workload_policy_invalid",
                "queue and active request policy is invalid",
            )


@dataclass(frozen=True)
class CapacityRequest:
    rollout_id: str
    identity_fingerprint: str
    required_gpu_count: int
    required_memory_mib: int
    requested_concurrency: int
    exclusive: bool = False

    def __post_init__(self) -> None:
        _identifier(self.rollout_id, "rollout_id")
        if _SHA256.fullmatch(self.identity_fingerprint) is None:
            raise ModelRolloutError(
                "mo.capacity_identity_fingerprint_invalid",
                "identity fingerprint must be a SHA-256 digest",
            )
        if (
            self.required_gpu_count < 1
            or self.required_memory_mib < 1
            or self.requested_concurrency < 1
        ):
            raise ModelRolloutError(
                "mo.capacity_request_invalid",
                "capacity request values must be positive",
            )


@dataclass(frozen=True)
class CapacityReservation:
    reservation_id: str
    rollout_id: str
    identity_fingerprint: str
    node_id: str
    gpu_count: int
    memory_mib: int
    concurrency: int
    exclusive: bool
    state: str = "RESERVED"

    def __post_init__(self) -> None:
        for field_name in ("reservation_id", "rollout_id", "node_id"):
            _identifier(getattr(self, field_name), field_name)
        if _SHA256.fullmatch(self.identity_fingerprint) is None:
            raise ModelRolloutError(
                "mo.capacity_identity_fingerprint_invalid",
                "identity fingerprint must be a SHA-256 digest",
            )
        if self.gpu_count < 1 or self.memory_mib < 1 or self.concurrency < 1:
            raise ModelRolloutError(
                "mo.capacity_reservation_invalid",
                "reservation values must be positive",
            )
        if self.state not in RESERVATION_STATES:
            raise ModelRolloutError(
                "mo.capacity_reservation_state_invalid",
                "unsupported reservation state",
            )

    def release(self) -> CapacityReservation:
        if self.state == "RELEASED":
            return self
        return CapacityReservation(**{**self.to_wire(), "state": "RELEASED"})

    def to_wire(self) -> dict[str, Any]:
        return {
            "reservation_id": self.reservation_id,
            "rollout_id": self.rollout_id,
            "identity_fingerprint": self.identity_fingerprint,
            "node_id": self.node_id,
            "gpu_count": self.gpu_count,
            "memory_mib": self.memory_mib,
            "concurrency": self.concurrency,
            "exclusive": self.exclusive,
            "state": self.state,
        }


@dataclass(frozen=True)
class CapacityAdmissionDecision:
    status: str
    reason: str | None
    evaluated_node_count: int
    eligible_node_count: int
    reservation: CapacityReservation | None
    node_failures: tuple[tuple[str, str], ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "mo_capacity_admission.v1",
            "status": self.status,
            "reason": self.reason,
            "evaluated_node_count": self.evaluated_node_count,
            "eligible_node_count": self.eligible_node_count,
            "reservation": (
                self.reservation.to_wire() if self.reservation is not None else None
            ),
            "node_failures": [
                {"node_id": node_id, "failure_code": failure_code}
                for node_id, failure_code in self.node_failures
            ],
        }


def admit_capacity(
    snapshot: ModelCapacitySnapshot,
    request: CapacityRequest,
    *,
    evaluated_at: str,
    policy: CapacityPolicy | None = None,
    reservations: Sequence[CapacityReservation] = (),
) -> CapacityAdmissionDecision:
    effective_policy = policy or CapacityPolicy()
    if request.identity_fingerprint != snapshot.identity.fingerprint:
        return _blocked(snapshot, "capacity_identity_mismatch")
    if not snapshot.is_fresh(evaluated_at):
        return _blocked(snapshot, "capacity_snapshot_stale")

    active = tuple(item for item in reservations if item.state == "RESERVED")
    candidates: list[tuple[tuple[float, int, str], Any]] = []
    failures: list[tuple[str, str]] = []
    for node in snapshot.nodes:
        failure = _node_failure(node, request, effective_policy, active)
        if failure is not None:
            failures.append((node.node_id, failure))
            continue
        rank = (node.gpu_utilization_percent, node.queue_depth, node.node_id)
        candidates.append((rank, node))

    if not candidates:
        reason = failures[0][1] if len(snapshot.nodes) == 1 else "capacity_unavailable"
        return CapacityAdmissionDecision(
            status="BLOCKED",
            reason=reason,
            evaluated_node_count=len(snapshot.nodes),
            eligible_node_count=0,
            reservation=None,
            node_failures=tuple(failures),
        )

    selected = min(candidates, key=lambda item: item[0])[1]
    reservation = CapacityReservation(
        reservation_id=_reservation_id(request, selected.node_id),
        rollout_id=request.rollout_id,
        identity_fingerprint=request.identity_fingerprint,
        node_id=selected.node_id,
        gpu_count=request.required_gpu_count,
        memory_mib=request.required_memory_mib,
        concurrency=request.requested_concurrency,
        exclusive=request.exclusive,
    )
    return CapacityAdmissionDecision(
        status="ADMITTED",
        reason=None,
        evaluated_node_count=len(snapshot.nodes),
        eligible_node_count=len(candidates),
        reservation=reservation,
        node_failures=tuple(failures),
    )


def _node_failure(node, request, policy, reservations) -> str | None:
    if node.health_status != "HEALTHY":
        return "capacity_node_not_healthy"
    if node.gpu_utilization_percent >= policy.maximum_gpu_utilization_percent:
        return "capacity_gpu_utilization_pressure"
    if node.gpu_temperature_c >= policy.maximum_gpu_temperature_c:
        return "capacity_gpu_temperature_pressure"
    if node.queue_depth > policy.maximum_queue_depth:
        return "capacity_queue_pressure"

    node_reservations = tuple(item for item in reservations if item.node_id == node.node_id)
    if any(item.exclusive for item in node_reservations) or (
        request.exclusive and node_reservations
    ):
        return "capacity_exclusive_conflict"
    reserved_gpu = sum(item.gpu_count for item in node_reservations)
    reserved_memory = sum(item.memory_mib for item in node_reservations)
    reserved_concurrency = sum(item.concurrency for item in node_reservations)
    if node.allocatable_gpu_count - reserved_gpu < request.required_gpu_count:
        return "capacity_gpu_insufficient"
    if node.memory_available_mib - reserved_memory < request.required_memory_mib:
        return "capacity_memory_insufficient"
    remaining_memory = (
        node.memory_available_mib - reserved_memory - request.required_memory_mib
    )
    headroom_percent = (remaining_memory / node.memory_total_mib) * 100
    if headroom_percent < policy.minimum_memory_headroom_percent:
        return "capacity_memory_headroom_insufficient"
    if (
        node.active_requests + reserved_concurrency + request.requested_concurrency
        > policy.maximum_active_requests
    ):
        return "capacity_concurrency_exceeded"
    return None


def _blocked(
    snapshot: ModelCapacitySnapshot,
    reason: str,
) -> CapacityAdmissionDecision:
    return CapacityAdmissionDecision(
        status="BLOCKED",
        reason=reason,
        evaluated_node_count=len(snapshot.nodes),
        eligible_node_count=0,
        reservation=None,
        node_failures=(),
    )


def _reservation_id(request: CapacityRequest, node_id: str) -> str:
    payload = json.dumps(
        {
            "identity_fingerprint": request.identity_fingerprint,
            "node_id": node_id,
            "rollout_id": request.rollout_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"reservation:{hashlib.sha256(payload).hexdigest()[:32]}"


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ModelRolloutError(
            f"mo.{field_name}_invalid",
            f"{field_name} must be a stable identifier",
        )
    return value
