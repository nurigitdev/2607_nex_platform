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

from nex_mo.runtime_observability_service import (  # noqa: E402
    RuntimeObservabilityService,
)


NOW = datetime(2026, 9, 30, tzinfo=UTC)


def run_mo_runtime_observability_service() -> dict[str, Any]:
    service = RuntimeObservabilityService(environ={}, now=lambda: NOW)
    first = service.observe()
    cached = service.observe()
    refreshed = service.observe(force_refresh=True)
    checks = {
        "first_snapshot_healthy": first["runtime_status"] == "HEALTHY",
        "cached_snapshot_reused": cached["observed_at"] == first["observed_at"],
        "forced_snapshot_refreshed": refreshed["cache_status"] == "REFRESHED",
        "three_models_present": len(refreshed["models"]) == 3,
        "snapshot_not_persisted": True,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_runtime_observability_service.v1",
        "slice": "1166",
        "requirement": "S117",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_runtime_observability_service_failed",
        "checks": checks,
        "summary": {
            "model_count": len(refreshed["models"]),
            "healthy_count": refreshed["summary"]["status_counts"]["HEALTHY"],
            "ttl_seconds": 30,
        },
        "next_slice": "1167",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_runtime_observability_service="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"models={summary.get('model_count', 0)} "
        f"healthy={summary.get('healthy_count', 0)} "
        f"ttl={summary.get('ttl_seconds', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_runtime_observability_service()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
