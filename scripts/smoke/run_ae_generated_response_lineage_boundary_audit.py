#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_generated_response_lineage_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/1061_s106_ae_citation_repair_workflow_closure.md",
    "docs/13_ae_agent_orchestration_contract.md",
    "docs/29_nex_platform_mvp_srs_v0_1_assembly.md",
    "services/nex-cx/nex_cx/generation_handoff.py",
    "services/nex-ae-api/nex_ae_api/async_generation.py",
    "services/nex-ae-api/nex_ae_api/chat.py",
    "services/nex-ae-api/nex_ae_api/workspace_chat_orchestration.py",
    "services/nex-ae-api/nex_ae_api/workspace_chat_observability.py",
    "database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql",
    "database/nex-ae-api/migrations/1014_ae_workspace_activity_persistence.sql",
    "docs/development_process.md",
    "docs/slices/1062_ae_generated_response_lineage_boundary_audit.md",
    "docs/README.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "s106_closure",
        "scripts/smoke/run_s106_ae_citation_repair_workflow_closure.py",
        '"READY_FOR_S107"',
    ),
    EvidenceToken(
        "cx_private_handoff",
        "services/nex-cx/nex_cx/generation_handoff.py",
        'content = read_model.get_content(',
    ),
    EvidenceToken(
        "cx_owner_scope",
        "services/nex-cx/nex_cx/generation_handoff.py",
        '"owner_scope_enforced": True',
    ),
    EvidenceToken(
        "ae_transient_content",
        "services/nex-ae-api/nex_ae_api/async_generation.py",
        '"content": content["content"] if content is not None else None',
    ),
    EvidenceToken(
        "ae_ready_persisted",
        "contracts/examples/generation/ae_async_chat_refresh.ready.json",
        '"content_persisted_by_ae": true',
    ),
    EvidenceToken(
        "ae_chat_metadata_store",
        "services/nex-ae-api/nex_ae_api/chat.py",
        '"generation_summary"',
    ),
    EvidenceToken(
        "ae_sql_chat_store",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "class SqlAlchemyChatInteractionStore:",
    ),
    EvidenceToken(
        "workspace_activity",
        "services/nex-ae-api/nex_ae_api/workspace_chat_orchestration.py",
        "def append_persisted_workspace_chat_activity(",
    ),
    EvidenceToken(
        "metadata_observability",
        "services/nex-ae-api/nex_ae_api/workspace_chat_observability.py",
        '"response_content_included": False',
    ),
    EvidenceToken(
        "ae_chat_table",
        "database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql",
        "CREATE TABLE IF NOT EXISTS ae_chat_interactions",
    ),
    EvidenceToken(
        "response_requirement",
        "docs/13_ae_agent_orchestration_contract.md",
        "Persists chat message, artifact links, lineage, and activity.",
    ),
    EvidenceToken(
        "tiered_gate",
        "docs/development_process.md",
        "Checkpoint Gate",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "1062_ae_generated_response_lineage_boundary_audit.md",
    ),
)

GAP_RESOLUTION_PATHS = {
    "private_response_storage_missing": (
        "docs/slices/1063_ae_private_generated_response_storage.md"
    ),
    "chat_lineage_projection_missing": (
        "docs/slices/1064_ae_generated_response_lineage_projection.md"
    ),
    "owner_scoped_response_api_missing": (
        "docs/slices/1065_ae_generated_response_api.md"
    ),
    "async_handoff_response_not_durable": (
        "docs/slices/1066_ae_async_response_handoff_integration.md"
    ),
    "retry_repair_lineage_incomplete": (
        "docs/slices/1067_ae_generated_response_retry_repair_lineage.md"
    ),
    "response_observability_missing": (
        "docs/slices/1068_ae_generated_response_observability.md"
    ),
    "contract_openapi_missing": (
        "docs/slices/1069_ae_generated_response_contract_hardening.md"
    ),
    "postgres_evidence_missing": (
        "docs/slices/1070_ae_generated_response_postgres_smoke.md"
    ),
}

