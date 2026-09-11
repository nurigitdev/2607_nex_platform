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
SCHEMA_VERSION = "ag_operator_review_case_evidence_admission_boundary_audit.v1"

SLICE_ID = "0661"
S67_SURFACE = "AG operator review case evidence/admission"
CASE_EVIDENCE_ADMISSION_BOUNDARY = (
    "ag_owned_operator_review_case_evidence_admission"
)
CASE_TABLE = "ag_op_cases"
NOTE_TABLE = "ag_op_notes"
EXPORT_TABLE = "ag_ev_exports"
OPERATIONAL_EVENT_TABLE = "service_operational_events"
MAX_TABLE_NAME_LENGTH = 30
NEXT_SLICE = "Slice_0662"

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
        "Canonical SRS source for AG governance and operator review.",
    ),
    RequiredPath(
        "service_partition",
        "docs/30_service_specific_requirement_partition.md",
        "Service ownership split for AG-owned read models.",
    ),
    RequiredPath(
        "testing_strategy",
        "docs/34_testing_strategy_v0_1_detail.md",
        "Testing baseline for protected boundary and PostgreSQL evidence.",
    ),
    RequiredPath(
        "s66_closure",
        "scripts/smoke/run_s66_operator_review_case_workbench_closure.py",
        "Closed S66 case workbench baseline.",
    ),
    RequiredPath(
        "s66_closure_doc",
        "docs/slices/0660_s66_operator_review_case_workbench_closure.md",
        "S66 closure implementation note.",
    ),
    RequiredPath(
        "s67_boundary_script",
        "scripts/smoke/run_ag_operator_review_case_evidence_admission_boundary_audit.py",
        "S67 boundary audit script.",
    ),
    RequiredPath(
        "s67_boundary_test",
        "tests/test_ag_operator_review_case_evidence_admission_boundary_audit.py",
        "S67 boundary audit regression tests.",
    ),
    RequiredPath(
        "s67_boundary_doc",
        "docs/slices/0661_ag_operator_review_case_evidence_admission_boundary_audit.md",
        "S67 boundary audit documentation.",
    ),
    RequiredPath(
        "ag_operator_review_cases",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "AG-owned case/action runtime surface.",
    ),
    RequiredPath(
        "ag_operator_reviews",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "AG-owned operator note and redacted evidence export runtime.",
    ),
    RequiredPath(
        "ag_operator_review_workbench",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        "AG-owned note/export workbench projection baseline.",
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
        "event_migration",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "Existing AG-owned operational event table baseline.",
    ),
    RequiredPath(
        "case_workbench_schema",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "Case workbench queue/detail/timeline contract baseline.",
    ),
    RequiredPath(
        "operator_workbench_schema",
        "contracts/schemas/service/nex_ag/operator_review_workbench.v1.schema.json",
        "Operator note/export workbench contract baseline.",
    ),
    RequiredPath(
        "openapi",
        "contracts/openapi/nex-ag.openapi.yaml",
        "AG OpenAPI contract surface.",
    ),
    RequiredPath(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "Default regression gate.",
    ),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath("ag_readme", "services/nex-ag/README.md", "AG implementation notes."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s66_closed_baseline",
        "scripts/smoke/run_s66_operator_review_case_workbench_closure.py",
        "s66_closure_schema",
        "s66_operator_review_case_workbench_closure.v1",
        "S67 starts after S66 case workbench capability is closed.",
    ),
    TokenRequirement(
        "s66_closed_baseline",
        "docs/slices/0660_s66_operator_review_case_workbench_closure.md",
        "s66_boundary",
        "ag_owned_operator_review_case_workbench_projection",
        "S67 extends the closed AG-owned case workbench boundary.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "case_table_constant",
        'AG_OPERATOR_REVIEW_CASE_TABLE = "ag_op_cases"',
        "Evidence/admission reads the existing short AG-owned case table.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "action_state_machine",
        "CASE_ACTION_ALLOWED_FROM",
        "Action admission must use the same state-machine source as mutations.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "workbench_action_controls",
        "def _case_workbench_action_controls",
        "Existing workbench detail already exposes safe action controls.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "idempotency_required",
        '"requires_idempotency_key": True',
        "Admission should keep idempotency requirements explicit.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "source_ref_validation",
        "operator_review_case_source_ref",
        "Evidence links should enter through validated safe source refs.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "operator_note_source_type",
        '"operator_review_note"',
        "Case source refs may point to safe operator note refs.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "redacted_export_source_type",
        '"redacted_evidence_export"',
        "Case source refs may point to safe redacted export refs.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "payload_redaction_guard",
        "assert_operator_review_note_payload_redaction_safe",
        "Case/admission mutations must keep the shared redaction guard.",
    ),
    TokenRequirement(
        "evidence_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "note_table_constant",
        'AG_OPERATOR_NOTE_TABLE = "ag_op_notes"',
        "Evidence links reuse the existing short AG note table.",
    ),
    TokenRequirement(
        "evidence_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "export_table_constant",
        'AG_EVIDENCE_EXPORT_TABLE = "ag_ev_exports"',
        "Evidence links reuse the existing short AG export table.",
    ),
    TokenRequirement(
        "evidence_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "note_list_response",
        "def build_operator_review_note_list_response",
        "Evidence links can project from existing note list records.",
    ),
    TokenRequirement(
        "evidence_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "export_list_response",
        "def build_operator_evidence_export_list_response",
        "Evidence links can project from existing redacted export list records.",
    ),
    TokenRequirement(
        "evidence_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "redacted_manifest",
        "def evidence_manifest",
        "Export evidence remains a redacted manifest plus hashes.",
    ),
    TokenRequirement(
        "evidence_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "raw_evidence_not_stored",
        '"raw_evidence_body_stored": False',
        "Raw evidence bodies must not enter S67 evidence/admission payloads.",
    ),
    TokenRequirement(
        "evidence_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "export_storage_policy",
        '"export_storage": "redacted_manifest_plus_hashes"',
        "Exports expose only redacted manifests and hashes.",
    ),
    TokenRequirement(
        "evidence_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "note_storage_policy",
        '"operator_note_storage": "hash_and_short_preview_only"',
        "Notes expose only hashes and short previews.",
    ),
    TokenRequirement(
        "workbench_linkage_baseline",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        "note_hash",
        "operator_note_hash",
        "Workbench projections already expose safe note hashes.",
    ),
    TokenRequirement(
        "workbench_linkage_baseline",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        "note_preview",
        "operator_note_preview",
        "Workbench projections already expose bounded note previews.",
    ),
    TokenRequirement(
        "workbench_linkage_baseline",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        "evidence_exports",
        "evidence_exports",
        "Workbench projections already group redacted evidence exports.",
    ),
    TokenRequirement(
        "workbench_linkage_baseline",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        "evidence_shape",
        "redacted_manifest_plus_hashes",
        "Workbench evidence shape remains redacted.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "case_table",
        "CREATE TABLE IF NOT EXISTS ag_op_cases",
        "S67 should not add another case table.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0622_ag_operator_review_note_persistence.sql",
        "note_table",
        "CREATE TABLE IF NOT EXISTS ag_op_notes",
        "S67 evidence links should read the existing note table.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0626_ag_redacted_evidence_export_persistence.sql",
        "export_table",
        "CREATE TABLE IF NOT EXISTS ag_ev_exports",
        "S67 evidence links should read the existing export table.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "event_table",
        "CREATE TABLE IF NOT EXISTS service_operational_events",
        "S67 evidence/admission may correlate redaction-safe events.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0622_ag_operator_review_note_persistence.sql",
        "note_target_index",
        "idx_ag_op_notes_target_time",
        "Evidence link lookups need target-scoped note indexing.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "case_target_index",
        "idx_ag_op_cases_target_time",
        "Evidence link lookups start from target-scoped case records.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "action_controls_schema",
        "action_controls",
        "S67 admission contracts should extend existing safe action controls.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_workbench.v1.schema.json",
        "evidence_export_ref_schema",
        "evidence_export_ref",
        "S67 evidence link contracts should reuse safe export refs.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/openapi/nex-ag.openapi.yaml",
        "existing_case_workbench_path",
        "/admin/v1/operator-review/cases/{case_id}/workbench-detail",
        "S67 evidence/admission should hang off the existing case workbench path.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_workbench.v1.schema.json",
        "evidence_export_ref_contract",
        "evidence_export_ref",
        "S67 evidence links should reference existing export contract refs.",
    ),
    TokenRequirement(
        "s67_boundary_docs",
        "docs/README.md",
        "doc_index_0661",
        "0661_ag_operator_review_case_evidence_admission_boundary_audit.md",
        "Slice 0661 must be indexed.",
    ),
    TokenRequirement(
        "s67_boundary_docs",
        "services/nex-ag/README.md",
        "ag_s67_readme_note",
        "Slice 0661 starts S67",
        "AG README must record the evidence/admission boundary.",
    ),
    TokenRequirement(
        "s67_boundary_docs",
        "scripts/quality/run_quality_gate.sh",
        "s67_boundary_quality_gate_hook",
        "run_ag_operator_review_case_evidence_admission_boundary_audit.py",
        "Slice 0661 audit must run in the default quality gate.",
    ),
)

