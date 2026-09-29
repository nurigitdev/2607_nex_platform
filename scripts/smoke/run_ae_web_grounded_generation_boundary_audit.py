#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_web_grounded_generation_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/1081_s108_ae_async_artifact_rendering_closure.md",
    "apps/nex-ae-web/src/main.js",
    "apps/nex-ae-web/src/clientRegistry.js",
    "apps/nex-ae-web/src/retrievalClient.js",
    "apps/nex-ae-web/src/groundedResponseQuality.js",
    "apps/nex-ae-web/src/repairedResponseReviewCard.js",
    "contracts/openapi/nex-ae-api.openapi.yaml",
    "docs/development_process.md",
    "docs/slices/1082_ae_web_grounded_generation_boundary_audit.md",
    "docs/README.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "s108_closure",
        "scripts/smoke/run_s108_ae_async_artifact_rendering_closure.py",
        '"READY_FOR_S109"',
    ),
    EvidenceToken(
        "authenticated_runtime",
        "apps/nex-ae-web/src/authenticatedRuntime.js",
        "createAuthenticatedAeWebRuntime",
    ),
    EvidenceToken(
        "retrieval_client",
        "apps/nex-ae-web/src/retrievalClient.js",
        "createFetchRetrievalClient",
    ),
    EvidenceToken(
        "quality_surface",
        "apps/nex-ae-web/src/groundedResponseQuality.js",
        "buildGroundedResponseQualitySurface",
    ),
    EvidenceToken(
        "repair_surface",
        "apps/nex-ae-web/src/repairedResponseReviewCard.js",
        "renderRepairedResponseReviewCard",
    ),
    EvidenceToken(
        "chat_admission_api",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "/api/v1/chat/interactions:",
    ),
    EvidenceToken(
        "progress_api",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "/api/v1/chat/interactions/{interaction_id}/progress:",
    ),
    EvidenceToken(
        "refresh_api",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "/api/v1/chat/interactions/{interaction_id}/refresh:",
    ),
    EvidenceToken(
        "cancel_api",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "/api/v1/chat/interactions/{interaction_id}/cancel:",
    ),
    EvidenceToken(
        "retry_api",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "/api/v1/chat/interactions/{interaction_id}/retry:",
    ),
    EvidenceToken(
        "response_api",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "/api/v1/chat/interactions/{interaction_id}/response:",
    ),
    EvidenceToken(
        "citation_api",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "/api/v1/chat/interactions/{interaction_id}/citation-quality:",
    ),
    EvidenceToken(
        "playwright_foundation",
        "apps/nex-ae-web/package.json",
        '"@playwright/test"',
    ),
    EvidenceToken(
        "tiered_gate",
        "docs/development_process.md",
        "Checkpoint Gate",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "1082_ae_web_grounded_generation_boundary_audit.md",
    ),
)

GAP_RESOLUTION_PATHS = {
    "generation_client_missing": (
        "docs/slices/1083_ae_web_grounded_generation_client.md"
    ),
    "lifecycle_state_read_model_missing": (
        "docs/slices/1084_ae_web_generation_lifecycle_state.md"
    ),
    "runtime_composition_missing": (
        "docs/slices/1085_ae_web_generation_runtime_composition.md"
    ),
    "submission_progress_wiring_missing": (
        "docs/slices/1086_ae_web_generation_progress_wiring.md"
    ),
    "cancel_retry_recovery_ux_missing": (
        "docs/slices/1087_ae_web_generation_recovery_ux.md"
    ),
    "verified_response_quality_wiring_missing": (
        "docs/slices/1088_ae_web_verified_grounded_response.md"
    ),
    "diagnostics_accessibility_contract_missing": (
        "docs/slices/1089_ae_web_grounded_generation_experience_hardening.md"
    ),
    "protected_browser_evidence_missing": (
        "docs/slices/1090_ae_web_grounded_generation_playwright_postgres_smoke.md"
    ),
}

GAP_SLICES = {
    name: f"{1083 + index:04d}" for index, name in enumerate(GAP_RESOLUTION_PATHS)
}


