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
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_answer_support_interactive_slo_policy import (
    DECISION,
    build_interactive_slo_operator_decision,
    decide_interactive_slo_runtime_policy,
    validate_interactive_slo_policy_design,
)
from nex_cx.retrieval_answer_support_sync_capacity import (
    evaluate_sync_capacity_receipt,
)
from nex_cx.retrieval_answer_support_sync_capacity_control import (
    evaluate_sync_capacity_control_receipt,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

SCHEMA_VERSION = "gb2_s20qpx_interactive_slo_policy_decision.v1"
SMOKE_ENV = "NEX_GB2_S20QPX_SLO_POLICY_DECISION"
DECISION_ENV = "NEX_GB2_S20QPX_DECISION"
OPERATOR_ENV = "NEX_GB2_S20QPX_OPERATOR_ID"
RECEIPT_ENV = "NEX_GB2_S20QPX_DECISION_RECEIPT_PATH"

DESIGN_PATH = (
    ROOT
    / "scripts/smoke/data/s136_answer_support_interactive_slo_policy_v1_design.json"
)
CAPACITY_DESIGN_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_sync_capacity_v1_design.json"
)
CONTROL_DESIGN_PATH = (
    ROOT
    / "scripts/smoke/data/s136_answer_support_sync_capacity_c1_control_v1_design.json"
)
CAPACITY_RECEIPT_PATH = ROOT / "reports/live/gb2_ca00_s20qpw_sync_capacity_receipt.json"
CONTROL_RECEIPT_PATH = ROOT / "reports/live/gb2_ca00_s20qpwa_c1_control_receipt.json"
DEFAULT_RECEIPT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpx_interactive_slo_decision_receipt.json"
)
OUTPUT_PATH = ROOT / "reports/live/gb2_ca00_s20qpx_interactive_slo_policy_decision.json"


def run_gb2_s20qpx_interactive_slo_policy_decision(
    environ: Mapping[str, str] | None = None,
    *,
    design: Mapping[str, Any] | None = None,
    capacity_design: Mapping[str, Any] | None = None,
    control_design: Mapping[str, Any] | None = None,
    capacity_receipt: Mapping[str, Any] | None = None,
    control_receipt: Mapping[str, Any] | None = None,
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
        return _failure("explicit_operator_policy_decision_required")
    target = receipt_path or Path(env.get(RECEIPT_ENV, str(DEFAULT_RECEIPT_PATH)))
    if target.exists():
        return _failure("interactive_slo_policy_decision_already_recorded")

    try:
        design_value = dict(design or _load(DESIGN_PATH))
        normalized_design = validate_interactive_slo_policy_design(design_value)
        capacity_design_value = dict(capacity_design or _load(CAPACITY_DESIGN_PATH))
        control_design_value = dict(control_design or _load(CONTROL_DESIGN_PATH))
        capacity_receipt_value = dict(capacity_receipt or _load(CAPACITY_RECEIPT_PATH))
        control_receipt_value = dict(control_receipt or _load(CONTROL_RECEIPT_PATH))
        capacity_manifest = evaluate_sync_capacity_receipt(
            capacity_receipt_value,
            design=capacity_design_value,
        )
        control_manifest = evaluate_sync_capacity_control_receipt(
            control_receipt_value,
            design=control_design_value,
            capacity_receipt=capacity_receipt_value,
        )
        current = (clock or (lambda: datetime.now(UTC)))()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        operator_decision = build_interactive_slo_operator_decision(
            operator_id=env[OPERATOR_ENV],
            decided_at=_iso(current),
            design=normalized_design,
            capacity_manifest=capacity_manifest,
            control_manifest=control_manifest,
        )
        manifest = decide_interactive_slo_runtime_policy(
            design=normalized_design,
            capacity_manifest=capacity_manifest,
            control_manifest=control_manifest,
            operator_decision=operator_decision,
        )
        decision_receipt = {
            "receipt_schema_version": (
                "cx_answer_support_interactive_slo_policy_decision_receipt.v1"
            ),
            "status": "PASS",
            "decision": manifest["decision"],
            "design_hash": normalized_design["design_hash"],
            "operator_decision_hash": operator_decision["decision_hash"],
            "manifest_hash": manifest["manifest_hash"],
            "selected_policy_hash": manifest["selected_policy"]["policy_hash"],
            "capacity_receipt_hash": normalized_design["source_binding"][
                "capacity_receipt_hash"
            ],
            "control_receipt_hash": normalized_design["source_binding"][
                "control_receipt_hash"
            ],
            "decided_at": operator_decision["decided_at"],
            "runtime_activation_permitted": False,
            "production_cutover_permitted": False,
        }
        decision_receipt["receipt_hash"] = semantic_sha256_hash_ref(decision_receipt)
        _write_exclusive_json(target, decision_receipt)
    except Exception as exc:  # noqa: BLE001 - protected decision boundary
        return _failure(
            "interactive_slo_policy_decision_failed",
            detail={"exception": exc.__class__.__name__},
        )

    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-X",
        "status": "PASS",
        "decision": manifest["decision"],
        "design_hash": normalized_design["design_hash"],
        "operator_decision_hash": operator_decision["decision_hash"],
        "decision_receipt_hash": decision_receipt["receipt_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "selected_policy": manifest["selected_policy"],
        "observed_capacity": manifest["observed_capacity"],
        "reason_codes": manifest["reason_codes"],
        "checks": manifest["checks"],
        "pending_acceptance": manifest["pending_acceptance"],
        "execution_mode_selected": True,
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
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
        "slice_id": "GB2-CA00-S20Q-P-X",
        "status": "FAIL",
        "failure_code": code,
        "execution_mode_selected": False,
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
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
        policy = result.get("selected_policy")
        policy = policy if isinstance(policy, Mapping) else {}
        runtime = policy.get("runtime_policy")
        runtime = runtime if isinstance(runtime, Mapping) else {}
        observed = result.get("observed_capacity")
        observed = observed if isinstance(observed, Mapping) else {}
        return (
            "gb2_s20qpx_interactive_slo_policy_decision=pass "
            f"decision={result.get('decision')} "
            f"concurrency={runtime.get('maximum_in_flight_provider_requests')} "
            f"provider_p95_ms={observed.get('maximum_fresh_provider_p95_latency_ms')} "
            "activation=pending_e2e"
        )
    if status == "skipped":
        return "gb2_s20qpx_interactive_slo_policy_decision=skipped"
    return (
        "gb2_s20qpx_interactive_slo_policy_decision=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpx_interactive_slo_policy_decision()
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
