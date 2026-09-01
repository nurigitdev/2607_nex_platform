#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
for service_path in (
    "services/_shared",
    "services/nex-ag",
):
    sys.path.insert(0, str(ROOT / service_path))

from nex_ag.artifact_operations import (  # noqa: E402
    AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION,
    InMemoryAeArtifactOperationsClient,
    _artifact_retention_batch_plan_cache_key,
    _artifact_retention_history_cache_key,
    assert_artifact_operation_projection_redacted,
    register_artifact_operation_routes,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)

SCHEMA_VERSION = "ag_artifact_retention_automation_operations_smoke.v1"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
TENANT_ID = "tenant-0509"
WORKSPACE_ID = "workspace-0509"
OWNER_USER_ID = "user-0509"
AS_OF = "2026-09-01T00:00:00Z"
CHECKED_AT = "2026-09-01T02:30:00Z"
ROUTE = "/admin/v1/operations/artifact-retention/automation"


def run_ag_artifact_retention_automation_operations_smoke() -> dict[str, Any]:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_artifact_operation_routes(app, client=_smoke_source_client())
    client = TestClient(app)
    response = client.get(
        ROUTE,
        params={
            "tenant_id": TENANT_ID,
            "workspace_id": WORKSPACE_ID,
            "owner_user_id": OWNER_USER_ID,
            "retention_days": "30",
            "as_of": AS_OF,
            "scan_limit": "20",
            "max_delete_count": "1",
            "checked_at": CHECKED_AT,
            "limit": "20",
        },
        headers=_auth_headers(),
    )
    payload = response.json() if response.content else {}
    checks = _smoke_checks(response.status_code, payload)
    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "route": ROUTE,
        "response_status": response.status_code,
        "trace_id": TRACE_ID,
        "projection_schema_version": payload.get("projection_schema_version"),
        "summary": payload.get("summary") if isinstance(payload, Mapping) else {},
        "checks": checks,
    }
    assert_smoke_evidence_redacted(evidence)
    return evidence


def _smoke_source_client() -> InMemoryAeArtifactOperationsClient:
    return InMemoryAeArtifactOperationsClient(
        artifact_retention_batch_plans={
            _artifact_retention_batch_plan_cache_key(
                tenant_id=TENANT_ID,
                workspace_id=WORKSPACE_ID,
                owner_user_id=OWNER_USER_ID,
                retention_days=30,
                as_of=AS_OF,
                scan_limit=20,
                max_delete_count=1,
                checked_at=CHECKED_AT,
            ): _batch_plan()
        },
        artifact_retention_scheduled_jobs={
            "job-retention-automation-queued-0509": _scheduled_job(
                job_id="job-retention-automation-queued-0509",
                status="QUEUED",
                selected_count=1,
                updated_at="2026-09-01T02:31:00Z",
            ),
            "job-retention-automation-failed-0509": _scheduled_job(
                job_id="job-retention-automation-failed-0509",
                status="FAILED",
                selected_count=2,
                retryable=True,
                updated_at="2026-09-01T02:32:00Z",
            ),
        },
        artifact_retention_history_collections={
            _artifact_retention_history_cache_key(
                tenant_id=TENANT_ID,
                workspace_id=WORKSPACE_ID,
                owner_user_id=OWNER_USER_ID,
                mode=None,
                execution_status=None,
                limit=20,
            ): _history()
        },
    )


