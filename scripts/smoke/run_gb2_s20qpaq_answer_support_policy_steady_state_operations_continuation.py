#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_gb2_s20qpao_answer_support_policy_steady_state_operations as base
from nex_cx.retrieval_answer_support_policy_steady_state_operations import (
    load_policy_steady_state_operations_policy,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

SCHEMA_VERSION = (
    "gb2_s20qpaq_answer_support_policy_steady_state_operations_continuation.v1"
)
SMOKE_ENV = "NEX_GB2_S20QPAQ_STEADY_STATE_CONTINUATION"
APPROVED_ENV = "NEX_GB2_S20QPAQ_OPERATOR_APPROVED"
OPERATOR_ENV = "NEX_GB2_S20QPAQ_OPERATOR_ID"
OUTPUT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpaq_answer_support_policy_"
    "steady_state_operations_continuation.json"
)
POLICY_PATH = (
    ROOT / "services/nex-cx/nex_cx/data/"
    "answer_support_policy_steady_state_continuation.v1.json"
)
REVIEW_REPORT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpap_answer_support_policy_"
    "steady_state_operations_operator_review.json"
)
REVIEW_RECEIPT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpap_answer_support_policy_"
    "steady_state_operations_operator_review_receipt.json"
)
DECISION = "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_CONTINUATION_ACCEPTED"
NEXT_BOUNDARY = (
    "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_CONTINUATION_OPERATOR_REVIEW"
)


