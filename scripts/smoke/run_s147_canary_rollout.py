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

from nex_mo.model_capacity_scheduler import CapacityReservation
from nex_mo.model_rollout import ModelRevisionIdentity
from nex_mo.model_rollout_state import (
    CanaryMetrics,
    CanaryPolicy,
    begin_validation,
    evaluate_canary,
    mark_rollout_ready,
    register_rollout,
    start_canary,
)

DIGESTS = ["sha256:" + char * 64 for char in "abcdef"]


def run_canary_rollout() -> dict[str, Any]:
    model = _identity("2")
    record = register_rollout(
        model,
        rollout_id="rollout:generation:2",
        last_known_good_binding_id="binding:generation:1",
        last_known_good_identity_fingerprint=_identity("1").fingerprint,
        created_at="2026-10-08T00:00:00Z",
    )
    validating = begin_validation(record, changed_at="2026-10-08T00:01:00Z")
    ready = mark_rollout_ready(
        validating,
        {
            "status": "READY",
            "identity_fingerprint": model.fingerprint,
            "evidence_digest": DIGESTS[2],
        },
        {
            "status": "CALIBRATED",
            "identity_fingerprint": model.fingerprint,
            "profile_id": "calibration:generation:2",
            "profile_hash": DIGESTS[3],
        },
        CapacityReservation(
            reservation_id="reservation:generation:2",
            rollout_id=record.rollout_id,
            identity_fingerprint=model.fingerprint,
            node_id="node:one",
            gpu_count=1,
            memory_mib=20_000,
            concurrency=2,
            exclusive=False,
        ),
        changed_at="2026-10-08T00:02:00Z",
    )
    policy = CanaryPolicy(
        traffic_percent=10,
        observation_seconds=300,
        minimum_sample_count=100,
        maximum_error_rate=0.02,
        minimum_quality_score=0.85,
        maximum_p95_latency_ms=2_000,
    )
    canary = start_canary(ready, policy, changed_at="2026-10-08T00:03:00Z")
    passed_record, passed = evaluate_canary(
        canary,
        policy,
        _metrics(model),
        changed_at="2026-10-08T00:09:00Z",
    )
    blocked_record, blocked = evaluate_canary(
        canary,
        policy,
        replace(_metrics(model), error_rate=0.2),
        changed_at="2026-10-08T00:09:00Z",
    )
    states = [record.state, validating.state, ready.state, canary.state]
    checks = {
        "forward_states_exact": states == ["REGISTERED", "VALIDATING", "READY", "CANARY"],
        "candidate_differs_from_stable": record.identity.fingerprint != record.last_known_good_identity_fingerprint,
        "readiness_bound": ready.readiness_evidence_digest == DIGESTS[2],
        "calibration_bound": ready.calibration_profile_hash == DIGESTS[3],
        "reservation_bound": ready.reservation_id == "reservation:generation:2",
        "traffic_ceiling_bound": policy.traffic_percent == 10,
        "canary_policy_digest_bound": canary.canary_policy_hash == policy.policy_hash,
        "passing_canary_promotable": passed["promotable"] is True and passed_record.canary_status == "PASSED",
        "passing_canary_not_yet_active": passed_record.state == "CANARY",
        "failing_canary_blocked": blocked["promotable"] is False and blocked_record.state == "BLOCKED",
        "failure_code_bound": blocked_record.failure_code == "canary_budget_failed",
        "canary_evidence_payload_free": "model_name" not in passed and "endpoint" not in passed,
    }
    passed_all = all(checks.values())
    return {
        "schema_version": "s147_canary_rollout.v1",
        "status": "PASS" if passed_all else "FAIL",
        "checks": checks,
        "summary": {
            "state_count": len(states),
            "promotable_count": int(passed["promotable"]),
            "blocked_count": int(blocked_record.state == "BLOCKED"),
            "check_count": len(checks),
        },
        "next_slice": "1469" if passed_all else "blocked",
    }


def _identity(revision: str) -> ModelRevisionIdentity:
    return ModelRevisionIdentity(
        provider_capability="generation",
        alias="generation-default",
        catalog_id=f"catalog:generation:r{revision}",
        model_revision=f"revision:generation:{revision}",
        deployment_id=f"deployment:generation:{revision}",
        artifact_digest=DIGESTS[0],
        runtime_engine="vllm",
        precision="bfloat16",
        request_shape_hash=DIGESTS[1],
    )


def _metrics(model: ModelRevisionIdentity) -> CanaryMetrics:
    return CanaryMetrics(
        identity_fingerprint=model.fingerprint,
        sample_count=120,
        error_rate=0.01,
        quality_score=0.9,
        p95_latency_ms=1_500,
        observed_seconds=360,
        measured_at="2026-10-08T00:09:00Z",
    )


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    return (
        f"canary_rollout={str(result.get('status') or 'FAIL').lower()} "
        f"states={summary.get('state_count', 0)} "
        f"promotable={summary.get('promotable_count', 0)} "
        f"blocked={summary.get('blocked_count', 0)} "
        f"checks={summary.get('check_count', 0)}/12 "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_canary_rollout()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
