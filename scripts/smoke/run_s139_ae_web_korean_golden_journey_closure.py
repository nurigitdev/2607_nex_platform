#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from run_ae_web_artifact_journey_acceptance import (
    run_ae_web_artifact_journey_acceptance,
)
from run_ae_web_golden_journey_state import run_ae_web_golden_journey_state
from run_ae_web_grounding_journey_acceptance import (
    run_ae_web_grounding_journey_acceptance,
)
from run_ae_web_korean_golden_journey_boundary import (
    run_ae_web_korean_golden_journey_boundary,
)
from run_ae_web_korean_golden_journey_playwright_acceptance import (
    run_ae_web_korean_golden_journey_playwright_acceptance,
)
from run_ae_web_korean_message_contract import run_ae_web_korean_message_contract
from run_ae_web_login_upload_ingestion_acceptance import (
    run_ae_web_login_upload_ingestion_acceptance,
)
from run_ae_web_viewport_accessibility_acceptance import (
    run_ae_web_viewport_accessibility_acceptance,
)
from run_s139_ae_web_protected_acceptance import (
    run_s139_ae_web_protected_acceptance,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s139_ae_web_korean_golden_journey_closure.v1"
CANONICAL_DOCUMENT = "docs/46_platform_ae_web_korean_golden_journey.md"
RELEASE_PLAN = "docs/37_platform_mvp_integration_release_plan.md"
RUNBOOK = "docs/runbooks/ae_web_korean_golden_journey.md"
PROTECTED_DOCUMENT = "docs/slices/1390_ae_web_protected_postgres_acceptance.md"
QUALITY_GATE = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s139_ae_web_korean_golden_journey_closure.py"
SECRET_PATTERNS = (
    r"postgres(?:ql)?(?:\+[^:]*)?://",
    r"\b(?:password|api[_ -]?key)\s*[:=]\s*\S+",
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    r"begin (?:rsa |ec |openssh )?private key",
)
WEB_ARTIFACTS = (
    "apps/nex-ae-web/src/locales/messages.js",
    "apps/nex-ae-web/src/goldenJourneyState.js",
    "apps/nex-ae-web/src/goldenJourneyIngestion.js",
    "apps/nex-ae-web/src/goldenJourneyGrounding.js",
    "apps/nex-ae-web/src/goldenJourneyArtifact.js",
    "apps/nex-ae-web/src/goldenJourneyViewport.js",
    "apps/nex-ae-web/src/deterministicGoldenJourney.js",
    "apps/nex-ae-web/scripts/runKoreanGoldenJourneyPlaywrightAcceptance.mjs",
    "apps/nex-ae-web/test/deterministicGoldenJourney.test.mjs",
    "apps/nex-ae-web/test/koreanGoldenJourneyPlaywrightAcceptance.test.mjs",
)
EvidenceRunner = Callable[[], dict[str, Any]]
EVIDENCE_RUNNERS: tuple[tuple[str, EvidenceRunner], ...] = (
    ("boundary", run_ae_web_korean_golden_journey_boundary),
    ("messages", run_ae_web_korean_message_contract),
    ("state", run_ae_web_golden_journey_state),
    ("ingestion", run_ae_web_login_upload_ingestion_acceptance),
    ("grounding", run_ae_web_grounding_journey_acceptance),
    ("artifact", run_ae_web_artifact_journey_acceptance),
    ("viewport", run_ae_web_viewport_accessibility_acceptance),
    ("playwright", run_ae_web_korean_golden_journey_playwright_acceptance),
    ("protected", lambda: run_s139_ae_web_protected_acceptance({})),
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1382", "ae_web_korean_golden_journey_boundary"),
        ("1383", "ae_web_korean_message_contract"),
        ("1384", "ae_web_golden_journey_state"),
        ("1385", "ae_web_login_upload_ingestion_acceptance"),
        ("1386", "ae_web_grounding_journey_acceptance"),
        ("1387", "ae_web_artifact_journey_acceptance"),
        ("1388", "ae_web_viewport_accessibility_hardening"),
        ("1389", "ae_web_korean_golden_journey_playwright"),
        ("1390", "ae_web_protected_postgres_acceptance"),
        ("1391", "s139_ae_web_korean_golden_journey_closure"),
    )
)