def _batch_plan() -> dict[str, Any]:
    return {
        "artifact_retention_batch_plan_schema_version": (
            "ae_artifact_retention_batch_plan.v1"
        ),
        "plan_id": "retention-automation-plan-0509",
        "service_id": "nex-ae-api",
        "schedule": {
            "schedule_id": "ae-artifact-retention-schedule-local-v1",
            "policy_id": "ae-artifact-logical-purge-30d-local-v1",
            "service_id": "nex-ae-api",
            "enabled": False,
            "planning_enabled": True,
            "default_mode": "DRY_RUN",
            "allowed_modes": ["DRY_RUN", "EXECUTE"],
            "retention_days_presets": [15, 30],
            "default_retention_days_after_logical_purge": 30,
            "max_scan_limit": 100,
            "max_delete_count": 10,
            "timezone": "Asia/Seoul",
            "batch_window": {
                "start_local_time": "02:00",
                "end_local_time": "05:00",
            },
            "scheduler": {"daemon_enabled": False, "cron": "PRIVATE_CRON"},
            "execution_guards": {
                "delete_enabled": False,
                "storage_mutation_enabled": False,
                "database_row_delete_enabled": False,
            },
            "ownership": {"system_of_record": "nex-ae-api"},
        },
        "candidate_filter": {
            "tenant_id": TENANT_ID,
            "workspace_id": WORKSPACE_ID,
            "owner_user_id": OWNER_USER_ID,
            "status": "DELETED",
            "retention_days": 30,
            "as_of": AS_OF,
            "cutoff_at": "2026-08-02T00:00:00Z",
            "limit": 20,
            "dry_run": True,
        },
        "tenant_id": TENANT_ID,
        "workspace_id": WORKSPACE_ID,
        "owner_user_id": OWNER_USER_ID,
        "mode": "DRY_RUN",
        "plan_status": "READY",
        "scheduler_status": "DISABLED",
        "execution_advice": "Review dry-run evidence before enabling deletes.",
        "as_of": AS_OF,
        "cutoff_at": "2026-08-02T00:00:00Z",
        "checked_at": CHECKED_AT,
        "scan_limit": 20,
        "max_delete_count": 1,
        "candidate_count": 2,
        "selected_count": 1,
        "unselected_count": 1,
        "estimated_deleted_counts": {
            "artifacts": 1,
            "source_refs": 1,
            "versions": 1,
            "render_jobs": 1,
            "files": 2,
            "links": 4,
            "storage_files": 2,
        },
        "selected_candidates": [
            {
                "artifact_id": "artifact-retention-automation-0509",
                "display_title": "Retention automation artifact",
                "artifact_status": "DELETED",
                "logical_purged_at": "2026-07-31T00:00:00Z",
                "purge_eligible_at": "2026-08-30T00:00:00Z",
                "age_days_after_logical_purge": 32,
                "version_count": 1,
                "file_count": 2,
                "link_count": 4,
                "render_job_count": 1,
                "planned_action": "retention_purge_dry_run",
                "execution_mode": "dry-run",
                "dry_run": True,
                "storage_ref": "/data/nex-platform/ae/private.md",
            }
        ],
        "requested_by": {
            "actor_type": "service",
            "actor_id": "nex-ag",
            "service_id": "nex-ae-api",
        },
        "idempotency_key": "retention-automation-plan-0509",
        "metadata": {
            "metadata_only": True,
            "dry_run": True,
            "physical_delete_executed": False,
            "storage_mutation_executed": False,
            "database_row_delete_executed": False,
            "history_write_executed": False,
            "database_url": "postgresql://nuri1004@private",
        },
    }


def _scheduled_job(
    *,
    job_id: str,
    status: str,
    selected_count: int,
    retryable: bool = False,
    updated_at: str,
) -> dict[str, Any]:
    command_id = f"command-{job_id}"
    return {
        "artifact_retention_scheduled_job_schema_version": (
            "ae_artifact_retention_scheduled_job.v1"
        ),
        "job_schema_version": "common_job.v1",
        "job_id": job_id,
        "job_type": "ae.artifact_retention.scheduled_execution",
        "status": status,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "subject_ref": {
            "type": "ae.artifact_retention.scheduled_execution",
            "id": command_id,
            "database_url": "postgresql://nuri1004@private",
        },
        "idempotency_key": f"idem-{job_id}",
        "attempt_count": 1 if status == "FAILED" else 0,
        "max_attempts": 3,
        "retryable": retryable,
        "links": {
            "ae_retention_batch_plan": "/api/v1/artifact-retention/batch-plan",
            "ae_retention_purge": "/api/v1/artifact-retention/purge",
            "ae_retention_history": "/api/v1/artifact-retention/executions",
            "unsafe_storage": "/data/nex-platform/ae/private.md",
        },
        "payload": {
            "payload_schema_version": "ae_artifact_retention_scheduled_job_payload.v1",
            "command_id": command_id,
            "source_plan_id": "retention-automation-plan-0509",
            "tenant_id": TENANT_ID,
            "workspace_id": WORKSPACE_ID,
            "owner_user_id": OWNER_USER_ID,
            "trigger_type": "scheduler_tick",
            "scheduler_status": "DISABLED",
            "command_status": "READY",
            "execution_mode": "DRY_RUN",
            "retention_days_after_logical_purge": 30,
            "scan_limit": 20,
            "max_delete_count": 1,
            "candidate_count": 2,
            "selected_count": selected_count,
            "estimated_deleted_counts": {
                "artifacts": selected_count,
                "storage_files": selected_count * 2,
            },
            "command_summary": {
                "command_status": "READY",
                "trigger_type": "scheduler_tick",
                "scheduler_status": "DISABLED",
                "execution_mode": "DRY_RUN",
                "candidate_count": 2,
                "selected_count": selected_count,
                "estimated_deleted_artifacts": selected_count,
                "estimated_deleted_storage_files": selected_count * 2,
                "command_created_at": "2026-09-01T02:31:00Z",
                "next_action": "Review dry-run evidence before enabling deletes.",
            },
            "requested_by": {
                "actor_type": "service",
                "actor_id": "nex-ag",
                "service_id": "nex-ae-api",
                "database_url": "postgresql://nuri1004@private",
            },
            "requested_at": "2026-09-01T02:31:00Z",
            "redaction_summary": {
                "metadata_only": True,
                "scheduled_command_embedded": True,
                "batch_plan_embedded": False,
                "artifact_payload_included": False,
                "prompt_content_included": False,
                "generation_output_included": False,
                "storage_locator_included": False,
                "database_url_included": False,
            },
            "scheduled_command": {
                "execution_request": {"storage_ref": "/data/nex-platform/ae/private.md"}
            },
        },
        "created_at": "2026-09-01T02:31:00Z",
        "updated_at": updated_at,
    }


