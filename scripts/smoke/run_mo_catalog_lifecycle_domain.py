#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.catalog_lifecycle import (  # noqa: E402
    build_bootstrap_catalog,
    validate_active_bindings,
)


FORBIDDEN_FIELDS = {
    "provider_endpoint",
    "provider_api_key",
    "authorization_token",
    "ssh_target",
    "model_path",
    "database_url",
    "changed_by",
}


def run_mo_catalog_lifecycle_domain() -> dict[str, Any]:
    entries, bindings = build_bootstrap_catalog()
    validate_active_bindings(entries, bindings)
    projection = {
        "entries": [entry.to_wire() for entry in entries],
        "bindings": [binding.to_wire() for binding in bindings],
    }
    serialized = json.dumps(projection, sort_keys=True)
    exposed = sorted(field for field in FORBIDDEN_FIELDS if field in serialized)
    capabilities = {entry.provider_capability for entry in entries}
    checks = {
        "three_catalog_entries_bootstrapped": len(entries) == 3,
        "three_active_aliases_bootstrapped": len(bindings) == 3
        and all(binding.binding_state == "ACTIVE" for binding in bindings),
        "required_capabilities_complete": capabilities
        == {"embedding", "reranking", "generation"},
        "catalog_binding_references_valid": {binding.catalog_id for binding in bindings}
        == {entry.catalog_id for entry in entries},
        "public_projection_private_fields_omitted": not exposed,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_catalog_lifecycle_domain.v1",
        "slice": "1173",
        "requirement": "S118",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_catalog_lifecycle_domain_failed",
        "checks": checks,
        "summary": {
            "catalog_entry_count": len(entries),
            "active_binding_count": len(bindings),
            "capability_count": len(capabilities),
            "exposed_private_field_count": len(exposed),
        },
        "issues": exposed,
        "next_slice": "1174" if passed else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_catalog_lifecycle_domain="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"entries={summary.get('catalog_entry_count', 0)} "
        f"bindings={summary.get('active_binding_count', 0)} "
        f"capabilities={summary.get('capability_count', 0)} "
        f"private_fields={summary.get('exposed_private_field_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_catalog_lifecycle_domain()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
