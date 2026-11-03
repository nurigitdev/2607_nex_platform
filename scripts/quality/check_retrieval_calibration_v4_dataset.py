#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_calibration_folds import (
    build_retrieval_calibration_nested_fold_plan,
)
from nex_runtime import admit_model_calibration_package_dataset_v4
from nex_runtime.semantic_hashes import sha256_text

DEFAULT_DATASET_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_retrieval_package_calibration_v4.json"
)
DEFAULT_FOLD_PLAN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_retrieval_package_calibration_v4_folds.json"
)
DEFAULT_DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_retrieval_package_calibration_v4_design.json"
)
DEFAULT_V3_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_retrieval_package_calibration_v3.json"
)
FROZEN_DATASET_FILE_SHA256 = (
    "a0be13e113efee2a4a2dd904aaab6d65916a4e31b4a71b91465b66210d9dea20"
)
FROZEN_DATASET_SHA256 = (
    "594209203d25b0a87e6fd136b6794bdc30058a5eb45b7e2c8ff27523bd7f1757"
)
FROZEN_FOLD_PLAN_FILE_SHA256 = (
    "f38fdcd955d07b6d1692dca2a8cdf7c22a2fdffe1ce7d5206a780aa2297d2720"
)
FROZEN_FOLD_PLAN_HASH = (
    "sha256:6e01aa5792b3d18f67a39419a37622f9c8df6e8124e981b04151496180de4613"
)


def check_retrieval_calibration_v4_dataset(
    *,
    dataset_path: Path = DEFAULT_DATASET_PATH,
    fold_plan_path: Path = DEFAULT_FOLD_PLAN_PATH,
    design_path: Path = DEFAULT_DESIGN_PATH,
    v3_path: Path = DEFAULT_V3_PATH,
) -> dict[str, Any]:
    dataset_text = dataset_path.read_text(encoding="utf-8")
    dataset_file_sha256 = sha256_text(dataset_text)
    if dataset_file_sha256 != FROZEN_DATASET_FILE_SHA256:
        raise ValueError("frozen retrieval calibration v4 dataset file digest mismatch")
    dataset_payload = json.loads(dataset_text)
    admitted = admit_model_calibration_package_dataset_v4(dataset_payload)
    if admitted.manifest["dataset_sha256"] != FROZEN_DATASET_SHA256:
        raise ValueError("frozen retrieval calibration v4 semantic digest mismatch")

    v3_payload = json.loads(v3_path.read_text(encoding="utf-8"))
    _require_v3_calibration_continuity(v3_payload, admitted.dataset)

    design_payload = json.loads(design_path.read_text(encoding="utf-8"))
    expected_fold_plan = build_retrieval_calibration_nested_fold_plan(
        admitted.dataset,
        design_payload,
    )
    fold_text = fold_plan_path.read_text(encoding="utf-8")
    fold_file_sha256 = sha256_text(fold_text)
    if fold_file_sha256 != FROZEN_FOLD_PLAN_FILE_SHA256:
        raise ValueError("frozen retrieval calibration v4 fold file digest mismatch")
    stored_fold_plan = json.loads(fold_text)
    if stored_fold_plan != expected_fold_plan:
        raise ValueError("frozen retrieval calibration v4 fold materialization mismatch")
    if stored_fold_plan["fold_plan_hash"] != FROZEN_FOLD_PLAN_HASH:
        raise ValueError("frozen retrieval calibration v4 fold semantic digest mismatch")

    return {
        "status": "PASS",
        "dataset_id": admitted.manifest["dataset_id"],
        "dataset_file_sha256": dataset_file_sha256,
        "dataset_sha256": admitted.manifest["dataset_sha256"],
        "scenario_count": admitted.manifest["scenario_count"],
        "package_count": admitted.manifest["package_count"],
        "candidate_count": admitted.manifest["candidate_count"],
        "calibration_scenario_count": admitted.manifest[
            "partition_scenario_counts"
        ]["CALIBRATION"],
        "holdout_scenario_count": admitted.manifest["partition_scenario_counts"][
            "HOLDOUT"
        ],
        "scenario_review_count": admitted.manifest["scenario_review_count"],
        "independent_review_passed": admitted.manifest[
            "independent_review_passed"
        ],
        "v3_calibration_scenario_count": 30,
        "new_calibration_scenario_count": 50,
        "new_holdout_scenario_count": 20,
        "fold_plan_file_sha256": fold_file_sha256,
        "fold_plan_hash": stored_fold_plan["fold_plan_hash"],
        "outer_fold_count": stored_fold_plan["assignment"]["outer_fold_count"],
        "inner_fold_count": stored_fold_plan["assignment"]["inner_fold_count"],
        "holdout_excluded_from_folds": stored_fold_plan["checks"][
            "holdout_excluded"
        ],
        "runtime_activation_permitted": stored_fold_plan[
            "runtime_activation_permitted"
        ],
        "immutable": True,
    }


def _require_v3_calibration_continuity(
    v3_payload: dict[str, Any],
    v4_payload: dict[str, Any],
) -> None:
    v3_cases = {case["case_id"]: case for case in v3_payload["cases"]}
    v4_cases = {case["case_id"]: case for case in v4_payload["cases"]}
    v3_scenario_ids = {case["scenario_id"] for case in v3_cases.values()}
    holdout_scenario_ids = {
        case["scenario_id"]
        for case in v4_cases.values()
        if case["partition"] == "HOLDOUT"
    }
    if holdout_scenario_ids & v3_scenario_ids:
        raise ValueError("v4 holdout must not reuse a v3 scenario")
    for case_id, v3_case in v3_cases.items():
        if case_id not in v4_cases:
            raise ValueError("v3 calibration continuity case missing")
        expected = dict(v3_case)
        expected["partition"] = "CALIBRATION"
        expected["candidates"] = sorted(
            expected["candidates"], key=lambda item: item["candidate_id"]
        )
        if v4_cases[case_id] != expected:
            raise ValueError("v3 calibration continuity content mismatch")


def summary_line(result: dict[str, Any]) -> str:
    return (
        f"retrieval_calibration_v4_dataset={result['status'].lower()} "
        f"scenarios={result['scenario_count']} "
        f"calibration={result['calibration_scenario_count']} "
        f"holdout={result['holdout_scenario_count']} "
        f"packages={result['package_count']} "
        f"candidates={result['candidate_count']} "
        f"folds={result['outer_fold_count']}x{result['inner_fold_count']} "
        f"dataset_sha256={result['dataset_sha256']} "
        f"fold_plan_hash={result['fold_plan_hash']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the frozen retrieval calibration v4 dataset and folds."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--fold-plan", type=Path, default=DEFAULT_FOLD_PLAN_PATH)
    parser.add_argument("--design", type=Path, default=DEFAULT_DESIGN_PATH)
    parser.add_argument("--v3", type=Path, default=DEFAULT_V3_PATH)
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = check_retrieval_calibration_v4_dataset(
            dataset_path=args.dataset,
            fold_plan_path=args.fold_plan,
            design_path=args.design,
            v3_path=args.v3,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"status": "FAIL", "detail": type(exc).__name__},
                sort_keys=True,
            )
        )
        return 1
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
