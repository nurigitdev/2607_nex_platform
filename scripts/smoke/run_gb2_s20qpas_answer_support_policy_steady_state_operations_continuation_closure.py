#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_answer_support_policy_steady_state_continuation_closure import (
    build_policy_steady_state_continuation_closure,
)

SCHEMA_VERSION = (
    "gb2_s20qpas_answer_support_policy_steady_state_operations_continuation_closure.v1"
)
SMOKE_ENV = "NEX_GB2_S20QPAS_POLICY_STEADY_STATE_CONTINUATION_CLOSURE"
REPORT_ENV = "NEX_GB2_S20QPAS_OPERATOR_REVIEW_REPORT_PATH"
RECEIPT_ENV = "NEX_GB2_S20QPAS_OPERATOR_REVIEW_RECEIPT_PATH"

DESIGN_PATH = (
    ROOT / "scripts/smoke/data/"
    "s136_answer_support_policy_steady_state_continuation_closure_v1_design.json"
)
OPERATOR_REVIEW_REPORT_PATH = (
    ROOT / "reports/live/"
    "gb2_ca00_s20qpar_answer_support_policy_steady_state_operations_"
    "continuation_operator_review.json"
)
OPERATOR_REVIEW_RECEIPT_PATH = (
    ROOT / "reports/live/"
    "gb2_ca00_s20qpar_answer_support_policy_steady_state_operations_"
    "continuation_operator_review_receipt.json"
)
OUTPUT_PATH = (
    ROOT / "reports/live/"
    "gb2_ca00_s20qpas_answer_support_policy_steady_state_operations_"
    "continuation_closure.json"
)


def run_gb2_s20qpas_answer_support_policy_steady_state_continuation_closure(
    environ: Mapping[str, str] | None = None,
    *,
    design: Mapping[str, Any] | None = None,
    operator_review_report: Mapping[str, Any] | None = None,
    operator_review_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    try:
        closure = build_policy_steady_state_continuation_closure(
            design=dict(design or _load(DESIGN_PATH)),
            operator_review_report=dict(
                operator_review_report
                or _load_private(
                    Path(env.get(REPORT_ENV, str(OPERATOR_REVIEW_REPORT_PATH)))
                )
            ),
            operator_review_receipt=dict(
                operator_review_receipt
                or _load_private(
                    Path(env.get(RECEIPT_ENV, str(OPERATOR_REVIEW_RECEIPT_PATH)))
                )
            ),
        )
    except Exception as exc:  # noqa: BLE001 - protected closure boundary
        return _failure(
            "policy_steady_state_continuation_closure_failed",
            detail={"exception": exc.__class__.__name__},
        )
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-AS",
        **closure,
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("JSON document must be an object")
    return value


def _load_private(path: Path) -> dict[str, Any]:
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PermissionError(f"{path.name} must be owner-private")
    return _load(path)


def _write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-AS",
        "status": "FAIL",
        "failure_code": code,
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_changed": False,
        "rollback_contract_preserved": True,
        "production_cutover_permitted": False,
        "corrective_chain_closed": False,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        return (
            "gb2_s20qpas_policy_steady_state_continuation_closure=pass "
            f"decision={result.get('decision')} "
            f"baseline={result.get('baseline_status')} "
            f"next={result.get('next_boundary')}"
        )
    if status == "skipped":
        return "gb2_s20qpas_policy_steady_state_continuation_closure=skipped"
    return (
        "gb2_s20qpas_policy_steady_state_continuation_closure=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpas_answer_support_policy_steady_state_continuation_closure()
    if result.get("status") != "SKIPPED" or not args.output.exists():
        _write_private_json(args.output, result)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
