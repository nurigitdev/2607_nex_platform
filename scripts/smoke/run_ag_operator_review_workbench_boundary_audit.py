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
SCHEMA_VERSION = "ag_operator_review_workbench_boundary_audit.v1"

SLICE_ID = "0631"
S64_SURFACE = "AG operator review workbench"
WORKBENCH_BOUNDARY = "ag_owned_operator_review_workbench_projection"
NOTE_TABLE = "ag_op_notes"
EXPORT_TABLE = "ag_ev_exports"
MAX_TABLE_NAME_LENGTH = 30
NEXT_SLICE = "Slice_0632"

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
        "Canonical SRS source for AG operator review capability.",
    ),
    RequiredPath(
        "service_partition",
        "docs/30_service_specific_requirement_partition.md",
        "Service ownership split for AG write APIs and read-only source records.",
    ),
    RequiredPath(
        "testing_strategy",
        "docs/34_testing_strategy_v0_1_detail.md",
        "Testing requirement for operator-note and export-denied branches.",
    ),
    RequiredPath(
        "design_system",
        "docs/35_design_system_v0_1_expansion.md",
        "AG dashboard operator review visibility guidance.",
    ),
    RequiredPath(
        "s63_closure",
        "scripts/smoke/run_s63_operator_review_evidence_closure.py",
        "Closed S63 note/export evidence baseline.",
    ),
    RequiredPath(
        "s63_closure_doc",
        "docs/slices/0630_s63_operator_review_evidence_closure.md",
        "S63 closure implementation note.",
    ),
    RequiredPath(
        "ag_operator_reviews",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "AG operator note and evidence export runtime surface.",
    ),
    RequiredPath(
        "ag_operations",
        "services/nex-ag/nex_ag/operations.py",
        "AG dashboard, rollup, and issue-candidate projection surface.",
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
        "note_schema",
        "contracts/schemas/generation/ag_operator_review_note.v1.schema.json",
        "Operator note contract shape.",
    ),
    RequiredPath(
        "export_schema",
        "contracts/schemas/generation/ag_redacted_evidence_export.v1.schema.json",
        "Redacted evidence export contract shape.",
    ),
    RequiredPath(
        "note_postgres_smoke",
        "scripts/smoke/run_ag_operator_review_note_postgres_smoke.py",
        "Protected test DB evidence for note path.",
    ),
    RequiredPath(
        "export_postgres_smoke",
        "scripts/smoke/run_ag_redacted_evidence_export_postgres_smoke.py",
        "Protected test DB evidence for export path.",
    ),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh", "Default regression gate."),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath("ag_readme", "services/nex-ag/README.md", "AG implementation notes."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s63_closed_baseline",
        "scripts/smoke/run_s63_operator_review_evidence_closure.py",
        "s63_closure_schema",
        "s63_operator_review_evidence_closure.v1",
        "S64 starts after S63 note/export capability is closed.",
    ),
    TokenRequirement(
        "s63_closed_baseline",
        "docs/slices/0630_s63_operator_review_evidence_closure.md",
        "s63_closed_boundary",
        "ag_owned_operator_review_notes_redacted_exports",
        "S64 workbench must build on the closed AG-owned note/export boundary.",
    ),
    TokenRequirement(
        "operator_review_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "note_table_constant",
        'AG_OPERATOR_NOTE_TABLE = "ag_op_notes"',
        "Workbench read-model inputs include the short note table.",
    ),
    TokenRequirement(
        "operator_review_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "export_table_constant",
        'AG_EVIDENCE_EXPORT_TABLE = "ag_ev_exports"',
        "Workbench read-model inputs include the short export table.",
    ),
    TokenRequirement(
        "operator_review_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "note_list_route",
        '"/admin/v1/operator-review/notes"',
        "Existing note collection route remains the mutation/read source.",
    ),
    TokenRequirement(
        "operator_review_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "export_list_route",
        '"/admin/v1/operator-review/evidence-exports"',
        "Existing export collection route remains the mutation/read source.",
    ),
    TokenRequirement(
        "operator_review_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "note_service",
        "class OperatorReviewNoteService",
        "Workbench should depend on the stable note service/store boundary.",
    ),
    TokenRequirement(
        "operator_review_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "export_service",
        "class OperatorEvidenceExportService",
        "Workbench should depend on the stable export service/store boundary.",
    ),
    TokenRequirement(
        "operations_projection_surface",
        "services/nex-ag/nex_ag/operations.py",
        "dashboard_projection",
        "ag_operations_dashboard_snapshot_projection.v1",
        "Workbench dashboard wiring should attach to the existing AG dashboard projection.",
    ),
    TokenRequirement(
        "operations_projection_surface",
        "services/nex-ag/nex_ag/operations.py",
        "issue_candidate_projection",
        "build_operations_issue_candidate_projection",
        "Workbench attention states should later flow into issue candidates.",
    ),
    TokenRequirement(
        "operations_projection_surface",
        "services/nex-ag/nex_ag/operations.py",
        "rollup_metrics_projection",
        "build_operations_rollup_metrics_projection",
        "Workbench counts should later integrate with existing rollup metrics.",
    ),
    TokenRequirement(
        "operator_review_contracts",
        "contracts/schemas/generation/ag_operator_review_note.v1.schema.json",
        "note_hash_storage",
        "note_hash",
        "Workbench must not require raw note text.",
    ),
    TokenRequirement(
        "operator_review_contracts",
        "contracts/schemas/generation/ag_redacted_evidence_export.v1.schema.json",
        "export_hash_storage",
        "evidence_hash",
        "Workbench must not require raw evidence bodies.",
    ),
    TokenRequirement(
        "operator_review_contracts",
        "scripts/smoke/run_ag_operator_review_note_postgres_smoke.py",
        "note_test_db_smoke_env",
        "NEX_AG_OPERATOR_REVIEW_NOTE_POSTGRES_SMOKE",
        "Workbench DB smoke should reuse the protected note evidence path.",
    ),
    TokenRequirement(
        "operator_review_contracts",
        "scripts/smoke/run_ag_redacted_evidence_export_postgres_smoke.py",
        "export_test_db_smoke_env",
        "NEX_AG_REDACTED_EVIDENCE_EXPORT_POSTGRES_SMOKE",
        "Workbench DB smoke should reuse the protected export evidence path.",
    ),
    TokenRequirement(
        "s64_boundary_docs",
        "docs/README.md",
        "s64_doc_indexed",
        "0631_ag_operator_review_workbench_boundary_audit.md",
        "Slice 0631 must be indexed.",
    ),
    TokenRequirement(
        "s64_boundary_docs",
        "services/nex-ag/README.md",
        "ag_s64_readme_note",
        "Slice 0631 starts S64",
        "AG README must record the workbench boundary.",
    ),
    TokenRequirement(
        "s64_boundary_docs",
        "scripts/quality/run_quality_gate.sh",
        "s64_boundary_quality_gate_hook",
        "run_ag_operator_review_workbench_boundary_audit.py",
        "Slice 0631 audit must run in the default quality gate.",
    ),
)

