#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-ae-api", ROOT / "services" / "_shared"):
    sys.path.insert(0, str(path))

from nex_ae_api.runtime_policy import (  # noqa: E402
    RuntimePolicyError,
    resolve_runtime_policy,
)


def run_ae_runtime_policy_resolver() -> dict[str, Any]:
    general = resolve_runtime_policy({"user_message": "hello"})
    grounded = resolve_runtime_policy(
        {"user_message": "what changed", "retrieval": {"enabled": True}}
    )
    summary = resolve_runtime_policy({"user_message": "문서를 요약해줘"})
    report = resolve_runtime_policy(
        {
            "user_message": "보고서를 작성해줘",
            "generation": {
                "template_id": "report",
                "template_version": "v1",
            },
        }
    )
    rejected = _rejection_code({"provider_url": "http://forbidden"})
    checks = {
        "general_rule": general["compatibility_rule"]["rule_id"]
        == "ae.general_answer.v1",
        "grounded_rule": grounded["compatibility_rule"]["rule_id"]
        == "ae.grounded_answer.v1",
        "summary_rule": summary["compatibility_rule"]["rule_id"]
        == "ae.document_summary.v1",
        "report_rule": report["compatibility_rule"]["rule_id"]
        == "ae.document_generation.report.v1",
        "explicit_versions": all(
            item["prompt_contract_ref"]["prompt_version"] == "v1"
            for item in (general, grounded, summary, report)
        ),
        "snapshot_hashes": all(
            len(item["policy_snapshot_hash"]) == 64
            for item in (general, grounded, summary, report)
        ),
        "raw_prompt_excluded": all(
            item["raw_prompt_included"] is False
            for item in (general, grounded, summary, report)
        ),
        "provider_runtime_excluded": all(
            item["provider_runtime_included"] is False
            for item in (general, grounded, summary, report)
        ),
        "unsafe_field_rejected": rejected == "ae.provider_runtime_field_forbidden",
    }
    return {
        "smoke_schema_version": "ae_runtime_policy_resolver.v1",
        "slice": "1025",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "resolved_rule_count": 4,
        "remote_provider_required": False,
        "next_slice": "1026",
    }


def _rejection_code(generation: dict[str, Any]) -> str | None:
    try:
        resolve_runtime_policy(
            {"user_message": "hello", "generation": generation}
        )
    except RuntimePolicyError as exc:
        return exc.error_code
    return None


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks", {})
    return (
        "ae_runtime_policy_resolver="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"rules={result.get('resolved_rule_count', 0)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_runtime_policy_resolver()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
