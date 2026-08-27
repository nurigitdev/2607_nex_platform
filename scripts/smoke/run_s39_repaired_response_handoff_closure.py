#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s39_repaired_response_handoff_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/repaired_response_boundary.py",
    "services/nex-ae-api/nex_ae_api/repaired_response_client.py",
    "services/nex-ae-api/nex_ae_api/repaired_responses.py",
    "services/nex-ae-api/nex_ae_api/repaired_response_review.py",
    "services/nex-ae-api/nex_ae_api/repaired_response_decisions.py",
    "services/nex-ae-api/nex_ae_api/main.py",
    "services/nex-cx/nex_cx/remediation_execution.py",
    "contracts/openapi/nex-ae-api.openapi.yaml",
    "contracts/openapi/nex-cx.openapi.yaml",
    "contracts/schemas/service/nex_ae_api/repaired_response_handoff.v1.schema.json",
    "contracts/schemas/service/nex_ae_api/repaired_response_review_projection.v1.schema.json",
    "contracts/schemas/service/nex_ae_api/repaired_response_decision.v1.schema.json",
    "contracts/examples/generation/ae_repaired_response_handoff.ready_for_review.json",
    "contracts/tests/negative/generation/ae_repaired_response_handoff.raw_output_field.json",
    "database/nex-ae-api/migrations/0383_ae_repaired_response_handoff_persistence.sql",
    "database/nex-ae-api/migrations/0387_ae_repaired_response_decision_persistence.sql",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_repaired_response_handoff_postgres_smoke.py",
    "scripts/smoke/run_ae_repaired_response_decision_postgres_smoke.py",
    "scripts/smoke/run_s38_remediation_operations_automation_closure.py",
    "scripts/smoke/run_s39_repaired_response_handoff_closure.py",
    "tests/test_nex_ae_repaired_response_boundary.py",
    "tests/test_nex_ae_repaired_response_client.py",
    "tests/test_nex_ae_repaired_responses.py",
    "tests/test_ae_repaired_response_handoff_postgres_smoke.py",
    "tests/test_ae_repaired_response_decision_postgres_smoke.py",
    "tests/test_s39_repaired_response_handoff_closure.py",
    "docs/README.md",
    "docs/slices/0381_ae_repaired_response_runtime_boundary_audit.md",
    "docs/slices/0382_ae_to_cx_repaired_lineage_client_adapter.md",
    "docs/slices/0383_ae_repaired_handoff_persistence_foundation.md",
    "docs/slices/0384_ae_repaired_handoff_service_api_wiring.md",
    "docs/slices/0385_ae_repaired_handoff_postgresql_smoke_evidence.md",
    "docs/slices/0386_ae_repaired_handoff_user_review_projection.md",
    "docs/slices/0387_ae_repaired_handoff_user_decision_contract_persistence.md",
    "docs/slices/0388_ae_repaired_handoff_user_decision_service_api_wiring.md",
    "docs/slices/0389_ae_repaired_handoff_decision_postgresql_smoke_evidence.md",
    "docs/slices/0390_s39_repaired_response_handoff_closure.md",
)

TOKEN_CHECKS = (
    (
        "s39_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s39_repaired_response_handoff_closure.py",
    ),
    (
        "s38_closure_dependency_still_registered",
        "scripts/quality/run_quality_gate.sh",
        "run_s38_remediation_operations_automation_closure.py",
    ),
    (
        "handoff_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_repaired_response_handoff_postgres_smoke.py",
    ),
    (
        "decision_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_repaired_response_decision_postgres_smoke.py",
    ),
    (
        "ae_runtime_boundary_decision",
        "services/nex-ae-api/nex_ae_api/repaired_response_boundary.py",
        "ae_repaired_response_runtime_boundary_decision.v1",
    ),
    (
        "ae_cx_repaired_response_source_client",
        "services/nex-ae-api/nex_ae_api/repaired_response_client.py",
        "HttpCxRepairedResponseSourceClient",
    ),
    (
        "cx_repaired_lineage_source",
        "services/nex-cx/nex_cx/remediation_execution.py",
        "CX_REPAIRED_GENERATION_LINEAGE_SCHEMA_VERSION",
    ),
    (
        "handoff_schema_constant",
        "services/nex-ae-api/nex_ae_api/repaired_responses.py",
        "AE_REPAIRED_RESPONSE_HANDOFF_SCHEMA_VERSION",
    ),
    (
        "handoff_route_registration",
        "services/nex-ae-api/nex_ae_api/main.py",
        "register_repaired_response_handoff_routes(app)",
    ),
    (
        "review_projection_schema_constant",
        "services/nex-ae-api/nex_ae_api/repaired_response_review.py",
        "AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "decision_schema_constant",
        "services/nex-ae-api/nex_ae_api/repaired_response_decisions.py",
        "AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION",
    ),
    (
        "decision_route_registration",
        "services/nex-ae-api/nex_ae_api/main.py",
        "register_repaired_response_decision_routes(app)",
    ),
    (
        "handoff_openapi_create",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "createAeRepairedResponseHandoff",
    ),
    (
        "decision_openapi_create",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "createAeRepairedResponseDecision",
    ),
    (
        "decision_openapi_list",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "listAeRepairedResponseDecisions",
    ),
    (
        "decision_openapi_get",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "getAeRepairedResponseDecision",
    ),
    (
        "handoff_migration_record",
        "database/nex-ae-api/migrations/0383_ae_repaired_response_handoff_persistence.sql",
        "0383_ae_repaired_response_handoff_persistence",
    ),
    (
        "decision_migration_record",
        "database/nex-ae-api/migrations/0387_ae_repaired_response_decision_persistence.sql",
        "0387_ae_repaired_response_decision_persistence",
    ),
    (
        "handoff_live_smoke_evidence",
        "docs/slices/0385_ae_repaired_handoff_postgresql_smoke_evidence.md",
        "ae_repaired_response_handoff_postgres_smoke=pass",
    ),
    (
        "decision_live_smoke_evidence",
        "docs/slices/0389_ae_repaired_handoff_decision_postgresql_smoke_evidence.md",
        "ae_repaired_response_decision_postgres_smoke=pass",
    ),
    (
        "s39_slice_index",
        "docs/README.md",
        "Slice 0390",
    ),
)


def run_s39_repaired_response_handoff_closure(root: Path = ROOT) -> dict[str, Any]:
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
        "slice_range": "0381-0390",
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
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s39_repaired_response_handoff_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s39_repaired_response_handoff_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S39 repaired response handoff closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s39_repaired_response_handoff_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(any(docs_dir.glob(f"{slice_id:04d}_*.md")) for slice_id in range(381, 391))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
