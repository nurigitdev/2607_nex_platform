#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))

from nex_runtime import admit_model_calibration_dataset_v2  # noqa: E402
from nex_runtime.semantic_hashes import sha256_text  # noqa: E402


DEFAULT_V1_PATH = ROOT / "scripts/smoke/data/s136_reranker_calibration_v1.json"
DEFAULT_V2_PATH = ROOT / "scripts/smoke/data/s136_reranker_calibration_v2.json"
FROZEN_V1_FILE_SHA256 = (
    "743bee364a8f576b857380d3e6f0dffb45bcc4dc007a02b4ece698bbf73df205"
)
FROZEN_V2_DATASET_SHA256 = (
    "a59c47a2401004897ab5f03cd911f76aee09e81d3df9c59d799b553175665899"
)


def admit_calibration_dataset_files(
    *,
    v1_path: Path = DEFAULT_V1_PATH,
    v2_path: Path = DEFAULT_V2_PATH,
) -> dict[str, Any]:
    v1_text = v1_path.read_text(encoding="utf-8")
    v1_sha256 = sha256_text(v1_text)
    if v1_sha256 != FROZEN_V1_FILE_SHA256:
        raise ValueError("frozen v1 calibration dataset digest mismatch")

    payload = json.loads(v2_path.read_text(encoding="utf-8"))
    admitted = admit_model_calibration_dataset_v2(payload)
    if admitted.manifest["dataset_sha256"] != FROZEN_V2_DATASET_SHA256:
        raise ValueError("frozen v2 calibration dataset digest mismatch")
    return {
        "status": "PASS",
        "v1": {
            "dataset_id": "s136-reranker-relevance-public-v1",
            "file_sha256": v1_sha256,
            "immutable": True,
        },
        "v2": admitted.manifest,
    }


def summary_line(result: dict[str, Any]) -> str:
    v2 = result["v2"]
    return (
        f"model_calibration_dataset_admission={result['status'].lower()} "
        f"dataset_id={v2['dataset_id']} queries={v2['query_count']} "
        f"pairs={v2['pair_count']} sha256={v2['dataset_sha256']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the frozen v1 and admit the v2 calibration dataset."
    )
    parser.add_argument("--v1", type=Path, default=DEFAULT_V1_PATH)
    parser.add_argument("--v2", type=Path, default=DEFAULT_V2_PATH)
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = admit_calibration_dataset_files(v1_path=args.v1, v2_path=args.v2)
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
