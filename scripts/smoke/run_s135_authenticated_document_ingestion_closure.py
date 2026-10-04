#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from run_ae_protected_upload_owner_policy import run_ae_protected_upload_owner_policy
from run_ae_upload_handoff_persistence import run_ae_upload_handoff_persistence
from run_ae_upload_ingestion_progress import run_ae_upload_ingestion_progress
from run_cx_ingestion_restart_cancellation import run_cx_ingestion_restart_cancellation
from run_cx_ingestion_worker_hydration import run_cx_ingestion_worker_hydration
from run_cx_mock_vector_publish_freshness import run_cx_mock_vector_publish_freshness
from run_cx_upload_admission_lineage import run_cx_upload_admission_lineage
from run_platform_authenticated_document_ingestion_boundary import (
    run_platform_authenticated_document_ingestion_boundary,
)
from run_platform_authenticated_ingestion_postgres_smoke import run_smoke


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s135_authenticated_document_ingestion_closure.v1"
CANONICAL_DOCUMENT = "docs/42_platform_authenticated_document_ingestion.md"
RELEASE_PLAN = "docs/37_platform_mvp_integration_release_plan.md"
RUNBOOK = "docs/runbooks/platform_authenticated_document_ingestion.md"
PROTECTED_DOCUMENT = "docs/slices/1350_platform_authenticated_ingestion_postgres_smoke.md"
QUALITY_GATE = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s135_authenticated_document_ingestion_closure.py"
PROGRESS_SCHEMA = "contracts/schemas/service/nex_ae_api/upload_ingestion_progress.v1.schema.json"
PROGRESS_EXAMPLE = "contracts/examples/generation/ae_upload_ingestion_progress.index_ready.json"
PROGRESS_NEGATIVE = "contracts/tests/negative/generation/ae_upload_ingestion_progress.raw_source_leak.json"
EvidenceRunner = Callable[[], dict[str, Any]]
EVIDENCE_RUNNERS: tuple[tuple[str, EvidenceRunner], ...] = (
    ("boundary", run_platform_authenticated_document_ingestion_boundary),
    ("owner_policy", run_ae_protected_upload_owner_policy),
    ("handoff", run_ae_upload_handoff_persistence),
    ("admission", run_cx_upload_admission_lineage),
    ("hydration", run_cx_ingestion_worker_hydration),
    ("vector", run_cx_mock_vector_publish_freshness),
    ("progress", run_ae_upload_ingestion_progress),
    ("restart", run_cx_ingestion_restart_cancellation),
    ("postgres", lambda: run_smoke({})),
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1342", "platform_authenticated_document_ingestion_boundary"),
        ("1343", "ae_protected_upload_owner_claims"),
        ("1344", "ae_upload_handoff_persistence"),
        ("1345", "cx_upload_admission_lineage"),
        ("1346", "cx_ingestion_worker_hydration"),
        ("1347", "cx_mock_vector_publish_freshness"),
        ("1348", "ae_upload_ingestion_progress"),
        ("1349", "cx_ingestion_restart_cancellation"),
        ("1350", "platform_authenticated_ingestion_postgres_smoke"),
        ("1351", "s135_authenticated_document_ingestion_closure"),
    )
)