def _history() -> dict[str, Any]:
    return {
        "artifact_retention_execution_history_collection_schema_version": (
            "ae_artifact_retention_execution_history_collection.v1"
        ),
        "filter": {
            "tenant_id": TENANT_ID,
            "workspace_id": WORKSPACE_ID,
            "owner_user_id": OWNER_USER_ID,
            "mode": None,
            "execution_status": None,
            "limit": 20,
        },
        "count": 2,
        "limit": 20,
        "next_cursor": None,
        "items": [
            {
                "retention_execution_id": "retention-execute-0509",
                "mode": "EXECUTE",
                "execution_status": "SUCCEEDED",
                "tenant_id": TENANT_ID,
                "workspace_id": WORKSPACE_ID,
                "owner_user_id": OWNER_USER_ID,
                "checked_at": "2026-09-01T02:50:00Z",
                "candidate_count": 2,
                "selected_count": 1,
                "delete_enabled": True,
                "storage_mutation_enabled": True,
                "database_row_delete_enabled": True,
                "deleted_counts": {"artifacts": 1, "storage_files": 2},
                "blocked_reason": None,
                "execution_payload_hash": "a" * 64,
            },
            {
                "retention_execution_id": "retention-approval-blocked-0509",
                "mode": "EXECUTE",
                "execution_status": "BLOCKED",
                "tenant_id": TENANT_ID,
                "workspace_id": WORKSPACE_ID,
                "owner_user_id": OWNER_USER_ID,
                "checked_at": "2026-09-01T02:45:00Z",
                "candidate_count": 2,
                "selected_count": 0,
                "deleted_counts": {"artifacts": 0, "storage_files": 0},
                "blocked_reason": "operator_approval_required",
                "execution_payload_hash": "b" * 64,
            },
        ],
    }


def _auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _smoke_checks(status_code: int, payload: Any) -> dict[str, bool]:
    if not isinstance(payload, Mapping):
        return {
            "route_status_ok": False,
            "schema_version": False,
            "dispatch_available": False,
            "operator_attention": False,
            "approval_gate_visible": False,
            "no_direct_ag_mutation": False,
            "metadata_only": False,
            "redacted": False,
        }
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        summary = {}
    guidance = payload.get("operator_guidance")
    if not isinstance(guidance, Mapping):
        guidance = {}
    return {
        "route_status_ok": status_code == 200,
        "schema_version": payload.get("projection_schema_version")
        == AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION,
        "dispatch_available": summary.get("dispatch_available") is True,
        "operator_attention": summary.get("operator_attention_required") is True,
        "approval_gate_visible": summary.get("approval_blocked_count") == 1
        and summary.get("physical_delete_operator_approval_required") is True,
        "no_direct_ag_mutation": guidance.get("ag_direct_database_write_allowed")
        is False
        and guidance.get("ag_direct_job_enqueue_allowed") is False,
        "metadata_only": guidance.get("metadata_only") is True,
        "redacted": _is_redacted(payload),
    }


def _is_redacted(payload: Mapping[str, Any]) -> bool:
    try:
        assert_artifact_operation_projection_redacted(payload)
    except ValueError:
        return False
    return True


def assert_smoke_evidence_redacted(evidence: Mapping[str, Any]) -> None:
    serialized = json.dumps(evidence, sort_keys=True)
    forbidden_fragments = (
        "/data/nex-platform",
        "database_url",
        "nuri1004",
        "PRIVATE_CRON",
        "storage_ref",
    )
    for fragment in forbidden_fragments:
        if fragment in serialized:
            raise ValueError(
                "AG artifact retention automation smoke leaked private data."
            )


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary")
    if not isinstance(summary, Mapping):
        summary = {}
    failing_checks = [
        key for key, passed in evidence.get("checks", {}).items() if passed is not True
    ]
    suffix = (
        f"route_status={evidence.get('response_status')} "
        f"safety={summary.get('safety_status')} "
        f"scheduled_jobs={summary.get('scheduled_job_count')} "
        f"history={summary.get('history_count')} "
        f"approval_blocked={summary.get('approval_blocked_count')}"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ag_artifact_retention_automation_operations_smoke="
        f"{str(evidence.get('status')).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AG artifact retention automation operations smoke."
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a short result line."
    )
    parser.add_argument(
        "--output", type=Path, help="Optional JSON evidence output path."
    )
    return parser


def write_smoke_evidence(path: Path, evidence: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ag_artifact_retention_automation_operations_smoke()
        if args.output:
            write_smoke_evidence(args.output, evidence)
        print(
            summary_line(evidence) if args.summary else json.dumps(evidence, indent=2)
        )
        return 0 if evidence["status"] == "PASS" else 1
    except Exception as exc:
        print(
            "ag_artifact_retention_automation_operations_smoke=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
