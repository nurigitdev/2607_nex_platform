#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from run_ae_grounded_artifact_admission import (
    run_ae_grounded_artifact_admission,
)
from run_ae_grounded_artifact_recovery_access import (
    run_ae_grounded_artifact_recovery_access,
)
from run_ae_grounded_response_lineage import run_ae_grounded_response_lineage
from run_cx_grounded_generation_runtime_composition import (
    run_cx_grounded_generation_runtime_composition,
)
from run_cx_grounding_repair_lineage import run_cx_grounding_repair_lineage
from run_cx_retrieval_package_materialization import (
    run_cx_retrieval_package_materialization,
)
from run_platform_grounded_generation_artifact_boundary import (
    run_platform_grounded_generation_artifact_boundary,
)
from run_platform_grounded_generation_artifact_e2e import (
    run_platform_grounded_generation_artifact_e2e,
)
from run_platform_grounded_generation_artifact_live_postgres_smoke import (
    run_platform_grounded_generation_artifact_live_postgres_smoke,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s137_grounded_generation_artifact_closure.v1"
CANONICAL_DOCUMENT = "docs/44_platform_grounded_generation_artifact_e2e.md"
RELEASE_PLAN = "docs/37_platform_mvp_integration_release_plan.md"
RUNBOOK = "docs/runbooks/platform_grounded_generation_artifact_e2e.md"
PROTECTED_DOCUMENT = (
    "docs/slices/1370_platform_grounded_generation_artifact_live_postgres.md"
)
QUALITY_GATE = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s137_grounded_generation_artifact_closure.py"
SECRET_PATTERNS = (
    r"postgres(?:ql)?(?:\+[^:]*)?://",
    r"\b(?:password|api[_ -]?key)\s*[:=]\s*\S+",
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    r"begin (?:rsa |ec |openssh )?private key",
)
CONTRACT_ARTIFACTS = (
    "contracts/schemas/generation/cx_grounded_generation_lineage.v1.schema.json",
    "contracts/examples/generation/cx_grounded_generation_lineage.repaired.json",
    "contracts/tests/negative/generation/"
    "cx_grounded_generation_lineage.private_evidence.json",
    "contracts/schemas/service/nex_ae_api/"
    "grounded_artifact_admission.v1.schema.json",
    "contracts/examples/generation/"
    "ae_grounded_artifact_admission.enqueued.json",
    "contracts/tests/negative/generation/"
    "ae_grounded_artifact_admission.content_leak.json",
)
EvidenceRunner = Callable[[], dict[str, Any]]
EVIDENCE_RUNNERS: tuple[tuple[str, EvidenceRunner], ...] = (
    ("boundary", run_platform_grounded_generation_artifact_boundary),
    ("materialization", run_cx_retrieval_package_materialization),
    ("runtime", run_cx_grounded_generation_runtime_composition),
    ("repair", run_cx_grounding_repair_lineage),
    ("ae_response", run_ae_grounded_response_lineage),
    ("ae_artifact", run_ae_grounded_artifact_admission),
    ("ae_recovery", run_ae_grounded_artifact_recovery_access),
    ("deterministic_e2e", run_platform_grounded_generation_artifact_e2e),
    (
        "protected_live",
        lambda: run_platform_grounded_generation_artifact_live_postgres_smoke({}),
    ),
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1362", "platform_grounded_generation_artifact_boundary"),
        ("1363", "cx_retrieval_package_materialization"),
        ("1364", "cx_grounded_generation_runtime_composition"),
        ("1365", "cx_citation_repair_lineage_binding"),
        ("1366", "ae_generated_response_grounding_lineage"),
        ("1367", "ae_grounded_artifact_admission"),
        ("1368", "ae_grounded_artifact_recovery_access"),
        ("1369", "platform_grounded_generation_artifact_deterministic_e2e"),
        ("1370", "platform_grounded_generation_artifact_live_postgres"),
        ("1371", "s137_grounded_generation_artifact_closure"),
    )
)


