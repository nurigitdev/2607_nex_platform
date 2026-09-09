#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s63_operator_review_evidence_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/operator_reviews.py",
    "services/nex-ag/nex_ag/main.py",
    "services/nex-ag/README.md",
    "database/nex-ag/migrations/0622_ag_operator_review_note_persistence.sql",
    "database/nex-ag/migrations/0626_ag_redacted_evidence_export_persistence.sql",
    "contracts/schemas/generation/ag_operator_review_note.v1.schema.json",
    "contracts/schemas/generation/ag_redacted_evidence_export.v1.schema.json",
    "contracts/examples/generation/ag_operator_review_note.observation.json",
    "contracts/examples/generation/ag_redacted_evidence_export.worker_result.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_note_export_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_note_postgres_smoke.py",
    "scripts/smoke/run_ag_redacted_evidence_export_postgres_smoke.py",
    "scripts/smoke/run_s63_operator_review_evidence_closure.py",
    "tests/test_ag_operator_review_note_export_boundary_audit.py",
    "tests/test_nex_ag_operator_reviews.py",
    "tests/test_nex_ag_operator_review_exports.py",
    "tests/test_ag_operator_review_note_postgres_smoke.py",
    "tests/test_ag_redacted_evidence_export_postgres_smoke.py",
    "tests/test_s63_operator_review_evidence_closure.py",
    "docs/README.md",
    "docs/slices/0621_ag_operator_review_note_export_boundary_audit.md",
    "docs/slices/0622_ag_operator_review_note_persistence.md",
    "docs/slices/0623_ag_operator_review_note_service.md",
    "docs/slices/0624_ag_operator_review_note_routes.md",
    "docs/slices/0625_ag_operator_review_note_postgresql_smoke.md",
    "docs/slices/0626_ag_redacted_evidence_export_persistence.md",
    "docs/slices/0627_ag_redacted_evidence_export_service.md",
    "docs/slices/0628_ag_redacted_evidence_export_routes.md",
    "docs/slices/0629_ag_redacted_evidence_export_postgresql_smoke.md",
    "docs/slices/0630_s63_operator_review_evidence_closure.md",
)

TOKEN_CHECKS = (
    (
        "s63_boundary_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_note_export_boundary_audit.py",
    ),
    (
        "note_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_operator_review_note_postgres_smoke.py",
    ),
    (
        "export_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_redacted_evidence_export_postgres_smoke.py",
    ),
    (
        "s63_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s63_operator_review_evidence_closure.py",
    ),
    (
        "note_table_constant",
        "services/nex-ag/nex_ag/operator_reviews.py",
        'AG_OPERATOR_NOTE_TABLE = "ag_op_notes"',
    ),
    (
        "export_table_constant",
        "services/nex-ag/nex_ag/operator_reviews.py",
        'AG_EVIDENCE_EXPORT_TABLE = "ag_ev_exports"',
    ),
    (
        "note_sqlalchemy_store",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "SqlAlchemyOperatorReviewNoteStore",
    ),
    (
        "export_sqlalchemy_store",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "SqlAlchemyOperatorEvidenceExportStore",
    ),
    (
        "note_service",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "class OperatorReviewNoteService",
    ),
    (
        "export_service",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "class OperatorEvidenceExportService",
    ),
    (
        "note_idempotency_required",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "ag.operator_review_note_idempotency_key_required",
    ),
    (
        "export_idempotency_required",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "ag.evidence_export_idempotency_key_required",
    ),
    (
        "note_route",
        "services/nex-ag/nex_ag/operator_reviews.py",
        '"/admin/v1/operator-review/notes"',
    ),
    (
        "export_route",
        "services/nex-ag/nex_ag/operator_reviews.py",
        '"/admin/v1/operator-review/evidence-exports"',
    ),
    (
        "note_event",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "ag.operator_review_note.recorded",
    ),
    (
        "export_event",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "ag.evidence_export.recorded",
    ),
    (
        "note_migration_table",
        "database/nex-ag/migrations/0622_ag_operator_review_note_persistence.sql",
        "CREATE TABLE IF NOT EXISTS ag_op_notes",
    ),
    (
        "export_migration_table",
        "database/nex-ag/migrations/0626_ag_redacted_evidence_export_persistence.sql",
        "CREATE TABLE IF NOT EXISTS ag_ev_exports",
    ),
    (
        "note_postgres_opt_in",
        "scripts/smoke/run_ag_operator_review_note_postgres_smoke.py",
        "NEX_AG_OPERATOR_REVIEW_NOTE_POSTGRES_SMOKE",
    ),
    (
        "export_postgres_opt_in",
        "scripts/smoke/run_ag_redacted_evidence_export_postgres_smoke.py",
        "NEX_AG_REDACTED_EVIDENCE_EXPORT_POSTGRES_SMOKE",
    ),
    (
        "note_postgres_direct_table_check",
        "scripts/smoke/run_ag_operator_review_note_postgres_smoke.py",
        "ag_op_notes",
    ),
    (
        "export_postgres_direct_table_check",
        "scripts/smoke/run_ag_redacted_evidence_export_postgres_smoke.py",
        "ag_ev_exports",
    ),
    (
        "export_contract_schema",
        "contracts/schemas/generation/ag_redacted_evidence_export.v1.schema.json",
        "redacted_manifest_plus_hashes",
    ),
    (
        "export_example_manifest_hash",
        "contracts/examples/generation/ag_redacted_evidence_export.worker_result.json",
        "evidence_hash",
    ),
    (
        "s63_doc_index_0630",
        "docs/README.md",
        "Slice 0630",
    ),
)

