#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo import provider_normalization, remote_provider  # noqa: E402


def run_mo_provider_normalization_extraction(root: Path = ROOT) -> dict[str, Any]:
    module_path = root / "services/nex-mo/nex_mo/provider_normalization.py"
    remote_path = root / "services/nex-mo/nex_mo/remote_provider.py"
    module_source = module_path.read_text(encoding="utf-8") if module_path.is_file() else ""
    remote_source = remote_path.read_text(encoding="utf-8") if remote_path.is_file() else ""
    config = SimpleNamespace(model_revision="revision", deployment_id="deployment")
    embedding = provider_normalization.normalize_remote_embedding_response(
        provider_payload={"embeddings": [[1, 2]]},
        alias="embedding-default",
        config=config,
        input_count=1,
        input_texts=["text"],
    )
    rerank = provider_normalization.normalize_remote_rerank_response(
        provider_payload={"results": [{"index": 0, "relevance_score": 0.75}]},
        alias="reranker-default",
        config=config,
        documents=["document"],
        query="query",
    )
    checks = {
        "normalization_module_present": bool(module_source),
        "remote_compatibility_import_present": "from nex_mo.provider_normalization import ("
        in remote_source,
        "generation_compatibility_preserved": remote_provider.normalize_remote_generation_response
        is provider_normalization.normalize_remote_generation_response,
        "embedding_shape_preserved": embedding["data"][0]["embedding"] == [1.0, 2.0],
        "rerank_shape_preserved": rerank["results"][0]["score"] == 0.75,
        "normalization_owns_no_transport": "httpx" not in module_source,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_normalization_extraction.v1",
        "slice": "1115",
        "requirement": "S112",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_normalization_extraction_failed",
        "checks": checks,
        "summary": {
            "normalizer_count": 3,
            "compatibility_export_count": 3,
            "failed_check_count": sum(not value for value in checks.values()),
        },
        "issues": [name for name, value in checks.items() if not value],
        "next_slice": "1116",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_normalization_extraction="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"normalizers={summary.get('normalizer_count', 0)} "
        f"compatibility={summary.get('compatibility_export_count', 0)} "
        f"failed={summary.get('failed_check_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_normalization_extraction()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
