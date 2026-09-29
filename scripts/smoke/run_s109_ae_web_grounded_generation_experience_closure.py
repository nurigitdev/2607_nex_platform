#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "quality"))

from run_ae_web_grounded_generation_boundary_audit import (  # noqa: E402
    run_ae_web_grounded_generation_boundary_audit as run_boundary,
)
from run_ae_web_grounded_generation_playwright_postgres_smoke import (  # noqa: E402
    EXPECTED_MODELS,
    SMOKE_ENV as LIVE_SMOKE_ENV,
    run_ae_web_grounded_generation_playwright_postgres_smoke as run_live,
)
from validate_contracts import validate_contract_tree  # noqa: E402


SCHEMA_VERSION = "s109_ae_web_grounded_generation_experience_closure.v1"
SLICE_RANGE = "1082-1091"

REQUIRED_FILES = (
    "apps/nex-ae-web/src/groundedGenerationClient.js",
    "apps/nex-ae-web/src/groundedGenerationWorkflow.js",
    "apps/nex-ae-web/src/groundedGenerationRecovery.js",
    "apps/nex-ae-web/src/groundedGenerationPresentation.js",
    "apps/nex-ae-web/src/documentBootstrap.js",
    "apps/nex-ae-web/src/workspaceBootstrap.js",
    "apps/nex-ae-web/scripts/runGroundedGenerationExperienceSmoke.mjs",
    "apps/nex-ae-web/scripts/runGroundedGenerationPlaywrightSmoke.mjs",
    "scripts/smoke/run_ae_web_grounded_generation_boundary_audit.py",
    "scripts/smoke/run_ae_web_grounded_generation_playwright_postgres_smoke.py",
    "scripts/smoke/run_s109_ae_web_grounded_generation_experience_closure.py",
    "tests/test_s109_ae_web_grounded_generation_experience_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("1082", "ae_web_grounded_generation_boundary_audit"),
            ("1083", "ae_web_grounded_generation_client"),
            ("1084", "ae_web_generation_lifecycle_state"),
            ("1085", "ae_web_generation_runtime_composition"),
            ("1086", "ae_web_generation_progress_wiring"),
            ("1087", "ae_web_generation_recovery_ux"),
            ("1088", "ae_web_verified_grounded_response"),
            ("1089", "ae_web_grounded_generation_experience_hardening"),
            ("1090", "ae_web_grounded_generation_playwright_postgres_smoke"),
            ("1091", "s109_ae_web_grounded_generation_experience_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "same_origin_client",
        "apps/nex-ae-web/src/groundedGenerationClient.js",
        "export function createFetchGroundedGenerationClient(",
    ),
    (
        "bounded_workflow",
        "apps/nex-ae-web/src/groundedGenerationWorkflow.js",
        "export async function runGroundedGenerationWorkflow(",
    ),
    (
        "recovery_actions",
        "apps/nex-ae-web/src/groundedGenerationRecovery.js",
        "export async function retryGroundedGeneration(",
    ),
    (
        "verified_presentation",
        "apps/nex-ae-web/src/groundedGenerationPresentation.js",
        "export async function buildGroundedGenerationPresentation(",
    ),
    (
        "runtime_wiring",
        "apps/nex-ae-web/src/main.js",
        "async function appendPromptInteraction()",
    ),
    (
        "cancel_wiring",
        "apps/nex-ae-web/src/main.js",
        "async function cancelActiveGeneration()",
    ),
    (
        "retry_wiring",
        "apps/nex-ae-web/src/main.js",
        "async function retryLastGeneration()",
    ),
    (
        "diagnostics_projection",
        "apps/nex-ae-web/src/runtimeDiagnostics.js",
        "buildGroundedGenerationPresentationSummary",
    ),
    (
        "deterministic_experience_smoke",
        "scripts/quality/run_quality_gate.sh",
        "runGroundedGenerationExperienceSmoke.mjs",
    ),
    (
        "protected_playwright",
        "apps/nex-ae-web/scripts/runGroundedGenerationPlaywrightSmoke.mjs",
        "runGroundedGenerationPlaywrightSmoke",
    ),
    (
        "actual_ae_test",
        "scripts/smoke/run_ae_web_grounded_generation_playwright_postgres_smoke.py",
        'AE_DATABASE = "nex_ae_test"',
    ),
    (
        "actual_cx_test",
        "scripts/smoke/run_ae_web_grounded_generation_playwright_postgres_smoke.py",
        'CX_DATABASE = "nex_cx_test"',
    ),
    (
        "live_provider_evidence",
        "scripts/smoke/run_ae_web_grounded_generation_playwright_postgres_smoke.py",
        '"all_live_provider_capabilities_called"',
    ),
    (
        "quality_live_smoke",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_web_grounded_generation_playwright_postgres_smoke.py",
    ),
    (
        "quality_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s109_ae_web_grounded_generation_experience_closure.py",
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "1091_s109_ae_web_grounded_generation_experience_closure.md",
    ),
)

