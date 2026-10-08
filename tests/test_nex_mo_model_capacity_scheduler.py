from __future__ import annotations

from dataclasses import replace

import pytest
from nex_mo.model_capacity_scheduler import (
    CapacityPolicy,
    CapacityRequest,
    CapacityReservation,
    admit_capacity,
)
from nex_mo.model_rollout import (
    GpuNodeCapacity,
    ModelRevisionIdentity,
    ModelRolloutError,
    build_capacity_snapshot,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def identity() -> ModelRevisionIdentity:
    return ModelRevisionIdentity(
        provider_capability="generation",
        alias="generation-default",
        catalog_id="catalog:generation:r2",
        model_revision="revision:generation:2",
        deployment_id="deployment:generation:2",
        artifact_digest=DIGEST_A,
        runtime_engine="vllm",
        precision="bfloat16",
        request_shape_hash=DIGEST_B,
    )


def node(node_id: str = "node:a", **changes) -> GpuNodeCapacity:
    values = {
        "node_id": node_id,
        "accelerator_type": "nvidia-gpu",
        "gpu_count": 2,
        "allocatable_gpu_count": 2,
        "memory_total_mib": 100_000,
        "memory_reserved_mib": 20_000,
        "active_requests": 2,
        "queue_depth": 1,
        "gpu_utilization_percent": 30.0,
        "gpu_temperature_c": 55.0,
        "health_status": "HEALTHY",
    }
    values.update(changes)
    return GpuNodeCapacity(**values)


def snapshot(*nodes: GpuNodeCapacity):
    return build_capacity_snapshot(
        identity(),
        nodes or (node(),),
        source="deterministic_fixture",
        observed_at="2026-10-08T00:00:00Z",
        expires_at="2026-10-08T00:01:00Z",
    )


def request(**changes) -> CapacityRequest:
    values = {
        "rollout_id": "rollout:generation:2",
        "identity_fingerprint": identity().fingerprint,
        "required_gpu_count": 1,
        "required_memory_mib": 20_000,
        "requested_concurrency": 4,
        "exclusive": False,
    }
    values.update(changes)
    return CapacityRequest(**values)


def test_admission_selects_lowest_pressure_node_deterministically() -> None:
    decision = admit_capacity(
        snapshot(
            node("node:b", gpu_utilization_percent=40.0),
            node("node:a", gpu_utilization_percent=10.0),
        ),
        request(),
        evaluated_at="2026-10-08T00:00:30Z",
    )

    assert decision.status == "ADMITTED"
    assert decision.reason is None
    assert decision.evaluated_node_count == 2
    assert decision.eligible_node_count == 2
    assert decision.reservation is not None
    assert decision.reservation.node_id == "node:a"
    assert decision.reservation.reservation_id.startswith("reservation:")
    assert decision.to_wire()["node_failures"] == []


def test_existing_reservation_is_subtracted_and_release_is_idempotent() -> None:
    first = admit_capacity(
        snapshot(), request(), evaluated_at="2026-10-08T00:00:30Z"
    ).reservation
    assert first is not None
    blocked = admit_capacity(
        snapshot(node(allocatable_gpu_count=1)),
        replace(request(), rollout_id="rollout:generation:3"),
        evaluated_at="2026-10-08T00:00:30Z",
        reservations=[first],
    )
    assert blocked.status == "BLOCKED"
    assert blocked.reason == "capacity_gpu_insufficient"
    assert blocked.node_failures == (("node:a", "capacity_gpu_insufficient"),)

    released = first.release()
    assert released.state == "RELEASED"
    assert released.release() is released
    assert released.to_wire()["state"] == "RELEASED"
    admitted = admit_capacity(
        snapshot(node(allocatable_gpu_count=1)),
        replace(request(), rollout_id="rollout:generation:3"),
        evaluated_at="2026-10-08T00:00:30Z",
        reservations=[released],
    )
    assert admitted.status == "ADMITTED"


@pytest.mark.parametrize(
    ("node_value", "reason"),
    [
        (node(health_status="DEGRADED"), "capacity_node_not_healthy"),
        (node(gpu_utilization_percent=85.0), "capacity_gpu_utilization_pressure"),
        (node(gpu_temperature_c=85.0), "capacity_gpu_temperature_pressure"),
        (node(queue_depth=9), "capacity_queue_pressure"),
        (node(allocatable_gpu_count=0), "capacity_gpu_insufficient"),
        (node(memory_reserved_mib=90_000), "capacity_memory_insufficient"),
        (node(memory_reserved_mib=70_000), "capacity_memory_headroom_insufficient"),
        (node(active_requests=30), "capacity_concurrency_exceeded"),
    ],
)
def test_node_pressure_blocks_admission(
    node_value: GpuNodeCapacity,
    reason: str,
) -> None:
    decision = admit_capacity(
        snapshot(node_value),
        request(),
        evaluated_at="2026-10-08T00:00:30Z",
    )
    assert decision.status == "BLOCKED"
    assert decision.reason == reason
    assert decision.reservation is None


def test_multiple_failures_are_redacted_to_capacity_unavailable() -> None:
    decision = admit_capacity(
        snapshot(node("node:a", health_status="UNAVAILABLE"), node("node:b", queue_depth=20)),
        request(),
        evaluated_at="2026-10-08T00:00:30Z",
    )
    assert decision.reason == "capacity_unavailable"
    assert len(decision.to_wire()["node_failures"]) == 2


def test_identity_staleness_and_exclusive_conflicts_fail_closed() -> None:
    mismatch = admit_capacity(
        snapshot(),
        request(identity_fingerprint="sha256:" + "c" * 64),
        evaluated_at="2026-10-08T00:00:30Z",
    )
    assert mismatch.reason == "capacity_identity_mismatch"
    stale = admit_capacity(
        snapshot(), request(), evaluated_at="2026-10-08T00:02:00Z"
    )
    assert stale.reason == "capacity_snapshot_stale"

    existing = CapacityReservation(
        reservation_id="reservation:existing",
        rollout_id="rollout:existing",
        identity_fingerprint=identity().fingerprint,
        node_id="node:a",
        gpu_count=1,
        memory_mib=10_000,
        concurrency=1,
        exclusive=True,
    )
    blocked = admit_capacity(
        snapshot(),
        request(),
        evaluated_at="2026-10-08T00:00:30Z",
        reservations=[existing],
    )
    assert blocked.reason == "capacity_exclusive_conflict"

    nonexclusive = replace(existing, exclusive=False)
    exclusive_request = request(exclusive=True)
    assert (
        admit_capacity(
            snapshot(),
            exclusive_request,
            evaluated_at="2026-10-08T00:00:30Z",
            reservations=[nonexclusive],
        ).reason
        == "capacity_exclusive_conflict"
    )


@pytest.mark.parametrize(
    ("factory", "changes", "code"),
    [
        (CapacityPolicy, {"minimum_memory_headroom_percent": 100}, "mo.capacity_headroom_policy_invalid"),
        (CapacityPolicy, {"maximum_gpu_utilization_percent": 0}, "mo.capacity_utilization_policy_invalid"),
        (CapacityPolicy, {"maximum_gpu_temperature_c": 151}, "mo.capacity_temperature_policy_invalid"),
        (CapacityPolicy, {"maximum_queue_depth": -1}, "mo.capacity_workload_policy_invalid"),
    ],
)
def test_policy_validation(factory, changes: dict[str, object], code: str) -> None:
    with pytest.raises(ModelRolloutError) as exc:
        factory(**changes)
    assert exc.value.error_code == code


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"rollout_id": "bad rollout"}, "mo.rollout_id_invalid"),
        ({"identity_fingerprint": "bad"}, "mo.capacity_identity_fingerprint_invalid"),
        ({"required_gpu_count": 0}, "mo.capacity_request_invalid"),
    ],
)
def test_request_validation(changes: dict[str, object], code: str) -> None:
    with pytest.raises(ModelRolloutError) as exc:
        request(**changes)
    assert exc.value.error_code == code


def test_reservation_validation() -> None:
    admitted = admit_capacity(
        snapshot(), request(), evaluated_at="2026-10-08T00:00:30Z"
    ).reservation
    assert admitted is not None
    for changes, code in (
        ({"reservation_id": "bad id"}, "mo.reservation_id_invalid"),
        ({"identity_fingerprint": "bad"}, "mo.capacity_identity_fingerprint_invalid"),
        ({"memory_mib": 0}, "mo.capacity_reservation_invalid"),
        ({"state": "ACTIVE"}, "mo.capacity_reservation_state_invalid"),
    ):
        with pytest.raises(ModelRolloutError) as exc:
            replace(admitted, **changes)
        assert exc.value.error_code == code