PLANNED_SLICES = (
    ("unified_read_model_projection", "Slice_0632", "Unify note/export rows by target reference."),
    ("rollup_metrics", "Slice_0633", "Summarize open/in-progress/resolved review counts."),
    ("dashboard_section", "Slice_0634", "Wire operator-review section into AG operations dashboard."),
    ("issue_candidate_correlation", "Slice_0635", "Correlate review attention with issue candidates."),
    ("search_filter_hardening", "Slice_0636", "Harden target, trace, operator, status, and date filters."),
    ("openapi_schema_examples", "Slice_0637", "Freeze workbench contract examples and negative fixtures."),
    ("postgres_smoke", "Slice_0638", "Prove workbench dashboard path against nex_ag_test."),
    ("privacy_regression_pack", "Slice_0639", "Guard against raw note/evidence/path/key leakage."),
    ("s64_closure", "Slice_0640", "Close S64 operator review workbench track."),
)

SOURCE_TABLE_NAMES = (NOTE_TABLE, EXPORT_TABLE)


def run_ag_operator_review_workbench_boundary_audit(
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
        "s63_closed_baseline_present": token_groups.get("s63_closed_baseline", False),
        "operator_review_runtime_present": token_groups.get("operator_review_runtime", False),
        "operations_projection_surface_present": token_groups.get(
            "operations_projection_surface", False
        ),
        "operator_review_contracts_present": token_groups.get(
            "operator_review_contracts", False
        ),
        "s64_boundary_docs_present": token_groups.get("s64_boundary_docs", False),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "slice": SLICE_ID,
        "surface": S64_SURFACE,
        "workbench_boundary": _workbench_boundary(),
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
        evidence["failure_code"] = "ag_operator_review_workbench_boundary_failed"
        evidence["issues"] = _issues(paths, tokens, table_names)
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), environment)
    return evidence