GAP_SLICES = {
    name: f"{1063 + index:04d}"
    for index, name in enumerate(GAP_RESOLUTION_PATHS)
}


def run_ae_generated_response_lineage_boundary_audit(
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
        "s106_handoff_bound": _group_present(tokens, "s106_closure"),
        "cx_private_handoff_reusable": all(
            _group_present(tokens, group)
            for group in ("cx_private_handoff", "cx_owner_scope")
        ),
        "ae_durable_ready_contract_confirmed": all(
            _group_present(tokens, group)
            for group in ("ae_transient_content", "ae_ready_persisted")
        ),
        "ae_chat_metadata_store_reusable": all(
            _group_present(tokens, group)
            for group in ("ae_chat_metadata_store", "ae_sql_chat_store")
        ),
        "workspace_lineage_surfaces_reusable": all(
            _group_present(tokens, group)
            for group in ("workspace_activity", "metadata_observability")
        ),
        "ae_chat_table_reusable": _group_present(tokens, "ae_chat_table"),
        "response_requirement_confirmed": _group_present(
            tokens, "response_requirement"
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
        "1071",
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1062",
        "requirement": "S107",
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
            "ready_handoff_content_is_returned_but_not_persisted_by_ae",
            "ae_chat_has_no_private_generated_response_storage_adapter",
            "ae_chat_generation_summary_has_no_canonical_response_lineage",
            "ae_has_no_owner_scoped_generated_response_read_route",
            "async_restart_read_cannot_recover_owner_response_content",
            "retry_and_bounded_repair_response_lineage_is_not_unified",
            "response_observability_does_not_report_safe_lineage_metadata",
        ],
        "gap_states": gap_states,
        "gap_resolution_paths": GAP_RESOLUTION_PATHS,
        "slice_plan": [
            "1062_boundary_audit",
            "1063_private_response_storage",
            "1064_chat_lineage_projection_persistence",
            "1065_owner_scoped_response_api",
            "1066_async_handoff_integration_checkpoint",
            "1067_retry_repair_lineage",
            "1068_response_observability",
            "1069_contract_openapi_hardening",
            "1070_actual_postgresql_smoke",
            "1071_s107_closure_full_gate",
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
        "scope": "ae_generated_response_and_chat_lineage_integration",
        "cx_generation_source_owner": "nex-cx",
        "ae_chat_response_owner": "nex-ae-api",
        "ae_web_consumer": "nex-ae-web",
        "owner_scope": "tenant_and_owner_user_exact_match",
        "content_storage_model": "private_storage_outside_postgresql",
        "metadata_storage_model": "ae_chat_interactions.generation_summary",
        "default_local_storage_root": "/data/nex-platform/ae/chat-responses",
        "storage_root_env": "NEX_AE_CHAT_RESPONSE_STORAGE_ROOT",
        "logical_storage_ref_scheme": "ae://chat-responses/",
        "database_table_reused": "ae_chat_interactions",
        "new_tables_expected": 0,
        "raw_response_in_postgresql": False,
        "raw_response_in_operational_events": False,
        "storage_path_in_public_api": False,
        "restart_safe_response_required": True,
        "idempotency_key": (
            "interaction_id+cx_generation_id+content_sha256"
        ),
        "retry_lineage_model": "parent_interaction_and_parent_response_refs",
        "bounded_repair_lineage_model": "same_cx_generation_final_content",
        "actual_postgres_required_slice": "1070",
        "remote_provider_required": False,
        "quality_cadence": {
            "slice_gate": "1062-1071",
            "checkpoint_gate": "1066",
            "full_gate": "1071",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "ae_generated_response_lineage_boundary=fail "
            f"issues={len(result.get('issues', []))}"
        )
    summary = result["summary"]
    return (
        "ae_generated_response_lineage_boundary=pass "
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
    result = run_ae_generated_response_lineage_boundary_audit()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
