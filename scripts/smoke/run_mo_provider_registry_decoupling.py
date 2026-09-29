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

from nex_mo import provider_registry, providers, remote_provider  # noqa: E402


def run_mo_provider_registry_decoupling(root: Path = ROOT) -> dict[str, Any]:
    registry_path = root / "services/nex-mo/nex_mo/provider_registry.py"
    providers_path = root / "services/nex-mo/nex_mo/providers.py"
    remote_path = root / "services/nex-mo/nex_mo/remote_provider.py"
    registry_source = registry_path.read_text(encoding="utf-8") if registry_path.is_file() else ""
    providers_source = providers_path.read_text(encoding="utf-8") if providers_path.is_file() else ""
    remote_source = remote_path.read_text(encoding="utf-8") if remote_path.is_file() else ""
    route = provider_registry.resolve_provider_route(
        "mock-embedding-default",
        "embedding",
    )
    checks = {
        "registry_module_present": bool(registry_source),
        "providers_compatibility_import_present": "from nex_mo.provider_registry import ("
        in providers_source,
        "remote_uses_registry_contract": "from nex_mo.provider_registry import ("
        in remote_source,
        "remote_does_not_import_provider_api": "from nex_mo.providers import" not in remote_source,
        "route_compatibility_preserved": providers.ProviderRoute
        is provider_registry.ProviderRoute,
        "error_compatibility_preserved": providers.ProviderRouteError
        is provider_registry.ProviderRouteError,
        "resolution_preserved": route.embedding_dimensions == 8,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_registry_decoupling.v1",
        "slice": "1118",
        "requirement": "S112",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_registry_decoupling_failed",
        "checks": checks,
        "summary": {
            "route_count": len(provider_registry.DEFAULT_PROVIDER_ROUTES),
            "compatibility_export_count": 5,
            "direct_remote_api_import_count": remote_source.count(
                "from nex_mo.providers import"
            ),
            "failed_check_count": sum(not value for value in checks.values()),
        },
        "issues": [name for name, value in checks.items() if not value],
        "next_slice": "1119",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_registry_decoupling="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"routes={summary.get('route_count', 0)} "
        f"compatibility={summary.get('compatibility_export_count', 0)} "
        f"remote_api_imports={summary.get('direct_remote_api_import_count', 0)} "
        f"failed={summary.get('failed_check_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_registry_decoupling()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
