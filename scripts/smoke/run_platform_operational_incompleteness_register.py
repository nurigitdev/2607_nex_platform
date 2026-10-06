#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from run_platform_production_deferral_inventory import (  # noqa: E402
    DEFERRAL_REGISTRY,
)


SCHEMA_VERSION = "platform_operational_incompleteness_register.v1"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"
OWNER_IDS = ("platform_integration", "OA", "AE", "CX", "MO", "AG")


@dataclass(frozen=True)
class OperationalGap:
    gap_id: str
    domain: str
    priority: str
    owners: tuple[str, ...]
    target: str
    evidence_outcomes: tuple[str, ...]
    source_deferrals: tuple[str, ...] = ()
    state: str = "OPEN"


OPERATIONAL_GAPS = (
    OperationalGap(
        "secret_rotation_operations",
        "trust",
        "P0",
        ("platform_integration", "OA", "AE", "CX", "MO", "AG"),
        "S143",
        ("external_injection", "rotation", "revocation", "restart", "no_secret"),
        ("production_secret_injection_rotation",),
    ),
    OperationalGap(
        "tls_certificate_operations",
        "trust",
        "P0",
        ("platform_integration",),
        "S143",
        ("termination", "renewal", "expiry_alert", "rollback"),
        ("managed_tls_certificate_lifecycle",),
    ),
    OperationalGap(
        "signing_key_custody_rotation",
        "trust",
        "P0",
        ("OA",),
        "S144",
        ("external_custody", "rotation", "overlap", "revocation", "jwks", "restart"),
        ("external_signing_key_custody",),
    ),
    OperationalGap(
        "enterprise_federation_operations",
        "trust",
        "P1",
        ("OA",),
        "S144",
        ("registration", "metadata_rollover", "denial", "outage_recovery"),
        ("enterprise_idp_registration",),
    ),
    OperationalGap(
        "postgres_backup_failover_restore",
        "data",
        "P0",
        ("platform_integration", "OA", "AE", "CX", "MO", "AG"),
        "S145",
        ("backup", "point_in_time_restore", "failover", "rollback", "rpo", "rto"),
        ("production_postgresql_backup_ha_dr",),
    ),
    OperationalGap(
        "private_object_storage_lifecycle",
        "data",
        "P0",
        ("CX", "AE"),
        "S146",
        ("encryption", "owner_scope", "versioning", "retention", "restore", "rollback"),
        ("production_object_storage_lifecycle",),
    ),
    OperationalGap(
        "gpu_capacity_scheduling",
        "model",
        "P1",
        ("MO",),
        "S147",
        ("capacity", "concurrency", "placement", "saturation", "recovery"),
        ("production_gpu_scheduling_capacity",),
    ),
    OperationalGap(
        "model_rollout_failover_calibration",
        "model",
        "P1",
        ("MO", "CX"),
        "S147",
        ("canary", "fallback", "calibration", "drift", "rollback"),
    ),
    OperationalGap(
        "external_incident_dispatch",
        "incident",
        "P1",
        ("AG",),
        "S148",
        ("redacted_delivery", "retry", "deduplication", "outage", "recovery"),
        ("external_notification_incident_endpoints",),
    ),
    OperationalGap(
        "monitoring_paging_slo_operations",
        "incident",
        "P0",
        ("platform_integration", "OA", "AE", "CX", "MO", "AG"),
        "S148",
        ("sli", "slo", "alert", "paging", "ownership", "escalation", "audit"),
        ("production_monitoring_paging_slo_approval",),
    ),
    OperationalGap(
        "staging_reliability_security_rehearsal",
        "release",
        "P0",
        ("platform_integration", "OA", "AE", "CX", "MO", "AG"),
        "S149",
        ("load", "soak", "failure_injection", "security", "privacy", "recovery", "rollback"),
    ),
    OperationalGap(
        "go_live_rollback_change_approval",
        "release",
        "P0",
        ("platform_integration",),
        "S150",
        ("fresh_manifest", "approver_decision", "rollout", "rollback", "zero_residue"),
    ),
)