REDACTION_SCAN_FILES = (
    "services/nex-ag/README.md",
    "docs/slices/0621_ag_operator_review_note_export_boundary_audit.md",
    "docs/slices/0622_ag_operator_review_note_persistence.md",
    "docs/slices/0623_ag_operator_review_note_service.md",
    "docs/slices/0624_ag_operator_review_note_routes.md",
    "docs/slices/0625_ag_operator_review_note_postgresql_smoke.md",
    "docs/slices/0626_ag_redacted_evidence_export_persistence.md",
    "docs/slices/0627_ag_redacted_evidence_export_service.md",
    "docs/slices/0628_ag_redacted_evidence_export_routes.md",
    "docs/slices/0629_ag_redacted_evidence_export_postgresql_smoke.md",
    "docs/slices/0630_s63_operator_review_evidence_closure.md",
)


def run_s63_operator_review_evidence_closure(root: Path = ROOT) -> dict[str, Any]:
    required_file_results = _required_file_results(root)
    token_results = _token_results(root)
    redaction_summary = _redaction_summary(root)
    table_lengths = {"ag_op_notes": len("ag_op_notes"), "ag_ev_exports": len("ag_ev_exports")}
    checks = {
        "required_files_present": all(
            item["present"] for item in required_file_results
        ),
        "token_checks_present": all(item["present"] for item in token_results),
        "slice_docs_contiguous": _slice_docs_contiguous(root),
        "redaction_scan_safe": not any(
            value is True
            for key, value in redaction_summary.items()
            if key.endswith("_included")
        ),
        "table_names_short": all(length <= 30 for length in table_lengths.values()),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    evidence = {
        "closure_schema_version": SCHEMA_VERSION,
        "status": status,
        "slice_range": "0621-0630",
        "owned_tables": table_lengths,
        "boundary": "ag_owned_operator_review_notes_redacted_exports",
        "raw_payload_storage": "hash_preview_or_redacted_manifest_only",
        "required_file_count": len(REQUIRED_FILES),
        "token_check_count": len(TOKEN_CHECKS),
        "checks": checks,
        "experience_matrix": _experience_matrix(token_results),
        "redaction_summary": redaction_summary,
        "required_file_results": required_file_results,
        "token_results": token_results,
    }
    if status != "PASS":
        evidence["failure_code"] = "closure_checks_failed"
        evidence["failed_checks"] = [
            key for key, passed in checks.items() if not passed
        ]
    return evidence


def _required_file_results(root: Path) -> list[dict[str, Any]]:
    return [
        {"path": relative_path, "present": (root / relative_path).is_file()}
        for relative_path in REQUIRED_FILES
    ]


def _token_results(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for check_id, relative_path, token in TOKEN_CHECKS:
        text = _read_text(root / relative_path)
        results.append(
            {"check_id": check_id, "path": relative_path, "present": token in text}
        )
    return results


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    if not docs_dir.is_dir():
        return False
    existing = {path.name for path in docs_dir.glob("*.md")}
    return all(
        any(name.startswith(f"{number:04d}_") for name in existing)
        for number in range(621, 631)
    )


def _experience_matrix(token_results: list[dict[str, Any]]) -> dict[str, bool]:
    present = {item["check_id"]: item["present"] for item in token_results}
    return {
        "boundary_audit": present.get("s63_boundary_quality_gate_hook", False)
        and present.get("note_table_constant", False)
        and present.get("export_table_constant", False),
        "note_schema_store_foundation": present.get("note_migration_table", False)
        and present.get("note_sqlalchemy_store", False),
        "note_service_idempotency": present.get("note_service", False)
        and present.get("note_idempotency_required", False),
        "note_protected_routes": present.get("note_route", False)
        and present.get("note_event", False),
        "note_postgresql_smoke": present.get("note_postgres_quality_gate_hook", False)
        and present.get("note_postgres_direct_table_check", False),
        "export_schema_store_foundation": present.get(
            "export_migration_table", False
        )
        and present.get("export_sqlalchemy_store", False)
        and present.get("export_contract_schema", False),
        "export_service_idempotency": present.get("export_service", False)
        and present.get("export_idempotency_required", False),
        "export_protected_routes": present.get("export_route", False)
        and present.get("export_event", False),
        "export_postgresql_smoke": present.get(
            "export_postgres_quality_gate_hook", False
        )
        and present.get("export_postgres_direct_table_check", False),
        "closure_checkpoint": present.get("s63_closure_quality_gate_hook", False)
        and present.get("s63_doc_index_0630", False),
    }


def _redaction_summary(root: Path) -> dict[str, bool]:
    text = "\n".join(_read_text(root / path) for path in REDACTION_SCAN_FILES)
    return {
        "database_url_included": bool(
            re.search(r"postgres(?:ql)?(?:\+psycopg)?://[^*\s]+:[^*\s]+@", text)
        ),
        "shared_password_included": "nuri1004" in text,
        "provider_api_key_included": "ed6@c496em" in text,
        "raw_operator_note_included": "raw note text must not appear" in text,
        "raw_evidence_body_included": "raw body leaked" in text,
        "idempotency_key_included": "ag-ev-export-smoke-idem" in text
        or "ag-op-note-smoke-idem" in text,
        "storage_path_included": "/data/nex-platform" in text,
        "note_hash_preview_documented": "SHA-256 hash plus bounded preview" in text
        or "SHA-256 hashes plus bounded previews" in text,
        "export_redacted_manifest_documented": (
            "redacted manifest" in text
            and "SHA-256 hashes" in text
        ),
        "protected_postgres_smoke_envs_required": (
            "NEX_AG_OPERATOR_REVIEW_NOTE_POSTGRES_SMOKE=1" in text
            and "NEX_AG_REDACTED_EVIDENCE_EXPORT_POSTGRES_SMOKE=1" in text
        ),
        "ag_owned_boundary_documented": "AG-owned" in text
        or "AG-owned" in _read_text(root / "docs" / "README.md"),
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s63_operator_review_evidence_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']} "
            f"boundary={evidence['boundary']} "
            "note_table=ag_op_notes export_table=ag_ev_exports "
            "smoke=test_db_note_and_export"
        )
    failed = ",".join(evidence.get("failed_checks", []))
    return f"s63_operator_review_evidence_closure=fail failed_checks={failed}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the S63 operator review evidence closure checkpoint."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s63_operator_review_evidence_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
