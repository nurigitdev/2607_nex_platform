#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
for service_path in (
    "services/_shared",
    "services/nex-oa",
    "services/nex-ag",
):
    sys.path.insert(0, str(ROOT / service_path))

from nex_ag.operations import (  # noqa: E402
    AgOperationsSourceRuntime,
    build_operations_source_registry,
    register_job_operation_routes,
    register_operation_source_readiness_routes,
    register_operational_event_taxonomy_routes,
    register_operational_event_routes,
    register_service_log_routes,
    register_unified_operation_routes,
)
from nex_ag.processing_operations import (  # noqa: E402
    InMemoryCxProcessingRunOperationsStore,
    register_cx_processing_run_operation_routes,
)
from nex_ag.retrieval_operations import (  # noqa: E402
    InMemoryRetrievalPackageOperationsStore,
)
from nex_runtime import (  # noqa: E402
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    InMemoryServiceLogStore,
    InMemoryWorkerHeartbeatStore,
    SERVICE_SPECS,
    build_common_job,
    build_operational_event,
    build_service_app,
    build_service_log_entry,
    build_service_log_retention_execution,
    build_subject_ref,
    build_worker_heartbeat,
    issue_mock_service_token,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
SCHEMA_VERSION = "ag_operations_dashboard_smoke.v1"


def run_ag_operations_dashboard_smoke() -> dict[str, Any]:
    cx_processing_run_stores = _build_cx_processing_run_stores()
    retrieval_package_stores = _build_retrieval_package_stores()
    registry = build_operations_source_registry(
        job_queues=_build_job_queues(),
        event_stores=_build_event_stores(),
        service_log_stores=_build_log_stores(),
        worker_heartbeat_stores=_build_worker_heartbeat_stores(),
    )
    runtime = AgOperationsSourceRuntime(
        mode="memory",
        profile="dev",
        selected_service_ids=tuple(registry.service_ids()),
        registry=registry,
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operation_source_readiness_routes(app, runtime=runtime)
    register_cx_processing_run_operation_routes(
        app,
        stores=cx_processing_run_stores,
        runtime=runtime,
    )
    register_unified_operation_routes(
        app,
        registry=registry,
        runtime=runtime,
        retrieval_package_stores=retrieval_package_stores,
        cx_processing_run_stores=cx_processing_run_stores,
    )
    register_operational_event_taxonomy_routes(app)
    register_operational_event_routes(app, registry=registry)
    register_service_log_routes(app, registry=registry)
    register_job_operation_routes(app, registry=registry)

    client = TestClient(app)
    projections = _read_operations_projections(client)
    checks = _ag_operations_dashboard_smoke_checks(projections)
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": status,
        "trace_id": TRACE_ID,
        "endpoint_count": len(projections),
        "projection_versions": {
            name: projection.get("projection_schema_version")
            for name, projection in projections.items()
        },
        "counts": _projection_counts(projections),
        "checks": checks,
    }


def _build_cx_processing_run_stores() -> dict[str, InMemoryCxProcessingRunOperationsStore]:
    return {
        "nex-cx": InMemoryCxProcessingRunOperationsStore(
            records=[
                _sample_processing_run(
                    pipeline_run_id="smoke-processing-run-cx-001",
                    status="RUNNING",
                    job_id="smoke-job-cx-001",
                    updated_at="2026-08-05T00:00:04Z",
                    step_failed=0,
                    job_retryable=True,
                ),
                _sample_processing_run(
                    pipeline_run_id="smoke-processing-run-cx-002",
                    status="FAILED",
                    job_id="smoke-job-cx-002",
                    updated_at="2026-08-05T00:00:05Z",
                    step_failed=1,
                    job_retryable=False,
                ),
            ]
        )
    }


def _build_retrieval_package_stores() -> dict[str, InMemoryRetrievalPackageOperationsStore]:
    return {
        "nex-cx": InMemoryRetrievalPackageOperationsStore(
            records=[
                _sample_retrieval_package(
                    retrieval_package_id="smoke-retrieval-package-cx-001",
                    created_at="2026-08-05T00:00:06Z",
                )
            ]
        )
    }


def _build_job_queues() -> dict[str, InMemoryJobQueue]:
    cx_queue = InMemoryJobQueue()
    cx_queue.enqueue(
        _sample_job(
            job_id="smoke-job-cx-001",
            idempotency_key="smoke-idem-cx-001",
            created_at="2026-08-05T00:00:00Z",
        )
    )
    cx_queue.start_job(
        "smoke-job-cx-001",
        updated_at="2026-08-05T00:00:03Z",
    )
    cx_queue.enqueue(
        _sample_job(
            job_id="smoke-job-cx-002",
            idempotency_key="smoke-idem-cx-002",
            created_at="2026-08-05T00:00:01Z",
            max_attempts=1,
        )
    )
    cx_queue.start_job(
        "smoke-job-cx-002",
        updated_at="2026-08-05T00:00:04Z",
    )
    cx_queue.retry_job(
        "smoke-job-cx-002",
        error={
            "error_code": "cx.processing.failed",
            "detail": "Smoke processing failed.",
        },
        failed_at="2026-08-05T00:00:05Z",
    )
    ae_queue = InMemoryJobQueue()
    ae_queue.enqueue(
        _sample_job(
            job_id="smoke-job-ae-001",
            job_type="ae.artifact_render",
            subject_ref=build_subject_ref("ae.artifact", "artifact-smoke-001"),
            idempotency_key="smoke-idem-ae-001",
            created_at="2026-08-05T00:00:02Z",
        )
    )
    return {
        "nex-ae-api": ae_queue,
        "nex-cx": cx_queue,
    }


def _build_event_stores() -> dict[str, InMemoryOperationalEventStore]:
    cx_store = InMemoryOperationalEventStore()
    cx_store.append(
        build_operational_event(
            event_id="smoke-event-cx-001",
            service_id="nex-cx",
            event_type="cx.processing.succeeded",
            severity="INFO",
            message="Smoke document processing succeeded.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            subject_ref={"type": "cx.document", "id": "doc-smoke-001"},
            details={"job_id": "smoke-job-cx-001"},
            created_at="2026-08-05T00:00:00Z",
        )
    )
    cx_store.append(
        build_operational_event(
            event_id="smoke-event-cx-worker-001",
            service_id="nex-cx",
            event_type="cx.worker.lifecycle.busy",
            severity="INFO",
            message="Smoke CX worker started job.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            subject_ref={"type": "worker", "id": "smoke-worker-cx-001"},
            details={
                "worker_id": "smoke-worker-cx-001",
                "worker_type": "cx.document_processing.worker",
                "worker_status": "BUSY",
                "active_job_id": "smoke-job-cx-001",
                "job_id": "smoke-job-cx-001",
            },
            created_at="2026-08-05T00:00:04Z",
        )
    )
    mo_store = InMemoryOperationalEventStore()
    mo_store.append(
        build_operational_event(
            event_id="smoke-event-mo-001",
            service_id="nex-mo",
            event_type="mo.provider.failed",
            severity="ERROR",
            message="Smoke provider request failed.",
            trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            request_id=REQUEST_ID,
            subject_ref={"type": "mo.provider", "id": "embedding"},
            details={"authorization": "Bearer private"},
            created_at="2026-08-05T00:00:01Z",
        )
    )
    return {
        "nex-cx": cx_store,
        "nex-mo": mo_store,
    }


def _build_worker_heartbeat_stores() -> dict[str, InMemoryWorkerHeartbeatStore]:
    cx_store = InMemoryWorkerHeartbeatStore()
    observed_at = _utc_now()
    cx_store.upsert_heartbeat(
        build_worker_heartbeat(
            service_id="nex-cx",
            worker_id="smoke-worker-cx-001",
            worker_type="cx.document_processing.worker",
            status="BUSY",
            active_job_id="smoke-job-cx-001",
            trace_id=TRACE_ID,
            started_at=observed_at,
            last_seen_at=observed_at,
            metadata={"queue": "cx.document_processing", "smoke": True},
        )
    )
    return {"nex-cx": cx_store}


def _build_log_stores() -> dict[str, InMemoryServiceLogStore]:
    cx_store = InMemoryServiceLogStore()
    cx_store.append(
        build_service_log_entry(
            log_id="smoke-log-cx-001",
            service_id="nex-cx",
            severity="INFO",
            logger_name="nex_runtime.worker_runner",
            message="Smoke worker completed a job.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            job_id="smoke-job-cx-001",
            subject_ref={"type": "cx.document", "id": "doc-smoke-001"},
            attributes={
                "worker_id": "smoke-worker-cx-001",
                "worker_type": "cx.document_processing.worker",
                "attempt_count": 1,
            },
            observed_at="2026-08-05T00:00:06Z",
        )
    )
    cx_store.record_retention_history(
        build_service_log_retention_execution(
            service_id="nex-cx",
            mode="EXECUTE",
            execution_status="SUCCEEDED",
            retention_cutoff="2026-07-06T00:00:00Z",
            checked_at="2026-08-05T00:00:07Z",
            candidate_count=2,
            deleted_count=1,
            delete_enabled=True,
            max_delete_count=1,
            requested_by={
                "actor_type": "service",
                "actor_id": "nex-ag",
                "service_id": "nex-ag",
            },
            idempotency_key="smoke-retention-execute",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            execution_id="smoke-retention-execution-cx-001",
        ),
        recorded_at="2026-08-05T00:00:08Z",
    )
    mo_store = InMemoryServiceLogStore()
    mo_store.append(
        build_service_log_entry(
            log_id="smoke-log-mo-001",
            service_id="nex-mo",
            severity="ERROR",
            logger_name="nex_mo.remote_provider",
            message="Smoke provider request failed.",
            trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            request_id=REQUEST_ID,
            job_id="smoke-job-mo-001",
            subject_ref={"type": "mo.provider", "id": "embedding"},
            attributes={"authorization": "Bearer private", "provider": "vllm"},
            observed_at="2026-08-05T00:00:02Z",
        )
    )
    return {
        "nex-cx": cx_store,
        "nex-mo": mo_store,
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sample_job(**overrides: Any) -> dict[str, Any]:
    return build_common_job(
        job_id=overrides.pop("job_id", "smoke-job-001"),
        job_type=overrides.pop("job_type", "cx.document_processing"),
        trace_id=overrides.pop("trace_id", TRACE_ID),
        request_id=overrides.pop("request_id", REQUEST_ID),
        subject_ref=overrides.pop(
            "subject_ref",
            build_subject_ref("cx.document", "doc-smoke-001"),
        ),
        idempotency_key=overrides.pop("idempotency_key", "smoke-idem-001"),
        created_at=overrides.pop("created_at", "2026-08-05T00:00:00Z"),
        max_attempts=overrides.pop("max_attempts", 2),
        status=overrides.pop("status", "QUEUED"),
        **overrides,
    )


def _sample_processing_run(**overrides: Any) -> dict[str, Any]:
    pipeline_run_id = overrides.pop("pipeline_run_id", "smoke-processing-run-cx-001")
    status = overrides.pop("status", "RUNNING")
    job_id = overrides.pop("job_id", "smoke-job-cx-001")
    updated_at = overrides.pop("updated_at", "2026-08-05T00:00:04Z")
    step_failed = int(overrides.pop("step_failed", 0))
    job_retryable = bool(overrides.pop("job_retryable", True))
    return {
        "pipeline_run_id": pipeline_run_id,
        "pipeline_schema_version": "cx_document_processing_pipeline.v1",
        "document_id": "doc-smoke-001",
        "status": status,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "job_id": job_id,
        "job_type": "cx.document_processing",
        "job_status": status,
        "job_attempt_count": 1,
        "job_max_attempts": 2,
        "job_retryable": job_retryable,
        "job_subject_ref": {"type": "cx.document", "id": "doc-smoke-001"},
        "job_links": {"processing": "/api/v1/documents/doc-smoke-001/processing"},
        "step_total": 2,
        "step_succeeded": 1 if step_failed else 2,
        "step_skipped": 0,
        "step_failed": step_failed,
        "queued_at": "2026-08-05T00:00:01Z",
        "started_at": "2026-08-05T00:00:02Z",
        "completed_at": updated_at if status in {"SUCCEEDED", "FAILED"} else None,
        "updated_at": updated_at,
        "steps": [
            {
                "pipeline_run_id": pipeline_run_id,
                "step_order": 1,
                "step_id": "extract_text",
                "status": "SUCCEEDED",
                "output_ref_type": "text_extraction",
                "output_ref_id": "smoke-text-extraction-001",
                "output_ref_document_id": "doc-smoke-001",
                "output_ref_hash": "a" * 64,
                "error_code": None,
                "error_detail_sha256": None,
                "error_retryable": None,
                "created_at": "2026-08-05T00:00:03Z",
            },
            {
                "pipeline_run_id": pipeline_run_id,
                "step_order": 2,
                "step_id": "build_embedding_index",
                "status": "FAILED" if step_failed else "SUCCEEDED",
                "output_ref_type": None if step_failed else "chunk_embedding_index",
                "output_ref_id": None if step_failed else "smoke-embedding-index-001",
                "output_ref_document_id": "doc-smoke-001",
                "output_ref_hash": None if step_failed else "b" * 64,
                "error_code": (
                    "cx.embedding.provider_unavailable" if step_failed else None
                ),
                "error_detail_sha256": "c" * 64 if step_failed else None,
                "error_retryable": True if step_failed else None,
                "created_at": updated_at,
            },
        ],
        **overrides,
    }


def _sample_retrieval_package(**overrides: Any) -> dict[str, Any]:
    retrieval_package_id = overrides.pop(
        "retrieval_package_id",
        "smoke-retrieval-package-cx-001",
    )
    created_at = overrides.pop("created_at", "2026-08-05T00:00:06Z")
    return {
        "retrieval_package_id": retrieval_package_id,
        "package_hash": "d" * 64,
        "status": "READY",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "query_text_sha256": "e" * 64,
        "query_text_preview": "smoke retrieval query",
        "query_embedding_provided": True,
        "query_embedding_sha256": "f" * 64,
        "query_embedding_dimension": 3,
        "purpose": "grounded_answer",
        "retrieval_policy_id": "weighted_rrf_vector_bm25_v1",
        "retrieval_policy_version": "0001",
        "retrieval_policy_hash": "a" * 64,
        "retrieval_policy_source": "ag_registry_active",
        "ranker_mix": "weighted_rrf_vector_bm25_v1",
        "rerank_state": "NOT_APPLIED",
        "permission_snapshot_hash": "b" * 64,
        "source_summary": {"source_count": 1, "document_count": 1, "chunk_count": 1},
        "score_summary": {
            "best_score": 0.92,
            "confidence_bucket": "READY",
            "low_confidence_threshold": 0.2,
        },
        "warning_count": 0,
        "evidence_count": 1,
        "no_answer_reason": None,
        "created_at": created_at,
        "updated_at": created_at,
        **overrides,
    }


def _read_operations_projections(client: TestClient) -> dict[str, dict[str, Any]]:
    return {
        "sources": _get_json(
            client,
            "/admin/v1/operations/sources",
            params={"service_id": "nex-cx"},
        ),
        "unified": _get_json(
            client,
            "/admin/v1/operations",
            params={"service_id": "nex-cx", "limit": 10},
        ),
        "event_taxonomy": _get_json(
            client,
            "/admin/v1/operations/event-taxonomy",
            params={"service_id": "nex-cx"},
        ),
        "events": _get_json(
            client,
            "/admin/v1/operations/events",
            params={"service_id": "nex-mo", "severity": "ERROR"},
        ),
        "event_detail": _get_json(
            client,
            "/admin/v1/operations/events/smoke-event-mo-001",
        ),
        "logs": _get_json(
            client,
            "/admin/v1/operations/logs",
            params={"service_id": "nex-cx", "q": "worker"},
        ),
        "log_detail": _get_json(
            client,
            "/admin/v1/operations/logs/smoke-log-mo-001",
        ),
        "log_policy": _get_json(
            client,
            "/admin/v1/operations/logs/policy",
        ),
        "log_retention_dry_run": _get_json(
            client,
            "/admin/v1/operations/logs/retention/dry-run",
            params={"service_id": "nex-cx", "retention_days": 30},
        ),
        "log_retention_history": _get_json(
            client,
            "/admin/v1/operations/logs/retention/history",
            params={
                "service_id": "nex-cx",
                "mode": "execute",
                "execution_status": "succeeded",
                "request_id": REQUEST_ID,
            },
        ),
        "jobs": _get_json(
            client,
            "/admin/v1/operations/jobs",
            params={"service_id": "nex-cx"},
        ),
        "cx_processing_runs": _get_json(
            client,
            "/admin/v1/operations/cx-processing-runs",
            params={"service_id": "nex-cx", "limit": 10},
        ),
        "cx_processing_run_detail": _get_json(
            client,
            "/admin/v1/operations/cx-processing-runs/smoke-processing-run-cx-002",
            params={"service_id": "nex-cx"},
        ),
        "job_detail": _get_json(
            client,
            "/admin/v1/operations/jobs/nex-cx/smoke-job-cx-001",
        ),
        "workers": _get_json(
            client,
            "/admin/v1/operations/workers",
            params={"service_id": "nex-cx", "stale_after_seconds": 60},
        ),
        "worker_detail": _get_json(
            client,
            "/admin/v1/operations/workers/nex-cx/smoke-worker-cx-001",
            params={"stale_after_seconds": 60},
        ),
        "trace_timeline": _get_json(
            client,
            f"/admin/v1/operations/traces/{TRACE_ID}",
            params={"service_id": "nex-cx"},
        ),
        "rollups": _get_json(
            client,
            "/admin/v1/operations/rollups",
            params={"service_id": "nex-cx"},
        ),
        "dashboard": _get_json(
            client,
            "/admin/v1/operations/dashboard",
            params={"service_id": "nex-cx", "recent_limit": 2},
        ),
        "issue_candidates": _get_json(
            client,
            "/admin/v1/operations/issue-candidates",
            params={
                "service_id": "nex-cx",
                "recent_limit": 2,
                "stale_after_seconds": 315360000,
            },
        ),
    }


def _get_json(
    client: TestClient,
    path: str,
    *,
    params: dict[str, object] | None = None,
) -> dict[str, Any]:
    response = client.get(path, params=params, headers=_ag_service_headers())
    response.raise_for_status()
    return response.json()


def _ag_service_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _ag_operations_dashboard_smoke_checks(
    projections: dict[str, dict[str, Any]],
) -> dict[str, bool]:
    dashboard = projections["dashboard"]
    issue_candidates = projections["issue_candidates"]
    event_detail = projections["event_detail"]
    logs = projections["logs"]
    log_detail = projections["log_detail"]
    log_policy = projections["log_policy"]
    log_retention_dry_run = projections["log_retention_dry_run"]
    log_retention_history = projections["log_retention_history"]
    job_detail = projections["job_detail"]
    cx_processing_runs = projections["cx_processing_runs"]
    cx_processing_run_detail = projections["cx_processing_run_detail"]
    workers = projections["workers"]
    worker_detail = projections["worker_detail"]
    trace_timeline = projections["trace_timeline"]
    expected_versions = {
        "sources": "ag_operation_source_readiness_projection.v1",
        "unified": "ag_unified_operations_projection.v1",
        "event_taxonomy": "ag_operational_event_taxonomy_projection.v1",
        "events": "ag_operational_event_projection.v1",
        "event_detail": "ag_operational_event_detail_projection.v1",
        "logs": "ag_service_log_projection.v1",
        "log_detail": "ag_service_log_detail_projection.v1",
        "log_policy": "ag_service_log_query_policy_projection.v1",
        "log_retention_dry_run": "ag_service_log_retention_dry_run_projection.v1",
        "log_retention_history": "ag_service_log_retention_history_projection.v1",
        "jobs": "ag_job_operations_projection.v1",
        "cx_processing_runs": "ag_cx_processing_run_operations_projection.v1",
        "cx_processing_run_detail": "ag_cx_processing_run_detail_projection.v1",
        "job_detail": "ag_job_operation_detail_projection.v1",
        "workers": "ag_worker_runtime_projection.v1",
        "worker_detail": "ag_worker_detail_projection.v1",
        "trace_timeline": "ag_cross_service_trace_timeline_projection.v1",
        "rollups": "ag_operations_rollup_metrics_projection.v1",
        "dashboard": "ag_operations_dashboard_snapshot_projection.v1",
        "issue_candidates": "ag_operations_issue_candidate_projection.v1",
    }
    return {
        "projection_versions": all(
            projections[name].get("projection_schema_version") == version
            for name, version in expected_versions.items()
        ),
        "source_ready": projections["sources"]["sources"][0]["readiness_status"] == "READY",
        "unified_jobs_and_events_visible": (
            projections["unified"]["jobs"]["summary"]["total"] == 2
            and projections["unified"]["events"]["summary"]["total"] == 2
        ),
        "event_detail_redacted": "private" not in json.dumps(
            event_detail,
            ensure_ascii=False,
        ),
        "service_logs_visible_and_redacted": (
            logs["logs"][0]["log_id"] == "smoke-log-cx-001"
            and log_detail["log"]["log_id"] == "smoke-log-mo-001"
            and "private" not in json.dumps(log_detail, ensure_ascii=False)
        ),
        "service_log_policy_visible": (
            log_policy["policy"]["query"]["max_limit"] == 500
            and log_policy["policy"]["retention"]["default_retention_days"] == 30
            and log_policy["policy"]["retention"]["purge_execution"]
            == "service_local_control_api"
        ),
        "service_log_retention_dry_run_visible": (
            log_retention_dry_run["dry_run"]["delete_enabled"] is False
            and log_retention_dry_run["policy"]["retention"]["default_retention_days"]
            == 30
            and log_retention_dry_run["source_statuses"]["nex-cx"]["status"]
            == "READY"
        ),
        "service_log_retention_history_visible": (
            log_retention_history["projection_status"] == "READY"
            and log_retention_history["filters"]["mode"] == "EXECUTE"
            and log_retention_history["filters"]["execution_status"] == "SUCCEEDED"
            and log_retention_history["retention_history"][0]["execution_id"]
            == "smoke-retention-execution-cx-001"
            and log_retention_history["summary"]["total"] == 1
            and log_retention_history["summary"]["deleted_count"] == 1
        ),
        "job_detail_timeline_ready": (
            job_detail["lifecycle_timeline"]["timeline_status"] == "READY"
        ),
        "cx_processing_runs_visible_and_redacted": (
            cx_processing_runs["summary"]["total"] == 2
            and cx_processing_runs["summary"]["failed_count"] == 1
            and cx_processing_run_detail["processing_run"]["pipeline_run_id"]
            == "smoke-processing-run-cx-002"
            and cx_processing_run_detail["summary"]["error_hash_count"] == 1
            and "provider_unavailable" in json.dumps(
                cx_processing_run_detail,
                ensure_ascii=False,
            )
            and "SECRET" not in json.dumps(cx_processing_run_detail, ensure_ascii=False)
        ),
        "worker_runtime_visible": (
            workers["workers"][0]["worker_id"] == "smoke-worker-cx-001"
            and workers["workers"][0]["active_job_id"] == "smoke-job-cx-001"
        ),
        "worker_detail_correlates_job_event": (
            worker_detail["worker"]["worker_id"] == "smoke-worker-cx-001"
            and worker_detail["active_job"]["job_id"] == "smoke-job-cx-001"
            and worker_detail["worker_lifecycle_timeline"]["events"][0]["event_id"]
            == "smoke-event-cx-worker-001"
            and worker_detail["summary"]["source_statuses"]
            == {"workers": "READY", "jobs": "READY", "events": "READY"}
        ),
        "trace_timeline_mixes_jobs_events_logs": {
            item["timeline_item_type"]
            for item in trace_timeline["timeline"]
        } == {"job", "event", "log", "retrieval_package"}
        and trace_timeline["log_source_statuses"]["nex-cx"]["status"] == "READY"
        and trace_timeline["retrieval_package_source_statuses"]["nex-cx"]["status"]
        == "READY",
        "rollup_counts": (
            projections["rollups"]["rollups"][0]["jobs"]["total"] == 2
            and projections["rollups"]["rollups"][0]["events"]["total"] == 2
            and projections["rollups"]["rollups"][0]["logs"]["total"] == 1
            and projections["rollups"]["log_source_statuses"]["nex-cx"]["status"]
            == "READY"
        ),
        "dashboard_failure_and_active_jobs": (
            dashboard["recent_failures"]["jobs"][0]["job_id"] == "smoke-job-cx-002"
            and dashboard["replay_candidates"][0]["job_id"] == "smoke-job-cx-002"
            and dashboard["replay_candidates"][0]["control_path"]
            == "/admin/v1/operations/jobs/nex-cx/smoke-job-cx-002/replay"
            and dashboard["active_jobs"][0]["job_id"] == "smoke-job-cx-001"
        ),
        "dashboard_cx_processing_runs_visible": (
            dashboard["cx_processing_runs"]["summary"]["total"] == 2
            and dashboard["cx_processing_runs"]["summary"]["failed_count"] == 1
            and dashboard["cx_processing_runs"]["recent_failures"][0][
                "pipeline_run_id"
            ]
            == "smoke-processing-run-cx-002"
            and dashboard["cx_processing_runs"]["active"][0]["pipeline_run_id"]
            == "smoke-processing-run-cx-001"
            and dashboard["cx_processing_runs"]["source_statuses"]["nex-cx"][
                "status"
            ]
            == "READY"
        ),
        "dashboard_retrieval_threshold_decisions_visible": (
            dashboard["retrieval_threshold_decisions"]["summary"][
                "total_decisions"
            ]
            == 2
            and dashboard["retrieval_threshold_decisions"]["summary"][
                "observed_sample_count"
            ]
            == 1
            and dashboard["retrieval_threshold_decisions"]["source_statuses"][
                "nex-cx"
            ]["status"]
            == "READY"
        ),
        "issue_candidates_include_failed_and_active": {
            candidate["rule_id"]
            for candidate in issue_candidates["issue_candidates"]
        } == {
            "failed_jobs_present.v1",
            "dead_letter_replay_available.v1",
            "active_jobs_review.v1",
            "retrieval_threshold_live_samples_insufficient.v1",
        },
    }


def _projection_counts(projections: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {
        "sources": len(projections["sources"]["sources"]),
        "events": len(projections["events"]["events"]),
        "logs": len(projections["logs"]["logs"]),
        "retention_history": len(
            projections["log_retention_history"]["retention_history"]
        ),
        "jobs": len(projections["jobs"]["jobs"]),
        "cx_processing_runs": len(
            projections["cx_processing_runs"]["processing_runs"]
        ),
        "cx_processing_run_steps": len(
            projections["cx_processing_run_detail"]["processing_run"]["steps"]
        ),
        "workers": len(projections["workers"]["workers"]),
        "worker_detail_events": len(
            projections["worker_detail"]["worker_lifecycle_timeline"]["events"]
        ),
        "trace_timeline": len(projections["trace_timeline"]["timeline"]),
        "rollups": len(projections["rollups"]["rollups"]),
        "dashboard_degraded_sources": len(projections["dashboard"]["degraded_sources"]),
        "dashboard_replay_candidates": len(
            projections["dashboard"]["replay_candidates"]
        ),
        "threshold_decisions": len(
            projections["dashboard"]["retrieval_threshold_decisions"][
                "threshold_decisions"
            ]
        ),
        "issue_candidates": len(projections["issue_candidates"]["issue_candidates"]),
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        counts = evidence["counts"]
        return (
            "ag_operations_dashboard_smoke=pass "
            f"endpoints={evidence['endpoint_count']} "
            f"jobs={counts['jobs']} workers={counts['workers']} "
            f"processing_runs={counts['cx_processing_runs']} "
            f"threshold_decisions={counts['threshold_decisions']} "
            f"events={counts['events']} "
            f"logs={counts['logs']} "
            f"history={counts['retention_history']} "
            f"issues={counts['issue_candidates']}"
        )
    return "ag_operations_dashboard_smoke=fail"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run mock-first AG operations dashboard smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_operations_dashboard_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