PLANNED_SLICES = (
    ("case_evidence_link_read_model", "Slice_0662", "Project safe case evidence links."),
    ("case_evidence_link_routes", "Slice_0663", "Expose protected case evidence-link routes."),
    ("case_action_admission_model", "Slice_0664", "Project safe action-admission decisions."),
    ("case_action_admission_routes", "Slice_0665", "Expose protected action-admission routes."),
    ("workbench_detail_integration", "Slice_0666", "Wire evidence/admission links into detail and operations views."),
    ("contract_schema_examples", "Slice_0667", "Freeze evidence/admission contracts and examples."),
    ("postgres_smoke", "Slice_0668", "Prove evidence/admission read models against nex_ag_test."),
    ("privacy_regression", "Slice_0669", "Lock raw-field leak regression across S67 surfaces."),
    ("s67_closure", "Slice_0670", "Close the evidence/admission loop."),
)

SOURCE_TABLE_NAMES = (
    CASE_TABLE,
    NOTE_TABLE,
    EXPORT_TABLE,
    OPERATIONAL_EVENT_TABLE,
)


def run_ag_operator_review_case_evidence_admission_boundary_audit(
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
        "s66_closed_baseline_present": token_groups.get("s66_closed_baseline", False),
        "case_runtime_present": token_groups.get("case_runtime", False),
        "evidence_runtime_present": token_groups.get("evidence_runtime", False),
        "workbench_linkage_baseline_present": token_groups.get(
            "workbench_linkage_baseline",
            False,
        ),
        "persistence_baseline_present": token_groups.get("persistence_baseline", False),
        "contracts_baseline_present": token_groups.get("contracts_baseline", False),
        "s67_boundary_docs_present": token_groups.get("s67_boundary_docs", False),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "slice": SLICE_ID,
        "surface": S67_SURFACE,
        "case_evidence_admission_boundary": _case_evidence_admission_boundary(),
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
            "ag_operator_review_case_evidence_admission_boundary_failed"
        )
        evidence["issues"] = _issues(paths, tokens, table_names)
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), environment)
    return evidence


