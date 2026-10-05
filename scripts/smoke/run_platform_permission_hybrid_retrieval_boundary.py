#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_permission_hybrid_retrieval_boundary.v1"
CANONICAL_DOCUMENT = "docs/43_platform_permission_filtered_hybrid_retrieval.md"
REQUIRED_PATHS = (
    "docs/37_platform_mvp_integration_release_plan.md",
    CANONICAL_DOCUMENT,
    "services/nex-cx/nex_cx/retrieval_permissions.py",
    "services/nex-cx/nex_cx/lexical_candidates.py",
    "services/nex-cx/nex_cx/vector_candidates.py",
    "services/nex-cx/nex_cx/hybrid_ranking.py",
    "services/nex-cx/nex_cx/hybrid_retrieval_package.py",
    "services/nex-cx/nex_cx/hybrid_retrieval_runtime.py",
    "services/nex-cx/nex_cx/mvp_runtime.py",
    "services/nex-cx/nex_cx/main.py",
)
REQUIRED_TOKENS = (
    ("outcome", CANONICAL_DOCUMENT, "## Required Outcome"),
    ("invariants", CANONICAL_DOCUMENT, "## Retrieval Invariants"),
    ("gaps", CANONICAL_DOCUMENT, "## Current Gaps"),
    ("sequence", CANONICAL_DOCUMENT, "## Slice Sequence"),
    ("completion", CANONICAL_DOCUMENT, "## Completion Signal"),
    ("handoff", CANONICAL_DOCUMENT, "## S137 Handoff"),
    ("plan", "docs/37_platform_mvp_integration_release_plan.md", "## S136 Slice Plan"),
    ("quality", "scripts/quality/run_quality_gate.sh", "run_platform_permission_hybrid_retrieval_boundary.py"),
    ("index", "docs/README.md", "1352_platform_permission_hybrid_retrieval_boundary.md"),
)


def run_platform_permission_hybrid_retrieval_boundary(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = [{"path": path, "present": (root / path).is_file()} for path in REQUIRED_PATHS]
    tokens = [
        {"group": group, "path": path, "present": token in _read_text(root / path)}
        for group, path, token in REQUIRED_TOKENS
    ]
    sources = {
        "permission": _read_text(root / "services/nex-cx/nex_cx/retrieval_permissions.py"),
        "lexical": _read_text(root / "services/nex-cx/nex_cx/lexical_candidates.py"),
        "ranking": _read_text(root / "services/nex-cx/nex_cx/hybrid_ranking.py"),
        "package": _read_text(root / "services/nex-cx/nex_cx/hybrid_retrieval_package.py"),
        "runtime": _read_text(root / "services/nex-cx/nex_cx/mvp_runtime.py"),
        "main": _read_text(root / "services/nex-cx/nex_cx/main.py"),
    }
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "owner_tenant_filter_exists": (
            "cx.private_owner_active.v1" in sources["permission"]
            and "require_all_visible=True" in _read_text(
                root / "services/nex-cx/nex_cx/hybrid_retrieval_runtime.py"
            )
        ),
        "postgres_bm25_exists": (
            "PostgresLexicalCandidateStore" in sources["lexical"]
            and "DEFAULT_BM25_K1 = 1.2" in sources["lexical"]
            and "DEFAULT_BM25_B = 0.75" in sources["lexical"]
        ),
        "weighted_rrf_exists": (
            "DEFAULT_VECTOR_WEIGHT = 0.7" in sources["ranking"]
            and "DEFAULT_BM25_WEIGHT = 0.3" in sources["ranking"]
            and "DEFAULT_RRF_K = 60" in sources["ranking"]
        ),
        "confidence_states_exist": all(
            token in sources["package"]
            for token in ('"READY"', '"LOW_CONFIDENCE"', '"NO_ANSWER"')
        ),
        "production_runtime_composed": (
            "build_permission_hardened_hybrid_runtime" in sources["runtime"]
            and "CX_MVP_RUNTIME.hybrid_retrieval_runtime" in sources["main"]
        ),
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "boundary_schema_version": SCHEMA_VERSION,
        "slice": "1352",
        "requirement": "S136",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": None if not issues else "platform_permission_hybrid_retrieval_boundary_failed",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "required_tokens": tokens,
        "findings": {
            "existing_component_count": 8,
            "current_gap_count": 6,
            "candidate_channel_count": 2,
            "decision_state_count": 3,
        },
        "decision": {
            "permission_precedes_candidates": True,
            "actual_test_database_required": True,
            "remote_embedding_provider_required": True,
            "remote_reranker_provider_required": True,
            "remote_generation_provider_required": False,
            "next_slice": "1353",
        },
        "slice_plan": [str(value) for value in range(1352, 1362)],
        "quality_cadence": {
            "slice_gate": "every_slice",
            "checkpoint_gate": "1356",
            "full_gate": "1361",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "platform_permission_hybrid_retrieval_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    findings = evidence.get("findings") or {}
    return (
        "platform_permission_hybrid_retrieval_boundary=pass "
        f"components={findings.get('existing_component_count', 0)} "
        f"channels={findings.get('candidate_channel_count', 0)} "
        f"gaps={findings.get('current_gap_count', 0)} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_permission_hybrid_retrieval_boundary()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
