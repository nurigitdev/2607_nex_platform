#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.catalog_lifecycle_repository import InMemoryCatalogLifecycleRepository  # noqa: E402
from nex_mo.catalog_lifecycle_service import CatalogLifecycleService  # noqa: E402
from nex_mo.operations_service import MOOperationsService  # noqa: E402
from nex_mo.provider_readiness_service import ProviderReadinessService  # noqa: E402
from nex_mo.runtime_observability_service import RuntimeObservabilityService  # noqa: E402


NOW = datetime(2026, 10, 1, tzinfo=UTC)


def run_mo_operations_integration_service() -> dict[str, Any]:
    catalog = CatalogLifecycleService(
        InMemoryCatalogLifecycleRepository(),
        clock=lambda: "2026-10-01T00:00:00Z",
    )
    catalog.ensure_bootstrap()
    telemetry = [
        {
            "capability": capability,
            "configured": False,
            "request_count": 1,
            "success_count": 1,
            "failure_count": 0,
            "degraded_count": 0,
            "last_outcome": "success",
            "last_observed_at": "2026-10-01T00:00:00Z",
            "last_latency_ms": 5,
        }
        for capability in ("embedding", "reranking", "generation")
    ]
    service = MOOperationsService(
        catalog_service=catalog,
        readiness_service=ProviderReadinessService(environ={}, now=lambda: NOW),
        runtime_service=RuntimeObservabilityService(environ={}, now=lambda: NOW),
        telemetry_reader=lambda: telemetry,
        environ={},
        now=lambda: NOW,
    )
    snapshot = service.snapshot()
    private_fields = {
        "provider_endpoint",
        "provider_api_key",
        "database_url",
        "model_path",
    }
    serialized = json.dumps(snapshot, sort_keys=True)
    leaked = [field for field in private_fields if field in serialized]
    passed = (
        snapshot["operations_status"] == "READY"
        and snapshot["summary"]["source_count"] == 4
        and snapshot["summary"]["capability_count"] == 3
        and not leaked
    )
    return {
        "evidence_schema_version": "mo_operations_integration_service_evidence.v1",
        "slice": "1184",
        "requirement": "S119",
        "status": "PASS" if passed else "FAIL",
        "snapshot": snapshot,
        "summary": {
            "source_count": snapshot["summary"]["source_count"],
            "capability_count": snapshot["summary"]["capability_count"],
            "ready_count": snapshot["summary"]["capability_status_counts"]["READY"],
            "private_field_count": len(leaked),
        },
        "next_slice": "1185" if passed else None,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_operations_integration_service="
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
    evidence = run_mo_operations_integration_service()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
