#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import httpx


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_readiness_evaluator import (  # noqa: E402
    evaluate_provider_readiness_plan,
)
from nex_mo.provider_readiness_plan import (  # noqa: E402
    build_provider_readiness_probe_plan,
)


PRIVATE_VALUES = (
    "http://private-provider.local:9112/v1/embeddings",
    "http://private-provider.local:9113/v1/rerank",
    "http://private-provider.local:9111",
    "private-api-key",
)


def run_mo_provider_readiness_evaluator() -> dict[str, Any]:
    env = {
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_REMOTE_EMBEDDING_URL": PRIVATE_VALUES[0],
        "NEX_MO_REMOTE_RERANKER_URL": PRIVATE_VALUES[1],
        "NEX_MO_VLLM_BASE_URL": PRIVATE_VALUES[2],
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": PRIVATE_VALUES[3],
        "NEX_MO_REMOTE_RERANKER_API_KEY": PRIVATE_VALUES[3],
        "NEX_MO_VLLM_API_KEY": PRIVATE_VALUES[3],
    }
    calls: list[str] = []

    def requester(method: str, url: str, **kwargs: Any) -> httpx.Response:
        calls.append(method)
        if url.endswith("/v1/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
        if url.endswith("/v1/rerank"):
            return httpx.Response(200, json={"results": [{"index": 0, "score": 0.9}]})
        return httpx.Response(200, json={"data": [{"id": "Qwen3.5-4B"}]})

    mock_snapshot = evaluate_provider_readiness_plan(
        build_provider_readiness_probe_plan({}),
        checked_at="2026-09-30T00:00:00Z",
    ).to_wire()
    live_snapshot = evaluate_provider_readiness_plan(
        build_provider_readiness_probe_plan(env),
        checked_at="2026-09-30T00:00:00Z",
        requester=requester,
    ).to_wire()
    serialized = json.dumps(live_snapshot, sort_keys=True)
    leaks = [value for value in PRIVATE_VALUES if value in serialized]
    checks = {
        "mock_ready_without_network": mock_snapshot["readiness_status"] == "READY",
        "three_active_live_probes": calls == ["POST", "POST", "GET"],
        "live_readiness_ready": live_snapshot["readiness_status"] == "READY",
        "all_live_routes_ready": all(
            route["status"] == "READY" for route in live_snapshot["routes"]
        ),
        "private_values_omitted": not leaks,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_readiness_evaluator.v1",
        "slice": "1125",
        "requirement": "S113",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_readiness_evaluator_failed",
        "checks": checks,
        "summary": {
            "live_probe_count": len(calls),
            "ready_route_count": live_snapshot["summary"]["status_counts"]["READY"],
            "private_value_leak_count": len(leaks),
        },
        "issues": leaks,
        "next_slice": "1126",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_readiness_evaluator="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"probes={summary.get('live_probe_count', 0)} "
        f"ready={summary.get('ready_route_count', 0)} "
        f"leaks={summary.get('private_value_leak_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_readiness_evaluator()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
