from __future__ import annotations

from dataclasses import replace

import pytest
from nex_mo.model_capacity_scheduler import CapacityRequest, admit_capacity
from nex_mo.model_rollout import (
    GpuNodeCapacity,
    ModelRevisionIdentity,
    build_capacity_snapshot,
)
from nex_mo.model_rollout_readiness import evaluate_revision_readiness
from nex_mo.provider_readiness import ProviderRouteHealth
from nex_mo.runtime_observability import ModelRuntimeObservation

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def identity() -> ModelRevisionIdentity:
    return ModelRevisionIdentity(
        provider_capability="reranking",
        alias="reranking-default",
        catalog_id="catalog:reranking:r2",
        model_revision="revision:reranking:2",
        deployment_id="deployment:reranking:2",
        artifact_digest=DIGEST_A,
        runtime_engine="vllm",
        precision="bfloat16",
        request_shape_hash=DIGEST_B,
    )


def route(**changes) -> ProviderRouteHealth:
    values = {
        "provider_capability": "reranking",
        "alias": "reranking-default",
        "route_id": "route:reranking:2",
        "deployment_id": "deployment:reranking:2",
        "model_revision": "revision:reranking:2",
        "status": "READY",
        "source": "active_preflight",
        "checked_at": "2026-10-08T00:00:00Z",
    }
    values.update(changes)
    return ProviderRouteHealth(**values)


def runtime(**changes) -> ModelRuntimeObservation:
    values = {
        "provider_capability": "reranking",
        "alias": "reranking-default",
        "deployment_id": "deployment:reranking:2",
        "model_revision": "revision:reranking:2",
        "runtime_status": "HEALTHY",
        "precision_status": "MATCH",
        "requested_dtype": "bfloat16",
        "loaded_dtype": "bfloat16",
        "process_count": 1,
        "gpu_count": 1,
        "gpu_memory_used_mib": 10_000,
        "gpu_memory_total_mib": 100_000,
        "gpu_utilization_percent": 20,
        "gpu_temperature_c": 50,
        "source": "protected_ssh",
        "observed_at": "2026-10-08T00:00:00Z",
    }
    values.update(changes)
    return ModelRuntimeObservation(**values)


def capacity():
    model = identity()
    snapshot = build_capacity_snapshot(
        model,
        [
            GpuNodeCapacity(
                node_id="node:one",
                accelerator_type="nvidia-gpu",
                gpu_count=2,
                allocatable_gpu_count=2,
                memory_total_mib=100_000,
                memory_reserved_mib=20_000,
                active_requests=1,
                queue_depth=0,
                gpu_utilization_percent=20,
                gpu_temperature_c=50,
                health_status="HEALTHY",
            )
        ],
        source="protected_ssh",
        observed_at="2026-10-08T00:00:00Z",
        expires_at="2026-10-08T00:01:00Z",
    )
    return admit_capacity(
        snapshot,
        CapacityRequest(
            rollout_id="rollout:reranking:2",
            identity_fingerprint=model.fingerprint,
            required_gpu_count=1,
            required_memory_mib=20_000,
            requested_concurrency=2,
        ),
        evaluated_at="2026-10-08T00:00:30Z",
    )


def decision(**changes):
    values = {
        "identity": identity(),
        "route": route(),
        "runtime": runtime(),
        "capacity": capacity(),
        "evaluated_at": "2026-10-08T00:00:30Z",
        "require_live": True,
    }
    values.update(changes)
    return evaluate_revision_readiness(**values)


def test_exact_live_evidence_is_ready_and_metadata_only() -> None:
    result = decision()

    assert result["status"] == "READY"
    assert result["failure_code"] is None
    assert result["failure_checks"] == []
    assert all(result["checks"].values())
    assert result["identity_fingerprint"] == identity().fingerprint
    assert result["evidence_digest"].startswith("sha256:")
    assert "endpoint" not in result["evidence"]


@pytest.mark.parametrize(
    ("changes", "failed_check"),
    [
        ({"route": route(model_revision="revision:other")}, "provider_identity_matches"),
        ({"route": route(status="DEGRADED", degraded=True)}, "provider_route_ready"),
        ({"route": route(checked_at="2026-10-07T23:00:00Z")}, "provider_evidence_fresh"),
        ({"route": route(source="mock_registry")}, "provider_source_admitted"),
        ({"runtime": runtime(deployment_id="deployment:other")}, "runtime_identity_matches"),
        ({"runtime": runtime(runtime_status="DEGRADED")}, "runtime_healthy"),
        ({"runtime": runtime(observed_at="2026-10-07T23:00:00Z")}, "runtime_evidence_fresh"),
        ({"runtime": runtime(source="mock_fixture")}, "runtime_source_admitted"),
    ],
)
def test_mismatched_or_stale_evidence_blocks(changes, failed_check: str) -> None:
    result = decision(**changes)
    assert result["status"] == "BLOCKED"
    assert result["failure_code"] == "revision_readiness_blocked"
    assert failed_check in result["failure_checks"]


def test_capacity_status_and_identity_must_match() -> None:
    blocked_capacity = replace(capacity(), status="BLOCKED", reservation=None)
    result = decision(capacity=blocked_capacity)
    assert result["checks"]["capacity_admitted"] is False
    assert result["checks"]["capacity_identity_matches"] is False

    reservation = capacity().reservation
    assert reservation is not None
    wrong = replace(reservation, identity_fingerprint="sha256:" + "c" * 64)
    result = decision(capacity=replace(capacity(), reservation=wrong))
    assert result["failure_checks"] == ["capacity_identity_matches"]


def test_non_live_mode_accepts_mock_sources() -> None:
    result = decision(
        route=route(source="mock_registry"),
        runtime=runtime(source="mock_fixture"),
        require_live=False,
    )
    assert result["status"] == "READY"


@pytest.mark.parametrize("timestamp", ["bad", "2026-10-08T00:00:00"])
def test_invalid_timestamps_are_rejected(timestamp: str) -> None:
    with pytest.raises(ValueError, match="timestamp"):
        decision(evaluated_at=timestamp)


@pytest.mark.parametrize("ttl", [0, 301])
def test_invalid_ttl_is_rejected(ttl: int) -> None:
    with pytest.raises(ValueError, match="evidence_ttl_seconds"):
        decision(evidence_ttl_seconds=ttl)


def test_future_evidence_is_not_fresh() -> None:
    result = decision(evaluated_at="2026-10-07T23:59:00Z")
    assert result["checks"]["provider_evidence_fresh"] is False
    assert result["checks"]["runtime_evidence_fresh"] is False
