#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ag_operator_review_case_action_boundary_audit.v1"

SLICE_ID = "0641"
S65_SURFACE = "AG operator review case/action loop"
CASE_ACTION_BOUNDARY = "ag_owned_operator_review_cases_actions"
CASE_TABLE = "ag_op_cases"
RESERVED_ACTION_EVENT_TABLE = "ag_op_case_events"
NOTE_TABLE = "ag_op_notes"
EXPORT_TABLE = "ag_ev_exports"
MAX_TABLE_NAME_LENGTH = 30
NEXT_SLICE = "Slice_0642"

PROTECTED_ENV_KEYS = (
    "NEX_AG_DATABASE_URL",
    "NEX_AG_TEST_DATABASE_URL",
    "NEX_AG_OPERATIONS_SOURCE_MODE",
    "NEX_AG_OPERATIONS_SOURCE_PROFILE",
    "NEX_AG_AE_ARTIFACT_BASE_URL",
    "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN",
    "NEX_AG_TO_NEX_AE_API_SERVICE_TOKEN",
    "NEX_SERVICE_TOKEN",
)


@dataclass(frozen=True)
class RequiredPath:
    name: str
    relative_path: str
    purpose: str


@dataclass(frozen=True)
class TokenRequirement:
    group: str
    relative_path: str
    token_id: str
    token: str
    purpose: str