def run_s139_ae_web_korean_golden_journey_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_documents = (*SLICE_DOCUMENTS, CANONICAL_DOCUMENT, RELEASE_PLAN, RUNBOOK)
    document_presence = {
        path: (root / path).is_file() for path in required_documents
    }
    web_artifact_presence = {
        path: (root / path).is_file() for path in WEB_ARTIFACTS
    }
    evidence = (
        _run_evidence(root)
        if all(document_presence.values()) and all(web_artifact_presence.values())
        else {}
    )
    statuses = {name: item.get("status") for name, item in evidence.items()}
    canonical = _normalized_text(root / CANONICAL_DOCUMENT)
    release_plan = _normalized_text(root / RELEASE_PLAN)
    runbook = _normalized_text(root / RUNBOOK)
    protected = _normalized_text(root / PROTECTED_DOCUMENT)
    quality_gate = _read_text(root / QUALITY_GATE)

    deterministic_names = tuple(
        name for name, _runner in EVIDENCE_RUNNERS if name != "protected"
    )
    checks = {
        "eight_deterministic_components_pass": all(
            statuses.get(name) == "PASS" for name in deterministic_names
        ),
        "protected_component_is_opt_in": (
            statuses.get("protected") == "SKIPPED"
            and bool(_mapping(evidence.get("protected")).get("skip_reason"))
        ),
        "all_slice_canonical_and_runbook_documents_present": all(
            document_presence.values()
        ),
        "all_korean_journey_web_artifacts_present": all(
            web_artifact_presence.values()
        ),
        "closure_registered_once_in_full_gate": (
            quality_gate.count(CLOSURE_RUNNER) == 1
        ),
        "all_s139_evidence_registered_once_in_full_gate": all(
            quality_gate.count(Path(runner.__module__).name + ".py") == 1
            for name, runner in EVIDENCE_RUNNERS
            if name != "protected" and runner.__module__ != "__main__"
        ) and quality_gate.count("run_s139_ae_web_protected_acceptance.py") == 1,
        "actual_protected_execution_recorded": all(
            token in protected
            for token in (
                "sources `5/5`",
                "test databases `3`",
                "actual processes `13`",
                "Chromium viewports `2`",
                "all seven AE/CX residue counters equal to zero",
            )
        ),
        "korean_default_two_viewport_boundary_frozen": all(
            token in canonical
            for token in (
                "Default document language and primary user-facing workflow labels are Korean",
                "desktop `1440x900` and mobile `390x844`",
                "zero overflow/overlap",
            )
        ),
        "runbook_complete_and_secret_free": (
            all(
                marker in runbook
                for marker in (
                    "## Preconditions",
                    "## Deterministic Command",
                    "## Protected Command",
                    "## Expected Evidence",
                    "## Failure Triage",
                    "## Screenshot And Viewport Verification",
                    "## Cleanup Verification",
                    "## Rollback And Fail-Closed",
                    "## Privacy And Secret Handling",
                    "## S140 Handoff",
                )
            )
            and not _contains_secret(runbook)
        ),
        "browser_service_and_provider_boundaries_frozen": all(
            token in runbook
            for token in (
                "The browser must call only the same-origin `/ae-api` facade",
                "Do not replace a failed owner check with browser-supplied ownership",
                "Remote provider execution is not part of S139",
                "must fail closed",
            )
        ),
        "canonical_marks_s139_complete": all(
            token in canonical
            for token in (
                "Status: S139 complete.",
                "## Slice 1391 Closure",
                "Completion signal: Met.",
                "## S140 Handoff",
            )
        ),
        "release_plan_marks_s139_met_and_s140_active": all(
            token in release_plan
            for token in (
                "S139 completion signal: Met.",
                "S140 is the next active requirement",
            )
        ),
        "s140_handoff_preserves_release_candidate_boundary": all(
            token in canonical
            for token in (
                "all test databases",
                "all three remote provider capabilities",
                "deployment deferrals",
            )
        ),
        "privacy_projection_remains_content_free": all(
            token in canonical
            for token in (
                "must not contain passwords, tokens, prompts, document text",
                "generated text",
                "storage references",
            )
        ),
        "protected_default_does_not_mutate_databases": (
            _mapping(evidence.get("protected")).get("actual_postgres") is False
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1391",
        "slice_range": "1382-1391",
        "requirement": "S139",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "s139_ae_web_golden_journey_closure_failed",
        "closure_readiness": "READY_FOR_S140" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "evidence_statuses": statuses,
        "required_documents": document_presence,
        "web_artifacts": web_artifact_presence,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(
                value == "PASS" for value in statuses.values()
            ),
            "protected_skip_count": sum(
                value == "SKIPPED" for value in statuses.values()
            ),
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "journey_stage_count": 9 if passed else 0,
            "viewport_count": 2 if passed else 0,
            "actual_process_count": 13 if passed else 0,
            "protected_database_count": 3 if passed else 0,
            "web_artifact_count": sum(web_artifact_presence.values()),
        },
        "decision": {
            "completion_signal_met": passed,
            "actual_protected_browser_process_postgres_evidence_recorded": passed,
            "closure_database_or_provider_mutation_performed": False,
            "same_origin_browser_boundary_preserved": True,
            "private_payload_projection_allowed": False,
            "remote_provider_reexecution_required": False,
            "full_gate_registered": quality_gate.count(CLOSURE_RUNNER) == 1,
            "next_requirement": "S140" if passed else "blocked",
            "next_requirement_scope": (
                "platform_mvp_release_candidate_acceptance_and_operations_closure"
                if passed
                else "blocked"
            ),
        },
    }


def _run_evidence(root: Path) -> dict[str, dict[str, Any]]:
    if root.resolve() != ROOT.resolve():
        return {}
    return {name: runner() for name, runner in EVIDENCE_RUNNERS}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _normalized_text(path: Path) -> str:
    return " ".join(_read_text(path).split())


def _contains_secret(text: str) -> bool:
    return any(
        re.search(pattern, text, re.IGNORECASE) for pattern in SECRET_PATTERNS
    )


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "s139_ae_web_korean_golden_journey_closure=fail "
            f"checks={len(result.get('failed_checks') or [])}"
        )
    summary = _mapping(result.get("summary"))
    decision = _mapping(result.get("decision"))
    return (
        "s139_ae_web_korean_golden_journey_closure=pass "
        f"evidence={summary.get('passed_evidence_count', 0)}+"
        f"{summary.get('protected_skip_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"stages={summary.get('journey_stage_count', 0)} "
        f"viewports={summary.get('viewport_count', 0)} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_s139_ae_web_korean_golden_journey_closure()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
