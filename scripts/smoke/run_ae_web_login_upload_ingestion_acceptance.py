#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_web_login_upload_ingestion_acceptance.v1"

REQUIRED_PATHS = (
    "apps/nex-ae-web/src/goldenJourneyIngestion.js",
    "apps/nex-ae-web/src/uploadProgressClient.js",
    "apps/nex-ae-web/test/goldenJourneyIngestion.test.mjs",
    "apps/nex-ae-web/test/uploadProgressClient.test.mjs",
    "docs/slices/1385_ae_web_login_upload_ingestion_acceptance.md",
)

REQUIRED_TOKENS = {
    "session_login": (
        "apps/nex-ae-web/src/goldenJourneyIngestion.js",
        "await sessionClient.login(loginRequest)",
    ),
    "claim_derived_owner": (
        "apps/nex-ae-web/src/goldenJourneyIngestion.js",
        "ownerUserId: session.subjectRef.id",
    ),
    "browser_owner_rejected": (
        "apps/nex-ae-web/src/goldenJourneyIngestion.js",
        '"BROWSER_OWNER_SCOPE_FORBIDDEN"',
    ),
    "upload_submission": (
        "apps/nex-ae-web/src/goldenJourneyIngestion.js",
        "await uploadClient.submitUploadDraft",
    ),
    "bounded_progress_poll": (
        "apps/nex-ae-web/src/goldenJourneyIngestion.js",
        "while (pollCount < maxPolls)",
    ),
    "index_ready_gate": (
        "apps/nex-ae-web/src/goldenJourneyIngestion.js",
        'progress?.status !== "INDEX_READY"',
    ),
    "same_origin_credentials": (
        "apps/nex-ae-web/src/uploadProgressClient.js",
        'credentials: "same-origin"',
    ),
    "ae_progress_route": (
        "apps/nex-ae-web/src/uploadProgressClient.js",
        "`/api/v1/uploads/${encodeURIComponent(normalized)}/progress`",
    ),
    "main_progress_wiring": (
        "apps/nex-ae-web/src/main.js",
        "workspaceState.uploadProgressClient.getProgress",
    ),
    "registry_progress_wiring": (
        "apps/nex-ae-web/src/clientRegistry.js",
        "uploadProgressClient: createFetchUploadProgressClient",
    ),
}


def run_ae_web_login_upload_ingestion_acceptance(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    tokens = {
        name: token in _read_text(root / path)
        for name, (path, token) in REQUIRED_TOKENS.items()
    }
    workflow = _read_text(root / "apps/nex-ae-web/src/goldenJourneyIngestion.js")
    checks = {
        "required_paths_present": all(paths.values()),
        "required_tokens_present": all(tokens.values()),
        "three_stages_correlated": all(
            f'stage: "{stage}"' in workflow
            for stage in (
                "SESSION_AUTHENTICATED",
                "UPLOAD_ACCEPTED",
                "INGESTION_INDEXED",
            )
        ),
        "private_error_detail_excluded": (
            "error.message" not in workflow and "loginRequest" not in workflow.split("return Object.freeze", 1)[-1]
        ),
        "direct_cx_browser_call_absent": "nex-cx" not in workflow,
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = not issues
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1385",
        "requirement": "S139",
        "status": "PASS" if passed else "FAIL",
        "ingestion_acceptance_readiness": "READY" if passed else "BLOCKED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "evidence_tokens": tokens,
        "summary": {
            "required_path_count": sum(paths.values()),
            "evidence_token_count": sum(tokens.values()),
            "journey_stage_count": 3,
            "same_origin_route_count": 1,
            "issue_count": len(issues),
        },
        "decision": {
            "oa_claims_owner_authoritative": True,
            "browser_owner_scope_allowed": False,
            "direct_cx_browser_call_allowed": False,
            "new_table_required": False,
            "remote_provider_required": False,
            "next_slice": "1386" if passed else "blocked",
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
            "ae_web_login_upload_ingestion=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "ae_web_login_upload_ingestion=pass "
        f"paths={summary.get('required_path_count', 0)}/{len(REQUIRED_PATHS)} "
        f"tokens={summary.get('evidence_token_count', 0)}/{len(REQUIRED_TOKENS)} "
        f"stages={summary.get('journey_stage_count', 0)} "
        f"owner=oa-claims next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_web_login_upload_ingestion_acceptance()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
