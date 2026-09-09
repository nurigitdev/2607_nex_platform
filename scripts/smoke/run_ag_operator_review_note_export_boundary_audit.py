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
SCHEMA_VERSION = "ag_operator_review_note_export_boundary_audit.v1"

S63_SURFACE = "AG operator review notes and redacted evidence export"
OPERATOR_REVIEW_BOUNDARY = "ag_owned_operator_review_notes_redacted_exports"
NOTE_TABLE = "ag_op_notes"
EXPORT_TABLE = "ag_ev_exports"
MAX_TABLE_NAME_LENGTH = 30
NEXT_SLICE = "Slice_0622"

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
        "Canonical SRS requirement source.",
    ),
    RequiredPath(
        "service_partition",
        "docs/30_service_specific_requirement_partition.md",
        "Service ownership split for AG write APIs.",
    ),
    RequiredPath(
        "testing_strategy",
        "docs/34_testing_strategy_v0_1_detail.md",
        "Admin branch coverage themes for operator notes and export denial.",
    ),
    RequiredPath(
        "design_system",
        "docs/35_design_system_v0_1_expansion.md",
        "AG dashboard design requirement for operator note visibility.",
    ),
    RequiredPath(
        "s62_closure",
        "scripts/smoke/run_s62_ae_worker_result_persistence_closure.py",
        "Closed S62 worker-result persistence/read-model baseline.",
    ),
    RequiredPath(
        "s62_closure_doc",
        "docs/slices/0620_s62_ae_worker_result_persistence_closure.md",
        "S62 closure implementation note.",
    ),
    RequiredPath(
        "ag_operations",
        "services/nex-ag/nex_ag/operations.py",
        "AG unified operations projection surface.",
    ),
    RequiredPath(
        "ag_artifact_operations",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG artifact operation and worker-result diagnostics surface.",
    ),
    RequiredPath(
        "ag_quality_disposition",
        "services/nex-ag/nex_ag/generation_quality_disposition.py",
        "Existing AG-owned operator note hash/preview write pattern.",
    ),
    RequiredPath(
        "ag_quality_disposition_migration",
        "database/nex-ag/migrations/0337_ag_generation_quality_operator_disposition_persistence.sql",
        "Existing AG-owned operator disposition persistence baseline.",
    ),
    RequiredPath(
        "ag_remediation_task_migration",
        "database/nex-ag/migrations/0345_ag_generation_remediation_task_persistence.sql",
        "Existing AG-owned remediation task persistence baseline.",
    ),
    RequiredPath(
        "s63_boundary_audit",
        "scripts/smoke/run_ag_operator_review_note_export_boundary_audit.py",
        "S63 operator note/export boundary audit runner.",
    ),
    RequiredPath(
        "s63_boundary_test",
        "tests/test_ag_operator_review_note_export_boundary_audit.py",
        "S63 boundary regression tests.",
    ),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh", "Default regression gate."),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath("ag_readme", "services/nex-ag/README.md", "AG implementation notes."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s62_closed_baseline",
        "scripts/smoke/run_s62_ae_worker_result_persistence_closure.py",
        "s62_closure_schema",
        "s62_ae_worker_result_persistence_closure.v1",
        "S63 starts after the worker-result persistence/read-model track is closed.",
    ),
    TokenRequirement(
        "s62_closed_baseline",
        "docs/slices/0620_s62_ae_worker_result_persistence_closure.md",
        "s62_next_slice",
        "Slice 0621 can start the next capability track",
        "S62 closure leaves the next capability track open.",
    ),
    TokenRequirement(
        "srs_operator_review_requirement",
        "docs/29_nex_platform_mvp_srs_v0_1_assembly.md",
        "srs_ag_fr_004",
        "AG-FR-004",
        "S63 implements the AG operator note and export requirement family.",
    ),
    TokenRequirement(
        "srs_operator_review_requirement",
        "docs/29_nex_platform_mvp_srs_v0_1_assembly.md",
        "srs_operator_notes_export",
        "Support operator notes and redacted evidence export",
        "SRS names the core operator review capability.",
    ),
    TokenRequirement(
        "srs_operator_review_requirement",
        "docs/30_service_specific_requirement_partition.md",
        "partition_ag_write_apis",
        "AG write APIs",
        "Operator review persistence belongs in AG, not in observed services.",
    ),
    TokenRequirement(
        "srs_operator_review_requirement",
        "docs/34_testing_strategy_v0_1_detail.md",
        "admin_operator_note_branch",
        "operator note",
        "Regression coverage should include operator-note branches.",
    ),
    TokenRequirement(
        "srs_operator_review_requirement",
        "docs/34_testing_strategy_v0_1_detail.md",
        "admin_export_denied_branch",
        "export denied",
        "Regression coverage should include export-denied branches.",
    ),
    TokenRequirement(
        "srs_operator_review_requirement",
        "docs/35_design_system_v0_1_expansion.md",
        "design_operator_note",
        "operator note",
        "AG dashboard design expects visible operator-note context.",
    ),
    TokenRequirement(
        "ag_existing_owned_write_pattern",
        "services/nex-ag/nex_ag/generation_quality_disposition.py",
        "quality_disposition_schema",
        "ag_generation_quality_operator_disposition.v1",
        "AG already owns bounded operator disposition records.",
    ),
    TokenRequirement(
        "ag_existing_owned_write_pattern",
        "services/nex-ag/nex_ag/generation_quality_disposition.py",
        "operator_note_hash",
        "operator_note_hash",
        "Free-text operator notes should store a hash for correlation.",
    ),
    TokenRequirement(
        "ag_existing_owned_write_pattern",
        "services/nex-ag/nex_ag/generation_quality_disposition.py",
        "operator_note_preview",
        "operator_note_preview",
        "Free-text operator notes should store only a short preview.",
    ),
    TokenRequirement(
        "ag_existing_owned_write_pattern",
        "services/nex-ag/nex_ag/generation_quality_disposition.py",
        "note_storage_policy",
        "hash_and_short_preview_only",
        "The generic note boundary should reuse the existing AG redaction style.",
    ),
    TokenRequirement(
        "ag_existing_owned_write_pattern",
        "database/nex-ag/migrations/0337_ag_generation_quality_operator_disposition_persistence.sql",
        "quality_disposition_table",
        "ag_generation_quality_operator_dispositions",
        "Existing AG-owned table proves AG can persist operator review metadata.",
    ),
    TokenRequirement(
        "ag_existing_owned_write_pattern",
        "database/nex-ag/migrations/0345_ag_generation_remediation_task_persistence.sql",
        "remediation_task_table",
        "ag_generation_remediation_tasks",
        "Existing AG-owned remediation table proves AG-owned operational write scope.",
    ),
    TokenRequirement(
        "ag_read_projection_sources",
        "services/nex-ag/nex_ag/operations.py",
        "unified_operations_projection",
        "ag_unified_operations_projection.v1",
        "Operator notes and exports should attach to existing AG projection targets.",
    ),
    TokenRequirement(
        "ag_read_projection_sources",
        "services/nex-ag/nex_ag/operations.py",
        "dashboard_projection",
        "ag_operations_dashboard_snapshot_projection.v1",
        "Dashboard integration should remain projection-first.",
    ),
    TokenRequirement(
        "ag_read_projection_sources",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "worker_result_diagnostics_projection",
        "ag_artifact_operation_retention_daemon_operator_control_execution_worker_result_diagnostics_projection.v1",
        "S63 can attach review metadata to the S62 diagnostics surface.",
    ),
    TokenRequirement(
        "ag_read_projection_sources",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "ag_direct_database_write_disallowed",
        '"ag_direct_database_write_allowed": False',
        "AG must not write into AE worker-result persistence.",
    ),
    TokenRequirement(
        "ag_read_projection_sources",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "ag_direct_job_enqueue_disallowed",
        '"ag_direct_job_enqueue_allowed": False',
        "Operator review notes must not become a backdoor AE job enqueue path.",
    ),
    TokenRequirement(
        "s63_boundary_docs",
        "docs/slices/0621_ag_operator_review_note_export_boundary_audit.md",
        "candidate_note_table",
        NOTE_TABLE,
        "Slice 0621 must document the short note table candidate.",
    ),
    TokenRequirement(
        "s63_boundary_docs",
        "docs/slices/0621_ag_operator_review_note_export_boundary_audit.md",
        "candidate_export_table",
        EXPORT_TABLE,
        "Slice 0621 must document the short export table candidate.",
    ),
    TokenRequirement(
        "s63_boundary_docs",
        "docs/slices/0621_ag_operator_review_note_export_boundary_audit.md",
        "hash_preview_policy",
        "hash + short preview",
        "Slice 0621 must document the free-text storage rule.",
    ),
    TokenRequirement(
        "s63_boundary_docs",
        "docs/slices/0621_ag_operator_review_note_export_boundary_audit.md",
        "redacted_manifest_policy",
        "redacted evidence manifest",
        "Slice 0621 must document export redaction scope.",
    ),
    TokenRequirement(
        "quality_docs",
        "scripts/quality/run_quality_gate.sh",
        "s63_boundary_quality_gate_hook",
        "run_ag_operator_review_note_export_boundary_audit.py",
        "Slice 0621 audit must run in the default quality gate.",
    ),
    TokenRequirement(
        "quality_docs",
        "docs/README.md",
        "s63_doc_indexed",
        "0621_ag_operator_review_note_export_boundary_audit.md",
        "Slice 0621 must be indexed.",
    ),
    TokenRequirement(
        "quality_docs",
        "services/nex-ag/README.md",
        "ag_s63_readme_note",
        "Slice 0621 starts S63",
        "AG notes must record the operator note/export boundary.",
    ),
)

