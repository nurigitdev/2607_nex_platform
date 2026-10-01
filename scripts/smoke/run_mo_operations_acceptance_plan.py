#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.operations_acceptance import build_operations_acceptance_plan  # noqa: E402


def acceptance_environment() -> dict[str, str]:
    return {
        "NEX_MO_OPERATIONS_LIVE_ACCEPTANCE": "1",
        "NEX_MO_OPERATIONS_LIVE_ACCEPTANCE_PROFILE": "test",
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_mo_user:private@127.0.0.1:5432/nex_mo_test"
        ),
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.example:9112/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "private-key",
        "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "openai_embeddings",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.example:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "private-key",
        "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE": "rerank",
        "NEX_MO_VLLM_BASE_URL": "http://dgx.example:9111",
        "NEX_MO_VLLM_API_KEY": "private-key",
        "NEX_MO_RUNTIME_OBSERVABILITY_MODE": "live",
        "NEX_MO_DGX_SSH_TARGET": "operator@dgx.example",
    }


def run_mo_operations_acceptance_plan() -> dict[str, Any]:
    env = acceptance_environment()
    plan = build_operations_acceptance_plan(env).to_wire()
    serialized = json.dumps(plan, sort_keys=True)
    protected_values = [
        env["NEX_MO_TEST_DATABASE_URL"],
        env["NEX_MO_REMOTE_EMBEDDING_URL"],
        env["NEX_MO_REMOTE_RERANKER_URL"],
        env["NEX_MO_VLLM_BASE_URL"],
        env["NEX_MO_REMOTE_EMBEDDING_API_KEY"],
        env["NEX_MO_DGX_SSH_TARGET"],
    ]
    leaked = [value for value in protected_values if value in serialized]
    passed = (
        plan["admission_status"] == "READY"
        and len(plan["targets"]) == 3
        and not plan["issues"]
        and not leaked
    )
    return {
        "evidence_schema_version": "mo_operations_acceptance_plan_evidence.v1",
        "slice": "1186",
        "requirement": "S119",
        "status": "PASS" if passed else "FAIL",
        "plan": plan,
        "summary": {
            "target_count": len(plan["targets"]),
            "issue_count": len(plan["issues"]),
            "private_value_count": len(leaked),
            "database_allowed": plan["database"] == {
                "configured": True,
                "name": "nex_mo_test",
                "role": "nex_mo_user",
            },
        },
        "next_slice": "1187" if passed else None,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_operations_acceptance_plan="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"targets={summary.get('target_count', 0)} "
        f"issues={summary.get('issue_count', 0)} "
        f"private={summary.get('private_value_count', 0)} "
        f"database={str(bool(summary.get('database_allowed'))).lower()} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_operations_acceptance_plan()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
