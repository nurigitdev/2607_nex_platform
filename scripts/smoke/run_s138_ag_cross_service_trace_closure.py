#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from run_ae_trace_projection_contract import run_ae_trace_projection_contract
from run_ag_cross_service_trace_aggregation_contract import (
    run_ag_cross_service_trace_aggregation_contract,
)
from run_ag_cross_service_trace_deterministic_e2e import (
    run_ag_cross_service_trace_deterministic_e2e,
)
from run_ag_cross_service_trace_operations_contract import (
    run_ag_cross_service_trace_operations_contract,
)
from run_cx_trace_projection_contract import run_cx_trace_projection_contract
from run_oa_mo_trace_projection_contract import run_oa_mo_trace_projection_contract
from run_platform_ag_cross_service_trace_boundary import (
    run_platform_ag_cross_service_trace_boundary,
)
from run_platform_ag_trace_postgres_smoke import (
    run_platform_ag_trace_postgres_smoke,
)
from run_platform_trace_envelope_contract import run_platform_trace_envelope_contract


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s138_ag_cross_service_trace_closure.v1"
CANONICAL_DOCUMENT = "docs/45_platform_ag_cross_service_trace_operations_e2e.md"
RELEASE_PLAN = "docs/37_platform_mvp_integration_release_plan.md"
RUNBOOK = "docs/runbooks/platform_ag_cross_service_trace_operations.md"
PROTECTED_DOCUMENT = "docs/slices/1380_platform_ag_trace_postgresql_smoke.md"
QUALITY_GATE = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s138_ag_cross_service_trace_closure.py"
SECRET_PATTERNS = (
    r"postgres(?:ql)?(?:\+[^:]*)?://",
    r"\b(?:password|api[_ -]?key)\s*[:=]\s*\S+",
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    r"begin (?:rsa |ec |openssh )?private key",
)
CONTRACT_ARTIFACTS = (
    "contracts/schemas/common/cross_service_trace_stage.v1.schema.json",
    "contracts/schemas/common/service_cross_service_trace_projection.v1.schema.json",
    "contracts/schemas/service/nex_ag/cross_service_trace_e2e.v1.schema.json",
    "contracts/examples/common/cross_service_trace_stage.generation.json",
    "contracts/examples/operations/ag_cross_service_trace_e2e.ready.json",
    "contracts/examples/operations/cx_cross_service_trace_projection.ready.json",
    "contracts/tests/negative/common/cross_service_trace_stage.prompt_leak.json",
    "contracts/tests/negative/operations/ag_cross_service_trace_e2e.private_stage.json",
    "contracts/tests/negative/operations/mo_cross_service_trace_projection.provider_url.json",
)
EvidenceRunner = Callable[[], dict[str, Any]]
EVIDENCE_RUNNERS: tuple[tuple[str, EvidenceRunner], ...] = (
    ("boundary", run_platform_ag_cross_service_trace_boundary),
    ("envelope", run_platform_trace_envelope_contract),
    ("cx_projection", run_cx_trace_projection_contract),
    ("ae_projection", run_ae_trace_projection_contract),
    ("oa_mo_projection", run_oa_mo_trace_projection_contract),
    ("ag_aggregation", run_ag_cross_service_trace_aggregation_contract),
    ("ag_operations", run_ag_cross_service_trace_operations_contract),
    ("deterministic_e2e", run_ag_cross_service_trace_deterministic_e2e),
    ("protected_postgres", lambda: run_platform_ag_trace_postgres_smoke({})),
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1372", "platform_ag_cross_service_trace_boundary"),
        ("1373", "cross_service_trace_envelope_contract"),
        ("1374", "cx_admin_trace_projection"),
        ("1375", "ae_trace_projection"),
        ("1376", "oa_mo_trace_projections"),
        ("1377", "ag_cross_service_trace_aggregation"),
        ("1378", "ag_cross_service_trace_operations"),
        ("1379", "ag_cross_service_trace_deterministic_e2e"),
        ("1380", "platform_ag_trace_postgresql_smoke"),
        ("1381", "s138_ag_cross_service_trace_closure"),
    )
)


