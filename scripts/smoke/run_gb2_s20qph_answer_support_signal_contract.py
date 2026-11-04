#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_answer_support_signal import (
    build_answer_support_package_features,
    build_answer_support_request,
    normalize_answer_support_response,
    validate_answer_support_signal_design,
)

SCHEMA_VERSION = "gb2_s20qph_answer_support_signal_contract.v1"
SMOKE_ENV = "NEX_GB2_S20QPH_ANSWER_SUPPORT_CONTRACT"
PROFILE_ENV = "NEX_GB2_S20QPH_PROFILE"
DESIGN_ENV = "NEX_GB2_S20QPH_DESIGN"
DESIGN_PATH = (
    ROOT / "scripts" / "smoke" / "data" / "s136_answer_support_signal_v1_design.json"
)
OUTPUT_PATH = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qph_answer_support_signal_contract.json"
)
FORBIDDEN_PERSISTED_KEYS = {
    "query",
    "query_text",
    "text",
    "candidate_text",
    "raw_query",
    "raw_text",
    "rationale",
    "api_key",
    "endpoint",
}


def run_gb2_s20qph_answer_support_signal_contract(
    environ: Mapping[str, str] | None = None,
    *,
    design: Mapping[str, Any] | None = None,
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
    design = design or _load_json(Path(env.get(DESIGN_ENV, str(DESIGN_PATH))))
    if design is None:
        return _failure("design_missing")
    try:
        normalized_design = validate_answer_support_signal_design(design)
        request = build_answer_support_request(
            request_id="s20qph-contract-probe",
            query_text="What is the quarterly expense approval policy?",
            candidates=[
                {
                    "candidate_id": "candidate-1",
                    "text": "The direct approval limits and policy.",
                },
                {
                    "candidate_id": "candidate-2",
                    "text": "The exception procedure supporting that policy.",
                },
                {
                    "candidate_id": "candidate-3",
                    "text": "Expense context without an approval policy.",
                },
                {
                    "candidate_id": "candidate-4",
                    "text": "A conflicting statement that approval is unnecessary.",
                },
            ],
            design=design,
            permission_filtered=True,
            owner_scope_enforced=True,
        )
        binding = {
            "provider_alias": "contract-probe",
            "provider_type": "PROVIDER_NEUTRAL_TEST_DOUBLE",
            "model_revision": "contract-only:not-admitted",
            "deployment_id": "offline-contract-probe",
            "request_profile_id": "answer-support-contract-v1",
            "score_semantics_id": "bounded-ordinal-v1",
        }
        response = {
            "response_schema_version": "cx_answer_support_signal_response.v1",
            "request_id": request["request_id"],
            "provider_binding": binding,
            "items": [
                {
                    "candidate_id": "candidate-1",
                    "classification": "DIRECT_ANSWER",
                    "answer_support_score": 0.92,
                    "contradiction_score": 0.03,
                },
                {
                    "candidate_id": "candidate-2",
                    "classification": "SUPPORTING_EVIDENCE",
                    "answer_support_score": 0.81,
                    "contradiction_score": 0.05,
                },
                {
                    "candidate_id": "candidate-3",
                    "classification": "TOPICAL_NON_ANSWER",
                    "answer_support_score": 0.25,
                    "contradiction_score": 0.08,
                },
                {
                    "candidate_id": "candidate-4",
                    "classification": "CONTRADICTORY_EVIDENCE",
                    "answer_support_score": 0.07,
                    "contradiction_score": 0.88,
                },
            ],
        }
        evidence = normalize_answer_support_response(
            request=request,
            response=response,
            expected_provider_binding=binding,
            design=design,
        )
        features = build_answer_support_package_features(evidence)
    except (KeyError, TypeError, ValueError) as exc:
        return _failure("contract_invalid", detail=str(exc))

    forbidden = sorted(
        key for key in _nested_keys({"evidence": evidence, "features": features})
        if key in FORBIDDEN_PERSISTED_KEYS
    )
    checks = {
        "design_frozen_contract_only": (
            normalized_design["status"] == "FROZEN_CONTRACT_ONLY"
        ),
        "provider_neutral_boundary_preserved": (
            normalized_design["safety"]["provider_selection_permitted"] is False
        ),
        "raw_text_absent_from_persisted_projection": not forbidden,
        "candidate_truth_runtime_input_prohibited": (
            evidence["safety"]["candidate_truth_runtime_input_permitted"] is False
        ),
        "provider_binding_preserved": evidence["provider_binding"] == binding,
        "threshold_and_decision_absent": (
            features["semantics"]["ready_threshold"] is None
            and features["semantics"]["ready_decision"] is None
        ),
        "holdout_remained_sealed": (
            features["safety"]["holdout_access_permitted"] is False
        ),
        "runtime_activation_prohibited": (
            features["safety"]["runtime_activation_permitted"] is False
        ),
    }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-H",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": "CONTRACT_FROZEN_FOR_LIVE_COLLECTION_DESIGN",
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_opened": False,
        "runtime_activated": False,
        "design_hash": normalized_design["design_hash"],
        "evidence_hash": evidence["evidence_hash"],
        "feature_hash": features["feature_hash"],
        "provider_binding": evidence["provider_binding"],
        "classification_counts": features["classification_counts"],
        "forbidden_persisted_keys": forbidden,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _nested_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(_nested_keys(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            keys.update(_nested_keys(item))
    return keys


def _load_json(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, Mapping) else None


def _failure(code: str, *, detail: str | None = None) -> dict[str, Any]:
    result = {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
    }
    if detail:
        result["failure_detail"] = detail
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        return (
            "gb2_s20qph_answer_support_signal_contract=pass "
            "provider=neutral holdout=sealed runtime=disabled"
        )
    if status == "skipped":
        return "gb2_s20qph_answer_support_signal_contract=skipped"
    return (
        "gb2_s20qph_answer_support_signal_contract=fail "
        f"checks={','.join(result.get('failed_checks', [])) or result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qph_answer_support_signal_contract()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"{json.dumps(result, indent=2, sort_keys=True)}\n", encoding="utf-8"
        )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
