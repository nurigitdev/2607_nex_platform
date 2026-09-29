#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_async_artifact_rendering_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/1071_s107_ae_generated_response_lineage_closure.md",
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/nex_ae_api/generated_response_lineage.py",
    "services/_shared/nex_runtime/jobs.py",
    "database/nex-ae-api/migrations/0402_ae_artifact_persistence_foundation.sql",
    "database/nex-ae-api/migrations/0083_service_job_queue_foundation.sql",
    "docs/development_process.md",
    "docs/slices/1072_ae_async_artifact_rendering_boundary_audit.md",
    "docs/README.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "s107_closure",
        "scripts/smoke/run_s107_ae_generated_response_lineage_closure.py",
        '"READY_FOR_S108"',
    ),
    EvidenceToken(
        "sync_render_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        'app.post("/api/v1/artifacts/{artifact_id}/render-jobs"',
    ),
    EvidenceToken(
        "sync_completion",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"job_status": "COMPLETED"',
    ),
    EvidenceToken(
        "render_storage_adapter",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "class RenderedArtifactStorage(Protocol):",
    ),
    EvidenceToken(
        "render_job_table",
        "database/nex-ae-api/migrations/0402_ae_artifact_persistence_foundation.sql",
        "CREATE TABLE IF NOT EXISTS ae_artifact_render_jobs",
    ),
    EvidenceToken(
        "service_job_table",
        "database/nex-ae-api/migrations/0083_service_job_queue_foundation.sql",
        "CREATE TABLE IF NOT EXISTS service_jobs",
    ),
    EvidenceToken(
        "job_queue_protocol",
        "services/_shared/nex_runtime/jobs.py",
        "class JobQueue(Protocol):",
    ),
    EvidenceToken(
        "render_formats",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"PDF_RENDERING"',
    ),
    EvidenceToken(
        "generated_response_lineage",
        "services/nex-ae-api/nex_ae_api/generated_response_lineage.py",
        "def prepare_generated_response(",
    ),
    EvidenceToken(
        "tiered_gate",
        "docs/development_process.md",
        "Checkpoint Gate",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "1072_ae_async_artifact_rendering_boundary_audit.md",
    ),
)

GAP_RESOLUTION_PATHS = {
    "async_render_contract_missing": (
        "docs/slices/1073_ae_async_artifact_render_contract.md"
    ),
    "durable_admission_missing": (
        "docs/slices/1074_ae_async_artifact_render_admission.md"
    ),
    "owner_scoped_api_missing": ("docs/slices/1075_ae_async_artifact_render_api.md"),
    "render_worker_missing": ("docs/slices/1076_ae_async_artifact_render_worker.md"),
    "chat_response_lineage_missing": (
        "docs/slices/1077_ae_async_artifact_response_lineage.md"
    ),
    "recovery_observability_missing": (
        "docs/slices/1078_ae_async_artifact_render_recovery.md"
    ),
    "contract_openapi_missing": (
        "docs/slices/1079_ae_async_artifact_render_contract_hardening.md"
    ),
    "postgres_evidence_missing": (
        "docs/slices/1080_ae_async_artifact_render_postgres_smoke.md"
    ),
}

GAP_SLICES = {
    name: f"{1073 + index:04d}" for index, name in enumerate(GAP_RESOLUTION_PATHS)
}


def run_ae_async_artifact_rendering_boundary_audit(
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
    gap_states = {
        name: "RESOLVED" if (root / path).is_file() else "OPEN"
        for name, path in GAP_RESOLUTION_PATHS.items()
    }
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s107_handoff_bound": _group_present(tokens, "s107_closure"),
        "existing_render_pipeline_reusable": all(
            _group_present(tokens, group)
            for group in (
                "sync_render_route",
                "sync_completion",
                "render_storage_adapter",
                "render_formats",
            )
        ),
        "durable_job_foundation_reusable": all(
            _group_present(tokens, group)
            for group in ("render_job_table", "service_job_table", "job_queue_protocol")
        ),
        "generated_response_lineage_reusable": _group_present(
            tokens, "generated_response_lineage"
        ),
        "tiered_quality_cadence_confirmed": _group_present(tokens, "tiered_gate"),
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
        "1081",
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1072",
        "requirement": "S108",
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
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "known_drifts": [
            "render_post_executes_source_fetch_transform_and_publish_inline",
            "render_job_is_persisted_only_after_successful_completion",
            "render_work_is_not_admitted_to_the_durable_service_job_queue",
            "render_status_has_no_exact_owner_authorization",
            "render_cancellation_retry_and_restart_recovery_are_missing",
            "chat_response_to_artifact_render_lineage_is_not_canonical",
            "async_render_contract_and_postgresql_evidence_are_missing",
        ],
        "gap_states": gap_states,
        "gap_resolution_paths": GAP_RESOLUTION_PATHS,
        "slice_plan": [
            "1072_boundary_audit",
            "1073_async_render_contract",
            "1074_durable_queue_admission",
            "1075_owner_scoped_render_api",
            "1076_render_worker_checkpoint",
            "1077_chat_response_lineage",
            "1078_recovery_observability",
            "1079_contract_openapi_hardening",
            "1080_actual_postgresql_storage_smoke",
            "1081_s108_closure_full_gate",
        ],
        "checks": checks,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": next_slice,
    }


def boundary_decision() -> dict[str, Any]:
    return {
        "owner": "nex-ae-api",
        "scope": "ae_asynchronous_artifact_rendering_integration",
        "source_content_owner": "nex-cx_structured_draft",
        "response_lineage_owner": "nex-ae-api",
        "execution_model": "durable_queue_backed_asynchronous_render",
        "render_state_store": "ae_artifact_render_jobs",
        "execution_queue_store": "service_jobs",
        "rendered_payload_store": "ae_private_rendered_artifact_storage",
        "new_tables_expected": 0,
        "legacy_sync_route_preserved": True,
        "explicit_async_admission_required": True,
        "exact_owner_scope_required": True,
        "raw_rendered_content_in_postgresql": False,
        "raw_rendered_content_in_operational_events": False,
        "storage_path_in_public_api": False,
        "restart_safe_render_required": True,
        "remote_provider_required": False,
        "quality_cadence": {
            "slice_gate": "every_slice",
            "checkpoint_gate": "1076",
            "full_gate": "1081",
        },
    }


def summary_line(result: dict[str, Any]) -> str:
    summary = result.get("summary", {})
    return (
        "ae_async_artifact_rendering_boundary="
        f"{'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"foundations={summary.get('foundation_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"open={summary.get('open_gap_count', 0)} "
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
    result = run_ae_async_artifact_rendering_boundary_audit()
    if args.summary:
        print(summary_line(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