REQUIRED_PATHS = (
    RequiredPath(
        "srs_assembly",
        "docs/29_nex_platform_mvp_srs_v0_1_assembly.md",
        "Canonical SRS source for AG operator review and governance.",
    ),
    RequiredPath(
        "service_partition",
        "docs/30_service_specific_requirement_partition.md",
        "Service ownership split for AG-owned operation state.",
    ),
    RequiredPath(
        "testing_strategy",
        "docs/34_testing_strategy_v0_1_detail.md",
        "Testing requirement for operator branches and PostgreSQL smoke evidence.",
    ),
    RequiredPath(
        "s63_closure",
        "scripts/smoke/run_s63_operator_review_evidence_closure.py",
        "Closed note/export evidence baseline.",
    ),
    RequiredPath(
        "s64_closure",
        "scripts/smoke/run_s64_operator_review_workbench_closure.py",
        "Closed workbench/issue-candidate baseline.",
    ),
    RequiredPath(
        "s64_closure_doc",
        "docs/slices/0640_s64_operator_review_workbench_closure.md",
        "S64 closure implementation note.",
    ),
    RequiredPath(
        "ag_operator_reviews",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "AG-owned operator note and evidence export write surface.",
    ),
    RequiredPath(
        "ag_operator_review_workbench",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        "AG-owned workbench read-model projection.",
    ),
    RequiredPath(
        "ag_operations",
        "services/nex-ag/nex_ag/operations.py",
        "AG dashboard and issue-candidate projection surface.",
    ),
    RequiredPath(
        "note_migration",
        "database/nex-ag/migrations/0622_ag_operator_review_note_persistence.sql",
        "Existing AG-owned operator note table baseline.",
    ),
    RequiredPath(
        "export_migration",
        "database/nex-ag/migrations/0626_ag_redacted_evidence_export_persistence.sql",
        "Existing AG-owned redacted evidence export table baseline.",
    ),
    RequiredPath(
        "workbench_postgres_smoke",
        "scripts/smoke/run_ag_operator_review_workbench_postgres_smoke.py",
        "Protected test DB evidence for workbench readback.",
    ),
    RequiredPath(
        "workbench_privacy_regression",
        "scripts/smoke/run_ag_operator_review_workbench_privacy_regression.py",
        "Privacy regression for workbench/dashboard/issue surfaces.",
    ),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh", "Default regression gate."),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath("ag_readme", "services/nex-ag/README.md", "AG implementation notes."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s64_closed_baseline",
        "scripts/smoke/run_s64_operator_review_workbench_closure.py",
        "s64_closure_schema",
        "s64_operator_review_workbench_closure.v1",
        "S65 starts after the workbench capability is closed.",
    ),
    TokenRequirement(
        "s64_closed_baseline",
        "docs/slices/0640_s64_operator_review_workbench_closure.md",
        "s64_closed_boundary",
        "ag_owned_operator_review_workbench_projection",
        "Case/action work must build on the closed workbench projection boundary.",
    ),
    TokenRequirement(
        "operator_review_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "note_table_constant",
        'AG_OPERATOR_NOTE_TABLE = "ag_op_notes"',
        "Case intake may correlate existing note rows.",
    ),
    TokenRequirement(
        "operator_review_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "export_table_constant",
        'AG_EVIDENCE_EXPORT_TABLE = "ag_ev_exports"',
        "Case intake may correlate existing export rows.",
    ),
    TokenRequirement(
        "operator_review_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "idempotency_required",
        "ag.operator_review_note_idempotency_key_required",
        "S65 mutating actions should keep the idempotent mutation pattern.",
    ),
    TokenRequirement(
        "operator_review_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "admin_or_service_auth",
        "AG operator review note routes require an admin user role.",
        "Case/action routes should reuse the S63/S64 operator review authorization boundary.",
    ),
    TokenRequirement(
        "workbench_runtime",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        "workbench_schema",
        "ag_operator_review_workbench.v1",
        "Case creation starts from workbench target refs, not raw source payloads.",
    ),
    TokenRequirement(
        "workbench_runtime",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        "workbench_route",
        '"/admin/v1/operator-review/workbench"',
        "S65 case correlation should attach to the existing workbench route.",
    ),
    TokenRequirement(
        "operations_issue_surface",
        "services/nex-ag/nex_ag/operations.py",
        "issue_rule_id",
        "operator_review_attention_required.v1",
        "S65 case intake should consume the existing operator-review issue signal.",
    ),
    TokenRequirement(
        "operations_issue_surface",
        "services/nex-ag/nex_ag/operations.py",
        "recommended_actions",
        "recommended_operator_actions",
        "S65 actions should be derived from safe recommended action codes.",
    ),
    TokenRequirement(
        "operations_issue_surface",
        "services/nex-ag/nex_ag/operations.py",
        "workbench_issue_source",
        "operator_review_workbench",
        "Issue candidates should remain tied to the workbench projection.",
    ),
    TokenRequirement(
        "postgres_evidence_baseline",
        "scripts/smoke/run_ag_operator_review_workbench_postgres_smoke.py",
        "workbench_smoke_env",
        "NEX_AG_OPERATOR_REVIEW_WORKBENCH_POSTGRES_SMOKE",
        "Case/action PostgreSQL smoke should follow the protected test DB profile.",
    ),
    TokenRequirement(
        "postgres_evidence_baseline",
        "scripts/smoke/run_ag_operator_review_workbench_postgres_smoke.py",
        "workbench_direct_db_check",
        '"tables_present"',
        "S65 smoke must directly verify AG-owned case rows in PostgreSQL.",
    ),
    TokenRequirement(
        "privacy_baseline",
        "scripts/smoke/run_ag_operator_review_workbench_privacy_regression.py",
        "privacy_surfaces",
        '"issue_candidates"',
        "Case/action correlation must preserve the S64 privacy surface checks.",
    ),
    TokenRequirement(
        "s65_boundary_docs",
        "docs/README.md",
        "s65_doc_indexed",
        "0641_ag_operator_review_case_action_boundary_audit.md",
        "Slice 0641 must be indexed.",
    ),
    TokenRequirement(
        "s65_boundary_docs",
        "services/nex-ag/README.md",
        "ag_s65_readme_note",
        "Slice 0641 starts S65",
        "AG README must record the case/action boundary.",
    ),
    TokenRequirement(
        "s65_boundary_docs",
        "scripts/quality/run_quality_gate.sh",
        "s65_boundary_quality_gate_hook",
        "run_ag_operator_review_case_action_boundary_audit.py",
        "Slice 0641 audit must run in the default quality gate.",
    ),
)

