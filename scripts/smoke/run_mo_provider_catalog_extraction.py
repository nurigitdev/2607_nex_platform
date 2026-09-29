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

from nex_mo.provider_catalog import (  # noqa: E402
    build_model_profile_catalog as build_catalog,
)
from nex_mo.providers import (  # noqa: E402
    build_model_profile_catalog as build_compatibility_catalog,
)


def run_mo_provider_catalog_extraction(root: Path = ROOT) -> dict[str, Any]:
    catalog_path = root / "services/nex-mo/nex_mo/provider_catalog.py"
    providers_path = root / "services/nex-mo/nex_mo/providers.py"
    catalog_source = (
        catalog_path.read_text(encoding="utf-8") if catalog_path.is_file() else ""
    )
    providers_source = (
        providers_path.read_text(encoding="utf-8") if providers_path.is_file() else ""
    )
    direct = build_catalog({})
    compatible = build_compatibility_catalog({})
    public_profiles = [item.to_wire() for item in direct]
    checks = {
        "catalog_module_present": bool(catalog_source),
        "compatibility_import_present": "from nex_mo.provider_catalog import ("
        in providers_source,
        "catalog_build_is_compatible": direct == compatible,
        "three_capabilities_selected": {
            item.provider_capability for item in direct if item.selected
        }
        == {"embedding", "reranking", "generation"},
        "private_paths_omitted": all(
            "model_path" not in item and "live_health_env" not in item
            for item in public_profiles
        ),
        "environment_parsing_is_catalog_owned": "NEX_MO_GENERATION_PROFILE"
        in catalog_source,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_catalog_extraction.v1",
        "slice": "1114",
        "requirement": "S112",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_catalog_extraction_failed",
        "checks": checks,
        "summary": {
            "profile_count": len(direct),
            "selected_count": sum(item.selected for item in direct),
            "compatibility_route_count": 1,
            "failed_check_count": sum(not value for value in checks.values()),
        },
        "issues": [name for name, value in checks.items() if not value],
        "next_slice": "1115",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_catalog_extraction="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"profiles={summary.get('profile_count', 0)} "
        f"selected={summary.get('selected_count', 0)} "
        f"compatibility={summary.get('compatibility_route_count', 0)} "
        f"failed={summary.get('failed_check_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_catalog_extraction()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
