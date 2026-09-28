#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_citation_repair_workflow_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/1051_s105_ae_generation_lifecycle_closure.md",
    "services/nex-ae-api/nex_ae_api/chat.py",
    "services/nex-ae-api/nex_ae_api/async_generation.py",
    "services/nex-ae-api/nex_ae_api/repaired_responses.py",
    "services/nex-ae-api/nex_ae_api/repaired_response_decisions.py",
    "services/nex-cx/nex_cx/citation_repair.py",
    "services/nex-cx/nex_cx/async_generation_worker.py",
    "services/nex-cx/nex_cx/generation_read_model.py",
    "database/nex-ae-api/migrations/0383_ae_repaired_response_handoff_persistence.sql",
    "database/nex-ae-api/migrations/0387_ae_repaired_response_decision_persistence.sql",
    "docs/development_process.md",
    "docs/slices/1052_ae_citation_repair_workflow_boundary_audit.md",
    "docs/README.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "s105_closure",
        "scripts/smoke/run_s105_ae_generation_lifecycle_closure.py",
        '"READY_FOR_S106"',
    ),
    EvidenceToken(
        "ae_quality_projection",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "def grounded_response_quality_contract(",
    ),
    EvidenceToken(
        "ae_async_handoff",
        "services/nex-ae-api/nex_ae_api/async_generation.py",
        "def refresh_async_generation_projection(",
    ),
    EvidenceToken(
        "ae_repaired_handoff",
        "services/nex-ae-api/nex_ae_api/repaired_responses.py",
        "def register_repaired_response_handoff_routes(",
    ),
    EvidenceToken(
        "ae_repaired_decision",
        "services/nex-ae-api/nex_ae_api/repaired_response_decisions.py",
        "def register_repaired_response_decision_routes(",
    ),
    EvidenceToken(
        "cx_bounded_repair",
        "services/nex-cx/nex_cx/citation_repair.py",
        "def generate_with_bounded_citation_repair(",
    ),
    EvidenceToken(
        "cx_async_worker",
        "services/nex-cx/nex_cx/async_generation_worker.py",
        '"citation_repair": generation_result.repair',
    ),
    EvidenceToken(
        "cx_quality_read_model",
        "services/nex-cx/nex_cx/generation_read_model.py",
        '"grounded_response_quality_status"',
    ),
    EvidenceToken(
        "ae_handoff_table",
        "database/nex-ae-api/migrations/0383_ae_repaired_response_handoff_persistence.sql",
        "ae_repaired_response_handoffs",
    ),
    EvidenceToken(
        "ae_decision_table",
        "database/nex-ae-api/migrations/0387_ae_repaired_response_decision_persistence.sql",
        "ae_repaired_response_decisions",
    ),
    EvidenceToken(
        "tiered_gate",
        "docs/development_process.md",
        "Checkpoint Gate",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "1052_ae_citation_repair_workflow_boundary_audit.md",
    ),
)

GAP_RESOLUTION_PATHS = {
    "cx_repair_metadata_not_persisted": (
        "docs/slices/1053_cx_citation_repair_metadata_persistence.md"
    ),
    "ae_workflow_projection_missing": (
        "docs/slices/1054_ae_citation_quality_workflow_projection.md"
    ),
    "owner_scoped_quality_api_missing": (
        "docs/slices/1055_ae_citation_quality_api.md"
    ),
    "legacy_handoff_owner_scope_incomplete": (
        "docs/slices/1056_ae_repaired_response_owner_scope_hardening.md"
    ),
    "async_handoff_workflow_not_durable": (
        "docs/slices/1057_ae_async_citation_workflow_integration.md"
    ),
    "workflow_observability_missing": (
        "docs/slices/1058_ae_citation_repair_workflow_observability.md"
    ),
    "contract_openapi_missing": (
        "docs/slices/1059_ae_citation_repair_contract_hardening.md"
    ),
    "postgres_evidence_missing": (
        "docs/slices/1060_ae_citation_repair_postgres_smoke.md"
    ),
}

