#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s40_ae_web_repaired_response_review_closure.v1"

REQUIRED_FILES = (
    "apps/nex-ae-web/src/clientRegistry.js",
    "apps/nex-ae-web/src/main.js",
    "apps/nex-ae-web/src/repairedResponseReviewBoundary.js",
    "apps/nex-ae-web/src/repairedResponseReviewClient.js",
    "apps/nex-ae-web/src/repairedResponseReviewCard.js",
    "apps/nex-ae-web/src/repairedResponseDecisionClient.js",
    "apps/nex-ae-web/src/repairedResponseDecisionState.js",
    "apps/nex-ae-web/src/repairedResponseReviewReadModel.js",
    "apps/nex-ae-web/src/runtimeDiagnostics.js",
    "apps/nex-ae-web/test/repairedResponseReviewBoundary.test.mjs",
    "apps/nex-ae-web/test/repairedResponseReviewClient.test.mjs",
    "apps/nex-ae-web/test/repairedResponseReviewCard.test.mjs",
    "apps/nex-ae-web/test/repairedResponseDecisionClient.test.mjs",
    "apps/nex-ae-web/test/repairedResponseDecisionState.test.mjs",
    "apps/nex-ae-web/test/repairedResponseReviewReadModel.test.mjs",
    "apps/nex-ae-web/test/runtimeDiagnostics.test.mjs",
    "contracts/openapi/nex-ae-api.openapi.yaml",
    "contracts/schemas/service/nex_ae_api/repaired_response_review_projection.v1.schema.json",
    "contracts/schemas/service/nex_ae_api/repaired_response_decision.v1.schema.json",
    "services/nex-ae-api/nex_ae_api/repaired_response_review.py",
    "services/nex-ae-api/nex_ae_api/repaired_response_decisions.py",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_web_repaired_response_decision_postgres_smoke.py",
    "scripts/smoke/run_ae_web_repaired_response_review_diagnostics_postgres_smoke.py",
    "scripts/smoke/run_s39_repaired_response_handoff_closure.py",
    "scripts/smoke/run_s40_ae_web_repaired_response_review_closure.py",
    "tests/test_ae_web_repaired_response_decision_postgres_smoke.py",
    "tests/test_ae_web_repaired_response_review_diagnostics_postgres_smoke.py",
    "tests/test_nex_ae_web_static.py",
    "tests/test_s40_ae_web_repaired_response_review_closure.py",
    "docs/README.md",
    "apps/nex-ae-web/README.md",
    "docs/slices/0391_ae_web_repaired_response_review_surface_boundary.md",
    "docs/slices/0392_ae_web_repaired_response_handoff_client_adapter.md",
    "docs/slices/0393_ae_web_repaired_response_review_card_rendering.md",
    "docs/slices/0394_ae_web_repaired_response_decision_submit_adapter.md",
    "docs/slices/0395_ae_web_repaired_response_decision_ux_wiring.md",
    "docs/slices/0396_ae_web_repaired_response_decision_postgresql_smoke_evidence.md",
    "docs/slices/0397_ae_web_repaired_response_review_read_model.md",
    "docs/slices/0398_ae_web_repaired_response_read_model_runtime_diagnostics.md",
    "docs/slices/0399_ae_web_repaired_response_review_diagnostics_postgresql_smoke.md",
    "docs/slices/0400_s40_ae_web_repaired_response_review_closure.md",
)