PLANNED_SLICES = (
    ("operator_note_schema_store", "Slice_0622", "AG operator note schema/store foundation."),
    ("operator_note_repository_api", "Slice_0623", "AG operator note service/repository API."),
    ("operator_note_routes", "Slice_0624", "AG operator note protected route wiring."),
    ("operator_note_postgres_smoke", "Slice_0625", "AG operator note PostgreSQL smoke evidence."),
    ("evidence_export_contract", "Slice_0626", "AG redacted evidence export contract/schema."),
    ("evidence_export_builder_api", "Slice_0627", "AG redacted evidence export builder/API wiring."),
    ("evidence_export_postgres_smoke", "Slice_0628", "AG evidence export PostgreSQL smoke evidence."),
    ("operations_dashboard_note_export", "Slice_0629", "AG operations dashboard note/export integration."),
    ("s63_closure", "Slice_0630", "S63 operator review evidence closure checkpoint."),
)

CANDIDATE_TABLE_NAMES = (NOTE_TABLE, EXPORT_TABLE)


def run_ag_operator_review_note_export_boundary_audit(
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
        "table_name_lengths_safe": all(
            item["within_limit"] for item in table_names
        ),
        "s62_closed_baseline_present": token_groups.get(
            "s62_closed_baseline", False
        ),
        "srs_operator_review_requirement_present": token_groups.get(
            "srs_operator_review_requirement", False
        ),
        "ag_existing_owned_write_pattern_present": token_groups.get(
            "ag_existing_owned_write_pattern", False
        ),
        "ag_read_projection_sources_present": token_groups.get(
            "ag_read_projection_sources", False
        ),
        "s63_boundary_docs_present": token_groups.get("s63_boundary_docs", False),
        "quality_docs_present": token_groups.get("quality_docs", False),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "slice": "0621",
        "surface": S63_SURFACE,
        "operator_review_boundary": _operator_review_boundary(),
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
        evidence["failure_code"] = "ag_operator_review_note_export_boundary_failed"
        evidence["issues"] = _issues(paths, tokens, table_names)
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), environment)
    return evidence


