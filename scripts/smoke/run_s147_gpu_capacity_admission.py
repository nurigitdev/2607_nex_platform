#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.model_capacity_scheduler import (
    CapacityRequest,
    admit_capacity,
)
from nex_mo.model_rollout import (
    GpuNodeCapacity,
    ModelRevisionIdentity,
    build_capacity_snapshot,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def run_gpu_capacity_admission() -> dict[str, Any]:
    identity = _identity()
    snapshot = build_capacity_snapshot(
        identity,
        [_node("node:busy", utilization=70), _node("node:preferred", utilization=20)],
        source="deterministic_fixture",
        observed_at="2026-10-08T00:00:00Z",
        expires_at="2026-10-08T00:01:00Z",
    )
    request = CapacityRequest(
        rollout_id="rollout:generation:2",
        identity_fingerprint=identity.fingerprint,
        required_gpu_count=1,
        required_memory_mib=20_000,
        requested_concurrency=4,
    )
    admitted = admit_capacity(snapshot, request, evaluated_at="2026-10-08T00:00:30Z")
    reservation = admitted.reservation
    pressure = admit_capacity(
        build_capacity_snapshot(
            identity,
            [_node("node:pressure", utilization=90)],
            source="deterministic_fixture",
            observed_at="2026-10-08T00:00:00Z",
            expires_at="2026-10-08T00:01:00Z",
        ),
        request,
        evaluated_at="2026-10-08T00:00:30Z",
    )
    stale = admit_capacity(snapshot, request, evaluated_at="2026-10-08T00:02:00Z")
    conflict = (
        admit_capacity(
            build_capacity_snapshot(
                identity,
                [_node("node:preferred", utilization=20)],
                source="deterministic_fixture",
                observed_at="2026-10-08T00:00:00Z",
                expires_at="2026-10-08T00:01:00Z",
            ),
            replace(request, rollout_id="rollout:generation:3", exclusive=True),
            evaluated_at="2026-10-08T00:00:30Z",
            reservations=[reservation] if reservation else [],
        )
        if reservation
        else pressure
    )
    released = reservation.release() if reservation else None
    checks = {
        "capacity_admitted": admitted.status == "ADMITTED",
        "deterministic_node_selected": reservation is not None and reservation.node_id == "node:preferred",
        "reservation_identity_bound": reservation is not None and reservation.identity_fingerprint == identity.fingerprint,
        "pressure_blocks": pressure.reason == "capacity_gpu_utilization_pressure",
        "stale_snapshot_blocks": stale.reason == "capacity_snapshot_stale",
        "exclusive_conflict_blocks": conflict.reason == "capacity_exclusive_conflict",
        "release_is_explicit": released is not None and released.state == "RELEASED",
        "no_overcommit_after_reservation": reservation is not None and reservation.gpu_count == 1,
        "decision_is_payload_free": "model_name" not in admitted.to_wire() and "endpoint" not in admitted.to_wire(),
        "blocked_decisions_have_no_reservation": pressure.reservation is None and stale.reservation is None,
    }
    passed = all(checks.values())
    return {
        "schema_version": "s147_gpu_capacity_admission.v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "node_count": len(snapshot.nodes),
            "admitted_count": int(admitted.status == "ADMITTED"),
            "blocked_count": sum(item.status == "BLOCKED" for item in (pressure, stale, conflict)),
            "released_count": int(released is not None and released.state == "RELEASED"),
            "check_count": len(checks),
        },
        "next_slice": "1466" if passed else "blocked",
    }


def _identity() -> ModelRevisionIdentity:
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


def _node(node_id: str, *, utilization: float) -> GpuNodeCapacity:
    return GpuNodeCapacity(
        node_id=node_id,
        accelerator_type="nvidia-gpu",
        gpu_count=2,
        allocatable_gpu_count=2,
        memory_total_mib=100_000,
        memory_reserved_mib=20_000,
        active_requests=2,
        queue_depth=1,
        gpu_utilization_percent=utilization,
        gpu_temperature_c=55,
        health_status="HEALTHY",
    )


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    return (
        f"gpu_capacity_admission={str(result.get('status') or 'FAIL').lower()} "
        f"nodes={summary.get('node_count', 0)} "
        f"admitted={summary.get('admitted_count', 0)} "
        f"blocked={summary.get('blocked_count', 0)} "
        f"released={summary.get('released_count', 0)} "
        f"checks={summary.get('check_count', 0)}/10 "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gpu_capacity_admission()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
