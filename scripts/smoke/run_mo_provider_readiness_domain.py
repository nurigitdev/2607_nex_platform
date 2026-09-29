#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_readiness import (  # noqa: E402
    build_mock_provider_readiness_snapshot,
)


FORBIDDEN_FIELDS = {
    "provider_endpoint",
    "provider_api_key",
    "model_path",
    "process_command",
    "request_payload",
    "response_payload",
}


def run_mo_provider_readiness_domain() -> dict[str, Any]:
    snapshot = build_mock_provider_readiness_snapshot(
        checked_at="2026-09-30T00:00:00Z"
    ).to_wire()
    serialized = json.dumps(snapshot, sort_keys=True)
    exposed = sorted(field for field in FORBIDDEN_FIELDS if field in serialized)
    checks = {
        "snapshot_ready": snapshot["readiness_status"] == "READY",
        "three_routes_projected": len(snapshot["routes"]) == 3,
        "all_routes_ready": all(item["status"] == "READY" for item in snapshot["routes"]),
        "public_projection_private_fields_omitted": not exposed,
        "ttl_bounded": snapshot["expires_at"] == "2026-09-30T00:00:30Z",
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_readiness_domain.v1",
        "slice": "1123",
        "requirement": "S113",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_readiness_domain_failed",
        "checks": checks,
        "summary": {
            "route_count": len(snapshot["routes"]),
            "ready_count": snapshot["summary"]["status_counts"]["READY"],
            "exposed_private_field_count": len(exposed),
        },
        "issues": exposed,
        "next_slice": "1124",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_readiness_domain="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"routes={summary.get('route_count', 0)} "
        f"ready={summary.get('ready_count', 0)} "
        f"private_fields={summary.get('exposed_private_field_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_readiness_domain()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
