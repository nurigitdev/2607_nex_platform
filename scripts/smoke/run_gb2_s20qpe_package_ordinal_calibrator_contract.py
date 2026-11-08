#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_package_ready_calibrator import (
    build_package_ordinal_features,
    score_package_ordinal_features,
    validate_package_ordinal_calibrator_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

SCHEMA_VERSION = "gb2_s20qpe_package_ordinal_calibrator_contract.v1"
SMOKE_ENV = "NEX_GB2_S20QPE_PACKAGE_ORDINAL_CALIBRATOR_CONTRACT"
PROFILE_ENV = "NEX_GB2_S20QPE_PROFILE"
DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_package_ordinal_calibrator_v1_design.json"
)


def run_gb2_s20qpe_package_ordinal_calibrator_contract(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if env.get(PROFILE_ENV, "test") != "test":
        return _failure("profile_not_allowed")
    design = validate_package_ordinal_calibrator_design(
        json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    )
    ready_features = build_package_ordinal_features(_signal(ready=True))
    low_features = build_package_ordinal_features(_signal(ready=False))
    profile_results = []
    for profile in design["profile_shortlist"]:
        ready = score_package_ordinal_features(
            ready_features,
            profile=profile,
            design_hash=design["design_hash"],
        )
        low = score_package_ordinal_features(
            low_features,
            profile=profile,
            design_hash=design["design_hash"],
        )
        profile_results.append(
            {
                "profile_id": profile["profile_id"],
                "ready_score": ready["ordinal_score"],
                "low_confidence_score": low["ordinal_score"],
                "directional": ready["ordinal_score"] > low["ordinal_score"],
                "score_is_probability": ready["semantics"][
                    "score_is_probability"
                ],
            }
        )
    checks = {
        "design_frozen": design["status"] == "FROZEN_CALIBRATION_ONLY",
        "shortlist_is_finite": len(profile_results) == 4,
        "design_fixture_directional": all(
            row["directional"] for row in profile_results
        ),
        "score_not_claimed_as_probability": all(
            row["score_is_probability"] is False for row in profile_results
        ),
        "conditional_independence_removed": design["semantics"][
            "conditional_independence_assumption"
        ]
        is False,
        "holdout_access_prohibited": design["safety"][
            "holdout_access_permitted"
        ]
        is False,
        "runtime_activation_prohibited": design["safety"][
            "runtime_activation_permitted"
        ]
        is False,
    }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-E",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_opened": False,
        "design": design,
        "design_fixture": profile_results,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _signal(*, ready: bool) -> dict[str, Any]:
    probabilities = [0.90, 0.80, 0.20, 0.10] if ready else [
        0.40,
        0.30,
        0.20,
        0.10,
    ]
    expected_count = sum(probabilities)
    signal: dict[str, Any] = {
        "signal_schema_version": "cx_retrieval_package_ready_signal.v1",
        "policy_id": "cx_probability_at_least_two_relevant_v1",
        "status": "CALIBRATION_ONLY_PROJECTED",
        "source_profile_id": "fixture-v1",
        "candidate_probability_model_hash": "sha256:" + "a" * 64,
        "binding": {"dataset_id": "design-fixture"},
        "candidate_probabilities": [
            {
                "candidate_id": str(index),
                "candidate_score": probability,
                "relevance_probability": probability,
            }
            for index, probability in enumerate(probabilities)
        ],
        "relevant_count_probability": {},
        "features": {
            "ready_probability_at_least_two": 0.5 if ready else 0.1,
            "expected_relevant_count": expected_count,
            "second_candidate_probability": probabilities[1],
            "top_two_probability_mean": sum(probabilities[:2]) / 2,
            "second_third_probability_gap": probabilities[1] - probabilities[2],
            "candidate_probability_spread": probabilities[0] - probabilities[-1],
            "probability_at_least_half_count": sum(p >= 0.5 for p in probabilities),
            "historical_second_highest_candidate_score": probabilities[1],
        },
        "semantics": {},
        "safety": {},
    }
    signal["signal_hash"] = semantic_sha256_hash_ref(signal)
    return signal


def _failure(code: str) -> dict[str, Any]:
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        return (
            "gb2_s20qpe_package_ordinal_calibrator_contract=pass "
            "profiles=4 holdout=sealed runtime=disabled"
        )
    if status == "skipped":
        return "gb2_s20qpe_package_ordinal_calibrator_contract=skipped"
    return (
        "gb2_s20qpe_package_ordinal_calibrator_contract=fail "
        f"checks={','.join(result.get('failed_checks', [])) or result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpe_package_ordinal_calibrator_contract()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"{json.dumps(result, indent=2, sort_keys=True)}\n",
            encoding="utf-8",
        )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
