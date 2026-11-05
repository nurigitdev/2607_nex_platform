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

from nex_cx.retrieval_answer_support_runtime_activation_decision import (
    DECISION,
    build_runtime_activation_operator_decision,
    decide_runtime_activation,
    validate_runtime_activation_decision_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

SCHEMA_VERSION = "gb2_s20qpz_runtime_activation_operator_decision.v1"
SMOKE_ENV = "NEX_GB2_S20QPZ_RUNTIME_ACTIVATION_DECISION"
DECISION_ENV = "NEX_GB2_S20QPZ_DECISION"
OPERATOR_ENV = "NEX_GB2_S20QPZ_OPERATOR_ID"
RECEIPT_ENV = "NEX_GB2_S20QPZ_DECISION_RECEIPT_PATH"
E2E_REPORT_ENV = "NEX_GB2_S20QPZ_E2E_REPORT_PATH"
E2E_RECEIPT_ENV = "NEX_GB2_S20QPZ_E2E_RECEIPT_PATH"

DESIGN_PATH = (
    ROOT / "scripts/smoke/data/"
    "s136_answer_support_runtime_activation_operator_decision_v1_design.json"
)
E2E_DESIGN_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_sync_runtime_e2e_v1_design.json"
)
INTERACTIVE_SLO_DECISION_RECEIPT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpx_interactive_slo_decision_receipt.json"
)
E2E_REPORT_PATH = ROOT / "reports/live/gb2_ca00_s20qpya_sync_runtime_e2e_retry1.json"
E2E_RECEIPT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpya_sync_runtime_e2e_retry1_receipt.json"
)
DEFAULT_RECEIPT_PATH = (
    ROOT
    / "reports/live/gb2_ca00_s20qpz_runtime_activation_operator_decision_receipt.json"
)
OUTPUT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpz_runtime_activation_operator_decision.json"
)


def run_gb2_s20qpz_runtime_activation_operator_decision(
    environ: Mapping[str, str] | None = None,
    *,
    design: Mapping[str, Any] | None = None,
    e2e_report: Mapping[str, Any] | None = None,
    e2e_receipt: Mapping[str, Any] | None = None,
    e2e_design: Mapping[str, Any] | None = None,
    interactive_slo_decision_receipt: Mapping[str, Any] | None = None,
    clock: Callable[[], datetime] | None = None,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if env.get(DECISION_ENV) != DECISION or not env.get(OPERATOR_ENV):
        return _failure("explicit_runtime_activation_operator_decision_required")
    target = receipt_path or Path(env.get(RECEIPT_ENV, str(DEFAULT_RECEIPT_PATH)))
    if target.exists():
        return _failure("runtime_activation_operator_decision_already_recorded")

    try:
        design_value = dict(design or _load(DESIGN_PATH))
        normalized_design = validate_runtime_activation_decision_design(design_value)
        e2e_report_value = dict(
            e2e_report or _load(Path(env.get(E2E_REPORT_ENV, str(E2E_REPORT_PATH))))
        )
        e2e_receipt_value = dict(
            e2e_receipt or _load(Path(env.get(E2E_RECEIPT_ENV, str(E2E_RECEIPT_PATH))))
        )
        e2e_design_value = dict(e2e_design or _load(E2E_DESIGN_PATH))
        policy_receipt_value = dict(
            interactive_slo_decision_receipt
            or _load(INTERACTIVE_SLO_DECISION_RECEIPT_PATH)
        )
        current = (clock or (lambda: datetime.now(UTC)))()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        operator_decision = build_runtime_activation_operator_decision(
            operator_id=env[OPERATOR_ENV],
            decided_at=_iso(current),
            design=normalized_design,
            e2e_report=e2e_report_value,
            e2e_receipt=e2e_receipt_value,
            e2e_design=e2e_design_value,
            interactive_slo_decision_receipt=policy_receipt_value,
        )
        manifest = decide_runtime_activation(
            design=normalized_design,
            e2e_report=e2e_report_value,
            e2e_receipt=e2e_receipt_value,
            e2e_design=e2e_design_value,
            interactive_slo_decision_receipt=policy_receipt_value,
            operator_decision=operator_decision,
        )
        decision_receipt = {
            "receipt_schema_version": (
                "cx_answer_support_runtime_activation_operator_decision_receipt.v1"
            ),
            "status": "PASS",
            "decision": manifest["decision"],
            "activation_status": manifest["activation_status"],
            "design_hash": normalized_design["design_hash"],
            "operator_decision_hash": operator_decision["decision_hash"],
            "manifest_hash": manifest["manifest_hash"],
            "source_e2e_receipt_hash": manifest["source_e2e_receipt_hash"],
            "source_e2e_manifest_hash": manifest["source_e2e_manifest_hash"],
            "selected_policy_hash": manifest["selected_policy_hash"],
            "approved_activation_scope": manifest["approved_activation_scope"],
            "decided_at": operator_decision["decided_at"],
            "runtime_activation_approved": True,
            "runtime_activated": False,
            "user_visible_decision_change_permitted": False,
            "production_cutover_approved": False,
        }
        decision_receipt["receipt_hash"] = semantic_sha256_hash_ref(decision_receipt)
        _write_exclusive_json(target, decision_receipt)
    except Exception as exc:  # noqa: BLE001 - protected operator boundary
        return _failure(
            "runtime_activation_operator_decision_failed",
            detail={"exception": exc.__class__.__name__},
        )

    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-Z",
        "status": "PASS",
        "decision": manifest["decision"],
        "activation_status": manifest["activation_status"],
        "design_hash": normalized_design["design_hash"],
        "operator_decision_hash": operator_decision["decision_hash"],
        "decision_receipt_hash": decision_receipt["receipt_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "source_e2e_receipt_hash": manifest["source_e2e_receipt_hash"],
        "source_e2e_manifest_hash": manifest["source_e2e_manifest_hash"],
        "selected_policy_hash": manifest["selected_policy_hash"],
        "approved_activation_scope": manifest["approved_activation_scope"],
        "observed_execution": manifest["observed_execution"],
        "observed_metrics": manifest["observed_metrics"],
        "reason_codes": manifest["reason_codes"],
        "checks": manifest["checks"],
        "failed_checks": manifest["failed_checks"],
        "fallback_policy": manifest["fallback_policy"],
        "rollback_target": manifest["rollback_target"],
        "rollback_policy": manifest["rollback_policy"],
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": True,
        "runtime_activated": False,
        "user_visible_decision_change_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": manifest["next_boundary"],
    }


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-Z",
        "status": "FAIL",
        "failure_code": code,
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
        "runtime_activated": False,
        "production_cutover_permitted": False,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        metrics = result.get("observed_metrics")
        metrics = metrics if isinstance(metrics, Mapping) else {}
        return (
            "gb2_s20qpz_runtime_activation_operator_decision=pass "
            f"decision={result.get('decision')} "
            f"e2e_p95_ms={metrics.get('e2e_p95_latency_ms')} "
            "activation=approved_not_activated"
        )
    if status == "skipped":
        return "gb2_s20qpz_runtime_activation_operator_decision=skipped"
    return (
        "gb2_s20qpz_runtime_activation_operator_decision=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpz_runtime_activation_operator_decision()
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