def run_platform_operational_incompleteness_register(
    root: Path = ROOT,
) -> dict[str, Any]:
    plan = _read_text(root / PLAN_PATH)
    gap_ids = tuple(item.gap_id for item in OPERATIONAL_GAPS)
    deferral_ids = {item.deferral_id for item in DEFERRAL_REGISTRY}
    covered_deferrals = {
        source for item in OPERATIONAL_GAPS for source in item.source_deferrals
    }
    owners = {owner for item in OPERATIONAL_GAPS for owner in item.owners}
    targets = {item.target for item in OPERATIONAL_GAPS}
    record_checks = {
        item.gap_id: {
            "documented": f"`{item.gap_id}`" in plan,
            "priority_valid": item.priority in {"P0", "P1"},
            "owners_valid": bool(item.owners)
            and set(item.owners).issubset(OWNER_IDS),
            "target_valid": item.target in {f"S{number}" for number in range(143, 151)},
            "evidence_outcomes_present": bool(item.evidence_outcomes),
            "state_open": item.state == "OPEN",
            "source_deferrals_valid": set(item.source_deferrals).issubset(
                deferral_ids
            ),
        }
        for item in OPERATIONAL_GAPS
    }
    checks = {
        "twelve_unique_operational_gaps": len(gap_ids) == len(set(gap_ids)) == 12,
        "all_gap_records_complete": all(
            all(values.values()) for values in record_checks.values()
        ),
        "all_nine_deferrals_covered": covered_deferrals == deferral_ids,
        "all_six_owner_groups_participate": owners == set(OWNER_IDS),
        "s143_through_s150_covered": targets
        == {f"S{number}" for number in range(143, 151)},
        "priority_split_exact": (
            sum(item.priority == "P0" for item in OPERATIONAL_GAPS) == 8
            and sum(item.priority == "P1" for item in OPERATIONAL_GAPS) == 4
        ),
        "all_gaps_remain_open": all(
            item.state == "OPEN" for item in OPERATIONAL_GAPS
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1408",
        "requirement": "S141",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": issues,
        "gaps": [
            {
                "gap_id": item.gap_id,
                "domain": item.domain,
                "priority": item.priority,
                "owners": list(item.owners),
                "target": item.target,
                "evidence_outcomes": list(item.evidence_outcomes),
                "source_deferrals": list(item.source_deferrals),
                "state": item.state,
                "checks": record_checks[item.gap_id],
            }
            for item in OPERATIONAL_GAPS
        ],
        "summary": {
            "gap_count": len(OPERATIONAL_GAPS),
            "p0_count": sum(item.priority == "P0" for item in OPERATIONAL_GAPS),
            "p1_count": sum(item.priority == "P1" for item in OPERATIONAL_GAPS),
            "domain_count": len({item.domain for item in OPERATIONAL_GAPS}),
            "owner_count": len(owners),
            "target_requirement_count": len(targets),
            "deferral_coverage_count": len(covered_deferrals),
            "open_count": sum(item.state == "OPEN" for item in OPERATIONAL_GAPS),
        },
        "decision": {
            "gap_inventory_is_completion_evidence": False,
            "production_admission_blocked": True,
            "production_connection_required": False,
            "next_slice": "1409" if passed else "blocked",
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
            "platform_operational_incompleteness_register=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_operational_incompleteness_register=pass "
        f"gaps={summary.get('gap_count', 0)} "
        f"p0={summary.get('p0_count', 0)} "
        f"p1={summary.get('p1_count', 0)} "
        f"deferrals={summary.get('deferral_coverage_count', 0)}/9 "
        f"targets={summary.get('target_requirement_count', 0)} "
        f"open={summary.get('open_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_operational_incompleteness_register()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