def _case_evidence_admission_boundary() -> dict[str, Any]:
    return {
        "system_of_record": "nex-ag",
        "projection_owner": "nex-ag",
        "boundary": CASE_EVIDENCE_ADMISSION_BOUNDARY,
        "create_table_in_slice_0661": False,
        "first_read_model_slice": NEXT_SLICE,
        "case_source_table": CASE_TABLE,
        "case_source_table_length": len(CASE_TABLE),
        "note_source_table": NOTE_TABLE,
        "note_source_table_length": len(NOTE_TABLE),
        "export_source_table": EXPORT_TABLE,
        "export_source_table_length": len(EXPORT_TABLE),
        "event_source_table": OPERATIONAL_EVENT_TABLE,
        "event_source_table_length": len(OPERATIONAL_EVENT_TABLE),
        "source_tables": [
            {"table_name": CASE_TABLE, "role": "case_context_source"},
            {"table_name": NOTE_TABLE, "role": "operator_note_link_source"},
            {"table_name": EXPORT_TABLE, "role": "redacted_evidence_export_link_source"},
            {"table_name": OPERATIONAL_EVENT_TABLE, "role": "safe_event_correlation_source"},
        ],
        "planned_read_model_surfaces": [
            "/admin/v1/operator-review/cases/{case_id}/evidence-links",
            "/admin/v1/operator-review/cases/{case_id}/action-admission",
        ],
        "existing_reference_surfaces": [
            "/admin/v1/operator-review/cases/{case_id}/workbench-detail",
            "/admin/v1/operator-review/cases/{case_id}/actions",
            "/admin/v1/operator-review/notes",
            "/admin/v1/operator-review/evidence-exports",
        ],
        "evidence_link_sources": [
            "operator_review_case.source_ref",
            "operator_review_workbench_target",
            "operator_review_note_ref",
            "redacted_evidence_export_ref",
            "operational_event_subject_ref",
        ],
        "action_admission_inputs": [
            "case_status",
            "action_type",
            "operator_claims",
            "assignment_ref_presence",
            "resolution_comment_presence",
            "idempotency_key_required",
        ],
        "action_admission_outputs": [
            "allowed",
            "blocked_reason",
            "target_status",
            "required_fields",
            "case_action_path",
            "idempotency_key_required",
        ],
        "allowed_payload_shape": [
            "case_id",
            "target_reference",
            "safe_source_reference",
            "operator_note_hash",
            "operator_note_preview",
            "evidence_export_ref",
            "evidence_hash",
            "bounded_previews",
            "redaction_flags",
            "action_admission_metadata",
        ],
        "forbidden_payloads": [
            "raw_operator_note_text",
            "raw_evidence_body",
            "raw_action_comment",
            "raw_resolution_text",
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
        ],
        "operator_auth_policy": "service_token_or_admin_user_claim_required",
        "postgres_smoke_required_before_s67_closure": True,
        "ag_may_write_own_case_records": True,
        "evidence_links_are_read_model_first": True,
        "action_admission_is_preflight_only": True,
        "case_action_mutation_route_remains_source_of_truth": True,
        "ag_may_mutate_source_service_records": False,
        "ag_may_copy_raw_source_payloads": False,
        "cross_service_database_write_allowed": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "reuse_ag_op_cases_for_case_context": True,
        "reuse_ag_op_notes_for_note_links": True,
        "reuse_ag_ev_exports_for_redacted_export_links": True,
        "reuse_service_operational_events_for_safe_correlation": True,
        "avoid_new_evidence_link_table_until_queries_are_insufficient": True,
        "derive_action_admission_from_case_action_state_machine": True,
        "keep_action_mutation_route_as_final_authority": True,
        "link_notes_and_exports_by_safe_refs_hashes_and_previews_only": True,
        "store_and_return_free_text_as_hash_and_short_preview_only": True,
        "require_real_nex_ag_test_db_smoke_before_s67_closure": True,
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
        r"raw_operator_note_text\s*[:=]\s*['\"]",
        r"raw_evidence_body\s*[:=]\s*['\"]",
        r"raw_action_comment\s*[:=]\s*['\"]",
        r"raw_resolution_text\s*[:=]\s*['\"]",
        r"raw_prompt_text\s*[:=]\s*['\"]",
        r"raw_generation_output_text\s*[:=]\s*['\"]",
        r"raw_source_document_text\s*[:=]\s*['\"]",
        r"raw_provider_payload\s*[:=]\s*\{",
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
            "ag_operator_review_case_evidence_admission_boundary_audit=fail "
            f"failed_checks={','.join(failed) or 'unknown'}"
        )
    boundary = evidence.get("case_evidence_admission_boundary")
    table_results = evidence.get("table_name_results")
    return (
        "ag_operator_review_case_evidence_admission_boundary_audit=pass "
        f"paths={_present_count(evidence.get('paths'))}/{len(REQUIRED_PATHS)} "
        f"tokens={_present_count(evidence.get('source_tokens'))}/{len(REQUIRED_SOURCE_TOKENS)} "
        f"token_groups={sum(1 for value in _grouped_token_status(evidence.get('source_tokens')).values() if value)}/"
        f"{len(_grouped_token_status(evidence.get('source_tokens')))} "
        f"tables={sum(1 for item in table_results or [] if item.get('within_limit'))}/{len(table_results or [])} "
        f"boundary={boundary.get('boundary') if isinstance(boundary, Mapping) else CASE_EVIDENCE_ADMISSION_BOUNDARY} "
        "evidence=ag_op_notes,ag_ev_exports "
        "admission=preflight "
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
            "Run the Slice 0661 AG operator review case evidence/admission "
            "boundary audit."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print one-line summary.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    args = parser.parse_args(argv)

    evidence = run_ag_operator_review_case_evidence_admission_boundary_audit()
    if args.output:
        write_audit_evidence(args.output, evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