def _operator_review_boundary() -> dict[str, Any]:
    return {
        "system_of_record": "nex-ag",
        "persistence_owner": "nex-ag",
        "source_record_owners": ["nex-ae-api", "nex-cx", "nex-mo", "nex-oa"],
        "boundary": OPERATOR_REVIEW_BOUNDARY,
        "create_table_in_slice_0621": False,
        "first_schema_slice": NEXT_SLICE,
        "candidate_note_table": NOTE_TABLE,
        "candidate_note_table_length": len(NOTE_TABLE),
        "candidate_export_table": EXPORT_TABLE,
        "candidate_export_table_length": len(EXPORT_TABLE),
        "max_table_name_length": MAX_TABLE_NAME_LENGTH,
        "target_reference_columns": [
            "target_service",
            "target_kind",
            "target_id",
            "trace_id",
            "request_id",
        ],
        "target_reference_columns_indexable": True,
        "note_storage_shape": "hash_and_short_preview_only",
        "note_preview_max_chars": 240,
        "export_storage_shape": "redacted_manifest_plus_hashes",
        "export_payload_body_storage_deferred": True,
        "allowed_ag_writes": [
            "operator_note_metadata",
            "operator_note_hash",
            "operator_note_preview",
            "redacted_evidence_manifest",
            "export_request_metadata",
            "export_hashes",
        ],
        "forbidden_write_payloads": [
            "raw_operator_note_text",
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
        ],
        "ag_may_write_own_review_records": True,
        "ag_may_mutate_source_service_records": False,
        "ag_may_copy_raw_source_payloads": False,
        "cross_service_database_write_allowed": False,
        "oa_admin_claim_required": True,
        "idempotency_key_required_for_create": True,
        "test_profile_postgres_smoke_required": True,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "separate_operator_review_records_from_source_projections": True,
        "keep_ag_owned_write_models_in_nex_ag": True,
        "keep_source_records_read_only_through_service_apis": True,
        "split_target_reference_into_indexable_columns": True,
        "add_repository_before_route_wiring": True,
        "store_free_text_as_hash_and_short_preview_only": True,
        "store_exports_as_redacted_manifest_plus_hashes": True,
        "defer_export_payload_file_storage_until_manifest_is_stable": True,
        "require_oa_admin_claims_for_create_routes": True,
        "require_idempotency_keys_for_mutating_routes": True,
        "require_real_nex_ag_test_db_smoke_before_dashboard_write_enablement": True,
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
        for table_name in CANDIDATE_TABLE_NAMES
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
            "ag_operator_review_note_export_boundary_audit=pass "
            f"paths={paths}/{len(REQUIRED_PATHS)} "
            f"tokens={tokens}/{len(REQUIRED_SOURCE_TOKENS)} "
            f"token_groups={token_groups}/{total_token_groups} "
            f"tables={table_count}/{len(CANDIDATE_TABLE_NAMES)} "
            f"boundary={OPERATOR_REVIEW_BOUNDARY} "
            f"note_table={NOTE_TABLE} "
            f"export_table={EXPORT_TABLE} "
            f"next={NEXT_SLICE}"
        )
    checks = evidence.get("checks") if isinstance(evidence.get("checks"), Mapping) else {}
    failing = ",".join(key for key, value in checks.items() if value is not True)
    return (
        "ag_operator_review_note_export_boundary_audit=fail "
        f"reason={evidence.get('failure_code')} "
        f"failing_checks={failing}"
    )


def write_audit_evidence(output_path: Path, evidence: Mapping[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit the S63 AG operator review note/export boundary."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a concise summary line instead of JSON evidence.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path where JSON evidence should be written.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_operator_review_note_export_boundary_audit()
    if args.output is not None:
        write_audit_evidence(args.output, evidence)
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