TOKEN_CHECKS = (
    (
        "s40_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s40_ae_web_repaired_response_review_closure.py",
    ),
    (
        "s39_closure_dependency_still_registered",
        "scripts/quality/run_quality_gate.sh",
        "run_s39_repaired_response_handoff_closure.py",
    ),
    (
        "web_decision_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_web_repaired_response_decision_postgres_smoke.py",
    ),
    (
        "web_review_diagnostics_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_web_repaired_response_review_diagnostics_postgres_smoke.py",
    ),
    (
        "review_boundary_schema",
        "apps/nex-ae-web/src/repairedResponseReviewBoundary.js",
        "ae_web_repaired_response_review_boundary.v1",
    ),
    (
        "review_client_surface_schema",
        "apps/nex-ae-web/src/repairedResponseReviewClient.js",
        "ae_web_repaired_response_review_surface.v1",
    ),
    (
        "review_client_fetch_adapter",
        "apps/nex-ae-web/src/repairedResponseReviewClient.js",
        "createFetchRepairedResponseReviewClient",
    ),
    (
        "review_card_renderer",
        "apps/nex-ae-web/src/repairedResponseReviewCard.js",
        "renderRepairedResponseReviewCard",
    ),
    (
        "review_card_decision_actions",
        "apps/nex-ae-web/src/repairedResponseReviewCard.js",
        "data-repaired-response-decision-action",
    ),
    (
        "decision_client_schema",
        "apps/nex-ae-web/src/repairedResponseDecisionClient.js",
        "ae_web_repaired_response_decision_client.v1",
    ),
    (
        "decision_client_fetch_adapter",
        "apps/nex-ae-web/src/repairedResponseDecisionClient.js",
        "createFetchRepairedResponseDecisionClient",
    ),
    (
        "decision_state_machine",
        "apps/nex-ae-web/src/repairedResponseDecisionState.js",
        "markRepairedResponseDecisionRecorded",
    ),
    (
        "main_decision_click_wiring",
        "apps/nex-ae-web/src/main.js",
        "submitRepairedResponseDecision(",
    ),
    (
        "main_review_read_model_wiring",
        "apps/nex-ae-web/src/main.js",
        "buildWorkspaceRepairedResponseReviewReadModel",
    ),
    (
        "runtime_diagnostics_review_counts",
        "apps/nex-ae-web/src/runtimeDiagnostics.js",
        "repaired_response_review_count",
    ),
    (
        "review_read_model_schema",
        "apps/nex-ae-web/src/repairedResponseReviewReadModel.js",
        "ae_web_repaired_response_review_read_model.v1",
    ),
    (
        "review_read_model_summary",
        "apps/nex-ae-web/src/repairedResponseReviewReadModel.js",
        "buildRepairedResponseReviewReadModelSummary",
    ),
    (
        "client_registry_review_client",
        "apps/nex-ae-web/src/clientRegistry.js",
        "repairedResponseReviewClient",
    ),
    (
        "client_registry_decision_client",
        "apps/nex-ae-web/src/clientRegistry.js",
        "repairedResponseDecisionClient",
    ),
    (
        "ae_api_review_projection_schema",
        "services/nex-ae-api/nex_ae_api/repaired_response_review.py",
        "AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ae_api_decision_schema",
        "services/nex-ae-api/nex_ae_api/repaired_response_decisions.py",
        "AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION",
    ),
    (
        "ae_openapi_review_list",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "listAeRepairedResponseHandoffReviews",
    ),
    (
        "ae_openapi_decision_create",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "createAeRepairedResponseDecision",
    ),
    (
        "web_decision_smoke_live_evidence",
        "docs/slices/0396_ae_web_repaired_response_decision_postgresql_smoke_evidence.md",
        "ae_web_repaired_response_decision_postgres_smoke=pass",
    ),
    (
        "web_review_diagnostics_smoke_live_evidence",
        "docs/slices/0399_ae_web_repaired_response_review_diagnostics_postgresql_smoke.md",
        "ae_web_repaired_response_review_diagnostics_postgres_smoke=pass",
    ),
    (
        "s40_slice_index",
        "docs/README.md",
        "Slice 0400",
    ),
    (
        "s40_web_readme_note",
        "apps/nex-ae-web/README.md",
        "Slice 0399 adds protected PostgreSQL smoke evidence",
    ),
)


def run_s40_ae_web_repaired_response_review_closure(
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
        "slice_range": "0391-0400",
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
            "s40_ae_web_repaired_response_review_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s40_ae_web_repaired_response_review_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S40 AE Web repaired response review closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s40_ae_web_repaired_response_review_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        any(docs_dir.glob(f"{slice_id:04d}_*.md"))
        for slice_id in range(391, 401)
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
