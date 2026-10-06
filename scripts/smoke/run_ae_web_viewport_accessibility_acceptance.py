#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_web_viewport_accessibility_acceptance.v1"


def run_ae_web_viewport_accessibility_acceptance(
    root: Path = ROOT,
) -> dict[str, Any]:
    module = _read_text(
        root / "apps/nex-ae-web/src/goldenJourneyViewport.js"
    )
    tests = _read_text(
        root / "apps/nex-ae-web/test/goldenJourneyViewport.test.mjs"
    )
    html = _read_text(root / "apps/nex-ae-web/index.html")
    css = _read_text(root / "apps/nex-ae-web/src/styles.css")
    messages = _read_text(root / "apps/nex-ae-web/src/locales/messages.js")
    required_regions = (
        "golden-sidebar",
        "main-workspace",
        "golden-topbar",
        "workspace-summary",
        "golden-content",
        "golden-workspace-column",
        "golden-context-pane",
        "golden-chat",
        "golden-timeline",
    )
    checks = {
        "viewport_contract_present": all(
            token in module
            for token in (
                "desktop: Object.freeze({ width: 1440, height: 900 })",
                "mobile: Object.freeze({ width: 390, height: 844 })",
                "MIN_CONTROL_TARGET_PX = 24",
            )
        ),
        "layout_checks_frozen": all(
            token in module
            for token in (
                "korean_document",
                "single_main_landmark",
                "single_primary_heading",
                "no_horizontal_overflow",
                "controls_accessibly_named",
                "controls_meet_target_size",
                "focus_indicator_visible",
                "primary_regions_do_not_overlap",
            )
        ),
        "required_region_markers_present": all(
            f'id="{region}"' in html for region in required_regions
        ),
        "korean_main_landmark_present": (
            '<html lang="ko">' in html
            and '<main class="workspace" id="main-workspace"' in html
        ),
        "localized_skip_link_present": all(
            token in html + messages
            for token in (
                'class="skip-link"',
                'href="#main-workspace"',
                '"action.skip_main": "본문으로 건너뛰기"',
                '"action.skip_main": "Skip to main content"',
            )
        ),
        "focus_and_responsive_css_present": all(
            token in css
            for token in (
                ".skip-link:focus-visible",
                "@media (max-width: 1080px)",
                "@media (max-width: 900px)",
                "@media (max-width: 620px)",
                "overflow-wrap: anywhere",
            )
        ),
        "positive_and_negative_node_tests_present": all(
            token in tests
            for token in (
                "accepts desktop and mobile snapshots",
                "reports overflow, accessibility, target, focus, region, and overlap failures",
                "calculates rectangle intersections",
            )
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = not issues
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1388",
        "requirement": "S139",
        "status": "PASS" if passed else "FAIL",
        "viewport_accessibility_readiness": "READY" if passed else "BLOCKED",
        "checks": checks,
        "issues": issues,
        "summary": {
            "viewport_count": 2,
            "required_region_count": len(required_regions),
            "non_overlap_pair_count": 5,
            "minimum_control_target_px": 24,
            "issue_count": len(issues),
        },
        "decision": {
            "desktop_viewport": "1440x900",
            "mobile_viewport": "390x844",
            "default_locale": "ko",
            "horizontal_overflow_allowed": False,
            "actual_browser_required_next": True,
            "remote_provider_required": False,
            "next_slice": "1389" if passed else "blocked",
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
            "ae_web_viewport_accessibility=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "ae_web_viewport_accessibility=pass "
        f"viewports={summary.get('viewport_count', 0)} "
        f"regions={summary.get('required_region_count', 0)} "
        f"pairs={summary.get('non_overlap_pair_count', 0)} "
        f"target={summary.get('minimum_control_target_px', 0)}px "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_web_viewport_accessibility_acceptance()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
