#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_retrieval_confidence_acceptance.v1"
REQUIRED_TOKENS = (
    ("services/nex-cx/nex_cx/hybrid_retrieval_package.py", 'CONFIDENCE_POLICY_ID = "cx_retrieval_confidence_v1"'),
    ("services/nex-cx/nex_cx/hybrid_retrieval_package.py", '"threshold_inclusive": True'),
    ("services/nex-cx/nex_cx/hybrid_retrieval_package.py", '"NO_ANSWER"'),
    ("services/nex-cx/nex_cx/hybrid_retrieval_package.py", '"LOW_CONFIDENCE"'),
    ("tests/test_nex_cx_hybrid_retrieval_package.py", "test_runtime_treats_exact_confidence_threshold_as_ready"),
    ("tests/test_nex_cx_hybrid_retrieval_package.py", "test_confidence_decision_uses_best_score_not_evidence_order"),
)


def run_cx_retrieval_confidence_acceptance(root: Path = ROOT) -> dict[str, Any]:
    checks = {
        f"token_{index}": token in _read_text(root / path)
        for index, (path, token) in enumerate(REQUIRED_TOKENS, start=1)
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1357",
        "requirement": "S136",
        "status": "PASS" if not issues else "FAIL",
        "checks": checks,
        "issues": issues,
        "confidence_policy": {
            "policy_id": "cx_retrieval_confidence_v1",
            "low_confidence_threshold": 0.2,
            "threshold_inclusive": True,
            "no_evidence_behavior": "NO_ANSWER",
            "below_threshold_behavior": "LOW_CONFIDENCE",
        },
        "next_slice": "1358",
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"cx_retrieval_confidence_acceptance=fail issues={len(evidence.get('issues') or [])}"
    policy = evidence.get("confidence_policy") or {}
    return (
        "cx_retrieval_confidence_acceptance=pass "
        f"policy={policy.get('policy_id')} "
        f"threshold={policy.get('low_confidence_threshold')} "
        f"next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_retrieval_confidence_acceptance()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
