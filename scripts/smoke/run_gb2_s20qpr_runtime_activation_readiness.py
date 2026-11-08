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

from nex_cx.retrieval_answer_support_runtime_readiness import (
    AnswerSupportRuntimeReadinessError,
    decide_answer_support_runtime_readiness,
)

SCHEMA_VERSION = "gb2_s20qpr_runtime_activation_readiness.v1"
SMOKE_ENV = "NEX_GB2_S20QPR_RUNTIME_READINESS"
HOLDOUT_REPORT_PATH = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qpq_one_shot_holdout.json"
)
RECEIPT_PATH = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qpq_holdout_one_shot_receipt.json"
)
DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_answer_support_runtime_activation_readiness_v1_design.json"
)
OUTPUT_PATH = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qpr_runtime_activation_readiness.json"
)


def run_gb2_s20qpr_runtime_activation_readiness(
    environ: Mapping[str, str] | None = None,
    *,
    holdout_report_path: Path = HOLDOUT_REPORT_PATH,
    receipt_path: Path = RECEIPT_PATH,
    design_path: Path = DESIGN_PATH,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    try:
        if receipt_path.stat().st_mode & 0o077:
            raise PermissionError("HOLDOUT receipt must not be group/world accessible")
        manifest = decide_answer_support_runtime_readiness(
            _load(holdout_report_path),
            _load(receipt_path),
            design=_load(design_path),
        )
    except (
        AnswerSupportRuntimeReadinessError,
        json.JSONDecodeError,
        OSError,
        PermissionError,
        TypeError,
        ValueError,
    ) as exc:
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice_id": "GB2-CA00-S20Q-P-R",
            "status": "FAIL",
            "failure_code": getattr(exc, "error_code", "readiness_evidence_invalid"),
            "failure_type": exc.__class__.__name__,
            "runtime_activation_permitted": False,
            "holdout_reexecution_permitted": False,
            "new_provider_calls": 0,
            "new_database_calls": 0,
        }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-R",
        "status": "PASS",
        "manifest": manifest,
        "runtime_activation_permitted": False,
        "holdout_reexecution_permitted": False,
        "new_provider_calls": 0,
        "new_database_calls": 0,
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("readiness evidence must be a JSON object")
    return value


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        manifest = result.get("manifest")
        manifest = manifest if isinstance(manifest, Mapping) else {}
        return (
            "gb2_s20qpr_runtime_activation_readiness=pass "
            f"decision={manifest.get('decision')} "
            f"activation={manifest.get('activation_status')} "
            "holdout_reexecution=prohibited provider_calls=0 database_calls=0"
        )
    if status == "skipped":
        return "gb2_s20qpr_runtime_activation_readiness=skipped"
    return (
        "gb2_s20qpr_runtime_activation_readiness=fail "
        f"reason={result.get('failure_code', 'readiness_evidence_invalid')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpr_runtime_activation_readiness()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
