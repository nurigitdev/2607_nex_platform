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
SCHEMA_VERSION = "ag_operator_review_case_decision_lifecycle_boundary_audit.v1"

SLICE_ID = "0671"
S68_SURFACE = "AG operator review case decision lifecycle"
CASE_DECISION_LIFECYCLE_BOUNDARY = (
    "ag_owned_operator_review_case_decision_lifecycle"
)
CASE_TABLE = "ag_op_cases"
NOTE_TABLE = "ag_op_notes"
EXPORT_TABLE = "ag_ev_exports"
OPERATIONAL_EVENT_TABLE = "service_operational_events"
MAX_TABLE_NAME_LENGTH = 30
NEXT_SLICE = "Slice_0672"

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
        "Canonical SRS source for AG governance and operator evidence.",
    ),
    RequiredPath(
        "service_partition",
        "docs/30_service_specific_requirement_partition.md",
        "Service ownership split for AG-owned operator review state.",
    ),
    RequiredPath(
        "testing_strategy",
        "docs/34_testing_strategy_v0_1_detail.md",
        "Testing baseline for protected regression and PostgreSQL smoke evidence.",
    ),
    RequiredPath(
        "s65_action_state_doc",
        "docs/slices/0644_ag_operator_review_case_action_state_machine.md",
        "Existing case action state-machine decision record.",
    ),
    RequiredPath(
        "s66_timeline_doc",
        "docs/slices/0655_ag_operator_review_case_timeline_projection.md",
        "Existing timeline projection over operational events.",
    ),
    RequiredPath(
        "s67_closure_script",
        "scripts/smoke/run_s67_operator_review_case_evidence_admission_closure.py",
        "Closed evidence/admission baseline.",
    ),
    RequiredPath(
        "s67_closure_doc",
        "docs/slices/0670_s67_operator_review_case_evidence_admission_closure.md",
        "S67 closure implementation note.",
    ),
    RequiredPath(
        "ag_operator_review_cases",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "AG-owned operator review case/action runtime surface.",
    ),
    RequiredPath(
        "ag_operator_reviews",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "AG-owned operator notes and redacted evidence exports.",
    ),
    RequiredPath(
        "ag_operations",
        "services/nex-ag/nex_ag/operations.py",
        "AG dashboard and issue-candidate projection surface.",
    ),
    RequiredPath(
        "case_migration",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "Existing AG-owned case table baseline.",
    ),
    RequiredPath(
        "event_migration",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "Existing AG-owned operational event table baseline.",
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
        "case_schema",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "Case mutation/action contract baseline.",
    ),
    RequiredPath(
        "case_workbench_schema",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "Case workbench/timeline/admission contract baseline.",
    ),
    RequiredPath(
        "openapi",
        "contracts/openapi/nex-ag.openapi.yaml",
        "AG OpenAPI contract surface.",
    ),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh", "Default regression gate."),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath("ag_readme", "services/nex-ag/README.md", "AG implementation notes."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s67_closed_baseline",
        "scripts/smoke/run_s67_operator_review_case_evidence_admission_closure.py",
        "s67_closure_schema",
        "s67_operator_review_case_evidence_admission_closure.v1",
        "S68 starts after S67 evidence/admission is closed.",
    ),
    TokenRequirement(
        "s67_closed_baseline",
        "docs/slices/0670_s67_operator_review_case_evidence_admission_closure.md",
        "s67_boundary",
        "ag_owned_operator_review_case_evidence_admission",
        "Decision lifecycle extends the closed evidence/admission boundary.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "case_table_constant",
        'AG_OPERATOR_REVIEW_CASE_TABLE = "ag_op_cases"',
        "Lifecycle reads and status updates keep using the short AG case table.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "action_state_machine",
        "CASE_ACTION_ALLOWED_FROM",
        "Lifecycle decisions must remain state-machine driven.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "action_event_type",
        "OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE",
        "Action history must be observable through safe operational events.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "action_event_emitter",
        "def emit_operator_review_case_action_event",
        "Mutations already emit AG action audit events.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "timeline_projection",
        "def build_operator_review_case_timeline_projection",
        "The lifecycle read model should harden the existing timeline projection.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "action_mutation_response",
        "def build_operator_review_case_action_mutation_response",
        "Lifecycle outcome details should derive from the authoritative mutation response.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "action_application",
        "def apply_operator_review_case_action",
        "Lifecycle state changes already have a single transition function.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "action_metadata_guard",
        "def operator_review_case_action_metadata",
        "Action metadata is normalized before storage or projection.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "last_action_marker",
        '"last_action_id"',
        "The case row keeps a safe latest-action marker for read models.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "resolution_preview",
        '"resolution_preview"',
        "Resolution text is represented as a hash plus bounded preview.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "operational_events_first",
        '"action_history_shape": "operational_events_first"',
        "Action history remains event-first instead of a new action-history table.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "timeline_payload_shape",
        '"timeline_payload_shape": "operational_event_metadata_only"',
        "Timeline payloads remain metadata-only.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "idempotency_keys_redacted",
        '"idempotency_keys_included": False',
        "Lifecycle surfaces must not expose raw idempotency keys.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "metadata_payload_redacted",
        '"metadata_payload_included": False',
        "Lifecycle surfaces must not expose raw metadata payloads.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "resolution_comment_redacted",
        '"raw_resolution_comment_included": False',
        "Lifecycle surfaces must not expose raw resolution text.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "case_table",
        "CREATE TABLE IF NOT EXISTS ag_op_cases",
        "S68 should reuse the existing case table.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "case_status_index",
        "idx_ag_op_cases_status_time",
        "Lifecycle queues need status/time indexed case reads.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "case_assignee_index",
        "idx_ag_op_cases_assignee_time",
        "Assignment workload projections need assignee/time indexed case reads.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "case_trace_index",
        "idx_ag_op_cases_trace_time",
        "Lifecycle timeline correlation uses trace-scoped reads.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "event_table",
        "CREATE TABLE IF NOT EXISTS service_operational_events",
        "Action history should read existing operational events.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "event_trace_index",
        "ix_service_operational_events_trace",
        "Timeline projection needs trace-indexed operational events.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "event_type_index",
        "ix_service_operational_events_type",
        "Lifecycle outcome read models need event-type filtering.",
    ),
    TokenRequirement(
        "evidence_sources",
        "database/nex-ag/migrations/0622_ag_operator_review_note_persistence.sql",
        "note_table",
        "CREATE TABLE IF NOT EXISTS ag_op_notes",
        "Closure packets may summarize existing operator notes.",
    ),
    TokenRequirement(
        "evidence_sources",
        "database/nex-ag/migrations/0626_ag_redacted_evidence_export_persistence.sql",
        "export_table",
        "CREATE TABLE IF NOT EXISTS ag_ev_exports",
        "Closure packets may summarize existing redacted evidence exports.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "case_action_record_contract",
        "case_action_record",
        "Lifecycle outcome contracts start from the existing action record.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "action_mutation_schema",
        "ag_operator_review_case_action_mutation.v1",
        "Mutation response remains the authoritative action result.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "timeline_schema",
        "ag_operator_review_case_timeline.v1",
        "S68 lifecycle timeline should harden the existing timeline schema.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "action_event_contract",
        "ag.operator_review_case_action.recorded",
        "Lifecycle timeline must include action events safely.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/openapi/nex-ag.openapi.yaml",
        "case_action_path",
        "/admin/v1/operator-review/cases/{case_id}/actions",
        "S68 keeps the existing action mutation route authoritative.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/openapi/nex-ag.openapi.yaml",
        "case_timeline_path",
        "/admin/v1/operator-review/cases/{case_id}/timeline",
        "S68 hardens the existing timeline route before adding new lifecycle views.",
    ),
    TokenRequirement(
        "s68_boundary_docs",
        "docs/README.md",
        "doc_index_0671",
        "0671_ag_operator_review_case_decision_lifecycle_boundary_audit.md",
        "Slice 0671 must be indexed.",
    ),
    TokenRequirement(
        "s68_boundary_docs",
        "services/nex-ag/README.md",
        "ag_s68_readme_note",
        "Slice 0671 starts S68",
        "AG README must record the decision lifecycle boundary.",
    ),
    TokenRequirement(
        "s68_boundary_docs",
        "scripts/quality/run_quality_gate.sh",
        "s68_boundary_quality_gate_hook",
        "run_ag_operator_review_case_decision_lifecycle_boundary_audit.py",
        "Slice 0671 audit must run in the default quality gate.",
    ),
)

