from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class RefactoringBoundary:
    boundary_id: str
    source_path: str
    evidence_token: str
    target_module: str
    target_slice: str


REFACTORING_BOUNDARIES = (
    RefactoringBoundary(
        "public_projection",
        "services/nex-mo/nex_mo/providers.py",
        "def to_wire(self) -> dict[str, Any]:",
        "nex_mo.provider_projection",
        "1113",
    ),
    RefactoringBoundary(
        "catalog_configuration",
        "services/nex-mo/nex_mo/providers.py",
        "def build_model_profile_catalog",
        "nex_mo.provider_catalog",
        "1114",
    ),
    RefactoringBoundary(
        "response_normalization",
        "services/nex-mo/nex_mo/provider_normalization.py",
        "def normalize_remote_generation_response",
        "nex_mo.provider_normalization",
        "1115",
    ),
    RefactoringBoundary(
        "http_transport",
        "services/nex-mo/nex_mo/provider_transport.py",
        "def execute_remote_json_request",
        "nex_mo.provider_transport",
        "1116",
    ),
    RefactoringBoundary(
        "runtime_telemetry",
        "services/nex-mo/nex_mo/provider_telemetry.py",
        "class RemoteProviderTelemetryBucket",
        "nex_mo.provider_telemetry",
        "1117",
    ),
)

PERSISTENCE_DECISION = {
    "decision": "HYBRID_PERSISTENCE_BOUNDARY",
    "durable_postgres_candidates": [
        "provider_catalog",
        "active_alias",
        "activation_history",
        "bounded_usage_aggregate",
    ],
    "external_metrics_candidates": [
        "high_frequency_gpu_samples",
        "high_frequency_runtime_samples",
    ],
    "forbidden_persistence": [
        "provider_endpoint",
        "provider_api_key",
        "model_path",
        "process_command",
        "request_payload",
        "response_payload",
    ],
    "table_creation_slice": None,
}


def build_mo_runtime_hardening_boundary(
    root: Path = ROOT,
    *,
    boundaries: Sequence[RefactoringBoundary] = REFACTORING_BOUNDARIES,
) -> dict[str, Any]:
    results = [_inspect_boundary(root, item) for item in boundaries]
    evidence_issues = [
        {
            "category": "runtime_hardening_evidence_missing",
            "boundary_id": item["boundary_id"],
            "source_path": item["source_path"],
        }
        for item in results
        if not item["evidence_present"]
    ]
    forbidden = set(PERSISTENCE_DECISION["forbidden_persistence"])
    checks = {
        "refactoring_boundaries_complete": len(results) == 5,
        "source_evidence_present": not evidence_issues,
        "target_modules_unique": len({item["target_module"] for item in results})
        == len(results),
        "slice_order_is_monotonic": [item["target_slice"] for item in results]
        == sorted(item["target_slice"] for item in results),
        "persistence_decision_explicit": PERSISTENCE_DECISION["decision"]
        == "HYBRID_PERSISTENCE_BOUNDARY",
        "private_runtime_fields_forbidden": {
            "provider_endpoint",
            "provider_api_key",
            "model_path",
            "process_command",
        }.issubset(forbidden),
        "no_table_in_boundary_slice": PERSISTENCE_DECISION["table_creation_slice"]
        is None,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_runtime_hardening_boundary.v1",
        "slice": "1112",
        "requirement": "S112",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_runtime_hardening_boundary_failed",
        "boundary": "behavior_preserving_provider_runtime_decomposition",
        "checks": checks,
        "summary": {
            "refactoring_boundary_count": len(results),
            "durable_candidate_count": len(
                PERSISTENCE_DECISION["durable_postgres_candidates"]
            ),
            "external_metrics_candidate_count": len(
                PERSISTENCE_DECISION["external_metrics_candidates"]
            ),
            "forbidden_persistence_count": len(forbidden),
            "evidence_issue_count": len(evidence_issues),
        },
        "refactoring_boundaries": results,
        "persistence_decision": PERSISTENCE_DECISION,
        "guardrails": [
            "preserve public provider routes and response shapes",
            "preserve deterministic mock behavior and requester injection",
            "retain compatibility imports until S112 closure",
            "do not add retry readiness or catalog lifecycle features in S112",
            "do not persist endpoints credentials paths commands or payloads",
        ],
        "issues": evidence_issues,
        "next_slice": "1113",
    }


def _inspect_boundary(root: Path, boundary: RefactoringBoundary) -> dict[str, Any]:
    path = root / boundary.source_path
    present = path.is_file() and boundary.evidence_token in path.read_text(
        encoding="utf-8"
    )
    return {
        "boundary_id": boundary.boundary_id,
        "source_path": boundary.source_path,
        "target_module": boundary.target_module,
        "target_slice": boundary.target_slice,
        "evidence_present": present,
    }
