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

from nex_runtime.app import SERVICE_SPECS  # noqa: E402
from run_platform_production_deferral_inventory import (  # noqa: E402
    DEFERRAL_REGISTRY,
)


SCHEMA_VERSION = "platform_production_responsibility_matrix.v1"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"
OWNER_IDS = ("platform_integration", "OA", "AE", "CX", "MO", "AG")
DATABASE_OWNER_BY_SERVICE = {
    "nex-oa": "OA",
    "nex-ae-api": "AE",
    "nex-cx": "CX",
    "nex-mo": "MO",
    "nex-ag": "AG",
}


@dataclass(frozen=True)
class ResponsibilityAssignment:
    control_id: str
    accountable: tuple[str, ...]
    responsible: tuple[str, ...]
    coordinators: tuple[str, ...]
    targets: tuple[str, ...]


ASSIGNMENTS = (
    ResponsibilityAssignment(
        "external_signing_key_custody",
        ("OA",),
        ("OA",),
        ("platform_integration",),
        ("S144",),
    ),
    ResponsibilityAssignment(
        "managed_tls_certificate_lifecycle",
        ("platform_integration",),
        ("platform_integration",),
        ("platform_integration",),
        ("S143",),
    ),
    ResponsibilityAssignment(
        "production_secret_injection_rotation",
        ("platform_integration",),
        ("OA", "AE", "CX", "MO", "AG"),
        ("platform_integration",),
        ("S143",),
    ),
    ResponsibilityAssignment(
        "enterprise_idp_registration",
        ("OA",),
        ("OA",),
        ("platform_integration",),
        ("S144",),
    ),
    ResponsibilityAssignment(
        "production_object_storage_lifecycle",
        ("CX", "AE"),
        ("CX", "AE"),
        ("platform_integration",),
        ("S146",),
    ),
    ResponsibilityAssignment(
        "production_postgresql_backup_ha_dr",
        ("OA", "AE", "CX", "MO", "AG"),
        ("OA", "AE", "CX", "MO", "AG"),
        ("platform_integration",),
        ("S145",),
    ),
    ResponsibilityAssignment(
        "external_notification_incident_endpoints",
        ("AG",),
        ("AG",),
        ("platform_integration",),
        ("S148",),
    ),
    ResponsibilityAssignment(
        "production_gpu_scheduling_capacity",
        ("MO",),
        ("MO",),
        ("platform_integration",),
        ("S147",),
    ),
    ResponsibilityAssignment(
        "production_monitoring_paging_slo_approval",
        ("AG", "platform_integration"),
        ("OA", "AE", "CX", "MO", "AG"),
        ("platform_integration",),
        ("S148", "S150"),
    ),
)


def run_platform_production_responsibility_matrix(
    root: Path = ROOT,
) -> dict[str, Any]:
    plan = _read_text(root / PLAN_PATH)
    deferral_ids = tuple(item.deferral_id for item in DEFERRAL_REGISTRY)
    assignment_ids = tuple(item.control_id for item in ASSIGNMENTS)
    deferral_targets = {
        item.deferral_id: item.targets for item in DEFERRAL_REGISTRY
    }
    valid_owners = set(OWNER_IDS)
    assignment_checks = {
        item.control_id: {
            "accountable_present": bool(item.accountable),
            "responsible_present": bool(item.responsible),
            "coordinator_present": bool(item.coordinators),
            "owners_valid": set(
                (*item.accountable, *item.responsible, *item.coordinators)
            ).issubset(valid_owners),
            "targets_match_deferral": (
                item.targets == deferral_targets.get(item.control_id)
            ),
            "canonical_row_present": f"| `{item.control_id}` |" in plan,
        }
        for item in ASSIGNMENTS
    }
    database_ownership = {
        service_id: {
            "owner": DATABASE_OWNER_BY_SERVICE.get(service_id),
            "database_env": spec.database_env,
        }
        for service_id, spec in SERVICE_SPECS.items()
    }
    accountable_owners = {
        owner for item in ASSIGNMENTS for owner in item.accountable
    }
    responsible_owners = {
        owner for item in ASSIGNMENTS for owner in item.responsible
    }
    checks = {
        "assignment_inventory_exact": assignment_ids == deferral_ids,
        "all_assignments_complete": all(
            all(values.values()) for values in assignment_checks.values()
        ),
        "all_six_owners_accountable": accountable_owners == valid_owners,
        "all_six_owners_responsible": responsible_owners == valid_owners,
        "five_database_owners_exact": (
            set(database_ownership) == set(DATABASE_OWNER_BY_SERVICE)
            and all(
                item["owner"] is not None and item["database_env"]
                for item in database_ownership.values()
            )
        ),
        "cross_database_reads_forbidden": (
            "Cross-service database reads remain prohibited." in plan
        ),
        "platform_does_not_own_domain_data": (
            "it does not own service domain data" in plan
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1407",
        "requirement": "S141",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": issues,
        "assignments": [
            {
                "control_id": item.control_id,
                "accountable": list(item.accountable),
                "responsible": list(item.responsible),
                "coordinators": list(item.coordinators),
                "targets": list(item.targets),
                "checks": assignment_checks[item.control_id],
            }
            for item in ASSIGNMENTS
        ],
        "database_ownership": database_ownership,
        "summary": {
            "control_count": len(ASSIGNMENTS),
            "owner_count": len(valid_owners),
            "accountable_owner_count": len(accountable_owners),
            "responsible_owner_count": len(responsible_owners),
            "database_owner_count": len(database_ownership),
            "target_requirement_count": len(
                {target for item in ASSIGNMENTS for target in item.targets}
            ),
        },
        "decision": {
            "service_data_ownership_changed": False,
            "shared_database_access_allowed": False,
            "platform_coordination_implies_domain_ownership": False,
            "production_connection_required": False,
            "next_slice": "1408" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "platform_production_responsibility_matrix=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_production_responsibility_matrix=pass "
        f"controls={summary.get('control_count', 0)} "
        f"owners={summary.get('owner_count', 0)} "
        f"databases={summary.get('database_owner_count', 0)} "
        f"targets={summary.get('target_requirement_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_production_responsibility_matrix()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
