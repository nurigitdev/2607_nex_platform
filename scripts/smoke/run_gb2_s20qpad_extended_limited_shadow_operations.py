#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_answer_support_controlled_activation import (
    DEFAULT_ACTIVATION_BUNDLE_PATH,
    OperationalRuntimeActivationStateStore,
)
from nex_cx.retrieval_answer_support_limited_operations import (
    DEFAULT_EXTENDED_POLICY_PATH,
    load_limited_operations_policy,
    validate_extended_operations_authorization,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_gb2_s20qpab_limited_shadow_operations import (
    CASES_PATH,
    LimitedShadowAcceptanceProfile,
    _assert_redacted,
    _load,
    run_gb2_s20qpab_limited_shadow_operations,
)

SCHEMA_VERSION = "gb2_s20qpad_extended_limited_shadow_operations.v1"
SMOKE_ENV = "NEX_GB2_S20QPAD_EXTENDED_LIMITED_SHADOW_OPERATIONS"
APPROVED_ENV = "NEX_GB2_S20QPAD_OPERATOR_APPROVED"
OPERATOR_ENV = "NEX_GB2_S20QPAD_OPERATOR_ID"
DECISION_RECEIPT_ENV = "NEX_GB2_S20QPAD_DECISION_RECEIPT_PATH"
OUTPUT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpad_extended_limited_shadow_operations.json"
)
DECISION_RECEIPT_PATH = (
    ROOT
    / "reports/live/gb2_ca00_s20qpac_limited_shadow_operator_review_receipt.json"
)

PAD_PROFILE = LimitedShadowAcceptanceProfile(
    schema_version=SCHEMA_VERSION,
    slice_id="GB2-CA00-S20Q-P-AD",
    smoke_env=SMOKE_ENV,
    approved_env=APPROVED_ENV,
    operator_env=OPERATOR_ENV,
    trace_id="20ad20ad20ad20ad20ad20ad20ad20ad",
    identity_prefix="s20qpad",
    accepted_decision="EXTENDED_LIMITED_SHADOW_RUNTIME_OPERATIONS_ACCEPTED",
    rejected_decision="EXTENDED_LIMITED_SHADOW_RUNTIME_OPERATIONS_REJECTED",
    failure_code="extended_limited_shadow_runtime_operations_acceptance_failed",
    next_boundary="EXTENDED_LIMITED_SHADOW_OPERATOR_REVIEW_DECISION",
)


def run_gb2_s20qpad_extended_limited_shadow_operations(
    environ: Mapping[str, str] | None = None,
    *,
    requester: Callable[..., Any] | None = None,
    port_probe: Callable[[str, Sequence[int]], Mapping[str, bool]] | None = None,
    state_store: OperationalRuntimeActivationStateStore | None = None,
    generation_client: Any | None = None,
    bundle_path: Path = DEFAULT_ACTIVATION_BUNDLE_PATH,
    policy_path: Path = DEFAULT_EXTENDED_POLICY_PATH,
    cases_document: Mapping[str, Any] | None = None,
    decision_receipt: Mapping[str, Any] | None = None,
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
    cases = dict(cases_document or _load(CASES_PATH))
    try:
        policy = load_limited_operations_policy(policy_path)
        receipt = dict(
            decision_receipt
            or _load(
                Path(env.get(DECISION_RECEIPT_ENV, str(DECISION_RECEIPT_PATH)))
            )
        )
        normalized_receipt = validate_extended_operations_authorization(
            policy, receipt
        )
    except Exception as exc:  # noqa: BLE001 - protected acceptance boundary
        result = _failure(
            "extended_limited_shadow_authorization_failed",
            detail={"exception": exc.__class__.__name__},
        )
        _assert_redacted(result, env, _case_rows(cases))
        return result

    result = run_gb2_s20qpab_limited_shadow_operations(
        env,
        requester=requester,
        port_probe=port_probe,
        state_store=state_store,
        generation_client=generation_client,
        bundle_path=bundle_path,
        policy_path=policy_path,
        cases_document=cases,
        profile=PAD_PROFILE,
    )
    if result.get("status") == "PASS":
        result["source_operator_decision"] = {
            "decision": normalized_receipt["decision"],
            "decision_status": normalized_receipt["decision_status"],
            "operator_decision_hash": normalized_receipt["operator_decision_hash"],
            "decision_receipt_hash": normalized_receipt["receipt_hash"],
            "decision_receipt_document_hash": semantic_sha256_hash_ref(
                normalized_receipt
            ),
        }
        result.pop("evidence_hash", None)
        result["evidence_hash"] = semantic_sha256_hash_ref(result)
    _assert_redacted(result, env, _case_rows(cases))
    return result


def _case_rows(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = document.get("cases")
    return list(value) if isinstance(value, list) else []


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": PAD_PROFILE.slice_id,
        "status": "FAIL",
        "failure_code": code,
        "provider_http_requests": 0,
        "holdout_accessed": False,
        "user_visible_decision_change": False,
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
            "gb2_s20qpad_extended_limited_shadow_operations=pass "
            f"samples={live.get('sample_count')} "
            f"provider_p95_ms={live.get('provider_p95_latency_ms')} "
            f"e2e_p95_ms={live.get('e2e_p95_latency_ms')} "
            "restart_cap=verified"
        )
    if status == "skipped":
        return "gb2_s20qpad_extended_limited_shadow_operations=skipped"
    return (
        "gb2_s20qpad_extended_limited_shadow_operations=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpad_extended_limited_shadow_operations()
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
