#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "mo_current_state_reaudit_boundary.v1"
SLICE_ID = "1102"
REQUIREMENT = "S111"
BOUNDARY = "mo_current_state_reaudit_and_refactoring_checkpoint"


@dataclass(frozen=True)
class RequiredPath:
    name: str
    relative_path: str


@dataclass(frozen=True)
class TokenRequirement:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    RequiredPath(
        "s110_closure",
        "scripts/smoke/run_s110_ae_mvp_acceptance_operations_closure.py",
    ),
    RequiredPath("mo_readme", "services/nex-mo/README.md"),
    RequiredPath("mo_runtime", "services/nex-mo/nex_mo/main.py"),
    RequiredPath("provider_registry", "services/nex-mo/nex_mo/providers.py"),
    RequiredPath("remote_transport", "services/nex-mo/nex_mo/remote_provider.py"),
    RequiredPath("mo_openapi", "contracts/openapi/nex-mo.openapi.yaml"),
    RequiredPath(
        "generation_contract",
        "docs/17_cx_mo_generation_provider_contract.md",
    ),
    RequiredPath(
        "service_requirements",
        "docs/30_service_specific_requirement_partition.md",
    ),
    RequiredPath("testing_strategy", "docs/34_testing_strategy_v0_1_detail.md"),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh"),
    RequiredPath("docs_index", "docs/README.md"),
    RequiredPath(
        "slice_doc",
        "docs/slices/1102_mo_current_state_reaudit_boundary.md",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s110_handoff",
        "scripts/smoke/run_s110_ae_mvp_acceptance_operations_closure.py",
        '"next_requirement": "S111"',
    ),
    TokenRequirement(
        "mo_app",
        "services/nex-mo/nex_mo/main.py",
        "register_mock_provider_routes(app)",
    ),
    TokenRequirement(
        "provider_registry",
        "services/nex-mo/nex_mo/provider_registry.py",
        "class ProviderRoute",
    ),
    TokenRequirement(
        "provider_profiles",
        "services/nex-mo/nex_mo/provider_catalog.py",
        "class ModelProfile",
    ),
    TokenRequirement(
        "remote_transport",
        "services/nex-mo/nex_mo/remote_provider.py",
        "class RemoteProviderExecutionConfig",
    ),
    TokenRequirement(
        "remote_telemetry",
        "services/nex-mo/nex_mo/provider_telemetry.py",
        "class RemoteProviderTelemetryBucket",
    ),
    TokenRequirement(
        "mo_requirements",
        "docs/30_service_specific_requirement_partition.md",
        "MO-FR-005",
    ),
    TokenRequirement(
        "route_privacy",
        "docs/17_cx_mo_generation_provider_contract.md",
        "it never exposes provider URL or model file path",
    ),
    TokenRequirement(
        "coverage_policy",
        "docs/34_testing_strategy_v0_1_detail.md",
        "Branch coverage",
    ),
    TokenRequirement(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_mo_current_state_reaudit_boundary.py",
    ),
    TokenRequirement(
        "docs_index",
        "docs/README.md",
        "1102_mo_current_state_reaudit_boundary.md",
    ),
)


def run_mo_current_state_reaudit_boundary(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = [
        {
            "name": item.name,
            "path": item.relative_path,
            "present": (root / item.relative_path).is_file(),
        }
        for item in REQUIRED_PATHS
    ]
    tokens = [
        {
            "group": item.group,
            "path": item.relative_path,
            "present": item.token in _read_text(root / item.relative_path),
        }
        for item in TOKEN_REQUIREMENTS
    ]
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s110_handoff_ready": _group_present(tokens, "s110_handoff"),
        "mo_runtime_reusable": all(
            _group_present(tokens, group)
            for group in (
                "mo_app",
                "provider_registry",
                "provider_profiles",
                "remote_transport",
                "remote_telemetry",
            )
        ),
        "requirements_and_privacy_inputs_reusable": all(
            _group_present(tokens, group)
            for group in (
                "mo_requirements",
                "route_privacy",
                "coverage_policy",
            )
        ),
    }
    issues = [
        {"category": "path_missing", "path": item["path"]}
        for item in paths
        if not item["present"]
    ]
    issues.extend(
        {
            "category": "source_token_missing",
            "path": item["path"],
            "group": item["group"],
        }
        for item in tokens
        if not item["present"]
    )
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": SLICE_ID,
        "requirement": REQUIREMENT,
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "mo_current_state_reaudit_boundary_failed"
        ),
        "boundary": BOUNDARY,
        "decision": {
            "owner": "nex-mo",
            "audit_scope": "mo_fr_001_through_005",
            "repository_state_is_primary_evidence": True,
            "legacy_provider_profiles_are_compatibility_only": True,
            "refactor_before_feature_when_needed": True,
            "actual_test_database_evidence_required": False,
            "protected_live_provider_evidence_required": True,
            "new_table_required": False,
            "existing_mo_records_mutated": False,
            "next_requirement": "S112",
            "decision_status": "FROZEN",
        },
        "audit_surfaces": [
            "provider_registry_and_capability_aliases",
            "model_catalog_and_runtime_configuration",
            "remote_http_transport_and_normalization",
            "model_precision_and_resource_safety",
            "credentials_route_privacy_and_service_claims",
            "contracts_and_api_drift",
            "timeouts_failures_telemetry_and_readiness",
            "protected_live_embedding_reranking_and_generation",
        ],
        "deferred_scope": [
            "durable_provider_control_plane",
            "production_secret_manager_activation",
            "production_multi_dgx_routing_and_failover",
            "production_load_and_disaster_recovery_certification",
        ],
        "slice_plan": [
            "1102_boundary_audit",
            "1103_capability_traceability_inventory",
            "1104_provider_catalog_configuration_drift_audit",
            "1105_remote_transport_runtime_coupling_audit",
            "1106_privacy_refactoring_checkpoint",
            "1107_precision_resource_safety_audit",
            "1108_contract_api_drift_audit",
            "1109_resilience_telemetry_readiness_audit",
            "1110_protected_live_provider_reaudit",
            "1111_s111_closure_s112_handoff",
        ],
        "required_paths": paths,
        "required_tokens": tokens,
        "checks": checks,
        "issues": issues,
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _group_present(items: list[dict[str, Any]], group: str) -> bool:
    matching = [item for item in items if item["group"] == group]
    return bool(matching) and all(item["present"] for item in matching)


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "mo_current_state_reaudit_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    decision = evidence.get("decision") or {}
    return (
        "mo_current_state_reaudit_boundary=pass "
        f"scope={decision.get('audit_scope')} "
        f"owner={decision.get('owner')} "
        f"live_required={decision.get('protected_live_provider_evidence_required')} "
        f"new_table={decision.get('new_table_required')} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_current_state_reaudit_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
