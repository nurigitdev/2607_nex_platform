#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.model_rollout import (
    GpuNodeCapacity,
    ModelRevisionIdentity,
    build_capacity_snapshot,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def run_model_revision_capacity_domain() -> dict[str, Any]:
    identities = tuple(_identity(capability) for capability in ("embedding", "reranking", "generation"))
    snapshots = tuple(
        build_capacity_snapshot(
            identity,
            [_node(capability=identity.provider_capability)],
            source="deterministic_fixture",
            observed_at="2026-10-08T00:00:00Z",
            expires_at="2026-10-08T00:01:00Z",
        )
        for identity in identities
    )
    wires = [snapshot.to_wire() for snapshot in snapshots]
    checks = {
        "three_capabilities_present": len(identities) == 3,
        "identity_fingerprints_unique": len({identity.fingerprint for identity in identities}) == 3,
        "model_names_absent": all("model_name" not in wire["identity"] for wire in wires),
        "artifact_and_request_digests_bound": all(
            wire["identity"]["artifact_digest"].startswith("sha256:")
            and wire["identity"]["request_shape_hash"].startswith("sha256:")
            for wire in wires
        ),
        "gpu_capacity_aggregated": sum(snapshot.total_gpu_count for snapshot in snapshots) == 3,
        "allocatable_capacity_aggregated": sum(snapshot.allocatable_gpu_count for snapshot in snapshots) == 3,
        "memory_capacity_aggregated": sum(snapshot.memory_available_mib for snapshot in snapshots) == 72_000,
        "freshness_enforced": all(snapshot.is_fresh("2026-10-08T00:00:30Z") for snapshot in snapshots),
        "expired_snapshots_rejected": not any(snapshot.is_fresh("2026-10-08T00:01:00Z") for snapshot in snapshots),
    }
    passed = all(checks.values())
    return {
        "schema_version": "s147_model_revision_capacity_domain.v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "capability_count": len(identities),
            "identity_count": len(identities),
            "node_count": sum(len(snapshot.nodes) for snapshot in snapshots),
            "gpu_count": sum(snapshot.total_gpu_count for snapshot in snapshots),
            "check_count": len(checks),
        },
        "identity_fingerprints": [identity.fingerprint for identity in identities],
        "next_slice": "1465" if passed else "blocked",
    }


def _identity(capability: str) -> ModelRevisionIdentity:
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


def _node(*, capability: str) -> GpuNodeCapacity:
    return GpuNodeCapacity(
        node_id=f"node:{capability}",
        accelerator_type="nvidia-gpu",
        gpu_count=1,
        allocatable_gpu_count=1,
        memory_total_mib=32_000,
        memory_reserved_mib=8_000,
        active_requests=0,
        queue_depth=0,
        gpu_utilization_percent=10.0,
        gpu_temperature_c=50.0,
        health_status="HEALTHY",
    )


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    return (
        "model_revision_capacity_domain="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"capabilities={summary.get('capability_count', 0)} "
        f"identities={summary.get('identity_count', 0)} "
        f"nodes={summary.get('node_count', 0)} "
        f"checks={summary.get('check_count', 0)}/9 "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_model_revision_capacity_domain()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
