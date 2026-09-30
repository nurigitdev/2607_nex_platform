#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-mo"):
    sys.path.insert(0, str(path))

from nex_mo.catalog_lifecycle_repository import (  # noqa: E402
    InMemoryCatalogLifecycleRepository,
)
from nex_mo.catalog_lifecycle_service import (  # noqa: E402
    CatalogLifecycleService,
    RegisterCatalogEntry,
)
from nex_mo.catalog_route_source import CatalogProviderRouteSource  # noqa: E402
from nex_mo.provider_registry import (  # noqa: E402
    configure_provider_route_source,
    resolve_provider_route,
)


NOW = "2026-10-01T05:00:00Z"


def run_mo_catalog_route_resolution() -> dict[str, Any]:
    repository = InMemoryCatalogLifecycleRepository()
    identifiers = iter(("candidate", "binding"))
    service = CatalogLifecycleService(
        repository,
        clock=lambda: NOW,
        id_factory=lambda: next(identifiers),
    )
    service.ensure_bootstrap()
    before = resolve_provider_route(
        "general-llm-default",
        "generation",
    )
    candidate = service.register_catalog_entry(
        RegisterCatalogEntry(
            provider_capability="generation",
            model_name="Generation Candidate",
            model_revision="candidate-v2",
            deployment_id="candidate-deployment",
            runtime_profile="candidate-profile",
            precision="BF16",
            provider_type="openai-compatible",
            supports_response_formats=("text", "json_object"),
            max_input_tokens=16384,
            max_output_tokens=2048,
        )
    )
    service.transition_catalog_entry(
        candidate.catalog_id,
        expected_revision=1,
        target_state="ACTIVE",
    )
    current = next(
        binding
        for binding in service.list_alias_bindings(state="ACTIVE")
        if binding.provider_capability == "generation"
    )
    service.activate_alias(
        alias=current.alias,
        capability="generation",
        catalog_id=candidate.catalog_id,
        expected_binding_revision=current.binding_revision,
        change_reason="Promote candidate",
        changed_by="service:nex-ag",
    )
    previous = configure_provider_route_source(CatalogProviderRouteSource(service))
    try:
        after = resolve_provider_route(current.alias, "generation")
    finally:
        configure_provider_route_source(previous)
    checks = {
        "bootstrap_route_preserved": before.model_revision == "mock-llm-v1",
        "active_alias_resolved": after.model_revision == "candidate-v2",
        "deployment_switched": after.deployment_id == "candidate-deployment",
        "binding_route_identified": after.route_id == "route-binding-binding",
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_catalog_route_resolution.v1",
        "slice": "1178",
        "requirement": "S118",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_catalog_route_resolution_failed",
        "checks": checks,
        "summary": {
            "bootstrap_revision": before.model_revision,
            "switched_revision": after.model_revision,
            "switched_deployment": after.deployment_id,
            "switched_route_id": after.route_id,
        },
        "issues": [],
        "next_slice": "1179" if passed else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_catalog_route_resolution="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"bootstrap={summary.get('bootstrap_revision', 'missing')} "
        f"switched={summary.get('switched_revision', 'missing')} "
        f"route={summary.get('switched_route_id', 'missing')} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_catalog_route_resolution()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
