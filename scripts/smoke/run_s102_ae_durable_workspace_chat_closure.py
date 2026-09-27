#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from run_ae_durable_workspace_chat_boundary_audit import (
    run_ae_durable_workspace_chat_boundary_audit as run_boundary,
)
from run_ae_workspace_chat_contract_observability import (
    run_workspace_chat_contract_observability_smoke as run_contract_observability,
)
from run_ae_workspace_chat_postgres_smoke import (
    SMOKE_ENV as POSTGRES_SMOKE_ENV,
    run_ae_workspace_chat_postgres_smoke as run_postgres,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s102_ae_durable_workspace_chat_closure.v1"
SLICE_RANGE = "1012-1021"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/workspace_chat_auth.py",
    "services/nex-ae-api/nex_ae_api/workspace_persistence.py",
    "services/nex-ae-api/nex_ae_api/workspace_chat_orchestration.py",
    "services/nex-ae-api/nex_ae_api/workspace_chat_observability.py",
    "database/nex-ae-api/migrations/1014_ae_workspace_activity_persistence.sql",
    "contracts/schemas/service/nex_ae_api/workspace_activity.v1.schema.json",
    "contracts/schemas/service/nex_ae_api/chat_interaction.v1.schema.json",
    "scripts/smoke/run_ae_workspace_chat_postgres_smoke.py",
    "scripts/smoke/run_s102_ae_durable_workspace_chat_closure.py",
    "tests/test_s102_ae_durable_workspace_chat_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("1012", "ae_durable_workspace_chat_boundary_audit"),
            ("1013", "ae_workspace_chat_owner_scope_contract"),
            ("1014", "ae_workspace_activity_persistence_schema"),
            ("1015", "ae_workspace_sqlalchemy_repository"),
            ("1016", "ae_owner_scoped_workspace_api"),
            ("1017", "ae_owner_scoped_chat_persistence_api"),
            ("1018", "ae_durable_workspace_chat_orchestration"),
            ("1019", "ae_workspace_chat_contract_openapi_observability"),
            ("1020", "ae_workspace_chat_postgresql_smoke"),
            ("1021", "s102_ae_durable_workspace_chat_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "claim_authoritative_owner_scope",
        "services/nex-ae-api/nex_ae_api/workspace_chat_auth.py",
        "def owner_scoped_payload",
    ),
    (
        "durable_workspace_repository",
        "services/nex-ae-api/nex_ae_api/workspace_persistence.py",
        "class SqlAlchemyWorkspaceRepository",
    ),
    (
        "durable_workspace_tables",
        "database/nex-ae-api/migrations/1014_ae_workspace_activity_persistence.sql",
        "CREATE TABLE IF NOT EXISTS ae_workspace_activities",
    ),
    (
        "chat_workspace_link",
        "database/nex-ae-api/migrations/1014_ae_workspace_activity_persistence.sql",
        "ADD COLUMN IF NOT EXISTS workspace_id UUID NULL",
    ),
    (
        "owner_scoped_chat_read",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "def _get_visible_chat_record",
    ),
    (
        "pending_terminal_orchestration",
        "services/nex-ae-api/nex_ae_api/workspace_chat_orchestration.py",
        "def append_workspace_chat_activity",
    ),
    (
        "metadata_only_observability",
        "services/nex-ae-api/nex_ae_api/workspace_chat_observability.py",
        "owner_identity_included",
    ),
    (
        "chat_pending_contract",
        "contracts/schemas/service/nex_ae_api/chat_interaction.v1.schema.json",
        '"PENDING"',
    ),
    (
        "workspace_activity_contract",
        "contracts/schemas/service/nex_ae_api/workspace_activity.v1.schema.json",
        "ae_workspace_activity.v1",
    ),
    (
        "openapi_v1",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "version: 1.0.0",
    ),
    (
        "protected_postgres_target",
        "scripts/smoke/run_ae_workspace_chat_postgres_smoke.py",
        'EXPECTED_DATABASE = "nex_ae_test"',
    ),
    (
        "postgres_cleanup_required",
        "scripts/smoke/run_ae_workspace_chat_postgres_smoke.py",
        'checks["cleanup_complete"]',
    ),
    (
        "quality_postgres",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_workspace_chat_postgres_smoke.py",
    ),
    (
        "quality_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s102_ae_durable_workspace_chat_closure.py",
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "1021_s102_ae_durable_workspace_chat_closure.md",
    ),
)

COMPONENT_TOKEN_NAMES = {
    "owner_scope": ("claim_authoritative_owner_scope",),
    "workspace_persistence": (
        "durable_workspace_repository",
        "durable_workspace_tables",
    ),
    "chat_persistence": ("chat_workspace_link", "owner_scoped_chat_read"),
    "orchestration": ("pending_terminal_orchestration",),
    "contract_and_openapi": (
        "chat_pending_contract",
        "workspace_activity_contract",
        "openapi_v1",
    ),
    "privacy_observability": ("metadata_only_observability",),
    "protected_postgresql": (
        "protected_postgres_target",
        "postgres_cleanup_required",
    ),
    "quality_and_documentation": (
        "quality_postgres",
        "quality_closure",
        "docs_closure_index",
    ),
}


