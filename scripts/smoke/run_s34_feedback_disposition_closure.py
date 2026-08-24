#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s34_feedback_disposition_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/generation_feedback.py",
    "services/nex-ag/nex_ag/generation_quality_disposition.py",
    "services/nex-ag/nex_ag/generation_quality_feedback_rollup.py",
    "apps/nex-ae-web/src/generationFeedback.js",
    "apps/nex-ae-web/src/main.js",
    "scripts/smoke/run_ae_generation_feedback_postgres_smoke.py",
    "scripts/smoke/run_ag_generation_quality_disposition_postgres_smoke.py",
    "scripts/quality/run_quality_gate.sh",
    "contracts/schemas/service/nex_ae_api/generation_feedback.v1.schema.json",
    "contracts/schemas/generation/ag_generation_quality_operator_disposition.v1.schema.json",
    "contracts/schemas/generation/ag_generation_quality_feedback_rollup.v1.schema.json",
    "docs/slices/0331_ae_generation_feedback_disposition_boundary_audit.md",
    "docs/slices/0332_ae_generation_feedback_contract_foundation.md",
    "docs/slices/0333_ae_generation_feedback_intake_api_regression.md",
    "docs/slices/0334_ae_generation_feedback_postgresql_smoke_evidence.md",
    "docs/slices/0335_ag_generation_quality_operator_disposition_foundation.md",
    "docs/slices/0336_ag_generation_quality_disposition_api_wiring.md",
    "docs/slices/0337_ag_generation_quality_disposition_postgresql_smoke_evidence.md",
    "docs/slices/0338_ag_generation_quality_feedback_rollup_projection.md",
    "docs/slices/0339_ae_web_generation_feedback_surface.md",
    "docs/slices/0340_s34_feedback_disposition_closure_checkpoint.md",
)

TOKEN_CHECKS = (
    (
        "ae_feedback_sql_store",
        "services/nex-ae-api/nex_ae_api/generation_feedback.py",
        "SqlAlchemyGenerationFeedbackStore",
    ),
    (
        "ag_disposition_sql_store",
        "services/nex-ag/nex_ag/generation_quality_disposition.py",
        "SqlAlchemyGenerationQualityDispositionStore",
    ),
    (
        "ag_disposition_routes",
        "services/nex-ag/nex_ag/generation_quality_disposition.py",
        "/admin/v1/generation-audit/generations/{cx_generation_id}/quality-dispositions",
    ),
    (
        "ag_feedback_rollup_contract",
        "services/nex-ag/nex_ag/generation_quality_feedback_rollup.py",
        "ag_generation_quality_feedback_rollup.v1",
    ),
    (
        "ae_web_feedback_surface",
        "apps/nex-ae-web/src/main.js",
        "data-generation-feedback-value",
    ),
    (
        "ae_web_feedback_client",
        "apps/nex-ae-web/src/generationFeedback.js",
        "createFetchGenerationFeedbackClient",
    ),
    (
        "ag_disposition_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_generation_quality_disposition_postgres_smoke.py",
    ),
)


def run_s34_feedback_disposition_closure(root: Path = ROOT) -> dict[str, Any]:
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
        "slice_range": "0331-0340",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "redaction_summary": {
            "database_url_included": False,
            "service_token_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s34_feedback_disposition_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s34_feedback_disposition_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S34 feedback/disposition closure checks."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s34_feedback_disposition_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(any(docs_dir.glob(f"{slice_id:04d}_*.md")) for slice_id in range(331, 341))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
