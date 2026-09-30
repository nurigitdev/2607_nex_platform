#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.runtime_observability import (  # noqa: E402
    build_mock_model_runtime_snapshot,
)


FORBIDDEN_FIELDS = {
    "ssh_target",
    "provider_endpoint",
    "provider_api_key",
    "process_id",
    "process_command_line",
    "model_path",
    "gpu_uuid",
}


def run_mo_runtime_observability_domain() -> dict[str, Any]:
    snapshot = build_mock_model_runtime_snapshot().to_wire()
    serialized = json.dumps(snapshot, sort_keys=True)
    exposed = sorted(field for field in FORBIDDEN_FIELDS if field in serialized)
    checks = {
        "snapshot_healthy": snapshot["runtime_status"] == "HEALTHY",
        "three_models_projected": len(snapshot["models"]) == 3,
        "all_models_precision_matched": all(
            item["precision_status"] == "MATCH" for item in snapshot["models"]
        ),
        "public_projection_private_fields_omitted": not exposed,
        "ttl_bounded": snapshot["expires_at"] == "2026-09-30T00:00:30Z",
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_runtime_observability_domain.v1",
        "slice": "1163",
        "requirement": "S117",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_runtime_observability_domain_failed",
        "checks": checks,
        "summary": {
            "model_count": len(snapshot["models"]),
            "healthy_count": snapshot["summary"]["status_counts"]["HEALTHY"],
            "precision_match_count": sum(
                item["precision_status"] == "MATCH" for item in snapshot["models"]
            ),
            "exposed_private_field_count": len(exposed),
        },
        "issues": exposed,
        "next_slice": "1164",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_runtime_observability_domain="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"models={summary.get('model_count', 0)} "
        f"healthy={summary.get('healthy_count', 0)} "
        f"precision={summary.get('precision_match_count', 0)} "
        f"private_fields={summary.get('exposed_private_field_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_runtime_observability_domain()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
