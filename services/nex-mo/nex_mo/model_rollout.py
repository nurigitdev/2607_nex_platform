from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

MODEL_CAPABILITIES = frozenset({"embedding", "reranking", "generation"})
CAPACITY_SOURCES = frozenset({"deterministic_fixture", "protected_ssh"})
NODE_HEALTH_STATUSES = frozenset({"HEALTHY", "DEGRADED", "UNAVAILABLE"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class ModelRolloutError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class ModelRevisionIdentity:
    provider_capability: str
    alias: str
    catalog_id: str
    model_revision: str
    deployment_id: str
    artifact_digest: str
    runtime_engine: str
    precision: str
    request_shape_hash: str

    def __post_init__(self) -> None:
        if self.provider_capability not in MODEL_CAPABILITIES:
            raise ModelRolloutError(
                "mo.rollout_capability_invalid",
                "unsupported model capability",
            )
        for field_name in (
            "alias",
            "catalog_id",
            "model_revision",
            "deployment_id",
            "runtime_engine",
            "precision",
        ):
            _identifier(getattr(self, field_name), field_name)
        _digest(self.artifact_digest, "artifact_digest")
        _digest(self.request_shape_hash, "request_shape_hash")

    @property
    def fingerprint(self) -> str:
        return _sha256(self.to_wire())

    def to_wire(self) -> dict[str, str]:
        return {
            "provider_capability": self.provider_capability,
            "alias": self.alias,
            "catalog_id": self.catalog_id,
            "model_revision": self.model_revision,
            "deployment_id": self.deployment_id,
            "artifact_digest": self.artifact_digest,
            "runtime_engine": self.runtime_engine,
            "precision": self.precision,
            "request_shape_hash": self.request_shape_hash,
        }


@dataclass(frozen=True)
class GpuNodeCapacity:
    node_id: str
    accelerator_type: str
    gpu_count: int
    allocatable_gpu_count: int
    memory_total_mib: int
    memory_reserved_mib: int
    active_requests: int
    queue_depth: int
    gpu_utilization_percent: float
    gpu_temperature_c: float
    health_status: str

    def __post_init__(self) -> None:
        _identifier(self.node_id, "node_id")
        _identifier(self.accelerator_type, "accelerator_type")
        if self.gpu_count < 1:
            raise ModelRolloutError(
                "mo.capacity_gpu_count_invalid",
                "gpu_count must be positive",
            )
        if not 0 <= self.allocatable_gpu_count <= self.gpu_count:
            raise ModelRolloutError(
                "mo.capacity_allocatable_gpu_invalid",
                "allocatable GPU count exceeds node capacity",
            )
        if self.memory_total_mib < 1 or not 0 <= self.memory_reserved_mib <= self.memory_total_mib:
            raise ModelRolloutError(
                "mo.capacity_memory_invalid",
                "GPU memory capacity is invalid",
            )
        if self.active_requests < 0 or self.queue_depth < 0:
            raise ModelRolloutError(
                "mo.capacity_workload_invalid",
                "active request and queue counts must not be negative",
            )
        if not 0 <= self.gpu_utilization_percent <= 100:
            raise ModelRolloutError(
                "mo.capacity_utilization_invalid",
                "GPU utilization must be between 0 and 100",
            )
        if not 0 <= self.gpu_temperature_c <= 150:
            raise ModelRolloutError(
                "mo.capacity_temperature_invalid",
                "GPU temperature must be between 0 and 150",
            )
        if self.health_status not in NODE_HEALTH_STATUSES:
            raise ModelRolloutError(
                "mo.capacity_health_invalid",
                "unsupported GPU node health status",
            )

    @property
    def memory_available_mib(self) -> int:
        return self.memory_total_mib - self.memory_reserved_mib

    def to_wire(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "accelerator_type": self.accelerator_type,
            "gpu_count": self.gpu_count,
            "allocatable_gpu_count": self.allocatable_gpu_count,
            "memory_total_mib": self.memory_total_mib,
            "memory_reserved_mib": self.memory_reserved_mib,
            "memory_available_mib": self.memory_available_mib,
            "active_requests": self.active_requests,
            "queue_depth": self.queue_depth,
            "gpu_utilization_percent": self.gpu_utilization_percent,
            "gpu_temperature_c": self.gpu_temperature_c,
            "health_status": self.health_status,
        }


@dataclass(frozen=True)
class ModelCapacitySnapshot:
    identity: ModelRevisionIdentity
    nodes: tuple[GpuNodeCapacity, ...]
    source: str
    observed_at: str
    expires_at: str

    def __post_init__(self) -> None:
        if not self.nodes:
            raise ModelRolloutError(
                "mo.capacity_nodes_missing",
                "at least one GPU node is required",
            )
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ModelRolloutError(
                "mo.capacity_node_duplicate",
                "GPU node identities must be unique",
            )
        if self.source not in CAPACITY_SOURCES:
            raise ModelRolloutError(
                "mo.capacity_source_invalid",
                "unsupported capacity observation source",
            )
        observed = _timestamp(self.observed_at, "observed_at")
        expires = _timestamp(self.expires_at, "expires_at")
        if expires <= observed:
            raise ModelRolloutError(
                "mo.capacity_expiry_invalid",
                "capacity expiry must follow observation time",
            )

    @property
    def total_gpu_count(self) -> int:
        return sum(node.gpu_count for node in self.nodes)

    @property
    def allocatable_gpu_count(self) -> int:
        return sum(node.allocatable_gpu_count for node in self.nodes)

    @property
    def memory_available_mib(self) -> int:
        return sum(node.memory_available_mib for node in self.nodes)

    def is_fresh(self, at: str) -> bool:
        instant = _timestamp(at, "at")
        return _timestamp(self.observed_at, "observed_at") <= instant < _timestamp(
            self.expires_at,
            "expires_at",
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "mo_model_capacity_snapshot.v1",
            "identity": self.identity.to_wire(),
            "identity_fingerprint": self.identity.fingerprint,
            "source": self.source,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "nodes": [node.to_wire() for node in self.nodes],
            "summary": {
                "node_count": len(self.nodes),
                "total_gpu_count": self.total_gpu_count,
                "allocatable_gpu_count": self.allocatable_gpu_count,
                "memory_available_mib": self.memory_available_mib,
            },
        }


def build_capacity_snapshot(
    identity: ModelRevisionIdentity,
    nodes: Sequence[GpuNodeCapacity],
    *,
    source: str,
    observed_at: str,
    expires_at: str,
) -> ModelCapacitySnapshot:
    return ModelCapacitySnapshot(
        identity=identity,
        nodes=tuple(nodes),
        source=source,
        observed_at=observed_at,
        expires_at=expires_at,
    )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ModelRolloutError(
            f"mo.{field_name}_invalid",
            f"{field_name} must be a stable identifier",
        )
    return value


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ModelRolloutError(
            f"mo.{field_name}_invalid",
            f"{field_name} must be a SHA-256 digest",
        )
    return value


def _timestamp(value: object, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelRolloutError(
            f"mo.{field_name}_invalid",
            f"{field_name} must be ISO 8601",
        ) from exc
    if parsed.tzinfo is None:
        raise ModelRolloutError(
            f"mo.{field_name}_invalid",
            f"{field_name} must include a timezone",
        )
    return parsed.astimezone(UTC)


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
