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

from nex_mo.providers import (  # noqa: E402
    build_model_profile_catalog,
    list_provider_routes,
)


FORBIDDEN_FIELDS = {
    "model_path",
    "live_health_env",
    "provider_endpoint",
    "provider_api_key",
    "process_command",
}


def run_mo_provider_projection_extraction() -> dict[str, Any]:
    profiles = [item.to_wire() for item in build_model_profile_catalog({})]
    routes = [item.to_wire() for item in list_provider_routes()]
    exposed = sorted(
        FORBIDDEN_FIELDS.intersection(
            field for item in (*profiles, *routes) for field in item
        )
    )
    checks = {
        "profiles_projected": len(profiles) >= 3,
        "routes_projected": len(routes) == 3,
        "private_fields_omitted": not exposed,
        "embedding_dimension_preserved": routes[0].get("embedding_dimensions") == 8,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_projection_extraction.v1",
        "slice": "1113",
        "requirement": "S112",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_projection_extraction_failed",
        "checks": checks,
        "summary": {
            "profile_count": len(profiles),
            "route_count": len(routes),
            "exposed_private_field_count": len(exposed),
        },
        "issues": exposed,
        "next_slice": "1114",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_projection_extraction="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"profiles={summary.get('profile_count', 0)} "
        f"routes={summary.get('route_count', 0)} "
        f"private_fields={summary.get('exposed_private_field_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_projection_extraction()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
