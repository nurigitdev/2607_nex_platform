#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s148_observability_incident_boundary.v1"
CANONICAL_PATH = "docs/56_platform_observability_slo_incident_integration.md"
READINESS_PATH = "docs/48_platform_production_readiness_plan.md"
SLICE_PATH = "docs/slices/1473_s148_observability_incident_boundary.md"
DELIVERY_MODES = ("local_only", "private_network", "internet_connected")
SERVICE_OWNERS = ("nex-oa", "nex-ae-api", "nex-cx", "nex-mo", "nex-ag")
REQUIRED_PATHS = (
    CANONICAL_PATH,
    READINESS_PATH,
    SLICE_PATH,
    "services/nex-ag/nex_ag/cross_service_trace.py",
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
    "database/nex-ag/migrations/0702_ag_operator_review_escalation_dispatch.sql",
    "docs/55_platform_model_serving_capacity_rollout.md",
)


def run_observability_incident_boundary(root: Path = ROOT) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    readiness = " ".join(_read_text(root / READINESS_PATH).split())
    checks = {
        "required_paths_present": all(paths.values()),
        "signal_correlation_frozen": all(
            token in canonical
            for token in ("METRIC", "LOG", "TRACE", "READINESS", "trace_id")
        ),
        "service_sli_slo_ownership_frozen": all(
            service in canonical for service in SERVICE_OWNERS
        )
        and "NO_DATA" in canonical,
        "alert_delivery_separation_frozen": all(
            token in canonical
            for token in (
                "Alert detection is separate from notification delivery",
                "PENDING -> FIRING -> ACKNOWLEDGED -> RESOLVED",
            )
        ),
        "delivery_modes_frozen": all(mode in canonical for mode in DELIVERY_MODES)
        and "NEX_NOTIFICATION_MODE" in canonical,
        "mock_state_honest": all(
            token in canonical
            for token in ("MOCK_ACCEPTED", "EXTERNAL_NOT_ACTIVATED")
        ),
        "durable_state_frozen": all(
            token in canonical
            for token in ("ag_alerts", "ag_notify_outbox", "ag_notify_attempts")
        ),
        "privacy_boundary_frozen": all(
            token in canonical
            for token in ("Prompts", "credentials", "one-way digests")
        ),
        "single_host_limit_frozen": all(
            token in canonical
            for token in ("dead-man receiver", "total power, host, or network-loss")
        ),
        "existing_dispatch_reuse_bounded": all(
            token in canonical
            for token in ("ag_op_esc_dispatches", "case-specific")
        ),
        "ten_slice_gate_sequence_frozen": (
            all(f"`{slice_id}`" in canonical for slice_id in range(1473, 1483))
            and "Checkpoint Gate runs at Slice 1477" in canonical
            and "Full Gate runs at Slice 1482" in canonical
        ),
        "production_deferrals_remain_open": all(
            token in readiness
            for token in (
                "external_notification_incident_endpoints",
                "production_monitoring_paging_slo_approval",
            )
        ),
    }
    issues = [
        {"category": "path_missing", "path": path}
        for path, present in paths.items()
        if not present
    ]
    issues.extend(
        {"category": "check_failed", "check": name}
        for name, passed in checks.items()
        if not passed
    )
    passed = not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1473",
        "requirement": "S148",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "delivery_modes": list(DELIVERY_MODES),
        "service_owners": list(SERVICE_OWNERS),
        "summary": {
            "required_path_count": sum(paths.values()),
            "check_count": len(checks),
            "delivery_mode_count": len(DELIVERY_MODES),
            "service_owner_count": len(SERVICE_OWNERS),
            "gap_count": 7,
            "slice_count": 10,
            "missing_path_count": sum(not value for value in paths.values()),
        },
        "decision": {
            "alert_source_of_record": "ag_alerts",
            "notification_source_of_record": "ag_notify_outbox",
            "external_activation": "EXTERNAL_NOT_ACTIVATED",
            "current_acceptance": "MOCK_ACCEPTED",
            "production_deployment_approved": False,
            "next_slice": "1474" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"s148_observability_boundary=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "s148_observability_boundary=pass "
        f"checks={summary.get('check_count', 0)}/12 "
        f"modes={summary.get('delivery_mode_count', 0)} "
        f"services={summary.get('service_owner_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"slices={summary.get('slice_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_observability_incident_boundary()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover - exercised by the gate command
    raise SystemExit(main())
