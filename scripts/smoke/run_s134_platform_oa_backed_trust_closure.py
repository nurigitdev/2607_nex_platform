#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from run_platform_oa_backed_trust_boundary import (
    run_platform_oa_backed_trust_boundary,
)
from run_platform_oa_backed_trust_postgres_smoke import run_smoke as run_postgres_smoke
from run_platform_trust_evidence import sample_platform_trust_evidence
from run_platform_trust_operations_hardening import (
    run_platform_trust_operations_hardening,
)
from run_platform_trust_restart_plan import run_platform_trust_restart_plan
from run_platform_trust_scope_policy import run_platform_trust_scope_policy


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s134_platform_oa_backed_trust_closure.v1"
CANONICAL_DOCUMENT = "docs/41_platform_oa_backed_trust_integration.md"
RELEASE_PLAN = "docs/37_platform_mvp_integration_release_plan.md"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s134_platform_oa_backed_trust_closure.py"
PROTECTED_DOCUMENT = "docs/slices/1339_platform_oa_backed_trust_postgres_smoke.md"
RUNBOOK = "docs/runbooks/platform_oa_backed_trust_operations.md"
EvidenceRunner = Callable[[], dict[str, Any]]
EVIDENCE_RUNNERS: tuple[tuple[str, EvidenceRunner], ...] = (
    ("boundary", run_platform_oa_backed_trust_boundary),
    ("trust", sample_platform_trust_evidence),
    ("scope", run_platform_trust_scope_policy),
    ("restart", run_platform_trust_restart_plan),
    ("postgres", lambda: run_postgres_smoke({})),
    ("operations", run_platform_trust_operations_hardening),
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1332", "platform_oa_backed_trust_boundary"),
        ("1333", "oa_signed_internal_admission"),
        ("1334", "oa_test_file_signing_custody"),
        ("1335", "ae_oa_signed_login_activation"),
        ("1336", "platform_trust_evidence_checkpoint"),
        ("1337", "platform_trust_scope_propagation"),
        ("1338", "platform_trust_restart_orchestration"),
        ("1339", "platform_oa_backed_trust_postgres_smoke"),
        ("1340", "platform_trust_contract_privacy_runbook"),
        ("1341", "s134_platform_oa_backed_trust_closure"),
    )
)


