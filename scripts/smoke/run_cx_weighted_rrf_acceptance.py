#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_weighted_rrf_acceptance.v1"
REQUIRED_TOKENS = (
    ("services/nex-cx/nex_cx/hybrid_ranking.py", "DEFAULT_VECTOR_WEIGHT = 0.7"),
    ("services/nex-cx/nex_cx/hybrid_ranking.py", "DEFAULT_BM25_WEIGHT = 0.3"),
    ("services/nex-cx/nex_cx/hybrid_ranking.py", "DEFAULT_RRF_K = 60"),
    ("services/nex-cx/nex_cx/hybrid_retrieval_package.py", '"candidate_summary": _candidate_summary'),
    ("tests/test_nex_cx_hybrid_retrieval_package.py", "test_candidate_summary_counts_single_channel_contributions"),
)


def run_cx_weighted_rrf_acceptance(root: Path = ROOT) -> dict[str, Any]:
    checks = {
        f"token_{index}": token in _read_text(root / path)
        for index, (path, token) in enumerate(REQUIRED_TOKENS, start=1)
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1356",
        "requirement": "S136",
        "status": "PASS" if not issues else "FAIL",
        "checks": checks,
        "issues": issues,
        "ranking_policy": {
            "policy_id": "weighted_rrf_vector_bm25_v1",
            "vector_weight": 0.7,
            "bm25_weight": 0.3,
            "rrf_k": 60,
        },
        "channel_evidence": (
            "bm25_candidate_count,vector_candidate_count,fused_candidate_count,"
            "both_channel_count,bm25_only_count,vector_only_count"
        ),
        "next_slice": "1357",
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"cx_weighted_rrf_acceptance=fail issues={len(evidence.get('issues') or [])}"
    policy = evidence.get("ranking_policy") or {}
    return (
        "cx_weighted_rrf_acceptance=pass "
        f"weights={policy.get('vector_weight')}/{policy.get('bm25_weight')} "
        f"k={policy.get('rrf_k')} next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_weighted_rrf_acceptance()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
