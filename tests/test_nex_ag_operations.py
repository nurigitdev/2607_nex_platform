from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

import nex_ag.operations as ag_operations
from nex_ag.operations import (
    AG_SERVICE_LOG_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION,
    AG_SERVICE_LOG_RETENTION_DISPATCH_SCHEMA_VERSION,
    AG_SERVICE_LOG_RETENTION_EVENT_FAILED,
    AG_SERVICE_LOG_RETENTION_EVENT_SUCCEEDED,
    AG_JOB_CONTROL_DISPATCH_SCHEMA_VERSION,
    AG_OPERATIONS_SOURCE_MODE_ENV,
    AG_OPERATIONS_SOURCE_PROFILE_ENV,
    AG_OPERATIONS_SOURCE_SERVICES_ENV,
    OperationsQueryError,
    OperationsSourceConfigError,
    OperationsSource,
    OperationsSourceRegistry,
    RegistryServiceLogStore,
    RegistryOperationalEventStore,
    ReadOnlyJobQueue,
    ReadOnlyOperationalEventStore,
    ReadOnlyServiceLogStore,
    ReadOnlyWorkerHeartbeatStore,
    ag_operations_source_database_env,
    attach_ag_operations_source_runtime,
    build_ag_operations_source_runtime,
    build_cross_service_trace_timeline_projection,
    build_job_operation_detail_projection,
    build_job_control_dispatch_projection,
    build_generation_quality_issue_detail_projection,
    build_job_operations_projection,
    build_operation_query_options,
    build_operation_source_readiness_projection,
    build_operations_dashboard_snapshot_projection,
    build_operations_issue_candidate_projection,
    build_operations_rollup_metrics_projection,
    build_operations_source_registry,
    build_worker_detail_projection,
    build_worker_runtime_projection,
    build_operational_event_detail_projection,
    build_operational_event_taxonomy_projection,
    build_operational_event_projection,
    build_operations_issue_candidates,
    build_service_log_detail_projection,
    build_service_log_retention_dispatch_projection,
    build_service_log_retention_history_projection,
    build_service_log_query_policy_projection,
    build_service_log_projection,
    build_service_log_retention_dry_run_projection,
    build_unified_operations_projection,
    normalize_operation_event_search_query,
    normalize_operation_log_search_query,
    normalize_service_log_retention_days,
    normalize_operation_cursor,
    normalize_operation_sort,
    normalize_operation_timestamp,
    normalize_ag_operations_source_mode,
    normalize_ag_operations_source_profile,
    normalize_dashboard_recent_limit,
    operations_issue_candidate_rules,
    register_job_operation_routes,
    register_operation_source_readiness_routes,
    register_operational_event_taxonomy_routes,
    register_operational_event_routes,
    register_service_log_routes,
    register_unified_operation_routes,
    select_ag_operations_source_service_ids,
    summarize_operation_source_readiness,
    summarize_job_operations,
    summarize_operations_issue_candidates,
    summarize_operations_rollup_metrics,
    summarize_trace_timeline_items,
    _filter_records_by_operation_time,
    _dashboard_generation_remediation_section,
    _dashboard_generation_quality_section,
    _dashboard_remediation_execution_section,
    _dashboard_replay_candidates,
    _dashboard_timestamp,
    _issue_candidates_from_generation_quality,
    _issue_candidates_from_remediation_executions,
    _job_error_code,
    _nullable_string,
    _operational_event_matches_query,
    _operation_record_timestamp,
    _safe_optional_int,
    _service_log_matches_query,
    service_log_query_policy,
)
from nex_ag.generation_remediation import GenerationRemediationTaskStore
from nex_ag.job_control import AgJobControlError
from nex_ag.retrieval_operations import (
    InMemoryRetrievalPackageOperationsStore,
    RetrievalPackageOperationsError,
)
from nex_ag.processing_operations import (
    CxProcessingRunOperationsError,
    InMemoryCxProcessingRunOperationsStore,
)
from nex_ag.remediation_execution_operations import (
    InMemoryRemediationExecutionOperationsStore,
    build_remediation_execution_operations_projection,
)
from nex_ag.service_log_retention import AgServiceLogRetentionError
from nex_runtime import (
    AG_JOB_CONTROL_EVENT_FAILED,
    AG_JOB_CONTROL_EVENT_SUCCEEDED,
    CX_PROCESSING_EVENT_FAILED,
    CX_PROCESSING_EVENT_STARTED,
    FAILED,
    InMemoryOperationalEventStore,
    InMemoryJobQueue,
    InMemoryServiceLogStore,
    InMemoryWorkerHeartbeatStore,
    JobQueueError,
    OperationalEventError,
    RUNNING,
    SERVICE_SPECS,
    SUCCEEDED,
    ServiceLogError,
    WorkerHeartbeatError,
    build_common_job,
    build_operational_event,
    build_service_app,
    build_service_log_entry,
    build_subject_ref,
    build_worker_heartbeat,
    issue_mock_service_token,
    normalize_job_limit,
)

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
CONTRACT_ROOT = Path(__file__).parents[1] / "contracts"


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {"Authorization": f"Bearer {issued.access_token}"}


def retrieval_package_record(
    *,
    retrieval_package_id: str = "retrieval-package-001",
    trace_id: str = TRACE_ID,
    created_at: str = "2026-08-05T00:00:02Z",
) -> dict[str, object]:
    return {
        "retrieval_package_id": retrieval_package_id,
        "package_hash": "a" * 64,
        "status": "READY",
        "trace_id": trace_id,
        "request_id": REQUEST_ID,
        "query_text_sha256": "b" * 64,
        "query_text_preview": "bounded query preview",
        "query_embedding_provided": True,
        "query_embedding_sha256": "c" * 64,
        "query_embedding_dimension": 3,
        "purpose": "grounded_answer",
        "retrieval_policy_id": "weighted_rrf_vector_bm25_v1",
        "retrieval_policy_version": "2026-08-09",
        "retrieval_policy_hash": "d" * 64,
        "retrieval_policy_source": "ag_registry_active",
        "ranker_mix": "weighted_rrf_vector_bm25_v1",
        "rerank_state": "NOT_APPLIED",
        "permission_snapshot_hash": "e" * 64,
        "source_summary": {"source_count": 1},
        "score_summary": {"best_score": 0.92},
        "warning_count": 0,
        "evidence_count": 2,
        "no_answer_reason": None,
        "created_at": created_at,
        "updated_at": created_at,
    }


def cx_processing_run_record(
    *,
    pipeline_run_id: str = "processing-run-001",
    status: str = "FAILED",
    updated_at: str = "2026-08-05T00:00:06Z",
    step_failed: int = 1,
    job_retryable: bool = True,
) -> dict[str, object]:
    return {
        "pipeline_run_id": pipeline_run_id,
        "pipeline_schema_version": "cx_document_processing_pipeline.v1",
        "document_id": "doc-001",
        "status": status,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "job_id": f"job-{pipeline_run_id}",
        "job_type": "cx.document_processing",
        "job_status": status,
        "job_attempt_count": 1,
        "job_max_attempts": 3,
        "job_retryable": job_retryable,
        "job_subject_ref": {"type": "cx.document", "id": "doc-001"},
        "job_links": {},
        "step_total": 2,
        "step_succeeded": 1 if step_failed else 2,
        "step_skipped": 0,
        "step_failed": step_failed,
        "queued_at": "2026-08-05T00:00:01Z",
        "started_at": "2026-08-05T00:00:02Z",
        "completed_at": updated_at if status in {"SUCCEEDED", "FAILED"} else None,
        "updated_at": updated_at,
        "steps": [],
    }


