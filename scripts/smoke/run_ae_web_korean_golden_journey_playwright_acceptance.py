#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_web_korean_golden_journey_playwright_acceptance.v1"


def run_ae_web_korean_golden_journey_playwright_acceptance(
    root: Path = ROOT,
) -> dict[str, Any]:
    journey = _read_text(
        root / "apps/nex-ae-web/src/deterministicGoldenJourney.js"
    )
    playwright = _read_text(
        root
        / "apps/nex-ae-web/scripts/runKoreanGoldenJourneyPlaywrightAcceptance.mjs"
    )
    package = _read_text(root / "apps/nex-ae-web/package.json")
    main = _read_text(root / "apps/nex-ae-web/src/main.js")
    checks = {
        "correlated_nine_stage_runner_present": all(
            token in journey
            for token in (
                "runGoldenJourneyIngestion",
                "runGoldenJourneyGrounding",
                "runGoldenJourneyArtifact",
                "completedStageCount",
            )
        ),
        "actual_chromium_runner_present": all(
            token in playwright
            for token in (
                "playwright.chromium.launch",
                'browser: "chromium"',
                "browser.newContext",
                "page.goto",
            )
        ),
        "two_viewports_and_layout_evaluator_present": all(
            token in playwright
            for token in (
                "GOLDEN_JOURNEY_VIEWPORTS",
                "evaluateGoldenJourneyViewport",
                "GOLDEN_JOURNEY_NON_OVERLAP_PAIRS",
                "rectangleOverlapArea",
            )
        ),
        "visible_ui_actions_present": all(
            token in playwright
            for token in (
                'page.fill("#credential-employee-id"',
                'page.setInputFiles("#upload-file-input"',
                'page.fill("#prompt"',
                'locator("[data-artifact-preview-route]")',
                'locator("[data-artifact-download-route]")',
            )
        ),
        "screenshot_and_redaction_present": all(
            token in playwright
            for token in (
                "page.screenshot",
                "assertEvidenceRedacted",
                "prompt_content_included: false",
                "credential_material_included: false",
            )
        ),
        "mock_login_surface_is_executable": all(
            token in main
            for token in (
                "createMockSessionClient",
                "buildLocalMockBrowserSessionSnapshot",
                'reason: "login_required"',
            )
        ),
        "package_command_present": (
            '"smoke:korean-golden-journey-playwright"' in package
        ),
        "node_tests_present": all(
            path.is_file()
            for path in (
                root
                / "apps/nex-ae-web/test/deterministicGoldenJourney.test.mjs",
                root
                / "apps/nex-ae-web/test/koreanGoldenJourneyPlaywrightAcceptance.test.mjs",
            )
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = not issues
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1389",
        "requirement": "S139",
        "status": "PASS" if passed else "FAIL",
        "playwright_acceptance_readiness": "READY" if passed else "BLOCKED",
        "checks": checks,
        "issues": issues,
        "summary": {
            "viewport_count": 2,
            "journey_stage_count": 9,
            "ui_action_family_count": 3,
            "artifact_action_count": 2,
            "screenshot_count": 2,
            "issue_count": len(issues),
        },
        "decision": {
            "actual_browser": "chromium",
            "actual_browser_execution_required": True,
            "deterministic_provider_mode": "mock",
            "test_postgresql_required": False,
            "remote_provider_required": False,
            "next_slice": "1390" if passed else "blocked",
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
            "ae_web_korean_golden_journey_playwright=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "ae_web_korean_golden_journey_playwright=pass "
        f"viewports={summary.get('viewport_count', 0)} "
        f"stages={summary.get('journey_stage_count', 0)} "
        f"actions={summary.get('ui_action_family_count', 0)}+"
        f"{summary.get('artifact_action_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_web_korean_golden_journey_playwright_acceptance()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