def run_gb2_s20qpaq_answer_support_policy_steady_state_operations_continuation(
    environ: Mapping[str, str] | None = None,
    *,
    requester: Callable[..., Any] | None = None,
    port_probe: Callable[[str, Sequence[int]], Mapping[str, bool]] | None = None,
    generation_client: Any | None = None,
    event_store: Any | None = None,
    cases_document: Mapping[str, Any] | None = None,
    activation_report: Mapping[str, Any] | None = None,
    review_report: Mapping[str, Any] | None = None,
    review_receipt: Mapping[str, Any] | None = None,
    base_runner: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if env.get(APPROVED_ENV) != "1" or not env.get(OPERATOR_ENV):
        return _failure("operator_approval_required")

    stage = "CONTINUATION_SOURCE_ADMISSION"
    try:
        policy = load_policy_steady_state_operations_policy(POLICY_PATH)
        report = dict(review_report or _load_private(REVIEW_REPORT_PATH))
        receipt = dict(review_receipt or _load_private(REVIEW_RECEIPT_PATH))
        _require_review_binding(policy, report, receipt)

        stage = "CONTINUATION_RUNTIME_ACCEPTANCE"
        effective_env = {
            **env,
            base.SMOKE_ENV: "1",
            base.APPROVED_ENV: "1",
            base.OPERATOR_ENV: env[OPERATOR_ENV],
            "NEX_CX_ANSWER_SUPPORT_STEADY_STATE_OPERATIONS_PATH": str(POLICY_PATH),
        }
        run_base = (
            base_runner
            or base.run_gb2_s20qpao_answer_support_policy_steady_state_operations
        )
        base_result = dict(
            run_base(
                effective_env,
                requester=requester,
                port_probe=port_probe,
                generation_client=generation_client,
                event_store=event_store,
                cases_document=cases_document,
                activation_report=activation_report,
            )
        )
        if base_result.get("status") != "PASS":
            raise RuntimeError(
                str(base_result.get("failure_code", "continuation execution failed"))
            )

        checks = dict(_mapping(base_result.get("checks"), "base_checks"))
        checks.update(
            {
                "pap_review_report_bound": True,
                "pap_continuation_receipt_bound": True,
                "continuation_policy_bound": (
                    base_result.get("policy_hash") == policy["policy_hash"]
                ),
            }
        )
        result = deepcopy(base_result)
        result.pop("evidence_hash", None)
        result.update(
            {
                "evidence_schema_version": SCHEMA_VERSION,
                "slice_id": "GB2-CA00-S20Q-P-AQ",
                "status": "PASS" if all(checks.values()) else "FAIL",
                "decision": (
                    DECISION
                    if all(checks.values())
                    else "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_"
                    "CONTINUATION_REJECTED"
                ),
                "continuation_receipt_hash": receipt["receipt_hash"],
                "source_review_report_document_hash": semantic_sha256_hash_ref(report),
                "checks": checks,
                "failed_checks": [name for name, ok in checks.items() if not ok],
                "next_boundary": NEXT_BOUNDARY,
            }
        )
        result["evidence_hash"] = semantic_sha256_hash_ref(result)
        return result
    except Exception as exc:  # noqa: BLE001 - protected continuation boundary
        return _failure(
            "policy_steady_state_operations_continuation_failed",
            detail={"exception": exc.__class__.__name__, "stage": stage},
        )


def _require_review_binding(
    policy: Mapping[str, Any],
    report: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> None:
    source = _mapping(policy.get("source_review"), "source_review")
    report_hash = semantic_sha256_hash_ref(report)
    receipt_hash = semantic_sha256_hash_ref(receipt)
    receipt_payload = dict(receipt)
    supplied_receipt_hash = receipt_payload.pop("receipt_hash", None)
    checks = report.get("checks")
    if (
        report_hash != source.get("review_report_document_hash")
        or receipt_hash != source.get("decision_receipt_document_hash")
        or supplied_receipt_hash != source.get("decision_receipt_hash")
        or semantic_sha256_hash_ref(receipt_payload) != supplied_receipt_hash
        or report.get("evidence_schema_version")
        != source.get("evidence_schema_version")
        or report.get("slice_id") != "GB2-CA00-S20Q-P-AP"
        or report.get("status") != "PASS"
        or report.get("decision") != source.get("decision")
        or report.get("decision_status") != source.get("decision_status")
        or report.get("approved_scope") != source.get("approved_scope")
        or report.get("next_boundary") != source.get("next_boundary")
        or report.get("design_hash") != source.get("design_hash")
        or report.get("operator_decision_hash") != source.get("operator_decision_hash")
        or report.get("manifest_hash") != source.get("manifest_hash")
        or report.get("decision_receipt_hash") != source.get("decision_receipt_hash")
        or report.get("source_evidence_hash") != source.get("source_evidence_hash")
        or report.get("failed_checks") != []
        or not isinstance(checks, Mapping)
        or any(value is not True for value in checks.values())
        or report.get("controlled_continuation_permitted") is not True
        or report.get("runtime_change_permitted") is not False
        or report.get("rollback_contract_preserved") is not True
        or report.get("production_cutover_permitted") is not False
        or report.get("provider_calls") != 0
        or report.get("database_calls") != 0
        or report.get("holdout_accessed") is not False
        or receipt.get("status") != "PASS"
        or receipt.get("decision") != source.get("decision")
        or receipt.get("manifest_hash") != source.get("manifest_hash")
        or receipt.get("source_evidence_hash") != source.get("source_evidence_hash")
        or receipt.get("steady_state_operations_continuation_approved") is not True
        or receipt.get("runtime_changed") is not False
        or receipt.get("rollback_contract_preserved") is not True
        or receipt.get("production_cutover_permitted") is not False
    ):
        raise ValueError("steady-state continuation review binding drift")


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _load_private(path: Path) -> dict[str, Any]:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise PermissionError(f"{path.name} must be owner-private")
    value = json.loads(path.read_text(encoding="utf-8"))
    return dict(_mapping(value, path.name))


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-AQ",
        "status": "FAIL",
        "failure_code": code,
        "provider_http_requests": 0,
        "holdout_accessed": False,
        "runtime_stopped_at_review_cadence": False,
        "rollback_contract_preserved": True,
        "production_cutover_permitted": False,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        live = result.get("live_execution")
        live = live if isinstance(live, Mapping) else {}
        return (
            "gb2_s20qpaq_policy_steady_state_continuation=pass "
            f"samples={live.get('sample_count')} "
            f"provider_p95_ms={live.get('provider_p95_latency_ms')} "
            f"e2e_p95_ms={live.get('e2e_p95_latency_ms')} review=due"
        )
    if status == "skipped":
        return "gb2_s20qpaq_policy_steady_state_continuation=skipped"
    return (
        "gb2_s20qpaq_policy_steady_state_continuation=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = (
        run_gb2_s20qpaq_answer_support_policy_steady_state_operations_continuation()
    )
    if result.get("status") != "SKIPPED" or not args.output.exists():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        args.output.chmod(0o600)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
