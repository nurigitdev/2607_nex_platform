from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class OperationsIntegrationBoundary:
    boundary_id: str
    source_path: str
    evidence_token: str
    disposition: str
    target_slice: str


OPERATIONS_INTEGRATION_BOUNDARIES = (
    OperationsIntegrationBoundary(
        "catalog_alias_state",
        "services/nex-mo/nex_mo/catalog_lifecycle_service.py",
        "class CatalogLifecycleService",
        "COMPOSE_READ_ONLY",
        "1184",
    ),
    OperationsIntegrationBoundary(
        "provider_route_readiness",
        "services/nex-mo/nex_mo/provider_readiness_service.py",
        "class ProviderReadinessService",
        "COMPOSE_REFRESHABLE",
        "1184",
    ),
    OperationsIntegrationBoundary(
        "durable_provider_telemetry",
        "services/nex-mo/nex_mo/provider_telemetry_runtime.py",
        "def current_remote_provider_telemetry_store",
        "COMPOSE_READ_ONLY",
        "1184",
    ),
    OperationsIntegrationBoundary(
        "gpu_model_runtime",
        "services/nex-mo/nex_mo/runtime_observability_service.py",
        "class RuntimeObservabilityService",
        "COMPOSE_REFRESHABLE",
        "1184",
    ),
    OperationsIntegrationBoundary(
        "authenticated_operations_api",
        "services/nex-mo/nex_mo/provider_auth.py",
        "def authorize_mo_service_request",
        "REUSE",
        "1185",
    ),
    OperationsIntegrationBoundary(
        "protected_remote_execution",
        "scripts/smoke/run_protected_remote_provider_live_smoke.py",
        "def run_protected_remote_provider_live_smoke",
        "EXTEND",
        "1190",
    ),
    OperationsIntegrationBoundary(
        "protected_runtime_observation",
        "scripts/smoke/run_mo_runtime_observability_live_smoke.py",
        "def run_mo_runtime_observability_live_smoke",
        "REUSE",
        "1190",
    ),
    OperationsIntegrationBoundary(
        "actual_test_database",
        "scripts/smoke/run_mo_catalog_lifecycle_postgres_smoke.py",
        "EXPECTED_DATABASE = \"nex_mo_test\"",
        "REUSE_GUARD",
        "1189",
    ),
)


OPERATIONS_INTEGRATION_POLICY = {
    "owner": "nex-mo",
    "required_capabilities": ["embedding", "reranking", "generation"],
    "sources": ["catalog", "readiness", "telemetry", "runtime"],
    "status_precedence": ["UNAVAILABLE", "DEGRADED", "UNKNOWN", "READY"],
    "persistence": "reuse_existing_tables_only",
    "new_tables": [],
    "acceptance_database": "nex_mo_user@nex_mo_test",
    "acceptance_providers": "protected_dgx_vllm_three_capabilities",
    "acceptance_mutation": "bounded_catalog_alias_seed_and_targeted_cleanup",
    "refresh": "explicit_bounded_force_refresh_only",
    "failure_mode": "fail_closed_without_partial_ready",
    "forbidden_projection": [
        "provider_endpoint",
        "provider_api_key",
        "authorization_token",
        "ssh_target",
        "model_path",
        "database_url",
        "request_payload",
        "response_payload",
        "prompt_text",
    ],
}


def build_mo_operations_integration_boundary(
    root: Path = ROOT,
    *,
    boundaries: Sequence[OperationsIntegrationBoundary] = (
        OPERATIONS_INTEGRATION_BOUNDARIES
    ),
) -> dict[str, Any]:
    results = [_inspect_boundary(root, boundary) for boundary in boundaries]
    issues = [
        {
            "category": "operations_integration_boundary_evidence_missing",
            "boundary_id": item["boundary_id"],
            "source_path": item["source_path"],
        }
        for item in results
        if not item["evidence_present"]
    ]
    policy = OPERATIONS_INTEGRATION_POLICY
    checks = {
        "boundary_inventory_complete": len(results) == 8,
        "source_evidence_present": not issues,
        "slice_order_bounded": all(
            "1183" <= item["target_slice"] <= "1190" for item in results
        ),
        "four_operational_sources": policy["sources"]
        == ["catalog", "readiness", "telemetry", "runtime"],
        "three_capabilities_required": policy["required_capabilities"]
        == ["embedding", "reranking", "generation"],
        "degraded_state_precedes_ready": policy["status_precedence"]
        == ["UNAVAILABLE", "DEGRADED", "UNKNOWN", "READY"],
        "no_new_persistence": policy["persistence"]
        == "reuse_existing_tables_only"
        and not policy["new_tables"],
        "actual_protected_acceptance_required": policy["acceptance_database"]
        == "nex_mo_user@nex_mo_test"
        and policy["acceptance_providers"]
        == "protected_dgx_vllm_three_capabilities",
        "evidence_redaction_required": {
            "provider_endpoint",
            "provider_api_key",
            "database_url",
            "request_payload",
            "response_payload",
        }.issubset(policy["forbidden_projection"]),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_operations_integration_boundary.v1",
        "slice": "1182",
        "requirement": "S119",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "mo_operations_integration_boundary_failed"
        ),
        "boundary": "mo_operations_integration_and_protected_live_acceptance",
        "checks": checks,
        "summary": {
            "boundary_count": len(results),
            "source_count": len(policy["sources"]),
            "required_capability_count": len(policy["required_capabilities"]),
            "new_table_count": len(policy["new_tables"]),
            "evidence_issue_count": len(issues),
        },
        "operations_policy": policy,
        "boundaries": results,
        "issues": issues,
        "guardrails": [
            "compose existing service-owned facts without cross-service table reads",
            "never report ready when a required source is unavailable or stale",
            "keep refresh explicit bounded and service authenticated",
            "reuse existing MO tables and add no S119 persistence table",
            "exercise all three live capabilities against the protected DGX profile",
            "use only nex_mo_test and clean every acceptance mutation",
            "exclude endpoints credentials payloads paths and database secrets",
        ],
        "ordered_work": [
            {"slice": "1183", "work_item": "operations snapshot domain"},
            {"slice": "1184", "work_item": "operations integration service"},
            {"slice": "1185", "work_item": "authenticated operations API"},
            {"slice": "1186", "work_item": "acceptance admission and plan"},
            {"slice": "1187", "work_item": "contract and privacy hardening"},
            {"slice": "1188", "work_item": "deterministic integrated acceptance"},
            {"slice": "1189", "work_item": "PostgreSQL operations evidence"},
            {"slice": "1190", "work_item": "protected DGX live acceptance"},
            {"slice": "1191", "work_item": "S119 closure"},
        ],
        "next_slice": "1183" if passed else "blocked",
    }


def _inspect_boundary(
    root: Path,
    boundary: OperationsIntegrationBoundary,
) -> dict[str, Any]:
    path = root / boundary.source_path
    source = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {
        "boundary_id": boundary.boundary_id,
        "source_path": boundary.source_path,
        "disposition": boundary.disposition,
        "target_slice": boundary.target_slice,
        "evidence_present": boundary.evidence_token in source,
    }
