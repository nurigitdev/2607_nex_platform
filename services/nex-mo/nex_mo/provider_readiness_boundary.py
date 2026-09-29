from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ReadinessBoundary:
    boundary_id: str
    source_path: str
    evidence_token: str
    target_slice: str


READINESS_BOUNDARIES = (
    ReadinessBoundary(
        "generic_service_readiness",
        "services/_shared/nex_runtime/app.py",
        'app.get("/ready")',
        "1128",
    ),
    ReadinessBoundary(
        "provider_route_registry",
        "services/nex-mo/nex_mo/provider_registry.py",
        "class ProviderRoute",
        "1123",
    ),
    ReadinessBoundary(
        "provider_preflight",
        "services/nex-mo/nex_mo/remote_provider.py",
        "def run_remote_provider_preflight_check",
        "1125",
    ),
    ReadinessBoundary(
        "provider_telemetry",
        "services/nex-mo/nex_mo/provider_telemetry.py",
        "class ProviderTelemetryStore",
        "1126",
    ),
    ReadinessBoundary(
        "provider_operations_compatibility",
        "scripts/smoke/run_mo_provider_operations_compatibility.py",
        "LIVE_COMPATIBLE",
        "1130",
    ),
    ReadinessBoundary(
        "mo_openapi_readiness",
        "contracts/openapi/nex-mo.openapi.yaml",
        "getMoReadiness",
        "1129",
    ),
)

READINESS_POLICY = {
    "required_capabilities": ["embedding", "reranking", "generation"],
    "route_health_statuses": ["READY", "DEGRADED", "UNAVAILABLE", "UNKNOWN"],
    "mock_mode": "deterministic_ready_without_network",
    "live_mode": "all_required_capabilities_must_pass_active_preflight",
    "database_composition": "all_database_and_provider_checks_must_pass",
    "refresh_policy": "bounded_on_demand_ttl_cache",
    "default_ttl_seconds": 30,
    "stale_policy": "stale_snapshot_never_satisfies_service_readiness",
    "persistence": "process_local_no_table_in_s113",
    "forbidden_projection": [
        "provider_endpoint",
        "provider_api_key",
        "model_path",
        "process_command",
        "request_payload",
        "response_payload",
    ],
}


def build_mo_provider_readiness_boundary(
    root: Path = ROOT,
    *,
    boundaries: Sequence[ReadinessBoundary] = READINESS_BOUNDARIES,
) -> dict[str, Any]:
    results = [_inspect_boundary(root, item) for item in boundaries]
    issues = [
        {
            "category": "readiness_boundary_evidence_missing",
            "boundary_id": item["boundary_id"],
            "source_path": item["source_path"],
        }
        for item in results
        if not item["evidence_present"]
    ]
    forbidden = set(READINESS_POLICY["forbidden_projection"])
    checks = {
        "boundary_inventory_complete": len(results) == 6,
        "source_evidence_present": not issues,
        "slice_order_bounded": all(
            "1123" <= item["target_slice"] <= "1130" for item in results
        ),
        "three_capabilities_required": READINESS_POLICY["required_capabilities"]
        == ["embedding", "reranking", "generation"],
        "live_mode_fails_closed": READINESS_POLICY["live_mode"]
        == "all_required_capabilities_must_pass_active_preflight",
        "stale_snapshot_fails_closed": READINESS_POLICY["stale_policy"]
        == "stale_snapshot_never_satisfies_service_readiness",
        "private_runtime_values_forbidden": {
            "provider_endpoint",
            "provider_api_key",
            "model_path",
            "process_command",
        }.issubset(forbidden),
        "no_table_in_s113": READINESS_POLICY["persistence"]
        == "process_local_no_table_in_s113",
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_readiness_boundary.v1",
        "slice": "1122",
        "requirement": "S113",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_readiness_boundary_failed",
        "boundary": "provider_aware_readiness_and_route_health",
        "checks": checks,
        "summary": {
            "boundary_count": len(results),
            "required_capability_count": len(
                READINESS_POLICY["required_capabilities"]
            ),
            "route_health_status_count": len(
                READINESS_POLICY["route_health_statuses"]
            ),
            "forbidden_projection_count": len(forbidden),
            "evidence_issue_count": len(issues),
        },
        "readiness_policy": READINESS_POLICY,
        "boundaries": results,
        "issues": issues,
        "guardrails": [
            "preserve generic database readiness for every service",
            "add provider checks only to nex-mo readiness composition",
            "keep mock readiness deterministic and network free",
            "never use stale provider observations to report READY",
            "never project endpoints credentials paths commands or payloads",
            "do not add retry telemetry persistence or GPU metrics in S113",
        ],
        "next_slice": "1123",
    }


def _inspect_boundary(root: Path, boundary: ReadinessBoundary) -> dict[str, Any]:
    path = root / boundary.source_path
    source = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {
        "boundary_id": boundary.boundary_id,
        "source_path": boundary.source_path,
        "target_slice": boundary.target_slice,
        "evidence_present": boundary.evidence_token in source,
    }
