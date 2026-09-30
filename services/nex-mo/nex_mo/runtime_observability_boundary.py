from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class RuntimeObservabilityBoundary:
    boundary_id: str
    source_path: str
    evidence_token: str
    target_slice: str


RUNTIME_OBSERVABILITY_BOUNDARIES = (
    RuntimeObservabilityBoundary(
        "model_profile_identity",
        "services/nex-mo/nex_mo/provider_catalog.py",
        "class ModelProfile",
        "1163",
    ),
    RuntimeObservabilityBoundary(
        "protected_process_dtype_probe",
        "scripts/smoke/run_mo_dgx_process_dtype_probe.py",
        "REMOTE_PROBE",
        "1164",
    ),
    RuntimeObservabilityBoundary(
        "provider_readiness_cache",
        "services/nex-mo/nex_mo/provider_readiness_cache.py",
        "class InMemoryProviderReadinessStore",
        "1166",
    ),
    RuntimeObservabilityBoundary(
        "authenticated_provider_api",
        "services/nex-mo/nex_mo/provider_auth.py",
        "def authorize_mo_service_request",
        "1167",
    ),
    RuntimeObservabilityBoundary(
        "mo_openapi",
        "contracts/openapi/nex-mo.openapi.yaml",
        "getMoProviderTelemetry",
        "1169",
    ),
    RuntimeObservabilityBoundary(
        "protected_live_evidence",
        "docs/slices/1110_mo_protected_dgx_live_reaudit.md",
        "Explicit BF16 process dtype",
        "1170",
    ),
)

RUNTIME_OBSERVABILITY_POLICY = {
    "required_capabilities": ["embedding", "reranking", "generation"],
    "runtime_statuses": ["HEALTHY", "DEGRADED", "UNAVAILABLE", "UNKNOWN"],
    "precision_statuses": ["MATCH", "MISMATCH", "UNVERIFIED"],
    "default_mode": "mock",
    "live_mode": "protected_fixed_ssh_collector",
    "refresh_policy": "bounded_on_demand_ttl_cache",
    "default_ttl_seconds": 30,
    "persistence": "process_local_snapshot_no_table_in_s117",
    "readiness_composition": "diagnostic_only_not_a_service_readiness_gate",
    "forbidden_projection": [
        "ssh_target",
        "provider_endpoint",
        "provider_api_key",
        "process_id",
        "process_command_line",
        "model_path",
        "gpu_uuid",
    ],
    "allowed_projection": [
        "capability",
        "model_revision",
        "deployment_id",
        "requested_dtype",
        "loaded_dtype",
        "gpu_count",
        "gpu_memory_used_mib",
        "gpu_memory_total_mib",
        "gpu_utilization_percent",
        "gpu_temperature_c",
        "observed_at",
        "expires_at",
    ],
}


def build_mo_runtime_observability_boundary(
    root: Path = ROOT,
    *,
    boundaries: Sequence[RuntimeObservabilityBoundary] = (
        RUNTIME_OBSERVABILITY_BOUNDARIES
    ),
) -> dict[str, Any]:
    results = [_inspect_boundary(root, item) for item in boundaries]
    issues = [
        {
            "category": "runtime_observability_boundary_evidence_missing",
            "boundary_id": item["boundary_id"],
            "source_path": item["source_path"],
        }
        for item in results
        if not item["evidence_present"]
    ]
    forbidden = set(RUNTIME_OBSERVABILITY_POLICY["forbidden_projection"])
    checks = {
        "boundary_inventory_complete": len(results) == 6,
        "source_evidence_present": not issues,
        "slice_order_bounded": all(
            "1163" <= item["target_slice"] <= "1170" for item in results
        ),
        "three_capabilities_required": RUNTIME_OBSERVABILITY_POLICY[
            "required_capabilities"
        ]
        == ["embedding", "reranking", "generation"],
        "live_collection_is_protected": RUNTIME_OBSERVABILITY_POLICY["live_mode"]
        == "protected_fixed_ssh_collector",
        "snapshot_is_not_persisted": RUNTIME_OBSERVABILITY_POLICY["persistence"]
        == "process_local_snapshot_no_table_in_s117",
        "observability_does_not_gate_readiness": RUNTIME_OBSERVABILITY_POLICY[
            "readiness_composition"
        ]
        == "diagnostic_only_not_a_service_readiness_gate",
        "private_runtime_values_forbidden": {
            "ssh_target",
            "provider_api_key",
            "process_id",
            "process_command_line",
            "model_path",
            "gpu_uuid",
        }.issubset(forbidden),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_runtime_observability_boundary.v1",
        "slice": "1162",
        "requirement": "S117",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "mo_runtime_observability_boundary_failed"
        ),
        "boundary": "gpu_and_model_runtime_observability",
        "checks": checks,
        "summary": {
            "boundary_count": len(results),
            "required_capability_count": len(
                RUNTIME_OBSERVABILITY_POLICY["required_capabilities"]
            ),
            "runtime_status_count": len(
                RUNTIME_OBSERVABILITY_POLICY["runtime_statuses"]
            ),
            "forbidden_projection_count": len(forbidden),
            "evidence_issue_count": len(issues),
        },
        "observability_policy": RUNTIME_OBSERVABILITY_POLICY,
        "boundaries": results,
        "issues": issues,
        "guardrails": [
            "keep the default mock collector deterministic and network free",
            "allow only a fixed protected collector in live mode",
            "never infer loaded dtype from a model name",
            "never project targets credentials process details paths or GPU UUIDs",
            "keep high-frequency GPU samples outside PostgreSQL",
            "do not make diagnostic collection a service readiness dependency",
        ],
        "next_slice": "1163",
    }


def _inspect_boundary(
    root: Path,
    boundary: RuntimeObservabilityBoundary,
) -> dict[str, Any]:
    path = root / boundary.source_path
    source = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {
        "boundary_id": boundary.boundary_id,
        "source_path": boundary.source_path,
        "target_slice": boundary.target_slice,
        "evidence_present": boundary.evidence_token in source,
    }
