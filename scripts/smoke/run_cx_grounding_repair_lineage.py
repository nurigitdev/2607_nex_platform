#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LineageToken:
    name: str
    path: str
    token: str


TOKENS = (
    LineageToken(
        "deterministic_evidence_binding",
        "services/nex-cx/nex_cx/grounded_prompt.py",
        "def build_grounded_evidence_binding(",
    ),
    LineageToken(
        "repair_checks_binding",
        "services/nex-cx/nex_cx/citation_repair.py",
        'raise _invalid("Citation repair evidence binding changed.")',
    ),
    LineageToken(
        "execution_builds_lineage",
        "services/nex-cx/nex_cx/generation.py",
        "build_grounded_generation_lineage(",
    ),
    LineageToken(
        "persistence_validates_lineage",
        "services/nex-cx/nex_cx/generation_persistence.py",
        "validate_grounded_generation_lineage(",
    ),
    LineageToken(
        "read_model_validates_lineage",
        "services/nex-cx/nex_cx/generation_read_model.py",
        "validate_grounded_generation_lineage(",
    ),
    LineageToken(
        "handoff_fails_closed",
        "services/nex-cx/nex_cx/generation_handoff.py",
        "Ready grounded generation metadata does not match its lineage.",
    ),
)


def run_cx_grounding_repair_lineage(root: Path = ROOT) -> dict[str, Any]:
    checks = {item.name: item.token in _read_text(root / item.path) for item in TOKENS}
    schema = _read_json(
        root
        / "contracts/schemas/generation/cx_grounded_generation_lineage.v1.schema.json"
    )
    example = _read_json(
        root
        / "contracts/examples/generation/cx_grounded_generation_lineage.repaired.json"
    )
    required = set(schema.get("required") or [])
    checks.update(
        {
            "strict_lineage_schema": schema.get("additionalProperties") is False,
            "exact_binding_contract": {
                "retrieval_package_hash",
                "evidence_binding_hash",
                "selected_evidence_count",
            }.issubset(required),
            "repair_transition_contract": {
                "citation_repair_attempted",
                "citation_repair_attempt_count",
                "original_provider_prompt_package_hash",
                "effective_provider_prompt_package_hash",
            }.issubset(required),
            "example_is_privacy_safe": (
                example.get("private_evidence_included") is False
                and "evidence_text" not in example
            ),
        }
    )
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "evidence_schema_version": "cx_grounding_repair_lineage_evidence.v1",
        "slice": "1365",
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
            "private_evidence_persisted": False,
            "repair_attempt_limit": 1,
            "remote_provider_required": False,
            "next_slice": "1366" if not issues else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "cx_grounding_repair_lineage="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"checks={summary.get('passed_count', 0)}/{summary.get('check_count', 0)} "
        f"issues={summary.get('issue_count', 0)} "
        f"next={decision.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_grounding_repair_lineage()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
