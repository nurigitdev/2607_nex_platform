#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_intent_template_policy_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/1021_s102_ae_durable_workspace_chat_closure.md",
    "docs/13_ae_agent_orchestration_contract.md",
    "docs/16_ae_cx_generation_request_package_contract.md",
    "docs/archive/planning/24_prompt_template_output_compatibility_matrix.md",
    "services/nex-ae-api/nex_ae_api/prompts.py",
    "services/nex-ae-api/nex_ae_api/chat.py",
    "services/_shared/nex_runtime/compatibility.py",
    "database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql",
    "database/nex-ae-api/migrations/0029_prompt_registry_seed.sql",
    "docs/development_process.md",
    "docs/slices/1022_ae_intent_template_policy_boundary_audit.md",
    "docs/README.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "s102_handoff",
        "docs/slices/1021_s102_ae_durable_workspace_chat_closure.md",
        "next requirement `S103`",
    ),
    EvidenceToken(
        "ae_orchestration_owner",
        "docs/13_ae_agent_orchestration_contract.md",
        "Build AE generation policy package",
    ),
    EvidenceToken(
        "ae_cx_package",
        "docs/16_ae_cx_generation_request_package_contract.md",
        "client_package_hash",
    ),
    EvidenceToken(
        "compatibility_matrix",
        "docs/archive/planning/24_prompt_template_output_compatibility_matrix.md",
        "Explicit template and prompt versions are required",
    ),
    EvidenceToken(
        "memory_prompt_registry",
        "services/nex-ae-api/nex_ae_api/prompts.py",
        "DEFAULT_AE_PROMPT_STORE = PromptRegistryStore()",
    ),
    EvidenceToken(
        "chat_payload_defaults",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "def build_cx_generation_payload",
    ),
    EvidenceToken(
        "compatibility_foundation",
        "services/_shared/nex_runtime/compatibility.py",
        "DEFAULT_GENERATION_COMPATIBILITY_RULES",
    ),
    EvidenceToken(
        "registry_schema",
        "database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql",
        "ae_prompt_render_events",
    ),
    EvidenceToken(
        "registry_seed",
        "database/nex-ae-api/migrations/0029_prompt_registry_seed.sql",
        "ae.grounded_chat.default",
    ),
    EvidenceToken(
        "tiered_gate",
        "docs/development_process.md",
        "Checkpoint Gate",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "1022_ae_intent_template_policy_boundary_audit.md",
    ),
)

GAP_RESOLUTION_PATHS = {
    "intent_contract_missing": (
        "docs/slices/1023_ae_intent_execution_mode_contract.md"
    ),
    "durable_registry_adapter_missing": (
        "docs/slices/1024_ae_prompt_template_registry_postgresql_adapter.md"
    ),
    "runtime_policy_resolver_missing": (
        "docs/slices/1025_ae_runtime_compatibility_policy_resolver.md"
    ),
    "policy_api_missing": (
        "docs/slices/1026_ae_runtime_policy_inspection_api.md"
    ),
    "generation_policy_package_missing": (
        "docs/slices/1027_ae_generation_policy_package.md"
    ),
    "chat_policy_wiring_missing": (
        "docs/slices/1028_ae_chat_runtime_policy_orchestration.md"
    ),
    "contract_observability_missing": (
        "docs/slices/1029_ae_runtime_policy_contract_openapi_observability.md"
    ),
    "postgres_evidence_missing": (
        "docs/slices/1030_ae_runtime_policy_postgresql_smoke.md"
    ),
}

GAP_SLICES = {
    name: f"{1023 + index:04d}"
    for index, name in enumerate(GAP_RESOLUTION_PATHS)
}


