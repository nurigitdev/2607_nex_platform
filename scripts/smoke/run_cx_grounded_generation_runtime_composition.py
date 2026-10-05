#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CompositionToken:
    name: str
    path: str
    token: str


TOKENS = (
    CompositionToken(
        "mvp_owns_durable_store",
        "services/nex-cx/nex_cx/mvp_runtime.py",
        "retrieval_package_store=RestartSafeRetrievalPackageStore(",
    ),
    CompositionToken(
        "main_selects_store",
        "services/nex-cx/nex_cx/main.py",
        "CX_GENERATION_RETRIEVAL_STORE = select_cx_generation_retrieval_store(",
    ),
    CompositionToken(
        "sync_route_uses_selected_store",
        "services/nex-cx/nex_cx/main.py",
        "retrieval_store=CX_GENERATION_RETRIEVAL_STORE",
    ),
    CompositionToken(
        "async_route_registered",
        "services/nex-cx/nex_cx/main.py",
        "register_async_generation_operations_routes(",
    ),
    CompositionToken(
        "request_context_propagated",
        "services/nex-cx/nex_cx/generation.py",
        "access_context=access_context,",
    ),
    CompositionToken(
        "materialization_failure_mapped",
        "services/nex-cx/nex_cx/generation.py",
        "except RetrievalPackageMaterializationError as exc:",
    ),
    CompositionToken(
        "retrieval_route_context_propagated",
        "services/nex-cx/nex_cx/retrieval.py",
        "access_context=access_context,",
    ),
    CompositionToken(
        "local_fallback_preserved",
        "services/nex-cx/nex_cx/main.py",
        "return fallback",
    ),
)


def run_cx_grounded_generation_runtime_composition(
    root: Path = ROOT,
) -> dict[str, Any]:
    checks = {
        item.name: item.token in _read_text(root / item.path)
        for item in TOKENS
    }
    main_text = _read_text(root / "services/nex-cx/nex_cx/main.py")
    checks["sync_and_async_share_one_store"] = (
        main_text.count("retrieval_store=CX_GENERATION_RETRIEVAL_STORE") == 2
    )
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "evidence_schema_version": "cx_grounded_generation_composition.v1",
        "slice": "1364",
        "requirement": "S137",
        "status": "PASS" if not issues else "FAIL",
        "checks": checks,
        "issues": issues,
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(checks.values()),
            "issue_count": len(issues),
        },
        "decision": {
            "postgres_store": "restart_safe_owner_scoped",
            "local_store": "in_memory_compatibility",
            "sync_async_store_identity": "shared",
            "remote_provider_required": False,
            "next_slice": "1365" if not issues else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "cx_grounded_generation_composition="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"checks={summary.get('passed_count', 0)}/{summary.get('check_count', 0)} "
        f"issues={summary.get('issue_count', 0)} "
        f"next={decision.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_grounded_generation_runtime_composition()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