PLANNED_SLICES = (
    ("action_timeline_projection_hardening", "Slice_0672", "Harden case action timeline projection."),
    ("action_outcome_read_model", "Slice_0673", "Add safe action outcome read model."),
    ("assignment_workload_projection", "Slice_0674", "Project assignee/status workload signals."),
    ("closure_packet_foundation", "Slice_0675", "Assemble redaction-safe closure packets."),
    ("closure_packet_route_wiring", "Slice_0676", "Expose protected closure packet surface."),
    ("lifecycle_dashboard_integration", "Slice_0677", "Fold lifecycle state into operations dashboard."),
    ("lifecycle_contract_openapi_hardening", "Slice_0678", "Freeze lifecycle contracts and examples."),
    ("lifecycle_postgres_smoke", "Slice_0679", "Prove lifecycle read models against nex_ag_test."),
    ("s68_closure", "Slice_0680", "Close the decision lifecycle loop."),
)

SOURCE_TABLE_NAMES = (
    CASE_TABLE,
    OPERATIONAL_EVENT_TABLE,
    NOTE_TABLE,
    EXPORT_TABLE,
)


def run_ag_operator_review_case_decision_lifecycle_boundary_audit(
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
        "s67_closed_baseline_present": token_groups.get("s67_closed_baseline", False),
        "case_runtime_present": token_groups.get("case_runtime", False),
        "persistence_baseline_present": token_groups.get("persistence_baseline", False),
        "evidence_sources_present": token_groups.get("evidence_sources", False),
        "contracts_baseline_present": token_groups.get("contracts_baseline", False),
        "s68_boundary_docs_present": token_groups.get("s68_boundary_docs", False),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "slice": SLICE_ID,
        "surface": S68_SURFACE,
        "case_decision_lifecycle_boundary": _case_decision_lifecycle_boundary(),
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
        evidence["failure_code"] = (
            "ag_operator_review_case_decision_lifecycle_boundary_failed"
        )
        evidence["issues"] = _issues(paths, tokens, table_names)
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), environment)
    return evidence