def run_ae_intent_template_policy_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_PATHS
    ]
    tokens = [
        {
            "group": item.group,
            "path": item.relative_path,
            "present": item.token in _read_text(root / item.relative_path),
        }
        for item in EVIDENCE_TOKENS
    ]
    gap_states = {
        name: "RESOLVED" if (root / path).is_file() else "OPEN"
        for name, path in GAP_RESOLUTION_PATHS.items()
    }
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s102_handoff_bound": _group_present(tokens, "s102_handoff"),
        "ae_policy_ownership_confirmed": all(
            _group_present(tokens, group)
            for group in ("ae_orchestration_owner", "ae_cx_package")
        ),
        "versioned_compatibility_required": _group_present(
            tokens, "compatibility_matrix"
        ),
        "registry_schema_reusable": all(
            _group_present(tokens, group)
            for group in ("registry_schema", "registry_seed")
        ),
        "runtime_gaps_confirmed": all(
            _group_present(tokens, group)
            for group in (
                "memory_prompt_registry",
                "chat_payload_defaults",
                "compatibility_foundation",
            )
        ),
        "tiered_quality_cadence_confirmed": _group_present(tokens, "tiered_gate"),
        "implementation_gaps_accounted_for": len(gap_states) == 8,
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
    passed = all(checks.values()) and not issues
    next_slice = next(
        (GAP_SLICES[name] for name, state in gap_states.items() if state == "OPEN"),
        "1031",
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1022",
        "requirement": "S103",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "decision": boundary_decision(),
        "summary": {
            "foundation_count": 7,
            "gap_count": len(gap_states),
            "open_gap_count": sum(state == "OPEN" for state in gap_states.values()),
            "resolved_gap_count": sum(
                state == "RESOLVED" for state in gap_states.values()
            ),
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "known_drifts": [
            "runtime_prompt_registry_is_process_local",
            "chat_generation_defaults_bypass_policy_resolution",
            "general_answer_reuses_grounded_prompt_binding",
            "document_generation_mode_names_are_not_canonical",
            "resolved_policy_snapshot_is_not_persisted",
        ],
        "gap_states": gap_states,
        "gap_resolution_paths": GAP_RESOLUTION_PATHS,
        "slice_plan": [
            "1022_boundary_audit",
            "1023_intent_execution_mode_contract",
            "1024_prompt_template_postgresql_adapter",
            "1025_runtime_compatibility_policy_resolver",
            "1026_runtime_policy_inspection_api",
            "1027_generation_policy_package",
            "1028_chat_runtime_policy_orchestration",
            "1029_contract_openapi_observability",
            "1030_actual_postgresql_smoke",
            "1031_s103_closure_full_gate",
        ],
        "checks": checks,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": next_slice,
    }


def boundary_decision() -> dict[str, Any]:
    return {
        "owner": "nex-ae-api",
        "scope": "intent_template_prompt_runtime_policy_orchestration",
        "explicit_user_mode_precedence": True,
        "canonical_execution_modes": [
            "GENERAL_ANSWER",
            "GROUNDED_ANSWER",
            "DOCUMENT_SUMMARY",
            "DOCUMENT_GENERATION",
        ],
        "version_policy": "explicit_versions_no_latest_in_resolved_records",
        "compatibility_policy": "exact_active_rule_required_fail_closed",
        "registry_tables": [
            "ae_prompt_templates",
            "ae_prompt_template_versions",
            "ae_prompt_bindings",
            "ae_prompt_render_events",
        ],
        "policy_snapshot_storage": "ae_chat_interactions.generation_summary",
        "raw_prompt_in_policy_snapshot": False,
        "direct_provider_runtime_fields_allowed": False,
        "new_tables_expected": 0,
        "actual_postgres_required_slice": "1030",
        "remote_provider_required": False,
        "quality_cadence": {
            "slice_gate": "1022-1031",
            "checkpoint_gate": "1026",
            "full_gate": "1031",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "ae_intent_template_policy_boundary=fail "
            f"issues={len(result.get('issues', []))}"
        )
    summary = result["summary"]
    return (
        "ae_intent_template_policy_boundary=pass "
        f"foundations={summary['foundation_count']} gaps={summary['gap_count']} "
        f"open={summary['open_gap_count']} next={result['next_slice']} "
        f"issues={summary['issue_count']}"
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _group_present(items: list[dict[str, Any]], group: str) -> bool:
    return any(item["group"] == group and item["present"] for item in items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_intent_template_policy_boundary_audit()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