def run_s137_grounded_generation_artifact_closure(
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
    openapi = _read_text(root / "contracts/openapi/nex-ae-api.openapi.yaml")

    deterministic_names = tuple(
        name for name, _runner in EVIDENCE_RUNNERS if name != "protected_live"
    )
    checks = {
        "eight_deterministic_components_pass": all(
            statuses.get(name) == "PASS" for name in deterministic_names
        ),
        "protected_live_component_is_opt_in": (
            statuses.get("protected_live") == "SKIPPED"
            and bool(_mapping(evidence.get("protected_live")).get("skip_reason"))
        ),
        "all_slice_canonical_and_runbook_documents_present": all(
            document_presence.values()
        ),
        "contract_artifacts_present": all(contract_presence.values()),
        "closure_registered_once_in_full_gate": (
            quality_gate.count(CLOSURE_RUNNER) == 1
        ),
        "all_s137_evidence_registered_once_in_full_gate": all(
            quality_gate.count(Path(runner.__module__).name + ".py") == 1
            for name, runner in EVIDENCE_RUNNERS
            if name not in {"protected_live"}
            and runner.__module__ != "__main__"
        ) and quality_gate.count(
            "run_platform_grounded_generation_artifact_live_postgres_smoke.py"
        ) == 1,
        "contract_examples_and_negatives_indexed": all(
            path.removeprefix("contracts/")
            in (negative_index if "/tests/negative/" in path else examples_index)
            for path in CONTRACT_ARTIFACTS
            if "/examples/" in path or "/tests/negative/" in path
        ),
        "owner_scoped_artifact_openapi_published": all(
            marker in openapi
            for marker in (
                "/api/v1/generated-responses/{response_id}/artifacts:",
                "GroundedArtifactAdmission",
                '"404":',
                '"503":',
            )
        ),
        "actual_protected_execution_recorded": all(
            token in protected
            for token in (
                "checks: `8/8 PASS`",
                "actual databases: `nex_ae_test` and `nex_cx_test`",
                "live capabilities: embedding, reranking, and generation (`3/3`)",
                "cleanup: AE and CX journey rows `0`; temporary artifact storage absent",
            )
        ),
        "owner_private_structured_draft_boundary_frozen": all(
            token in canonical
            for token in (
                "owner-private storage decision",
                "opaque storage reference",
                "verify size, hash, JSON schema, generation id, and draft id",
                "neither AE nor AG may resolve the CX storage URI directly",
            )
        ),
        "runbook_complete_and_secret_free": (
            all(
                marker in runbook
                for marker in (
                    "## Preconditions",
                    "## Protected Command",
                    "## Expected Evidence",
                    "## Structured Draft Storage",
                    "## Failure Triage",
                    "## Cleanup Verification",
                    "## Rollback And Fail-Closed",
                    "## Privacy And Secret Handling",
                    "## S138 Handoff",
                )
            )
            and not _contains_secret(runbook)
        ),
        "failure_cleanup_and_privacy_controls_frozen": all(
            token in runbook
            for token in (
                "Do not bypass LOW_CONFIDENCE or NO_ANSWER",
                "Do not retry citation repair more than once",
                "must remain owner-scoped and fail closed",
                "must not contain prompt, source, evidence, generated, or draft text",
            )
        ),
        "canonical_marks_s137_complete": all(
            token in canonical
            for token in (
                "Status: S137 complete.",
                "## Slice 1371 Closure",
                "Completion signal: Met.",
                "## S138 Handoff",
            )
        ),
        "release_plan_marks_s137_met_and_s138_active": all(
            token in release_plan
            for token in (
                "S137 completion signal: Met.",
                "S138 is the next active requirement",
            )
        ),
        "s138_handoff_preserves_service_ownership": all(
            token in canonical
            for token in (
                "metadata-safe trace and operations projections only",
                "may not read OA, CX, AE, or MO databases",
                "service APIs",
            )
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1371",
        "slice_range": "1362-1371",
        "requirement": "S137",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None
            if passed
            else "s137_grounded_generation_artifact_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S138" if passed else "BLOCKED",
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
            "scenario_count": 4 if passed else 0,
            "provider_capability_count": 3 if passed else 0,
            "database_count": 2 if passed else 0,
            "contract_artifact_count": sum(contract_presence.values()),
        },
        "decision": {
            "completion_signal_met": passed,
            "actual_protected_database_and_provider_evidence_recorded": passed,
            "closure_database_or_provider_mutation_performed": False,
            "oa_claims_remain_owner_authority": True,
            "cx_remains_retrieval_generation_and_private_draft_owner": True,
            "ae_remains_response_and_artifact_owner": True,
            "mo_remains_provider_execution_owner": True,
            "full_gate_registered": quality_gate.count(CLOSURE_RUNNER) == 1,
            "next_requirement": "S138" if passed else "blocked",
            "next_requirement_scope": (
                "ag_cross_service_trace_audit_and_operations_e2e"
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
            "s137_grounded_generation_artifact_closure=fail "
            f"checks={len(result.get('failed_checks') or [])}"
        )
    summary = _mapping(result.get("summary"))
    decision = _mapping(result.get("decision"))
    return (
        "s137_grounded_generation_artifact_closure=pass "
        f"evidence={summary.get('passed_evidence_count', 0)}+"
        f"{summary.get('protected_skip_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"scenarios={summary.get('scenario_count', 0)} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_s137_grounded_generation_artifact_closure()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
