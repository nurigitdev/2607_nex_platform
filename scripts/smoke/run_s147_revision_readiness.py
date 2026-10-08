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
from nex_mo.model_rollout_readiness import evaluate_revision_readiness
from nex_mo.provider_readiness import ProviderRouteHealth
from nex_mo.runtime_observability import ModelRuntimeObservation

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def run_revision_readiness() -> dict[str, Any]:
    ready = []
    for capability in ("embedding", "reranking", "generation"):
        identity = _identity(capability)
        ready.append(
            evaluate_revision_readiness(
                identity,
                _route(identity),
                _runtime(identity),
                _capacity(identity),
                evaluated_at="2026-10-08T00:00:30Z",
                require_live=True,
            )
        )
    mismatch_identity = _identity("reranking")
    mismatch = evaluate_revision_readiness(
        mismatch_identity,
        replace(_route(mismatch_identity), model_revision="revision:unexpected"),
        _runtime(mismatch_identity),
        _capacity(mismatch_identity),
        evaluated_at="2026-10-08T00:00:30Z",
        require_live=True,
    )
    stale_identity = _identity("generation")
    stale = evaluate_revision_readiness(
        stale_identity,
        replace(_route(stale_identity), checked_at="2026-10-07T23:00:00Z"),
        _runtime(stale_identity),
        _capacity(stale_identity),
        evaluated_at="2026-10-08T00:00:30Z",
        require_live=True,
    )
    checks = {
        "three_capabilities_ready": len(ready) == 3 and all(item["status"] == "READY" for item in ready),
        "provider_identity_exact": all(item["checks"]["provider_identity_matches"] for item in ready),
        "runtime_identity_exact": all(item["checks"]["runtime_identity_matches"] for item in ready),
        "provider_health_required": all(item["checks"]["provider_route_ready"] for item in ready),
        "runtime_health_required": all(item["checks"]["runtime_healthy"] for item in ready),
        "capacity_reservation_required": all(item["checks"]["capacity_identity_matches"] for item in ready),
        "live_sources_required": all(
            item["checks"]["provider_source_admitted"] and item["checks"]["runtime_source_admitted"]
            for item in ready
        ),
        "mismatch_blocks": mismatch["status"] == "BLOCKED" and "provider_identity_matches" in mismatch["failure_checks"],
        "stale_evidence_blocks": stale["status"] == "BLOCKED" and "provider_evidence_fresh" in stale["failure_checks"],
        "evidence_is_digest_bound": all(item["evidence_digest"].startswith("sha256:") for item in ready),
        "evidence_is_payload_free": all("endpoint" not in item["evidence"] and "model_name" not in item["evidence"] for item in ready),
        "blocked_state_has_failure_code": mismatch["failure_code"] == "revision_readiness_blocked",
    }
    passed = all(checks.values())
    return {
        "schema_version": "s147_revision_readiness.v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "capability_count": len(ready),
            "ready_count": sum(item["status"] == "READY" for item in ready),
            "blocked_count": sum(item["status"] == "BLOCKED" for item in (mismatch, stale)),
            "check_count": len(checks),
        },
        "next_slice": "1467" if passed else "blocked",
    }


def _identity(capability: str) -> ModelRevisionIdentity:
    return ModelRevisionIdentity(
        provider_capability=capability,
        alias=f"{capability}-default",
        catalog_id=f"catalog:{capability}:r2",
        model_revision=f"revision:{capability}:2",
        deployment_id=f"deployment:{capability}:2",
        artifact_digest=DIGEST_A,
        runtime_engine="openai-compatible",
        precision="bfloat16",
        request_shape_hash=DIGEST_B,
    )


def _route(identity: ModelRevisionIdentity) -> ProviderRouteHealth:
    return ProviderRouteHealth(
        provider_capability=identity.provider_capability,
        alias=identity.alias,
        route_id=f"route:{identity.provider_capability}:2",
        deployment_id=identity.deployment_id,
        model_revision=identity.model_revision,
        status="READY",
        source="active_preflight",
        checked_at="2026-10-08T00:00:00Z",
    )


def _runtime(identity: ModelRevisionIdentity) -> ModelRuntimeObservation:
    return ModelRuntimeObservation(
        provider_capability=identity.provider_capability,
        alias=identity.alias,
        deployment_id=identity.deployment_id,
        model_revision=identity.model_revision,
        runtime_status="HEALTHY",
        precision_status="MATCH",
        requested_dtype="bfloat16",
        loaded_dtype="bfloat16",
        process_count=1,
        gpu_count=1,
        gpu_memory_used_mib=10_000,
        gpu_memory_total_mib=100_000,
        gpu_utilization_percent=20,
        gpu_temperature_c=50,
        source="protected_ssh",
        observed_at="2026-10-08T00:00:00Z",
    )


def _capacity(identity: ModelRevisionIdentity):
    snapshot = build_capacity_snapshot(
        identity,
        [
            GpuNodeCapacity(
                node_id=f"node:{identity.provider_capability}",
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
            rollout_id=f"rollout:{identity.provider_capability}:2",
            identity_fingerprint=identity.fingerprint,
            required_gpu_count=1,
            required_memory_mib=20_000,
            requested_concurrency=2,
        ),
        evaluated_at="2026-10-08T00:00:30Z",
    )


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    return (
        f"revision_readiness={str(result.get('status') or 'FAIL').lower()} "
        f"capabilities={summary.get('capability_count', 0)} "
        f"ready={summary.get('ready_count', 0)} "
        f"blocked={summary.get('blocked_count', 0)} "
        f"checks={summary.get('check_count', 0)}/12 "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_revision_readiness()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
