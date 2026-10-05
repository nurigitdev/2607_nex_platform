#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from run_cx_current_chunk_candidate_postgres_smoke import (
    run_cx_current_chunk_candidate_postgres_smoke,
)
from run_cx_live_retrieval_provider_identity import (
    run_cx_live_retrieval_provider_identity,
)
from run_cx_permission_first_scope_hardening import (
    run_cx_permission_first_scope_hardening,
)
from run_cx_retrieval_confidence_acceptance import (
    run_cx_retrieval_confidence_acceptance,
)
from run_cx_retrieval_operations_observability import (
    run_cx_retrieval_operations_observability,
)
from run_cx_weighted_rrf_acceptance import run_cx_weighted_rrf_acceptance
from run_platform_permission_hybrid_retrieval_boundary import (
    run_platform_permission_hybrid_retrieval_boundary,
)
from run_s136_model_calibration_live import run_s136_model_calibration_live
from run_s136_permission_hybrid_live_postgres_smoke import (
    run_s136_permission_hybrid_live_postgres_smoke,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s136_permission_hybrid_retrieval_closure.v1"
CANONICAL_DOCUMENT = "docs/43_platform_permission_filtered_hybrid_retrieval.md"
RELEASE_PLAN = "docs/37_platform_mvp_integration_release_plan.md"
RUNBOOK = "docs/runbooks/platform_permission_filtered_hybrid_retrieval.md"
PROTECTED_DOCUMENT = "docs/slices/1360_cx_multisignal_calibrated_live_retrieval.md"
QUALITY_GATE = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s136_permission_hybrid_retrieval_closure.py"
RETRIEVAL_SCHEMA = (
    "contracts/schemas/service/nex_cx/retrieval_context_package.v1.schema.json"
)
READY_EXAMPLE = (
    "contracts/examples/retrieval/cx_retrieval_context_package.mock_success.json"
)
NO_ANSWER_EXAMPLE = (
    "contracts/examples/retrieval/cx_retrieval_context_package.no_answer.json"
)
TOKEN_NEGATIVE = (
    "contracts/tests/negative/retrieval/"
    "cx_retrieval_context_package.raw_token_leak.json"
)
CALIBRATION_SCHEMA = (
    "contracts/schemas/service/nex_cx/"
    "retrieval_confidence_calibration_profile.v1.schema.json"
)
CALIBRATION_EXAMPLE = (
    "contracts/examples/service/nex_cx/"
    "retrieval_confidence_calibration_profile.candidate.json"
)
EvidenceRunner = Callable[[], dict[str, Any]]
EVIDENCE_RUNNERS: tuple[tuple[str, EvidenceRunner], ...] = (
    ("boundary", run_platform_permission_hybrid_retrieval_boundary),
    ("permission", run_cx_permission_first_scope_hardening),
    ("current_chunk_postgres", lambda: run_cx_current_chunk_candidate_postgres_smoke({})),
    ("provider_identity", run_cx_live_retrieval_provider_identity),
    ("weighted_rrf", run_cx_weighted_rrf_acceptance),
    ("confidence", run_cx_retrieval_confidence_acceptance),
    ("operations", run_cx_retrieval_operations_observability),
    ("raw_score_calibration", lambda: run_s136_model_calibration_live({})),
    ("protected_live", lambda: run_s136_permission_hybrid_live_postgres_smoke({})),
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1352", "platform_permission_hybrid_retrieval_boundary"),
        ("1353", "cx_permission_first_scope_hardening"),
        ("1354", "cx_current_candidate_lineage"),
        ("1355", "cx_live_retrieval_provider_identity"),
        ("1356", "cx_weighted_rrf_acceptance"),
        ("1357", "cx_retrieval_confidence_semantics"),
        ("1358", "cx_retrieval_operations_evidence"),
        ("1359", "model_agnostic_confidence_calibration"),
        ("1360", "cx_multisignal_calibrated_live_retrieval"),
        ("1361", "s136_permission_hybrid_retrieval_closure"),
    )
)