def run_s102_ae_durable_workspace_chat_closure(
    root: Path = ROOT,
    *,
    postgres_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]
    token_checks = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in TOKEN_CHECKS
    ]
    token_status = {item["name"]: item["present"] for item in token_checks}
    components = {
        name: all(token_status[token] for token in tokens)
        for name, tokens in COMPONENT_TOKEN_NAMES.items()
    }
    boundary = _safe_evidence(lambda: run_boundary(root))
    contract = _safe_evidence(run_contract_observability)
    postgres = (
        dict(postgres_evidence)
        if postgres_evidence is not None
        else _safe_evidence(run_postgres)
    )
    boundary_summary = _mapping(boundary.get("summary"))
    postgres_checks = _mapping(postgres.get("checks"))
    postgres_requested = os.environ.get(POSTGRES_SMOKE_ENV) == "1"
    postgres_executed = (
        postgres.get("status") == "PASS"
        and postgres.get("actual_postgres") is True
        and postgres.get("execution_state") == "EXECUTED"
        and postgres.get("database") == "nex_ae_test"
        and bool(postgres_checks)
        and all(postgres_checks.values())
        and _mapping(postgres.get("cleanup_counts")).get("remaining") == 0
    )
    postgres_policy_satisfied = postgres_executed or (
        not postgres_requested and postgres.get("status") == "SKIPPED"
    )
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "boundary_audit_passed": boundary.get("status") == "PASS",
        "boundary_plan_completed": (
            boundary_summary.get("planned_slice_count") == 10
            and boundary_summary.get("gap_count") == 8
            and boundary_summary.get("resolved_gap_count") == 8
            and boundary_summary.get("open_gap_count") == 0
            and boundary.get("next_slice") == "1021"
        ),
        "all_components_closed": all(components.values()),
        "contract_observability_passed": contract.get("status") == "PASS"
        and all(_mapping(contract.get("checks")).values()),
        "postgres_policy_satisfied": postgres_policy_satisfied,
        "owner_privacy_boundary_preserved": (
            _mapping(boundary.get("decision")).get("browser_owner_authority")
            == "validated_oa_claim"
            and _mapping(boundary.get("decision")).get("cross_owner_behavior")
            == "not_found"
            and _mapping(boundary.get("decision")).get(
                "private_message_body_persisted"
            )
            is False
        ),
        "tiered_quality_cadence_preserved": (
            _mapping(boundary.get("decision")).get("quality_cadence")
            == {
                "slice_gate": "1012-1021",
                "checkpoint_gate": "1016",
                "full_gate": "1021",
            }
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1021",
        "slice_range": SLICE_RANGE,
        "requirement": "S102",
        "status": status,
        "failure_code": None if status == "PASS" else "s102_ae_closure_failed",
        "closure_readiness": (
            "READY_FOR_S103"
            if status == "PASS" and postgres_executed
            else "READY_WITH_PROTECTED_POSTGRES_PENDING"
            if status == "PASS"
            else "BLOCKED"
        ),
        "feature_readiness": (
            "AE_DURABLE_WORKSPACE_CHAT_READY"
            if status == "PASS" and postgres_executed
            else "REPOSITORY_READY_PROTECTED_POSTGRES_PENDING"
            if status == "PASS"
            else "INCOMPLETE"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "resolved_gap_count": int(
                boundary_summary.get("resolved_gap_count") or 0
            ),
            "contract_check_count": len(_mapping(contract.get("checks"))),
            "postgres_check_count": len(postgres_checks) if postgres_executed else 0,
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
        "components": components,
        "boundary_status": boundary.get("status"),
        "contract_observability_status": contract.get("status"),
        "postgres_status": postgres.get("status"),
        "postgres_executed": postgres_executed,
        "postgres_evidence": postgres,
        "required_files": required_files,
        "token_checks": token_checks,
        "decision": _closure_decision(),
        "next_requirement": "S103",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "ae_durable_workspace_and_chat_orchestration",
        "owner_policy": "oa_claim_authoritative_cross_owner_not_found",
        "persistence_policy": "postgres_metadata_bounded_preview_no_raw_body",
        "orchestration_policy": "pending_before_provider_idempotent_terminal_state",
        "observability_policy": "non_blocking_metadata_only_operational_events",
        "postgres_smoke_target": "nex_ae_user@nex_ae_test",
        "remote_provider_required": False,
        "new_tables_added": ["ae_workspaces", "ae_workspace_activities"],
        "legacy_chat_workspace_link": "nullable",
        "next_requirement_scope": "S103_ae_upload_document_workflow_hardening",
    }


def _safe_evidence(builder: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    try:
        return dict(builder())
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": "evidence_builder_failed",
            "detail": exc.__class__.__name__,
        }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "s102_ae_durable_workspace_chat_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"gaps={summary.get('resolved_gap_count', 0)}/8 "
        f"postgres={str(evidence.get('postgres_status') or 'not-run').lower()} "
        f"postgres_checks={summary.get('postgres_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s102_ae_durable_workspace_chat_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
