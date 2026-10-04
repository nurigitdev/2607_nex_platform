#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_registry import resolve_provider_route  # noqa: E402
from nex_runtime.service_endpoints import (  # noqa: E402
    SERVICE_ENDPOINTS,
    resolve_cx_mo_timeout_budget,
    resolve_service_endpoint,
)


def run_platform_endpoint_timeout_policy() -> dict[str, Any]:
    endpoints = [
        resolve_service_endpoint(service_id)
        for service_id in SERVICE_ENDPOINTS
    ]
    budgets = [
        resolve_cx_mo_timeout_budget(capability)
        for capability in ("embedding", "reranking", "generation")
    ]
    canonical_aliases = {
        "embedding": resolve_provider_route(
            "embedding-default", "embedding"
        ).alias,
        "reranking": resolve_provider_route(
            "reranker-default", "reranking"
        ).alias,
    }
    checks = {
        "five_endpoints_resolve": len(endpoints) == 5,
        "endpoint_environment_names_are_unique": len(
            {item.environment_name for item in endpoints}
        )
        == 5,
        "three_timeout_budgets_are_safe": all(
            item.client_timeout_seconds >= item.minimum_client_timeout_seconds
            for item in budgets
        ),
        "embedding_budget_is_60_seconds": budgets[0].client_timeout_seconds == 60,
        "reranking_budget_is_60_seconds": budgets[1].client_timeout_seconds == 60,
        "generation_budget_is_130_seconds": budgets[2].client_timeout_seconds == 130,
        "canonical_aliases_preserve_compatibility": canonical_aliases
        == {
            "embedding": "mock-embedding-default",
            "reranking": "mock-reranker-default",
        },
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "platform_endpoint_timeout_policy.v1",
        "slice": "1316",
        "requirement": "S132",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "platform_endpoint_timeout_policy_failed",
        "checks": checks,
        "issues": [name for name, value in checks.items() if not value],
        "endpoints": [
            {
                "service_id": item.service_id,
                "environment_name": item.environment_name,
                "base_url": item.base_url,
            }
            for item in endpoints
        ],
        "timeout_budgets": [
            {
                "capability": item.capability,
                "upstream_timeout_seconds": item.upstream_timeout_seconds,
                "max_attempts": item.max_attempts,
                "minimum_client_timeout_seconds": item.minimum_client_timeout_seconds,
                "client_timeout_seconds": item.client_timeout_seconds,
            }
            for item in budgets
        ],
        "canonical_aliases": canonical_aliases,
        "decision": {
            "cx_mo_timeout_inversion_closed": True,
            "provider_hosts_remain_mo_owned": True,
            "legacy_aliases_removed": False,
            "next_slice": "1317",
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_endpoint_timeout_policy=fail issues={len(evidence.get('issues') or [])}"
    budgets = evidence.get("timeout_budgets") or []
    return (
        "platform_endpoint_timeout_policy=pass "
        f"endpoints={len(evidence.get('endpoints') or [])} "
        f"budgets={'/'.join(str(item['client_timeout_seconds']).removesuffix('.0') for item in budgets)} "
        f"aliases={len(evidence.get('canonical_aliases') or {})} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_endpoint_timeout_policy()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
