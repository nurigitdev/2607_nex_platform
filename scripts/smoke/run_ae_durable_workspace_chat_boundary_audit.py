#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_durable_workspace_chat_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/1011_s101_ae_current_state_reaudit_closure.md",
    "services/nex-ae-api/nex_ae_api/workspace.py",
    "services/nex-ae-api/nex_ae_api/chat.py",
    "services/nex-ae-api/nex_ae_api/route_auth.py",
    "database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql",
    "database/nex-ae-api/migrations/0407_ae_chat_artifact_refs_foundation.sql",
    "docs/development_process.md",
    "docs/slices/1012_ae_durable_workspace_chat_boundary_audit.md",
    "docs/README.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "s101_handoff",
        "docs/slices/1011_s101_ae_current_state_reaudit_closure.md",
        "READY_FOR_TARGETED_S102_HARDENING",
    ),
    EvidenceToken(
        "workspace_memory_store",
        "services/nex-ae-api/nex_ae_api/workspace.py",
        "class WorkspaceStateStore",
    ),
    EvidenceToken(
        "chat_sql_store",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "class SqlAlchemyChatInteractionStore",
    ),
    EvidenceToken(
        "shared_route_auth",
        "services/nex-ae-api/nex_ae_api/route_auth.py",
        "class AeFacadeRouteAuthContext",
    ),
    EvidenceToken(
        "chat_schema",
        "database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql",
        "ae_chat_interactions",
    ),
    EvidenceToken(
        "artifact_ref_schema",
        "database/nex-ae-api/migrations/0407_ae_chat_artifact_refs_foundation.sql",
        "ae_chat_artifact_refs",
    ),
    EvidenceToken(
        "tiered_gate",
        "docs/development_process.md",
        "Checkpoint Gate",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "1012_ae_durable_workspace_chat_boundary_audit.md",
    ),
)

GAP_RESOLUTION_PATHS = {
    "shared_owner_scope_contract_missing": (
        "docs/slices/1013_ae_workspace_chat_owner_scope_contract.md"
    ),
    "workspace_schema_missing": (
        "docs/slices/1014_ae_workspace_activity_persistence_schema.md"
    ),
    "workspace_repository_missing": (
        "docs/slices/1015_ae_workspace_sqlalchemy_repository.md"
    ),
    "workspace_route_wiring_missing": (
        "docs/slices/1016_ae_owner_scoped_workspace_api.md"
    ),
    "chat_owner_scope_missing": (
        "docs/slices/1017_ae_owner_scoped_chat_persistence_api.md"
    ),
    "durable_orchestration_missing": (
        "docs/slices/1018_ae_durable_workspace_chat_orchestration.md"
    ),
    "contract_observability_missing": (
        "docs/slices/1019_ae_workspace_chat_contract_openapi_observability.md"
    ),
    "postgres_evidence_missing": (
        "docs/slices/1020_ae_workspace_chat_postgresql_smoke.md"
    ),
}

GAP_SLICES = {
    name: f"{1013 + index:04d}"
    for index, name in enumerate(GAP_RESOLUTION_PATHS)
}


def run_ae_durable_workspace_chat_boundary_audit(
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
        "s101_handoff_bound": _group_present(tokens, "s101_handoff"),
        "workspace_gap_confirmed": _group_present(tokens, "workspace_memory_store"),
        "chat_foundation_reusable": all(
            _group_present(tokens, group)
            for group in ("chat_sql_store", "chat_schema", "artifact_ref_schema")
        ),
        "shared_auth_reusable": _group_present(tokens, "shared_route_auth"),
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
        "1021",
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1012",
        "requirement": "S102",
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
        "gap_states": gap_states,
        "gap_resolution_paths": GAP_RESOLUTION_PATHS,
        "slice_plan": [
            "1012_boundary_audit",
            "1013_shared_owner_scope_contract",
            "1014_workspace_activity_schema",
            "1015_workspace_sqlalchemy_repository",
            "1016_owner_scoped_workspace_api_checkpoint",
            "1017_owner_scoped_chat_repository_api",
            "1018_durable_workspace_chat_orchestration",
            "1019_contract_openapi_observability",
            "1020_actual_postgresql_smoke",
            "1021_s102_closure_full_gate",
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
        "scope": "durable_workspace_and_chat_orchestration",
        "workspace_tables": ["ae_workspaces", "ae_workspace_activities"],
        "chat_table": "ae_chat_interactions",
        "chat_workspace_link": "nullable_for_legacy_service_compatibility",
        "browser_owner_authority": "validated_oa_claim",
        "service_owner_authority": "validated_service_claim_and_explicit_scope",
        "cross_owner_behavior": "not_found",
        "private_message_body_persisted": False,
        "new_tables_expected": 2,
        "remote_provider_required": False,
        "quality_cadence": {
            "slice_gate": "1012-1021",
            "checkpoint_gate": "1016",
            "full_gate": "1021",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "ae_durable_workspace_chat_boundary=fail "
            f"issues={len(result.get('issues', []))}"
        )
    summary = result["summary"]
    return (
        "ae_durable_workspace_chat_boundary=pass "
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
    result = run_ae_durable_workspace_chat_boundary_audit()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