def run_s136_permission_hybrid_retrieval_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    contract_artifacts = (
        RETRIEVAL_SCHEMA,
        READY_EXAMPLE,
        NO_ANSWER_EXAMPLE,
        TOKEN_NEGATIVE,
        CALIBRATION_SCHEMA,
        CALIBRATION_EXAMPLE,
    )
    required_documents = (*SLICE_DOCUMENTS, CANONICAL_DOCUMENT, RELEASE_PLAN, RUNBOOK)
    document_presence = {
        path: (root / path).is_file() for path in required_documents
    }
    contract_presence = {
        path: (root / path).is_file() for path in contract_artifacts
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
    retrieval_schema = _read_text(root / RETRIEVAL_SCHEMA)
    examples_index = _read_text(root / "contracts/examples/index.json")
    negative_index = _read_text(root / "contracts/tests/negative/index.json")

    checks = {
        "six_deterministic_components_pass": all(
            statuses.get(name) == "PASS"
            for name in (
                "boundary",
                "permission",
                "provider_identity",
                "weighted_rrf",
                "confidence",
                "operations",
            )
        ),
        "three_protected_components_are_opt_in": all(
            statuses.get(name) == "SKIPPED"
            and bool(_mapping(evidence.get(name)).get("skip_reason"))
            for name in (
                "current_chunk_postgres",
                "raw_score_calibration",
                "protected_live",
            )
        ),
        "all_slice_canonical_and_runbook_documents_present": all(
            document_presence.values()
        ),
        "contract_artifacts_present": all(contract_presence.values()),
        "closure_registered_once_in_full_gate": (
            quality_gate.count(CLOSURE_RUNNER) == 1
        ),
        "retrieval_contract_examples_indexed": (
            READY_EXAMPLE.removeprefix("contracts/") in examples_index
            and NO_ANSWER_EXAMPLE.removeprefix("contracts/") in examples_index
            and CALIBRATION_EXAMPLE.removeprefix("contracts/") in examples_index
            and TOKEN_NEGATIVE.removeprefix("contracts/") in negative_index
        ),
        "retrieval_contract_is_owner_calibration_and_state_hardened": all(
            token in retrieval_schema
            for token in (
                '"tenant_ref_type"',
                '"owner_subject_ref_type"',
                '"persistence_payload_policy"',
                '"cx_retrieval_confidence_multisignal_v1"',
                '"calibration_profile_hash"',
                '"weighted_rrf_vector_bm25_v1"',
                '"LOW_CONFIDENCE"',
                '"NO_ANSWER"',
            )
        ),
        "actual_protected_execution_recorded": all(
            token in protected
            for token in (
                "protected checks: `17/17 PASS`",
                "20 calibration queries",
                "false-READY rate: `0.0`",
                "provider calls: embedding `24`, reranking `22`, failures `0`",
                "restart readback: all `23` hash-only retrieval packages",
                "cleanup: source, content, vector, retrieval, and event fixtures absent",
            )
        ),
        "runbook_complete_and_secret_free": (
            all(
                marker in runbook
                for marker in (
                    "## Preconditions",
                    "## Protected Command",
                    "## Expected Evidence",
                    "## Calibration And Model Changes",
                    "## Failure Triage",
                    "## Cleanup Verification",
                    "## Rollback And Fail-Closed",
                    "## Privacy And Secret Handling",
                    "## S137 Handoff",
                )
            )
            and not any(
                marker in runbook.lower()
                for marker in (
                    "postgresql+psycopg://",
                    "postgresql://",
                    "password=",
                    "api-key=",
                    "authorization: bearer",
                    "begin private key",
                )
            )
        ),
        "model_change_and_fail_closed_controls_frozen": all(
            token in runbook
            for token in (
                "retires the old profile",
                "must remain `LOW_CONFIDENCE`",
                "Do not lower the threshold to make the smoke pass",
                "Do not fall back to unfiltered search",
            )
        ),
        "canonical_marks_s136_complete": all(
            token in canonical
            for token in (
                "Status: S136 complete",
                "## Slice 1361 Closure",
                "Completion signal: Met.",
                "## S137 Handoff",
            )
        ),
        "release_plan_marks_s136_met_and_s137_active": all(
            token in release_plan
            for token in (
                "S136 completion signal: Met.",
                "S137 is the next active requirement",
            )
        ),
        "s137_handoff_preserves_retrieval_ownership": all(
            token in canonical
            for token in (
                "S137 is the next active requirement",
                "owner-scoped retrieval package",
                "S137 owns generation, citation validation, repair, and artifact lifecycle",
                "S136 does not call the generation provider",
            )
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1361",
        "slice_range": "1352-1361",
        "requirement": "S136",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "s136_permission_hybrid_retrieval_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S137" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "evidence_statuses": statuses,
        "required_documents": document_presence,
        "contract_artifacts": contract_presence,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(value == "PASS" for value in statuses.values()),
            "protected_skip_count": sum(value == "SKIPPED" for value in statuses.values()),
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "contract_artifact_count": sum(contract_presence.values()),
            "decision_state_count": 3 if passed else 0,
            "candidate_channel_count": 2 if passed else 0,
        },
        "decision": {
            "completion_signal_met": passed,
            "actual_protected_database_and_provider_evidence_recorded": passed,
            "closure_database_or_provider_mutation_performed": False,
            "oa_claims_remain_owner_authority": True,
            "cx_remains_retrieval_and_calibration_owner": True,
            "generation_provider_required": False,
            "full_gate_registered": quality_gate.count(CLOSURE_RUNNER) == 1,
            "next_requirement": "S137" if passed else "blocked",
            "next_requirement_scope": (
                "grounded_generation_repair_and_artifact_lifecycle_e2e"
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
            "s136_permission_hybrid_retrieval_closure=fail "
            f"checks={len(evidence.get('failed_checks') or [])}"
        )
    summary = _mapping(evidence.get("summary"))
    decision = _mapping(evidence.get("decision"))
    return (
        "s136_permission_hybrid_retrieval_closure=pass "
        f"evidence={summary.get('passed_evidence_count', 0)}+"
        f"{summary.get('protected_skip_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"states={summary.get('decision_state_count', 0)} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s136_permission_hybrid_retrieval_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
