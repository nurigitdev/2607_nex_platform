#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_answer_support_policy_sustained_operations_review import (
    DECISION,
    build_policy_sustained_operations_operator_decision,
    decide_policy_sustained_operations_review,
    validate_policy_sustained_operations_review_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

SCHEMA_VERSION = (
    "gb2_s20qpak_answer_support_policy_sustained_operations_operator_review.v1"
)
SMOKE_ENV = "NEX_GB2_S20QPAK_POLICY_SUSTAINED_OPERATIONS_REVIEW"
DECISION_ENV = "NEX_GB2_S20QPAK_DECISION"
OPERATOR_ENV = "NEX_GB2_S20QPAK_OPERATOR_ID"
SOURCE_REPORT_ENV = "NEX_GB2_S20QPAK_SOURCE_REPORT_PATH"
RECEIPT_ENV = "NEX_GB2_S20QPAK_DECISION_RECEIPT_PATH"

DESIGN_PATH = (
    ROOT
    / "scripts/smoke/data/"
    "s136_answer_support_policy_sustained_operations_review_v1_design.json"
)
SOURCE_REPORT_PATH = (
    ROOT
    / "reports/live/"
    "gb2_ca00_s20qpaj_answer_support_policy_sustained_operations.json"
)
DEFAULT_RECEIPT_PATH = (
    ROOT
    / "reports/live/"
    "gb2_ca00_s20qpak_answer_support_policy_sustained_operations_"
    "operator_review_receipt.json"
)
OUTPUT_PATH = (
    ROOT
    / "reports/live/"
    "gb2_ca00_s20qpak_answer_support_policy_sustained_operations_"
    "operator_review.json"
)


def run_gb2_s20qpak_answer_support_policy_sustained_operations_operator_review(
    environ: Mapping[str, str] | None = None,
    *,
    design: Mapping[str, Any] | None = None,
    source_report: Mapping[str, Any] | None = None,
    clock: Callable[[], datetime] | None = None,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if env.get(DECISION_ENV) != DECISION or not env.get(OPERATOR_ENV):
        return _failure("explicit_policy_sustained_operations_review_required")
    target = receipt_path or Path(env.get(RECEIPT_ENV, str(DEFAULT_RECEIPT_PATH)))
    if target.exists():
        return _failure("policy_sustained_operations_review_already_recorded")

    try:
        normalized_design = validate_policy_sustained_operations_review_design(
            dict(design or _load(DESIGN_PATH))
        )
        report = dict(
            source_report
            or _load(Path(env.get(SOURCE_REPORT_ENV, str(SOURCE_REPORT_PATH))))
        )
        current = (clock or (lambda: datetime.now(UTC)))()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        operator_decision = build_policy_sustained_operations_operator_decision(
            operator_id=env[OPERATOR_ENV],
            decided_at=_iso(current),
            design=normalized_design,
            source_report=report,
        )
        manifest = decide_policy_sustained_operations_review(
            design=normalized_design,
            source_report=report,
            operator_decision=operator_decision,
        )
        receipt = {
            "receipt_schema_version": (
                "cx_answer_support_policy_sustained_operations_"
                "operator_review_receipt.v1"
            ),
            "status": "PASS",
            "decision": manifest["decision"],
            "decision_status": manifest["decision_status"],
            "design_hash": normalized_design["design_hash"],
            "operator_decision_hash": operator_decision["decision_hash"],
            "manifest_hash": manifest["manifest_hash"],
            "source_evidence_hash": manifest["source_evidence_hash"],
            "source_report_document_hash": manifest["source_report_document_hash"],
            "approved_scope": manifest["approved_scope"],
            "next_boundary": manifest["next_boundary"],
            "decided_at": operator_decision["decided_at"],
            "sustained_operations_continuation_approved": True,
            "runtime_changed": False,
            "rollback_contract_preserved": True,
            "steady_state_activation_permitted": False,
            "production_cutover_permitted": False,
        }
        receipt["receipt_hash"] = semantic_sha256_hash_ref(receipt)
        _write_exclusive_json(target, receipt)
    except Exception as exc:  # noqa: BLE001 - protected operator boundary
        return _failure(
            "policy_sustained_operations_operator_review_failed",
            detail={"exception": exc.__class__.__name__},
        )

    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-AK",
        **manifest,
        "decision_receipt_hash": receipt["receipt_hash"],
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("JSON document must be an object")
    return value


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-AK",
        "status": "FAIL",
        "failure_code": code,
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "controlled_continuation_permitted": False,
        "runtime_change_permitted": False,
        "rollback_contract_preserved": True,
        "steady_state_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        metrics = result.get("observed_metrics")
        metrics = metrics if isinstance(metrics, Mapping) else {}
        return (
            "gb2_s20qpak_policy_sustained_operations_review=pass "
            f"decision={result.get('decision')} "
            f"samples={metrics.get('sample_count')} "
            f"next={result.get('next_boundary')}"
        )
    if status == "skipped":
        return "gb2_s20qpak_policy_sustained_operations_review=skipped"
    return (
        "gb2_s20qpak_policy_sustained_operations_review=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpak_answer_support_policy_sustained_operations_operator_review()
    if result.get("status") != "SKIPPED" or not args.output.exists():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