def run_s134_platform_oa_backed_trust_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_documents = (*SLICE_DOCUMENTS, CANONICAL_DOCUMENT, RELEASE_PLAN, RUNBOOK)
    document_presence = {
        path: (root / path).is_file() for path in required_documents
    }
    evidence = _run_evidence(root) if all(document_presence.values()) else {}
    statuses = {name: item.get("status") for name, item in evidence.items()}
    canonical = _normalized_text(root / CANONICAL_DOCUMENT)
    release_plan = _normalized_text(root / RELEASE_PLAN)
    protected_document = _normalized_text(root / PROTECTED_DOCUMENT)
    runbook = _normalized_text(root / RUNBOOK)
    quality_gate = _read_text(root / QUALITY_GATE_PATH)
    trust = _mapping(evidence.get("trust"))
    trust_summary = _mapping(trust.get("summary"))
    scope = _mapping(evidence.get("scope"))
    restart = _mapping(evidence.get("restart"))
    operations = _mapping(evidence.get("operations"))
    operations_summary = _mapping(operations.get("summary"))

    checks = {
        "five_deterministic_components_pass": all(
            statuses.get(name) == "PASS"
            for name in ("boundary", "trust", "scope", "restart", "operations")
        ),
        "protected_postgres_component_is_opt_in": (
            statuses.get("postgres") == "SKIPPED"
            and bool(evidence.get("postgres", {}).get("skip_reason"))
        ),
        "all_slice_canonical_and_runbook_documents_present": all(
            document_presence.values()
        ),
        "closure_registered_once_in_full_gate": quality_gate.count(CLOSURE_RUNNER)
        == 1,
        "trust_chain_and_denials_complete": (
            trust_summary.get("passed_hop_count") == 5
            and trust_summary.get("hop_count") == 5
            and trust_summary.get("passed_denial_count") == 4
            and trust_summary.get("denial_count") == 4
        ),
        "restart_and_database_evidence_complete": (
            trust_summary.get("restart_generation_count") == 2
            and trust_summary.get("database_service_count") == 5
            and trust_summary.get("cleanup_residue_count") == 0
            and restart.get("generation_count") == 2
            and restart.get("service_count") == 5
            and restart.get("checkpoint_count") == 4
        ),
        "least_privilege_scope_policy_complete": (
            scope.get("grant_count") == 8
            and scope.get("service_count") == 4
            and scope.get("audience_count") == 4
        ),
        "operations_hardening_complete": (
            operations_summary.get("check_count") == 11
            and operations_summary.get("passed_check_count") == 11
            and operations_summary.get("active_claim_service_count") == 4
            and operations_summary.get("contract_artifact_count") == 6
        ),
        "actual_protected_execution_recorded": all(
            token in protected_document
            for token in (
                "actual five-database/two-generation",
                "passed five of five trust hops",
                "four of four denial scenarios",
                "zero S134 tenants",
                "remote embedding, reranking, and generation providers were not contacted",
            )
        ),
        "canonical_marks_s134_complete": all(
            token in canonical
            for token in (
                "Status: S134 complete",
                "Completion signal: Met.",
                "## Slice 1341 Closure",
                "## S135 Handoff",
            )
        ),
        "release_plan_marks_s134_met_and_s135_active": all(
            token in release_plan
            for token in (
                "S134 completion signal: Met.",
                "S135 is the next active requirement",
            )
        ),
        "privacy_and_secret_boundaries_remain_closed": all(
            token in canonical
            for token in (
                "No raw password, client secret, session id, service token, private key, or database URL",
                "zero seeded-row or temporary-key residue",
            )
        ),
        "operator_fail_closed_controls_recorded": all(
            token in runbook
            for token in (
                "Keep consumer rollout at `SIGNED_ONLY`",
                "must return `503`",
                "must return `401` or `403`",
            )
        ),
        "remote_model_providers_remain_outside_scope": (
            "providers are outside S134" in runbook
            and "Remote model providers are outside S134" in canonical
        ),
        "s135_handoff_preserves_trust_ownership": all(
            token in canonical
            for token in (
                "validated OA session owner context",
                "signed service identity",
                "authenticated document upload-to-index durability",
                "must not reopen identity, signing, or cross-service trust ownership",
            )
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1341",
        "slice_range": "1332-1341",
        "requirement": "S134",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s134_platform_oa_backed_trust_closure_failed",
        "closure_readiness": "READY_FOR_S135" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "evidence_statuses": statuses,
        "required_documents": document_presence,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(value == "PASS" for value in statuses.values()),
            "protected_skip_count": sum(
                value == "SKIPPED" for value in statuses.values()
            ),
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "service_count": 5 if passed else 0,
            "trust_hop_count": int(trust_summary.get("hop_count") or 0),
            "denial_count": int(trust_summary.get("denial_count") or 0),
            "restart_generation_count": int(
                trust_summary.get("restart_generation_count") or 0
            ),
            "database_count": int(trust_summary.get("database_service_count") or 0),
            "operations_check_count": int(operations_summary.get("check_count") or 0),
        },
        "decision": {
            "completion_signal_met": passed,
            "actual_protected_database_evidence_recorded": passed,
            "closure_database_or_provider_mutation_performed": False,
            "oa_remains_trust_authority": True,
            "service_local_database_ownership_retained": True,
            "remote_provider_required": False,
            "full_gate_registered": quality_gate.count(CLOSURE_RUNNER) == 1,
            "next_requirement": "S135" if passed else "blocked",
            "next_requirement_scope": (
                "authenticated_document_upload_to_index_durable_journey"
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


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "s134_platform_oa_backed_trust_closure=fail "
            f"checks={len(evidence.get('failed_checks') or [])}"
        )
    summary = evidence.get("summary") or {}
    return (
        "s134_platform_oa_backed_trust_closure=pass "
        f"evidence={summary.get('passed_evidence_count', 0)}+"
        f"{summary.get('protected_skip_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"hops={summary.get('trust_hop_count', 0)} "
        f"denials={summary.get('denial_count', 0)} "
        f"next={evidence.get('decision', {}).get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s134_platform_oa_backed_trust_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
