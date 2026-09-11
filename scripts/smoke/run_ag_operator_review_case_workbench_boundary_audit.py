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
SCHEMA_VERSION = "ag_operator_review_case_workbench_boundary_audit.v1"

SLICE_ID = "0651"
S66_SURFACE = "AG operator review case workbench"
CASE_WORKBENCH_BOUNDARY = "ag_owned_operator_review_case_workbench_projection"
CASE_TABLE = "ag_op_cases"
OPERATIONAL_EVENT_TABLE = "service_operational_events"
NOTE_TABLE = "ag_op_notes"
EXPORT_TABLE = "ag_ev_exports"
MAX_TABLE_NAME_LENGTH = 30
NEXT_SLICE = "Slice_0652"

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
        "Testing baseline for operator review and PostgreSQL evidence.",
    ),
    RequiredPath(
        "s65_closure",
        "scripts/smoke/run_s65_operator_review_case_action_closure.py",
        "Closed S65 case/action baseline.",
    ),
    RequiredPath(
        "s65_closure_doc",
        "docs/slices/0650_s65_operator_review_case_action_closure.md",
        "S65 closure implementation note.",
    ),
    RequiredPath(
        "ag_operator_review_cases",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "AG-owned case/action runtime surface.",
    ),
    RequiredPath(
        "ag_operator_review_workbench",
        "services/nex-ag/nex_ag/operator_review_workbench.py",
        "AG-owned note/export workbench baseline.",
    ),
    RequiredPath(
        "ag_operations",
        "services/nex-ag/nex_ag/operations.py",
        "AG dashboard, issue-candidate, and timeline projection surface.",
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
        "case_schema",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "Case/action contract shape.",
    ),
    RequiredPath(
        "case_rollup_schema",
        "contracts/schemas/service/nex_ag/operator_review_case_rollup.v1.schema.json",
        "Case/action rollup contract shape.",
    ),
    RequiredPath(
        "operations_schema",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "Operations dashboard projection schema.",
    ),
    RequiredPath(
        "case_postgres_smoke",
        "scripts/smoke/run_ag_operator_review_case_postgres_smoke.py",
        "Protected test DB evidence for S65 case/action path.",
    ),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh", "Default regression gate."),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath("ag_readme", "services/nex-ag/README.md", "AG implementation notes."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s65_closed_baseline",
        "scripts/smoke/run_s65_operator_review_case_action_closure.py",
        "s65_closure_schema",
        "s65_operator_review_case_action_closure.v1",
        "S66 starts after S65 case/action capability is closed.",
    ),
    TokenRequirement(
        "s65_closed_baseline",
        "docs/slices/0650_s65_operator_review_case_action_closure.md",
        "s65_boundary",
        "`ag_op_cases`",
        "S66 workbench must build on the closed AG case/action boundary.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "case_table_constant",
        'AG_OPERATOR_REVIEW_CASE_TABLE = "ag_op_cases"',
        "Case workbench reads the existing short AG-owned case table.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "case_action_event",
        "ag.operator_review_case_action.recorded",
        "Timeline projection must read redaction-safe action events.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "action_history_storage",
        '"action_history_storage": "operational_events_first"',
        "S66 must keep action history event-first.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "last_action_summary",
        "def _safe_case_last_action_ref",
        "Queue projections may use the latest safe action summary.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "case_routes",
        '"/admin/v1/operator-review/cases"',
        "Case queue and detail surfaces build on existing protected case routes.",
    ),
    TokenRequirement(
        "case_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "case_rollup_route",
        '"/admin/v1/operator-review/cases/rollups"',
        "Case workbench rollup should reuse the existing rollup route.",
    ),
    TokenRequirement(
        "operations_projection_surface",
        "services/nex-ag/nex_ag/operations.py",
        "dashboard_case_section",
        "ag_operator_review_case_dashboard_section.v1",
        "S66 must preserve existing dashboard case correlation.",
    ),
    TokenRequirement(
        "operations_projection_surface",
        "services/nex-ag/nex_ag/operations.py",
        "dashboard_case_list_path",
        'case_list_path": "/admin/v1/operator-review/cases"',
        "Operations dashboard should keep linking to the case queue.",
    ),
    TokenRequirement(
        "operations_projection_surface",
        "services/nex-ag/nex_ag/operations.py",
        "trace_timeline_projection",
        "build_cross_service_trace_timeline_projection",
        "Case timeline work should follow existing AG timeline projection patterns.",
    ),
    TokenRequirement(
        "operations_projection_surface",
        "services/nex-ag/nex_ag/operations.py",
        "recommended_actions",
        "recommended_operator_actions",
        "Admission/recommendation guards should reuse safe action codes.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "case_table",
        "CREATE TABLE IF NOT EXISTS ag_op_cases",
        "S66 should not add another case queue table.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "event_table",
        "CREATE TABLE IF NOT EXISTS service_operational_events",
        "Timeline projection should read the existing operational event table.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "event_type_index",
        "ix_service_operational_events_type",
        "Action timeline queries need event-type indexing.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "case_schema",
        "ag_operator_review_case.v1",
        "S66 contracts should extend the existing case schema family.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case_rollup.v1.schema.json",
        "rollup_redaction",
        "raw_action_comment_included",
        "S66 must preserve action-comment redaction flags.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "dashboard_schema",
        "ag_operator_review_case_dashboard_section.v1",
        "Dashboard schema must already know the case section.",
    ),
    TokenRequirement(
        "postgres_evidence_baseline",
        "scripts/smoke/run_ag_operator_review_case_postgres_smoke.py",
        "case_smoke_env",
        "NEX_AG_OPERATOR_REVIEW_CASE_POSTGRES_SMOKE",
        "S66 PostgreSQL smoke should reuse protected test DB evidence style.",
    ),
    TokenRequirement(
        "s66_boundary_docs",
        "docs/README.md",
        "doc_index_0651",
        "0651_ag_operator_review_case_workbench_boundary_audit.md",
        "Slice 0651 must be indexed.",
    ),
    TokenRequirement(
        "s66_boundary_docs",
        "services/nex-ag/README.md",
        "ag_s66_readme_note",
        "Slice 0651 starts S66",
        "AG README must record the case workbench boundary.",
    ),
    TokenRequirement(
        "s66_boundary_docs",
        "scripts/quality/run_quality_gate.sh",
        "s66_boundary_quality_gate_hook",
        "run_ag_operator_review_case_workbench_boundary_audit.py",
        "Slice 0651 audit must run in the default quality gate.",
    ),
)