def run_s138_ag_cross_service_trace_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_documents = (*SLICE_DOCUMENTS, CANONICAL_DOCUMENT, RELEASE_PLAN, RUNBOOK)
    document_presence = {
        path: (root / path).is_file() for path in required_documents
    }
    contract_presence = {
        path: (root / path).is_file() for path in CONTRACT_ARTIFACTS
    }
    evidence = (
        _run_evidence(root)
        if all(document_presence.values()) and all(contract_presence.values())
        else {}
    )
    statuses = {name: item.get("status") for name, item in evidence.items()}
    canonical = _normalized_text(root / CANONICAL_DOCUMENT)
    release_plan = _normalized_text(root / RELEASE_PLAN)
    runbook = _normalized_text(root / RUNBOOK)
    protected = _normalized_text(root / PROTECTED_DOCUMENT)
    quality_gate = _read_text(root / QUALITY_GATE)
    examples_index = _read_text(root / "contracts/examples/index.json")
    negative_index = _read_text(root / "contracts/tests/negative/index.json")
    ag_openapi = _read_text(root / "contracts/openapi/nex-ag.openapi.yaml")

    deterministic_names = tuple(
        name for name, _runner in EVIDENCE_RUNNERS if name != "protected_postgres"
    )
    checks = {
        "eight_deterministic_components_pass": all(
            statuses.get(name) == "PASS" for name in deterministic_names
        ),
        "protected_postgres_component_is_opt_in": (
            statuses.get("protected_postgres") == "SKIPPED"
            and bool(_mapping(evidence.get("protected_postgres")).get("skip_reason"))
        ),
        "all_slice_canonical_and_runbook_documents_present": all(
            document_presence.values()
        ),
        "contract_artifacts_present": all(contract_presence.values()),
        "closure_registered_once_in_full_gate": quality_gate.count(CLOSURE_RUNNER)
        == 1,
        "all_s138_evidence_registered_once_in_full_gate": all(
            quality_gate.count(Path(runner.__module__).name + ".py") == 1
            for name, runner in EVIDENCE_RUNNERS
            if name != "protected_postgres" and runner.__module__ != "__main__"
        )
        and quality_gate.count("run_platform_ag_trace_postgres_smoke.py") == 1,
        "contract_examples_and_negatives_indexed": all(
            path.removeprefix("contracts/")
            in (negative_index if "/tests/negative/" in path else examples_index)
            for path in CONTRACT_ARTIFACTS
            if "/examples/" in path or "/tests/negative/" in path
        ),
        "ag_operations_openapi_published": all(
            marker in ag_openapi
            for marker in (
                "/admin/v1/operations/traces/{trace_id}:",
                "schemas/service/nex_ag/cross_service_trace_e2e.v1.schema.json",
                '"401":',
                '"503":',
            )
        ),
        "actual_five_database_execution_recorded": all(
            token in protected
            for token in (
                "checks=9/9 services=5 families=8 residue=0 next=1381",
                "`94` migrations were current",
                "direct cross-database reads remained zero",
                "cleanup residue was zero in every database",
            )
        ),
        "service_api_only_privacy_boundary_frozen": all(
            token in canonical
            for token in (
                "AG must not read another service's database",
                "private_payload_included=false",
                "typed HTTP clients for all four source-service trace APIs",
            )
        ),
        "runbook_complete_and_secret_free": (
            all(
                marker in runbook
                for marker in (
                    "## Preconditions",
                    "## Protected Command",
                    "## Expected Evidence",
                    "## Source Failure Triage",
                    "## Audit And Restart Verification",
                    "## Cleanup Verification",
                    "## Rollback And Fail-Closed",
                    "## Privacy And Secret Handling",
                    "## S139 Handoff",
                )
            )
            and not _contains_secret(runbook)
        ),
        "partial_failure_and_access_controls_frozen": all(
            token in runbook
            for token in (
                "Do not replace an unavailable source with a cross-service database read",
                "Healthy source stages remain available",
                "Artifact preview and download access must emit durable metadata-only audit",
                "must fail closed",
            )
        ),
        "canonical_marks_s138_complete": all(
            token in canonical
            for token in (
                "Status: S138 complete.",
                "## Slice 1381 Closure",
                "Completion signal: Met.",
                "## S139 Handoff",
            )
        ),
        "release_plan_marks_s138_met_and_s139_active": all(
            token in release_plan
            for token in (
                "S138 completion signal: Met.",
                "S139 is the next active requirement",
            )
        ),
        "s139_handoff_preserves_browser_boundary": all(
            token in canonical
            for token in (
                "Korean-default Playwright acceptance",
                "may not consume AG database rows",
                "service-private audit payload",
            )
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1381",
        "slice_range": "1372-1381",
        "requirement": "S138",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "s138_ag_trace_closure_failed",
        "closure_readiness": "READY_FOR_S139" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "evidence_statuses": statuses,
        "required_documents": document_presence,
        "contract_artifacts": contract_presence,
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
            "stage_family_count": 8 if passed else 0,
            "source_service_count": 5 if passed else 0,
            "database_count": 5 if passed else 0,
            "contract_artifact_count": sum(contract_presence.values()),
        },
        "decision": {
            "completion_signal_met": passed,
            "actual_protected_five_database_evidence_recorded": passed,
            "closure_database_or_provider_mutation_performed": False,
            "service_api_only_boundary_preserved": True,
            "private_payload_projection_allowed": False,
            "remote_provider_reexecution_required": False,
            "full_gate_registered": quality_gate.count(CLOSURE_RUNNER) == 1,
            "next_requirement": "S139" if passed else "blocked",
            "next_requirement_scope": (
                "ae_web_korean_default_playwright_golden_journey_acceptance"
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
            "s138_ag_cross_service_trace_closure=fail "
            f"checks={len(result.get('failed_checks') or [])}"
        )
    summary = _mapping(result.get("summary"))
    decision = _mapping(result.get("decision"))
    return (
        "s138_ag_cross_service_trace_closure=pass "
        f"evidence={summary.get('passed_evidence_count', 0)}+"
        f"{summary.get('protected_skip_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"families={summary.get('stage_family_count', 0)} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_s138_ag_cross_service_trace_closure()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
