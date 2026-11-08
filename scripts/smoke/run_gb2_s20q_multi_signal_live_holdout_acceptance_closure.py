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

from nex_cx.retrieval_multisignal_holdout_acceptance_closure import (
    build_multisignal_holdout_acceptance_closure,
)

SCHEMA_VERSION = "gb2_s20q_multi_signal_live_holdout_acceptance_closure.v1"
SMOKE_ENV = "NEX_GB2_S20Q_HOLDOUT_ACCEPTANCE_CLOSURE"
RETRIEVAL_ENV = "NEX_GB2_S20Q_RETRIEVAL_LIVE_REPORT_PATH"
HOLDOUT_ENV = "NEX_GB2_S20Q_HOLDOUT_REPORT_PATH"
RECEIPT_ENV = "NEX_GB2_S20Q_HOLDOUT_RECEIPT_PATH"
OPERATIONS_ENV = "NEX_GB2_S20Q_OPERATIONS_CLOSURE_PATH"
MAINTENANCE_ENV = "NEX_GB2_S20Q_MAINTENANCE_REPORT_PATH"

DESIGN_PATH = (
    ROOT / "scripts/smoke/data/"
    "s136_multi_signal_live_holdout_acceptance_closure_v1_design.json"
)
RETRIEVAL_PATH = ROOT / "reports/live/gb2_ca00_s20qpa_vector_near_tie_ordering.json"
HOLDOUT_PATH = ROOT / "reports/live/gb2_ca00_s20qpq_one_shot_holdout.json"
RECEIPT_PATH = ROOT / "reports/live/gb2_ca00_s20qpq_holdout_one_shot_receipt.json"
OPERATIONS_PATH = (
    ROOT / "reports/live/"
    "gb2_ca00_s20qpas_answer_support_policy_steady_state_operations_"
    "continuation_closure.json"
)
MAINTENANCE_PATH = (
    ROOT / "reports/live/"
    "gb2_ca00_s20qpat_answer_support_policy_controlled_steady_state_"
    "baseline_maintenance.json"
)
OUTPUT_PATH = (
    ROOT / "reports/live/"
    "gb2_ca00_s20q_multi_signal_live_holdout_acceptance_closure.json"
)


def run_gb2_s20q_multi_signal_live_holdout_acceptance_closure(
    environ: Mapping[str, str] | None = None,
    *,
    design: Mapping[str, Any] | None = None,
    retrieval_live_report: Mapping[str, Any] | None = None,
    holdout_report: Mapping[str, Any] | None = None,
    holdout_receipt: Mapping[str, Any] | None = None,
    operations_closure_report: Mapping[str, Any] | None = None,
    maintenance_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    try:
        closure = build_multisignal_holdout_acceptance_closure(
            design=dict(_load(DESIGN_PATH) if design is None else design),
            retrieval_live_report=dict(
                _load(Path(env.get(RETRIEVAL_ENV, str(RETRIEVAL_PATH))))
                if retrieval_live_report is None
                else retrieval_live_report
            ),
            holdout_report=dict(
                _load(Path(env.get(HOLDOUT_ENV, str(HOLDOUT_PATH))))
                if holdout_report is None
                else holdout_report
            ),
            holdout_receipt=dict(
                _load_private(Path(env.get(RECEIPT_ENV, str(RECEIPT_PATH))))
                if holdout_receipt is None
                else holdout_receipt
            ),
            operations_closure_report=dict(
                _load_private(Path(env.get(OPERATIONS_ENV, str(OPERATIONS_PATH))))
                if operations_closure_report is None
                else operations_closure_report
            ),
            maintenance_report=dict(
                _load_private(Path(env.get(MAINTENANCE_ENV, str(MAINTENANCE_PATH))))
                if maintenance_report is None
                else maintenance_report
            ),
        )
    except Exception as exc:  # noqa: BLE001 - protected closure boundary
        return _failure(
            "multi_signal_live_holdout_acceptance_closure_failed",
            detail={"exception": exc.__class__.__name__},
        )
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q",
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
        "slice_id": "GB2-CA00-S20Q",
        "status": "FAIL",
        "failure_code": code,
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "holdout_reexecution_permitted": False,
        "runtime_changed": False,
        "production_cutover_permitted": False,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        return (
            "gb2_s20q_holdout_acceptance_closure=pass "
            f"decision={result.get('decision')} "
            f"closure={result.get('closure_status')} "
            f"next={result.get('next_boundary')}"
        )
    if status == "skipped":
        return "gb2_s20q_holdout_acceptance_closure=skipped"
    return (
        "gb2_s20q_holdout_acceptance_closure=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20q_multi_signal_live_holdout_acceptance_closure()
    if result.get("status") != "SKIPPED" or not args.output.exists():
        _write_private_json(args.output, result)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
