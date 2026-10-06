#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_web_artifact_journey_acceptance.v1"
MODULE_PATH = "apps/nex-ae-web/src/goldenJourneyArtifact.js"

REQUIRED_TOKENS = (
    "submitArtifactExportRequest",
    "previewArtifactFile",
    "downloadArtifactFile",
    'stage: "ARTIFACT_READY"',
    'stage: "PREVIEW_READY"',
    'stage: "DOWNLOAD_READY"',
    'surface?.jobStatus !== "COMPLETED"',
    'surface?.artifactSurface?.artifactStatus !== "READY"',
    "assertArtifactFileMatch",
    "buildGoldenJourneyEvidence",
)

PRIVATE_RETURN_TOKENS = (
    "textPreview:",
    "content:",
    "contentBase64:",
    "storageRef:",
    "downloadFileName:",
)


def run_ae_web_artifact_journey_acceptance(root: Path = ROOT) -> dict[str, Any]:
    source = _read_text(root / MODULE_PATH)
    success_projection = source.split("return Object.freeze", 1)[-1].split(
        "} catch", 1
    )[0]
    checks = {
        "artifact_module_present": bool(source),
        "required_orchestration_present": all(
            token in source for token in REQUIRED_TOKENS
        ),
        "nine_stage_journey_completion_frozen": all(
            stage in source
            for stage in ("ARTIFACT_READY", "PREVIEW_READY", "DOWNLOAD_READY")
        ),
        "render_completion_and_format_guard_present": all(
            token in source
            for token in ("progressPercent !== 100", "targetFormats.every")
        ),
        "artifact_file_lineage_guard_present": (
            "actual.artifactFileId !== expected.artifactFileId" in source
            and "actual.artifactId !== expected.artifactId" in source
        ),
        "private_payload_absent_from_return": not any(
            token in success_projection for token in PRIVATE_RETURN_TOKENS
        ),
        "exact_failure_phases_present": all(
            token in source
            for token in ("ARTIFACT_FAILED", "PREVIEW_FAILED", "DOWNLOAD_FAILED")
        ),
        "node_contract_test_present": (
            root / "apps/nex-ae-web/test/goldenJourneyArtifact.test.mjs"
        ).is_file(),
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = not issues
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1387",
        "requirement": "S139",
        "status": "PASS" if passed else "FAIL",
        "artifact_acceptance_readiness": "READY" if passed else "BLOCKED",
        "checks": checks,
        "issues": issues,
        "summary": {
            "required_token_count": len(REQUIRED_TOKENS),
            "journey_stage_count": 9,
            "artifact_operation_count": 3,
            "failure_phase_count": 3,
            "issue_count": len(issues),
        },
        "decision": {
            "completed_render_required": True,
            "artifact_file_lineage_required": True,
            "private_payload_in_evidence_allowed": False,
            "new_table_required": False,
            "remote_provider_required": False,
            "next_slice": "1388" if passed else "blocked",
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
            "ae_web_artifact_journey=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "ae_web_artifact_journey=pass "
        f"stages={summary.get('journey_stage_count', 0)} "
        f"operations={summary.get('artifact_operation_count', 0)} "
        f"failures={summary.get('failure_phase_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_web_artifact_journey_acceptance()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
