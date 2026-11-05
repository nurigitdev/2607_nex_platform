#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "quality",
):
    sys.path.insert(0, str(path))

from check_retrieval_calibration_v4_dataset import (
    check_retrieval_calibration_v4_dataset,
)
from nex_cx.retrieval_answer_support_holdout_freeze import (
    HOLDOUT_RECEIPT_PATH,
    freeze_holdout_one_shot_execution,
)

SCHEMA_VERSION = "gb2_s20qpp_pre_holdout_freeze.v1"
SMOKE_ENV = "NEX_GB2_S20QPP_PRE_HOLDOUT_FREEZE"
PROFILE_ENV = "NEX_GB2_S20QPP_PROFILE"
P_O_SOURCE_ENV = "NEX_GB2_S20QPP_P_O_EVIDENCE"
RECEIPT_PATH_ENV = "NEX_GB2_S20QPP_RECEIPT_PATH"
P_O_SOURCE_PATH = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qpo_canonical_threshold_admission.json"
)
DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_answer_support_holdout_one_shot_v1_design.json"
)
DEFAULT_RECEIPT_PATH = ROOT / HOLDOUT_RECEIPT_PATH
OUTPUT_PATH = ROOT / "reports" / "live" / "gb2_ca00_s20qpp_pre_holdout_freeze.json"

DatasetChecker = Callable[..., dict[str, Any]]
ReceiptLoader = Callable[[Path], Mapping[str, Any] | None]
Freezer = Callable[..., dict[str, Any]]


def run_gb2_s20qpp_pre_holdout_freeze(
    environ: Mapping[str, str] | None = None,
    *,
    p_o_source: Mapping[str, Any] | None = None,
    design: Mapping[str, Any] | None = None,
    dataset_checker: DatasetChecker = check_retrieval_calibration_v4_dataset,
    receipt_loader: ReceiptLoader | None = None,
    freezer: Freezer = freeze_holdout_one_shot_execution,
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
    try:
        source = (
            dict(p_o_source)
            if p_o_source is not None
            else _load(Path(env.get(P_O_SOURCE_ENV, str(P_O_SOURCE_PATH))))
        )
        design_value = dict(design) if design is not None else _load(DESIGN_PATH)
        dataset_manifest = dataset_checker()
        receipt_path = Path(
            env.get(RECEIPT_PATH_ENV, str(DEFAULT_RECEIPT_PATH))
        )
        existing_receipt = (
            receipt_loader(receipt_path)
            if receipt_loader is not None
            else _load_optional(receipt_path)
        )
        calibration = _mapping(source.get("calibration"), "P-O calibration")
        freeze = freezer(
            p_o_calibration=calibration,
            dataset_manifest=dataset_manifest,
            design=design_value,
            existing_receipt=existing_receipt,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failure(
            "pre_holdout_freeze_failed",
            detail={"exception": exc.__class__.__name__},
        )

    source_checks = _mapping(source.get("checks"), "P-O checks")
    authorization = _mapping(freeze.get("authorization"), "freeze authorization")
    protocol = _mapping(authorization.get("protocol"), "freeze protocol")
    receipt = _mapping(freeze.get("receipt_contract"), "receipt contract")
    checks = {
        "p_o_evidence_passed": source.get("status") == "PASS"
        and source.get("decision")
        == "CANONICAL_THRESHOLD_CANDIDATE_ADMITTED_HOLDOUT_REQUIRED",
        "p_o_checks_all_passed": bool(source_checks)
        and all(value is True for value in source_checks.values()),
        "dataset_v4_immutable_admission_passed": dataset_manifest.get("status")
        == "PASS"
        and dataset_manifest.get("immutable") is True,
        "one_shot_execution_armed": freeze.get("status")
        == "HOLDOUT_ONE_SHOT_EXECUTION_ARMED"
        and protocol.get("maximum_execution_attempts") == 1,
        "provider_request_budget_frozen": protocol.get(
            "expected_provider_evaluations"
        )
        == 40
        and protocol.get("maximum_provider_http_requests") == 40,
        "canonical_receipt_reserved": receipt.get("receipt_path")
        == HOLDOUT_RECEIPT_PATH
        and receipt.get("required_execution_id") == freeze.get("execution_id")
        and receipt.get("reservation_write_mode") == "ATOMIC_CREATE_EXCLUSIVE"
        and receipt.get("reservation_required_before_provider_call") is True,
        "holdout_not_executed": freeze.get("safety", {}).get(
            "holdout_executed_in_this_slice"
        )
        is False,
        "runtime_activation_prohibited": freeze.get(
            "runtime_activation_permitted"
        )
        is False,
        "provider_not_called": freeze.get("new_provider_calls") == 0,
        "database_not_called": freeze.get("new_database_calls") == 0,
    }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-P",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": "HOLDOUT_ONE_SHOT_EXECUTION_ARMED_P_Q_REQUIRED",
        "new_provider_calls": 0,
        "new_database_calls": 0,
        "freeze": freeze,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("evidence must be a JSON object")
    return value


def _load_optional(path: Path) -> dict[str, Any] | None:
    return _load(path) if path.is_file() else None


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        freeze = result.get("freeze")
        freeze = freeze if isinstance(freeze, Mapping) else {}
        authorization = freeze.get("authorization")
        authorization = authorization if isinstance(authorization, Mapping) else {}
        candidate = authorization.get("candidate")
        candidate = candidate if isinstance(candidate, Mapping) else {}
        return (
            "gb2_s20qpp_pre_holdout_freeze=pass "
            f"execution_id={freeze.get('execution_id')} "
            f"profile={candidate.get('profile_id')} "
            f"threshold={candidate.get('threshold')} "
            "attempts=1 provider_calls=0 holdout=not-executed"
        )
    if status == "skipped":
        return "gb2_s20qpp_pre_holdout_freeze=skipped"
    return (
        "gb2_s20qpp_pre_holdout_freeze=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpp_pre_holdout_freeze()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