PLANNED_SLICES = (
    ("case_persistence", "Slice_0642", "Add AG-owned case schema/store foundation."),
    ("case_state_machine", "Slice_0643", "Define idempotent case state transitions and service facade."),
    ("case_routes", "Slice_0644", "Expose protected case list/detail/create routes."),
    ("case_action_routes", "Slice_0645", "Expose acknowledge, assign, resolve, dismiss, and reopen actions."),
    ("workbench_case_correlation", "Slice_0646", "Attach safe case state to workbench items."),
    ("dashboard_case_awareness", "Slice_0647", "Fold case state into dashboard and issue candidates."),
    ("contract_schema_examples", "Slice_0648", "Freeze case/action OpenAPI schemas and examples."),
    ("postgres_smoke", "Slice_0649", "Prove case/action routes against nex_ag_test."),
    ("s65_closure", "Slice_0650", "Close the operator review case/action loop."),
)

SOURCE_TABLE_NAMES = (CASE_TABLE, RESERVED_ACTION_EVENT_TABLE, NOTE_TABLE, EXPORT_TABLE)


def run_ag_operator_review_case_action_boundary_audit(
    env: Mapping[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, Any]:
    environment = dict(os.environ if env is None else env)
    paths = _path_results(root_dir)
    tokens = _token_results(root_dir)
    token_groups = _grouped_token_status(tokens)
    table_names = _table_name_results()
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "table_name_lengths_safe": all(item["within_limit"] for item in table_names),
        "s64_closed_baseline_present": token_groups.get("s64_closed_baseline", False),
        "operator_review_runtime_present": token_groups.get("operator_review_runtime", False),
        "workbench_runtime_present": token_groups.get("workbench_runtime", False),
        "operations_issue_surface_present": token_groups.get("operations_issue_surface", False),
        "postgres_evidence_baseline_present": token_groups.get(
            "postgres_evidence_baseline", False
        ),
        "privacy_baseline_present": token_groups.get("privacy_baseline", False),
        "s65_boundary_docs_present": token_groups.get("s65_boundary_docs", False),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "slice": SLICE_ID,
        "surface": S65_SURFACE,
        "case_action_boundary": _case_action_boundary(),
        "refactoring_checkpoint": _refactoring_checkpoint(),
        "table_name_results": table_names,
        "next_slices": [planned_slice for _, planned_slice, _ in PLANNED_SLICES],
        "planned_sequence": [
            {"name": name, "planned_slice": planned_slice, "purpose": purpose}
            for name, planned_slice, purpose in PLANNED_SLICES
        ],
        "protected_env": {
            key: bool(environment.get(key)) for key in PROTECTED_ENV_KEYS
        },
        "checks": checks,
        "paths": paths,
        "source_tokens": tokens,
    }
    if evidence["status"] != "PASS":
        evidence["failure_code"] = "ag_operator_review_case_action_boundary_failed"
        evidence["issues"] = _issues(paths, tokens, table_names)
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), environment)
    return evidence


