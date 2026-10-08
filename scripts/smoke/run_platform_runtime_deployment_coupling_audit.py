#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from nex_runtime.ag_projection_policy import (  # noqa: E402
    AgProjectionPolicyError,
    resolve_ag_projection_policy,
)
from nex_runtime.process_manifest import build_platform_runtime_manifest  # noqa: E402
from nex_runtime.runtime_profiles import SERVICE_ENDPOINT_ENV_NAMES  # noqa: E402
from run_platform_route_client_topology_inventory import (  # noqa: E402
    run_platform_route_client_topology_inventory,
)
from run_platform_runtime_profile_residue_audit import (  # noqa: E402
    run_platform_runtime_profile_residue_audit,
)


SCHEMA_VERSION = "platform_runtime_deployment_coupling_audit.v1"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"
SERVICE_SOURCE_ROOTS = (
    "services/_shared",
    "services/nex-oa",
    "services/nex-ae-api",
    "services/nex-cx",
    "services/nex-mo",
    "services/nex-ag",
)


@dataclass(frozen=True)
class CouplingRecord:
    coupling_id: str
    production_disposition: str
    target: str


COUPLING_REGISTRY = (
    CouplingRecord("cross_service_domain_imports", "CLEAR", "continuous"),
    CouplingRecord("non_mo_provider_endpoint_access", "CLEAR", "continuous"),
    CouplingRecord("service_http_api_edges", "TARGET_BOUNDARY", "continuous"),
    CouplingRecord(
        "ag_legacy_cross_database_adapters",
        "FORBIDDEN_IN_PROTECTED_PROFILES",
        "S142",
    ),
    CouplingRecord(
        "loopback_endpoint_defaults", "FORBIDDEN_IN_PRODUCTION", "S142/S143"
    ),
    CouplingRecord(
        "source_tree_process_commands",
        "REPLACE_WITH_IMMUTABLE_ARTIFACTS",
        "S142",
    ),
)


def run_platform_runtime_deployment_coupling_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    topology = run_platform_route_client_topology_inventory(root)
    profiles = run_platform_runtime_profile_residue_audit(root)
    topology_findings = dict(topology.get("findings") or {})
    profile_findings = dict(profiles.get("findings") or {})
    loopback = _loopback_occurrences(root)
    manifest = build_platform_runtime_manifest("local_mock", environ={})
    plan = _read_text(root / PLAN_PATH)
    protected_legacy_rejected = _protected_legacy_projection_rejected()
    records_documented = {
        item.coupling_id: f"`{item.coupling_id}`" in plan
        for item in COUPLING_REGISTRY
    }
    checks = {
        "prior_topology_inventory_passed": topology.get("status") == "PASS",
        "prior_runtime_profile_audit_passed": profiles.get("status") == "PASS",
        "eleven_http_client_anchors_present": (
            topology_findings.get("http_edge_count") == 11
            and topology_findings.get("logical_edge_count") == 7
        ),
        "cross_service_domain_imports_absent": (
            topology_findings.get("cross_service_package_import_count") == 0
        ),
        "non_mo_provider_endpoint_access_absent": (
            profile_findings.get("direct_provider_reference_count_outside_mo") == 0
        ),
        "four_legacy_database_adapters_inventoried": (
            topology_findings.get("ag_cross_service_database_coupling_count") == 4
        ),
        "protected_profile_rejects_legacy_database_projection": (
            protected_legacy_rejected
        ),
        "production_requires_all_service_endpoints": (
            len(SERVICE_ENDPOINT_ENV_NAMES) == 6
        ),
        "loopback_baseline_exact": (
            loopback["occurrence_count"] == 46 and loopback["file_count"] == 26
        ),
        "thirteen_source_processes_inventoried": len(manifest.processes) == 13,
        "all_coupling_records_documented": all(records_documented.values()),
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1406",
        "requirement": "S141",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": issues,
        "records": [
            {
                "coupling_id": item.coupling_id,
                "production_disposition": item.production_disposition,
                "target": item.target,
                "documented": records_documented[item.coupling_id],
            }
            for item in COUPLING_REGISTRY
        ],
        "loopback_evidence": loopback,
        "summary": {
            "http_client_anchor_count": topology_findings.get(
                "http_edge_count", 0
            ),
            "logical_api_edge_count": topology_findings.get(
                "logical_edge_count", 0
            ),
            "cross_service_import_count": topology_findings.get(
                "cross_service_package_import_count", 0
            ),
            "non_mo_provider_reference_count": profile_findings.get(
                "direct_provider_reference_count_outside_mo", 0
            ),
            "legacy_database_adapter_count": topology_findings.get(
                "ag_cross_service_database_coupling_count", 0
            ),
            "loopback_occurrence_count": loopback["occurrence_count"],
            "loopback_file_count": loopback["file_count"],
            "source_process_count": len(manifest.processes),
            "coupling_record_count": len(COUPLING_REGISTRY),
        },
        "decision": {
            "shared_runtime_imports_allowed": True,
            "service_domain_imports_allowed": False,
            "cross_service_database_reads_allowed": False,
            "direct_provider_access_outside_mo_allowed": False,
            "production_connection_required": False,
            "next_slice": "1407" if passed else "blocked",
        },
    }


def _loopback_occurrences(root: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for relative_root in SERVICE_SOURCE_ROOTS:
        service_root = root / relative_root
        if not service_root.is_dir():
            continue
        for path in service_root.rglob("*.py"):
            count = _read_text(path).count("http://127.0.0.1")
            if count:
                findings.append(
                    {"path": str(path.relative_to(root)), "occurrence_count": count}
                )
    findings.sort(key=lambda item: item["path"])
    return {
        "file_count": len(findings),
        "occurrence_count": sum(item["occurrence_count"] for item in findings),
        "files": findings,
    }


def _protected_legacy_projection_rejected() -> bool:
    try:
        resolve_ag_projection_policy(
            "postgres", environ={"NEX_PROFILE": "production"}
        )
    except AgProjectionPolicyError:
        return True
    return False


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "platform_runtime_deployment_coupling_audit=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_runtime_deployment_coupling_audit=pass "
        f"http={summary.get('http_client_anchor_count', 0)} "
        f"imports={summary.get('cross_service_import_count', 0)} "
        f"provider_refs={summary.get('non_mo_provider_reference_count', 0)} "
        f"legacy_db={summary.get('legacy_database_adapter_count', 0)} "
        f"loopback={summary.get('loopback_occurrence_count', 0)}/"
        f"{summary.get('loopback_file_count', 0)} "
        f"processes={summary.get('source_process_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_runtime_deployment_coupling_audit()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
