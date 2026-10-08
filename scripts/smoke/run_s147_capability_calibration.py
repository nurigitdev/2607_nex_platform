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

from nex_mo.model_rollout import ModelRevisionIdentity
from nex_mo.model_rollout_calibration import (
    activate_calibration_profile,
    evaluate_calibration_profile,
    retire_calibration_profile,
    select_active_calibration_profile,
)

DIGESTS = ["sha256:" + char * 64 for char in "abcde"]
METRICS = {
    "embedding": {
        "vector_valid_rate": 1.0,
        "repeatability_rate": 0.995,
        "retrieval_quality_score": 0.85,
    },
    "reranking": {
        "ranking_quality_score": 0.9,
        "ready_recall": 0.9,
        "false_ready_rate": 0.05,
    },
    "generation": {
        "response_contract_rate": 1.0,
        "grounded_quality_score": 0.9,
        "error_rate": 0.01,
    },
}


def run_capability_calibration() -> dict[str, Any]:
    active = []
    for capability, capability_metrics in METRICS.items():
        model = _identity(capability, "2")
        candidate = _profile(model, capability_metrics)
        active.append(
            activate_calibration_profile(
                candidate,
                model,
                {"status": "READY", "identity_fingerprint": model.fingerprint},
                activated_at="2026-10-08T01:00:00Z",
            )
        )
    selections = [
        select_active_calibration_profile(
            [profile],
            _identity(profile.provider_capability, "2"),
            evaluated_at="2026-10-08T02:00:00Z",
        )
        for profile in active
    ]
    rejected = _profile(
        _identity("generation", "3"),
        {**METRICS["generation"], "error_rate": 0.2},
    )
    changed = _identity("reranking", "3")
    changed_selection = select_active_calibration_profile(
        active,
        changed,
        evaluated_at="2026-10-08T02:00:00Z",
    )
    retired = retire_calibration_profile(active[0])
    checks = {
        "three_capabilities_calibrated": len(active) == 3 and all(item.status == "ACTIVE" for item in active),
        "embedding_metrics_bound": dict(active[0].metrics) == METRICS["embedding"],
        "reranking_metrics_bound": dict(active[1].metrics) == METRICS["reranking"],
        "generation_metrics_bound": dict(active[2].metrics) == METRICS["generation"],
        "active_profiles_selected": all(item["status"] == "CALIBRATED" for item in selections),
        "profile_hashes_bound": all(item["profile_hash"].startswith("sha256:") for item in selections),
        "quality_failure_rejected": rejected.status == "REJECTED" and rejected.failed_metrics == ("error_rate",),
        "revision_change_requires_calibration": changed_selection["status"] == "CALIBRATION_REQUIRED",
        "retirement_is_explicit": retired.status == "RETIRED",
        "dataset_feature_policy_hashes_bound": all(
            profile.dataset_hash == DIGESTS[2]
            and profile.feature_schema_hash == DIGESTS[3]
            and profile.policy_hash == DIGESTS[4]
            for profile in active
        ),
        "sample_floor_enforced": all(profile.sample_count == 20 for profile in active),
        "profiles_are_payload_free": all("model_name" not in profile.to_wire() and "endpoint" not in profile.to_wire() for profile in active),
    }
    passed = all(checks.values())
    return {
        "schema_version": "s147_capability_calibration.v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "capability_count": len(active),
            "active_count": sum(profile.status == "ACTIVE" for profile in active),
            "rejected_count": int(rejected.status == "REJECTED"),
            "recalibration_required_count": int(changed_selection["status"] == "CALIBRATION_REQUIRED"),
            "check_count": len(checks),
        },
        "next_slice": "1468" if passed else "blocked",
    }


def _identity(capability: str, revision: str) -> ModelRevisionIdentity:
    return ModelRevisionIdentity(
        provider_capability=capability,
        alias=f"{capability}-default",
        catalog_id=f"catalog:{capability}:r{revision}",
        model_revision=f"revision:{capability}:{revision}",
        deployment_id=f"deployment:{capability}:{revision}",
        artifact_digest=DIGESTS[0],
        runtime_engine="openai-compatible",
        precision="bfloat16",
        request_shape_hash=DIGESTS[1],
    )


def _profile(model: ModelRevisionIdentity, metrics: Mapping[str, float]):
    return evaluate_calibration_profile(
        model,
        profile_id=f"calibration:{model.provider_capability}:{model.model_revision.rsplit(':', 1)[-1]}",
        dataset_hash=DIGESTS[2],
        feature_schema_hash=DIGESTS[3],
        policy_hash=DIGESTS[4],
        sample_count=20,
        metrics=metrics,
        evaluated_at="2026-10-08T00:00:00Z",
        expires_at="2026-10-09T00:00:00Z",
    )


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    return (
        f"capability_calibration={str(result.get('status') or 'FAIL').lower()} "
        f"capabilities={summary.get('capability_count', 0)} "
        f"active={summary.get('active_count', 0)} "
        f"rejected={summary.get('rejected_count', 0)} "
        f"recalibration={summary.get('recalibration_required_count', 0)} "
        f"checks={summary.get('check_count', 0)}/12 "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_capability_calibration()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
