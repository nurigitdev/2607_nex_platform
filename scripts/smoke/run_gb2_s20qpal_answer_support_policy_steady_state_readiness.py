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

from nex_cx.retrieval_answer_support_policy_steady_state_readiness import (
    PolicySteadyStateReadinessError,
    decide_policy_steady_state_operations_readiness,
)

SCHEMA_VERSION = "gb2_s20qpal_answer_support_policy_steady_state_readiness.v1"
SMOKE_ENV = "NEX_GB2_S20QPAL_POLICY_STEADY_STATE_READINESS"
REPORT_ENV = "NEX_GB2_S20QPAL_REVIEW_REPORT_PATH"
RECEIPT_ENV = "NEX_GB2_S20QPAL_REVIEW_RECEIPT_PATH"
DESIGN_ENV = "NEX_GB2_S20QPAL_READINESS_DESIGN_PATH"

REVIEW_REPORT_PATH = (
    ROOT
    / "reports/live/"
    "gb2_ca00_s20qpak_answer_support_policy_sustained_operations_"
    "operator_review.json"
)
REVIEW_RECEIPT_PATH = (
    ROOT
    / "reports/live/"
    "gb2_ca00_s20qpak_answer_support_policy_sustained_operations_"
    "operator_review_receipt.json"
)
DESIGN_PATH = (
    ROOT
    / "scripts/smoke/data/"
    "s136_answer_support_policy_steady_state_readiness_v1_design.json"
)
OUTPUT_PATH = (
    ROOT
    / "reports/live/"
    "gb2_ca00_s20qpal_answer_support_policy_steady_state_readiness.json"
)


def run_gb2_s20qpal_answer_support_policy_steady_state_readiness(
    environ: Mapping[str, str] | None = None,
    *,
    review_report_path: Path | None = None,
    review_receipt_path: Path | None = None,
    design_path: Path | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    report_path = review_report_path or Path(
        env.get(REPORT_ENV, str(REVIEW_REPORT_PATH))
    )
    receipt_path = review_receipt_path or Path(
        env.get(RECEIPT_ENV, str(REVIEW_RECEIPT_PATH))
    )
    policy_path = design_path or Path(env.get(DESIGN_ENV, str(DESIGN_PATH)))
    try:
        if receipt_path.stat().st_mode & 0o077:
            raise PermissionError(
                "operator review receipt must not be group/world accessible"
            )
        manifest = decide_policy_steady_state_operations_readiness(
            _load(report_path),
            _load(receipt_path),
            design=_load(policy_path),
        )
    except (
        PolicySteadyStateReadinessError,
        json.JSONDecodeError,
        OSError,
        PermissionError,
        TypeError,
        ValueError,
    ) as exc:
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice_id": "GB2-CA00-S20Q-P-AL",
            "status": "FAIL",
            "failure_code": getattr(exc, "error_code", "readiness_evidence_invalid"),
            "failure_type": exc.__class__.__name__,
            "provider_calls": 0,
            "database_calls": 0,
            "holdout_accessed": False,
            "runtime_change_permitted": False,
            "steady_state_activation_permitted": False,
            "production_cutover_permitted": False,
        }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-AL",
        "status": "PASS",
        **manifest,
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("readiness evidence must be a JSON object")
    return value


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        profile = result.get("operations_profile")
        profile = profile if isinstance(profile, Mapping) else {}
        return (
            "gb2_s20qpal_policy_steady_state_readiness=pass "
            f"decision={result.get('decision')} "
            f"activation={result.get('activation_status')} "
            f"profile={profile.get('status')} "
            f"next={result.get('next_boundary')}"
        )
    if status == "skipped":
        return "gb2_s20qpal_policy_steady_state_readiness=skipped"
    return (
        "gb2_s20qpal_policy_steady_state_readiness=fail "
        f"reason={result.get('failure_code', 'readiness_evidence_invalid')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpal_answer_support_policy_steady_state_readiness()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