COMPONENT_TOKEN_NAMES = {
    "boundary_audit": ("same_origin_client",),
    "same_origin_generation_client": ("same_origin_client",),
    "bounded_lifecycle_workflow": ("bounded_workflow",),
    "authenticated_runtime_wiring": ("runtime_wiring",),
    "cancel_retry_recovery": ("recovery_actions", "cancel_wiring", "retry_wiring"),
    "verified_response_quality": ("verified_presentation",),
    "diagnostics_accessibility": (
        "diagnostics_projection",
        "deterministic_experience_smoke",
    ),
    "protected_browser_runtime": ("protected_playwright",),
    "actual_postgres_live_providers": (
        "actual_ae_test",
        "actual_cx_test",
        "live_provider_evidence",
    ),
    "quality_documentation": (
        "quality_live_smoke",
        "quality_closure",
        "docs_closure_index",
    ),
}


def run_s109_ae_web_grounded_generation_experience_closure(
    root: Path = ROOT,
    *,
    live_evidence: Mapping[str, Any] | None = None,
    contract_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]
    token_checks = [
        {"name": name, "path": path, "present": token in _read_text(root / path)}
        for name, path, token in TOKEN_CHECKS
    ]
    token_status = {item["name"]: item["present"] for item in token_checks}
    components = {
        name: all(token_status[token] for token in tokens)
        for name, tokens in COMPONENT_TOKEN_NAMES.items()
    }
    boundary = _safe_evidence(lambda: run_boundary(root))
    contract = (
        dict(contract_evidence)
        if contract_evidence is not None
        else _safe_evidence(lambda: _contract_evidence(root))
    )
    live = (
        dict(live_evidence)
        if live_evidence is not None
        else _safe_evidence(run_live)
    )
    boundary_summary = _mapping(boundary.get("summary"))
    boundary_decision = _mapping(boundary.get("decision"))
    live_checks = _mapping(live.get("checks"))
    database_identity = _mapping(live.get("database_identity"))
    provider = _mapping(live.get("provider_observation"))
    browser = _mapping(live.get("browser_observation"))
    persistence = _mapping(live.get("persistence_observation"))
    live_requested = os.environ.get(LIVE_SMOKE_ENV) == "1"
    live_executed = (
        live.get("status") == "PASS"
        and live.get("actual_postgres") is True
        and live.get("execution_state") == "EXECUTED"
        and live.get("evidence_mode") == "single_correlated_browser_request"
        and database_identity.get("ae")
        == {"database": "nex_ae_test", "role": "nex_ae_user"}
        and database_identity.get("cx")
        == {"database": "nex_cx_test", "role": "nex_cx_user"}
        and bool(live_checks)
        and all(live_checks.values())
        and browser.get("display_mode") == "VERIFIED_RESPONSE"
        and persistence.get("ae_status") == "COMPLETED"
        and persistence.get("retrieval_status") == "READY"
        and persistence.get("generation_status") == "COMPLETED"
        and persistence.get("job_status") == "SUCCEEDED"
        and all(
            _mapping(provider.get(capability)).get("model") == model
            and int(_mapping(provider.get(capability)).get("success_count") or 0)
            >= 1
            for capability, model in EXPECTED_MODELS.items()
        )
    )
    live_policy_satisfied = live_executed or (
        not live_requested and live.get("status") == "SKIPPED"
    )
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "boundary_audit_passed": boundary.get("status") == "PASS",
        "boundary_plan_completed": (
            boundary_summary.get("planned_slice_count") == 10
            and boundary_summary.get("gap_count") == 8
            and boundary_summary.get("resolved_gap_count") == 8
            and boundary_summary.get("open_gap_count") == 0
            and boundary.get("next_slice") == "1091"
        ),
        "all_components_closed": all(components.values()),
        "contract_tree_valid": contract.get("status") == "PASS",
        "protected_live_policy_satisfied": live_policy_satisfied,
        "service_ownership_preserved": (
            boundary_decision.get("experience_owner") == "nex-ae-web"
            and boundary_decision.get("orchestration_owner") == "nex-ae-api"
            and boundary_decision.get("grounded_generation_owner") == "nex-cx"
            and boundary_decision.get("provider_execution_owner") == "nex-mo"
        ),
        "same_origin_secret_boundary_preserved": (
            boundary_decision.get("browser_service_boundary")
            == "same_origin_nex_ae_api_only"
            and boundary_decision.get("browser_direct_cx_call_allowed") is False
            and boundary_decision.get("browser_direct_mo_call_allowed") is False
            and boundary_decision.get("browser_service_token_allowed") is False
        ),
        "verified_response_boundary_preserved": (
            boundary_decision.get("completion_content_source")
            == "ae_generated_response_endpoint"
            and boundary_decision.get("quality_source")
            == "ae_citation_quality_endpoint"
            and boundary_decision.get("artifact_handoff_after_verified_completion")
            is True
        ),
        "tiered_quality_cadence_preserved": (
            boundary_decision.get("quality_cadence")
            == {
                "slice_gate": "every_slice",
                "checkpoint_gate": "1086",
                "full_gate": "1091",
            }
        ),
        "schema_stability_preserved": boundary_decision.get("new_tables_expected")
        == 0,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1091",
        "slice_range": SLICE_RANGE,
        "requirement": "S109",
        "status": status,
        "failure_code": (
            None
            if status == "PASS"
            else "s109_ae_web_grounded_generation_experience_closure_failed"
        ),
        "closure_readiness": (
            "READY_FOR_S110"
            if status == "PASS" and live_executed
            else (
                "READY_WITH_PROTECTED_LIVE_PENDING"
                if status == "PASS"
                else "BLOCKED"
            )
        ),
        "feature_readiness": (
            "AE_WEB_GROUNDED_GENERATION_READY"
            if status == "PASS" and live_executed
            else (
                "REPOSITORY_READY_PROTECTED_LIVE_PENDING"
                if status == "PASS"
                else "INCOMPLETE"
            )
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "resolved_gap_count": int(boundary_summary.get("resolved_gap_count") or 0),
            "contract_schema_count": int(contract.get("schema_count") or 0),
            "contract_example_count": int(contract.get("example_count") or 0),
            "contract_negative_count": int(contract.get("negative_example_count") or 0),
            "live_check_count": len(live_checks) if live_executed else 0,
            "provider_capability_count": len(provider) if live_executed else 0,
            "missing_file_count": sum(not item["present"] for item in required_files),
            "missing_token_count": sum(not item["present"] for item in token_checks),
        },
        "components": components,
        "boundary_status": boundary.get("status"),
        "contract_status": contract.get("status"),
        "live_status": live.get("status"),
        "live_executed": live_executed,
        "live_evidence": live,
        "required_files": required_files,
        "token_checks": token_checks,
        "decision": _closure_decision(),
        "next_requirement": "S110",
    }


