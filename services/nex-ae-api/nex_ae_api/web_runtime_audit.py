from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "ae_web_runtime_audit.v1"


def build_ae_web_runtime_audit(root: Path = ROOT) -> dict[str, Any]:
    web_root = root / "apps/nex-ae-web"
    source_root = web_root / "src"
    test_root = web_root / "test"
    scripts_root = web_root / "scripts"
    package_path = web_root / "package.json"
    index_path = web_root / "index.html"
    main_path = source_root / "main.js"
    issues = []

    package = _load_json_mapping(package_path)
    if not package:
        issues.append({"category": "web_package_missing_or_invalid"})
    index_source = _read_text(index_path)
    main_source = _read_text(main_path)
    if not index_source:
        issues.append({"category": "web_index_missing"})
    if not main_source:
        issues.append({"category": "web_composition_missing"})

    source_files = sorted(path for path in source_root.glob("*") if path.is_file())
    test_files = sorted(test_root.glob("*.test.mjs"))
    playwright_scripts = sorted(
        path for path in scripts_root.glob("*.mjs") if "playwright" in path.name.lower()
    )
    playwright_tests = sorted(
        path
        for path in test_root.glob("*.test.mjs")
        if "playwright" in path.name.lower()
    )
    accessibility_scripts = sorted(
        path
        for path in scripts_root.glob("*.mjs")
        if "accessibility" in path.name.lower()
    )
    accessibility_tests = sorted(
        path
        for path in test_root.glob("*.test.mjs")
        if "accessibility" in path.name.lower()
    )
    localization_files = [
        path
        for path in web_root.rglob("*")
        if path.is_file()
        and any(
            part.lower() in {"i18n", "locale", "locales"}
            for part in path.relative_to(web_root).parts
        )
    ]
    localization_contract_present = any(
        path.name == "messages.js" and "locales" in path.relative_to(web_root).parts
        for path in localization_files
    )
    package_text = _read_text(package_path)
    package_version = str(package.get("version") or "")
    main_line_count = len(main_source.splitlines())
    hardcoded_korean_lines = sum(
        bool(re.search(r"[\uac00-\ud7a3]", line))
        for line in f"{index_source}\n{main_source}".splitlines()
    )
    semantic_tokens = {
        "document_language": '<html lang="ko">' in index_source,
        "main_landmark": "<main" in index_source,
        "navigation_landmark": "<nav" in index_source,
        "live_region": 'aria-live="polite"' in index_source,
        "label_associations": "<label for=" in index_source,
    }
    checks = {
        "audit_inputs_present": not issues,
        "source_inventory_complete": len(source_files) >= 42,
        "test_inventory_complete": len(test_files) >= 54,
        "playwright_inventory_complete": (
            len(playwright_scripts) >= 6
            and len(playwright_scripts) == len(playwright_tests)
        ),
        "accessibility_inventory_classified": (
            len(accessibility_scripts) == 1 and len(accessibility_tests) == 1
        ),
        "semantic_baseline_present": all(semantic_tokens.values()),
        "known_gaps_classified": (
            main_line_count >= 2_500
            and localization_contract_present
            and "slice0227" in package_version
            and "axe-core" not in package_text
        ),
    }
    passed = all(checks.values()) and not issues
    findings = [
        {
            "finding_id": "web_composition_size",
            "disposition": "REFACTOR_REQUIRED",
            "risk": "HIGH",
            "evidence": {"main_js_line_count": main_line_count},
        },
        {
            "finding_id": "localization_contract",
            "disposition": (
                "GOOD_BOUNDARY" if localization_contract_present else "REFACTOR_REQUIRED"
            ),
            "risk": "LOW" if localization_contract_present else "HIGH",
            "evidence": {
                "localization_file_count": len(localization_files),
                "localization_contract_present": localization_contract_present,
                "hardcoded_korean_line_count": hardcoded_korean_lines,
            },
        },
        {
            "finding_id": "web_package_version_stale",
            "disposition": "REFACTOR_REQUIRED",
            "risk": "MEDIUM",
            "evidence": {"package_version": package_version},
        },
        {
            "finding_id": "accessibility_automation_narrow",
            "disposition": "REFACTOR_REQUIRED",
            "risk": "MEDIUM",
            "evidence": {
                "accessibility_script_count": len(accessibility_scripts),
                "axe_dependency_present": "axe-core" in package_text,
            },
        },
        {
            "finding_id": "semantic_html_baseline",
            "disposition": "GOOD_BOUNDARY",
            "risk": "LOW",
            "evidence": semantic_tokens,
        },
        {
            "finding_id": "deterministic_playwright_harnesses",
            "disposition": "GOOD_BOUNDARY",
            "risk": "LOW",
            "evidence": {
                "script_count": len(playwright_scripts),
                "test_count": len(playwright_tests),
            },
        },
        {
            "finding_id": "module_test_depth",
            "disposition": "GOOD_BOUNDARY",
            "risk": "LOW",
            "evidence": {
                "source_file_count": len(source_files),
                "test_file_count": len(test_files),
            },
        },
    ]
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1009",
        "requirement": "S101",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "ae_web_runtime_audit_failed",
        "web_readiness": "GAPS_CONFIRMED" if passed else "BLOCKED",
        "summary": {
            "source_file_count": len(source_files),
            "test_file_count": len(test_files),
            "main_js_line_count": main_line_count,
            "playwright_script_count": len(playwright_scripts),
            "playwright_test_count": len(playwright_tests),
            "accessibility_script_count": len(accessibility_scripts),
            "localization_file_count": len(localization_files),
            "hardcoded_korean_line_count": hardcoded_korean_lines,
            "refactor_required_count": sum(
                item["disposition"] == "REFACTOR_REQUIRED" for item in findings
            ),
            "good_boundary_count": sum(
                item["disposition"] == "GOOD_BOUNDARY" for item in findings
            ),
            "issue_count": len(issues),
        },
        "package_version": package_version,
        "checks": checks,
        "findings": findings,
        "issues": issues,
        "hardening_handoff": {
            "target_requirement": "S102",
            "priorities": [
                "extract Web application composition by capability",
                "add whole-page automated accessibility checks",
                "replace slice-era package versioning",
            ],
            "preserve": [
                "semantic HTML baseline",
                "Korean-default locale catalog contract",
                "deterministic Playwright harnesses",
                "module-level Node regression suite",
            ],
        },
        "actual_browser_comparison": {
            "status": "DEFERRED_TO_SLICE_1010",
            "tool": "Playwright",
        },
        "next_slice": "1010",
    }


def _load_json_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""
