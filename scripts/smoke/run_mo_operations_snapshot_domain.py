#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.operations_snapshot import (  # noqa: E402
    OperationsSourceAssessment,
    build_capability_operations_status,
    build_mo_operations_snapshot,
)


OBSERVED_AT = "2026-10-01T00:00:00Z"


def run_mo_operations_snapshot_domain() -> dict[str, Any]:
    sources = tuple(
        OperationsSourceAssessment(name, "READY", True, OBSERVED_AT)
        for name in ("catalog", "readiness", "telemetry", "runtime")
    )
    capabilities = tuple(
        build_capability_operations_status(
            provider_capability=capability,
            alias=alias,
            catalog_id=f"catalog-{capability}",
            model_revision=f"model-{capability}",
            deployment_id=f"deployment-{capability}",
            catalog_status="READY",
            route_status="READY",
            telemetry_status="READY",
            runtime_status="READY",
            request_count=1,
            success_count=1,
            failure_count=0,
            last_latency_ms=10,
        )
        for capability, alias in (
            ("embedding", "mock-embedding-default"),
            ("reranking", "mock-reranker-default"),
            ("generation", "general-llm-default"),
        )
    )
    snapshot = build_mo_operations_snapshot(
        provider_mode="mock",
        generated_at=OBSERVED_AT,
        sources=sources,
        capabilities=capabilities,
    ).to_wire()
    return {
        "evidence_schema_version": "mo_operations_snapshot_domain_evidence.v1",
        "slice": "1183",
        "requirement": "S119",
        "status": "PASS" if snapshot["operations_status"] == "READY" else "FAIL",
        "snapshot": snapshot,
        "summary": {
            "source_count": len(snapshot["sources"]),
            "capability_count": len(snapshot["capabilities"]),
            "ready_count": snapshot["summary"]["capability_status_counts"]["READY"],
            "private_field_count": _private_field_count(snapshot),
        },
        "next_slice": "1184",
    }


def _private_field_count(payload: Mapping[str, Any]) -> int:
    forbidden = {"provider_endpoint", "provider_api_key", "database_url", "model_path"}
    return sum(key in forbidden for key in _walk_keys(payload))


def _walk_keys(value: Any):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_operations_snapshot_domain="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"sources={summary.get('source_count', 0)} "
        f"capabilities={summary.get('capability_count', 0)} "
        f"ready={summary.get('ready_count', 0)} "
        f"private={summary.get('private_field_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_operations_snapshot_domain()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
