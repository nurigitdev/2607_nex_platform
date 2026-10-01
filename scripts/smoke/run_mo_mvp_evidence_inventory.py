#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.mvp_acceptance import build_mo_mvp_evidence_inventory  # noqa: E402


SCHEMA_VERSION = "mo_mvp_evidence_inventory_evidence.v1"


def run_mo_mvp_evidence_inventory(root: Path = ROOT) -> dict[str, Any]:
    inventory = build_mo_mvp_evidence_inventory(root)
    entries = inventory["entries"]
    checks = {
        "inventory_passed": inventory["status"] == "PASS",
        "nine_requirements_included": len(entries) == 9,
        "all_entries_ready": all(entry["status"] == "READY" for entry in entries),
        "all_runners_unique": all(
            entry["closure_runner_count"] == 1 for entry in entries
        ),
        "all_documents_unique": all(
            entry["closure_document_count"] == 1 for entry in entries
        ),
        "all_identity_tokens_present": all(
            entry["identity_tokens_present"] for entry in entries
        ),
        "mtime_not_trusted": inventory["freshness_contract"][
            "repository_mtime_is_acceptance_evidence"
        ]
        is False,
        "server_clock_authoritative": inventory["freshness_contract"][
            "server_clock_is_authoritative"
        ]
        is True,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1194",
        "requirement": "S120",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_mvp_evidence_inventory_failed",
        "summary": {
            "requirement_count": len(entries),
            "ready_count": sum(entry["status"] == "READY" for entry in entries),
            "issue_count": len(inventory["issues"]),
            "identity_count": sum(
                entry["identity_tokens_present"] for entry in entries
            ),
            "failed_check_count": sum(not value for value in checks.values()),
        },
        "checks": checks,
        "inventory": inventory,
        "next_slice": "1195" if passed else "blocked",
    }


def summary_line(result: dict[str, Any]) -> str:
    summary = result.get("summary", {})
    return (
        "mo_mvp_evidence_inventory="
        f"{'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"requirements={summary.get('ready_count', 0)}/"
        f"{summary.get('requirement_count', 0)} "
        f"identities={summary.get('identity_count', 0)} "
        f"issues={summary.get('issue_count', 0)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_mo_mvp_evidence_inventory()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