def _workbench_boundary() -> dict[str, Any]:
    return {
        "system_of_record": "nex-ag",
        "projection_owner": "nex-ag",
        "mutation_owner": "nex-ag",
        "boundary": WORKBENCH_BOUNDARY,
        "create_table_in_slice_0631": False,
        "first_read_model_slice": NEXT_SLICE,
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
        "workbench_inputs": [
            "operator_note_hash_preview_records",
            "redacted_evidence_export_manifest_records",
            "operations_dashboard_projection",
            "operations_issue_candidate_projection",
        ],
        "allowed_workbench_reads": [
            "ag_operator_note_records",
            "ag_redacted_evidence_export_records",
            "safe_operations_projection_records",
        ],
        "allowed_workbench_writes": [
            "none_new_in_slice_0631",
            "existing_note_mutations_only_through_operator_review_routes",
            "existing_export_mutations_only_through_operator_review_routes",
        ],
        "forbidden_workbench_payloads": [
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
        ],
        "dashboard_integration_policy": "read_model_before_dashboard_wiring",
        "issue_candidate_policy": "derive_from_safe_counts_and_status_only",
        "operator_auth_policy": "service_token_or_admin_user_claim_required",
        "postgres_smoke_required_before_operational_enablement": True,
        "ag_may_mutate_source_service_records": False,
        "ag_may_copy_raw_source_payloads": False,
        "cross_service_database_write_allowed": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "keep_workbench_projection_separate_from_mutation_services": True,
        "reuse_existing_note_and_export_stores_before_new_persistence": True,
        "avoid_new_table_in_slice_0631": True,
        "keep_source_service_records_read_only": True,
        "group_by_target_reference_before_dashboard_wiring": True,
        "attach_rollups_before_issue_candidates": True,
        "store_and_project_hash_preview_or_redacted_manifest_only": True,
        "do_not_project_raw_prompts_source_docs_provider_payloads_or_paths": True,
        "require_admin_or_service_claims_for_workbench_reads": True,
        "require_real_nex_ag_test_db_smoke_before_dashboard_section_closure": True,
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
    )
    for pattern in sensitive_patterns:
        if re.search(pattern, serialized):
            raise ValueError("Sensitive value leaked in audit evidence")


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "PASS":
        paths = _present_count(evidence.get("paths"))  # type: ignore[arg-type]
        tokens = _present_count(evidence.get("source_tokens"))  # type: ignore[arg-type]
        table_names = evidence.get("table_name_results")
        table_count = _present_count(
            [
                {"present": item.get("within_limit") is True}
                for item in table_names
            ]
            if isinstance(table_names, list)
            else None
        )
        checks = evidence.get("checks", {})
        token_groups = sum(
            1
            for key, value in checks.items()
            if key.endswith("_present") and value is True
        )
        total_token_groups = sum(1 for key in checks if key.endswith("_present"))
        return (
            "ag_operator_review_workbench_boundary_audit=pass "
            f"paths={paths}/{len(REQUIRED_PATHS)} "
            f"tokens={tokens}/{len(REQUIRED_SOURCE_TOKENS)} "
            f"token_groups={token_groups}/{total_token_groups} "
            f"tables={table_count}/{len(SOURCE_TABLE_NAMES)} "
            f"boundary={WORKBENCH_BOUNDARY} "
            f"note_table={NOTE_TABLE} "
            f"export_table={EXPORT_TABLE} "
            f"next={NEXT_SLICE}"
        )
    checks = evidence.get("checks") if isinstance(evidence.get("checks"), Mapping) else {}
    failing = ",".join(key for key, value in checks.items() if value is not True)
    return (
        "ag_operator_review_workbench_boundary_audit=fail "
        f"reason={evidence.get('failure_code')} "
        f"failing_checks={failing}"
    )


def write_audit_evidence(output_path: Path, evidence: Mapping[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run AG operator review workbench boundary audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print one-line summary.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    args = parser.parse_args(argv)

    evidence = run_ag_operator_review_workbench_boundary_audit()
    if args.output:
        write_audit_evidence(args.output, evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
