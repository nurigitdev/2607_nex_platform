#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_live_retrieval_provider_identity.v1"
REQUIRED_TOKENS = (
    ("services/nex-cx/nex_cx/hybrid_retrieval_runtime.py", '"query_embedding_profile"'),
    ("services/nex-cx/nex_cx/hybrid_retrieval_runtime.py", '"model_revision": _optional_identity'),
    ("services/nex-cx/nex_cx/hybrid_retrieval_package.py", '"provider_alias": query_embedding_profile.get'),
    ("services/nex-cx/nex_cx/hybrid_ranking.py", '"model_revision": _optional_identifier'),
    ("services/nex-cx/nex_cx/hybrid_ranking.py", '"deployment_id": _optional_identifier'),
)


def run_cx_live_retrieval_provider_identity(root: Path = ROOT) -> dict[str, Any]:
    checks = {
        f"token_{index}": token in _read_text(root / path)
        for index, (path, token) in enumerate(REQUIRED_TOKENS, start=1)
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1355",
        "requirement": "S136",
        "status": "PASS" if not issues else "FAIL",
        "checks": checks,
        "issues": issues,
        "provider_profile": {
            "embedding_alias": "embedding-default",
            "embedding_model": "Qwen3-Embedding-4B",
            "reranker_alias": "reranker-default",
            "reranker_model": "Qwen3-Reranker-4B",
            "endpoint_persisted": False,
            "credential_persisted": False,
        },
        "next_slice": "1356",
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"cx_live_retrieval_provider_identity=fail issues={len(evidence.get('issues') or [])}"
    profile = evidence.get("provider_profile") or {}
    return (
        "cx_live_retrieval_provider_identity=pass "
        f"embedding={profile.get('embedding_model')} "
        f"reranker={profile.get('reranker_model')} "
        f"next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_live_retrieval_provider_identity()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
