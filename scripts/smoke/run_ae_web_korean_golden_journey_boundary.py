#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_web_korean_golden_journey_boundary.v1"
CANONICAL_DOCUMENT = "docs/46_platform_ae_web_korean_golden_journey.md"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    path: str
    token: str


REQUIRED_PATHS = (
    "docs/37_platform_mvp_integration_release_plan.md",
    "docs/45_platform_ag_cross_service_trace_operations_e2e.md",
    CANONICAL_DOCUMENT,
    "apps/nex-ae-web/index.html",
    "apps/nex-ae-web/src/main.js",
    "apps/nex-ae-web/src/styles.css",
    "apps/nex-ae-web/scripts/runCredentialLoginPlaywrightSmoke.mjs",
    "apps/nex-ae-web/scripts/runAuthenticatedUploadPlaywrightSmoke.mjs",
    "apps/nex-ae-web/scripts/runGroundedGenerationPlaywrightSmoke.mjs",
    "apps/nex-ae-web/scripts/runArtifactPlaywrightSmoke.mjs",
    "scripts/quality/run_quality_gate.sh",
    "docs/slices/1382_ae_web_korean_golden_journey_boundary.md",
)

TOKENS = (
    EvidenceToken(
        "korean_document",
        "apps/nex-ae-web/index.html",
        '<html lang="ko">',
    ),
    EvidenceToken(
        "same_origin_facade",
        "apps/nex-ae-web/scripts/serve.mjs",
        'AE_API_PROXY_PREFIX = "/ae-api"',
    ),
    EvidenceToken(
        "credential_playwright",
        "apps/nex-ae-web/scripts/runCredentialLoginPlaywrightSmoke.mjs",
        "runCredentialLoginPlaywrightSmoke",
    ),
    EvidenceToken(
        "upload_playwright",
        "apps/nex-ae-web/scripts/runAuthenticatedUploadPlaywrightSmoke.mjs",
        "runAuthenticatedUploadPlaywrightSmoke",
    ),
    EvidenceToken(
        "generation_playwright",
        "apps/nex-ae-web/scripts/runGroundedGenerationPlaywrightSmoke.mjs",
        "runGroundedGenerationPlaywrightSmoke",
    ),
    EvidenceToken(
        "artifact_playwright",
        "apps/nex-ae-web/scripts/runArtifactPlaywrightSmoke.mjs",
        "runArtifactPlaywrightSmoke",
    ),
    EvidenceToken(
        "s138_handoff",
        "docs/45_platform_ag_cross_service_trace_operations_e2e.md",
        "owner-safe browser links needed for Korean-default Playwright acceptance",
    ),
    EvidenceToken(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_web_korean_golden_journey_boundary.py",
    ),
)

GAPS = {
    "korean_default_message_contract": "1383",
    "correlated_journey_state": "1384",
    "login_upload_progress_acceptance": "1385",
    "retrieval_generation_citation_acceptance": "1386",
    "artifact_preview_download_acceptance": "1387",
    "desktop_mobile_accessibility_acceptance": "1388",
    "deterministic_playwright_golden_journey": "1389",
    "protected_service_process_browser_acceptance": "1390",
}


def run_ae_web_korean_golden_journey_boundary(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    tokens = {
        item.group: item.token in _read_text(root / item.path)
        for item in TOKENS
    }
    canonical = _normalized_text(root / CANONICAL_DOCUMENT)
    gaps = {name: "OPEN" for name in GAPS}
    checks = {
        "required_paths_present": all(paths.values()),
        "required_tokens_present": all(tokens.values()),
        "korean_default_document_present": tokens.get("korean_document") is True,
        "same_origin_facade_frozen": tokens.get("same_origin_facade") is True,
        "focused_playwright_foundations_present": all(
            tokens.get(name) is True
            for name in (
                "credential_playwright",
                "upload_playwright",
                "generation_playwright",
                "artifact_playwright",
            )
        ),
        "eight_acceptance_gaps_frozen": (
            len(gaps) == 8
            and all(slice_id in canonical for slice_id in GAPS.values())
        ),
        "browser_ownership_and_privacy_frozen": all(
            token in canonical
            for token in (
                "same-origin `/ae-api` facade",
                "does not accept browser-supplied ownership",
                "must not contain passwords, tokens, prompts, document text",
                "never reads a service database",
            )
        ),
        "desktop_mobile_completion_signal_frozen": all(
            token in canonical
            for token in (
                "desktop and mobile viewports",
                "actual Chromium process",
                "actual service processes",
            )
        ),
        "s140_handoff_frozen": (
            "## S140 Handoff" in canonical
            and "S140 owns release-candidate execution" in canonical
        ),
    }
    issues = [
        {"category": "path_missing", "path": path}
        for path, present in paths.items()
        if not present
    ]
    issues.extend(
        {"category": "token_missing", "group": group}
        for group, present in tokens.items()
        if not present
    )
    passed = all(checks.values()) and not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1382",
        "requirement": "S139",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "evidence_tokens": tokens,
        "gap_states": gaps,
        "summary": {
            "required_path_count": sum(paths.values()),
            "evidence_token_count": sum(tokens.values()),
            "acceptance_gap_count": len(gaps),
            "open_gap_count": len(gaps),
            "focused_playwright_count": 4,
            "viewport_count": 2,
            "missing_path_count": sum(not value for value in paths.values()),
            "missing_token_count": sum(not value for value in tokens.values()),
        },
        "decision": {
            "new_table_required": False,
            "remote_model_provider_required": False,
            "actual_browser_required_now": False,
            "protected_browser_deferred_to_slice": "1390",
            "direct_service_or_database_browser_access_allowed": False,
            "next_slice": "1383" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _normalized_text(path: Path) -> str:
    return " ".join(_read_text(path).split())


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "ae_web_korean_golden_journey_boundary=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "ae_web_korean_golden_journey_boundary=pass "
        f"paths={summary.get('required_path_count', 0)}/{len(REQUIRED_PATHS)} "
        f"tokens={summary.get('evidence_token_count', 0)}/{len(TOKENS)} "
        f"gaps={summary.get('open_gap_count', 0)}/"
        f"{summary.get('acceptance_gap_count', 0)} "
        f"viewports={summary.get('viewport_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_web_korean_golden_journey_boundary()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