PLANNED_SLICES = (
    ("case_queue_read_model", "Slice_0652", "Build operator-facing case queue read model."),
    ("case_queue_filters", "Slice_0653", "Harden queue filter, search, and sort controls."),
    ("case_detail_timeline", "Slice_0654", "Project safe action history from operational events."),
    ("case_evidence_linkage", "Slice_0655", "Link cases to workbench notes and redacted exports."),
    ("action_admission_guardrail", "Slice_0656", "Expose allowed, blocked, and recommended actions."),
    ("dashboard_queue_correlation", "Slice_0657", "Harden operations dashboard case queue correlation."),
    ("contract_schema_examples", "Slice_0658", "Freeze queue/detail/timeline contracts and examples."),
    ("postgres_smoke", "Slice_0659", "Prove queue/detail/timeline against nex_ag_test."),
    ("s66_closure", "Slice_0660", "Close the operator review case workbench loop."),
)

SOURCE_TABLE_NAMES = (CASE_TABLE, OPERATIONAL_EVENT_TABLE, NOTE_TABLE, EXPORT_TABLE)


def run_ag_operator_review_case_workbench_boundary_audit(
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
        "s65_closed_baseline_present": token_groups.get("s65_closed_baseline", False),
        "case_runtime_present": token_groups.get("case_runtime", False),
        "operations_projection_surface_present": token_groups.get(
            "operations_projection_surface", False
        ),
        "persistence_baseline_present": token_groups.get("persistence_baseline", False),
        "contracts_baseline_present": token_groups.get("contracts_baseline", False),
        "postgres_evidence_baseline_present": token_groups.get(
            "postgres_evidence_baseline", False
        ),
        "s66_boundary_docs_present": token_groups.get("s66_boundary_docs", False),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "slice": SLICE_ID,
        "surface": S66_SURFACE,
        "case_workbench_boundary": _case_workbench_boundary(),
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
        evidence["failure_code"] = "ag_operator_review_case_workbench_boundary_failed"
        evidence["issues"] = _issues(paths, tokens, table_names)
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), environment)
    return evidence