def run_ae_web_grounded_generation_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_PATHS
    ]
    tokens = [
        {
            "group": item.group,
            "path": item.relative_path,
            "present": item.token in _read_text(root / item.relative_path),
        }
        for item in EVIDENCE_TOKENS
    ]
    main_source = _read_text(root / "apps/nex-ae-web/src/main.js")
    drift_states = {
        "locally_composed_assistant_response": (
            "retrieval 결과와 ${format} handoff를 연결했습니다." in main_source
        ),
        "mock_quality_built_in_submit_flow": (
            "buildMockGroundedResponseQualityContract(true" in main_source
        ),
        "fixture_progress_replaces_server_lifecycle": (
            "workspaceState.progressEvents = buildProgressEvents(grounded)"
            in main_source
        ),
    }
    gap_states = {
        name: "RESOLVED" if (root / path).is_file() else "OPEN"
        for name, path in GAP_RESOLUTION_PATHS.items()
    }
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s108_handoff_bound": _group_present(tokens, "s108_closure"),
        "authenticated_retrieval_foundation_reusable": all(
            _group_present(tokens, group)
            for group in ("authenticated_runtime", "retrieval_client")
        ),
        "quality_repair_surfaces_reusable": all(
            _group_present(tokens, group)
            for group in ("quality_surface", "repair_surface")
        ),
        "ae_async_lifecycle_api_complete": all(
            _group_present(tokens, group)
            for group in (
                "chat_admission_api",
                "progress_api",
                "refresh_api",
                "cancel_api",
                "retry_api",
                "response_api",
                "citation_api",
            )
        ),
        "browser_smoke_foundation_reusable": _group_present(
            tokens, "playwright_foundation"
        ),
        "tiered_quality_cadence_confirmed": _group_present(tokens, "tiered_gate"),
        "current_runtime_drift_reproduced": all(drift_states.values()),
        "implementation_gaps_accounted_for": len(gap_states) == 8,
    }
    issues = [
        {"category": "path_missing", "path": item["path"]}
        for item in paths
        if not item["present"]
    ]
    issues.extend(
        {
            "category": "source_token_missing",
            "path": item["path"],
            "group": item["group"],
        }
        for item in tokens
        if not item["present"]
    )
    passed = all(checks.values()) and not issues
    next_slice = next(
        (GAP_SLICES[name] for name, state in gap_states.items() if state == "OPEN"),
        "1091",
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1082",
        "requirement": "S109",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "decision": boundary_decision(),
        "summary": {
            "foundation_count": 6,
            "gap_count": len(gap_states),
            "open_gap_count": sum(state == "OPEN" for state in gap_states.values()),
            "resolved_gap_count": sum(
                state == "RESOLVED" for state in gap_states.values()
            ),
            "drift_count": sum(drift_states.values()),
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "known_drifts": [
            "chat_submit_composes_a_local_assistant_response_in_main_js",
            "grounded_generation_has_no_dedicated_browser_client",
            "progress_timeline_uses_static_fixture_events",
            "artifact_export_can_start_before_verified_generation_completion",
            "quality_and_repair_surfaces_receive_mock_submit_data",
            "cancel_retry_refresh_and_recovery_are_not_exposed_in_the_web_runtime",
            "protected_grounded_generation_browser_evidence_is_missing",
        ],
        "drift_states": drift_states,
        "gap_states": gap_states,
        "gap_resolution_paths": GAP_RESOLUTION_PATHS,
        "slice_plan": [
            "1082_boundary_audit",
            "1083_grounded_generation_client",
            "1084_lifecycle_state_read_model",
            "1085_runtime_composition",
            "1086_submission_progress_checkpoint",
            "1087_cancel_retry_recovery_ux",
            "1088_verified_response_quality_wiring",
            "1089_diagnostics_accessibility_contract_hardening",
            "1090_protected_playwright_postgres_live_smoke",
            "1091_s109_closure_full_gate",
        ],
        "checks": checks,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": next_slice,
    }


def boundary_decision() -> dict[str, Any]:
    return {
        "experience_owner": "nex-ae-web",
        "orchestration_owner": "nex-ae-api",
        "grounded_generation_owner": "nex-cx",
        "provider_execution_owner": "nex-mo",
        "scope": "ae_web_grounded_generation_experience_hardening",
        "browser_service_boundary": "same_origin_nex_ae_api_only",
        "browser_direct_cx_call_allowed": False,
        "browser_direct_mo_call_allowed": False,
        "browser_service_token_allowed": False,
        "browser_provider_url_allowed": False,
        "browser_database_url_allowed": False,
        "execution_model": "ae_async_interaction_poll_refresh",
        "completion_content_source": "ae_generated_response_endpoint",
        "quality_source": "ae_citation_quality_endpoint",
        "explicit_cancel_retry_recovery_required": True,
        "artifact_handoff_after_verified_completion": True,
        "new_tables_expected": 0,
        "actual_postgresql_required_slice": "1090",
        "playwright_required_slice": "1090",
        "remote_generation_provider_required_slice": "1090",
        "quality_cadence": {
            "slice_gate": "every_slice",
            "checkpoint_gate": "1086",
            "full_gate": "1091",
        },
    }


def summary_line(result: dict[str, Any]) -> str:
    summary = result.get("summary", {})
    return (
        "ae_web_grounded_generation_boundary="
        f"{'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"foundations={summary.get('foundation_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"open={summary.get('open_gap_count', 0)} "
        f"drifts={summary.get('drift_count', 0)} "
        f"issues={summary.get('issue_count', 0)} "
        f"next={result.get('next_slice', 'unknown')}"
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _group_present(tokens: list[dict[str, Any]], group: str) -> bool:
    return any(item["group"] == group and item["present"] for item in tokens)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_web_grounded_generation_boundary_audit()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
