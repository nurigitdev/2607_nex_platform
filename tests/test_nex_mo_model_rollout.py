from __future__ import annotations

from dataclasses import replace

import pytest
from nex_mo.model_rollout import (
    GpuNodeCapacity,
    ModelCapacitySnapshot,
    ModelRevisionIdentity,
    ModelRolloutError,
    build_capacity_snapshot,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def identity(capability: str = "embedding") -> ModelRevisionIdentity:
    return ModelRevisionIdentity(
        provider_capability=capability,
        alias=f"{capability}-default",
        catalog_id=f"catalog:{capability}:r1",
        model_revision=f"revision:{capability}:1",
        deployment_id=f"deployment:{capability}:1",
        artifact_digest=DIGEST_A,
        runtime_engine="openai-compatible",
        precision="bfloat16",
        request_shape_hash=DIGEST_B,
    )


def node(node_id: str = "dgx:one") -> GpuNodeCapacity:
    return GpuNodeCapacity(
        node_id=node_id,
        accelerator_type="nvidia-gpu",
        gpu_count=2,
        allocatable_gpu_count=1,
        memory_total_mib=200_000,
        memory_reserved_mib=120_000,
        active_requests=2,
        queue_depth=1,
        gpu_utilization_percent=42.5,
        gpu_temperature_c=61.0,
        health_status="HEALTHY",
    )


def snapshot() -> ModelCapacitySnapshot:
    return build_capacity_snapshot(
        identity(),
        [node(), node("dgx:two")],
        source="deterministic_fixture",
        observed_at="2026-10-08T00:00:00Z",
        expires_at="2026-10-08T00:01:00Z",
    )


def test_identity_fingerprint_is_stable_and_model_name_free() -> None:
    model = identity()

    assert model.fingerprint == identity().fingerprint
    assert model.fingerprint.startswith("sha256:")
    assert set(model.to_wire()) == {
        "provider_capability",
        "alias",
        "catalog_id",
        "model_revision",
        "deployment_id",
        "artifact_digest",
        "runtime_engine",
        "precision",
        "request_shape_hash",
    }
    assert "model_name" not in model.to_wire()
    assert replace(model, deployment_id="deployment:embedding:2").fingerprint != model.fingerprint


@pytest.mark.parametrize("capability", ["embedding", "reranking", "generation"])
def test_all_capabilities_are_supported(capability: str) -> None:
    assert identity(capability).provider_capability == capability


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("provider_capability", "vision", "mo.rollout_capability_invalid"),
        ("alias", "", "mo.alias_invalid"),
        ("artifact_digest", "abc", "mo.artifact_digest_invalid"),
        ("request_shape_hash", "sha256:ABC", "mo.request_shape_hash_invalid"),
    ],
)
def test_identity_rejects_invalid_values(field: str, value: str, code: str) -> None:
    with pytest.raises(ModelRolloutError) as exc:
        replace(identity(), **{field: value})
    assert exc.value.error_code == code
    assert str(exc.value) == exc.value.detail


def test_capacity_snapshot_projects_totals_and_freshness() -> None:
    capacity = snapshot()
    wire = capacity.to_wire()

    assert capacity.total_gpu_count == 4
    assert capacity.allocatable_gpu_count == 2
    assert capacity.memory_available_mib == 160_000
    assert capacity.is_fresh("2026-10-08T00:00:00Z") is True
    assert capacity.is_fresh("2026-10-08T00:00:59Z") is True
    assert capacity.is_fresh("2026-10-08T00:01:00Z") is False
    assert wire["summary"] == {
        "node_count": 2,
        "total_gpu_count": 4,
        "allocatable_gpu_count": 2,
        "memory_available_mib": 160_000,
    }
    assert wire["nodes"][0]["memory_available_mib"] == 80_000


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("gpu_count", 0, "mo.capacity_gpu_count_invalid"),
        ("allocatable_gpu_count", 3, "mo.capacity_allocatable_gpu_invalid"),
        ("memory_total_mib", 0, "mo.capacity_memory_invalid"),
        ("memory_reserved_mib", 300_000, "mo.capacity_memory_invalid"),
        ("active_requests", -1, "mo.capacity_workload_invalid"),
        ("queue_depth", -1, "mo.capacity_workload_invalid"),
        ("gpu_utilization_percent", 101, "mo.capacity_utilization_invalid"),
        ("gpu_temperature_c", 151, "mo.capacity_temperature_invalid"),
        ("health_status", "UNKNOWN", "mo.capacity_health_invalid"),
    ],
)
def test_node_rejects_invalid_capacity(field: str, value: object, code: str) -> None:
    with pytest.raises(ModelRolloutError) as exc:
        replace(node(), **{field: value})
    assert exc.value.error_code == code


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"nodes": ()}, "mo.capacity_nodes_missing"),
        ({"nodes": (node(), node())}, "mo.capacity_node_duplicate"),
        ({"source": "http"}, "mo.capacity_source_invalid"),
        ({"expires_at": "2026-10-07T23:59:00Z"}, "mo.capacity_expiry_invalid"),
        ({"observed_at": "not-time"}, "mo.observed_at_invalid"),
        ({"expires_at": "2026-10-08T00:01:00"}, "mo.expires_at_invalid"),
    ],
)
def test_snapshot_rejects_invalid_shape(changes: dict[str, object], code: str) -> None:
    with pytest.raises(ModelRolloutError) as exc:
        replace(snapshot(), **changes)
    assert exc.value.error_code == code


def test_identifier_and_at_timestamp_errors() -> None:
    with pytest.raises(ModelRolloutError, match="stable identifier"):
        replace(node(), node_id="bad node")
    with pytest.raises(ModelRolloutError) as exc:
        snapshot().is_fresh("bad-time")
    assert exc.value.error_code == "mo.at_invalid"