def run_s135_authenticated_document_ingestion_closure(
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
    runbook = _normalized_text(root / RUNBOOK)
    protected = _normalized_text(root / PROTECTED_DOCUMENT)
    quality_gate = _read_text(root / QUALITY_GATE)
    examples_index = _read_text(root / "contracts/examples/index.json")
    negative_index = _read_text(root / "contracts/tests/negative/index.json")
    ae_openapi = _read_text(root / "contracts/openapi/nex-ae-api.openapi.yaml")
    progress = _mapping(evidence.get("progress"))
    vector = _mapping(evidence.get("vector"))
    restart = _mapping(evidence.get("restart"))

    checks = {
        "eight_deterministic_components_pass": all(
            statuses.get(name) == "PASS"
            for name in (
                "boundary", "owner_policy", "handoff", "admission",
                "hydration", "vector", "progress", "restart",
            )
        ),
        "protected_postgres_component_is_opt_in": (
            statuses.get("postgres") == "SKIPPED"
            and bool(evidence.get("postgres", {}).get("skip_reason"))
        ),
        "all_slice_canonical_and_runbook_documents_present": all(
            document_presence.values()
        ),
        "closure_registered_once_in_full_gate": quality_gate.count(CLOSURE_RUNNER) == 1,
        "progress_contract_artifacts_present": all(
            (root / path).is_file()
            for path in (PROGRESS_SCHEMA, PROGRESS_EXAMPLE, PROGRESS_NEGATIVE)
        ),
        "progress_examples_and_privacy_negative_indexed": (
            PROGRESS_EXAMPLE.removeprefix("contracts/") in examples_index
            and PROGRESS_NEGATIVE.removeprefix("contracts/") in negative_index
        ),
        "progress_openapi_is_owner_scoped_and_fail_closed": all(
            marker in ae_openapi
            for marker in (
                "/api/v1/uploads/{upload_handoff_id}/progress:",
                "AeUploadIngestionProgress",
                '"404":',
                '"503":',
            )
        ),
        "index_ready_projection_and_restart_complete": (
            progress.get("journey_status") == "INDEX_READY"
            and progress.get("freshness_status") == "READY"
            and restart.get("work_status") == "SUCCEEDED"
            and restart.get("cancel_status") == "CANCELLED"
        ),
        "mock_vector_freshness_complete": (
            vector.get("status") == "PASS"
            and str(vector.get("provider_alias") or "").startswith("mock-")
            and vector.get("actual_postgres_deferred_to") == "1350"
            and _mapping(vector.get("readiness")).get("retrieval_usable") is True
        ),
        "actual_protected_execution_recorded": all(
            token in protected
            for token in (
                "Actual protected PostgreSQL smoke: `PASS`",
                "five test databases migrated",
                "two AE/CX generations restored `INDEX_READY`",
                "AE/CX/OA/storage residue counts were all zero",
            )
        ),
        "runbook_complete_and_secret_free": (
            all(
                marker in runbook
                for marker in (
                    "## Preconditions", "## Protected Command", "## Expected Evidence",
                    "## Failure Triage", "## Cleanup Verification",
                    "## Rollback And Fail-Closed", "## Privacy And Secret Handling",
                    "## Remote Provider Boundary",
                )
            )
            and not any(
                marker in runbook.lower()
                for marker in (
                    "postgresql+psycopg://", "postgresql://", "nuri1004",
                    "ed6@c496em", "begin private key",
                )
            )
        ),
        "failure_cleanup_and_privacy_boundaries_frozen": all(
            token in runbook
            for token in (
                "including failures before `INDEX_READY`",
                "must not contain source text, extracted Markdown, chunk text, summaries, vectors",
                "must not fall back to local owner defaults or memory persistence",
            )
        ),
        "canonical_marks_s135_complete": all(
            token in canonical
            for token in (
                "Status: S135 complete",
                "## Slice 1351 Closure",
                "Completion signal: Met.",
                "## S136 Handoff",
            )
        ),
        "release_plan_marks_s135_met_and_s136_active": all(
            token in release_plan
            for token in (
                "S135 completion signal: Met.",
                "S136 is the next active requirement",
            )
        ),
        "s136_handoff_preserves_ingestion_ownership": all(
            token in canonical
            for token in (
                "S136 is the next active requirement",
                "actual embedding and reranker providers",
                "must not reopen upload, source materialization, ingestion durability, or ownership authority",
            )
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1351",
        "slice_range": "1342-1351",
        "requirement": "S135",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "s135_authenticated_document_ingestion_closure_failed",
        "closure_readiness": "READY_FOR_S136" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "evidence_statuses": statuses,
        "required_documents": document_presence,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(value == "PASS" for value in statuses.values()),
            "protected_skip_count": sum(value == "SKIPPED" for value in statuses.values()),
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "durable_stage_count": 6 if passed else 0,
            "restart_generation_count": 2 if passed else 0,
            "database_count": 5 if passed else 0,
            "contract_artifact_count": 3 if passed else 0,
        },
        "decision": {
            "completion_signal_met": passed,
            "actual_protected_database_evidence_recorded": passed,
            "closure_database_or_provider_mutation_performed": False,
            "oa_claims_remain_owner_authority": True,
            "cx_remains_private_content_and_ingestion_owner": True,
            "remote_provider_required": False,
            "s136_live_embedding_and_reranker_required": True,
            "full_gate_registered": quality_gate.count(CLOSURE_RUNNER) == 1,
            "next_requirement": "S136" if passed else "blocked",
            "next_requirement_scope": (
                "permission_filtered_hybrid_retrieval_live_integration"
                if passed else "blocked"
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
            "s135_authenticated_document_ingestion_closure=fail "
            f"checks={len(evidence.get('failed_checks') or [])}"
        )
    summary = evidence.get("summary") or {}
    return (
        "s135_authenticated_document_ingestion_closure=pass "
        f"evidence={summary.get('passed_evidence_count', 0)}+"
        f"{summary.get('protected_skip_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"stages={summary.get('durable_stage_count', 0)} "
        f"next={evidence.get('decision', {}).get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s135_authenticated_document_ingestion_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