def generation_audit_projection_record(
    *,
    cx_generation_id: str = "cx-gen-001",
    coverage_status: str = "PASS",
    boundary_status: str = "PASS",
    issue_codes: list[str] | None = None,
    created_at: str = "2026-08-05T00:00:08Z",
) -> dict[str, object]:
    return {
        "projection_schema_version": "ag_generation_audit_projection.v1",
        "cx_generation_id": cx_generation_id,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "created_at": created_at,
        "grounded_response_quality": {
            "projection_schema_version": (
                "ag_generation_audit_grounded_response_quality_projection.v1"
            ),
            "gap_audit_schema_version": (
                "ag_generation_audit_grounded_response_quality_gap_audit.v1"
            ),
            "source_audit_schema_version": (
                "cx_grounded_response_citation_quality_audit.v1"
            ),
            "coverage_status": coverage_status,
            "boundary_status": boundary_status,
            "grounding_required": True,
            "citation_status": "VALIDATED",
            "source_quality_issue_count": 0 if boundary_status != "FAIL" else 1,
            "projection_issue_count": len(issue_codes or []),
            "issue_codes": issue_codes or [],
            "lineage_mismatches": [],
            "recommended_action": (
                "investigate_quality_failure"
                if boundary_status == "FAIL"
                else (
                    "wire_ag_quality_projection"
                    if coverage_status == "PASS"
                    else "complete_source_quality_metadata"
                )
            ),
            "retrieval_package_id": "cx-ret-001",
            "retrieval_package_hash": "d" * 64,
            "structured_draft_id": "draft-001",
            "evidence_ref_count": 2,
            "artifact_handoff_quality_available": True,
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
    }


def generation_remediation_task_record(
    *,
    remediation_action_id: str = "ag-remediation-dashboard-001",
    cx_generation_id: str = "cx-gen-remediation",
    action_type: str = "citation_repair",
    action_status: str = "ASSIGNED",
    priority: str = "HIGH",
    updated_at: str = "2026-08-05T00:00:09Z",
) -> dict[str, object]:
    return {
        "action_schema_version": "ag_generation_remediation_action.v1",
        "remediation_action_id": remediation_action_id,
        "cx_generation_id": cx_generation_id,
        "tenant_id": "local-tenant",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "action_type": action_type,
        "action_status": action_status,
        "priority": priority,
        "owner_ref": {
            "owner_type": "service",
            "owner_id": "nex-cx",
            "tenant_id": "local-tenant",
        },
        "reason_codes": ["citation_quality"],
        "source_refs": [
            {
                "source_service": "nex-ag",
                "ref_type": "generation_quality",
                "ref_id": cx_generation_id,
                "relation": "caused_by",
            }
        ],
        "evidence": {
            "evidence_hashes": ["a" * 64],
            "evidence_previews": ["Citation quality needs a bounded repair task."],
        },
        "result_ref": None,
        "metadata": {"source": "unit_test"},
        "created_at": "2026-08-05T00:00:08Z",
        "updated_at": updated_at,
    }


def remediation_execution_record(
    *,
    remediation_action_id: str = "ag-remediation-dashboard-001",
    parent_cx_generation_id: str = "cx-gen-remediation",
    execution_status: str = "SUCCEEDED",
    attempt_no: int = 1,
    updated_at: str = "2026-08-05T00:00:10Z",
) -> dict[str, object]:
    return {
        "result_schema_version": "cx_remediation_execution_result.v1",
        "remediation_action_id": remediation_action_id,
        "parent_cx_generation_id": parent_cx_generation_id,
        "root_cx_generation_id": parent_cx_generation_id,
        "repair_cx_generation_id": f"{parent_cx_generation_id}-repair",
        "tenant_id": "local-tenant",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "action_type": "citation_repair",
        "lineage_type": "repair",
        "execution_status": execution_status,
        "attempt_no": attempt_no,
        "result_ref": {
            "artifact_type": "structured_draft",
            "artifact_id": "draft-repair-001",
            "uri": "memory://draft-repair-001",
        },
        "failure": (
            {
                "error_code": "cx.remediation.execution_failed",
                "error_detail_sha256": "b" * 64,
                "retryable": True,
            }
            if execution_status == "FAILED"
            else None
        ),
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
        "metadata": {"source": "unit_test"},
        "created_at": "2026-08-05T00:00:09Z",
        "updated_at": updated_at,
    }


def ag_operations_projection_schema() -> dict[str, object]:
    schema_path = (
        CONTRACT_ROOT
        / "schemas"
        / "service"
        / "nex_ag"
        / "operations_projection.v1.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def ag_generation_quality_issue_detail_projection_schema() -> dict[str, object]:
    schema_path = (
        CONTRACT_ROOT
        / "schemas"
        / "generation"
        / "ag_generation_quality_issue_detail_projection.v1.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def assert_ag_operations_projection_contract(payload: dict[str, object]) -> None:
    Draft202012Validator(ag_operations_projection_schema()).validate(payload)


def build_store() -> InMemoryOperationalEventStore:
    store = InMemoryOperationalEventStore()
    store.append(
        build_operational_event(
            event_id="event-001",
            service_id="nex-cx",
            event_type="cx.processing.completed",
            severity="INFO",
            message="Document processing completed.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            subject_ref={"type": "cx.document", "id": "doc-001"},
            details={"pipeline_run_id": "run-001"},
            created_at="2026-08-05T00:00:00Z",
        )
    )
    store.append(
        build_operational_event(
            event_id="event-002",
            service_id="nex-mo",
            event_type="mo.provider.failed",
            severity="ERROR",
            message="Provider request failed.",
            trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            request_id=REQUEST_ID,
            subject_ref={"type": "mo.provider", "id": "embedding"},
            details={"authorization": "Bearer private"},
            created_at="2026-08-05T00:00:01Z",
        )
    )
    return store


def build_log_store() -> InMemoryServiceLogStore:
    store = InMemoryServiceLogStore()
    store.append(
        build_service_log_entry(
            log_id="log-001",
            service_id="nex-cx",
            severity="INFO",
            logger_name="nex_runtime.worker_runner",
            message="Worker completed a job.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            job_id="job-cx-001",
            subject_ref={"type": "cx.document", "id": "doc-001"},
            attributes={"worker_id": "cx-worker-001", "attempt_count": 1},
            observed_at="2026-08-05T00:00:00Z",
        )
    )
    store.append(
        build_service_log_entry(
            log_id="log-002",
            service_id="nex-mo",
            severity="ERROR",
            logger_name="nex_mo.remote_provider",
            message="Provider request failed.",
            trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            request_id=REQUEST_ID,
            job_id="job-mo-001",
            subject_ref={"type": "mo.provider", "id": "generation"},
            attributes={"authorization": "Bearer private", "provider": "vllm"},
            observed_at="2026-08-05T00:00:01Z",
        )
    )
    return store


def build_log_stores() -> dict[str, InMemoryServiceLogStore]:
    combined = build_log_store()
    cx_store = InMemoryServiceLogStore()
    mo_store = InMemoryServiceLogStore()
    cx_store.append(combined.get_log("log-001"))
    mo_store.append(combined.get_log("log-002"))
    return {"nex-cx": cx_store, "nex-mo": mo_store}


def build_retention_log_stores() -> dict[str, InMemoryServiceLogStore]:
    cx_store = InMemoryServiceLogStore()
    cx_store.append(
        build_service_log_entry(
            log_id="log-retention-001",
            service_id="nex-cx",
            severity="ERROR",
            logger_name="nex_cx.worker",
            message="Expired log candidate.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            job_id="job-retention-001",
            subject_ref={"type": "cx.document", "id": "doc-retention-001"},
            attributes={"authorization": "Bearer old-private"},
            observed_at="2026-06-01T00:00:00Z",
        )
    )
    cx_store.append(
        build_service_log_entry(
            log_id="log-retention-002",
            service_id="nex-cx",
            severity="WARNING",
            logger_name="nex_cx.worker",
            message="Second expired log candidate.",
            trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            request_id=REQUEST_ID,
            job_id="job-retention-002",
            subject_ref={"type": "cx.document", "id": "doc-retention-002"},
            attributes={"attempt_count": 3},
            observed_at="2026-06-15T00:00:00Z",
        )
    )
    cx_store.append(
        build_service_log_entry(
            log_id="log-retention-fresh",
            service_id="nex-cx",
            severity="INFO",
            logger_name="nex_cx.worker",
            message="Fresh log outside retention deletion window.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            job_id="job-retention-fresh",
            subject_ref={"type": "cx.document", "id": "doc-retention-fresh"},
            attributes={"worker_id": "cx-worker-001"},
            observed_at="2026-08-04T00:00:00Z",
        )
    )
    return {"nex-cx": cx_store}


def build_retention_history_stores() -> dict[str, InMemoryServiceLogStore]:
    stores = build_retention_log_stores()
    cx_store = stores["nex-cx"]
    cx_store.record_retention_history(
        service_log_retention_execution_response(
            service_id="nex-cx",
            mode="EXECUTE",
            execution_status="SUCCEEDED",
            retention_cutoff="2026-07-06T00:00:00Z",
            checked_at="2026-08-05T00:00:00Z",
            candidate_count=2,
            deleted_count=1,
            delete_enabled=True,
            max_delete_count=1,
            execution_id="retention-execution-001",
            idempotency_key="purge-001",
        ),
        recorded_at="2026-08-05T00:00:02Z",
    )
    cx_store.record_retention_history(
        service_log_retention_execution_response(
            service_id="nex-cx",
            mode="DRY_RUN",
            execution_status="BLOCKED",
            retention_cutoff="2026-07-06T00:00:00Z",
            checked_at="2026-08-05T00:00:01Z",
            candidate_count=2,
            deleted_count=0,
            delete_enabled=False,
            max_delete_count=1,
            execution_id="retention-execution-002",
            idempotency_key="purge-002",
        ),
        recorded_at="2026-08-05T00:00:03Z",
    )
    return stores


def sample_job(**overrides):
    return build_common_job(
        job_id=overrides.pop("job_id", "job-001"),
        job_type=overrides.pop("job_type", "cx.document_processing"),
        trace_id=overrides.pop("trace_id", TRACE_ID),
        request_id=overrides.pop("request_id", REQUEST_ID),
        subject_ref=overrides.pop(
            "subject_ref", build_subject_ref("cx.document", "doc-001")
        ),
        idempotency_key=overrides.pop("idempotency_key", "idem-001"),
        created_at=overrides.pop("created_at", "2026-08-05T00:00:00Z"),
        max_attempts=overrides.pop("max_attempts", 2),
        status=overrides.pop("status", "QUEUED"),
        **overrides,
    )


def build_job_queues() -> dict[str, InMemoryJobQueue]:
    cx_queue = InMemoryJobQueue()
    cx_queue.enqueue(
        sample_job(
            job_id="job-cx-001",
            idempotency_key="idem-cx-001",
            created_at="2026-08-05T00:00:00Z",
        )
    )
    cx_running = cx_queue.start_job(
        "job-cx-001",
        updated_at="2026-08-05T00:00:03Z",
    )
    assert cx_running["status"] == RUNNING
    cx_queue.enqueue(
        sample_job(
            job_id="job-cx-002",
            idempotency_key="idem-cx-002",
            created_at="2026-08-05T00:00:01Z",
            max_attempts=1,
        )
    )
    cx_queue.start_job("job-cx-002", updated_at="2026-08-05T00:00:04Z")
    cx_queue.retry_job(
        "job-cx-002",
        error={
            "error_code": "cx.processing.failed",
            "detail": "Processing failed.",
        },
        failed_at="2026-08-05T00:00:05Z",
    )

    ae_queue = InMemoryJobQueue()
    ae_queue.enqueue(
        sample_job(
            job_id="job-ae-001",
            job_type="ae.artifact_render",
            subject_ref=build_subject_ref("ae.artifact", "artifact-001"),
            idempotency_key="idem-ae-001",
            created_at="2026-08-05T00:00:02Z",
        )
    )
    ae_queue.complete_job(
        ae_queue.start_job("job-ae-001", updated_at="2026-08-05T00:00:06Z")["job_id"],
        updated_at="2026-08-05T00:00:07Z",
    )
    return {
        "nex-cx": cx_queue,
        "nex-ae-api": ae_queue,
    }


class BrokenJobQueue:
    def list_jobs(self, *, job_type=None, status=None):
        raise JobQueueError(
            error_code="job.store_unavailable",
            detail="job queue store is unavailable",
            status_code=503,
        )

    def enqueue(self, job):
        raise AssertionError("not used")

    def get_job(self, job_id):
        raise AssertionError("not used")

    def start_job(self, job_id, *, updated_at=None):
        raise AssertionError("not used")

    def complete_job(self, job_id, *, updated_at=None):
        raise AssertionError("not used")

    def fail_job(self, job_id, *, updated_at=None):
        raise AssertionError("not used")

    def cancel_job(self, job_id, *, updated_at=None):
        raise AssertionError("not used")

    def claim_next_job(self, worker_id, *, job_type=None, updated_at=None):
        raise AssertionError("not used")


class UnavailableJobQueue(BrokenJobQueue):
    def get_job(self, job_id):
        raise JobQueueError(
            error_code="job.store_unavailable",
            detail="job queue store is unavailable",
            status_code=503,
        )


class RecordingJobControlClient:
    def __init__(self, *, error: AgJobControlError | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def get_job(self, service_id, job_id, *, request_id, trace_id):
        raise AssertionError("not used")

    def cancel_job(self, service_id, job_id, *, request_id, trace_id, observed_at=None):
        self.calls.append(
            {
                "action": "cancel",
                "service_id": service_id,
                "job_id": job_id,
                "request_id": request_id,
                "trace_id": trace_id,
                "observed_at": observed_at,
            }
        )
        if self.error is not None:
            raise self.error
        return service_job_control_response(
            service_id=service_id,
            job_id=job_id,
            action="cancel",
            status="CANCELLED",
        )

    def retry_job(
        self,
        service_id,
        job_id,
        *,
        request_id,
        trace_id,
        error_code=None,
        detail=None,
        observed_at=None,
    ):
        self.calls.append(
            {
                "action": "retry",
                "service_id": service_id,
                "job_id": job_id,
                "request_id": request_id,
                "trace_id": trace_id,
                "error_code": error_code,
                "detail": detail,
                "observed_at": observed_at,
            }
        )
        if self.error is not None:
            raise self.error
        return service_job_control_response(
            service_id=service_id,
            job_id=job_id,
            action="retry",
            status="QUEUED",
        )

    def replay_job(
        self,
        service_id,
        job_id,
        *,
        request_id,
        trace_id,
        replay_job_id,
        idempotency_key,
        requested_by,
        reason,
        observed_at=None,
    ):
        self.calls.append(
            {
                "action": "replay",
                "service_id": service_id,
                "job_id": job_id,
                "request_id": request_id,
                "trace_id": trace_id,
                "replay_job_id": replay_job_id,
                "idempotency_key": idempotency_key,
                "requested_by": requested_by,
                "reason": reason,
                "observed_at": observed_at,
            }
        )
        if self.error is not None:
            raise self.error
        return {
            **service_job_control_response(
                service_id=service_id,
                job_id=replay_job_id,
                action="replay",
                status="QUEUED",
            ),
            "replay": {
                "source_job_id": job_id,
                "replay_job_id": replay_job_id,
                "lineage": {
                    "lineage_schema_version": "job_replay_lineage.v1",
                    "source_job_id": job_id,
                    "requested_by": requested_by,
                    "reason": reason,
                    "replayed_at": observed_at,
                },
            },
        }


class RecordingServiceLogRetentionClient:
    def __init__(self, *, error: AgServiceLogRetentionError | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def purge_logs(
        self,
        service_id,
        *,
        request_id,
        trace_id,
        retention_cutoff,
        retention_days=None,
        checked_at=None,
        dry_run=True,
        delete_enabled=False,
        max_delete_count=None,
        requested_by=None,
        idempotency_key=None,
    ):
        self.calls.append(
            {
                "service_id": service_id,
                "request_id": request_id,
                "trace_id": trace_id,
                "retention_cutoff": retention_cutoff,
                "retention_days": retention_days,
                "checked_at": checked_at,
                "dry_run": dry_run,
                "delete_enabled": delete_enabled,
                "max_delete_count": max_delete_count,
                "requested_by": requested_by,
                "idempotency_key": idempotency_key,
            }
        )
        if self.error is not None:
            raise self.error
        return service_log_retention_execution_response(
            service_id=service_id,
            mode="DRY_RUN" if dry_run else "EXECUTE",
            execution_status="SUCCEEDED",
            retention_cutoff=retention_cutoff,
            checked_at=checked_at or "2026-08-05T00:00:00Z",
            candidate_count=2,
            deleted_count=1 if delete_enabled else 0,
            delete_enabled=delete_enabled,
            max_delete_count=max_delete_count or 100,
        )


def service_job_control_response(
    *,
    service_id: str,
    job_id: str,
    action: str,
    status: str,
) -> dict[str, object]:
    return {
        "job_control_schema_version": "service_job_control.v1",
        "service_id": service_id,
        "action": action,
        "job": {
            "service_id": service_id,
            "job_id": job_id,
            "job_type": "cx.document_processing",
            "status": status,
        },
        "controls": {
            "can_cancel": False,
            "can_retry": False,
            "can_replay": False,
            "terminal": status in {"SUCCEEDED", "FAILED", "CANCELLED"},
            "dead_lettered": False,
            "allowed_actions": ["read"],
        },
    }


def service_log_retention_execution_response(
    *,
    service_id: str,
    mode: str,
    execution_status: str,
    retention_cutoff: str,
    checked_at: str,
    candidate_count: int,
    deleted_count: int,
    delete_enabled: bool,
    max_delete_count: int,
    execution_id: str = "retention-execution-001",
    idempotency_key: str = "purge-001",
) -> dict[str, object]:
    return {
        "retention_execution_schema_version": "service_log_retention_execution.v1",
        "execution_id": execution_id,
        "policy_id": "service-log-query-retention-v1",
        "service_id": service_id,
        "mode": mode,
        "execution_status": execution_status,
        "delete_enabled": delete_enabled,
        "retention_days": 30,
        "retention_cutoff": retention_cutoff,
        "checked_at": checked_at,
        "scan_limit": 50,
        "max_delete_count": max_delete_count,
        "candidate_count": candidate_count,
        "deleted_count": deleted_count,
        "requested_by": {
            "actor_type": "service",
            "actor_id": "nex-ag",
            "service_id": "nex-ag",
        },
        "idempotency_key": idempotency_key,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "blocked_reason": None,
        "error": None,
        "audit": {
            "audit_event_type": "service_log.retention.execution",
            "audit_event_id": "retention-audit-001",
            "emitted": False,
        },
    }


class BrokenOperationalEventStore:
    def append(self, event):
        raise AssertionError("not used")

    def get_event(self, event_id):
        raise AssertionError("not used")

    def list_events(self, **kwargs):
        raise OperationalEventError(
            error_code="operational_event.store_unavailable",
            detail="operational event store is unavailable",
            status_code=503,
        )


class BrokenServiceLogStore:
    def append(self, entry):
        raise AssertionError("not used")

    def get_log(self, log_id):
        raise ServiceLogError(
            error_code="service_log.store_unavailable",
            detail="service log store is unavailable",
            status_code=503,
        )

    def list_logs(self, **kwargs):
        raise ServiceLogError(
            error_code="service_log.store_unavailable",
            detail="service log store is unavailable",
            status_code=503,
        )

    def record_retention_history(self, execution, *, recorded_at=None):
        raise AssertionError("not used")

    def get_retention_history(self, execution_id):
        raise ServiceLogError(
            error_code="service_log_retention_history.store_unavailable",
            detail="service log retention history store is unavailable",
            status_code=503,
        )

    def list_retention_history(self, **kwargs):
        raise ServiceLogError(
            error_code="service_log_retention_history.store_unavailable",
            detail="service log retention history store is unavailable",
            status_code=503,
        )


class BrokenRetrievalPackageStore:
    source_kind = "postgres-read"
    database_env = "NEX_CX_TEST_DATABASE_URL"
    redacted_database_url = "postgresql://nex_cx_user:***@localhost/nex_cx_test"

    def list_retrieval_packages(self, **kwargs):
        raise RetrievalPackageOperationsError(
            error_code="ag.retrieval_package_source_unavailable",
            detail="retrieval package source is unavailable",
        )


class BrokenCxProcessingRunStore:
    source_kind = "postgres-read"
    database_env = "NEX_CX_TEST_DATABASE_URL"
    redacted_database_url = "postgresql://nex_cx_user:***@localhost/nex_cx_test"

    def list_processing_runs(self, **kwargs):
        raise CxProcessingRunOperationsError(
            error_code="ag.cx_processing_run_source_unavailable",
            detail="CX processing run source is unavailable.",
        )


class BrokenWorkerHeartbeatStore:
    def upsert_heartbeat(self, heartbeat):
        raise AssertionError("not used")

    def get_heartbeat(self, service_id, worker_id):
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.store_unavailable",
            detail="worker heartbeat store is unavailable",
            status_code=503,
        )

    def list_heartbeats(self, *, service_id=None, worker_type=None, status=None):
        raise WorkerHeartbeatError(
            error_code="worker_heartbeat.store_unavailable",
            detail="worker heartbeat store is unavailable",
            status_code=503,
        )


def build_event_stores() -> dict[str, InMemoryOperationalEventStore]:
    cx_store = InMemoryOperationalEventStore()
    cx_store.append(
        build_operational_event(
            event_id="event-cx-001",
            service_id="nex-cx",
            event_type="cx.processing.succeeded",
            severity="INFO",
            message="Document processing succeeded.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            subject_ref={"type": "cx.document", "id": "doc-001"},
            details={"pipeline_run_id": "run-001"},
            created_at="2026-08-05T00:00:00Z",
        )
    )
    mo_store = InMemoryOperationalEventStore()
    mo_store.append(
        build_operational_event(
            event_id="event-mo-001",
            service_id="nex-mo",
            event_type="mo.provider.failed",
            severity="ERROR",
            message="Provider request failed.",
            trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            request_id=REQUEST_ID,
            subject_ref={"type": "mo.provider", "id": "reranker"},
            details={"service_token": "private"},
            created_at="2026-08-05T00:00:01Z",
        )
    )
    return {"nex-cx": cx_store, "nex-mo": mo_store}


def build_worker_lifecycle_event_stores() -> dict[str, InMemoryOperationalEventStore]:
    cx_store = InMemoryOperationalEventStore()
    cx_store.append(
        build_operational_event(
            event_id="event-cx-worker-001",
            service_id="nex-cx",
            event_type="cx.worker.lifecycle.busy",
            severity="INFO",
            message="CX processing worker started job.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            subject_ref={"type": "worker", "id": "cx-worker-001"},
            details={
                "worker_id": "cx-worker-001",
                "worker_type": "cx.document_processing.worker",
                "worker_status": "BUSY",
                "active_job_id": "job-cx-001",
                "job_id": "job-cx-001",
            },
            created_at="2026-08-05T00:00:04Z",
        )
    )
    cx_store.append(
        build_operational_event(
            event_id="event-cx-worker-unrelated",
            service_id="nex-cx",
            event_type="cx.worker.lifecycle.idle",
            severity="INFO",
            message="Another worker is idle.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            subject_ref={"type": "worker", "id": "cx-worker-other"},
            details={"worker_id": "cx-worker-other"},
            created_at="2026-08-05T00:00:05Z",
        )
    )
    return {"nex-cx": cx_store}


def build_worker_heartbeat_stores() -> dict[str, InMemoryWorkerHeartbeatStore]:
    cx_store = InMemoryWorkerHeartbeatStore()
    cx_store.upsert_heartbeat(
        build_worker_heartbeat(
            service_id="nex-cx",
            worker_id="cx-worker-001",
            worker_type="cx.document_processing.worker",
            status="BUSY",
            active_job_id="job-cx-001",
            trace_id=TRACE_ID,
            started_at="2026-08-05T00:00:00Z",
            last_seen_at="2026-08-05T00:00:10Z",
            metadata={"queue": "cx.document_processing"},
        )
    )
    cx_store.upsert_heartbeat(
        build_worker_heartbeat(
            service_id="nex-cx",
            worker_id="cx-worker-002",
            worker_type="cx.document_processing.worker",
            status="IDLE",
            active_job_id=None,
            trace_id=None,
            started_at="2026-08-05T00:00:00Z",
            last_seen_at="2026-08-05T00:01:00Z",
            metadata={"queue": "cx.document_processing"},
        )
    )
    mo_store = InMemoryWorkerHeartbeatStore()
    mo_store.upsert_heartbeat(
        build_worker_heartbeat(
            service_id="nex-mo",
            worker_id="mo-worker-001",
            worker_type="mo.provider.worker",
            status="IDLE",
            active_job_id=None,
            trace_id=None,
            started_at="2026-08-05T00:00:00Z",
            last_seen_at="2026-08-05T00:00:45Z",
            metadata={"provider_family": "embedding"},
        )
    )
    return {"nex-cx": cx_store, "nex-mo": mo_store}


def test_ag_operations_source_config_helpers_normalize_runtime_inputs() -> None:
    assert normalize_ag_operations_source_mode(None) == "memory"
    assert normalize_ag_operations_source_mode("postgresql") == "postgres"
    assert normalize_ag_operations_source_profile(None) == "dev"
    assert normalize_ag_operations_source_profile("TEST") == "test"
    assert ag_operations_source_database_env("nex-cx") == "NEX_CX_DATABASE_URL"
    assert (
        ag_operations_source_database_env("nex-cx", profile="test")
        == "NEX_CX_TEST_DATABASE_URL"
    )
    assert select_ag_operations_source_service_ids("nex-cx,nex-ae-api,nex-cx") == (
        "nex-ae-api",
        "nex-cx",
    )
    assert select_ag_operations_source_service_ids(None) == tuple(sorted(SERVICE_SPECS))


def test_operation_query_options_normalize_sort_cursor_and_timestamps() -> None:
    options = build_operation_query_options(
        limit=9999,
        since="2026-08-05T00:00:00+09:00",
        until="2026-08-05T00:00:01Z",
        sort="ASC",
        cursor="002",
    )

    assert options.limit == 500
    assert options.since == "2026-08-04T15:00:00Z"
    assert options.until == "2026-08-05T00:00:01Z"
    assert options.sort == "asc"
    assert options.cursor == "2"
    assert options.offset == 2
    assert options.to_filter_dict() == {
        "limit": 500,
        "since": "2026-08-04T15:00:00Z",
        "until": "2026-08-05T00:00:01Z",
        "sort": "asc",
        "cursor": "2",
    }
    assert options.pagination(total=4, returned=2)["next_cursor"] is None


@pytest.mark.parametrize(
    "operation, expected_code",
    [
        (lambda: normalize_operation_sort("latest"), "ag.operation_sort_invalid"),
        (lambda: normalize_operation_cursor("-1"), "ag.operation_cursor_invalid"),
        (lambda: normalize_operation_cursor("abc"), "ag.operation_cursor_invalid"),
        (
            lambda: normalize_operation_timestamp("not-a-date", field_name="since"),
            "ag.operation_timestamp_invalid",
        ),
        (
            lambda: build_operation_query_options(
                limit=10,
                since="2026-08-05T00:00:02Z",
                until="2026-08-05T00:00:01Z",
            ),
            "ag.operation_time_window_invalid",
        ),
    ],
)
def test_operation_query_options_reject_invalid_inputs(
    operation, expected_code
) -> None:
    with pytest.raises(OperationsQueryError) as exc_info:
        operation()

    assert exc_info.value.error_code == expected_code


def test_operation_query_helpers_cover_timestamp_fallback_edges() -> None:
    options = build_operation_query_options(
        limit=10,
        since="2026-08-05T00:00:00",
        until="2026-08-05T00:00:01Z",
    )
    records = [
        {"record_id": "missing"},
        {"record_id": "fallback", "created_at": "2026-08-05T00:00:01Z"},
        {"record_id": "too-new", "updated_at": "2026-08-05T00:00:02Z"},
    ]

    assert options.since == "2026-08-05T00:00:00Z"
    assert (
        _operation_record_timestamp(
            {"created_at": "2026-08-05T00:00:01Z"},
            timestamp_field="updated_at",
        )
        .isoformat()
        .endswith("+00:00")
    )
    assert _operation_record_timestamp({}, timestamp_field="updated_at").year == 1
    assert [
        record["record_id"]
        for record in _filter_records_by_operation_time(
            records,
            options,
            timestamp_field="updated_at",
        )
    ] == ["fallback"]


@pytest.mark.parametrize(
    "operation",
    [
        lambda queue, job: queue.enqueue(job),
        lambda queue, job: queue.start_job(job["job_id"]),
        lambda queue, job: queue.complete_job(job["job_id"]),
        lambda queue, job: queue.fail_job(job["job_id"]),
        lambda queue, job: queue.cancel_job(job["job_id"]),
        lambda queue, job: queue.claim_next_job("ag-reader"),
    ],
)
def test_read_only_job_queue_allows_reads_and_rejects_writes(operation) -> None:
    delegate = InMemoryJobQueue()
    job = delegate.enqueue(
        sample_job(
            job_id="job-read-only-001",
            idempotency_key="idem-read-only-001",
        )
    )
    queue = ReadOnlyJobQueue(delegate)

    assert queue.get_job("job-read-only-001") == job
    assert [stored["job_id"] for stored in queue.list_jobs()] == ["job-read-only-001"]
    with pytest.raises(JobQueueError, match="read-only"):
        operation(queue, job)


def test_read_only_operational_event_store_allows_reads_and_rejects_append() -> None:
    delegate = build_event_stores()["nex-cx"]
    store = ReadOnlyOperationalEventStore(delegate)

    event = store.get_event("event-cx-001")
    assert event is not None
    assert event["event_id"] == "event-cx-001"
    assert [
        stored["event_id"] for stored in store.list_events(service_id="nex-cx")
    ] == ["event-cx-001"]
    with pytest.raises(OperationalEventError, match="read-only"):
        store.append(event)


def test_read_only_service_log_store_allows_reads_and_rejects_append() -> None:
    delegate = build_log_stores()["nex-cx"]
    store = ReadOnlyServiceLogStore(delegate)

    entry = store.get_log("log-001")
    assert entry is not None
    assert entry["log_id"] == "log-001"
    assert [stored["log_id"] for stored in store.list_logs(service_id="nex-cx")] == [
        "log-001"
    ]
    with pytest.raises(ServiceLogError, match="read-only"):
        store.append(entry)


def test_read_only_worker_heartbeat_store_allows_reads_and_rejects_writes() -> None:
    delegate = build_worker_heartbeat_stores()["nex-cx"]
    store = ReadOnlyWorkerHeartbeatStore(delegate)

    heartbeat = store.get_heartbeat("nex-cx", "cx-worker-001")
    assert heartbeat is not None
    assert heartbeat["worker_id"] == "cx-worker-001"
    assert [
        item["worker_id"] for item in store.list_heartbeats(service_id="nex-cx")
    ] == [
        "cx-worker-001",
        "cx-worker-002",
    ]
    with pytest.raises(WorkerHeartbeatError, match="read-only"):
        store.upsert_heartbeat(heartbeat)


def test_ag_operations_source_runtime_defaults_to_memory_without_registry() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])

    runtime = attach_ag_operations_source_runtime(app, environ={})

    assert runtime.mode == "memory"
    assert runtime.profile == "dev"
    assert runtime.registry is None
    assert app.state.nex_ag_operations_source_runtime is runtime
    assert runtime.to_summary()["registry"] is None


def test_ag_operations_source_runtime_builds_postgres_read_only_registry() -> None:
    engine_calls: list[dict[str, str]] = []
    session_calls: list[object] = []

    def fake_engine_factory(database_url: str, *, pool_settings: object) -> object:
        engine_calls.append(
            {
                "database_url": database_url,
                "service_id": pool_settings.service_id,
                "workload": pool_settings.workload,
            }
        )
        return SimpleNamespace(database_url=database_url, pool_settings=pool_settings)

    def fake_session_factory_builder(engine: object) -> object:
        session_calls.append(engine)
        return (
            f"session:{engine.pool_settings.service_id}:{engine.pool_settings.workload}"
        )

    runtime = build_ag_operations_source_runtime(
        environ={
            AG_OPERATIONS_SOURCE_MODE_ENV: "postgres",
            AG_OPERATIONS_SOURCE_PROFILE_ENV: "test",
            AG_OPERATIONS_SOURCE_SERVICES_ENV: "nex-cx,nex-ae-api,nex-cx",
            "NEX_CX_TEST_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
            "NEX_AE_TEST_DATABASE_URL": "postgresql://nex_ae_user:secret@localhost/nex_ae_test",
        },
        engine_factory=fake_engine_factory,
        session_factory_builder=fake_session_factory_builder,
    )

    assert runtime.mode == "postgres"
    assert runtime.profile == "test"
    assert runtime.selected_service_ids == ("nex-ae-api", "nex-cx")
    assert runtime.registry is not None
    assert [call["service_id"] for call in engine_calls] == [
        "nex-ae-api",
        "nex-ae-api",
        "nex-cx",
        "nex-cx",
    ]
    assert [call["workload"] for call in engine_calls] == [
        "api",
        "worker",
        "api",
        "worker",
    ]
    assert len(session_calls) == 4

    source = runtime.registry.get("nex-cx")
    assert source is not None
    assert source.source_kind == "postgres-read"
    assert source.database_env == "NEX_CX_TEST_DATABASE_URL"
    assert source.to_summary()["redacted_database_url"].endswith(
        "nex_cx_user:***@localhost/nex_cx_test"
    )
    assert isinstance(source.job_queue, ReadOnlyJobQueue)
    assert isinstance(source.operational_event_store, ReadOnlyOperationalEventStore)
    assert isinstance(source.service_log_store, ReadOnlyServiceLogStore)
    assert isinstance(source.worker_heartbeat_store, ReadOnlyWorkerHeartbeatStore)
    with pytest.raises(JobQueueError, match="read-only"):
        source.job_queue.enqueue(
            sample_job(
                job_id="job-runtime-read-only",
                idempotency_key="idem-runtime-read-only",
            )
        )
    with pytest.raises(ServiceLogError, match="read-only"):
        source.service_log_store.append(build_log_store().get_log("log-001"))


def test_operation_source_readiness_projection_reports_default_memory_runtime() -> None:
    runtime = build_ag_operations_source_runtime(environ={})

    projection = build_operation_source_readiness_projection(
        runtime=runtime,
        service_id="nex-cx",
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_operation_source_readiness_projection.v1"
    )
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["runtime"]["mode"] == "memory"
    assert projection["sources"] == [
        {
            "service_id": "nex-cx",
            "readiness_status": "DEFAULT_MEMORY",
            "configured": False,
            "source_kind": "memory-default",
            "capabilities": {
                "jobs": True,
                "events": True,
                "logs": True,
                "workers": True,
            },
            "read_only": False,
            "job_queue": "InMemoryJobQueue",
            "operational_event_store": "InMemoryOperationalEventStore",
            "service_log_store": "InMemoryServiceLogStore",
            "worker_heartbeat_store": "InMemoryWorkerHeartbeatStore",
            "database_env": None,
            "redacted_database_url": None,
        }
    ]
    assert projection["summary"] == {
        "total": 1,
        "by_status": {"DEFAULT_MEMORY": 1},
        "by_source_kind": {"memory-default": 1},
        "read_only": 0,
    }


def test_operation_source_readiness_projection_reports_postgres_sources() -> None:
    runtime = build_ag_operations_source_runtime(
        environ={
            AG_OPERATIONS_SOURCE_MODE_ENV: "postgres",
            AG_OPERATIONS_SOURCE_PROFILE_ENV: "test",
            AG_OPERATIONS_SOURCE_SERVICES_ENV: "nex-cx",
            "NEX_CX_TEST_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
        },
        engine_factory=lambda database_url, *, pool_settings: SimpleNamespace(
            database_url=database_url,
            pool_settings=pool_settings,
        ),
        session_factory_builder=lambda engine: f"session:{engine.pool_settings.workload}",
    )

    projection = build_operation_source_readiness_projection(runtime=runtime)

    assert projection["runtime"]["profile"] == "test"
    assert projection["sources"][0]["service_id"] == "nex-cx"
    assert projection["sources"][0]["readiness_status"] == "READY"
    assert projection["sources"][0]["source_kind"] == "postgres-read"
    assert projection["sources"][0]["read_only"] is True
    assert projection["sources"][0]["database_env"] == "NEX_CX_TEST_DATABASE_URL"
    assert projection["sources"][0]["redacted_database_url"].endswith(
        "nex_cx_user:***@localhost/nex_cx_test"
    )
    assert projection["summary"]["read_only"] == 1
    assert "secret" not in str(projection)


def test_operation_source_readiness_projection_reports_not_configured_registry_source() -> (
    None
):
    runtime = build_ag_operations_source_runtime(
        environ={
            AG_OPERATIONS_SOURCE_MODE_ENV: "postgres",
            AG_OPERATIONS_SOURCE_PROFILE_ENV: "test",
            AG_OPERATIONS_SOURCE_SERVICES_ENV: "nex-cx",
            "NEX_CX_TEST_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
        },
        engine_factory=lambda database_url, *, pool_settings: SimpleNamespace(
            database_url=database_url,
            pool_settings=pool_settings,
        ),
        session_factory_builder=lambda engine: f"session:{engine.pool_settings.workload}",
    )

    projection = build_operation_source_readiness_projection(
        runtime=runtime,
        service_id="nex-mo",
    )

    assert projection["sources"][0]["readiness_status"] == "NOT_CONFIGURED"
    assert projection["sources"][0]["read_only"] is None
    assert projection["summary"]["by_status"] == {"NOT_CONFIGURED": 1}


def test_summarize_operation_source_readiness_counts_empty_sources() -> None:
    assert summarize_operation_source_readiness([]) == {
        "total": 0,
        "by_status": {},
        "by_source_kind": {},
        "read_only": 0,
    }


@pytest.mark.parametrize(
    "environ, expected",
    [
        (
            {AG_OPERATIONS_SOURCE_MODE_ENV: "filesystem"},
            "unsupported AG operations source mode",
        ),
        (
            {AG_OPERATIONS_SOURCE_PROFILE_ENV: "prod"},
            "unsupported AG operations source profile",
        ),
        (
            {AG_OPERATIONS_SOURCE_SERVICES_ENV: "nex-cx,nex-unknown"},
            "unknown AG operations source services",
        ),
        (
            {AG_OPERATIONS_SOURCE_SERVICES_ENV: ", ,"},
            "selected no services",
        ),
        (
            {
                AG_OPERATIONS_SOURCE_MODE_ENV: "postgres",
                AG_OPERATIONS_SOURCE_SERVICES_ENV: "nex-cx",
            },
            "missing database URL env NEX_CX_DATABASE_URL",
        ),
        (
            {
                AG_OPERATIONS_SOURCE_MODE_ENV: "postgres",
                AG_OPERATIONS_SOURCE_SERVICES_ENV: "nex-cx",
                "NEX_CX_DATABASE_URL": "postgresql://nex_cx_user:<password>@localhost/nex_cx_dev",
            },
            "placeholder password",
        ),
    ],
)
def test_ag_operations_source_runtime_rejects_invalid_config(
    environ: dict[str, str],
    expected: str,
) -> None:
    with pytest.raises(OperationsSourceConfigError, match=expected):
        build_ag_operations_source_runtime(environ=environ)


def test_ag_operations_source_database_env_rejects_unknown_service() -> None:
    with pytest.raises(
        OperationsSourceConfigError, match="unknown AG operations source"
    ):
        ag_operations_source_database_env("nex-unknown")


def test_operations_source_registry_registers_sources_and_reports_capabilities() -> (
    None
):
    job_queues = build_job_queues()
    event_stores = build_event_stores()
    registry = build_operations_source_registry(
        job_queues=job_queues,
        event_stores=event_stores,
        service_log_stores=build_log_stores(),
        worker_heartbeat_stores=build_worker_heartbeat_stores(),
        source_kind="memory-test",
    )

    assert registry.service_ids() == ["nex-ae-api", "nex-cx", "nex-mo"]
    assert registry.get("nex-cx").job_queue is job_queues["nex-cx"]
    assert registry.get("nex-cx").operational_event_store is event_stores["nex-cx"]
    assert registry.get("nex-cx").service_log_store is not None
    assert registry.get("nex-cx").worker_heartbeat_store is not None
    assert sorted(registry.job_queues()) == ["nex-ae-api", "nex-cx"]
    assert sorted(registry.event_stores()) == ["nex-cx", "nex-mo"]
    assert sorted(registry.service_log_stores()) == ["nex-cx", "nex-mo"]
    assert sorted(registry.worker_heartbeat_stores()) == ["nex-cx", "nex-mo"]
    assert (
        registry.to_summary()["registry_schema_version"]
        == "ag_operations_source_registry.v1"
    )
    assert registry.to_summary()["sources"]["nex-mo"]["capabilities"] == {
        "jobs": False,
        "events": True,
        "logs": True,
        "workers": True,
    }


def test_operations_source_registry_rejects_unknown_or_empty_source_shapes() -> None:
    registry = OperationsSourceRegistry()

    try:
        OperationsSource(service_id="nex-unknown")
    except ValueError as exc:
        assert "unsupported operations source service" in str(exc)
    else:
        raise AssertionError("expected unknown service failure")

    try:
        OperationsSource(service_id="nex-cx", source_kind="")
    except ValueError as exc:
        assert "source_kind" in str(exc)
    else:
        raise AssertionError("expected empty source kind failure")

    try:
        OperationsSource(service_id="nex-cx", database_env="")
    except ValueError as exc:
        assert "database_env" in str(exc)
    else:
        raise AssertionError("expected empty database env failure")

    try:
        OperationsSource(service_id="nex-cx", redacted_database_url="")
    except ValueError as exc:
        assert "redacted_database_url" in str(exc)
    else:
        raise AssertionError("expected empty redacted database url failure")

    try:
        registry.get("nex-unknown")
    except ValueError as exc:
        assert "unsupported operations source service" in str(exc)
    else:
        raise AssertionError("expected unknown registry lookup failure")


def test_registry_operational_event_store_aggregates_and_filters_events() -> None:
    registry = build_operations_source_registry(event_stores=build_event_stores())
    registry_store = RegistryOperationalEventStore(registry)

    events = registry_store.list_events(limit=10)
    cx_events = registry_store.list_events(service_id="nex-cx", limit=10)
    missing = registry_store.list_events(service_id="nex-ag", limit=10)
    mo_event = registry_store.get_event("event-mo-001")
    absent_event = registry_store.get_event("event-missing")

    assert [event["event_id"] for event in events] == ["event-mo-001", "event-cx-001"]
    assert [event["event_id"] for event in cx_events] == ["event-cx-001"]
    assert missing == []
    assert mo_event is not None
    assert mo_event["details"]["service_token"] == "<redacted>"
    assert absent_event is None
    assert "private" not in str(events)

    try:
        registry_store.append(build_store().list_events(limit=1)[0])
    except Exception as exc:
        assert getattr(exc, "error_code") == "ag.operations_registry.read_only"
    else:
        raise AssertionError("expected read-only registry append failure")


def test_registry_service_log_store_aggregates_and_filters_logs() -> None:
    registry = build_operations_source_registry(service_log_stores=build_log_stores())
    registry_store = RegistryServiceLogStore(registry)

    logs = registry_store.list_logs(limit=10)
    cx_logs = registry_store.list_logs(service_id="nex-cx", limit=10)
    missing = registry_store.list_logs(service_id="nex-ag", limit=10)
    mo_log = registry_store.get_log("log-002")
    absent_log = registry_store.get_log("log-missing")

    assert [entry["log_id"] for entry in logs] == ["log-002", "log-001"]
    assert [entry["log_id"] for entry in cx_logs] == ["log-001"]
    assert missing == []
    assert mo_log is not None
    assert mo_log["attributes"]["provider"] == "vllm"
    assert absent_log is None
    assert "Bearer private" not in str(logs)

    try:
        registry_store.append(build_log_store().get_log("log-001"))
    except Exception as exc:
        assert getattr(exc, "error_code") == "ag.operations_registry.read_only"
    else:
        raise AssertionError("expected read-only registry append failure")


def test_operations_routes_accept_source_registry() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
        service_log_stores=build_log_stores(),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_routes(app, registry=registry)
    register_service_log_routes(app, registry=registry)
    register_job_operation_routes(app, registry=registry)
    client = TestClient(app)

    events_response = client.get(
        "/admin/v1/operations/events",
        params={"service_id": "nex-mo", "severity": "ERROR"},
        headers=auth_headers(),
    )
    jobs_response = client.get(
        "/admin/v1/operations/jobs",
        params={"service_id": "nex-ae-api"},
        headers=auth_headers(),
    )
    logs_response = client.get(
        "/admin/v1/operations/logs",
        params={"service_id": "nex-cx", "q": "worker"},
        headers=auth_headers(),
    )

    assert events_response.status_code == 200
    assert events_response.json()["events"][0]["event_id"] == "event-mo-001"
    assert jobs_response.status_code == 200
    assert logs_response.status_code == 200
    assert logs_response.json()["logs"][0]["log_id"] == "log-001"
    assert jobs_response.json()["jobs"][0]["job_id"] == "job-ae-001"


def test_build_worker_runtime_projection_filters_and_marks_stale_workers() -> None:
    registry = build_operations_source_registry(
        worker_heartbeat_stores=build_worker_heartbeat_stores(),
    )

    projection = build_worker_runtime_projection(
        registry=registry,
        service_id="nex-cx",
        status="busy",
        stale_after_seconds=60,
        checked_at="2026-08-05T00:01:20Z",
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == "ag_worker_runtime_projection.v1"
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-cx",
        "worker_type": None,
        "status": "BUSY",
        "stale_after_seconds": 60,
        "limit": 50,
        "since": None,
        "until": None,
        "sort": "desc",
        "cursor": None,
    }
    assert [worker["worker_id"] for worker in projection["workers"]] == [
        "cx-worker-001"
    ]
    assert projection["workers"][0]["stale"] is True
    assert projection["summary"]["total"] == 1
    assert projection["summary"]["stale"] == 1
    assert projection["source_statuses"]["nex-cx"] == {
        "status": "READY",
        "worker_count": 1,
    }
    assert_ag_operations_projection_contract(projection)


def test_worker_runtime_projection_reports_degraded_sources_and_applies_paging() -> (
    None
):
    projection = build_worker_runtime_projection(
        registry=build_operations_source_registry(
            worker_heartbeat_stores=build_worker_heartbeat_stores(),
        ),
        query_options=build_operation_query_options(limit=2, sort="asc"),
        checked_at="2026-08-05T00:01:20Z",
    )

    assert projection["projection_status"] == "DEGRADED"
    assert [worker["worker_id"] for worker in projection["workers"]] == [
        "cx-worker-001",
        "mo-worker-001",
    ]
    assert projection["pagination"]["next_cursor"] == "2"
    assert projection["source_statuses"]["nex-oa"] == {
        "status": "NOT_CONFIGURED",
        "worker_count": 0,
    }
    assert (
        projection["source_registry"]["sources"]["nex-cx"]["capabilities"]["workers"]
        is True
    )
    assert_ag_operations_projection_contract(projection)


def test_worker_runtime_projection_reports_unavailable_source() -> None:
    projection = build_worker_runtime_projection(
        worker_heartbeat_stores={"nex-cx": BrokenWorkerHeartbeatStore()},
        service_id="nex-cx",
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["workers"] == []
    assert projection["source_statuses"]["nex-cx"] == {
        "status": "UNAVAILABLE",
        "worker_count": 0,
        "error_code": "worker_heartbeat.store_unavailable",
        "detail": "worker heartbeat store is unavailable",
    }
    assert projection["summary"]["total"] == 0
    assert_ag_operations_projection_contract(projection)


def test_build_worker_detail_projection_correlates_active_job_and_lifecycle_events() -> (
    None
):
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_worker_lifecycle_event_stores(),
        worker_heartbeat_stores=build_worker_heartbeat_stores(),
    )

    projection = build_worker_detail_projection(
        registry=registry,
        service_id="nex-cx",
        worker_id="cx-worker-001",
        stale_after_seconds=60,
        checked_at="2026-08-05T00:01:20Z",
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == "ag_worker_detail_projection.v1"
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["worker"]["worker_id"] == "cx-worker-001"
    assert projection["worker"]["stale"] is True
    assert projection["active_job"]["job_id"] == "job-cx-001"
    assert projection["active_job"]["status"] == RUNNING
    assert projection["worker_lifecycle_timeline"]["timeline_status"] == "READY"
    assert [
        event["event_id"] for event in projection["worker_lifecycle_timeline"]["events"]
    ] == ["event-cx-worker-001"]
    assert projection["summary"]["active_job_status"] == RUNNING
    assert projection["source_statuses"] == {
        "workers": {
            "status": "READY",
            "worker_count": 1,
        },
        "jobs": {
            "status": "READY",
            "job_count": 1,
        },
        "events": {
            "status": "READY",
            "event_count": 1,
        },
    }
    assert_ag_operations_projection_contract(projection)


def test_build_worker_detail_projection_reports_source_states() -> None:
    not_configured = build_worker_detail_projection(
        worker_heartbeat_stores={},
        job_queues={},
        service_id="nex-cx",
        worker_id="cx-worker-001",
    )
    degraded = build_worker_detail_projection(
        worker_heartbeat_stores={"nex-cx": BrokenWorkerHeartbeatStore()},
        job_queues={},
        event_store=BrokenOperationalEventStore(),
        service_id="nex-cx",
        worker_id="cx-worker-001",
    )
    unavailable_correlations = build_worker_detail_projection(
        worker_heartbeat_stores=build_worker_heartbeat_stores(),
        job_queues={"nex-cx": UnavailableJobQueue()},
        event_store=BrokenOperationalEventStore(),
        service_id="nex-cx",
        worker_id="cx-worker-001",
        checked_at="2026-08-05T00:01:20Z",
    )
    idle = build_worker_detail_projection(
        worker_heartbeat_stores=build_worker_heartbeat_stores(),
        job_queues={},
        service_id="nex-cx",
        worker_id="cx-worker-002",
        checked_at="2026-08-05T00:01:20Z",
    )

    assert not_configured["projection_status"] == "DEGRADED"
    assert not_configured["worker"] is None
    assert not_configured["source_statuses"]["workers"] == {
        "status": "NOT_CONFIGURED",
        "worker_count": 0,
    }
    assert not_configured["summary"]["source_statuses"] == {
        "workers": "NOT_CONFIGURED",
        "jobs": "READY",
        "events": "READY",
    }
    assert_ag_operations_projection_contract(not_configured)

    assert degraded["projection_status"] == "DEGRADED"
    assert degraded["worker"] is None
    assert degraded["active_job"] is None
    assert degraded["source_statuses"]["workers"] == {
        "status": "UNAVAILABLE",
        "worker_count": 0,
        "error_code": "worker_heartbeat.store_unavailable",
        "detail": "worker heartbeat store is unavailable",
    }
    assert degraded["source_statuses"]["events"]["status"] == "READY"
    assert degraded["summary"]["worker_found"] is False
    assert_ag_operations_projection_contract(degraded)

    assert unavailable_correlations["projection_status"] == "DEGRADED"
    assert unavailable_correlations["worker"]["worker_id"] == "cx-worker-001"
    assert unavailable_correlations["active_job"] is None
    assert unavailable_correlations["source_statuses"]["jobs"] == {
        "status": "UNAVAILABLE",
        "job_count": 0,
        "error_code": "job.store_unavailable",
        "detail": "job queue store is unavailable",
    }
    assert unavailable_correlations["source_statuses"]["events"] == {
        "status": "UNAVAILABLE",
        "event_count": 0,
        "error_code": "operational_event.store_unavailable",
        "detail": "operational event store is unavailable",
    }
    assert unavailable_correlations["worker_lifecycle_timeline"]["source_error"] == {
        "error_code": "operational_event.store_unavailable",
        "detail": "operational event store is unavailable",
        "status_code": 503,
    }
    assert_ag_operations_projection_contract(unavailable_correlations)

    assert idle["projection_status"] == "DEGRADED"
    assert idle["worker"]["worker_id"] == "cx-worker-002"
    assert idle["active_job"] is None
    assert idle["source_statuses"]["jobs"] == {"status": "READY", "job_count": 0}
    assert idle["source_statuses"]["events"] == {
        "status": "NOT_CONFIGURED",
        "event_count": 0,
    }
    assert_ag_operations_projection_contract(idle)


def test_build_worker_detail_projection_rejects_bad_service_or_missing_worker() -> None:
    with pytest.raises(OperationsQueryError) as bad_service:
        build_worker_detail_projection(
            worker_heartbeat_stores=build_worker_heartbeat_stores(),
            service_id="nex-unknown",
            worker_id="cx-worker-001",
        )
    with pytest.raises(OperationsQueryError) as missing_worker:
        build_worker_detail_projection(
            worker_heartbeat_stores=build_worker_heartbeat_stores(),
            service_id="nex-cx",
            worker_id="cx-worker-missing",
        )

    assert bad_service.value.error_code == "ag.worker_service_invalid"
    assert bad_service.value.status_code == 400
    assert missing_worker.value.error_code == "ag.worker_not_found"
    assert missing_worker.value.status_code == 404


def test_worker_runtime_route_requires_auth_returns_projection_and_rejects_bad_filters() -> (
    None
):
    registry = build_operations_source_registry(
        worker_heartbeat_stores=build_worker_heartbeat_stores(),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app, registry=registry)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/workers")
    response = client.get(
        "/admin/v1/operations/workers",
        params={
            "service_id": "nex-cx",
            "status": "BUSY",
            "stale_after_seconds": 60,
        },
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )
    bad_service = client.get(
        "/admin/v1/operations/workers",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_status = client.get(
        "/admin/v1/operations/workers",
        params={"status": "BROKEN"},
        headers=auth_headers(),
    )
    bad_worker_type = client.get(
        "/admin/v1/operations/workers",
        params={"worker_type": ""},
        headers=auth_headers(),
    )

    assert missing_auth.status_code == 401
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["workers"][0]["worker_id"] == "cx-worker-001"
    assert payload["source_statuses"]["nex-cx"]["status"] == "READY"
    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.worker_service_invalid"
    assert bad_status.status_code == 400
    assert bad_status.json()["error_code"] == "ag.worker_status_invalid"
    assert bad_worker_type.status_code == 400
    assert bad_worker_type.json()["error_code"] == "ag.worker_type_invalid"


def test_worker_detail_route_requires_auth_returns_projection_and_rejects_bad_inputs() -> (
    None
):
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_worker_lifecycle_event_stores(),
        worker_heartbeat_stores=build_worker_heartbeat_stores(),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app, registry=registry)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/workers/nex-cx/cx-worker-001")
    response = client.get(
        "/admin/v1/operations/workers/nex-cx/cx-worker-001",
        params={"stale_after_seconds": 60},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )
    missing_worker = client.get(
        "/admin/v1/operations/workers/nex-cx/cx-worker-missing",
        headers=auth_headers(),
    )
    bad_service = client.get(
        "/admin/v1/operations/workers/nex-unknown/cx-worker-001",
        headers=auth_headers(),
    )
    bad_worker_id = client.get(
        "/admin/v1/operations/workers/nex-cx/%20",
        headers=auth_headers(),
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["worker"]["worker_id"] == "cx-worker-001"
    assert payload["active_job"]["job_id"] == "job-cx-001"
    assert payload["worker_lifecycle_timeline"]["event_count"] == 1
    assert missing_worker.status_code == 404
    assert missing_worker.json()["error_code"] == "ag.worker_not_found"
    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.worker_service_invalid"
    assert bad_worker_id.status_code == 400
    assert bad_worker_id.json()["error_code"] == "ag.worker_id_invalid"


def test_operation_source_readiness_route_requires_auth_and_filters_service() -> None:
    runtime = build_ag_operations_source_runtime(environ={})
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operation_source_readiness_routes(app, runtime=runtime)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/sources")
    response = client.get(
        "/admin/v1/operations/sources",
        params={"service_id": "nex-cx"},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["filters"] == {"service_id": "nex-cx"}
    assert payload["sources"][0]["service_id"] == "nex-cx"
    assert payload["sources"][0]["readiness_status"] == "DEFAULT_MEMORY"


def test_operation_source_readiness_route_reads_runtime_from_app_state() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    runtime = attach_ag_operations_source_runtime(app, environ={})
    register_operation_source_readiness_routes(app)

    response = TestClient(app).get(
        "/admin/v1/operations/sources",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["runtime"] == runtime.to_summary()


def test_operation_source_readiness_route_rejects_bad_service() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operation_source_readiness_routes(app)

    response = TestClient(app).get(
        "/admin/v1/operations/sources",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "ag.operation_source_service_invalid"


def test_build_unified_operations_projection_combines_jobs_events_and_registry_summary() -> (
    None
):
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
        service_log_stores=build_log_stores(),
    )

    projection = build_unified_operations_projection(
        registry=registry,
        service_id="nex-cx",
        job_status="running",
        event_severity="info",
        limit=9999,
        request_trace_id=TRACE_ID,
    )

    assert (
        projection["projection_schema_version"] == "ag_unified_operations_projection.v1"
    )
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-cx",
        "job_status": RUNNING,
        "job_type": None,
        "event_severity": "INFO",
        "event_type": None,
        "trace_id": None,
        "limit": 500,
        "since": None,
        "until": None,
        "sort": "desc",
        "cursor": None,
    }
    assert [job["job_id"] for job in projection["jobs"]["jobs"]] == ["job-cx-001"]
    assert [event["event_id"] for event in projection["events"]["events"]] == [
        "event-cx-001"
    ]
    assert projection["summary"]["jobs"]["statuses"][RUNNING] == 1
    assert projection["summary"]["events"]["by_severity"]["INFO"] == 1
    assert projection["source_registry"]["service_count"] == 3
    assert projection["pagination"]["jobs"]["total_after_filters"] == 1
    assert projection["pagination"]["events"]["total_after_filters"] == 1


def test_build_unified_operations_projection_supports_direct_injection_and_degraded_jobs() -> (
    None
):
    projection = build_unified_operations_projection(
        job_queues={
            **build_job_queues(),
            "nex-mo": BrokenJobQueue(),
        },
        event_store=build_store(),
        limit=2,
    )

    assert projection["projection_status"] == "DEGRADED"
    assert [job["job_id"] for job in projection["jobs"]["jobs"]] == [
        "job-ae-001",
        "job-cx-002",
    ]
    assert [event["event_id"] for event in projection["events"]["events"]] == [
        "event-002",
        "event-001",
    ]
    assert "source_registry" not in projection


def test_unified_operations_projection_applies_time_window_sort_and_cursor() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
        service_log_stores=build_log_stores(),
    )
    options = build_operation_query_options(
        limit=1,
        since="2026-08-05T00:00:01Z",
        sort="asc",
    )

    projection = build_unified_operations_projection(
        registry=registry,
        query_options=options,
    )

    assert projection["filters"]["since"] == "2026-08-05T00:00:01Z"
    assert projection["filters"]["sort"] == "asc"
    assert [job["job_id"] for job in projection["jobs"]["jobs"]] == ["job-cx-001"]
    assert projection["pagination"]["jobs"]["next_cursor"] == "1"
    assert [event["event_id"] for event in projection["events"]["events"]] == [
        "event-mo-001"
    ]
    assert projection["pagination"]["events"]["next_cursor"] is None


def test_unified_operations_route_requires_auth_and_returns_projection() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app, registry=registry)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations")
    response = client.get(
        "/admin/v1/operations",
        params={
            "service_id": "nex-cx",
            "job_status": "RUNNING",
            "event_severity": "INFO",
        },
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["jobs"]["jobs"][0]["job_id"] == "job-cx-001"
    assert payload["events"]["events"][0]["event_id"] == "event-cx-001"


def test_build_operations_rollup_metrics_projection_summarizes_sources() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
        service_log_stores=build_log_stores(),
    )

    projection = build_operations_rollup_metrics_projection(
        registry=registry,
        service_id="nex-cx",
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_operations_rollup_metrics_projection.v1"
    )
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-cx",
        "since": None,
        "until": None,
    }
    assert projection["rollups"] == [
        {
            "service_id": "nex-cx",
            "jobs": {
                "total": 2,
                "active": 1,
                "terminal": 1,
                "statuses": {
                    "QUEUED": 0,
                    "RUNNING": 1,
                    "SUCCEEDED": 0,
                    "FAILED": 1,
                    "CANCELLED": 0,
                },
                "by_job_type": {"cx.document_processing": 2},
            },
            "events": {
                "total": 1,
                "by_severity": {
                    "DEBUG": 0,
                    "INFO": 1,
                    "WARNING": 0,
                    "ERROR": 0,
                    "CRITICAL": 0,
                },
                "by_event_type": {"cx.processing.succeeded": 1},
            },
            "logs": {
                "total": 1,
                "by_severity": {
                    "DEBUG": 0,
                    "INFO": 1,
                    "WARNING": 0,
                    "ERROR": 0,
                    "CRITICAL": 0,
                },
                "by_logger_name": {"nex_runtime.worker_runner": 1},
                "redacted_attribute_count": 0,
            },
            "source_status": {
                "jobs": "READY",
                "events": "READY",
                "logs": "READY",
            },
        }
    ]
    assert projection["summary"]["jobs"]["total"] == 2
    assert projection["summary"]["events"]["total"] == 1
    assert projection["summary"]["logs"] == {
        "total": 1,
        "by_severity": {
            "DEBUG": 0,
            "INFO": 1,
            "WARNING": 0,
            "ERROR": 0,
            "CRITICAL": 0,
        },
        "by_service": {"nex-cx": 1},
        "redacted_attribute_count": 0,
    }
    assert projection["summary"]["source_statuses"] == {
        "jobs": {"READY": 1},
        "events": {"READY": 1},
        "logs": {"READY": 1},
    }
    assert projection["job_source_statuses"]["nex-cx"] == {
        "status": "READY",
        "job_count": 2,
    }
    assert projection["event_source_statuses"]["nex-cx"] == {
        "status": "READY",
        "event_count": 1,
    }
    assert projection["log_source_statuses"]["nex-cx"] == {
        "status": "READY",
        "log_count": 1,
    }
    assert_ag_operations_projection_contract(projection)


def test_operations_rollup_metrics_projection_applies_time_window() -> None:
    projection = build_operations_rollup_metrics_projection(
        registry=build_operations_source_registry(
            job_queues=build_job_queues(),
            event_stores=build_event_stores(),
        ),
        service_id="nex-cx",
        query_options=build_operation_query_options(
            limit=500,
            since="2026-08-05T00:00:04Z",
        ),
    )

    assert projection["filters"]["since"] == "2026-08-05T00:00:04Z"
    assert projection["rollups"][0]["jobs"]["total"] == 1
    assert projection["rollups"][0]["jobs"]["statuses"][FAILED] == 1
    assert projection["rollups"][0]["events"]["total"] == 0
    assert projection["rollups"][0]["logs"]["total"] == 0
    assert projection["summary"]["jobs"]["by_service"] == {"nex-cx": 1}
    assert projection["summary"]["events"]["by_service"] == {"nex-cx": 0}
    assert projection["summary"]["logs"]["by_service"] == {"nex-cx": 0}


def test_operations_rollup_metrics_projection_reports_degraded_sources() -> None:
    not_configured = build_operations_rollup_metrics_projection(
        registry=build_operations_source_registry(event_stores=build_event_stores()),
        service_id="nex-mo",
    )
    missing_events = build_operations_rollup_metrics_projection(
        registry=build_operations_source_registry(job_queues=build_job_queues()),
        service_id="nex-ae-api",
    )
    unavailable = build_operations_rollup_metrics_projection(
        job_queues={"nex-cx": BrokenJobQueue()},
        event_store=BrokenOperationalEventStore(),
        service_log_stores={"nex-cx": BrokenServiceLogStore()},
        service_id="nex-cx",
    )

    assert not_configured["projection_status"] == "DEGRADED"
    assert not_configured["job_source_statuses"]["nex-mo"] == {
        "status": "NOT_CONFIGURED",
        "job_count": 0,
    }
    assert not_configured["event_source_statuses"]["nex-mo"]["status"] == "READY"
    assert missing_events["projection_status"] == "DEGRADED"
    assert missing_events["job_source_statuses"]["nex-ae-api"]["status"] == "READY"
    assert missing_events["event_source_statuses"]["nex-ae-api"] == {
        "status": "NOT_CONFIGURED",
        "event_count": 0,
    }
    assert unavailable["projection_status"] == "DEGRADED"
    assert unavailable["rollups"][0]["jobs"]["total"] == 0
    assert unavailable["rollups"][0]["events"]["total"] == 0
    assert unavailable["rollups"][0]["logs"]["total"] == 0
    assert unavailable["job_source_statuses"]["nex-cx"]["status"] == "UNAVAILABLE"
    assert unavailable["event_source_statuses"]["nex-cx"]["status"] == "UNAVAILABLE"
    assert unavailable["log_source_statuses"]["nex-cx"]["status"] == "UNAVAILABLE"
    assert unavailable["summary"]["source_statuses"] == {
        "jobs": {"UNAVAILABLE": 1},
        "events": {"UNAVAILABLE": 1},
        "logs": {"UNAVAILABLE": 1},
    }
    assert_ag_operations_projection_contract(unavailable)


def test_summarize_operations_rollup_metrics_counts_empty() -> None:
    assert summarize_operations_rollup_metrics([]) == {
        "service_count": 0,
        "jobs": {
            "total": 0,
            "active": 0,
            "terminal": 0,
            "statuses": {
                "QUEUED": 0,
                "RUNNING": 0,
                "SUCCEEDED": 0,
                "FAILED": 0,
                "CANCELLED": 0,
            },
            "by_service": {},
        },
        "events": {
            "total": 0,
            "by_severity": {
                "DEBUG": 0,
                "INFO": 0,
                "WARNING": 0,
                "ERROR": 0,
                "CRITICAL": 0,
            },
            "by_service": {},
        },
        "logs": {
            "total": 0,
            "by_severity": {
                "DEBUG": 0,
                "INFO": 0,
                "WARNING": 0,
                "ERROR": 0,
                "CRITICAL": 0,
            },
            "by_service": {},
            "redacted_attribute_count": 0,
        },
        "source_statuses": {
            "jobs": {},
            "events": {},
            "logs": {},
        },
    }


def test_operations_rollup_metrics_route_requires_auth_returns_projection() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app, registry=registry)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/rollups")
    response = client.get(
        "/admin/v1/operations/rollups",
        params={"service_id": "nex-cx"},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["projection_status"] == "READY"
    assert payload["rollups"][0]["service_id"] == "nex-cx"
    assert payload["summary"]["jobs"]["total"] == 2
    assert payload["summary"]["logs"]["by_service"] == {"nex-cx": 0}
    assert payload["log_source_statuses"]["nex-cx"] == {
        "status": "NOT_CONFIGURED",
        "log_count": 0,
    }


def test_operations_rollup_metrics_route_rejects_bad_filters() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app)
    client = TestClient(app)

    bad_service = client.get(
        "/admin/v1/operations/rollups",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_window = client.get(
        "/admin/v1/operations/rollups",
        params={
            "since": "2026-08-05T00:00:02Z",
            "until": "2026-08-05T00:00:01Z",
        },
        headers=auth_headers(),
    )

    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert bad_window.status_code == 400
    assert bad_window.json()["error_code"] == "ag.operation_time_window_invalid"


def test_build_operations_dashboard_snapshot_projection_combines_sections() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    runtime = build_ag_operations_source_runtime(environ={})
    cx_processing_store = InMemoryCxProcessingRunOperationsStore(
        records=[
            cx_processing_run_record(
                pipeline_run_id="processing-run-001",
                status="FAILED",
                updated_at="2026-08-05T00:00:06Z",
                step_failed=1,
                job_retryable=True,
            ),
            cx_processing_run_record(
                pipeline_run_id="processing-run-002",
                status="RUNNING",
                updated_at="2026-08-05T00:00:07Z",
                step_failed=0,
                job_retryable=True,
            ),
        ]
    )

    projection = build_operations_dashboard_snapshot_projection(
        registry=registry,
        runtime=runtime,
        retrieval_package_stores={
            "nex-cx": InMemoryRetrievalPackageOperationsStore(
                records=[retrieval_package_record()]
            )
        },
        cx_processing_run_stores={"nex-cx": cx_processing_store},
        generation_audit_projections=[
            generation_audit_projection_record(
                cx_generation_id="cx-gen-pass",
                coverage_status="PASS",
                boundary_status="PASS",
                created_at="2026-08-05T00:00:04Z",
            ),
            generation_audit_projection_record(
                cx_generation_id="cx-gen-warn",
                coverage_status="WARN",
                boundary_status="PASS",
                issue_codes=["MISSING_CX_GROUNDED_RESPONSE_QUALITY_FIELDS"],
                created_at="2026-08-05T00:00:08Z",
            ),
        ],
        service_id="nex-cx",
        recent_limit=2,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_operations_dashboard_snapshot_projection.v1"
    )
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-cx",
        "since": None,
        "until": None,
        "recent_limit": 2,
    }
    assert projection["source_readiness_summary"]["total"] == 1
    assert projection["operation_sources"][0]["service_id"] == "nex-cx"
    assert projection["rollup_summary"]["jobs"]["total"] == 2
    assert projection["rollups"][0]["events"]["total"] == 1
    assert [job["job_id"] for job in projection["recent_failures"]["jobs"]] == [
        "job-cx-002"
    ]
    assert projection["replay_candidates"] == [
        {
            "service_id": "nex-cx",
            "job_id": "job-cx-002",
            "job_type": "cx.document_processing",
            "status": "FAILED",
            "trace_id": TRACE_ID,
            "request_id": REQUEST_ID,
            "updated_at": "2026-08-05T00:00:05Z",
            "source_error_code": "cx.processing.failed",
            "recommended_action": "replay",
            "allowed_actions": ["read", "replay"],
            "control_path": "/admin/v1/operations/jobs/nex-cx/job-cx-002/replay",
            "required_payload_fields": [
                "replay_job_id",
                "idempotency_key",
                "requested_by",
                "reason",
            ],
        }
    ]
    assert projection["recent_failures"]["events"] == []
    assert projection["recent_failures"]["logs"] == []
    assert [job["job_id"] for job in projection["active_jobs"]] == ["job-cx-001"]
    assert projection["cx_processing_runs"]["summary"] == {
        "total": 2,
        "by_status": {"FAILED": 1, "RUNNING": 1},
        "failed_count": 1,
        "running_count": 1,
        "queued_count": 0,
        "active_count": 1,
        "retryable_failed_count": 1,
        "step_failed_count": 1,
    }
    assert [
        run["pipeline_run_id"] for run in projection["cx_processing_runs"]["recent"]
    ] == ["processing-run-002", "processing-run-001"]
    assert (
        projection["cx_processing_runs"]["recent_failures"][0]["detail_path"]
        == "/admin/v1/operations/cx-processing-runs/processing-run-001"
    )
    assert projection["cx_processing_runs"]["active"][0]["pipeline_run_id"] == (
        "processing-run-002"
    )
    assert projection["cx_processing_runs"]["source_statuses"]["nex-cx"] == {
        "status": "READY",
        "service_id": "nex-cx",
        "source_kind": "memory",
        "processing_run_count": 2,
        "database_env": None,
        "redacted_database_url": None,
    }
    assert projection["retrieval_threshold_decisions"]["summary"] == {
        "total_decisions": 2,
        "by_sample_readiness": {"INSUFFICIENT_SAMPLES": 2},
        "by_decision_status": {"OBSERVE": 2},
        "observed_sample_count": 1,
        "threshold_override_count": 0,
        "ready_for_review": 0,
        "needs_operator_review": 0,
        "insufficient_samples": 2,
        "source_degraded": 0,
    }
    assert (
        projection["retrieval_threshold_decisions"]["closure"]["closure_status"]
        == "COLLECTING_SAMPLES"
    )
    assert {
        decision["policy_id"]: decision["observed_sample_count"]
        for decision in projection["retrieval_threshold_decisions"][
            "threshold_decisions"
        ]
    } == {
        "retrieval_quality_v1": 0,
        "weighted_rrf_vector_bm25_v1": 1,
    }
    assert projection["retrieval_threshold_decisions"]["source_statuses"]["nex-cx"] == {
        "status": "READY",
        "service_id": "nex-cx",
        "source_kind": "memory",
        "package_count": 1,
        "database_env": None,
        "redacted_database_url": None,
    }
    assert projection["generation_quality"]["summary"] == {
        "total": 2,
        "by_coverage_status": {
            "PASS": 1,
            "WARN": 1,
            "FAIL": 0,
            "NOT_REQUIRED": 0,
            "UNKNOWN": 0,
        },
        "by_boundary_status": {
            "PASS": 2,
            "WARN": 0,
            "FAIL": 0,
            "NOT_REQUIRED": 0,
            "UNKNOWN": 0,
        },
        "attention_count": 1,
        "failed_count": 0,
        "warning_count": 1,
    }
    assert [
        item["cx_generation_id"] for item in projection["generation_quality"]["recent"]
    ] == ["cx-gen-warn", "cx-gen-pass"]
    assert projection["generation_quality"]["attention"][0]["issue_codes"] == [
        "MISSING_CX_GROUNDED_RESPONSE_QUALITY_FIELDS"
    ]
    assert projection["generation_quality"]["attention"][0]["detail_path"] == (
        "/admin/v1/generation-audit/generations/cx-gen-warn"
    )
    assert projection["generation_remediation"] == {
        "projection_schema_version": "ag_generation_remediation_dashboard_section.v1",
        "summary": {
            "total": 0,
            "by_status": {},
            "by_action_type": {},
            "active_count": 0,
            "failed_count": 0,
            "completed_count": 0,
            "urgent_count": 0,
            "attention_count": 0,
        },
        "recent": [],
        "attention": [],
        "source_statuses": {},
    }
    assert projection["degraded_sources"] == []
    assert projection["log_source_statuses"]["nex-cx"] == {
        "status": "NOT_CONFIGURED",
        "log_count": 0,
    }
    assert_ag_operations_projection_contract(projection)


def test_operations_dashboard_snapshot_includes_generation_remediation_tasks() -> None:
    store = GenerationRemediationTaskStore()
    store.save(
        generation_remediation_task_record(
            remediation_action_id="ag-remediation-dashboard-001",
            action_status="ASSIGNED",
            priority="HIGH",
            updated_at="2026-08-05T00:00:09Z",
        )
    )
    store.save(
        generation_remediation_task_record(
            remediation_action_id="ag-remediation-dashboard-002",
            cx_generation_id="cx-gen-remediation-2",
            action_type="retry_generation",
            action_status="COMPLETED",
            priority="NORMAL",
            updated_at="2026-08-05T00:00:10Z",
        )
    )

    projection = build_operations_dashboard_snapshot_projection(
        generation_remediation_task_stores={"nex-ag": store},
        recent_limit=2,
    )

    remediation = projection["generation_remediation"]
    assert remediation["summary"] == {
        "total": 2,
        "by_status": {"ASSIGNED": 1, "COMPLETED": 1},
        "by_action_type": {"citation_repair": 1, "retry_generation": 1},
        "active_count": 1,
        "failed_count": 0,
        "completed_count": 1,
        "urgent_count": 0,
        "attention_count": 1,
    }
    assert [
        item["remediation_action_id"] for item in remediation["recent"]
    ] == ["ag-remediation-dashboard-002", "ag-remediation-dashboard-001"]
    assert [
        item["remediation_action_id"] for item in remediation["attention"]
    ] == ["ag-remediation-dashboard-001"]
    assert remediation["attention"][0]["detail_path"] == (
        "/admin/v1/generation-audit/generations/cx-gen-remediation"
        "/remediation-tasks/ag-remediation-dashboard-001"
    )
    assert remediation["source_statuses"]["nex-ag"] == {
        "status": "READY",
        "service_id": "nex-ag",
        "source_kind": "memory",
        "task_count": 2,
        "database_env": None,
        "redacted_database_url": None,
    }
    assert_ag_operations_projection_contract(projection)


def test_operations_dashboard_snapshot_includes_remediation_executions() -> None:
    task_store = GenerationRemediationTaskStore()
    task_store.save(
        generation_remediation_task_record(
            remediation_action_id="ag-remediation-sync",
            cx_generation_id="cx-gen-sync",
            action_status="ASSIGNED",
            updated_at="2026-08-05T00:00:10Z",
        )
    )
    task_store.save(
        generation_remediation_task_record(
            remediation_action_id="ag-remediation-completed",
            cx_generation_id="cx-gen-completed",
            action_status="COMPLETED",
            updated_at="2026-08-05T00:00:11Z",
        )
    )
    task_store.save(
        generation_remediation_task_record(
            remediation_action_id="ag-remediation-failed-exec",
            cx_generation_id="cx-gen-failed-exec",
            action_status="WAITING_ON_CX",
            updated_at="2026-08-05T00:00:12Z",
        )
    )
    execution_store = InMemoryRemediationExecutionOperationsStore(
        records=[
            remediation_execution_record(
                remediation_action_id="ag-remediation-sync",
                parent_cx_generation_id="cx-gen-sync",
                execution_status="SUCCEEDED",
                updated_at="2026-08-05T00:00:10Z",
            ),
            remediation_execution_record(
                remediation_action_id="ag-remediation-completed",
                parent_cx_generation_id="cx-gen-completed",
                execution_status="SUCCEEDED",
                updated_at="2026-08-05T00:00:11Z",
            ),
            remediation_execution_record(
                remediation_action_id="ag-remediation-failed-exec",
                parent_cx_generation_id="cx-gen-failed-exec",
                execution_status="FAILED",
                updated_at="2026-08-05T00:00:12Z",
            ),
        ]
    )

    projection = build_operations_dashboard_snapshot_projection(
        generation_remediation_task_stores={"nex-ag": GenerationRemediationTaskStore()},
        remediation_execution_task_stores={"nex-ag": task_store},
        remediation_execution_stores={"nex-cx": execution_store},
        remediation_execution_projection_builder=(
            build_remediation_execution_operations_projection
        ),
        recent_limit=3,
    )

    executions = projection["remediation_executions"]
    assert executions["projection_status"] == "READY"
    assert executions["summary"] == {
        "total": 3,
        "by_task_status": {
            "ASSIGNED": 1,
            "COMPLETED": 1,
            "WAITING_ON_CX": 1,
        },
        "by_execution_status": {"FAILED": 1, "SUCCEEDED": 2},
        "sync_required_count": 2,
        "missing_execution_count": 0,
        "orphan_execution_count": 0,
        "failed_execution_count": 1,
        "attention_required_count": 2,
        "by_status_sync_state": {"IN_SYNC": 1, "SYNC_REQUIRED": 2},
    }
    assert [
        item["remediation_action_id"] for item in executions["recent"]
    ] == [
        "ag-remediation-failed-exec",
        "ag-remediation-completed",
        "ag-remediation-sync",
    ]
    assert [
        item["remediation_action_id"] for item in executions["attention"]
    ] == ["ag-remediation-failed-exec", "ag-remediation-sync"]
    assert executions["attention"][0]["failure"] == {
        "error_code": "cx.remediation.execution_failed",
        "error_detail_sha256": "b" * 64,
        "retryable": True,
    }
    assert executions["attention"][1]["task_detail_path"] == (
        "/admin/v1/generation-audit/generations/cx-gen-sync"
        "/remediation-tasks/ag-remediation-sync"
    )
    assert executions["source_statuses"]["nex-ag"]["status"] == "READY"
    assert executions["source_statuses"]["nex-cx"]["status"] == "READY"
    assert projection["degraded_sources"] == []
    assert_ag_operations_projection_contract(projection)


def test_dashboard_remediation_execution_section_handles_empty_filtered_and_broken_builder() -> (
    None
):
    def broken_builder(**_: object) -> dict[str, object]:
        raise RuntimeError("projection down")

    empty = _dashboard_remediation_execution_section(
        None,
        task_stores=None,
        execution_stores=None,
        service_id=None,
        options=build_operation_query_options(limit=500),
        limit=3,
    )
    filtered = _dashboard_remediation_execution_section(
        build_remediation_execution_operations_projection,
        task_stores={"nex-ag": GenerationRemediationTaskStore()},
        execution_stores={"nex-cx": InMemoryRemediationExecutionOperationsStore()},
        service_id="nex-oa",
        options=build_operation_query_options(limit=500),
        limit=3,
    )
    broken = _dashboard_remediation_execution_section(
        broken_builder,
        task_stores=None,
        execution_stores=None,
        service_id="nex-cx",
        options=build_operation_query_options(limit=500),
        limit=3,
    )

    assert empty["source_statuses"] == {}
    assert filtered["source_statuses"] == {}
    assert broken["projection_status"] == "DEGRADED"
    assert broken["source_statuses"]["nex-ag"]["status"] == "UNAVAILABLE"
    assert broken["source_statuses"]["nex-cx"]["error_code"] == (
        "ag.remediation_execution_dashboard_source_unavailable"
    )


def test_dashboard_generation_remediation_section_handles_missing_and_broken_sources() -> (
    None
):
    class BrokenRemediationStore:
        source_kind = "postgres"
        database_env = "NEX_AG_TEST_DATABASE_URL"
        redacted_database_url = "postgresql://nex_ag_user:***@localhost/nex_ag_test"

        def list_recent(self, *, limit: int = 500) -> list[dict[str, object]]:
            raise RuntimeError("store down")

    empty = _dashboard_generation_remediation_section(
        None,
        service_id=None,
        options=build_operation_query_options(limit=500),
        limit=3,
    )
    filtered = _dashboard_generation_remediation_section(
        {"nex-ag": GenerationRemediationTaskStore()},
        service_id="nex-cx",
        options=build_operation_query_options(limit=500),
        limit=3,
    )
    missing = _dashboard_generation_remediation_section(
        {},
        service_id="nex-ag",
        options=build_operation_query_options(limit=500),
        limit=3,
    )
    broken = _dashboard_generation_remediation_section(
        {"nex-ag": BrokenRemediationStore()},
        service_id="nex-ag",
        options=build_operation_query_options(limit=500),
        limit=3,
    )

    assert empty["source_statuses"] == {}
    assert filtered["source_statuses"] == {}
    assert missing["source_statuses"]["nex-ag"]["status"] == "NOT_CONFIGURED"
    assert broken["source_statuses"]["nex-ag"]["status"] == "UNAVAILABLE"
    assert broken["source_statuses"]["nex-ag"]["error_code"] == (
        "ag.generation_remediation_source_unavailable"
    )


def test_operations_dashboard_snapshot_reports_retrieval_threshold_source_unavailable() -> (
    None
):
    projection = build_operations_dashboard_snapshot_projection(
        retrieval_package_stores={"nex-cx": BrokenRetrievalPackageStore()},
        service_id="nex-cx",
    )

    assert projection["projection_status"] == "DEGRADED"
    assert (
        projection["retrieval_threshold_decisions"]["summary"]["source_degraded"] == 2
    )
    assert (
        projection["retrieval_threshold_decisions"]["closure"]["closure_status"]
        == "BLOCKED"
    )
    assert {
        decision["sample_readiness"]
        for decision in projection["retrieval_threshold_decisions"][
            "threshold_decisions"
        ]
    } == {"SOURCE_DEGRADED"}
    assert projection["retrieval_threshold_decisions"]["source_statuses"]["nex-cx"] == {
        "status": "UNAVAILABLE",
        "service_id": "nex-cx",
        "source_kind": "postgres-read",
        "package_count": 0,
        "database_env": "NEX_CX_TEST_DATABASE_URL",
        "redacted_database_url": "postgresql://nex_cx_user:***@localhost/nex_cx_test",
        "error_code": "ag.retrieval_package_source_unavailable",
        "detail": "retrieval package source is unavailable",
    }
    assert {
        (source["source_type"], source["service_id"], source["status"])
        for source in projection["degraded_sources"]
    } == {("retrieval_threshold_decisions", "nex-cx", "UNAVAILABLE")}
    assert_ag_operations_projection_contract(projection)


def test_operations_dashboard_snapshot_retrieval_threshold_handles_missing_and_other_scope() -> (
    None
):
    missing = build_operations_dashboard_snapshot_projection(
        retrieval_package_stores={},
        service_id="nex-cx",
    )
    other_scope = build_operations_dashboard_snapshot_projection(
        retrieval_package_stores={
            "nex-cx": InMemoryRetrievalPackageOperationsStore(
                records=[retrieval_package_record()]
            )
        },
        service_id="nex-mo",
    )

    assert missing["projection_status"] == "DEGRADED"
    assert missing["retrieval_threshold_decisions"]["source_statuses"]["nex-cx"] == {
        "status": "NOT_CONFIGURED",
        "service_id": "nex-cx",
        "source_kind": "none",
        "package_count": 0,
        "database_env": None,
        "redacted_database_url": None,
    }
    assert missing["retrieval_threshold_decisions"]["summary"]["source_degraded"] == 2
    assert (
        missing["retrieval_threshold_decisions"]["closure"]["closure_status"]
        == "BLOCKED"
    )
    assert {
        (source["source_type"], source["service_id"], source["status"])
        for source in missing["degraded_sources"]
    } == {("retrieval_threshold_decisions", "nex-cx", "NOT_CONFIGURED")}
    assert other_scope["retrieval_threshold_decisions"] == {
        "summary": {
            "total_decisions": 0,
            "by_sample_readiness": {},
            "by_decision_status": {},
            "observed_sample_count": 0,
            "threshold_override_count": 0,
            "ready_for_review": 0,
            "needs_operator_review": 0,
            "insufficient_samples": 0,
            "source_degraded": 0,
        },
        "closure": {
            "closure_schema_version": ("ag_retrieval_threshold_calibration_closure.v1"),
            "closure_status": "NO_DECISIONS",
            "total_decisions": 0,
            "closed_decision_count": 0,
            "open_decision_count": 0,
            "readiness_counts": {},
            "blocking_readiness": [],
            "ready_policy_ids": [],
            "blocked_policy_ids": [],
            "recommended_next_actions": [],
            "minimum_live_samples_satisfied": False,
            "policy_review_ready": False,
        },
        "threshold_decisions": [],
        "source_statuses": {},
    }
    assert_ag_operations_projection_contract(missing)
    assert_ag_operations_projection_contract(other_scope)


def test_operations_dashboard_snapshot_reports_cx_processing_source_unavailable() -> (
    None
):
    projection = build_operations_dashboard_snapshot_projection(
        cx_processing_run_stores={"nex-cx": BrokenCxProcessingRunStore()},
        service_id="nex-cx",
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["cx_processing_runs"]["summary"]["total"] == 0
    assert projection["cx_processing_runs"]["source_statuses"]["nex-cx"] == {
        "status": "UNAVAILABLE",
        "service_id": "nex-cx",
        "source_kind": "postgres-read",
        "processing_run_count": 0,
        "database_env": "NEX_CX_TEST_DATABASE_URL",
        "redacted_database_url": "postgresql://nex_cx_user:***@localhost/nex_cx_test",
        "error_code": "ag.cx_processing_run_source_unavailable",
        "detail": "CX processing run source is unavailable.",
    }
    assert {
        (source["source_type"], source["service_id"], source["status"])
        for source in projection["degraded_sources"]
    } == {("cx_processing_runs", "nex-cx", "UNAVAILABLE")}
    assert_ag_operations_projection_contract(projection)


def test_operations_dashboard_snapshot_cx_processing_handles_missing_store_and_coercions() -> (
    None
):
    missing = build_operations_dashboard_snapshot_projection(
        cx_processing_run_stores={},
        service_id="nex-cx",
    )

    assert missing["projection_status"] == "DEGRADED"
    assert missing["cx_processing_runs"]["source_statuses"]["nex-cx"]["status"] == (
        "NOT_CONFIGURED"
    )
    assert {
        (source["source_type"], source["service_id"], source["status"])
        for source in missing["degraded_sources"]
    } == {("cx_processing_runs", "nex-cx", "NOT_CONFIGURED")}

    record = cx_processing_run_record(
        pipeline_run_id="processing-run-coerce",
        status="QUEUED",
        updated_at="2026-08-05T00:00:08Z",
    )
    record["step_total"] = True
    record["step_succeeded"] = "2"
    record["step_skipped"] = "bad"
    record["step_failed"] = "3"
    record["queued_at"] = None
    record["started_at"] = datetime(2026, 8, 5, 0, 0, 8, tzinfo=UTC)
    record["updated_at"] = datetime(2026, 8, 5, 0, 0, 9, tzinfo=UTC)
    projection = build_operations_dashboard_snapshot_projection(
        cx_processing_run_stores={
            "nex-cx": InMemoryCxProcessingRunOperationsStore(records=[record])
        },
        service_id="nex-cx",
    )

    item = projection["cx_processing_runs"]["recent"][0]
    assert item["step_total"] == 0
    assert item["step_succeeded"] == 2
    assert item["step_skipped"] == 0
    assert item["step_failed"] == 3
    assert item["queued_at"] is None
    assert item["started_at"] == "2026-08-05T00:00:08Z"
    assert item["updated_at"] == "2026-08-05T00:00:09Z"
    assert projection["cx_processing_runs"]["summary"]["queued_count"] == 1
    assert_ag_operations_projection_contract(projection)


def test_operations_dashboard_snapshot_reports_degraded_sources_and_failure_events_and_logs() -> (
    None
):
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
        service_log_stores=build_log_stores(),
    )

    projection = build_operations_dashboard_snapshot_projection(
        registry=registry,
        recent_limit=2,
    )

    assert projection["projection_status"] == "DEGRADED"
    assert [event["event_id"] for event in projection["recent_failures"]["events"]] == [
        "event-mo-001"
    ]
    assert [job["job_id"] for job in projection["recent_failures"]["jobs"]] == [
        "job-cx-002"
    ]
    assert [log["log_id"] for log in projection["recent_failures"]["logs"]] == [
        "log-002"
    ]
    assert [job["job_id"] for job in projection["active_jobs"]] == ["job-cx-001"]
    assert {
        (source["source_type"], source["service_id"], source["status"])
        for source in projection["degraded_sources"]
    } >= {
        ("readiness", "nex-oa", "NOT_CONFIGURED"),
        ("jobs", "nex-mo", "NOT_CONFIGURED"),
        ("events", "nex-ae-api", "NOT_CONFIGURED"),
    }
    assert projection["rollup_summary"]["source_statuses"]["jobs"] == {
        "READY": 2,
        "NOT_CONFIGURED": 3,
    }
    assert projection["log_source_statuses"]["nex-cx"] == {
        "status": "READY",
        "log_count": 1,
    }
    assert projection["log_source_statuses"]["nex-mo"] == {
        "status": "READY",
        "log_count": 1,
    }
    assert projection["log_source_statuses"]["nex-oa"] == {
        "status": "NOT_CONFIGURED",
        "log_count": 0,
    }
    assert_ag_operations_projection_contract(projection)


def test_operations_dashboard_snapshot_handles_unavailable_candidate_sources() -> None:
    projection = build_operations_dashboard_snapshot_projection(
        job_queues={"nex-cx": BrokenJobQueue()},
        event_store=BrokenOperationalEventStore(),
        service_log_stores={"nex-cx": BrokenServiceLogStore()},
        service_id="nex-cx",
        recent_limit=999,
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["filters"]["recent_limit"] == 20
    assert projection["recent_failures"] == {
        "jobs": [],
        "events": [],
        "logs": [],
    }
    assert projection["replay_candidates"] == []
    assert projection["active_jobs"] == []
    assert {
        (source["source_type"], source["service_id"], source["status"])
        for source in projection["degraded_sources"]
    } == {
        ("jobs", "nex-cx", "UNAVAILABLE"),
        ("events", "nex-cx", "UNAVAILABLE"),
        ("logs", "nex-cx", "UNAVAILABLE"),
    }
    assert projection["degraded_sources"][0]["error_code"] == "job.store_unavailable"
    assert projection["log_source_statuses"]["nex-cx"] == {
        "status": "UNAVAILABLE",
        "log_count": 0,
        "error_code": "service_log.store_unavailable",
        "detail": "service log store is unavailable",
    }
    assert_ag_operations_projection_contract(projection)


def test_dashboard_replay_candidates_only_include_dead_letter_jobs() -> None:
    ordinary_failure = sample_job(
        job_id="ordinary-failed",
        status=FAILED,
        idempotency_key="ordinary-failed-idem",
    )
    ordinary_failure["service_id"] = "nex-cx"
    ordinary_failure["error"] = {"error_code": "cx.failed", "dead_lettered": False}
    replayable_failure = sample_job(
        job_id="dead-lettered",
        status=FAILED,
        idempotency_key="dead-lettered-idem",
    )
    replayable_failure["service_id"] = "nex-cx"
    replayable_failure["error"] = {"dead_lettered": True}

    candidates = _dashboard_replay_candidates([ordinary_failure, replayable_failure])

    assert [candidate["job_id"] for candidate in candidates] == ["dead-lettered"]
    assert candidates[0]["source_error_code"] is None
    assert candidates[0]["allowed_actions"] == ["read", "replay"]
    assert _job_error_code({"error": "not-an-object"}) is None
    assert _job_error_code({"error": {}}) is None


def test_normalize_dashboard_recent_limit_clamps_bounds() -> None:
    assert normalize_dashboard_recent_limit(0) == 1
    assert normalize_dashboard_recent_limit(5) == 5
    assert normalize_dashboard_recent_limit(999) == 20


def test_operations_dashboard_snapshot_route_requires_auth_returns_projection() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    runtime = build_ag_operations_source_runtime(environ={})
    cx_processing_store = InMemoryCxProcessingRunOperationsStore(
        records=[cx_processing_run_record()]
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(
        app,
        registry=registry,
        runtime=runtime,
        retrieval_package_stores={
            "nex-cx": InMemoryRetrievalPackageOperationsStore(
                records=[retrieval_package_record()]
            )
        },
        cx_processing_run_stores={"nex-cx": cx_processing_store},
    )
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/dashboard")
    response = client.get(
        "/admin/v1/operations/dashboard",
        params={"service_id": "nex-cx", "recent_limit": 1},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["projection_status"] == "READY"
    assert payload["rollup_summary"]["jobs"]["total"] == 2
    assert payload["recent_failures"]["jobs"][0]["job_id"] == "job-cx-002"
    assert payload["cx_processing_runs"]["recent_failures"][0]["pipeline_run_id"] == (
        "processing-run-001"
    )
    assert payload["retrieval_threshold_decisions"]["summary"]["total_decisions"] == 2
    assert payload["replay_candidates"][0]["control_path"] == (
        "/admin/v1/operations/jobs/nex-cx/job-cx-002/replay"
    )


def test_operations_dashboard_snapshot_route_rejects_bad_filters() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app)
    client = TestClient(app)

    bad_service = client.get(
        "/admin/v1/operations/dashboard",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_window = client.get(
        "/admin/v1/operations/dashboard",
        params={
            "since": "2026-08-05T00:00:02Z",
            "until": "2026-08-05T00:00:01Z",
        },
        headers=auth_headers(),
    )

    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert bad_window.status_code == 400
    assert bad_window.json()["error_code"] == "ag.operation_time_window_invalid"


def test_build_operations_issue_candidate_projection_flags_service_scope() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )

    projection = build_operations_issue_candidate_projection(
        registry=registry,
        service_id="nex-cx",
        recent_limit=2,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_operations_issue_candidate_projection.v1"
    )
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert [rule["rule_id"] for rule in projection["rules"]] == [
        "operations_source_unavailable.v1",
        "operations_source_not_configured.v1",
        "failed_jobs_present.v1",
        "dead_letter_replay_available.v1",
        "error_events_present.v1",
        "critical_events_present.v1",
        "error_service_logs_present.v1",
        "critical_service_logs_present.v1",
        "active_jobs_review.v1",
        "stale_worker_heartbeat.v1",
        "active_job_without_fresh_worker.v1",
        "retrieval_threshold_decision_checkpoint_missing.v1",
        "retrieval_threshold_live_samples_insufficient.v1",
        "retrieval_threshold_operator_review_required.v1",
        "retrieval_threshold_policy_review_ready.v1",
        "generation_quality_attention_required.v1",
        "generation_remediation_attention_required.v1",
        "remediation_execution_attention_required.v1",
    ]
    assert [
        (candidate["rule_id"], candidate["service_id"], candidate["severity"])
        for candidate in projection["issue_candidates"]
    ] == [
        ("failed_jobs_present.v1", "nex-cx", "ERROR"),
        ("dead_letter_replay_available.v1", "nex-cx", "WARNING"),
        ("active_jobs_review.v1", "nex-cx", "INFO"),
    ]
    replay_candidate = projection["issue_candidates"][1]
    assert replay_candidate["signal"] == {
        "status": "FAILED_DEAD_LETTER",
        "count": 1,
        "threshold": 1,
        "job_ids": ["job-cx-002"],
        "recommended_action": "replay",
        "control_paths": ["/admin/v1/operations/jobs/nex-cx/job-cx-002/replay"],
        "required_payload_fields": [
            "replay_job_id",
            "idempotency_key",
            "requested_by",
            "reason",
        ],
    }
    assert projection["summary"] == {
        "total": 3,
        "by_severity": {
            "DEBUG": 0,
            "INFO": 1,
            "WARNING": 1,
            "ERROR": 1,
            "CRITICAL": 0,
        },
        "by_service": {"nex-cx": 3},
        "by_rule": {
            "failed_jobs_present.v1": 1,
            "dead_letter_replay_available.v1": 1,
            "active_jobs_review.v1": 1,
        },
    }
    assert projection["log_source_statuses"]["nex-cx"] == {
        "status": "NOT_CONFIGURED",
        "log_count": 0,
    }
    assert_ag_operations_projection_contract(projection)


def test_operations_issue_candidate_projection_flags_retrieval_threshold_decisions() -> (
    None
):
    registry = build_operations_source_registry(
        job_queues={"nex-cx": InMemoryJobQueue()},
        event_stores={"nex-cx": InMemoryOperationalEventStore()},
    )

    projection = build_operations_issue_candidate_projection(
        registry=registry,
        retrieval_package_stores={
            "nex-cx": InMemoryRetrievalPackageOperationsStore(
                records=[retrieval_package_record()]
            )
        },
        service_id="nex-cx",
    )

    assert projection["projection_status"] == "READY"
    assert [candidate["rule_id"] for candidate in projection["issue_candidates"]] == [
        "retrieval_threshold_live_samples_insufficient.v1"
    ]
    candidate = projection["issue_candidates"][0]
    assert candidate["candidate_id"] == (
        "nex-cx:INSUFFICIENT_SAMPLES:"
        "retrieval_threshold_live_samples_insufficient.v1"
    )
    assert candidate["severity"] == "INFO"
    assert candidate["signal"] == {
        "status": "INSUFFICIENT_SAMPLES",
        "count": 2,
        "threshold": 1,
        "policy_ids": [
            "retrieval_quality_v1",
            "weighted_rrf_vector_bm25_v1",
        ],
        "decision_statuses": ["OBSERVE"],
        "recommended_actions": ["collect_live_score_samples"],
        "observed_sample_count": 1,
        "minimum_live_samples_before_change": 20,
        "runbook_ids": [
            "retrieval_threshold.collect_live_score_samples.v1",
        ],
        "threshold_decision_paths": [
            "/admin/v1/operations/retrieval-threshold-decisions?"
            "service_id=nex-cx&retrieval_policy_id=retrieval_quality_v1",
            "/admin/v1/operations/retrieval-threshold-decisions?"
            "service_id=nex-cx&retrieval_policy_id=weighted_rrf_vector_bm25_v1",
        ],
        "calibration_samples_paths": [
            "/admin/v1/operations/retrieval-score-calibration?"
            "service_id=nex-cx&retrieval_policy_id=retrieval_quality_v1",
            "/admin/v1/operations/retrieval-score-calibration?"
            "service_id=nex-cx&retrieval_policy_id=weighted_rrf_vector_bm25_v1",
        ],
        "policy_detail_paths": [
            "/admin/v1/policies/retrieval/retrieval_quality_v1",
            "/admin/v1/policies/retrieval/weighted_rrf_vector_bm25_v1",
        ],
    }
    assert projection["summary"]["by_rule"] == {
        "retrieval_threshold_live_samples_insufficient.v1": 1
    }
    assert_ag_operations_projection_contract(projection)


def test_operations_issue_candidate_projection_flags_generation_quality_attention() -> (
    None
):
    projection = build_operations_issue_candidate_projection(
        job_queues={"nex-ag": InMemoryJobQueue()},
        event_store=InMemoryOperationalEventStore(),
        service_log_stores={"nex-ag": InMemoryServiceLogStore()},
        generation_audit_projections=[
            generation_audit_projection_record(
                cx_generation_id="cx-gen-warn",
                coverage_status="WARN",
                boundary_status="PASS",
                issue_codes=["MISSING_CX_GROUNDED_RESPONSE_QUALITY_FIELDS"],
            ),
            generation_audit_projection_record(
                cx_generation_id="cx-gen-fail",
                coverage_status="PASS",
                boundary_status="FAIL",
                issue_codes=["CX_GROUNDED_RESPONSE_QUALITY_FAILED"],
                created_at="2026-08-05T00:00:09Z",
            ),
            generation_audit_projection_record(
                cx_generation_id="cx-gen-pass",
                coverage_status="PASS",
                boundary_status="PASS",
                created_at="2026-08-05T00:00:01Z",
            ),
        ],
        service_id="nex-ag",
        recent_limit=3,
    )

    assert projection["projection_status"] == "READY"
    candidate = projection["issue_candidates"][0]
    assert candidate["rule_id"] == "generation_quality_attention_required.v1"
    assert candidate["candidate_id"] == (
        "nex-ag:generation_quality:generation_quality_attention_required.v1"
    )
    assert candidate["severity"] == "ERROR"
    assert candidate["signal"] == {
        "source_type": "generation_quality",
        "status": "FAIL",
        "count": 2,
        "threshold": 1,
        "coverage_statuses": ["PASS", "WARN"],
        "boundary_statuses": ["FAIL", "PASS"],
        "issue_codes": [
            "CX_GROUNDED_RESPONSE_QUALITY_FAILED",
            "MISSING_CX_GROUNDED_RESPONSE_QUALITY_FIELDS",
        ],
        "cx_generation_ids": ["cx-gen-fail", "cx-gen-warn"],
        "detail_paths": [
            "/admin/v1/generation-audit/generations/cx-gen-fail",
            "/admin/v1/generation-audit/generations/cx-gen-warn",
        ],
    }
    assert projection["summary"]["by_rule"] == {
        "generation_quality_attention_required.v1": 1
    }
    assert_ag_operations_projection_contract(projection)


def test_operations_issue_candidate_projection_flags_generation_remediation_attention() -> (
    None
):
    store = GenerationRemediationTaskStore()
    store.save(
        generation_remediation_task_record(
            remediation_action_id="ag-remediation-active",
            cx_generation_id="cx-gen-active",
            action_type="citation_repair",
            action_status="ASSIGNED",
            priority="HIGH",
            updated_at="2026-08-05T00:00:08Z",
        )
    )
    store.save(
        generation_remediation_task_record(
            remediation_action_id="ag-remediation-waiting",
            cx_generation_id="cx-gen-waiting",
            action_type="retrieval_repair",
            action_status="WAITING_ON_CX",
            priority="URGENT",
            updated_at="2026-08-05T00:00:09Z",
        )
    )
    store.save(
        generation_remediation_task_record(
            remediation_action_id="ag-remediation-failed",
            cx_generation_id="cx-gen-failed",
            action_type="prompt_policy_review",
            action_status="FAILED",
            priority="URGENT",
            updated_at="2026-08-05T00:00:10Z",
        )
    )
    store.save(
        generation_remediation_task_record(
            remediation_action_id="ag-remediation-completed",
            cx_generation_id="cx-gen-completed",
            action_status="COMPLETED",
            priority="NORMAL",
            updated_at="2026-08-05T00:00:11Z",
        )
    )

    projection = build_operations_issue_candidate_projection(
        job_queues={"nex-ag": InMemoryJobQueue()},
        event_store=InMemoryOperationalEventStore(),
        service_log_stores={"nex-ag": InMemoryServiceLogStore()},
        generation_remediation_task_stores={"nex-ag": store},
        service_id="nex-ag",
        recent_limit=5,
    )

    assert projection["projection_status"] == "READY"
    candidate = projection["issue_candidates"][0]
    assert candidate["candidate_id"] == (
        "nex-ag:generation_remediation:"
        "generation_remediation_attention_required.v1"
    )
    assert candidate["rule_id"] == "generation_remediation_attention_required.v1"
    assert candidate["severity"] == "ERROR"
    assert candidate["signal"] == {
        "source_type": "generation_remediation",
        "status": "FAILED",
        "count": 3,
        "threshold": 1,
        "failed_count": 1,
        "urgent_count": 2,
        "waiting_on_cx_count": 1,
        "action_statuses": ["ASSIGNED", "FAILED", "WAITING_ON_CX"],
        "action_types": [
            "citation_repair",
            "prompt_policy_review",
            "retrieval_repair",
        ],
        "priorities": ["HIGH", "URGENT"],
        "remediation_action_ids": [
            "ag-remediation-active",
            "ag-remediation-failed",
            "ag-remediation-waiting",
        ],
        "cx_generation_ids": [
            "cx-gen-active",
            "cx-gen-failed",
            "cx-gen-waiting",
        ],
        "task_detail_paths": [
            "/admin/v1/generation-audit/generations/cx-gen-active"
            "/remediation-tasks/ag-remediation-active",
            "/admin/v1/generation-audit/generations/cx-gen-failed"
            "/remediation-tasks/ag-remediation-failed",
            "/admin/v1/generation-audit/generations/cx-gen-waiting"
            "/remediation-tasks/ag-remediation-waiting",
        ],
        "runbook_ids": [
            "ag.generation_remediation.active_task_review.v1",
            "ag.generation_remediation.cx_dependency_followup.v1",
            "ag.generation_remediation.failed_task_triage.v1",
            "ag.generation_remediation.prompt_policy_review.v1",
        ],
        "recommended_operator_actions": [
            "follow_up_with_cx_owner",
            "prepare_prompt_policy_review",
            "review_active_remediation_task",
            "triage_failed_remediation_task",
        ],
    }
    assert projection["summary"]["by_rule"] == {
        "generation_remediation_attention_required.v1": 1
    }
    assert_ag_operations_projection_contract(projection)


def test_operations_issue_candidate_projection_flags_remediation_execution_attention() -> (
    None
):
    task_store = GenerationRemediationTaskStore()
    task_store.save(
        generation_remediation_task_record(
            remediation_action_id="ag-remediation-sync",
            cx_generation_id="cx-gen-sync",
            action_status="ASSIGNED",
            updated_at="2026-08-05T00:00:10Z",
        )
    )
    task_store.save(
        generation_remediation_task_record(
            remediation_action_id="ag-remediation-failed-exec",
            cx_generation_id="cx-gen-failed-exec",
            action_status="WAITING_ON_CX",
            updated_at="2026-08-05T00:00:12Z",
        )
    )
    execution_store = InMemoryRemediationExecutionOperationsStore(
        records=[
            remediation_execution_record(
                remediation_action_id="ag-remediation-sync",
                parent_cx_generation_id="cx-gen-sync",
                execution_status="SUCCEEDED",
                updated_at="2026-08-05T00:00:10Z",
            ),
            remediation_execution_record(
                remediation_action_id="ag-remediation-failed-exec",
                parent_cx_generation_id="cx-gen-failed-exec",
                execution_status="FAILED",
                updated_at="2026-08-05T00:00:12Z",
            ),
        ]
    )

    projection = build_operations_issue_candidate_projection(
        job_queues={"nex-ag": InMemoryJobQueue()},
        event_store=InMemoryOperationalEventStore(),
        service_log_stores={"nex-ag": InMemoryServiceLogStore()},
        remediation_execution_task_stores={"nex-ag": task_store},
        remediation_execution_stores={"nex-cx": execution_store},
        remediation_execution_projection_builder=(
            build_remediation_execution_operations_projection
        ),
        service_id="nex-ag",
        recent_limit=5,
    )

    assert projection["projection_status"] == "READY"
    assert [candidate["rule_id"] for candidate in projection["issue_candidates"]] == [
        "remediation_execution_attention_required.v1"
    ]
    candidate = projection["issue_candidates"][0]
    assert candidate["candidate_id"] == (
        "nex-ag:remediation_execution:"
        "remediation_execution_attention_required.v1"
    )
    assert candidate["severity"] == "ERROR"
    assert candidate["signal"] == {
        "source_type": "remediation_execution",
        "status": "FAILED",
        "count": 2,
        "threshold": 1,
        "failed_execution_count": 1,
        "failed_task_count": 0,
        "orphan_execution_count": 0,
        "missing_execution_count": 0,
        "sync_required_count": 2,
        "status_sync_states": ["SYNC_REQUIRED"],
        "task_statuses": ["ASSIGNED", "WAITING_ON_CX"],
        "execution_statuses": ["FAILED", "SUCCEEDED"],
        "remediation_action_ids": [
            "ag-remediation-failed-exec",
            "ag-remediation-sync",
        ],
        "cx_generation_ids": ["cx-gen-failed-exec", "cx-gen-sync"],
        "execution_detail_paths": [
            "/admin/v1/operations/remediation-executions"
            "?remediation_action_id=ag-remediation-failed-exec",
            "/admin/v1/operations/remediation-executions"
            "?remediation_action_id=ag-remediation-sync",
        ],
        "task_detail_paths": [
            "/admin/v1/generation-audit/generations/cx-gen-failed-exec"
            "/remediation-tasks/ag-remediation-failed-exec",
            "/admin/v1/generation-audit/generations/cx-gen-sync"
            "/remediation-tasks/ag-remediation-sync",
        ],
        "runbook_ids": [
            "ag.remediation_execution.failed_execution_triage.v1",
            "ag.remediation_execution.status_sync_review.v1",
        ],
        "recommended_operator_actions": [
            "reconcile_remediation_task_status",
            "triage_failed_remediation_execution",
        ],
    }
    assert projection["summary"]["by_rule"] == {
        "remediation_execution_attention_required.v1": 1
    }
    assert_ag_operations_projection_contract(projection)


def test_dashboard_generation_quality_section_handles_malformed_inputs() -> None:
    empty = _dashboard_generation_quality_section(None, limit=3)
    assert empty["summary"]["total"] == 0
    assert empty["recent"] == []
    assert empty["attention"] == []

    projection = _dashboard_generation_quality_section(
        [
            "malformed",
            {"cx_generation_id": "cx-gen-no-quality"},
            {
                "cx_generation_id": "cx-gen-unknown",
                "trace_id": TRACE_ID,
                "request_id": REQUEST_ID,
                "created_at": None,
                "grounded_response_quality": {
                    "coverage_status": "BROKEN",
                    "boundary_status": None,
                    "citation_status": "",
                    "grounding_required": False,
                    "source_quality_issue_count": True,
                    "projection_issue_count": "bad",
                    "issue_codes": ["MISSING_FIELD", 404],
                    "lineage_mismatches": ["retrieval_package_id", None],
                    "recommended_action": "",
                    "retrieval_package_id": "",
                    "retrieval_package_hash": None,
                    "structured_draft_id": "",
                    "evidence_ref_count": "bad",
                    "artifact_handoff_quality_available": False,
                },
            },
            {
                "cx_generation_id": "cx-gen-pass",
                "created_at": datetime(2026, 8, 5, tzinfo=UTC),
                "grounded_response_quality": {
                    "coverage_status": "PASS",
                    "boundary_status": "NOT_REQUIRED",
                    "citation_status": "VALIDATED",
                    "grounding_required": True,
                    "source_quality_issue_count": "2",
                    "projection_issue_count": "3",
                    "issue_codes": [],
                    "lineage_mismatches": [],
                    "recommended_action": "monitor",
                    "retrieval_package_id": "cx-ret-001",
                    "retrieval_package_hash": "d" * 64,
                    "structured_draft_id": "draft-001",
                    "evidence_ref_count": 0,
                    "artifact_handoff_quality_available": True,
                },
            },
        ],
        limit=5,
    )

    assert projection["summary"] == {
        "total": 2,
        "by_coverage_status": {
            "PASS": 1,
            "WARN": 0,
            "FAIL": 0,
            "NOT_REQUIRED": 0,
            "UNKNOWN": 1,
        },
        "by_boundary_status": {
            "PASS": 0,
            "WARN": 0,
            "FAIL": 0,
            "NOT_REQUIRED": 1,
            "UNKNOWN": 1,
        },
        "attention_count": 1,
        "failed_count": 0,
        "warning_count": 0,
    }
    assert [item["cx_generation_id"] for item in projection["recent"]] == [
        "cx-gen-pass",
        "cx-gen-unknown",
    ]
    unknown = projection["attention"][0]
    assert unknown["cx_generation_id"] == "cx-gen-unknown"
    assert unknown["created_at"] is None
    assert unknown["coverage_status"] == "UNKNOWN"
    assert unknown["boundary_status"] == "UNKNOWN"
    assert unknown["citation_status"] is None
    assert unknown["source_quality_issue_count"] is None
    assert unknown["projection_issue_count"] == 0
    assert unknown["issue_codes"] == ["MISSING_FIELD"]
    assert unknown["lineage_mismatches"] == ["retrieval_package_id"]
    assert unknown["recommended_action"] is None
    assert unknown["retrieval_package_id"] is None
    assert unknown["evidence_ref_count"] is None
    pass_item = projection["recent"][0]
    assert pass_item["created_at"] == "2026-08-05T00:00:00Z"
    assert pass_item["source_quality_issue_count"] == 2
    assert pass_item["projection_issue_count"] == 3
    assert pass_item["evidence_ref_count"] == 0
    assert _dashboard_timestamp(None) == "1970-01-01T00:00:00Z"


@pytest.mark.parametrize(
    (
        "coverage_status",
        "boundary_status",
        "expected_severity",
        "expected_runbook_id",
        "expected_action",
        "expected_attention_required",
    ),
    [
        (
            "FAIL",
            "PASS",
            "ERROR",
            "ag.generation_quality.failure_triage.v1",
            "triage_grounded_generation_quality_failure",
            True,
        ),
        (
            "PASS",
            "FAIL",
            "ERROR",
            "ag.generation_quality.failure_triage.v1",
            "triage_grounded_generation_quality_failure",
            True,
        ),
        (
            "WARN",
            "PASS",
            "WARNING",
            "ag.generation_quality.warning_triage.v1",
            "complete_source_quality_metadata",
            True,
        ),
        (
            "UNKNOWN",
            "PASS",
            "WARNING",
            "ag.generation_quality.metadata_gap_triage.v1",
            "restore_missing_quality_metadata",
            True,
        ),
        (
            "PASS",
            "PASS",
            "INFO",
            "ag.generation_quality.no_attention_required.v1",
            "observe",
            False,
        ),
    ],
)
def test_generation_quality_issue_detail_projection_runbook_matrix(
    coverage_status: str,
    boundary_status: str,
    expected_severity: str,
    expected_runbook_id: str,
    expected_action: str,
    expected_attention_required: bool,
) -> None:
    projection = build_generation_quality_issue_detail_projection(
        generation_audit_projection_record(
            cx_generation_id=f"cx-gen-{coverage_status.lower()}-{boundary_status.lower()}",
            coverage_status=coverage_status,
            boundary_status=boundary_status,
            issue_codes=["QUALITY_SIGNAL"],
        ),
        checked_at="2026-08-05T00:01:00Z",
        request_trace_id="request-trace-001",
    )

    assert projection["projection_schema_version"] == (
        "ag_generation_quality_issue_detail_projection.v1"
    )
    assert projection["projection_status"] == "READY"
    assert projection["checked_at"] == "2026-08-05T00:01:00Z"
    assert projection["request_trace_id"] == "request-trace-001"
    assert projection["attention_required"] is expected_attention_required
    assert projection["severity"] == expected_severity
    assert projection["runbook"]["runbook_id"] == expected_runbook_id
    assert (
        projection["runbook"]["recommended_operator_action"] == expected_action
    )
    assert projection["debug_paths"]["generation_audit_detail_path"] == (
        f"/admin/v1/generation-audit/generations/{projection['cx_generation_id']}"
    )
    assert projection["debug_paths"]["retrieval_package_detail_path"] == (
        "/admin/v1/operations/retrieval-packages/cx-ret-001"
    )
    assert projection["redaction_summary"]["raw_content_included"] is False
    assert projection["quality"]["issue_codes"] == ["QUALITY_SIGNAL"]


def test_generation_quality_issue_detail_projection_handles_invalid_source() -> None:
    projection = build_generation_quality_issue_detail_projection(
        {
            "projection_schema_version": "ag_generation_audit_projection.v1",
            "cx_generation_id": "cx-gen-invalid",
            "trace_id": TRACE_ID,
            "request_id": REQUEST_ID,
            "created_at": None,
            "grounded_response_quality": "bad",
        },
        checked_at="2026-08-05T00:02:00Z",
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["cx_generation_id"] == "cx-gen-invalid"
    assert projection["source_projection"] == {
        "projection_schema_version": "ag_generation_audit_projection.v1",
        "created_at": None,
        "grounded_response_quality_available": False,
    }
    assert projection["quality"] is None
    assert projection["attention_required"] is True
    assert projection["severity"] == "WARNING"
    assert projection["runbook"] == {
        "runbook_id": "ag.generation_quality.source_projection_invalid.v1",
        "recommended_operator_action": "restore_generation_quality_projection",
        "operator_steps": [
            "open_generation_audit_source",
            "verify_grounded_response_quality_projection",
            "rerun_generation_audit_projection",
        ],
    }
    assert projection["debug_paths"] == {
        "generation_audit_detail_path": None,
        "operations_dashboard_path": "/admin/v1/operations/dashboard",
        "retrieval_package_detail_path": None,
    }


def test_generation_quality_issue_detail_projection_matches_contract_schema() -> None:
    projection = build_generation_quality_issue_detail_projection(
        generation_audit_projection_record(
            cx_generation_id="cx-gen-contract",
            coverage_status="WARN",
            boundary_status="PASS",
            issue_codes=["MISSING_CX_GROUNDED_RESPONSE_QUALITY_FIELDS"],
        ),
        checked_at="2026-08-05T00:03:00Z",
        request_trace_id=TRACE_ID,
    )

    Draft202012Validator(
        ag_generation_quality_issue_detail_projection_schema()
    ).validate(projection)


def test_generation_quality_issue_candidates_handle_warning_only_attention() -> None:
    assert (
        _issue_candidates_from_generation_quality(
            {
                "attention": [
                    {
                        "coverage_status": "PASS",
                        "boundary_status": "PASS",
                        "cx_generation_id": "cx-gen-pass",
                    }
                ]
            }
        )
        == []
    )

    candidates = _issue_candidates_from_generation_quality(
        {
            "attention": [
                {
                    "coverage_status": "WARN",
                    "boundary_status": "PASS",
                    "issue_codes": ["MISSING_FIELD", 404],
                    "cx_generation_id": "cx-gen-warn",
                    "detail_path": "/admin/v1/generation-audit/generations/cx-gen-warn",
                },
                {
                    "coverage_status": "PASS",
                    "boundary_status": "UNKNOWN",
                    "cx_generation_id": "",
                    "detail_path": "",
                },
                "malformed",
            ]
        }
    )

    assert len(candidates) == 1
    assert candidates[0]["severity"] == "WARNING"
    assert candidates[0]["signal"] == {
        "source_type": "generation_quality",
        "status": "WARN",
        "count": 2,
        "threshold": 1,
        "coverage_statuses": ["PASS", "WARN"],
        "boundary_statuses": ["PASS", "UNKNOWN"],
        "issue_codes": ["MISSING_FIELD"],
        "cx_generation_ids": ["cx-gen-warn"],
        "detail_paths": ["/admin/v1/generation-audit/generations/cx-gen-warn"],
    }


def test_generation_quality_optional_value_helpers_are_defensive() -> None:
    assert _safe_optional_int(None) is None
    assert _safe_optional_int(False) is None
    assert _safe_optional_int(3) == 3
    assert _safe_optional_int(-1) is None
    assert _safe_optional_int("4") == 4
    assert _safe_optional_int("-2") is None
    assert _safe_optional_int("bad") is None
    assert _safe_optional_int(1.5) is None
    assert _nullable_string(None) is None
    assert _nullable_string("") is None
    assert _nullable_string(123) == "123"


def test_operations_issue_candidates_group_threshold_decision_readiness() -> None:
    base_dashboard = {
        "degraded_sources": [],
        "rollups": [],
        "recent_failures": {"logs": []},
        "replay_candidates": [],
        "active_jobs": [],
    }
    decisions = [
        {
            "service_id": "nex-cx",
            "policy_id": "policy-missing",
            "sample_readiness": "NO_DECISION_CHECKPOINT",
            "decision_status": "UNSPECIFIED",
            "recommended_operator_action": "register_threshold_decision",
            "observed_sample_count": 0,
            "minimum_live_samples_before_change": 0,
        },
        {
            "service_id": "nex-cx",
            "policy_id": "policy-review",
            "sample_readiness": "NEEDS_OPERATOR_REVIEW",
            "decision_status": "OBSERVE",
            "recommended_operator_action": "review_low_confidence_samples",
            "observed_sample_count": 21,
            "minimum_live_samples_before_change": 20,
        },
        {
            "service_id": "nex-cx",
            "policy_id": "policy-ready",
            "sample_readiness": "READY_FOR_REVIEW",
            "decision_status": "OBSERVE",
            "recommended_operator_action": "prepare_threshold_policy_review",
            "observed_sample_count": 20,
            "minimum_live_samples_before_change": 20,
        },
        {
            "service_id": "nex-cx",
            "policy_id": "policy-degraded",
            "sample_readiness": "SOURCE_DEGRADED",
        },
        {
            "service_id": "nex-unknown",
            "policy_id": "policy-invalid-service",
            "sample_readiness": "READY_FOR_REVIEW",
        },
        "malformed",
    ]

    candidates = build_operations_issue_candidates(
        {
            **base_dashboard,
            "retrieval_threshold_decisions": {"threshold_decisions": decisions},
        }
    )

    assert [
        (candidate["rule_id"], candidate["severity"], candidate["signal"]["status"])
        for candidate in candidates
    ] == [
        (
            "retrieval_threshold_decision_checkpoint_missing.v1",
            "WARNING",
            "NO_DECISION_CHECKPOINT",
        ),
        (
            "retrieval_threshold_operator_review_required.v1",
            "WARNING",
            "NEEDS_OPERATOR_REVIEW",
        ),
        (
            "retrieval_threshold_policy_review_ready.v1",
            "INFO",
            "READY_FOR_REVIEW",
        ),
    ]
    assert all(candidate["signal"]["runbook_ids"] == [] for candidate in candidates)
    assert all(
        candidate["signal"]["threshold_decision_paths"] == []
        for candidate in candidates
    )
    assert (
        build_operations_issue_candidates(
            {**base_dashboard, "retrieval_threshold_decisions": "bad"}
        )
        == []
    )
    assert (
        build_operations_issue_candidates(
            {
                **base_dashboard,
                "retrieval_threshold_decisions": {"threshold_decisions": "bad"},
            }
        )
        == []
    )
    assert (
        build_operations_issue_candidates(
            {**base_dashboard, "generation_quality": "bad"}
        )
        == []
    )
    assert (
        build_operations_issue_candidates(
            {**base_dashboard, "generation_quality": {"attention": "bad"}}
        )
        == []
    )
    assert (
        build_operations_issue_candidates(
            {**base_dashboard, "generation_remediation": "bad"}
        )
        == []
    )
    assert (
        build_operations_issue_candidates(
            {**base_dashboard, "generation_remediation": {"attention": "bad"}}
        )
        == []
    )
    assert (
        build_operations_issue_candidates(
            {**base_dashboard, "remediation_executions": "bad"}
        )
        == []
    )
    assert (
        build_operations_issue_candidates(
            {**base_dashboard, "remediation_executions": {"attention": "bad"}}
        )
        == []
    )
    remediation_candidates = build_operations_issue_candidates(
        {
            **base_dashboard,
            "generation_remediation": {
                "attention": [
                    {
                        "service_id": "nex-ag",
                        "action_status": "ASSIGNED",
                        "priority": "URGENT",
                        "action_type": "retry_generation",
                        "remediation_action_id": "ag-remediation-urgent",
                        "cx_generation_id": "cx-gen-urgent",
                        "detail_path": (
                            "/admin/v1/generation-audit/generations/cx-gen-urgent"
                            "/remediation-tasks/ag-remediation-urgent"
                        ),
                    },
                    {
                        "service_id": "nex-ag",
                        "remediation_action_id": "ag-remediation-unknown",
                    },
                    {"service_id": "nex-unknown", "action_status": "FAILED"},
                    "malformed",
                ]
            },
        }
    )

    assert len(remediation_candidates) == 1
    assert remediation_candidates[0]["severity"] == "WARNING"
    assert remediation_candidates[0]["signal"]["status"] == "ACTIVE"
    assert remediation_candidates[0]["signal"]["action_statuses"] == [
        "ASSIGNED",
        "UNKNOWN",
    ]
    assert remediation_candidates[0]["signal"]["runbook_ids"] == [
        "ag.generation_remediation.active_task_review.v1",
        "ag.generation_remediation.urgent_task_review.v1",
    ]
    remediation_execution_candidates = _issue_candidates_from_remediation_executions(
        {
            "attention": [
                {
                    "service_id": "nex-ag",
                    "remediation_action_id": "ag-remediation-orphan",
                    "cx_generation_id": "cx-gen-orphan",
                    "task_status": None,
                    "execution_status": "SUCCEEDED",
                    "status_sync_state": "ORPHAN_EXECUTION",
                    "attention_required": True,
                    "execution_detail_path": (
                        "/admin/v1/operations/remediation-executions"
                        "?remediation_action_id=ag-remediation-orphan"
                    ),
                    "task_detail_path": None,
                },
                {
                    "service_id": "nex-ag",
                    "remediation_action_id": "ag-remediation-missing",
                    "cx_generation_id": "cx-gen-missing",
                    "task_status": "ASSIGNED",
                    "execution_status": None,
                    "status_sync_state": "NO_EXECUTION",
                    "attention_required": True,
                    "execution_detail_path": (
                        "/admin/v1/operations/remediation-executions"
                        "?remediation_action_id=ag-remediation-missing"
                    ),
                    "task_detail_path": (
                        "/admin/v1/generation-audit/generations/cx-gen-missing"
                        "/remediation-tasks/ag-remediation-missing"
                    ),
                },
                {"service_id": "nex-unknown", "attention_required": True},
                {"service_id": "nex-ag", "attention_required": False},
                "malformed",
            ]
        }
    )

    assert len(remediation_execution_candidates) == 1
    assert remediation_execution_candidates[0]["severity"] == "ERROR"
    assert remediation_execution_candidates[0]["signal"]["status_sync_states"] == [
        "NO_EXECUTION",
        "ORPHAN_EXECUTION",
    ]
    assert remediation_execution_candidates[0]["signal"]["runbook_ids"] == [
        "ag.remediation_execution.missing_execution_followup.v1",
        "ag.remediation_execution.orphan_execution_review.v1",
    ]


def test_operations_issue_candidate_projection_flags_error_and_critical_service_logs() -> (
    None
):
    log_store = InMemoryServiceLogStore()
    log_store.append(
        build_service_log_entry(
            log_id="log-cx-error-001",
            service_id="nex-cx",
            severity="ERROR",
            logger_name="nex_cx.extractor",
            message="Document extraction failed.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            job_id="job-cx-error-001",
            subject_ref={"type": "cx.document", "id": "doc-error-001"},
            attributes={"password": "private", "stage": "extract"},
            observed_at="2026-08-05T00:00:02Z",
        )
    )
    log_store.append(
        build_service_log_entry(
            log_id="log-cx-critical-001",
            service_id="nex-cx",
            severity="CRITICAL",
            logger_name="nex_cx.chunker",
            message="Chunk persistence is unavailable.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            job_id="job-cx-critical-001",
            subject_ref={"type": "cx.document", "id": "doc-critical-001"},
            attributes={"stage": "chunk"},
            observed_at="2026-08-05T00:00:03Z",
        )
    )
    log_store.append(
        build_service_log_entry(
            log_id="log-cx-info-001",
            service_id="nex-cx",
            severity="INFO",
            logger_name="nex_cx.extractor",
            message="Document extraction started.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            subject_ref={"type": "cx.document", "id": "doc-info-001"},
            attributes={"stage": "extract"},
            observed_at="2026-08-05T00:00:01Z",
        )
    )
    registry = build_operations_source_registry(
        job_queues={"nex-cx": InMemoryJobQueue()},
        event_stores={"nex-cx": InMemoryOperationalEventStore()},
        service_log_stores={"nex-cx": log_store},
    )

    projection = build_operations_issue_candidate_projection(
        registry=registry,
        service_id="nex-cx",
        recent_limit=5,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_status"] == "READY"
    assert projection["log_source_statuses"]["nex-cx"] == {
        "status": "READY",
        "log_count": 3,
    }
    assert [
        (candidate["rule_id"], candidate["severity"], candidate["signal"])
        for candidate in projection["issue_candidates"]
    ] == [
        (
            "critical_service_logs_present.v1",
            "CRITICAL",
            {
                "status": "CRITICAL_SERVICE_LOGS",
                "count": 1,
                "threshold": 1,
                "log_ids": ["log-cx-critical-001"],
                "logger_names": ["nex_cx.chunker"],
            },
        ),
        (
            "error_service_logs_present.v1",
            "ERROR",
            {
                "status": "ERROR_SERVICE_LOGS",
                "count": 1,
                "threshold": 1,
                "log_ids": ["log-cx-error-001"],
                "logger_names": ["nex_cx.extractor"],
            },
        ),
    ]
    assert projection["summary"]["by_rule"] == {
        "critical_service_logs_present.v1": 1,
        "error_service_logs_present.v1": 1,
    }
    assert "private" not in json.dumps(projection)
    assert_ag_operations_projection_contract(projection)


def test_operations_issue_candidate_projection_flags_degraded_and_error_event_sources() -> (
    None
):
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )

    projection = build_operations_issue_candidate_projection(
        registry=registry,
        recent_limit=2,
    )

    assert projection["projection_status"] == "DEGRADED"
    candidates = {
        (candidate["rule_id"], candidate["service_id"], candidate["severity"])
        for candidate in projection["issue_candidates"]
    }
    assert (
        "operations_source_not_configured.v1",
        "nex-mo",
        "WARNING",
    ) in candidates
    assert ("failed_jobs_present.v1", "nex-cx", "ERROR") in candidates
    assert ("dead_letter_replay_available.v1", "nex-cx", "WARNING") in candidates
    assert ("error_events_present.v1", "nex-mo", "ERROR") in candidates
    assert ("active_jobs_review.v1", "nex-cx", "INFO") in candidates
    assert projection["summary"]["by_severity"]["WARNING"] >= 1
    assert projection["summary"]["by_rule"]["operations_source_not_configured.v1"] >= 1
    candidate_ids = [
        candidate["candidate_id"] for candidate in projection["issue_candidates"]
    ]
    assert len(candidate_ids) == len(set(candidate_ids))
    assert_ag_operations_projection_contract(projection)


def test_operations_issue_candidate_projection_flags_worker_reconciliation() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
        worker_heartbeat_stores=build_worker_heartbeat_stores(),
    )

    projection = build_operations_issue_candidate_projection(
        registry=registry,
        service_id="nex-cx",
        recent_limit=2,
        stale_after_seconds=60,
        checked_at="2026-08-05T00:01:20Z",
    )

    assert projection["projection_status"] == "READY"
    assert projection["filters"]["stale_after_seconds"] == 60
    assert projection["worker_source_statuses"]["nex-cx"] == {
        "status": "READY",
        "worker_count": 2,
    }
    assert [
        (candidate["rule_id"], candidate["severity"])
        for candidate in projection["issue_candidates"]
    ] == [
        ("failed_jobs_present.v1", "ERROR"),
        ("dead_letter_replay_available.v1", "WARNING"),
        ("active_jobs_review.v1", "INFO"),
        ("stale_worker_heartbeat.v1", "WARNING"),
        ("active_job_without_fresh_worker.v1", "WARNING"),
    ]
    assert projection["summary"]["by_rule"] == {
        "failed_jobs_present.v1": 1,
        "dead_letter_replay_available.v1": 1,
        "active_jobs_review.v1": 1,
        "stale_worker_heartbeat.v1": 1,
        "active_job_without_fresh_worker.v1": 1,
    }
    stale_candidate = next(
        candidate
        for candidate in projection["issue_candidates"]
        if candidate["rule_id"] == "stale_worker_heartbeat.v1"
    )
    missing_worker_candidate = next(
        candidate
        for candidate in projection["issue_candidates"]
        if candidate["rule_id"] == "active_job_without_fresh_worker.v1"
    )
    assert stale_candidate["signal"]["worker_ids"] == ["cx-worker-001"]
    assert missing_worker_candidate["signal"]["job_ids"] == ["job-cx-001"]
    assert_ag_operations_projection_contract(projection)


def test_operations_issue_candidates_ignore_malformed_candidate_inputs() -> None:
    base_dashboard = {
        "degraded_sources": [],
        "rollups": [],
        "active_jobs": [],
    }

    assert (
        build_operations_issue_candidates(
            {**base_dashboard, "replay_candidates": "not-a-list"}
        )
        == []
    )
    assert (
        build_operations_issue_candidates(
            {
                **base_dashboard,
                "recent_failures": {"logs": "not-a-list"},
                "replay_candidates": [],
            }
        )
        == []
    )

    candidates = build_operations_issue_candidates(
        {
            **base_dashboard,
            "replay_candidates": [
                "not-a-mapping",
                {"service_id": "nex-unknown", "job_id": "job-ignored"},
                {
                    "service_id": "nex-cx",
                    "job_id": "job-cx-002",
                    "control_path": "/admin/v1/operations/jobs/nex-cx/job-cx-002/replay",
                },
            ],
        }
    )

    assert len(candidates) == 1
    assert candidates[0]["rule_id"] == "dead_letter_replay_available.v1"
    assert candidates[0]["signal"]["job_ids"] == ["job-cx-002"]

    log_candidates = build_operations_issue_candidates(
        {
            **base_dashboard,
            "recent_failures": {
                "logs": [
                    "not-a-mapping",
                    {"service_id": "nex-unknown", "severity": "ERROR"},
                    {"service_id": "nex-cx", "severity": "ERROR"},
                    {"service_id": "nex-cx", "severity": "INFO"},
                    {
                        "service_id": "nex-cx",
                        "severity": "ERROR",
                        "log_id": "log-cx-error-001",
                        "logger_name": "nex_cx.extractor",
                    },
                ]
            },
            "replay_candidates": [],
        }
    )

    assert len(log_candidates) == 1
    assert log_candidates[0]["rule_id"] == "error_service_logs_present.v1"
    assert log_candidates[0]["signal"]["log_ids"] == ["log-cx-error-001"]


def test_operations_issue_candidate_projection_suppresses_worker_gap_when_worker_is_fresh() -> (
    None
):
    fresh_store = InMemoryWorkerHeartbeatStore()
    fresh_store.upsert_heartbeat(
        build_worker_heartbeat(
            service_id="nex-cx",
            worker_id="cx-worker-fresh",
            worker_type="cx.document_processing.worker",
            status="BUSY",
            active_job_id="job-cx-001",
            trace_id=TRACE_ID,
            started_at="2026-08-05T00:00:00Z",
            last_seen_at="2026-08-05T00:01:10Z",
            metadata={},
        )
    )

    projection = build_operations_issue_candidate_projection(
        registry=build_operations_source_registry(
            job_queues=build_job_queues(),
            worker_heartbeat_stores={"nex-cx": fresh_store},
        ),
        service_id="nex-cx",
        stale_after_seconds=60,
        checked_at="2026-08-05T00:01:20Z",
    )

    assert "active_job_without_fresh_worker.v1" not in projection["summary"]["by_rule"]
    assert "stale_worker_heartbeat.v1" not in projection["summary"]["by_rule"]
    assert projection["worker_source_statuses"]["nex-cx"]["status"] == "READY"
    assert_ag_operations_projection_contract(projection)


def test_operations_issue_candidate_projection_reconciles_workers_by_service() -> None:
    cx_queue = InMemoryJobQueue()
    cx_queue.enqueue(
        sample_job(
            job_id="shared-job-001",
            idempotency_key="idem-cx-shared-001",
        )
    )
    cx_queue.start_job("shared-job-001", updated_at="2026-08-05T00:00:03Z")
    mo_queue = InMemoryJobQueue()
    mo_queue.enqueue(
        sample_job(
            job_id="shared-job-001",
            job_type="mo.provider_request",
            subject_ref=build_subject_ref("mo.provider", "reranker"),
            idempotency_key="idem-mo-shared-001",
        )
    )
    mo_queue.start_job("shared-job-001", updated_at="2026-08-05T00:00:04Z")
    cx_worker_store = InMemoryWorkerHeartbeatStore()
    cx_worker_store.upsert_heartbeat(
        build_worker_heartbeat(
            service_id="nex-cx",
            worker_id="cx-worker-shared-001",
            worker_type="cx.document_processing.worker",
            status="BUSY",
            active_job_id="shared-job-001",
            trace_id=TRACE_ID,
            started_at="2026-08-05T00:00:00Z",
            last_seen_at="2026-08-05T00:01:10Z",
            metadata={},
        )
    )

    projection = build_operations_issue_candidate_projection(
        registry=build_operations_source_registry(
            job_queues={"nex-cx": cx_queue, "nex-mo": mo_queue},
            worker_heartbeat_stores={
                "nex-cx": cx_worker_store,
                "nex-mo": InMemoryWorkerHeartbeatStore(),
            },
        ),
        stale_after_seconds=60,
        checked_at="2026-08-05T00:01:20Z",
    )

    missing_worker_candidates = [
        candidate
        for candidate in projection["issue_candidates"]
        if candidate["rule_id"] == "active_job_without_fresh_worker.v1"
    ]
    assert [
        (candidate["service_id"], candidate["signal"]["job_ids"])
        for candidate in missing_worker_candidates
    ] == [("nex-mo", ["shared-job-001"])]
    assert_ag_operations_projection_contract(projection)


def test_operations_issue_candidate_projection_flags_worker_source_unavailable() -> (
    None
):
    projection = build_operations_issue_candidate_projection(
        job_queues={"nex-cx": build_job_queues()["nex-cx"]},
        event_store=build_store(),
        worker_heartbeat_stores={"nex-cx": BrokenWorkerHeartbeatStore()},
        service_id="nex-cx",
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["worker_source_statuses"]["nex-cx"]["status"] == "UNAVAILABLE"
    assert (
        "operations_source_unavailable.v1",
        "nex-cx",
        "ERROR",
    ) in {
        (candidate["rule_id"], candidate["service_id"], candidate["severity"])
        for candidate in projection["issue_candidates"]
    }
    assert projection["summary"]["by_rule"]["operations_source_unavailable.v1"] == 1
    assert_ag_operations_projection_contract(projection)


def test_operations_issue_candidate_projection_reports_unavailable_sources() -> None:
    projection = build_operations_issue_candidate_projection(
        job_queues={"nex-cx": BrokenJobQueue()},
        event_store=BrokenOperationalEventStore(),
        service_id="nex-cx",
    )

    assert projection["projection_status"] == "DEGRADED"
    assert {
        (candidate["rule_id"], candidate["service_id"], candidate["severity"])
        for candidate in projection["issue_candidates"]
    } == {
        ("operations_source_unavailable.v1", "nex-cx", "ERROR"),
    }
    assert projection["summary"]["by_rule"] == {
        "operations_source_unavailable.v1": 2,
    }
    assert projection["summary"]["by_severity"]["ERROR"] == 2
    assert_ag_operations_projection_contract(projection)


def test_operations_issue_candidate_rules_and_empty_summary_are_stable() -> None:
    assert operations_issue_candidate_rules()[0] == {
        "rule_id": "operations_source_unavailable.v1",
        "severity": "ERROR",
        "title": "Operations source unavailable",
        "description": "A configured operations source could not be read.",
        "enabled": True,
        "signal_type": "source_status",
    }
    assert summarize_operations_issue_candidates([]) == {
        "total": 0,
        "by_severity": {
            "DEBUG": 0,
            "INFO": 0,
            "WARNING": 0,
            "ERROR": 0,
            "CRITICAL": 0,
        },
        "by_service": {},
        "by_rule": {},
    }


def test_operations_issue_candidate_route_requires_auth_returns_projection() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app, registry=registry)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/issue-candidates")
    response = client.get(
        "/admin/v1/operations/issue-candidates",
        params={"service_id": "nex-cx", "recent_limit": 2},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["projection_status"] == "READY"
    assert payload["summary"]["by_rule"]["failed_jobs_present.v1"] == 1


def test_operations_issue_candidate_route_rejects_bad_filters() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app)
    client = TestClient(app)

    bad_service = client.get(
        "/admin/v1/operations/issue-candidates",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_window = client.get(
        "/admin/v1/operations/issue-candidates",
        params={
            "since": "2026-08-05T00:00:02Z",
            "until": "2026-08-05T00:00:01Z",
        },
        headers=auth_headers(),
    )

    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert bad_window.status_code == 400
    assert bad_window.json()["error_code"] == "ag.operation_time_window_invalid"


def test_unified_operations_route_rejects_bad_filters() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app)
    client = TestClient(app)

    bad_status = client.get(
        "/admin/v1/operations",
        params={"job_status": "BLOCKED"},
        headers=auth_headers(),
    )
    bad_service = client.get(
        "/admin/v1/operations",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_severity = client.get(
        "/admin/v1/operations",
        params={"event_severity": "NOTICE"},
        headers=auth_headers(),
    )
    bad_cursor = client.get(
        "/admin/v1/operations",
        params={"cursor": "before"},
        headers=auth_headers(),
    )
    bad_window = client.get(
        "/admin/v1/operations",
        params={
            "since": "2026-08-05T00:00:02Z",
            "until": "2026-08-05T00:00:01Z",
        },
        headers=auth_headers(),
    )

    assert bad_status.status_code == 400
    assert bad_status.json()["error_code"] == "ag.job_status_invalid"
    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert bad_severity.status_code == 400
    assert bad_severity.json()["error_code"] == "ag.operational_event_severity_invalid"
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["error_code"] == "ag.operation_cursor_invalid"
    assert bad_window.status_code == 400
    assert bad_window.json()["error_code"] == "ag.operation_time_window_invalid"


def test_build_cross_service_trace_timeline_projection_sorts_and_summarizes() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    projection = build_cross_service_trace_timeline_projection(
        trace_id=TRACE_ID,
        registry=registry,
        query_options=build_operation_query_options(limit=3, sort="asc"),
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_cross_service_trace_timeline_projection.v1"
    )
    assert projection["projection_status"] == "DEGRADED"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "trace_id": TRACE_ID,
        "service_id": None,
        "limit": 3,
        "since": None,
        "until": None,
        "sort": "asc",
        "cursor": None,
    }
    assert [
        (item["timeline_item_type"], item["item_id"]) for item in projection["timeline"]
    ] == [
        ("event", "event:event-cx-001"),
        ("job", "job:nex-cx:job-cx-001"),
        ("job", "job:nex-cx:job-cx-002"),
    ]
    assert projection["summary"] == {
        "total": 3,
        "by_item_type": {"event": 1, "job": 2},
        "by_service": {"nex-cx": 3},
    }
    assert projection["pagination"]["next_cursor"] == "3"
    assert projection["job_source_statuses"]["nex-oa"]["status"] == "NOT_CONFIGURED"
    assert projection["event_source_status"] == {
        "status": "READY",
        "event_count": 1,
    }
    assert projection["log_source_statuses"]["nex-cx"] == {
        "status": "NOT_CONFIGURED",
        "log_count": 0,
    }


def test_cross_service_trace_timeline_projection_includes_service_logs() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
        service_log_stores=build_log_stores(),
    )

    projection = build_cross_service_trace_timeline_projection(
        trace_id=TRACE_ID,
        registry=registry,
        service_id="nex-cx",
        query_options=build_operation_query_options(limit=4, sort="asc"),
    )

    assert projection["projection_status"] == "READY"
    assert [
        (item["timeline_item_type"], item["item_id"]) for item in projection["timeline"]
    ] == [
        ("event", "event:event-cx-001"),
        ("log", "log:nex-cx:log-001"),
        ("job", "job:nex-cx:job-cx-001"),
        ("job", "job:nex-cx:job-cx-002"),
    ]
    log_item = projection["timeline"][1]
    assert log_item["operation_timestamp"] == "2026-08-05T00:00:00Z"
    assert log_item["log"]["log_id"] == "log-001"
    assert projection["summary"] == {
        "total": 4,
        "by_item_type": {"event": 1, "log": 1, "job": 2},
        "by_service": {"nex-cx": 4},
    }
    assert projection["log_source_statuses"]["nex-cx"] == {
        "status": "READY",
        "log_count": 1,
    }
    assert_ag_operations_projection_contract(projection)


def test_cross_service_trace_timeline_projection_includes_retrieval_packages() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
        service_log_stores=build_log_stores(),
    )
    retrieval_store = InMemoryRetrievalPackageOperationsStore(
        records=[
            retrieval_package_record(),
            retrieval_package_record(
                retrieval_package_id="retrieval-package-other-trace",
                trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            ),
        ]
    )

    projection = build_cross_service_trace_timeline_projection(
        trace_id=TRACE_ID,
        registry=registry,
        service_id="nex-cx",
        retrieval_package_stores={"nex-cx": retrieval_store},
        query_options=build_operation_query_options(limit=5, sort="asc"),
    )

    assert projection["projection_status"] == "READY"
    assert [
        (item["timeline_item_type"], item["item_id"]) for item in projection["timeline"]
    ] == [
        ("event", "event:event-cx-001"),
        ("log", "log:nex-cx:log-001"),
        (
            "retrieval_package",
            "retrieval_package:nex-cx:retrieval-package-001",
        ),
        ("job", "job:nex-cx:job-cx-001"),
        ("job", "job:nex-cx:job-cx-002"),
    ]
    package_item = projection["timeline"][2]["retrieval_package"]
    assert package_item["service_id"] == "nex-cx"
    assert package_item["operation_type"] == "retrieval_package"
    assert package_item["operation_timestamp"] == "2026-08-05T00:00:02Z"
    assert package_item["retrieval_policy_id"] == "weighted_rrf_vector_bm25_v1"
    assert package_item["permission_snapshot_hash"] == "e" * 64
    assert package_item["evidence_count"] == 2
    assert projection["summary"] == {
        "total": 5,
        "by_item_type": {
            "event": 1,
            "log": 1,
            "retrieval_package": 1,
            "job": 2,
        },
        "by_service": {"nex-cx": 5},
    }
    assert projection["retrieval_package_source_statuses"]["nex-cx"] == {
        "status": "READY",
        "retrieval_package_count": 1,
    }
    assert "other-trace" not in str(projection)
    assert_ag_operations_projection_contract(projection)


def test_retrieval_package_trace_timeline_numeric_helpers_cover_edges() -> None:
    assert ag_operations._mapping_or_empty({"best_score": 0.9}) == {"best_score": 0.9}
    assert ag_operations._mapping_or_empty("not-a-mapping") == {}
    assert ag_operations._operation_number_or_none(0.91) == 0.91
    assert ag_operations._operation_number_or_none(1) == 1.0
    assert ag_operations._operation_number_or_none(True) is None
    assert ag_operations._operation_number_or_none("0.91") is None
    assert ag_operations._operation_integer_or_none(3) == 3
    assert ag_operations._operation_integer_or_none(False) is None
    assert ag_operations._operation_integer_or_none(3.0) is None


def test_cross_service_trace_timeline_projection_filters_service_and_window() -> None:
    projection = build_cross_service_trace_timeline_projection(
        trace_id=TRACE_ID,
        job_queues=build_job_queues(),
        event_store=build_store(),
        service_id="nex-cx",
        query_options=build_operation_query_options(
            limit=2,
            since="2026-08-05T00:00:01Z",
            sort="desc",
        ),
    )

    assert projection["projection_status"] == "READY"
    assert projection["filters"]["service_id"] == "nex-cx"
    assert [item["item_id"] for item in projection["timeline"]] == [
        "job:nex-cx:job-cx-002",
        "job:nex-cx:job-cx-001",
    ]
    assert projection["summary"]["by_item_type"] == {"job": 2}
    assert projection["pagination"]["next_cursor"] is None
    assert projection["log_source_statuses"]["nex-cx"] == {
        "status": "READY",
        "log_count": 0,
    }


def test_cross_service_trace_timeline_projection_reports_unavailable_sources() -> None:
    projection = build_cross_service_trace_timeline_projection(
        trace_id=TRACE_ID,
        job_queues={"nex-cx": BrokenJobQueue()},
        event_store=BrokenOperationalEventStore(),
        service_log_stores={"nex-cx": BrokenServiceLogStore()},
        retrieval_package_stores={"nex-cx": BrokenRetrievalPackageStore()},
        service_id="nex-cx",
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["timeline"] == []
    assert projection["summary"] == {
        "total": 0,
        "by_item_type": {},
        "by_service": {},
    }
    assert projection["job_source_statuses"]["nex-cx"]["status"] == "UNAVAILABLE"
    assert projection["event_source_status"] == {
        "status": "UNAVAILABLE",
        "event_count": 0,
        "error_code": "operational_event.store_unavailable",
        "detail": "operational event store is unavailable",
    }
    assert projection["log_source_statuses"]["nex-cx"] == {
        "status": "UNAVAILABLE",
        "log_count": 0,
        "error_code": "service_log.store_unavailable",
        "detail": "service log store is unavailable",
    }
    assert projection["retrieval_package_source_statuses"]["nex-cx"] == {
        "status": "UNAVAILABLE",
        "retrieval_package_count": 0,
        "error_code": "ag.retrieval_package_source_unavailable",
        "detail": "retrieval package source is unavailable",
    }
    assert_ag_operations_projection_contract(projection)


def test_summarize_trace_timeline_items_counts_empty_and_unknown_services() -> None:
    assert summarize_trace_timeline_items([]) == {
        "total": 0,
        "by_item_type": {},
        "by_service": {},
    }
    assert summarize_trace_timeline_items(
        [
            {
                "timeline_item_type": "custom",
                "service_id": "nex-cx",
            }
        ]
    ) == {
        "total": 1,
        "by_item_type": {"custom": 1},
        "by_service": {"nex-cx": 1},
    }


def test_cross_service_trace_timeline_route_requires_auth_and_returns_projection() -> (
    None
):
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(
        app,
        registry=registry,
        retrieval_package_stores={
            "nex-cx": InMemoryRetrievalPackageOperationsStore(
                records=[retrieval_package_record()]
            )
        },
    )
    client = TestClient(app)

    missing_auth = client.get(f"/admin/v1/operations/traces/{TRACE_ID}")
    response = client.get(
        f"/admin/v1/operations/traces/{TRACE_ID}",
        params={"service_id": "nex-cx", "sort": "asc", "limit": 3},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["filters"]["trace_id"] == TRACE_ID
    assert payload["filters"]["service_id"] == "nex-cx"
    assert [item["timeline_item_type"] for item in payload["timeline"]] == [
        "event",
        "retrieval_package",
        "job",
    ]
    assert payload["retrieval_package_source_statuses"]["nex-cx"] == {
        "status": "READY",
        "retrieval_package_count": 1,
    }
    assert payload["log_source_statuses"]["nex-cx"] == {
        "status": "NOT_CONFIGURED",
        "log_count": 0,
    }


def test_cross_service_trace_timeline_route_rejects_bad_filters() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app)
    client = TestClient(app)

    bad_service = client.get(
        f"/admin/v1/operations/traces/{TRACE_ID}",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_cursor = client.get(
        f"/admin/v1/operations/traces/{TRACE_ID}",
        params={"cursor": "before"},
        headers=auth_headers(),
    )

    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["error_code"] == "ag.operation_cursor_invalid"


def test_ag_operations_contract_schema_accepts_runtime_projection_family() -> None:
    job_queues = build_job_queues()
    event_stores = build_event_stores()
    registry = build_operations_source_registry(
        job_queues=job_queues,
        event_stores=event_stores,
        service_log_stores=build_log_stores(),
    )
    runtime = build_ag_operations_source_runtime(environ={})
    job = job_queues["nex-cx"].get_job("job-cx-001")
    event = build_store().get_event("event-002")
    assert job is not None
    assert event is not None

    projections = [
        build_operation_source_readiness_projection(
            runtime=runtime,
            service_id="nex-cx",
            request_trace_id=TRACE_ID,
        ),
        build_operational_event_projection(
            build_store(),
            service_id="nex-mo",
            severity="ERROR",
            request_trace_id=TRACE_ID,
        ),
        build_operational_event_detail_projection(
            event,
            request_trace_id=TRACE_ID,
        ),
        build_service_log_projection(
            service_log_stores=build_log_stores(),
            service_id="nex-cx",
            request_trace_id=TRACE_ID,
        ),
        build_service_log_detail_projection(
            build_log_store().get_log("log-001"),
            request_trace_id=TRACE_ID,
        ),
        build_operational_event_taxonomy_projection(
            service_id="nex-cx",
            event_type=CX_PROCESSING_EVENT_STARTED,
            request_trace_id=TRACE_ID,
        ),
        build_job_operations_projection(
            job_queues,
            service_id="nex-cx",
            status=RUNNING,
            request_trace_id=TRACE_ID,
        ),
        build_job_operation_detail_projection(
            job,
            service_id="nex-cx",
            event_store=build_store(),
            request_trace_id=TRACE_ID,
        ),
        build_unified_operations_projection(
            registry=registry,
            service_id="nex-cx",
            job_status=RUNNING,
            event_severity="INFO",
            trace_id=TRACE_ID,
            request_trace_id=TRACE_ID,
        ),
        build_operations_rollup_metrics_projection(
            registry=registry,
            service_id="nex-cx",
            request_trace_id=TRACE_ID,
        ),
        build_operations_dashboard_snapshot_projection(
            registry=registry,
            service_id="nex-cx",
            request_trace_id=TRACE_ID,
        ),
        build_operations_issue_candidate_projection(
            registry=registry,
            service_id="nex-cx",
            request_trace_id=TRACE_ID,
        ),
        build_worker_runtime_projection(
            registry=build_operations_source_registry(
                worker_heartbeat_stores=build_worker_heartbeat_stores(),
            ),
            service_id="nex-cx",
            checked_at="2026-08-05T00:01:20Z",
            request_trace_id=TRACE_ID,
        ),
        build_cross_service_trace_timeline_projection(
            trace_id=TRACE_ID,
            registry=registry,
            service_id="nex-cx",
            request_trace_id=TRACE_ID,
        ),
    ]

    for projection in projections:
        assert_ag_operations_projection_contract(projection)


def test_build_operational_event_projection_filters_and_summarizes() -> None:
    projection = build_operational_event_projection(
        build_store(),
        service_id="nex-mo",
        severity="error",
        limit=9999,
        request_trace_id=TRACE_ID,
    )

    assert (
        projection["projection_schema_version"] == "ag_operational_event_projection.v1"
    )
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-mo",
        "severity": "ERROR",
        "event_type": None,
        "trace_id": None,
        "q": None,
        "limit": 500,
        "since": None,
        "until": None,
        "sort": "desc",
        "cursor": None,
    }
    assert [event["event_id"] for event in projection["events"]] == ["event-002"]
    assert projection["summary"]["by_severity"]["ERROR"] == 1
    assert projection["pagination"]["returned"] == 1
    assert "Bearer private" not in str(projection)


def test_build_operational_event_projection_can_omit_request_trace_id() -> None:
    projection = build_operational_event_projection(build_store(), limit=1)

    assert "request_trace_id" not in projection
    assert projection["filters"]["limit"] == 1
    assert len(projection["events"]) == 1


def test_build_operational_event_projection_applies_text_query() -> None:
    by_message = build_operational_event_projection(build_store(), q="provider")
    by_subject = build_operational_event_projection(build_store(), q="doc-001")
    by_detail = build_operational_event_projection(build_store(), q="run-001")
    no_match = build_operational_event_projection(build_store(), q="not-observed")

    assert [event["event_id"] for event in by_message["events"]] == ["event-002"]
    assert by_message["filters"]["q"] == "provider"
    assert by_message["pagination"]["total_after_filters"] == 1
    assert [event["event_id"] for event in by_subject["events"]] == ["event-001"]
    assert [event["event_id"] for event in by_detail["events"]] == ["event-001"]
    assert no_match["events"] == []
    assert no_match["summary"]["total"] == 0


def test_operation_text_search_helpers_handle_minimal_records() -> None:
    minimal_event = {
        "event_id": "event-minimal",
        "service_id": "nex-cx",
        "event_type": "cx.minimal",
        "severity": "INFO",
        "message": "Minimal event.",
        "trace_id": None,
        "request_id": None,
        "subject_ref": None,
        "details": [],
    }
    minimal_log = {
        "log_id": "log-minimal",
        "service_id": "nex-cx",
        "severity": "INFO",
        "logger_name": "nex_cx.minimal",
        "message": "Minimal log.",
        "trace_id": None,
        "request_id": None,
        "job_id": None,
        "subject_ref": None,
        "attributes": [],
        "redacted_attribute_keys": None,
    }

    assert _operational_event_matches_query(minimal_event, "minimal") is True
    assert _operational_event_matches_query(minimal_event, "missing") is False
    assert _service_log_matches_query(minimal_log, "minimal") is True
    assert _service_log_matches_query(minimal_log, "missing") is False


def test_normalize_operation_event_search_query_strips_and_rejects_long_values() -> (
    None
):
    assert normalize_operation_event_search_query("  Provider  ") == "Provider"
    assert normalize_operation_event_search_query("   ") is None

    with pytest.raises(OperationsQueryError) as exc_info:
        normalize_operation_event_search_query("x" * 129)

    assert exc_info.value.error_code == "ag.operation_event_query_invalid"


def test_build_operational_event_detail_projection_returns_safe_event_summary() -> None:
    event = build_store().get_event("event-002")
    assert event is not None

    projection = build_operational_event_detail_projection(
        event,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_operational_event_detail_projection.v1"
    )
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["event"]["event_id"] == "event-002"
    assert projection["event"]["details"]["authorization"] == "<redacted>"
    assert projection["summary"] == {
        "event_id": "event-002",
        "service_id": "nex-mo",
        "event_type": "mo.provider.failed",
        "severity": "ERROR",
        "trace_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "subject_ref": {"type": "mo.provider", "id": "embedding"},
        "created_at": "2026-08-05T00:00:01Z",
    }
    assert "Bearer private" not in str(projection)


def test_build_operational_event_taxonomy_projection_filters_and_summarizes() -> None:
    projection = build_operational_event_taxonomy_projection(
        service_id="nex-cx",
        event_type=CX_PROCESSING_EVENT_STARTED,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_operational_event_taxonomy_projection.v1"
    )
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-cx",
        "event_type": CX_PROCESSING_EVENT_STARTED,
    }
    assert [item["event_type"] for item in projection["event_types"]] == [
        CX_PROCESSING_EVENT_STARTED
    ]
    assert projection["summary"]["by_service"] == {"nex-cx": 1}


def test_operational_event_taxonomy_route_requires_auth_returns_filtered_projection() -> (
    None
):
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_taxonomy_routes(app)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/event-taxonomy")
    response = client.get(
        "/admin/v1/operations/event-taxonomy",
        params={"event_type": CX_PROCESSING_EVENT_FAILED},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["event_types"][0]["event_type"] == CX_PROCESSING_EVENT_FAILED
    assert payload["event_types"][0]["default_severity"] == "ERROR"


def test_operational_event_taxonomy_route_rejects_bad_service() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_taxonomy_routes(app)

    response = TestClient(app).get(
        "/admin/v1/operations/event-taxonomy",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "ag.event_taxonomy_service_invalid"


def test_operational_events_route_requires_auth() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_routes(app, store=build_store())

    response = TestClient(app).get("/admin/v1/operations/events")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_operational_events_route_returns_filtered_projection() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_routes(app, store=build_store())

    response = TestClient(app).get(
        "/admin/v1/operations/events",
        params={"service_id": "nex-cx", "q": "doc-001", "limit": 1},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["filters"]["service_id"] == "nex-cx"
    assert payload["filters"]["q"] == "doc-001"
    assert payload["events"][0]["event_id"] == "event-001"
    assert payload["summary"]["total"] == 1


def test_operational_event_detail_route_requires_auth_returns_event_and_404() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_routes(app, store=build_store())
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/events/event-001")
    response = client.get(
        "/admin/v1/operations/events/event-001",
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )
    missing_event = client.get(
        "/admin/v1/operations/events/event-missing",
        headers=auth_headers(),
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["event"]["event_id"] == "event-001"
    assert payload["summary"]["subject_ref"] == {"type": "cx.document", "id": "doc-001"}
    assert missing_event.status_code == 404
    assert missing_event.json()["error_code"] == "ag.operational_event_not_found"


def test_operational_events_route_applies_sort_cursor_and_window() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_routes(app, store=build_store())

    response = TestClient(app).get(
        "/admin/v1/operations/events",
        params={
            "since": "2026-08-05T00:00:00Z",
            "sort": "asc",
            "limit": 1,
            "cursor": "1",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filters"]["sort"] == "asc"
    assert payload["filters"]["cursor"] == "1"
    assert [event["event_id"] for event in payload["events"]] == ["event-002"]
    assert payload["pagination"]["returned"] == 1
    assert payload["pagination"]["next_cursor"] is None


def test_operational_events_route_rejects_bad_severity() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_routes(app, store=build_store())

    response = TestClient(app).get(
        "/admin/v1/operations/events",
        params={"severity": "NOTICE"},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "ag.operational_event_severity_invalid"

    bad_sort = TestClient(app).get(
        "/admin/v1/operations/events",
        params={"sort": "latest"},
        headers=auth_headers(),
    )
    assert bad_sort.status_code == 400
    assert bad_sort.json()["error_code"] == "ag.operation_sort_invalid"

    bad_query = TestClient(app).get(
        "/admin/v1/operations/events",
        params={"q": "x" * 129},
        headers=auth_headers(),
    )
    assert bad_query.status_code == 400
    assert bad_query.json()["error_code"] == "ag.operation_event_query_invalid"


def test_build_service_log_projection_filters_searches_and_summarizes() -> None:
    projection = build_service_log_projection(
        service_log_stores=build_log_stores(),
        service_id="nex-mo",
        severity="error",
        q="vllm",
        limit=9999,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == "ag_service_log_projection.v1"
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-mo",
        "severity": "ERROR",
        "logger_name": None,
        "trace_id": None,
        "request_id": None,
        "job_id": None,
        "subject_type": None,
        "subject_id": None,
        "q": "vllm",
        "limit": 500,
        "since": None,
        "until": None,
        "sort": "desc",
        "cursor": None,
    }
    assert [entry["log_id"] for entry in projection["logs"]] == ["log-002"]
    assert projection["summary"]["by_severity"]["ERROR"] == 1
    assert projection["source_statuses"]["nex-mo"] == {
        "status": "READY",
        "log_count": 1,
    }
    assert projection["pagination"]["returned"] == 1
    assert "Bearer private" not in str(projection)

    by_redacted_key = build_service_log_projection(
        service_log_stores=build_log_stores(),
        service_id="nex-mo",
        q="authorization",
    )
    assert [entry["log_id"] for entry in by_redacted_key["logs"]] == ["log-002"]


def test_service_log_query_policy_projection_reports_query_and_retention_contract() -> (
    None
):
    projection = build_service_log_query_policy_projection(
        retention_days=999,
        request_trace_id=TRACE_ID,
    )
    policy = projection["policy"]

    assert projection["projection_schema_version"] == (
        "ag_service_log_query_policy_projection.v1"
    )
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["projection_status"] == "READY"
    assert policy["policy_schema_version"] == "service_log_query_policy.v1"
    assert policy["policy_id"] == "service-log-query-retention-v1"
    assert policy["applies_to"] == [
        "nex-ae-api",
        "nex-ag",
        "nex-cx",
        "nex-mo",
        "nex-oa",
    ]
    assert policy["query"]["default_limit"] == 50
    assert policy["query"]["max_limit"] == 500
    assert policy["query"]["max_q_length"] == 128
    assert set(policy["query"]["supported_filters"]) >= {
        "service_id",
        "severity",
        "trace_id",
        "q",
        "limit",
    }
    assert policy["retention"] == {
        "default_retention_days": 365,
        "minimum_retention_days": 7,
        "maximum_retention_days": 365,
        "storage_owner": "service-local",
        "purge_execution": "service_local_control_api",
        "future_archive_target": "object_storage_or_cold_table",
    }
    assert policy["redaction"]["redacted_value"] == "<redacted>"
    assert "authorization" in policy["redaction"]["sensitive_key_parts"]
    assert projection["summary"] == {
        "policy_id": "service-log-query-retention-v1",
        "status": "ACTIVE",
        "default_limit": 50,
        "max_limit": 500,
        "default_retention_days": 365,
        "supported_filter_count": 14,
    }
    assert_ag_operations_projection_contract(projection)


def test_service_log_query_policy_helpers_clamp_retention() -> None:
    projection = build_service_log_query_policy_projection()

    assert "request_trace_id" not in projection
    assert normalize_service_log_retention_days(1) == 7
    assert normalize_service_log_retention_days(30) == 30
    assert normalize_service_log_retention_days(9999) == 365
    assert service_log_query_policy()["retention"]["default_retention_days"] == 30


def test_service_log_retention_dry_run_projection_reports_safe_candidates() -> None:
    projection = build_service_log_retention_dry_run_projection(
        service_log_stores=build_retention_log_stores(),
        service_id="nex-cx",
        retention_days=30,
        limit=1,
        checked_at="2026-08-05T00:00:00Z",
        request_trace_id=TRACE_ID,
    )
    candidate = projection["retention_candidates"][0]

    assert projection["projection_schema_version"] == (
        "ag_service_log_retention_dry_run_projection.v1"
    )
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["retention_cutoff"] == "2026-07-06T00:00:00Z"
    assert projection["dry_run"] == {
        "delete_enabled": False,
        "purge_execution": "service_local_control_api",
        "storage_owner": "service-local",
    }
    assert projection["filters"] == {
        "service_id": "nex-cx",
        "retention_days": 30,
        "limit": 1,
        "scan_limit": 500,
    }
    assert projection["source_statuses"]["nex-cx"] == {
        "status": "READY",
        "log_count": 3,
        "candidate_count": 2,
    }
    assert candidate["log_id"] == "log-retention-001"
    assert candidate["age_days"] == 65
    assert candidate["redacted_attribute_keys"] == ["authorization"]
    assert "message" not in candidate
    assert "attributes" not in candidate
    assert "Bearer old-private" not in str(projection)
    assert projection["summary"]["total_candidate_count"] == 2
    assert projection["summary"]["returned_candidate_count"] == 1
    assert projection["summary"]["by_severity"]["ERROR"] == 1
    assert projection["summary"]["by_severity"]["WARNING"] == 1
    assert projection["pagination"] == {
        "limit": 1,
        "cursor": None,
        "returned": 1,
        "total_after_filters": 2,
        "next_cursor": "1",
    }
    assert_ag_operations_projection_contract(projection)


def test_service_log_retention_dry_run_projection_reports_degraded_sources() -> None:
    registry = build_operations_source_registry(
        service_log_stores=build_retention_log_stores()
    )
    projection = build_service_log_retention_dry_run_projection(
        registry=registry,
        retention_days=999,
        limit=0,
        checked_at="2026-08-05T00:00:00Z",
    )
    unavailable_projection = build_service_log_retention_dry_run_projection(
        service_log_stores={"nex-mo": BrokenServiceLogStore()},
        service_id="nex-mo",
        checked_at="2026-08-05T00:00:00Z",
    )

    assert "request_trace_id" not in projection
    assert projection["projection_status"] == "DEGRADED"
    assert projection["filters"]["retention_days"] == 365
    assert projection["filters"]["limit"] == 1
    assert (
        projection["source_registry"]["sources"]["nex-cx"]["capabilities"]["logs"]
        is True
    )
    assert projection["source_statuses"]["nex-cx"]["candidate_count"] == 0
    assert projection["source_statuses"]["nex-ag"]["status"] == "NOT_CONFIGURED"
    assert projection["summary"]["source_statuses"] == {
        "NOT_CONFIGURED": 4,
        "READY": 1,
    }
    assert projection["retention_candidates"] == []
    assert unavailable_projection["projection_status"] == "DEGRADED"
    assert (
        unavailable_projection["source_statuses"]["nex-mo"]["status"] == "UNAVAILABLE"
    )
    assert unavailable_projection["source_statuses"]["nex-mo"]["candidate_count"] == 0
    assert_ag_operations_projection_contract(projection)
    assert_ag_operations_projection_contract(unavailable_projection)


def test_service_log_retention_history_projection_filters_and_paginates() -> None:
    registry = build_operations_source_registry(
        service_log_stores=build_retention_history_stores()
    )

    projection = build_service_log_retention_history_projection(
        registry=registry,
        service_id="nex-cx",
        mode="execute",
        execution_status="succeeded",
        limit=1,
        request_trace_id=TRACE_ID,
    )

    history_entry = projection["retention_history"][0]
    assert projection["projection_schema_version"] == (
        AG_SERVICE_LOG_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION
    )
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-cx",
        "mode": "EXECUTE",
        "execution_status": "SUCCEEDED",
        "trace_id": None,
        "request_id": None,
        "idempotency_key": None,
        "limit": 1,
        "since": None,
        "until": None,
        "sort": "desc",
        "cursor": None,
    }
    assert history_entry["execution_id"] == "retention-execution-001"
    assert history_entry["recorded_at"] == "2026-08-05T00:00:02Z"
    assert history_entry["deleted_count"] == 1
    assert history_entry["execution"]["audit"]["audit_event_id"] == (
        "retention-audit-001"
    )
    assert projection["source_statuses"]["nex-cx"] == {
        "status": "READY",
        "history_count": 1,
    }
    assert (
        projection["source_registry"]["sources"]["nex-cx"]["capabilities"]["logs"]
        is True
    )
    assert projection["summary"]["total"] == 1
    assert projection["summary"]["by_mode"]["EXECUTE"] == 1
    assert projection["summary"]["by_status"]["SUCCEEDED"] == 1
    assert projection["summary"]["by_service"] == {"nex-cx": 1}
    assert projection["summary"]["candidate_count"] == 2
    assert projection["summary"]["deleted_count"] == 1
    assert projection["summary"]["source_statuses"] == {"READY": 1}
    assert projection["summary"]["scanned_history_count"] == 1
    assert projection["summary"]["returned_history_count"] == 1
    assert projection["pagination"] == {
        "limit": 1,
        "cursor": None,
        "returned": 1,
        "total_after_filters": 1,
        "next_cursor": None,
    }
    assert_ag_operations_projection_contract(projection)


def test_service_log_retention_history_projection_reports_degraded_sources() -> None:
    projection = build_service_log_retention_history_projection(
        service_log_stores=build_retention_history_stores(),
        request_trace_id=TRACE_ID,
    )
    unavailable_projection = build_service_log_retention_history_projection(
        service_log_stores={"nex-mo": BrokenServiceLogStore()},
        service_id="nex-mo",
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["source_statuses"]["nex-cx"] == {
        "status": "READY",
        "history_count": 2,
    }
    assert projection["source_statuses"]["nex-ag"]["status"] == "NOT_CONFIGURED"
    assert projection["summary"]["source_statuses"] == {
        "NOT_CONFIGURED": 4,
        "READY": 1,
    }
    assert projection["summary"]["scanned_history_count"] == 2
    assert unavailable_projection["projection_status"] == "DEGRADED"
    assert unavailable_projection["source_statuses"]["nex-mo"] == {
        "status": "UNAVAILABLE",
        "history_count": 0,
        "error_code": "service_log_retention_history.store_unavailable",
        "detail": "service log retention history store is unavailable",
    }
    assert unavailable_projection["summary"]["source_statuses"] == {"UNAVAILABLE": 1}
    assert_ag_operations_projection_contract(projection)
    assert_ag_operations_projection_contract(unavailable_projection)


def test_service_log_retention_dispatch_projection_wraps_service_response() -> None:
    projection = build_service_log_retention_dispatch_projection(
        service_id="nex-cx",
        service_response=service_log_retention_execution_response(
            service_id="nex-cx",
            mode="EXECUTE",
            execution_status="SUCCEEDED",
            retention_cutoff="2026-07-06T00:00:00Z",
            checked_at="2026-08-05T00:00:00Z",
            candidate_count=2,
            deleted_count=1,
            delete_enabled=True,
            max_delete_count=1,
        ),
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        AG_SERVICE_LOG_RETENTION_DISPATCH_SCHEMA_VERSION
    )
    assert projection["dispatch_status"] == "SUCCEEDED"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["audit_event"] == {
        "ok": False,
        "error_code": "ag.service_log_retention_audit_not_requested",
    }
    assert projection["summary"] == {
        "service_id": "nex-cx",
        "mode": "EXECUTE",
        "execution_status": "SUCCEEDED",
        "candidate_count": 2,
        "deleted_count": 1,
        "delete_enabled": True,
        "max_delete_count": 1,
    }


def test_service_log_retention_route_dispatches_to_service_client() -> None:
    control_client = RecordingServiceLogRetentionClient()
    audit_store = InMemoryOperationalEventStore()
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_service_log_routes(
        app,
        retention_control_client=control_client,
        audit_event_store=audit_store,
    )
    client = TestClient(app)
    headers = {
        **auth_headers(),
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }

    response = client.post(
        "/admin/v1/operations/logs/retention/nex-cx/purge",
        json={
            "retention_cutoff": "2026-07-06T00:00:00Z",
            "checked_at": "2026-08-05T00:00:00Z",
            "retention_days": 30,
            "dry_run": False,
            "delete_enabled": True,
            "max_delete_count": 1,
            "requested_by": {
                "actor_type": "service",
                "actor_id": "nex-ag",
                "service_id": "nex-ag",
            },
            "idempotency_key": "purge-001",
        },
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == (
        AG_SERVICE_LOG_RETENTION_DISPATCH_SCHEMA_VERSION
    )
    assert payload["summary"] == {
        "service_id": "nex-cx",
        "mode": "EXECUTE",
        "execution_status": "SUCCEEDED",
        "candidate_count": 2,
        "deleted_count": 1,
        "delete_enabled": True,
        "max_delete_count": 1,
    }
    assert payload["audit_event"]["event_type"] == (
        AG_SERVICE_LOG_RETENTION_EVENT_SUCCEEDED
    )
    assert control_client.calls == [
        {
            "service_id": "nex-cx",
            "request_id": REQUEST_ID,
            "trace_id": TRACE_ID,
            "retention_cutoff": "2026-07-06T00:00:00Z",
            "retention_days": 30,
            "checked_at": "2026-08-05T00:00:00Z",
            "dry_run": False,
            "delete_enabled": True,
            "max_delete_count": 1,
            "requested_by": {
                "actor_type": "service",
                "actor_id": "nex-ag",
                "service_id": "nex-ag",
            },
            "idempotency_key": "purge-001",
        }
    ]
    audit_events = audit_store.list_events(service_id="nex-ag", limit=10)
    assert audit_events[0]["event_type"] == AG_SERVICE_LOG_RETENTION_EVENT_SUCCEEDED
    assert audit_events[0]["details"]["deleted_count"] == 1


def test_service_log_retention_route_blocks_unsafe_execute_before_dispatch() -> None:
    control_client = RecordingServiceLogRetentionClient()
    audit_store = InMemoryOperationalEventStore()
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_service_log_routes(
        app,
        retention_control_client=control_client,
        audit_event_store=audit_store,
    )
    client = TestClient(app)

    missing_auth = client.post(
        "/admin/v1/operations/logs/retention/nex-cx/purge",
        json={"retention_cutoff": "2026-07-06T00:00:00Z"},
    )
    bad_service = client.post(
        "/admin/v1/operations/logs/retention/nex-unknown/purge",
        json={"retention_cutoff": "2026-07-06T00:00:00Z"},
        headers=auth_headers(),
    )
    blocked = client.post(
        "/admin/v1/operations/logs/retention/nex-cx/purge",
        json={
            "retention_cutoff": "2026-07-06T00:00:00Z",
            "dry_run": False,
        },
        headers=auth_headers(),
    )
    invalid_payload = client.post(
        "/admin/v1/operations/logs/retention/nex-cx/purge",
        json={
            "retention_cutoff": "2026-07-06T00:00:00Z",
            "dry_run": True,
            "delete_enabled": True,
        },
        headers=auth_headers(),
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.service_log_service_invalid"
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "ag.service_log_retention_delete_not_enabled"
    assert invalid_payload.status_code == 422
    assert invalid_payload.json()["error_code"] == (
        "ag.service_log_retention_payload_invalid"
    )
    assert control_client.calls == []
    audit_events = audit_store.list_events(service_id="nex-ag", limit=10)
    assert audit_events[0]["event_type"] == AG_SERVICE_LOG_RETENTION_EVENT_FAILED
    assert audit_events[0]["details"]["error_code"] == (
        "ag.service_log_retention_payload_invalid"
    )
    assert audit_events[1]["details"]["error_code"] == (
        "ag.service_log_retention_delete_not_enabled"
    )


def test_service_log_retention_history_route_filters_and_rejects_edges() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_service_log_routes(
        app,
        service_log_stores=build_retention_history_stores(),
    )
    client = TestClient(app)

    missing_auth = client.get(
        "/admin/v1/operations/logs/retention/history",
        params={"service_id": "nex-cx"},
    )
    invalid_mode = client.get(
        "/admin/v1/operations/logs/retention/history",
        params={"service_id": "nex-cx", "mode": "preview"},
        headers=auth_headers(),
    )
    invalid_status = client.get(
        "/admin/v1/operations/logs/retention/history",
        params={"service_id": "nex-cx", "execution_status": "done"},
        headers=auth_headers(),
    )
    response = client.get(
        "/admin/v1/operations/logs/retention/history",
        params={
            "service_id": "nex-cx",
            "mode": "execute",
            "execution_status": "succeeded",
            "trace_id": TRACE_ID,
            "request_id": REQUEST_ID,
            "idempotency_key": "purge-001",
            "limit": 1,
        },
        headers=auth_headers(),
    )

    assert missing_auth.status_code == 401
    assert invalid_mode.status_code == 422
    assert invalid_mode.json()["error_code"] == (
        "ag.service_log_retention_history_mode_invalid"
    )
    assert invalid_status.status_code == 422
    assert invalid_status.json()["error_code"] == (
        "ag.service_log_retention_history_status_invalid"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == (
        AG_SERVICE_LOG_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION
    )
    assert payload["filters"]["mode"] == "EXECUTE"
    assert payload["filters"]["execution_status"] == "SUCCEEDED"
    assert payload["retention_history"][0]["execution_id"] == "retention-execution-001"
    assert payload["summary"]["deleted_count"] == 1
    assert_ag_operations_projection_contract(payload)


def test_service_log_retention_route_maps_service_client_errors() -> None:
    audit_store = InMemoryOperationalEventStore()
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_service_log_routes(
        app,
        retention_control_client=RecordingServiceLogRetentionClient(
            error=AgServiceLogRetentionError(
                status_code=503,
                error_code="service_log.store_unavailable",
                detail="service log store is unavailable",
                retryable=True,
            )
        ),
        audit_event_store=audit_store,
    )

    response = TestClient(app).post(
        "/admin/v1/operations/logs/retention/nex-cx/purge",
        json={"retention_cutoff": "2026-07-06T00:00:00Z"},
        headers=auth_headers(),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "service_log.store_unavailable"
    assert response.json()["type"].endswith("/service-log-retention-dispatch-failed")
    assert response.json()["details"]["audit_event"]["event_type"] == (
        AG_SERVICE_LOG_RETENTION_EVENT_FAILED
    )
    audit_events = audit_store.list_events(service_id="nex-ag", limit=10)
    assert audit_events[0]["event_type"] == AG_SERVICE_LOG_RETENTION_EVENT_FAILED
    assert audit_events[0]["details"]["retryable"] is True


def test_service_log_retention_dispatch_request_rejects_payload_edges() -> None:
    with pytest.raises(AgServiceLogRetentionError) as bad_shape:
        ag_operations._service_log_retention_dispatch_request(["not", "object"])  # type: ignore[arg-type]
    with pytest.raises(AgServiceLogRetentionError) as missing_cutoff:
        ag_operations._service_log_retention_dispatch_request({})
    with pytest.raises(AgServiceLogRetentionError) as blank_cutoff:
        ag_operations._service_log_retention_dispatch_request({"retention_cutoff": ""})
    with pytest.raises(AgServiceLogRetentionError) as bad_bool:
        ag_operations._service_log_retention_dispatch_request(
            {"retention_cutoff": "2026-07-06T00:00:00Z", "dry_run": "yes"}
        )
    with pytest.raises(AgServiceLogRetentionError) as bad_int:
        ag_operations._service_log_retention_dispatch_request(
            {"retention_cutoff": "2026-07-06T00:00:00Z", "retention_days": "30"}
        )
    with pytest.raises(AgServiceLogRetentionError) as bad_object:
        ag_operations._service_log_retention_dispatch_request(
            {"retention_cutoff": "2026-07-06T00:00:00Z", "requested_by": "nex-ag"}
        )

    assert bad_shape.value.error_code == "ag.service_log_retention_payload_invalid"
    assert missing_cutoff.value.detail == "retention_cutoff must be a non-empty string."
    assert blank_cutoff.value.detail == (
        "retention_cutoff must be a non-empty string when supplied."
    )
    assert bad_bool.value.detail == "dry_run must be a boolean."
    assert bad_int.value.detail == "retention_days must be an integer."
    assert bad_object.value.detail == "requested_by must be an object."


def test_build_service_log_projection_uses_registry_and_can_omit_request_trace_id() -> (
    None
):
    registry = build_operations_source_registry(service_log_stores=build_log_stores())

    projection = build_service_log_projection(
        registry=registry,
        service_id="nex-cx",
        logger_name="nex_runtime.worker_runner",
        subject_type="cx.document",
        subject_id="doc-001",
    )

    assert "request_trace_id" not in projection
    assert projection["projection_status"] == "READY"
    assert (
        projection["source_registry"]["sources"]["nex-cx"]["capabilities"]["logs"]
        is True
    )
    assert [entry["log_id"] for entry in projection["logs"]] == ["log-001"]


def test_build_service_log_projection_applies_query_options_and_reports_sources() -> (
    None
):
    projection = build_service_log_projection(
        service_log_stores={
            "nex-cx": build_log_stores()["nex-cx"],
            "nex-mo": BrokenServiceLogStore(),
        },
        query_options=build_operation_query_options(
            limit=1,
            since="2026-08-05T00:00:00Z",
            sort="asc",
        ),
        q="doc-001",
    )
    missing_projection = build_service_log_projection(
        service_log_stores={"nex-cx": build_log_stores()["nex-cx"]},
        service_id="nex-ag",
    )

    assert projection["projection_status"] == "DEGRADED"
    assert [entry["log_id"] for entry in projection["logs"]] == ["log-001"]
    assert projection["source_statuses"]["nex-mo"]["status"] == "UNAVAILABLE"
    assert projection["source_statuses"]["nex-oa"]["status"] == "NOT_CONFIGURED"
    assert projection["pagination"]["next_cursor"] is None
    assert missing_projection["projection_status"] == "DEGRADED"
    assert missing_projection["logs"] == []
    assert missing_projection["source_statuses"]["nex-ag"]["status"] == "NOT_CONFIGURED"


def test_normalize_operation_log_search_query_strips_and_rejects_long_values() -> None:
    assert normalize_operation_log_search_query("  Worker  ") == "Worker"
    assert normalize_operation_log_search_query("   ") is None

    with pytest.raises(OperationsQueryError) as exc_info:
        normalize_operation_log_search_query("x" * 129)

    assert exc_info.value.error_code == "ag.service_log_query_invalid"


def test_build_service_log_detail_projection_returns_safe_log_summary() -> None:
    entry = build_log_store().get_log("log-002")
    assert entry is not None

    projection = build_service_log_detail_projection(
        entry,
        request_trace_id=TRACE_ID,
    )

    assert (
        projection["projection_schema_version"] == "ag_service_log_detail_projection.v1"
    )
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["log"]["log_id"] == "log-002"
    assert projection["summary"] == {
        "log_id": "log-002",
        "service_id": "nex-mo",
        "severity": "ERROR",
        "logger_name": "nex_mo.remote_provider",
        "trace_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "request_id": REQUEST_ID,
        "job_id": "job-mo-001",
        "subject_ref": {"type": "mo.provider", "id": "generation"},
        "observed_at": "2026-08-05T00:00:01Z",
        "redacted_attribute_keys": ["authorization"],
    }
    assert "Bearer private" not in str(projection)


def test_service_logs_route_requires_auth_returns_filtered_projection() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_service_log_routes(app, service_log_stores=build_log_stores())
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/logs")
    missing_policy_auth = client.get("/admin/v1/operations/logs/policy")
    missing_retention_auth = client.get("/admin/v1/operations/logs/retention/dry-run")
    response = client.get(
        "/admin/v1/operations/logs",
        params={"service_id": "nex-cx", "q": "worker", "limit": 1},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )
    policy_response = client.get(
        "/admin/v1/operations/logs/policy",
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )
    retention_response = client.get(
        "/admin/v1/operations/logs/retention/dry-run",
        params={"service_id": "nex-cx", "retention_days": 365, "limit": 1},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert missing_policy_auth.status_code == 401
    assert missing_retention_auth.status_code == 401
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["filters"]["service_id"] == "nex-cx"
    assert payload["filters"]["q"] == "worker"
    assert payload["logs"][0]["log_id"] == "log-001"
    assert payload["summary"]["total"] == 1
    assert policy_response.status_code == 200
    policy_payload = policy_response.json()
    assert policy_payload["request_trace_id"] == TRACE_ID
    assert policy_payload["projection_schema_version"] == (
        "ag_service_log_query_policy_projection.v1"
    )
    assert policy_payload["policy"]["retention"]["purge_execution"] == (
        "service_local_control_api"
    )
    assert retention_response.status_code == 200
    retention_payload = retention_response.json()
    assert retention_payload["request_trace_id"] == TRACE_ID
    assert retention_payload["projection_schema_version"] == (
        "ag_service_log_retention_dry_run_projection.v1"
    )
    assert retention_payload["dry_run"]["delete_enabled"] is False
    assert retention_payload["filters"]["service_id"] == "nex-cx"
    assert retention_payload["summary"]["total_candidate_count"] == 0


def test_service_log_detail_route_returns_detail_404_and_source_errors() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_service_log_routes(
        app,
        service_log_stores={
            "nex-cx": build_log_stores()["nex-cx"],
            "nex-mo": BrokenServiceLogStore(),
        },
    )
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/logs/log-001")
    response = client.get(
        "/admin/v1/operations/logs/log-001",
        headers=auth_headers(),
    )
    unavailable = client.get(
        "/admin/v1/operations/logs/log-missing",
        headers=auth_headers(),
    )

    assert missing_auth.status_code == 401
    assert response.status_code == 200
    assert response.json()["log"]["log_id"] == "log-001"
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "service_log.store_unavailable"


def test_service_logs_route_rejects_bad_filters() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_service_log_routes(app, service_log_stores=build_log_stores())
    client = TestClient(app)

    bad_service = client.get(
        "/admin/v1/operations/logs",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_retention_service = client.get(
        "/admin/v1/operations/logs/retention/dry-run",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_severity = client.get(
        "/admin/v1/operations/logs",
        params={"severity": "NOTICE"},
        headers=auth_headers(),
    )
    bad_logger = client.get(
        "/admin/v1/operations/logs",
        params={"logger_name": " "},
        headers=auth_headers(),
    )
    bad_subject = client.get(
        "/admin/v1/operations/logs",
        params={"subject_type": " "},
        headers=auth_headers(),
    )
    bad_cursor = client.get(
        "/admin/v1/operations/logs",
        params={"cursor": "before"},
        headers=auth_headers(),
    )
    bad_query = client.get(
        "/admin/v1/operations/logs",
        params={"q": "x" * 129},
        headers=auth_headers(),
    )
    not_found = client.get(
        "/admin/v1/operations/logs/log-missing",
        headers=auth_headers(),
    )

    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.service_log_service_invalid"
    assert bad_retention_service.status_code == 400
    assert (
        bad_retention_service.json()["error_code"] == "ag.service_log_service_invalid"
    )
    assert bad_severity.status_code == 400
    assert bad_severity.json()["error_code"] == "ag.service_log_severity_invalid"
    assert bad_logger.status_code == 400
    assert bad_logger.json()["error_code"] == "ag.service_log_logger_name_invalid"
    assert bad_subject.status_code == 400
    assert bad_subject.json()["error_code"] == "ag.service_log_subject_type_invalid"
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["error_code"] == "ag.operation_cursor_invalid"
    assert bad_query.status_code == 400
    assert bad_query.json()["error_code"] == "ag.service_log_query_invalid"
    assert not_found.status_code == 404
    assert not_found.json()["error_code"] == "ag.service_log_not_found"


def test_normalize_job_limit_clamps_bounds() -> None:
    assert normalize_job_limit(0) == 1
    assert normalize_job_limit(10) == 10
    assert normalize_job_limit(9999) == 500


def test_build_job_operations_projection_aggregates_filters_and_summarizes() -> None:
    projection = build_job_operations_projection(
        build_job_queues(),
        service_id="nex-cx",
        status="failed",
        limit=9999,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == "ag_job_operations_projection.v1"
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-cx",
        "status": FAILED,
        "job_type": None,
        "limit": 500,
        "since": None,
        "until": None,
        "sort": "desc",
        "cursor": None,
    }
    assert [job["job_id"] for job in projection["jobs"]] == ["job-cx-002"]
    assert projection["jobs"][0]["service_id"] == "nex-cx"
    assert projection["summary"]["statuses"][FAILED] == 1
    assert projection["summary"]["by_service"] == {"nex-cx": 1}
    assert projection["summary"]["by_job_type"] == {"cx.document_processing": 1}
    assert projection["source_statuses"]["nex-cx"] == {
        "status": "READY",
        "job_count": 1,
    }
    assert projection["pagination"] == {
        "limit": 500,
        "cursor": None,
        "returned": 1,
        "total_after_filters": 1,
        "next_cursor": None,
    }


def test_build_job_operations_projection_sorts_limits_and_reports_degraded_sources() -> (
    None
):
    projection = build_job_operations_projection(
        {
            **build_job_queues(),
            "nex-mo": BrokenJobQueue(),
        },
        limit=2,
    )

    assert projection["projection_status"] == "DEGRADED"
    assert [job["job_id"] for job in projection["jobs"]] == [
        "job-ae-001",
        "job-cx-002",
    ]
    assert projection["summary"]["total"] == 2
    assert projection["summary"]["by_service"] == {"nex-ae-api": 1, "nex-cx": 1}
    assert projection["source_statuses"]["nex-mo"]["status"] == "UNAVAILABLE"
    assert projection["source_statuses"]["nex-oa"] == {
        "status": "NOT_CONFIGURED",
        "job_count": 0,
    }


def test_build_job_operations_projection_applies_query_options_before_paging() -> None:
    projection = build_job_operations_projection(
        build_job_queues(),
        query_options=build_operation_query_options(
            limit=1,
            since="2026-08-05T00:00:04Z",
            until="2026-08-05T00:00:07Z",
            sort="asc",
        ),
    )

    assert [job["job_id"] for job in projection["jobs"]] == ["job-cx-002"]
    assert projection["source_statuses"]["nex-cx"]["job_count"] == 1
    assert projection["source_statuses"]["nex-ae-api"]["job_count"] == 1
    assert projection["pagination"] == {
        "limit": 1,
        "cursor": None,
        "returned": 1,
        "total_after_filters": 2,
        "next_cursor": "1",
    }


def test_build_job_operation_detail_projection_includes_lifecycle_timeline() -> None:
    job = build_job_queues()["nex-cx"].get_job("job-cx-001")
    assert job is not None

    projection = build_job_operation_detail_projection(
        job,
        service_id="nex-cx",
        event_store=build_store(),
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_job_operation_detail_projection.v1"
    )
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["job"]["service_id"] == "nex-cx"
    assert projection["job"]["job_id"] == "job-cx-001"
    assert projection["summary"]["timeline_status"] == "READY"
    assert projection["summary"]["timeline_event_count"] == 1
    timeline_event_ids = [
        event["event_id"] for event in projection["lifecycle_timeline"]["events"]
    ]
    assert timeline_event_ids == ["event-001"]


def test_build_job_operation_detail_projection_reports_timeline_source_states() -> None:
    job = build_job_queues()["nex-cx"].get_job("job-cx-001")
    assert job is not None

    not_configured = build_job_operation_detail_projection(
        job,
        service_id="nex-cx",
    )
    unavailable = build_job_operation_detail_projection(
        job,
        service_id="nex-cx",
        event_store=BrokenOperationalEventStore(),
    )

    assert not_configured["lifecycle_timeline"] == {
        "timeline_status": "NOT_CONFIGURED",
        "event_count": 0,
        "events": [],
        "source_error": None,
    }
    assert unavailable["lifecycle_timeline"]["timeline_status"] == "UNAVAILABLE"
    assert unavailable["lifecycle_timeline"]["source_error"] == {
        "error_code": "operational_event.store_unavailable",
        "detail": "operational event store is unavailable",
        "status_code": 503,
    }


def test_summarize_job_operations_counts_empty_and_unknown_shapes() -> None:
    assert summarize_job_operations([])["by_service"] == {}

    summary = summarize_job_operations(
        [
            {
                "status": SUCCEEDED,
                "service_id": "nex-cx",
                "job_type": "cx.document_processing",
            },
            {"status": "UNKNOWN"},
        ]
    )

    assert summary["total"] == 2
    assert summary["statuses"][SUCCEEDED] == 1
    assert summary["by_service"] == {"nex-cx": 1, "unknown": 1}
    assert summary["by_job_type"] == {"cx.document_processing": 1, "unknown": 1}


def test_job_operations_route_requires_auth() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(app, job_queues=build_job_queues())

    response = TestClient(app).get("/admin/v1/operations/jobs")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_job_operations_route_returns_filtered_projection() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(app, job_queues=build_job_queues())

    response = TestClient(app).get(
        "/admin/v1/operations/jobs",
        params={"job_type": "ae.artifact_render", "limit": 1},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["filters"]["job_type"] == "ae.artifact_render"
    assert payload["jobs"][0]["job_id"] == "job-ae-001"
    assert payload["summary"]["statuses"][SUCCEEDED] == 1


def test_job_operation_detail_route_requires_auth_returns_job_and_404() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(app, registry=registry)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/jobs/nex-cx/job-cx-001")
    response = client.get(
        "/admin/v1/operations/jobs/nex-cx/job-cx-001",
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )
    missing_job = client.get(
        "/admin/v1/operations/jobs/nex-cx/job-missing",
        headers=auth_headers(),
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["job"]["job_id"] == "job-cx-001"
    assert payload["lifecycle_timeline"]["timeline_status"] == "READY"
    timeline_event_ids = [
        event["event_id"] for event in payload["lifecycle_timeline"]["events"]
    ]
    assert timeline_event_ids == ["event-cx-001"]
    assert missing_job.status_code == 404
    assert missing_job.json()["error_code"] == "ag.job_not_found"


def test_job_operation_detail_route_rejects_bad_or_unavailable_sources() -> None:
    registry = build_operations_source_registry(job_queues=build_job_queues())
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(app, registry=registry)
    client = TestClient(app)

    bad_service = client.get(
        "/admin/v1/operations/jobs/nex-unknown/job-001",
        headers=auth_headers(),
    )
    missing_source = client.get(
        "/admin/v1/operations/jobs/nex-mo/job-001",
        headers=auth_headers(),
    )

    unavailable_app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(
        unavailable_app,
        job_queues={"nex-cx": UnavailableJobQueue()},
    )
    unavailable = TestClient(unavailable_app).get(
        "/admin/v1/operations/jobs/nex-cx/job-001",
        headers=auth_headers(),
    )

    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert missing_source.status_code == 404
    assert missing_source.json()["error_code"] == "ag.job_source_not_configured"
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "job.store_unavailable"


def test_job_control_dispatch_projection_wraps_service_response() -> None:
    projection = build_job_control_dispatch_projection(
        service_id="nex-cx",
        job_id="job-cx-001",
        action="cancel",
        service_response=service_job_control_response(
            service_id="nex-cx",
            job_id="job-cx-001",
            action="cancel",
            status="CANCELLED",
        ),
        request_trace_id=TRACE_ID,
    )

    assert (
        projection["projection_schema_version"]
        == AG_JOB_CONTROL_DISPATCH_SCHEMA_VERSION
    )
    assert projection["dispatch_status"] == "SUCCEEDED"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["audit_event"] == {
        "ok": False,
        "error_code": "ag.job_control_audit_not_requested",
    }
    assert projection["summary"] == {
        "service_id": "nex-cx",
        "job_id": "job-cx-001",
        "action": "cancel",
        "job_status": "CANCELLED",
        "allowed_actions": ["read"],
    }


def test_job_control_routes_dispatch_cancel_retry_and_replay_to_service_client() -> (
    None
):
    control_client = RecordingJobControlClient()
    audit_store = InMemoryOperationalEventStore()
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(
        app,
        job_queues=build_job_queues(),
        job_control_client=control_client,
        audit_event_store=audit_store,
    )
    client = TestClient(app)
    headers = {
        **auth_headers(),
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }

    cancel = client.post(
        "/admin/v1/operations/jobs/nex-cx/job-cx-001/cancel",
        json={"observed_at": "2026-08-05T00:00:08Z"},
        headers=headers,
    )
    retry = client.post(
        "/admin/v1/operations/jobs/nex-cx/job-cx-001/retry",
        json={
            "error_code": "operator.retry",
            "detail": "Operator requested retry.",
            "observed_at": "2026-08-05T00:00:09Z",
        },
        headers=headers,
    )
    replay = client.post(
        "/admin/v1/operations/jobs/nex-cx/job-cx-001/replay",
        json={
            "replay_job_id": "job-cx-001-replay-001",
            "idempotency_key": "idem-cx-001-replay-001",
            "requested_by": "operator-001",
            "reason": "fixed parser config",
            "observed_at": "2026-08-05T00:00:10Z",
        },
        headers=headers,
    )

    assert cancel.status_code == 200
    assert retry.status_code == 200
    assert replay.status_code == 200
    assert (
        cancel.json()["projection_schema_version"]
        == AG_JOB_CONTROL_DISPATCH_SCHEMA_VERSION
    )
    assert cancel.json()["audit_event"]["event_type"] == AG_JOB_CONTROL_EVENT_SUCCEEDED
    assert retry.json()["service_response"]["action"] == "retry"
    assert replay.json()["action"] == "replay"
    assert replay.json()["summary"] == {
        "service_id": "nex-cx",
        "job_id": "job-cx-001",
        "action": "replay",
        "job_status": "QUEUED",
        "allowed_actions": ["read"],
    }
    assert replay.json()["service_response"]["replay"]["replay_job_id"] == (
        "job-cx-001-replay-001"
    )
    assert retry.json()["audit_event"]["ok"] is True
    audit_events = audit_store.list_events(service_id="nex-ag", limit=10)
    assert [event["event_type"] for event in audit_events] == [
        AG_JOB_CONTROL_EVENT_SUCCEEDED,
        AG_JOB_CONTROL_EVENT_SUCCEEDED,
        AG_JOB_CONTROL_EVENT_SUCCEEDED,
    ]
    assert audit_events[0]["details"]["action"] == "replay"
    assert audit_events[1]["details"]["action"] == "retry"
    assert audit_events[2]["details"]["action"] == "cancel"
    assert control_client.calls == [
        {
            "action": "cancel",
            "service_id": "nex-cx",
            "job_id": "job-cx-001",
            "request_id": REQUEST_ID,
            "trace_id": TRACE_ID,
            "observed_at": "2026-08-05T00:00:08Z",
        },
        {
            "action": "retry",
            "service_id": "nex-cx",
            "job_id": "job-cx-001",
            "request_id": REQUEST_ID,
            "trace_id": TRACE_ID,
            "error_code": "operator.retry",
            "detail": "Operator requested retry.",
            "observed_at": "2026-08-05T00:00:09Z",
        },
        {
            "action": "replay",
            "service_id": "nex-cx",
            "job_id": "job-cx-001",
            "request_id": REQUEST_ID,
            "trace_id": TRACE_ID,
            "replay_job_id": "job-cx-001-replay-001",
            "idempotency_key": "idem-cx-001-replay-001",
            "requested_by": "operator-001",
            "reason": "fixed parser config",
            "observed_at": "2026-08-05T00:00:10Z",
        },
    ]


def test_job_control_routes_require_auth_and_validate_service_and_payload() -> None:
    control_client = RecordingJobControlClient()
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(app, job_control_client=control_client)
    client = TestClient(app)

    missing_auth = client.post("/admin/v1/operations/jobs/nex-cx/job-cx-001/cancel")
    retry_missing_auth = client.post(
        "/admin/v1/operations/jobs/nex-cx/job-cx-001/retry"
    )
    replay_missing_auth = client.post(
        "/admin/v1/operations/jobs/nex-cx/job-cx-001/replay"
    )
    cancel_bad_service = client.post(
        "/admin/v1/operations/jobs/nex-unknown/job-cx-001/cancel",
        headers=auth_headers(),
    )
    bad_service = client.post(
        "/admin/v1/operations/jobs/nex-unknown/job-cx-001/retry",
        headers=auth_headers(),
    )
    bad_payload = client.post(
        "/admin/v1/operations/jobs/nex-cx/job-cx-001/retry",
        json={"error_code": ""},
        headers=auth_headers(),
    )
    replay_bad_payload = client.post(
        "/admin/v1/operations/jobs/nex-cx/job-cx-001/replay",
        json={
            "replay_job_id": "job-cx-001-replay-001",
            "idempotency_key": "idem-cx-001-replay-001",
            "requested_by": "operator-001",
        },
        headers=auth_headers(),
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert retry_missing_auth.status_code == 401
    assert retry_missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert replay_missing_auth.status_code == 401
    assert replay_missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert cancel_bad_service.status_code == 400
    assert cancel_bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert bad_payload.status_code == 422
    assert bad_payload.json()["error_code"] == "ag.job_control_payload_invalid"
    assert replay_bad_payload.status_code == 422
    assert replay_bad_payload.json()["error_code"] == "ag.job_control_payload_invalid"
    assert replay_bad_payload.json()["detail"] == "reason must be a non-empty string."
    assert control_client.calls == []


def test_job_control_routes_map_service_client_errors() -> None:
    audit_store = InMemoryOperationalEventStore()
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(
        app,
        job_control_client=RecordingJobControlClient(
            error=AgJobControlError(
                status_code=409,
                error_code="job.retry_status_invalid",
                detail="only RUNNING jobs can be retried",
                retryable=False,
            )
        ),
        audit_event_store=audit_store,
    )

    response = TestClient(app).post(
        "/admin/v1/operations/jobs/nex-cx/job-cx-001/retry",
        headers=auth_headers(),
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "job.retry_status_invalid"
    assert response.json()["type"].endswith("/job-control-dispatch-failed")
    assert (
        response.json()["details"]["audit_event"]["event_type"]
        == AG_JOB_CONTROL_EVENT_FAILED
    )
    audit_events = audit_store.list_events(service_id="nex-ag", limit=10)
    assert audit_events[0]["event_type"] == AG_JOB_CONTROL_EVENT_FAILED
    assert audit_events[0]["details"]["error_code"] == "job.retry_status_invalid"


def test_job_control_route_still_succeeds_when_audit_emit_fails() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(
        app,
        job_control_client=RecordingJobControlClient(),
        audit_event_store=BrokenOperationalEventStore(),
    )

    response = TestClient(app).post(
        "/admin/v1/operations/jobs/nex-cx/job-cx-001/cancel",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["audit_event"] == {
        "ok": False,
        "error_code": "operational_event.emit_failed",
        "detail": "operational event emission failed",
        "status_code": 503,
    }


def test_job_operations_route_rejects_bad_filters() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(app, job_queues=build_job_queues())
    client = TestClient(app)

    bad_status = client.get(
        "/admin/v1/operations/jobs",
        params={"status": "BLOCKED"},
        headers=auth_headers(),
    )
    bad_service = client.get(
        "/admin/v1/operations/jobs",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_cursor = client.get(
        "/admin/v1/operations/jobs",
        params={"cursor": "-1"},
        headers=auth_headers(),
    )

    assert bad_status.status_code == 400
    assert bad_status.json()["error_code"] == "ag.job_status_invalid"
    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["error_code"] == "ag.operation_cursor_invalid"
