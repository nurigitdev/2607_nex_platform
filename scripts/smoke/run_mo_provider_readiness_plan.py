#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_readiness_plan import (  # noqa: E402
    build_provider_readiness_probe_plan,
)


PRIVATE_VALUES = (
    "http://private-provider.local/v1/embeddings",
    "http://private-provider.local/v1/rerank",
    "http://private-provider.local:9111",
    "private-api-key",
)
FORBIDDEN_FIELDS = (
    "url",
    "api_key",
    "provider_endpoint",
    "model_path",
    "request_payload",
    "response_payload",
)


def run_mo_provider_readiness_plan() -> dict[str, Any]:
    mock_plan = build_provider_readiness_probe_plan({}).to_safe_summary()
    live_plan = build_provider_readiness_probe_plan(
        {
            "NEX_MO_PROVIDER_MODE": "live",
            "NEX_MO_REMOTE_EMBEDDING_URL": PRIVATE_VALUES[0],
            "NEX_MO_REMOTE_RERANKER_URL": PRIVATE_VALUES[1],
            "NEX_MO_VLLM_BASE_URL": PRIVATE_VALUES[2],
            "NEX_MO_REMOTE_EMBEDDING_API_KEY": PRIVATE_VALUES[3],
            "NEX_MO_REMOTE_RERANKER_API_KEY": PRIVATE_VALUES[3],
            "NEX_MO_VLLM_API_KEY": PRIVATE_VALUES[3],
        }
    ).to_safe_summary()
    serialized = json.dumps(live_plan, sort_keys=True)
    leaks = [value for value in PRIVATE_VALUES if value in serialized]
    forbidden = [field for field in FORBIDDEN_FIELDS if f'"{field}"' in serialized]
    checks = {
        "mock_plan_has_three_targets": mock_plan["target_count"] == 3,
        "live_plan_has_three_targets": live_plan["target_count"] == 3,
        "required_capabilities_ordered": live_plan["required_capabilities"]
        == ["embedding", "reranking", "generation"],
        "live_targets_configured": all(
            target["configured"] for target in live_plan["targets"]
        ),
        "private_values_omitted": not leaks,
        "private_fields_omitted": not forbidden,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_readiness_plan.v1",
        "slice": "1124",
        "requirement": "S113",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_readiness_plan_failed",
        "checks": checks,
        "summary": {
            "mock_target_count": mock_plan["target_count"],
            "live_target_count": live_plan["target_count"],
            "private_value_leak_count": len(leaks),
            "private_field_count": len(forbidden),
        },
        "issues": [*leaks, *forbidden],
        "next_slice": "1125",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_readiness_plan="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"mock={summary.get('mock_target_count', 0)} "
        f"live={summary.get('live_target_count', 0)} "
        f"leaks={summary.get('private_value_leak_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_readiness_plan()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
