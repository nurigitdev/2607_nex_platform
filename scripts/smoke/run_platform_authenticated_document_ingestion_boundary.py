#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_authenticated_document_ingestion_boundary.v1"
CANONICAL_DOCUMENT = "docs/42_platform_authenticated_document_ingestion.md"
REQUIRED_PATHS = (
    "docs/37_platform_mvp_integration_release_plan.md",
    CANONICAL_DOCUMENT,
    "services/nex-ae-api/nex_ae_api/uploads.py",
    "services/nex-ae-api/nex_ae_api/auth_guard.py",
    "services/nex-ae-api/nex_ae_api/oa_session_client.py",
    "services/nex-cx/nex_cx/ingestion.py",
    "services/nex-cx/nex_cx/ingestion_admission.py",
    "services/nex-cx/nex_cx/ingestion_worker.py",
    "services/nex-cx/nex_cx/ingestion_coordinator.py",
    "services/nex-cx/nex_cx/mvp_runtime.py",
    "services/nex-cx/nex_cx/vector_index_publish.py",
    "scripts/dev/run_background_process.py",
)
REQUIRED_TOKENS = (
    ("outcome", CANONICAL_DOCUMENT, "## Required Outcome"),
    ("invariants", CANONICAL_DOCUMENT, "## Journey Invariants"),
    ("gaps", CANONICAL_DOCUMENT, "## Current Gaps"),
    ("sequence", CANONICAL_DOCUMENT, "## Slice Sequence"),
    ("completion", CANONICAL_DOCUMENT, "## Completion Signal"),
    ("handoff", CANONICAL_DOCUMENT, "## S136 Handoff"),
    ("plan", "docs/37_platform_mvp_integration_release_plan.md", "## S135 Slice Plan"),
    (
        "quality",
        "scripts/quality/run_quality_gate.sh",
        "run_platform_authenticated_document_ingestion_boundary.py",
    ),
    (
        "index",
        "docs/README.md",
        "1342_platform_authenticated_document_ingestion_boundary.md",
    ),
)


def run_platform_authenticated_document_ingestion_boundary(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = [{"path": path, "present": (root / path).is_file()} for path in REQUIRED_PATHS]
    tokens = [
        {"group": group, "path": path, "present": token in _read_text(root / path)}
        for group, path, token in REQUIRED_TOKENS
    ]
    sources = {
        "ae_uploads": _read_text(root / "services/nex-ae-api/nex_ae_api/uploads.py"),
        "cx_ingestion": _read_text(root / "services/nex-cx/nex_cx/ingestion.py"),
        "cx_admission": _read_text(
            root / "services/nex-cx/nex_cx/ingestion_admission.py"
        ),
        "cx_worker": _read_text(root / "services/nex-cx/nex_cx/ingestion_worker.py"),
        "cx_coordinator": _read_text(
            root / "services/nex-cx/nex_cx/ingestion_coordinator.py"
        ),
        "cx_mvp": _read_text(root / "services/nex-cx/nex_cx/mvp_runtime.py"),
        "background": _read_text(root / "scripts/dev/run_background_process.py"),
    }
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "authenticated_multipart_upload_exists": (
            "AE_MULTIPART_UPLOAD_ROUTE" in sources["ae_uploads"]
            and "authorize_ae_facade_route_request" in sources["ae_uploads"]
            and "_browser_owner_scoped_payload" in sources["ae_uploads"]
        ),
        "signed_ae_to_cx_handoff_exists": (
            "resolve_ae_outbound_service_token" in sources["ae_uploads"]
            and 'audience="nex-cx"' in sources["ae_uploads"]
            and 'X-Service-ID": "nex-ae-api"' in sources["ae_uploads"]
        ),
        "cx_owner_authorized_upload_exists": (
            'app.post("/api/v1/documents/uploads"' in sources["cx_ingestion"]
            and "authorize_cx_owner_request" in sources["cx_ingestion"]
            and "require_owner_assertion_match" in sources["cx_ingestion"]
        ),
        "source_materialization_exists": (
            "materialize_local_source_bytes" in sources["cx_ingestion"]
            and "checksum_verified_at" in sources["cx_ingestion"]
        ),
        "durable_job_and_run_admission_exists": (
            "admit_durable_ingestion" in sources["cx_ingestion"]
            and "job_queue.enqueue(" in sources["cx_admission"]
            and "run_repository.create(" in sources["cx_admission"]
        ),
        "checkpoint_pipeline_exists": (
            "execute_all_ingestion_checkpoints" in sources["cx_worker"]
            and "build_default_ingestion_step_handlers" in sources["cx_coordinator"]
        ),
        "mock_embedding_publish_path_exists": (
            "MvpIngestionVectorIndexer" in sources["cx_mvp"]
            and "mvp_embedding_handler" in sources["cx_mvp"]
        ),
        "ingestion_process_registered": (
            '"nex-cx-ingestion-worker"' in sources["background"]
        ),
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "boundary_schema_version": SCHEMA_VERSION,
        "slice": "1342",
        "requirement": "S135",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": (
            None if not issues else "platform_authenticated_document_ingestion_boundary_failed"
        ),
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "required_tokens": tokens,
        "findings": {
            "existing_component_count": 8,
            "current_gap_count": 6,
            "durable_stage_count": 6,
            "denial_scenario_count": 4,
        },
        "decision": {
            "oa_claims_are_owner_authority": True,
            "ae_persists_source_bytes": False,
            "cx_owns_ingestion_lineage": True,
            "shared_database_allowed": False,
            "actual_test_databases_required": True,
            "remote_embedding_provider_required": False,
            "mock_mo_embedding_required": True,
            "next_slice": "1343",
        },
        "slice_plan": [str(value) for value in range(1342, 1352)],
        "quality_cadence": {
            "slice_gate": "every_slice",
            "checkpoint_gate": "1346",
            "full_gate": "1351",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "platform_authenticated_document_ingestion_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    findings = evidence.get("findings") or {}
    return (
        "platform_authenticated_document_ingestion_boundary=pass "
        f"components={findings.get('existing_component_count', 0)} "
        f"stages={findings.get('durable_stage_count', 0)} "
        f"gaps={findings.get('current_gap_count', 0)} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_authenticated_document_ingestion_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
