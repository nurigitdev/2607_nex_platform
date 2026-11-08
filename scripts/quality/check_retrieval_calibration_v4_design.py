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

from nex_cx.retrieval_calibration_design import (
    RetrievalCalibrationDesignError,
    admit_retrieval_calibration_v4_design,
)
from nex_runtime.semantic_hashes import sha256_text

DEFAULT_DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_retrieval_package_calibration_v4_design.json"
)
FROZEN_FILE_SHA256 = (
    "84cbde0665bc4bfa5218c5e363f026651bf57a16d850c9e10d7cdc16d36a2e24"
)
FROZEN_DESIGN_HASH = (
    "sha256:f467d2c7ba37e0b314add4961a573dad8a9f800db58762ba3644456352585a2a"
)


def check_retrieval_calibration_v4_design(
    path: Path = DEFAULT_DESIGN_PATH,
) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    file_sha256 = sha256_text(text)
    if file_sha256 != FROZEN_FILE_SHA256:
        raise ValueError("frozen retrieval calibration v4 design file digest mismatch")
    admitted = admit_retrieval_calibration_v4_design(json.loads(text))
    if admitted.manifest["design_hash"] != FROZEN_DESIGN_HASH:
        raise ValueError("frozen retrieval calibration v4 semantic digest mismatch")
    return {
        **admitted.manifest,
        "design_status": admitted.manifest["status"],
        "status": "PASS",
        "file_sha256": file_sha256,
        "immutable": True,
    }


def summary_line(result: dict[str, Any]) -> str:
    return (
        f"retrieval_calibration_v4_design={result['status'].lower()} "
        f"scenarios={result['scenario_count']} "
        f"calibration={result['calibration_scenario_count']} "
        f"holdout={result['holdout_scenario_count']} "
        f"profiles={len(result['profile_ids'])} "
        f"design_hash={result['design_hash']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the frozen retrieval calibration dataset v4 design."
    )
    parser.add_argument("--design", type=Path, default=DEFAULT_DESIGN_PATH)
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = check_retrieval_calibration_v4_design(args.design)
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        RetrievalCalibrationDesignError,
    ) as exc:
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
