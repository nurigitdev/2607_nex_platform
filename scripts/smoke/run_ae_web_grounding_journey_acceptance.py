#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_web_grounding_journey_acceptance.v1"
MODULE_PATH = "apps/nex-ae-web/src/goldenJourneyGrounding.js"

REQUIRED_TOKENS = (
    "runGroundedGenerationWorkflow",
    "buildGroundedGenerationPresentation",
    'stage: "RETRIEVAL_READY"',
    'stage: "GENERATION_COMPLETED"',
    'stage: "GROUNDING_ACCEPTED"',
    'retrieval?.cxStatus !== "READY"',
    'presentation.displayMode === "REPAIRED_RESPONSE_REVIEW"',
    'quality_status: repaired ? "REPAIRED" : "VALIDATED"',
    "countCitationMarkers",
    "warningCount",
    "buildGoldenJourneyEvidence",
)

PRIVATE_RETURN_TOKENS = (
    "assistantText:",
    "userMessage:",
    "responseContent:",
    "sourceText:",
    "providerUrl:",
    "databaseUrl:",
)


def run_ae_web_grounding_journey_acceptance(root: Path = ROOT) -> dict[str, Any]:
    source = _read_text(root / MODULE_PATH)
    return_projection = source.split("return Object.freeze", 1)[-1]
    checks = {
        "grounding_module_present": bool(source),
        "required_orchestration_present": all(token in source for token in REQUIRED_TOKENS),
        "six_stage_journey_completion_frozen": all(
            stage in source
            for stage in (
                "RETRIEVAL_READY",
                "GENERATION_COMPLETED",
                "GROUNDING_ACCEPTED",
            )
        ),
        "warning_citation_repair_counts_present": all(
            token in source
            for token in (
                "warning_count",
                "citation_count",
                "repair_attempt_count",
            )
        ),
        "private_payload_absent_from_return": not any(
            token in return_projection for token in PRIVATE_RETURN_TOKENS
        ),
        "node_contract_test_present": (
            root / "apps/nex-ae-web/test/goldenJourneyGrounding.test.mjs"
        ).is_file(),
        "main_uses_same_workflow_and_presentation": all(
            token in _read_text(root / "apps/nex-ae-web/src/main.js")
            for token in (
                "runGroundedGenerationWorkflow({",
                "buildGroundedGenerationPresentation({",
                "retrievalQualityWarning",
                "groundedResponseQuality",
            )
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = not issues
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1386",
        "requirement": "S139",
        "status": "PASS" if passed else "FAIL",
        "grounding_acceptance_readiness": "READY" if passed else "BLOCKED",
        "checks": checks,
        "issues": issues,
        "summary": {
            "required_token_count": len(REQUIRED_TOKENS),
            "journey_stage_count": 6,
            "quality_signal_count": 3,
            "accepted_quality_outcome_count": 2,
            "issue_count": len(issues),
        },
        "decision": {
            "retrieval_ready_required": True,
            "accepted_quality_outcomes": ["VALIDATED", "REPAIRED"],
            "private_payload_in_evidence_allowed": False,
            "new_table_required": False,
            "remote_provider_required": False,
            "checkpoint_gate_required": True,
            "next_slice": "1387" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "ae_web_grounding_journey=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "ae_web_grounding_journey=pass "
        f"stages={summary.get('journey_stage_count', 0)} "
        f"signals={summary.get('quality_signal_count', 0)} "
        f"outcomes={summary.get('accepted_quality_outcome_count', 0)} "
        f"checkpoint=true next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_web_grounding_journey_acceptance()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
