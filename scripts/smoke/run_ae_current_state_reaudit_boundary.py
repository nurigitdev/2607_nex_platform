#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_current_state_reaudit_boundary.v1"
SLICE_ID = "1002"
REQUIREMENT = "S101"
BOUNDARY = "ae_current_state_reaudit_and_refactoring_checkpoint"


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
        "s100_closure",
        "scripts/smoke/run_s100_cx_mvp_integration_ae_handoff_closure.py",
    ),
    RequiredPath("ae_api_readme", "services/nex-ae-api/README.md"),
    RequiredPath("ae_api_runtime", "services/nex-ae-api/nex_ae_api/main.py"),
    RequiredPath("ae_workspace", "services/nex-ae-api/nex_ae_api/workspace.py"),
    RequiredPath("ae_chat", "services/nex-ae-api/nex_ae_api/chat.py"),
    RequiredPath("ae_uploads", "services/nex-ae-api/nex_ae_api/uploads.py"),
    RequiredPath("ae_artifacts", "services/nex-ae-api/nex_ae_api/artifacts.py"),
    RequiredPath("ae_auth", "services/nex-ae-api/nex_ae_api/auth_sessions.py"),
    RequiredPath("ae_web_readme", "apps/nex-ae-web/README.md"),
    RequiredPath("ae_web_runtime", "apps/nex-ae-web/src/main.js"),
    RequiredPath(
        "ae_latest_migration",
        "database/nex-ae-api/migrations/0612_ae_worker_result_persistence.sql",
    ),
    RequiredPath("ae_openapi", "contracts/openapi/nex-ae-api.openapi.yaml"),
    RequiredPath(
        "service_requirements",
        "docs/30_service_specific_requirement_partition.md",
    ),
    RequiredPath("testing_strategy", "docs/34_testing_strategy_v0_1_detail.md"),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh"),
    RequiredPath("docs_index", "docs/README.md"),
    RequiredPath(
        "slice_doc",
        "docs/slices/1002_ae_current_state_reaudit_boundary.md",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s100_handoff",
        "scripts/smoke/run_s100_cx_mvp_integration_ae_handoff_closure.py",
        '"next_requirement": "S101"',
    ),
    TokenRequirement(
        "ae_app",
        "services/nex-ae-api/nex_ae_api/main.py",
        "app = build_service_app(SERVICE_SPEC)",
    ),
    TokenRequirement(
        "workspace",
        "services/nex-ae-api/nex_ae_api/workspace.py",
        "class WorkspaceStateStore",
    ),
    TokenRequirement(
        "chat",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "class SqlAlchemyChatInteractionStore",
    ),
    TokenRequirement(
        "uploads",
        "services/nex-ae-api/nex_ae_api/uploads.py",
        "class UploadHandoffStore",
    ),
    TokenRequirement(
        "artifacts",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "class SqlAlchemyArtifactRecordStore",
    ),
    TokenRequirement(
        "auth",
        "services/nex-ae-api/nex_ae_api/auth_sessions.py",
        "def register_auth_session_routes",
    ),
    TokenRequirement(
        "web_runtime",
        "apps/nex-ae-web/src/main.js",
        "bootstrapAuthenticatedSessionRuntime",
    ),
    TokenRequirement(
        "ae_api_requirements",
        "docs/30_service_specific_requirement_partition.md",
        "AEAPI-FR-006",
    ),
    TokenRequirement(
        "ae_web_requirements",
        "docs/30_service_specific_requirement_partition.md",
        "AEWEB-FR-005",
    ),
    TokenRequirement(
        "coverage_policy",
        "docs/34_testing_strategy_v0_1_detail.md",
        "Branch coverage",
    ),
    TokenRequirement(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_current_state_reaudit_boundary.py",
    ),
    TokenRequirement(
        "docs_index",
        "docs/README.md",
        "1002_ae_current_state_reaudit_boundary.md",
    ),
)


def run_ae_current_state_reaudit_boundary(
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
        "s100_handoff_ready": _group_present(tokens, "s100_handoff"),
        "ae_api_runtime_reusable": all(
            _group_present(tokens, group)
            for group in (
                "ae_app",
                "workspace",
                "chat",
                "uploads",
                "artifacts",
                "auth",
            )
        ),
        "ae_web_runtime_reusable": _group_present(tokens, "web_runtime"),
        "requirements_and_quality_inputs_reusable": all(
            _group_present(tokens, group)
            for group in (
                "ae_api_requirements",
                "ae_web_requirements",
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
            None if passed else "ae_current_state_reaudit_boundary_failed"
        ),
        "boundary": BOUNDARY,
        "decision": {
            "owner": "nex-ae-api_and_nex-ae-web",
            "audit_scope": "aeapi_fr_001_through_006_and_aeweb_fr_001_through_005",
            "repository_state_is_primary_evidence": True,
            "legacy_gap_documents_are_advisory": True,
            "refactor_before_feature_when_needed": True,
            "actual_test_database_evidence_required": True,
            "browser_runtime_evidence_required": True,
            "live_provider_evidence_required": False,
            "new_table_required": False,
            "existing_ae_records_mutated": False,
            "next_requirement": "S102",
            "decision_status": "FROZEN",
        },
        "audit_surfaces": [
            "workspace_chat_and_prompt_orchestration",
            "oa_session_and_owner_context",
            "cx_upload_retrieval_generation_handoffs",
            "artifact_lifecycle_preview_and_download",
            "scheduler_worker_and_job_operations",
            "database_migrations_and_persistence_adapters",
            "api_contracts_and_privacy",
            "web_runtime_i18n_accessibility_and_responsiveness",
        ],
        "deferred_scope": [
            "new_end_user_feature_development",
            "production_identity_provider_activation",
            "production_object_storage_activation",
            "production_browser_load_and_disaster_recovery_certification",
        ],
        "slice_plan": [
            "1002_boundary_audit",
            "1003_capability_traceability_inventory",
            "1004_persistence_gap_rebaseline",
            "1005_auth_ownership_privacy_audit",
            "1006_runtime_coupling_refactoring_checkpoint",
            "1007_database_migration_drift_audit",
            "1008_contract_api_drift_audit",
            "1009_web_runtime_i18n_accessibility_drift_audit",
            "1010_postgres_reaudit_privacy_runbook",
            "1011_s101_closure_s102_handoff",
        ],
        "required_paths": paths,
        "required_tokens": tokens,
        "checks": checks,
        "issues": issues,
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _group_present(items: list[dict[str, Any]], group: str) -> bool:
    return any(
        item.get("group") == group and item.get("present") is True
        for item in items
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ae_current_state_reaudit_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    decision = evidence.get("decision") or {}
    return (
        "ae_current_state_reaudit_boundary=pass "
        f"scope={decision.get('audit_scope')} "
        f"owner={decision.get('owner')} "
        f"new_table={decision.get('new_table_required')} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ae_current_state_reaudit_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