def _contract_evidence(root: Path) -> dict[str, Any]:
    result = validate_contract_tree(root / "contracts")
    return {
        "status": "PASS" if result.ok else "FAIL",
        "schema_count": result.schema_count,
        "example_count": result.example_count,
        "negative_example_count": result.negative_example_count,
        "openapi_count": result.openapi_count,
        "failure_count": len(result.failures),
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "ae_web_grounded_generation_experience",
        "browser_owner": "nex-ae-web",
        "orchestration_owner": "nex-ae-api",
        "retrieval_generation_owner": "nex-cx",
        "provider_execution_owner": "nex-mo",
        "browser_network_policy": "same_origin_ae_api_only",
        "verified_response_required": True,
        "citation_quality_required": True,
        "actual_test_targets": ["nex_ae_user@nex_ae_test", "nex_cx_user@nex_cx_test"],
        "live_provider_capabilities": sorted(EXPECTED_MODELS),
        "new_tables_added": [],
        "next_requirement_scope": "S110_to_be_confirmed",
    }


def _safe_evidence(builder: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    try:
        return dict(builder())
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": "evidence_builder_failed",
            "detail": exc.__class__.__name__,
        }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "s109_ae_web_grounded_generation_experience_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"gaps={summary.get('resolved_gap_count', 0)}/8 "
        f"live={str(evidence.get('live_status') or 'not-run').lower()} "
        f"live_checks={summary.get('live_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s109_ae_web_grounded_generation_experience_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
