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

from nex_cx.retrieval_confidence_candidate_diagnostics import (
    EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION,
)
from nex_cx.retrieval_package_ready_signal import (
    PACKAGE_READY_SIGNAL_POLICY_ID,
    build_package_ready_signal,
    fit_candidate_probability_model,
    score_candidate_relevance_samples,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

SCHEMA_VERSION = "gb2_s20qpb_candidate_probability_package_signal.v1"
SMOKE_ENV = "NEX_GB2_S20QPB_CANDIDATE_PROBABILITY_PACKAGE_SIGNAL"
PROFILE_ENV = "NEX_GB2_S20QPB_PROFILE"
BINDING = {
    "dataset_id": "s136-retrieval-package-confidence-v4",
    "partition": "CALIBRATION_DESIGN_FIXTURE",
    "profile_revision": "s20qpb-design-v1",
}
PROFILE = {
    "profile_id": "s20qpb-balanced-design-v1",
    "weights": [
        {"field": "reranker_score", "weight": 0.6},
        {"field": "rrf_normalized_score", "weight": 0.4},
    ],
}


def run_gb2_s20qpb_candidate_probability_package_signal(
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

    scored = score_candidate_relevance_samples(_design_samples(), profile=PROFILE)
    model = fit_candidate_probability_model(
        scored,
        source_profile_id=PROFILE["profile_id"],
        expected_binding=BINDING,
    )
    repeated = fit_candidate_probability_model(
        scored,
        source_profile_id=PROFILE["profile_id"],
        expected_binding=BINDING,
    )
    ready = build_package_ready_signal(
        _package(scored, "design-0:positive"),
        model=model,
        expected_binding=BINDING,
    )
    low = build_package_ready_signal(
        _package(scored, "design-0:negative"),
        model=model,
        expected_binding=BINDING,
    )
    ready_probability = float(
        ready["features"]["ready_probability_at_least_two"]
    )
    low_probability = float(low["features"]["ready_probability_at_least_two"])
    checks = {
        "candidate_probability_model_fitted": (
            model.get("status") == "CALIBRATION_ONLY_FITTED"
        ),
        "model_fit_deterministic": model == repeated,
        "package_policy_bound": ready.get("policy_id")
        == PACKAGE_READY_SIGNAL_POLICY_ID,
        "ready_probability_directional": ready_probability > low_probability,
        "ready_semantics_exact": (
            ready["semantics"]["ready_definition"]
            == "AT_LEAST_TWO_RELEVANT_CANDIDATES"
        ),
        "count_distribution_normalized": abs(
            sum(ready["relevant_count_probability"].values()) - 1.0
        )
        < 1e-9,
        "holdout_access_prohibited": (
            model["safety"]["holdout_access_permitted"] is False
            and ready["safety"]["holdout_access_permitted"] is False
        ),
        "runtime_activation_prohibited": (
            model["safety"]["runtime_activation_permitted"] is False
            and ready["safety"]["runtime_activation_permitted"] is False
        ),
        "ready_decision_deferred": (
            ready["semantics"]["package_threshold"] is None
            and ready["semantics"]["ready_decision"] is None
        ),
    }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-B",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "execution_scope": "CALIBRATION_ONLY_DESIGN_FIXTURE",
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_opened": False,
        "candidate_probability_model": model,
        "package_signal": {
            "policy_id": ready["policy_id"],
            "positive_ready_probability": ready_probability,
            "negative_ready_probability": low_probability,
            "positive_signal_hash": ready["signal_hash"],
            "negative_signal_hash": low["signal_hash"],
        },
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _design_samples() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in range(2):
        for label, scores in (
            ("positive", (0.90, 0.80, 0.20, 0.10)),
            ("negative", (0.45, 0.35, 0.25, 0.15)),
        ):
            ready = label == "positive"
            for index, score in enumerate(scores):
                sample = {
                    "sample_schema_version": (
                        EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION
                    ),
                    "sample_id": f"design-{scenario}:{label}",
                    "candidate_id": f"{scenario}-{label}-{index}",
                    "expected_ready": ready,
                    "expected_relevant": ready and index < 2,
                    "signals": {
                        "reranker_score": score,
                        "rrf_normalized_score": score,
                        "channel_rank_quality": score,
                        "bm25_score_quality": score,
                        "vector_similarity_quality": score,
                    },
                }
                sample["sample_hash"] = semantic_sha256_hash_ref(sample)
                rows.append(sample)
    return rows


def _package(
    scored: list[dict[str, Any]], sample_id: str
) -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": row["candidate_id"],
            "candidate_score": row["candidate_score"],
        }
        for row in scored
        if row["sample_id"] == sample_id
    ]


def _failure(code: str) -> dict[str, Any]:
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        signal = result["package_signal"]
        return (
            "gb2_s20qpb_candidate_probability_package_signal=pass "
            f"positive={signal['positive_ready_probability']:.6f} "
            f"negative={signal['negative_ready_probability']:.6f} "
            "holdout=sealed runtime=disabled"
        )
    if status == "skipped":
        return "gb2_s20qpb_candidate_probability_package_signal=skipped"
    return (
        "gb2_s20qpb_candidate_probability_package_signal=fail "
        f"checks={','.join(result.get('failed_checks', [])) or result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpb_candidate_probability_package_signal()
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
