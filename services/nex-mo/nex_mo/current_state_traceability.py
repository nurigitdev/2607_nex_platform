from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[3]
REQUIRED_REQUIREMENTS = tuple(f"MO-FR-{number:03d}" for number in range(1, 6))
REQUIRED_LAYERS = ("requirement", "implementation", "test", "operations")


@dataclass(frozen=True)
class EvidenceRef:
    layer: str
    relative_path: str
    token: str | None = None


@dataclass(frozen=True)
class CapabilitySpec:
    requirement_id: str
    capability: str
    implementation_status: str
    gap: str | None
    evidence: tuple[EvidenceRef, ...]


CAPABILITY_SPECS = (
    CapabilitySpec(
        "MO-FR-001",
        "provider registry and capability aliases",
        "IMPLEMENTED",
        None,
        (
            EvidenceRef("requirement", "docs/30_service_specific_requirement_partition.md", "MO-FR-001"),
            EvidenceRef("implementation", "services/nex-mo/nex_mo/providers.py", "def resolve_provider_route"),
            EvidenceRef("implementation", "services/nex-mo/nex_mo/providers.py", "def list_provider_routes"),
            EvidenceRef("test", "tests/test_nex_mo_providers.py", "test_provider_registry_contains_required_mock_capabilities"),
            EvidenceRef("operations", "services/nex-mo/README.md", "GET /api/v1/provider-routes"),
        ),
    ),
    CapabilitySpec(
        "MO-FR-002",
        "embedding reranking and generation execution",
        "IMPLEMENTED",
        None,
        (
            EvidenceRef("requirement", "docs/30_service_specific_requirement_partition.md", "MO-FR-002"),
            EvidenceRef("implementation", "services/nex-mo/nex_mo/providers.py", "def create_embedding_response"),
            EvidenceRef("implementation", "services/nex-mo/nex_mo/providers.py", "def create_rerank_response"),
            EvidenceRef("implementation", "services/nex-mo/nex_mo/providers.py", "def create_generation_response"),
            EvidenceRef("test", "tests/test_nex_mo_remote_provider.py", "test_remote_embedding_execution"),
            EvidenceRef("operations", "services/nex-mo/README.md", "POST /api/v1/generations"),
        ),
    ),
    CapabilitySpec(
        "MO-FR-003",
        "provider health readiness usage latency and failure metadata",
        "PARTIAL",
        "provider-aware readiness is not yet composed into /ready",
        (
            EvidenceRef("requirement", "docs/30_service_specific_requirement_partition.md", "MO-FR-003"),
            EvidenceRef(
                "implementation",
                "services/nex-mo/nex_mo/provider_telemetry.py",
                "class RemoteProviderTelemetryBucket",
            ),
            EvidenceRef("implementation", "services/nex-mo/nex_mo/providers.py", '"/api/v1/provider-telemetry"'),
            EvidenceRef("test", "tests/test_nex_mo_providers.py", "test_provider_telemetry_endpoint"),
            EvidenceRef("operations", "services/nex-mo/README.md", "GET /api/v1/provider-telemetry"),
        ),
    ),
    CapabilitySpec(
        "MO-FR-004",
        "deterministic mock and protected live modes",
        "IMPLEMENTED",
        None,
        (
            EvidenceRef("requirement", "docs/30_service_specific_requirement_partition.md", "MO-FR-004"),
            EvidenceRef(
                "implementation",
                "services/nex-mo/nex_mo/provider_catalog.py",
                'DEFAULT_PROVIDER_MODE = "mock"',
            ),
            EvidenceRef("implementation", "scripts/smoke/run_protected_remote_provider_live_smoke.py"),
            EvidenceRef("test", "tests/test_protected_remote_provider_live_smoke.py"),
            EvidenceRef("operations", "services/nex-mo/README.md", "NEX_PROTECTED_REMOTE_PROVIDER_LIVE_SMOKE=1"),
        ),
    ),
    CapabilitySpec(
        "MO-FR-005",
        "vLLM and provider resource metrics",
        "PARTIAL",
        "GPU memory utilization and loaded dtype are not available in the MO metrics projection",
        (
            EvidenceRef("requirement", "docs/30_service_specific_requirement_partition.md", "MO-FR-005"),
            EvidenceRef("implementation", "services/nex-mo/nex_mo/remote_provider.py", "def list_remote_provider_telemetry"),
            EvidenceRef("test", "tests/test_nex_mo_remote_provider.py", "test_remote_provider_telemetry"),
            EvidenceRef("operations", "services/nex-mo/README.md", "--dtype bfloat16"),
        ),
    ),
)


def build_mo_capability_traceability_inventory(
    root: Path = ROOT,
    *,
    specs: Iterable[CapabilitySpec] = CAPABILITY_SPECS,
) -> dict[str, Any]:
    selected = tuple(specs)
    capabilities: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for spec in selected:
        evidence = [_inspect_evidence(root, ref) for ref in spec.evidence]
        layers = {item["layer"] for item in evidence if item["present"]}
        missing_layers = sorted(set(REQUIRED_LAYERS) - layers)
        missing_evidence = [item for item in evidence if not item["present"]]
        traceable = not missing_layers and not missing_evidence
        capabilities.append(
            {
                "requirement_id": spec.requirement_id,
                "capability": spec.capability,
                "implementation_status": spec.implementation_status,
                "gap": spec.gap,
                "traceable": traceable,
                "missing_layers": missing_layers,
                "evidence": evidence,
            }
        )
        issues.extend(
            {
                "category": "evidence_missing",
                "requirement_id": spec.requirement_id,
                "path": item["path"],
                "layer": item["layer"],
            }
            for item in missing_evidence
        )
        issues.extend(
            {
                "category": "layer_missing",
                "requirement_id": spec.requirement_id,
                "layer": layer,
            }
            for layer in missing_layers
        )

    requirement_ids = [item.requirement_id for item in selected]
    checks = {
        "requirement_set_complete": tuple(requirement_ids) == REQUIRED_REQUIREMENTS,
        "requirement_ids_unique": len(requirement_ids) == len(set(requirement_ids)),
        "all_capabilities_traceable": all(item["traceable"] for item in capabilities),
        "partial_capabilities_have_explicit_gaps": all(
            spec.implementation_status != "PARTIAL" or bool(spec.gap)
            for spec in selected
        ),
    }
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    return {
        "inventory_schema_version": "mo_capability_traceability_inventory.v1",
        "slice": "1103",
        "requirement": "S111",
        "status": status,
        "failure_code": None if status == "PASS" else "mo_traceability_inventory_failed",
        "checks": checks,
        "summary": {
            "requirement_count": len(capabilities),
            "traceable_count": sum(item["traceable"] for item in capabilities),
            "implemented_count": sum(
                item["implementation_status"] == "IMPLEMENTED"
                for item in capabilities
            ),
            "partial_count": sum(
                item["implementation_status"] == "PARTIAL"
                for item in capabilities
            ),
            "evidence_count": sum(len(item["evidence"]) for item in capabilities),
        },
        "decision": {
            "traceability_is_not_acceptance": True,
            "partial_requirements_are_s112_inputs": True,
            "new_table_required": False,
        },
        "capabilities": capabilities,
        "issues": issues,
    }


def _inspect_evidence(root: Path, ref: EvidenceRef) -> dict[str, Any]:
    path = root / ref.relative_path
    text = path.read_text(encoding="utf-8") if path.is_file() and ref.token else ""
    present = path.is_file() and (ref.token is None or ref.token in text)
    return {
        "layer": ref.layer,
        "path": ref.relative_path,
        "token_checked": ref.token is not None,
        "present": present,
    }