GAP_SLICES = {
    name: f"{1053 + index:04d}"
    for index, name in enumerate(GAP_RESOLUTION_PATHS)
}


def run_ae_citation_repair_workflow_boundary_audit(
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
        "s105_handoff_bound": _group_present(tokens, "s105_closure"),
        "ae_quality_projection_reusable": _group_present(
            tokens, "ae_quality_projection"
        ),
        "ae_async_handoff_reusable": _group_present(tokens, "ae_async_handoff"),
        "existing_review_workflow_reusable": all(
            _group_present(tokens, group)
            for group in ("ae_repaired_handoff", "ae_repaired_decision")
        ),
        "cx_bounded_repair_present": all(
            _group_present(tokens, group)
            for group in ("cx_bounded_repair", "cx_async_worker")
        ),
        "cx_quality_read_model_present": _group_present(
            tokens, "cx_quality_read_model"
        ),
        "existing_tables_reusable": all(
            _group_present(tokens, group)
            for group in ("ae_handoff_table", "ae_decision_table")
        ),
        "tiered_quality_cadence_confirmed": _group_present(
            tokens, "tiered_gate"
        ),
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
        "1061",
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1052",
        "requirement": "S106",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "decision": boundary_decision(),
        "summary": {
            "foundation_count": 8,
            "gap_count": len(gap_states),
            "open_gap_count": sum(state == "OPEN" for state in gap_states.values()),
            "resolved_gap_count": sum(
                state == "RESOLVED" for state in gap_states.values()
            ),
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "known_drifts": [
            "cx_worker_repair_projection_is_not_in_generation_read_model",
            "ae_async_refresh_drops_generation_quality_metadata",
            "ae_has_no_citation_quality_workflow_projection",
            "ae_has_no_owner_scoped_citation_quality_route",
            "legacy_repaired_handoff_reads_are_not_owner_filtered",
            "bounded_repair_and_operator_remediation_are_not_distinguished_by_ae",
            "citation_workflow_observability_is_incomplete",
        ],
        "gap_states": gap_states,
        "gap_resolution_paths": GAP_RESOLUTION_PATHS,
        "slice_plan": [
            "1052_boundary_audit",
            "1053_cx_repair_metadata_persistence",
            "1054_ae_workflow_projection",
            "1055_owner_scoped_quality_api",
            "1056_repaired_response_owner_scope_checkpoint",
            "1057_async_handoff_workflow_integration",
            "1058_workflow_observability",
            "1059_contract_openapi_hardening",
            "1060_actual_postgresql_smoke",
            "1061_s106_closure_full_gate",
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
        "scope": "ae_citation_quality_and_repair_workflow_hardening",
        "cx_generation_quality_owner": "nex-cx",
        "ae_workflow_projection_owner": "nex-ae-api",
        "ag_operator_remediation_owner": "nex-ag",
        "bounded_repair_model": "one_inline_attempt_same_retrieval_package",
        "operator_repair_model": "separate_ag_cx_remediation_lineage",
        "repair_modes_must_remain_distinct": True,
        "quality_source": "cx_generation_read_model_metadata",
        "owner_scope": "tenant_and_owner_user_exact_match",
        "ae_persisted_projection": (
            "privacy-safe citation workflow metadata in "
            "ae_chat_interactions.generation_summary"
        ),
        "existing_handoff_tables_reused": True,
        "new_tables_expected": 0,
        "raw_generation_content_in_workflow": False,
        "raw_invalid_output_in_workflow": False,
        "raw_evidence_text_in_workflow": False,
        "actual_postgres_required_slice": "1060",
        "remote_provider_required": False,
        "quality_cadence": {
            "slice_gate": "1052-1061",
            "checkpoint_gate": "1056",
            "full_gate": "1061",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "ae_citation_repair_workflow_boundary=fail "
            f"issues={len(result.get('issues', []))}"
        )
    summary = result["summary"]
    return (
        "ae_citation_repair_workflow_boundary=pass "
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
    result = run_ae_citation_repair_workflow_boundary_audit()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
