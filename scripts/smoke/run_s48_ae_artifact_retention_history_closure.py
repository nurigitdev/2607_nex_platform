#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s48_ae_artifact_retention_history_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "database/nex-ae-api/migrations/0472_ae_artifact_retention_execution_history.sql",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_artifact_retention_history_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_retention_history_postgres_smoke.py",
    "scripts/smoke/run_ae_artifact_retention_history_query_postgres_smoke.py",
    "scripts/smoke/run_s48_ae_artifact_retention_history_closure.py",
    "tests/test_ae_artifact_retention_history_boundary_audit.py",
    "tests/test_ae_artifact_retention_history_postgres_smoke.py",
    "tests/test_ae_artifact_retention_history_query_postgres_smoke.py",
    "tests/test_nex_ae_artifacts.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_s48_ae_artifact_retention_history_closure.py",
    "docs/README.md",
    "docs/slices/0471_ae_artifact_retention_execution_history_boundary_audit.md",
    "docs/slices/0472_ae_artifact_retention_execution_history_migration.md",
    "docs/slices/0473_ae_artifact_retention_execution_history_repository.md",
    "docs/slices/0474_ae_artifact_retention_purge_api_history_wiring.md",
    "docs/slices/0475_ae_artifact_retention_history_postgresql_smoke.md",
    "docs/slices/0476_ae_artifact_retention_history_read_model.md",
    "docs/slices/0477_ae_artifact_retention_history_api_wiring.md",
    "docs/slices/0478_ae_artifact_retention_history_query_postgresql_smoke.md",
    "docs/slices/0479_ag_artifact_retention_history_operations_projection.md",
    "docs/slices/0480_s48_ae_artifact_retention_history_closure.md",
)

TOKEN_CHECKS = (
    (
        "s48_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s48_ae_artifact_retention_history_closure.py",
    ),
    (
        "history_boundary_audit_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_history_boundary_audit.py",
    ),
    (
        "history_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_history_postgres_smoke.py",
    ),
    (
        "history_query_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_history_query_postgres_smoke.py",
    ),
    (
        "ae_history_record_schema",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_EXECUTION_HISTORY_SCHEMA_VERSION",
    ),
    (
        "ae_history_collection_schema",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_EXECUTION_HISTORY_COLLECTION_SCHEMA_VERSION",
    ),
    (
        "ae_history_item_schema",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_EXECUTION_HISTORY_ITEM_SCHEMA_VERSION",
    ),
    (
        "ae_history_repository",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "SqlAlchemyArtifactRetentionExecutionHistoryStore",
    ),
    (
        "ae_history_filter_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_retention_execution_history_filter",
    ),
    (
        "ae_history_collection_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_retention_execution_history_collection",
    ),
    (
        "ae_history_query_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/executions"',
    ),
    (
        "ae_purge_history_writer_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/purge"',
    ),
    (
        "ae_history_payload_hash",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "execution_payload_hash",
    ),
    (
        "ae_history_table_migration",
        "database/nex-ae-api/migrations/0472_ae_artifact_retention_execution_history.sql",
        "ae_artifact_retention_executions",
    ),
    (
        "history_query_smoke_env",
        "scripts/smoke/run_ae_artifact_retention_history_query_postgres_smoke.py",
        "NEX_AE_ARTIFACT_RETENTION_HISTORY_QUERY_POSTGRES_SMOKE",
    ),
    (
        "history_query_live_db_check",
        "scripts/smoke/run_ae_artifact_retention_history_query_postgres_smoke.py",
        "live_db",
    ),
    (
        "history_query_metadata_only_check",
        "scripts/smoke/run_ae_artifact_retention_history_query_postgres_smoke.py",
        "metadata_only_evidence",
    ),
    (
        "ag_retention_history_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_retention_history_client_method",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "list_artifact_retention_executions",
    ),
    (
        "ag_retention_history_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"/admin/v1/operations/artifact-retention/executions"',
    ),
    (
        "s48_slice_index",
        "docs/README.md",
        "Slice 0480",
    ),
    (
        "s48_ae_readme_query_smoke_note",
        "services/nex-ae-api/README.md",
        "Slice 0478 adds protected PostgreSQL smoke evidence",
    ),
    (
        "s48_ag_readme_projection_note",
        "services/nex-ag/README.md",
        "Slice 0479 adds",
    ),
)


def run_s48_ae_artifact_retention_history_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    missing_files = [
        relative_path
        for relative_path in REQUIRED_FILES
        if not (root / relative_path).is_file()
    ]
    token_results = [
        {
            "check_id": check_id,
            "path": relative_path,
            "present": token in _read_text(root / relative_path),
        }
        for check_id, relative_path, token in TOKEN_CHECKS
    ]
    checks = {
        "required_files_present": not missing_files,
        "token_checks_present": all(item["present"] for item in token_results),
        "slice_docs_contiguous": _slice_docs_contiguous(root),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": None if status == "PASS" else "closure_checks_failed",
        "slice_range": "0471-0480",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "experience_matrix": {
            "history_boundary_audit": True,
            "history_postgresql_migration": True,
            "history_repository": True,
            "purge_api_history_writer": True,
            "history_postgresql_writer_smoke": True,
            "history_read_model": True,
            "history_query_api": True,
            "history_query_postgresql_smoke": True,
            "ag_operations_projection": True,
            "closure_checkpoint": True,
        },
        "redaction_summary": {
            "database_url_included": False,
            "service_token_included": False,
            "provider_api_key_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_in_query_included": False,
            "raw_download_content_included": False,
            "storage_path_included": False,
            "storage_ref_included": False,
            "execution_payload_hash_available": True,
            "ae_system_of_record": True,
            "ag_projection_read_only": True,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s48_ae_artifact_retention_history_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s48_ae_artifact_retention_history_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S48 AE artifact retention history closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s48_ae_artifact_retention_history_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        (docs_dir / f"{slice_no:04d}_{suffix}.md").is_file()
        for slice_no, suffix in (
            (471, "ae_artifact_retention_execution_history_boundary_audit"),
            (472, "ae_artifact_retention_execution_history_migration"),
            (473, "ae_artifact_retention_execution_history_repository"),
            (474, "ae_artifact_retention_purge_api_history_wiring"),
            (475, "ae_artifact_retention_history_postgresql_smoke"),
            (476, "ae_artifact_retention_history_read_model"),
            (477, "ae_artifact_retention_history_api_wiring"),
            (478, "ae_artifact_retention_history_query_postgresql_smoke"),
            (479, "ag_artifact_retention_history_operations_projection"),
            (480, "s48_ae_artifact_retention_history_closure"),
        )
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