def _case_action_boundary() -> dict[str, Any]:
    return {
        "system_of_record": "nex-ag",
        "persistence_owner": "nex-ag",
        "action_owner": "nex-ag",
        "boundary": CASE_ACTION_BOUNDARY,
        "create_table_in_slice_0641": False,
        "first_schema_slice": NEXT_SLICE,
        "candidate_case_table": CASE_TABLE,
        "candidate_case_table_length": len(CASE_TABLE),
        "reserved_future_action_event_table": RESERVED_ACTION_EVENT_TABLE,
        "reserved_future_action_event_table_length": len(RESERVED_ACTION_EVENT_TABLE),
        "action_history_policy": "operational_events_first_no_action_table_in_s65",
        "source_tables": [
            {"table_name": NOTE_TABLE, "role": "operator_note_metadata"},
            {"table_name": EXPORT_TABLE, "role": "redacted_evidence_export_metadata"},
        ],
        "source_record_owners": ["nex-ae-api", "nex-cx", "nex-mo", "nex-oa"],
        "target_reference_columns": [
            "target_service",
            "target_kind",
            "target_id",
            "trace_id",
            "request_id",
        ],
        "target_reference_columns_indexable": True,
        "case_statuses": [
            "OPEN",
            "ACKNOWLEDGED",
            "ASSIGNED",
            "RESOLVED",
            "DISMISSED",
            "REOPENED",
        ],
        "case_action_commands": [
            "CREATE_CASE",
            "ACKNOWLEDGE",
            "ASSIGN",
            "RESOLVE",
            "DISMISS",
            "REOPEN",
        ],
        "case_intake_sources": [
            "operator_review_workbench_target",
            "operator_review_attention_required_issue_candidate",
            "operator_review_note_ref",
            "redacted_evidence_export_ref",
        ],
        "allowed_ag_case_writes": [
            "case_status",
            "case_priority",
            "case_assignment_ref",
            "target_reference",
            "safe_reason_codes",
            "resolution_hash",
            "resolution_preview",
            "idempotency_key_hash",
        ],
        "forbidden_case_payloads": [
            "raw_operator_note_text",
            "raw_evidence_body",
            "raw_prompt_text",
            "raw_generation_output_text",
            "raw_source_document_text",
            "raw_provider_payload",
            "database_url",
            "service_token",
            "provider_api_key",
            "local_storage_path",
            "source_service_record_blob",
            "artifact_binary_payload",
            "raw_idempotency_key",
            "external_notification_secret",
        ],
        "case_comment_storage_shape": "hash_and_short_preview_only",
        "operator_auth_policy": "service_token_or_admin_user_claim_required",
        "idempotency_key_required_for_mutating_actions": True,
        "notification_delivery_deferred": True,
        "external_incident_sync_deferred": True,
        "postgres_smoke_required_before_operational_enablement": True,
        "ag_may_write_own_case_records": True,
        "ag_may_mutate_source_service_records": False,
        "ag_may_copy_raw_source_payloads": False,
        "cross_service_database_write_allowed": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "keep_case_records_separate_from_note_and_export_records": True,
        "keep_source_service_records_read_only": True,
        "reuse_workbench_target_refs_for_case_intake": True,
        "split_target_reference_into_indexable_columns": True,
        "add_case_repository_before_route_wiring": True,
        "model_actions_as_idempotent_state_transitions": True,
        "emit_action_audit_events_without_raw_comments": True,
        "store_free_text_as_hash_and_short_preview_only": True,
        "defer_action_history_table_until_operational_events_are_insufficient": True,
        "defer_notifications_and_external_incident_sync": True,
        "require_admin_or_service_claims_for_mutating_actions": True,
        "require_real_nex_ag_test_db_smoke_before_case_closure": True,
        "do_not_mutate_ae_cx_mo_oa_records": True,
        "do_not_copy_raw_prompts_source_docs_provider_payloads_or_storage_paths": True,
    }


def _table_name_results() -> list[dict[str, Any]]:
    return [
        {
            "table_name": table_name,
            "length": len(table_name),
            "max_length": MAX_TABLE_NAME_LENGTH,
            "within_limit": len(table_name) <= MAX_TABLE_NAME_LENGTH,
        }
        for table_name in SOURCE_TABLE_NAMES
    ]


