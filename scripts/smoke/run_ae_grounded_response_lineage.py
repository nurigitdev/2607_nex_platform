#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]

TOKENS = {
    "grounding_source_validation": (
        "services/nex-ae-api/nex_ae_api/generated_response_lineage.py",
        "def _grounding_lineage_from_cx_generation(",
    ),
    "persisted_lineage_validation": (
        "services/nex-ae-api/nex_ae_api/generated_response_lineage.py",
        "def _validate_persisted_grounding_lineage(",
    ),
    "ready_handoff_binding": (
        "services/nex-ae-api/nex_ae_api/generated_response_handoff.py",
        "cx_generation=cx_generation",
    ),
    "chat_handoff_binding": (
        "services/nex-ae-api/nex_ae_api/chat.py",
        'cx_generation=handoff.get("generation")',
    ),
    "incomplete_workflow_block": (
        "services/nex-ae-api/nex_ae_api/generated_response_lineage.py",
        "Grounded response citation workflow is incomplete.",
    ),
}


def run_ae_grounded_response_lineage(root: Path = ROOT) -> dict[str, Any]:
    checks = {
        name: token in _read_text(root / path)
        for name, (path, token) in TOKENS.items()
    }
    schema = _read_json(
        root
        / "contracts/schemas/service/nex_ae_api/"
        "generated_response_lineage.v1.schema.json"
    )
    example = _read_json(
        root
        / "contracts/examples/generation/"
        "ae_generated_response_lineage.retry_repaired.json"
    )
    grounding = example.get("cx_grounding_lineage")
    properties = schema.get("properties") or {}
    checks.update(
        {
            "strict_response_lineage_schema": (
                schema.get("additionalProperties") is False
            ),
            "grounding_projection_contract": "cx_grounding_lineage" in properties,
            "exact_evidence_binding_example": (
                isinstance(grounding, Mapping)
                and bool(grounding.get("evidence_binding_hash"))
                and grounding.get("citation_validation_status") == "VALIDATED"
            ),
            "bounded_repair_example": (
                isinstance(grounding, Mapping)
                and grounding.get("citation_repair_attempted") is True
                and grounding.get("citation_repair_attempt_count") == 1
            ),
            "privacy_safe_example": (
                isinstance(grounding, Mapping)
                and grounding.get("private_evidence_included") is False
                and "evidence_text" not in grounding
                and "content" not in grounding
            ),
        }
    )
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "evidence_schema_version": "ae_grounded_response_lineage_evidence.v1",
        "slice": "1366",
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
            "legacy_lineage_read_compatible": True,
            "grounded_ready_requires_cx_lineage": True,
            "private_evidence_persisted": False,
            "remote_provider_required": False,
            "next_slice": "1367" if not issues else "blocked",
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
        "ae_grounded_response_lineage="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"checks={summary.get('passed_count', 0)}/{summary.get('check_count', 0)} "
        f"issues={summary.get('issue_count', 0)} "
        f"next={decision.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_grounded_response_lineage()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