def _case_decision_lifecycle_boundary() -> dict[str, Any]:
    return {
        "system_of_record": "nex-ag",
        "projection_owner": "nex-ag",
        "boundary": CASE_DECISION_LIFECYCLE_BOUNDARY,
        "create_table_in_slice_0671": False,
        "first_read_model_slice": NEXT_SLICE,
        "case_source_table": CASE_TABLE,
        "event_source_table": OPERATIONAL_EVENT_TABLE,
        "note_source_table": NOTE_TABLE,
        "export_source_table": EXPORT_TABLE,
        "source_tables": [
            {"table_name": CASE_TABLE, "role": "case_status_and_latest_action_source"},
            {"table_name": OPERATIONAL_EVENT_TABLE, "role": "action_history_timeline_source"},
            {"table_name": NOTE_TABLE, "role": "closure_note_summary_source"},
            {"table_name": EXPORT_TABLE, "role": "closure_evidence_export_summary_source"},
        ],
        "planned_read_model_surfaces": [
            "/admin/v1/operator-review/cases/{case_id}/timeline",
            "/admin/v1/operator-review/cases/{case_id}/action-outcomes",
            "/admin/v1/operator-review/cases/workloads",
            "/admin/v1/operator-review/cases/{case_id}/closure-packet",
        ],
        "existing_reference_surfaces": [
            "/admin/v1/operator-review/cases/{case_id}",
            "/admin/v1/operator-review/cases/{case_id}/workbench-detail",
            "/admin/v1/operator-review/cases/{case_id}/actions",
            "/admin/v1/operator-review/cases/{case_id}/action-admission",
            "/admin/v1/operator-review/cases/{case_id}/evidence-links",
        ],
        "decision_inputs": [
            "case_status",
            "action_type",
            "from_status",
            "to_status",
            "assignment_ref",
            "reason_codes",
            "safe_action_comment_hash",
            "safe_resolution_hash",
            "operational_event_trace",
        ],
        "decision_outputs": [
            "action_id",
            "action_type",
            "from_status",
            "to_status",
            "acted_at",
            "operator_ref",
            "assignment_ref",
            "reason_count",
            "resolution_hash",
            "bounded_resolution_preview",
            "timeline_event_ref",
            "next_recommended_actions",
        ],
        "allowed_payload_shape": [
            "case_id",
            "target_reference",
            "case_status",
            "latest_action_ref",
            "action_outcome_summary",
            "assignment_workload_counts",
            "closure_packet_summary",
            "safe_note_refs",
            "safe_evidence_export_refs",
            "operational_event_refs",
            "redaction_flags",
        ],
        "forbidden_payloads": [
            "raw_case_comment",
            "raw_action_comment",
            "raw_resolution_comment",
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
            "artifact_binary_payload",
            "raw_idempotency_key",
            "raw_metadata_payload",
        ],
        "operator_auth_policy": "service_token_or_admin_user_claim_required",
        "postgres_smoke_required_before_s68_closure": True,
        "action_history_storage": "operational_events_first",
        "closure_packet_persistence": "read_model_first",
        "closure_packet_table_deferred_until_query_or_retention_need": True,
        "case_action_mutation_route_remains_source_of_truth": True,
        "lifecycle_surfaces_are_metadata_only": True,
        "ag_may_write_own_case_records": True,
        "ag_may_mutate_source_service_records": False,
        "ag_may_copy_raw_source_payloads": False,
        "cross_service_database_write_allowed": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "reuse_ag_op_cases_for_case_state_and_latest_action": True,
        "reuse_service_operational_events_for_action_history": True,
        "reuse_ag_op_notes_for_closure_note_summaries": True,
        "reuse_ag_ev_exports_for_closure_evidence_summaries": True,
        "avoid_new_lifecycle_table_until_query_or_retention_need_is_proven": True,
        "harden_timeline_projection_before_adding_new_surfaces": True,
        "derive_outcome_read_model_from_authoritative_action_mutation_response": True,
        "keep_case_action_mutation_route_as_final_authority": True,
        "store_and_return_free_text_as_hash_and_short_preview_only": True,
        "require_real_nex_ag_test_db_smoke_before_s68_closure": True,
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
    return [
        {
            "name": required.name,
            "path": required.relative_path,
            "purpose": required.purpose,
            "present": (root_dir / required.relative_path).is_file(),
        }
        for required in REQUIRED_PATHS
    ]


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
        r"raw_case_comment\s*[:=]\s*['\"]",
        r"raw_action_comment\s*[:=]\s*['\"]",
        r"raw_resolution_comment\s*[:=]\s*['\"]",
        r"raw_operator_note_text\s*[:=]\s*['\"]",
        r"raw_evidence_body\s*[:=]\s*['\"]",
        r"raw_prompt_text\s*[:=]\s*['\"]",
        r"raw_generation_output_text\s*[:=]\s*['\"]",
        r"raw_source_document_text\s*[:=]\s*['\"]",
        r"raw_provider_payload\s*[:=]\s*\{",
        r"raw_metadata_payload\s*[:=]\s*\{",
        r"artifact_binary_payload\s*[:=]\s*[A-Za-z0-9+/=]{16,}",
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
            "ag_operator_review_case_decision_lifecycle_boundary_audit=fail "
            f"failed_checks={','.join(failed) or 'unknown'}"
        )
    boundary = evidence.get("case_decision_lifecycle_boundary")
    table_results = evidence.get("table_name_results")
    return (
        "ag_operator_review_case_decision_lifecycle_boundary_audit=pass "
        f"paths={_present_count(evidence.get('paths'))}/{len(REQUIRED_PATHS)} "
        f"tokens={_present_count(evidence.get('source_tokens'))}/{len(REQUIRED_SOURCE_TOKENS)} "
        f"token_groups={sum(1 for value in _grouped_token_status(evidence.get('source_tokens')).values() if value)}/"
        f"{len(_grouped_token_status(evidence.get('source_tokens')))} "
        f"tables={sum(1 for item in table_results or [] if item.get('within_limit'))}/{len(table_results or [])} "
        f"boundary={boundary.get('boundary') if isinstance(boundary, Mapping) else CASE_DECISION_LIFECYCLE_BOUNDARY} "
        "history=operational_events_first "
        "closure=read_model_first "
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
        description=(
            "Run the Slice 0671 AG operator review case decision lifecycle "
            "boundary audit."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print one-line summary.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    args = parser.parse_args(argv)

    evidence = run_ag_operator_review_case_decision_lifecycle_boundary_audit()
    if args.output:
        write_audit_evidence(args.output, evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
