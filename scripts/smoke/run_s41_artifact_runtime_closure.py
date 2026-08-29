#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s41_artifact_runtime_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/nex_ae_api/chat.py",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/nex_ag/main.py",
    "database/nex-ae-api/migrations/0402_ae_artifact_persistence_foundation.sql",
    "database/nex-ae-api/migrations/0406_ae_artifact_handoff_trace_request_columns.sql",
    "database/nex-ae-api/migrations/0407_ae_chat_artifact_refs_foundation.sql",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_artifact_runtime_persistence_storage_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_postgres_smoke.py",
    "scripts/smoke/run_ae_chat_artifact_postgres_smoke.py",
    "scripts/smoke/run_s40_ae_web_repaired_response_review_closure.py",
    "scripts/smoke/run_s41_artifact_runtime_closure.py",
    "tests/test_ae_artifact_runtime_persistence_storage_boundary_audit.py",
    "tests/test_ae_artifact_postgres_smoke.py",
    "tests/test_ae_chat_artifact_postgres_smoke.py",
    "tests/test_nex_ae_artifacts.py",
    "tests/test_nex_ae_chat.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_s41_artifact_runtime_closure.py",
    "docs/README.md",
    "docs/slices/0401_ae_artifact_runtime_persistence_storage_boundary_audit.md",
    "docs/slices/0402_ae_artifact_postgresql_schema_migration_foundation.md",
    "docs/slices/0403_ae_artifact_sqlalchemy_repository_sqlite_regression.md",
    "docs/slices/0404_ae_rendered_artifact_local_storage_adapter.md",
    "docs/slices/0405_ae_artifact_service_api_persisted_wiring.md",
    "docs/slices/0406_ae_artifact_postgresql_smoke_evidence.md",
    "docs/slices/0407_ae_chat_artifact_refs_persistence_foundation.md",
    "docs/slices/0408_ae_chat_artifact_postgresql_smoke_evidence.md",
    "docs/slices/0409_ag_artifact_operations_read_model_foundation.md",
    "docs/slices/0410_s41_artifact_runtime_closure.md",
)

TOKEN_CHECKS = (
    (
        "s41_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s41_artifact_runtime_closure.py",
    ),
    (
        "s40_closure_dependency_still_registered",
        "scripts/quality/run_quality_gate.sh",
        "run_s40_ae_web_repaired_response_review_closure.py",
    ),
    (
        "artifact_boundary_audit_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_runtime_persistence_storage_boundary_audit.py",
    ),
    (
        "artifact_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_postgres_smoke.py",
    ),
    (
        "chat_artifact_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_chat_artifact_postgres_smoke.py",
    ),
    (
        "artifact_handoff_sqlalchemy_store",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "SqlAlchemyArtifactHandoffStore",
    ),
    (
        "artifact_record_sqlalchemy_store",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "SqlAlchemyArtifactRecordStore",
    ),
    (
        "artifact_local_storage_adapter",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "LocalRenderedArtifactStorage",
    ),
    (
        "chat_sqlalchemy_store",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "SqlAlchemyChatInteractionStore",
    ),
    (
        "chat_artifact_refs_table",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "ae_chat_artifact_refs",
    ),
    (
        "chat_artifact_links_route",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "artifact-links",
    ),
    (
        "ag_artifact_operations_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_DETAIL_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_artifact_http_client",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "HttpAeArtifactOperationsClient",
    ),
    (
        "ag_artifact_redaction_guard",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "assert_artifact_operation_projection_redacted",
    ),
    (
        "ag_artifact_route_registration",
        "services/nex-ag/nex_ag/main.py",
        "register_artifact_operation_routes(app)",
    ),
    (
        "artifact_schema_migration_record",
        "database/nex-ae-api/migrations/0402_ae_artifact_persistence_foundation.sql",
        "0402_ae_artifact_persistence_foundation",
    ),
    (
        "artifact_trace_migration_record",
        "database/nex-ae-api/migrations/0406_ae_artifact_handoff_trace_request_columns.sql",
        "0406_ae_artifact_handoff_trace_request_columns",
    ),
    (
        "chat_artifact_refs_migration_record",
        "database/nex-ae-api/migrations/0407_ae_chat_artifact_refs_foundation.sql",
        "0407_ae_chat_artifact_refs_foundation",
    ),
    (
        "artifact_postgres_live_smoke_evidence",
        "docs/slices/0406_ae_artifact_postgresql_smoke_evidence.md",
        "ae_artifact_postgres_smoke=pass",
    ),
    (
        "chat_artifact_postgres_live_smoke_evidence",
        "docs/slices/0408_ae_chat_artifact_postgresql_smoke_evidence.md",
        "ae_chat_artifact_postgres_smoke=pass",
    ),
    (
        "ag_artifact_operations_coverage_evidence",
        "docs/slices/0409_ag_artifact_operations_read_model_foundation.md",
        "services/nex-ag/nex_ag/artifact_operations.py` coverage `100%",
    ),
    (
        "s41_slice_index",
        "docs/README.md",
        "Slice 0410",
    ),
)


def run_s41_artifact_runtime_closure(root: Path = ROOT) -> dict[str, Any]:
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
        "slice_range": "0401-0410",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "redaction_summary": {
            "database_url_included": False,
            "service_token_included": False,
            "provider_api_key_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
            "raw_evidence_included": False,
            "storage_path_included": False,
            "rendered_markdown_included": False,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s41_artifact_runtime_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s41_artifact_runtime_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S41 artifact runtime closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s41_artifact_runtime_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        any(docs_dir.glob(f"{slice_id:04d}_*.md"))
        for slice_id in range(401, 411)
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