def _case_workbench_boundary() -> dict[str, Any]:
    return {
        "system_of_record": "nex-ag",
        "projection_owner": "nex-ag",
        "boundary": CASE_WORKBENCH_BOUNDARY,
        "create_table_in_slice_0651": False,
        "first_read_model_slice": NEXT_SLICE,
        "case_queue_source_table": CASE_TABLE,
        "case_queue_source_table_length": len(CASE_TABLE),
        "timeline_source_table": OPERATIONAL_EVENT_TABLE,
        "timeline_source_table_length": len(OPERATIONAL_EVENT_TABLE),
        "action_history_policy": "operational_events_first_no_action_table_in_s66",
        "source_tables": [
            {"table_name": CASE_TABLE, "role": "case_queue_source"},
            {"table_name": OPERATIONAL_EVENT_TABLE, "role": "case_action_timeline_source"},
            {"table_name": NOTE_TABLE, "role": "operator_note_metadata"},
            {"table_name": EXPORT_TABLE, "role": "redacted_evidence_export_metadata"},
        ],
        "read_model_surfaces": [
            "/admin/v1/operator-review/cases",
            "/admin/v1/operator-review/cases/{case_id}",
            "/admin/v1/operator-review/cases/rollups",
            "planned:/admin/v1/operator-review/cases/queue",
            "planned:/admin/v1/operator-review/cases/{case_id}/timeline",
            "planned:/admin/v1/operator-review/cases/{case_id}/evidence-links",
            "planned:/admin/v1/operator-review/cases/{case_id}/action-admission",
        ],
        "queue_filters": [
            "case_status",
            "case_priority",
            "assignee_id",
            "target_service",
            "target_kind",
            "target_id",
            "trace_id",
            "latest_action_type",
            "attention_status",
            "updated_from",
            "updated_to",
        ],
        "timeline_event_types": [
            "ag.operator_review_case.recorded",
            "ag.operator_review_case_action.recorded",
        ],
        "evidence_link_sources": [
            "operator_review_workbench_target",
            "operator_review_note_ref",
            "redacted_evidence_export_ref",
        ],
        "allowed_payload_shape": [
            "case_id",
            "case_status",
            "case_priority",
            "target_reference",
            "operator_ref",
            "assignment_ref",
            "safe_reason_codes",
            "hashes",
            "bounded_previews",
            "redaction_flags",
            "safe_event_details",
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
        "postgres_smoke_required_before_s66_closure": True,
        "ag_may_write_own_case_records": True,
        "case_workbench_is_read_model_first": True,
        "ag_may_mutate_source_service_records": False,
        "ag_may_copy_raw_source_payloads": False,
        "cross_service_database_write_allowed": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "keep_case_queue_read_model_separate_from_mutation_service": True,
        "reuse_ag_op_cases_instead_of_new_queue_table": True,
        "reuse_service_operational_events_for_timeline": True,
        "defer_action_history_table_until_event_queries_are_insufficient": True,
        "link_notes_and_exports_by_safe_refs_only": True,
        "keep_source_service_records_read_only": True,
        "expose_action_admission_before_new_mutations": True,
        "store_and_return_free_text_as_hash_and_short_preview_only": True,
        "require_real_nex_ag_test_db_smoke_before_s66_closure": True,
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
            "ag_operator_review_case_workbench_boundary_audit=fail "
            f"failed_checks={','.join(failed) or 'unknown'}"
        )
    boundary = evidence.get("case_workbench_boundary")
    table_results = evidence.get("table_name_results")
    return (
        "ag_operator_review_case_workbench_boundary_audit=pass "
        f"paths={_present_count(evidence.get('paths'))}/{len(REQUIRED_PATHS)} "
        f"tokens={_present_count(evidence.get('source_tokens'))}/{len(REQUIRED_SOURCE_TOKENS)} "
        f"token_groups={sum(1 for value in _grouped_token_status(evidence.get('source_tokens')).values() if value)}/"
        f"{len(_grouped_token_status(evidence.get('source_tokens')))} "
        f"tables={sum(1 for item in table_results or [] if item.get('within_limit'))}/{len(table_results or [])} "
        f"boundary={boundary.get('boundary') if isinstance(boundary, Mapping) else CASE_WORKBENCH_BOUNDARY} "
        f"case_table={CASE_TABLE} "
        "timeline=service_operational_events "
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
        description="Run the Slice 0651 AG operator review case workbench boundary audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print one-line summary.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    args = parser.parse_args(argv)

    evidence = run_ag_operator_review_case_workbench_boundary_audit()
    if args.output:
        write_audit_evidence(args.output, evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
