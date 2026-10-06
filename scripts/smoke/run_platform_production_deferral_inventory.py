#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_production_deferral_inventory.v1"
SOURCE_PATH = "services/_shared/nex_runtime/release_candidate_assurance.py"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"


@dataclass(frozen=True)
class DeferralRecord:
    deferral_id: str
    owners: tuple[str, ...]
    targets: tuple[str, ...]
    state: str = "DEFERRED"


DEFERRAL_REGISTRY = (
    DeferralRecord("external_signing_key_custody", ("OA",), ("S144",)),
    DeferralRecord(
        "managed_tls_certificate_lifecycle",
        ("platform_integration",),
        ("S143",),
    ),
    DeferralRecord(
        "production_secret_injection_rotation",
        ("platform_integration", "OA", "AE", "CX", "MO", "AG"),
        ("S143",),
    ),
    DeferralRecord("enterprise_idp_registration", ("OA",), ("S144",)),
    DeferralRecord(
        "production_object_storage_lifecycle",
        ("CX", "AE"),
        ("S146",),
    ),
    DeferralRecord(
        "production_postgresql_backup_ha_dr",
        ("OA", "AE", "CX", "MO", "AG", "platform_integration"),
        ("S145",),
    ),
    DeferralRecord(
        "external_notification_incident_endpoints",
        ("AG",),
        ("S148",),
    ),
    DeferralRecord(
        "production_gpu_scheduling_capacity",
        ("MO",),
        ("S147",),
    ),
    DeferralRecord(
        "production_monitoring_paging_slo_approval",
        ("AG", "platform_integration"),
        ("S148", "S150"),
    ),
)


def run_platform_production_deferral_inventory(
    root: Path = ROOT,
) -> dict[str, Any]:
    source_ids = _load_string_tuple(root / SOURCE_PATH, "DEPLOYMENT_DEFERRALS")
    registry_ids = tuple(item.deferral_id for item in DEFERRAL_REGISTRY)
    plan = _read_text(root / PLAN_PATH)
    valid_targets = {f"S{number}" for number in range(143, 151)}
    record_checks = {
        item.deferral_id: {
            "owners_present": bool(item.owners),
            "targets_valid": bool(item.targets)
            and set(item.targets).issubset(valid_targets),
            "state_deferred": item.state == "DEFERRED",
            "documented": all(
                token in plan
                for token in (
                    f"`{item.deferral_id}`",
                    *(f"`{target}`" for target in item.targets),
                    f"`{item.state}`",
                )
            ),
        }
        for item in DEFERRAL_REGISTRY
    }
    checks = {
        "runtime_inventory_exact": source_ids == registry_ids,
        "nine_unique_deferrals": len(registry_ids) == len(set(registry_ids)) == 9,
        "all_records_complete": all(
            all(values.values()) for values in record_checks.values()
        ),
        "production_remains_unapproved": (
            "production deployment remains unapproved" in plan
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1403",
        "requirement": "S141",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": issues,
        "runtime_deferral_ids": list(source_ids),
        "records": [
            {
                "deferral_id": item.deferral_id,
                "owners": list(item.owners),
                "targets": list(item.targets),
                "state": item.state,
                "checks": record_checks[item.deferral_id],
            }
            for item in DEFERRAL_REGISTRY
        ],
        "summary": {
            "runtime_deferral_count": len(source_ids),
            "registered_deferral_count": len(DEFERRAL_REGISTRY),
            "documented_deferral_count": sum(
                values["documented"] for values in record_checks.values()
            ),
            "owner_count": len(
                {owner for item in DEFERRAL_REGISTRY for owner in item.owners}
            ),
            "target_requirement_count": len(
                {target for item in DEFERRAL_REGISTRY for target in item.targets}
            ),
            "open_deferral_count": sum(
                item.state == "DEFERRED" for item in DEFERRAL_REGISTRY
            ),
        },
        "decision": {
            "all_deferrals_remain_open": True,
            "production_connection_required": False,
            "production_deployment_approved": False,
            "next_slice": "1404" if passed else "blocked",
        },
    }


def _load_string_tuple(path: Path, name: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError):
        return ()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError):
            return ()
        if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
            return value
        return ()
    return ()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    if result.get("status") != "PASS":
        return (
            "platform_production_deferral_inventory=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    decision = dict(result.get("decision") or {})
    return (
        "platform_production_deferral_inventory=pass "
        f"deferrals={summary.get('registered_deferral_count', 0)}/9 "
        f"documented={summary.get('documented_deferral_count', 0)}/9 "
        f"owners={summary.get('owner_count', 0)} "
        f"targets={summary.get('target_requirement_count', 0)} "
        f"open={summary.get('open_deferral_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_production_deferral_inventory()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
