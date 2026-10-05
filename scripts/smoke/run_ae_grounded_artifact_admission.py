#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]

TOKENS = {
    "grounded_admission_composition": (
        "services/nex-ae-api/nex_ae_api/async_artifact_rendering.py",
        "def admit_grounded_response_artifact(",
    ),
    "grounding_lineage_guard": (
        "services/nex-ae-api/nex_ae_api/async_artifact_rendering.py",
        "def _validate_grounded_response_artifact_binding(",
    ),
    "owner_scoped_route": (
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/generated-responses/{response_id}/artifacts"',
    ),
    "handoff_owner_guard": (
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "def _artifact_handoff_visible_to_owner(",
    ),
    "content_free_request": (
        "services/nex-ae-api/nex_ae_api/async_artifact_rendering.py",
        '"content_included": False',
    ),
    "durable_queue_admission": (
        "services/nex-ae-api/nex_ae_api/async_artifact_rendering.py",
        "admission = admit_async_artifact_render(",
    ),
}


def run_ae_grounded_artifact_admission(root: Path = ROOT) -> dict[str, Any]:
    checks = {
        name: token in (root / path).read_text(encoding="utf-8")
        for name, (path, token) in TOKENS.items()
    }
    tests = (root / "tests/test_ae_async_artifact_response_lineage.py").read_text(
        encoding="utf-8"
    )
    checks.update(
        {
            "lineage_drift_regression": (
                "test_grounded_response_binding_rejects_missing_or_drifted" in tests
            ),
            "idempotent_route_regression": (
                "test_grounded_response_artifact_route_is_owner_scoped_and_idempotent"
                in tests
            ),
        }
    )
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "evidence_schema_version": "ae_grounded_artifact_admission_evidence.v1",
        "slice": "1367",
        "requirement": "S137",
        "status": "PASS" if not issues else "FAIL",
        "checks": checks,
        "summary": {
            "passed": len(checks) - len(issues),
            "total": len(checks),
            "issues": len(issues),
            "next_slice": "1368" if not issues else "blocked",
        },
        "issues": issues,
    }


def summary_line(result: dict[str, Any]) -> str:
    summary = result["summary"]
    return (
        "ae_grounded_artifact_admission="
        f"{result['status'].lower()} "
        f"checks={summary['passed']}/{summary['total']} "
        f"issues={summary['issues']} next={summary['next_slice']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_grounded_artifact_admission()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