def _path_results(root_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for required in REQUIRED_PATHS:
        path = root_dir / required.relative_path
        results.append(
            {
                "name": required.name,
                "path": required.relative_path,
                "purpose": required.purpose,
                "present": path.is_file(),
            }
        )
    return results


def _token_results(root_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for requirement in REQUIRED_SOURCE_TOKENS:
        text = _read_text(root_dir / requirement.relative_path)
        results.append(
            {
                "group": requirement.group,
                "token_id": requirement.token_id,
                "path": requirement.relative_path,
                "purpose": requirement.purpose,
                "present": requirement.token in text,
            }
        )
    return results


def _issues(
    paths: list[dict[str, Any]],
    tokens: list[dict[str, Any]],
    table_names: list[dict[str, Any]],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for path_result in paths:
        if not path_result["present"]:
            issues.append(
                {
                    "category": "path_missing",
                    "id": path_result["name"],
                    "path": path_result["path"],
                    "purpose": path_result["purpose"],
                }
            )
    for token_result in tokens:
        if not token_result["present"]:
            issues.append(
                {
                    "category": "source_token_missing",
                    "id": token_result["token_id"],
                    "path": token_result["path"],
                    "purpose": token_result["purpose"],
                }
            )
    for table_result in table_names:
        if not table_result["within_limit"]:
            issues.append(
                {
                    "category": "table_name_too_long",
                    "id": table_result["table_name"],
                    "path": "database/nex-ag/migrations",
                    "purpose": "Keep PostgreSQL relation names concise for operations.",
                }
            )
    return issues


def _grouped_token_status(tokens: list[dict[str, Any]] | None) -> dict[str, bool]:
    grouped: dict[str, list[bool]] = {}
    for token in tokens or []:
        grouped.setdefault(str(token.get("group")), []).append(
            token.get("present") is True
        )
    return {group: all(values) for group, values in grouped.items()}


def _present_count(items: list[dict[str, Any]] | None) -> int:
    return sum(1 for item in items or [] if item.get("present") is True)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def assert_evidence_redacted(serialized: str, env: Mapping[str, str]) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = env.get(key)
        if value and len(value) > 8 and value in serialized:
            raise ValueError(f"Sensitive value leaked in evidence: {key}")
    sensitive_patterns = (
        r"postgresql(?:\+psycopg)?://[^*\s]+:[^*\s]+@",
        r"Bearer\s+[A-Za-z0-9._~+/=@-]+",
        r"ed6@c496em",
        r"nuri1004",
        r"/data/nex-platform",
        r"idempotency[_-]?key\s*[:=]\s*[A-Za-z0-9._~+/=@-]+",
        r"raw_operator_note_text\s*[:=]\s*['\"]",
        r"raw_evidence_body\s*[:=]\s*['\"]",
        r"raw_prompt_text\s*[:=]\s*['\"]",
        r"raw_generation_output_text\s*[:=]\s*['\"]",
        r"raw_source_document_text\s*[:=]\s*['\"]",
        r"raw_provider_payload\s*[:=]\s*\{",
        r"source_service_record_blob\s*[:=]\s*\{",
        r"artifact_binary_payload\s*[:=]\s*[A-Za-z0-9+/=]{16,}",
        r"external_notification_secret\s*[:=]\s*['\"]",
    )
    for pattern in sensitive_patterns:
        if re.search(pattern, serialized):
            raise ValueError(f"Sensitive value leaked in evidence: {pattern}")


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks")
    if evidence.get("status") != "PASS":
        failed = [
            key
            for key, value in (checks.items() if isinstance(checks, Mapping) else [])
            if not value
        ]
        return (
            "ag_operator_review_case_action_boundary_audit=fail "
            f"failed_checks={','.join(failed) or 'unknown'}"
        )
    boundary = evidence.get("case_action_boundary")
    table_results = evidence.get("table_name_results")
    return (
        "ag_operator_review_case_action_boundary_audit=pass "
        f"paths={_present_count(evidence.get('paths'))}/{len(REQUIRED_PATHS)} "
        f"tokens={_present_count(evidence.get('source_tokens'))}/{len(REQUIRED_SOURCE_TOKENS)} "
        f"token_groups={sum(1 for value in _grouped_token_status(evidence.get('source_tokens')).values() if value)}/"
        f"{len(_grouped_token_status(evidence.get('source_tokens')))} "
        f"tables={sum(1 for item in table_results or [] if item.get('within_limit'))}/{len(table_results or [])} "
        f"boundary={boundary.get('boundary') if isinstance(boundary, Mapping) else CASE_ACTION_BOUNDARY} "
        f"case_table={CASE_TABLE} "
        f"action_history=operational_events_first "
        f"next={NEXT_SLICE}"
    )


def write_audit_evidence(output_path: Path, evidence: Mapping[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Slice 0641 AG operator review case/action boundary audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print one-line summary.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    args = parser.parse_args(argv)

    evidence = run_ag_operator_review_case_action_boundary_audit()
    if args.output:
        write_audit_evidence(args.output, evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
