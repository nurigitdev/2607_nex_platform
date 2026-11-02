#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))

from nex_runtime import (
    admit_model_calibration_dataset_v2,
    admit_model_calibration_package_dataset_v3,
)
from nex_runtime.semantic_hashes import sha256_text

DEFAULT_V1_PATH = ROOT / "scripts/smoke/data/s136_reranker_calibration_v1.json"
DEFAULT_V2_PATH = ROOT / "scripts/smoke/data/s136_reranker_calibration_v2.json"
DEFAULT_V3_PATH = ROOT / "scripts/smoke/data/s136_retrieval_package_calibration_v3.json"
FROZEN_V1_FILE_SHA256 = (
    "743bee364a8f576b857380d3e6f0dffb45bcc4dc007a02b4ece698bbf73df205"
)
FROZEN_V2_FILE_SHA256 = (
    "b46de76d4225307c50966b22188e5fff4859592d2d350ae3c1c3a8058409b907"
)
FROZEN_V2_DATASET_SHA256 = (
    "a59c47a2401004897ab5f03cd911f76aee09e81d3df9c59d799b553175665899"
)
FROZEN_V3_FILE_SHA256 = (
    "5f79912782bb4f7c672894d1b5be445b958f93a5fb044730dc72b643a8bcb8c4"
)
FROZEN_V3_DATASET_SHA256 = (
    "edde3040ef27adf2ae450cc3c2193a0900620e2e514dc372a31ebe57085b34fb"
)


def admit_calibration_dataset_files(
    *,
    v1_path: Path = DEFAULT_V1_PATH,
    v2_path: Path = DEFAULT_V2_PATH,
    v3_path: Path = DEFAULT_V3_PATH,
) -> dict[str, Any]:
    v1_text = v1_path.read_text(encoding="utf-8")
    v1_sha256 = sha256_text(v1_text)
    if v1_sha256 != FROZEN_V1_FILE_SHA256:
        raise ValueError("frozen v1 calibration dataset digest mismatch")

    v2_text = v2_path.read_text(encoding="utf-8")
    if sha256_text(v2_text) != FROZEN_V2_FILE_SHA256:
        raise ValueError("frozen v2 calibration dataset file digest mismatch")
    v2_admitted = admit_model_calibration_dataset_v2(json.loads(v2_text))
    if v2_admitted.manifest["dataset_sha256"] != FROZEN_V2_DATASET_SHA256:
        raise ValueError("frozen v2 calibration dataset digest mismatch")

    v3_text = v3_path.read_text(encoding="utf-8")
    if sha256_text(v3_text) != FROZEN_V3_FILE_SHA256:
        raise ValueError("frozen v3 calibration dataset file digest mismatch")
    v3_admitted = admit_model_calibration_package_dataset_v3(json.loads(v3_text))
    if v3_admitted.manifest["dataset_sha256"] != FROZEN_V3_DATASET_SHA256:
        raise ValueError("frozen v3 calibration dataset digest mismatch")
    return {
        "status": "PASS",
        "v1": {
            "dataset_id": "s136-reranker-relevance-public-v1",
            "file_sha256": v1_sha256,
            "immutable": True,
        },
        "v2": {
            **v2_admitted.manifest,
            "file_sha256": FROZEN_V2_FILE_SHA256,
            "immutable": True,
        },
        "v3": {
            **v3_admitted.manifest,
            "file_sha256": FROZEN_V3_FILE_SHA256,
            "immutable": True,
        },
    }


def summary_line(result: dict[str, Any]) -> str:
    v2 = result["v2"]
    v3 = result["v3"]
    return (
        f"model_calibration_dataset_admission={result['status'].lower()} "
        f"v2_queries={v2['query_count']} v2_pairs={v2['pair_count']} "
        f"v3_scenarios={v3['scenario_count']} "
        f"v3_packages={v3['package_count']} "
        f"v3_candidates={v3['candidate_count']} "
        f"v3_sha256={v3['dataset_sha256']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify and admit the frozen v1, v2, and v3 datasets."
    )
    parser.add_argument("--v1", type=Path, default=DEFAULT_V1_PATH)
    parser.add_argument("--v2", type=Path, default=DEFAULT_V2_PATH)
    parser.add_argument("--v3", type=Path, default=DEFAULT_V3_PATH)
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = admit_calibration_dataset_files(
            v1_path=args.v1,
            v2_path=args.v2,
            v3_path=args.v3,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
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
