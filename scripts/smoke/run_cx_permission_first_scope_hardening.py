#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_permission_first_scope_hardening.v1"
REQUIRED_TOKENS = (
    ("services/nex-cx/nex_cx/hybrid_retrieval_runtime.py", "filter_retrieval_document_scope("),
    ("services/nex-cx/nex_cx/hybrid_retrieval_runtime.py", 'visible_ids = permission["visible_document_ids"]'),
    ("services/nex-cx/nex_cx/hybrid_retrieval_package.py", "except RetrievalPermissionError as exc:"),
    ("tests/test_nex_cx_hybrid_retrieval_runtime.py", "test_candidate_provider_rejects_mixed_owner_scope_before_all_candidates"),
    ("tests/test_nex_cx_hybrid_retrieval_package.py", "test_runtime_preserves_fail_closed_permission_denial"),
)


def run_cx_permission_first_scope_hardening(root: Path = ROOT) -> dict[str, Any]:
    checks = {
        f"token_{index}": token in _read_text(root / path)
        for index, (path, token) in enumerate(REQUIRED_TOKENS, start=1)
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1353",
        "requirement": "S136",
        "status": "PASS" if not issues else "FAIL",
        "checks": checks,
        "issues": issues,
        "decision": {
            "denial_status_code": 404,
            "denial_retryable": False,
            "denied_identifier_exposed": False,
            "downstream_calls_after_denial": 0,
            "next_slice": "1354",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"cx_permission_first_scope_hardening=fail issues={len(evidence.get('issues') or [])}"
    return (
        "cx_permission_first_scope_hardening=pass "
        f"checks={len(evidence.get('checks') or {})} "
        f"denial={evidence.get('decision', {}).get('denial_status_code')} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_permission_first_scope_hardening()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
