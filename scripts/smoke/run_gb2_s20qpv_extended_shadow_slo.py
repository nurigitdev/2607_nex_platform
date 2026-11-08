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
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_answer_support_extended_shadow import (
    evaluate_extended_shadow_slo,
    validate_extended_shadow_entry,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_gb2_s20qpt_shadow_canary_operations import (
    APPROVED_ENV as CANARY_APPROVED_ENV,
)
from run_gb2_s20qpt_shadow_canary_operations import (
    OPERATOR_ENV as CANARY_OPERATOR_ENV,
)
from run_gb2_s20qpt_shadow_canary_operations import (
    SMOKE_ENV as CANARY_SMOKE_ENV,
)
from run_gb2_s20qpt_shadow_canary_operations import (
    run_gb2_s20qpt_shadow_canary_operations,
)

SCHEMA_VERSION = "gb2_s20qpv_extended_shadow_slo.v1"
SMOKE_ENV = "NEX_GB2_S20QPV_EXTENDED_SHADOW"
APPROVED_ENV = "NEX_GB2_S20QPV_OPERATOR_APPROVED"
OPERATOR_ENV = "NEX_GB2_S20QPV_OPERATOR_ID"
EXTENDED_RECEIPT_ENV = "NEX_GB2_S20QPV_EXTENDED_RECEIPT_PATH"
SLO_RECEIPT_ENV = "NEX_GB2_S20QPV_SLO_RECEIPT_PATH"

DESIGN_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_extended_shadow_slo_v1_design.json"
)
POLICY_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_extended_shadow_v1_policy.json"
)
CASES_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_extended_shadow_v1_cases.json"
)
CUTOVER_RECEIPT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpu_runtime_cutover_decision_receipt.json"
)
EXTENDED_RECEIPT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpv_extended_shadow_receipt.json"
)
SLO_RECEIPT_PATH = ROOT / "reports/live/gb2_ca00_s20qpv_latency_slo_receipt.json"
OUTPUT_PATH = ROOT / "reports/live/gb2_ca00_s20qpv_extended_shadow_slo.json"

CanaryRunner = Callable[..., dict[str, Any]]


def run_gb2_s20qpv_extended_shadow_slo(
    environ: Mapping[str, str] | None = None,
    *,
    canary_runner: CanaryRunner = run_gb2_s20qpt_shadow_canary_operations,
    cutover_receipt: Mapping[str, Any] | None = None,
    extended_receipt: Mapping[str, Any] | None = None,
    design: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    cases_document: Mapping[str, Any] | None = None,
    extended_receipt_path: Path | None = None,
    slo_receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Collect 30 bounded observations and evaluate the pre-frozen SLO."""
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if env.get(APPROVED_ENV) != "1" or not env.get(OPERATOR_ENV):
        return _failure("operator_approval_required")

    extended_target = extended_receipt_path or Path(
        env.get(EXTENDED_RECEIPT_ENV, str(EXTENDED_RECEIPT_PATH))
    )
    slo_target = slo_receipt_path or Path(
        env.get(SLO_RECEIPT_ENV, str(SLO_RECEIPT_PATH))
    )
    if extended_receipt is None and extended_target.exists():
        return _failure("extended_observation_already_consumed")
    if slo_target.exists():
        return _failure("latency_slo_decision_already_recorded")

    try:
        design_value = dict(design or _load(DESIGN_PATH))
        policy_value = dict(policy or _load(POLICY_PATH))
        cases_value = dict(cases_document or _load(CASES_PATH))
        cutover_value = dict(cutover_receipt or _load(CUTOVER_RECEIPT_PATH))
        normalized_design = validate_extended_shadow_entry(
            cutover_value,
            policy=policy_value,
            cases_document=cases_value,
            design=design_value,
        )
        if extended_receipt is None:
            canary_env = {
                **env,
                CANARY_SMOKE_ENV: "1",
                CANARY_APPROVED_ENV: "1",
                CANARY_OPERATOR_ENV: env[OPERATOR_ENV],
            }
            canary_result = canary_runner(
                canary_env,
                cases_document=cases_value,
                policy_document=policy_value,
                receipt_path=extended_target,
            )
            if canary_result.get("status") != "PASS":
                return _failure(
                    "extended_shadow_observation_failed",
                    detail={
                        "canary_failure_code": canary_result.get(
                            "failure_code", "checks_failed"
                        )
                    },
                )
            extended_value = _load(extended_target)
        else:
            extended_value = dict(extended_receipt)
            canary_result = {
                "status": "PASS",
                "provider_http_requests": extended_value.get(
                    "provider_http_requests", {}
                ),
            }
        manifest = evaluate_extended_shadow_slo(
            cutover_value,
            extended_value,
            design=normalized_design,
        )
        slo_receipt = {
            "receipt_schema_version": (
                "cx_answer_support_extended_shadow_slo_receipt.v1"
            ),
            "status": "PASS",
            "decision": manifest["decision"],
            "background_slo_status": manifest["background_slo_status"],
            "manifest_hash": manifest["manifest_hash"],
            "design_hash": manifest["design_hash"],
            "extended_shadow_receipt_hash": extended_value["receipt_hash"],
            "observed_metrics": manifest["observed_metrics"],
            "runtime_activation_permitted": False,
            "production_cutover_permitted": False,
        }
        slo_receipt["receipt_hash"] = semantic_sha256_hash_ref(slo_receipt)
        _write_exclusive_json(slo_target, slo_receipt)
    except Exception as exc:  # noqa: BLE001 - protected boundary consumes failures
        return _failure(
            "extended_shadow_slo_failed",
            detail={"exception": exc.__class__.__name__},
        )

    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-V",
        "status": "PASS",
        "decision": manifest["decision"],
        "background_slo_status": manifest["background_slo_status"],
        "design_hash": manifest["design_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "slo_receipt_hash": slo_receipt["receipt_hash"],
        "extended_shadow_receipt_hash": extended_value["receipt_hash"],
        "latency_slo": manifest["latency_slo"],
        "observed_metrics": manifest["observed_metrics"],
        "checks": manifest["checks"],
        "failed_checks": manifest["failed_checks"],
        "provider_http_requests": dict(
            canary_result.get("provider_http_requests") or {}
        ),
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
        "slice_id": "GB2-CA00-S20Q-P-V",
        "status": "FAIL",
        "failure_code": code,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
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
            "gb2_s20qpv_extended_shadow_slo=pass "
            f"samples={metrics.get('sample_count')} "
            f"p95_ms={metrics.get('p95_latency_ms')} "
            f"background_slo={result.get('background_slo_status')} "
            "cutover=prohibited"
        )
    if status == "skipped":
        return "gb2_s20qpv_extended_shadow_slo=skipped"
    return (
        "gb2_s20qpv_extended_shadow_slo=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpv_extended_shadow_slo()
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
