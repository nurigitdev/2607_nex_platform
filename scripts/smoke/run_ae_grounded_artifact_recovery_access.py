#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]

TOKENS = {
    "owner_file_resolution": (
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "def _visible_artifact_file(",
    ),
    "browser_storage_ref_redaction": (
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        'view.pop("storage_ref", None)',
    ),
    "persistent_file_owner_lookup": (
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "def get_artifact_for_file(",
    ),
    "restart_recovery_projection": (
        "services/nex-ae-api/nex_ae_api/async_artifact_render_recovery.py",
        "def inspect_async_artifact_render_recovery(",
    ),
    "idempotent_reconciliation": (
        "services/nex-ae-api/nex_ae_api/async_artifact_render_recovery.py",
        "def reconcile_async_artifact_render(",
    ),
}


def run_ae_grounded_artifact_recovery_access(root: Path = ROOT) -> dict[str, Any]:
    checks = {
        name: token in (root / path).read_text(encoding="utf-8")
        for name, (path, token) in TOKENS.items()
    }
    tests = (root / "tests/test_ae_grounded_artifact_recovery_access.py").read_text(
        encoding="utf-8"
    )
    checks.update(
        {
            "fresh_runtime_regression": (
                "test_fresh_runtime_restores_owner_preview_download" in tests
            ),
            "cross_owner_regression": (
                "test_artifact_file_and_recovery_routes_hide_cross_owner_state"
                in tests
            ),
            "orphan_file_regression": (
                "test_orphaned_file_metadata_is_not_publicly_resolvable" in tests
            ),
        }
    )
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "evidence_schema_version": (
            "ae_grounded_artifact_recovery_access_evidence.v1"
        ),
        "slice": "1368",
        "requirement": "S137",
        "status": "PASS" if not issues else "FAIL",
        "checks": checks,
        "summary": {
            "passed": len(checks) - len(issues),
            "total": len(checks),
            "issues": len(issues),
            "next_slice": "1369" if not issues else "blocked",
        },
        "issues": issues,
    }


def summary_line(result: dict[str, Any]) -> str:
    summary = result["summary"]
    return (
        "ae_grounded_artifact_recovery_access="
        f"{result['status'].lower()} "
        f"checks={summary['passed']}/{summary['total']} "
        f"issues={summary['issues']} next={summary['next_slice']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_grounded_artifact_recovery_access()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
