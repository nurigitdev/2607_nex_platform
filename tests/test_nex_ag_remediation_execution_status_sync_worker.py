from __future__ import annotations

from typing import Any

import pytest

from nex_ag.generation_remediation import build_generation_remediation_action
from nex_ag.generation_remediation_handoff import CxRemediationExecutionClientError
from nex_ag.remediation_execution_status_sync_jobs import (
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE,
    build_remediation_execution_status_sync_job,
)
from nex_ag.remediation_execution_status_sync_worker import (
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_RESULT_SCHEMA_VERSION,
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_TYPE,
    RemediationExecutionStatusSyncWorkerError,
    build_remediation_execution_status_sync_worker_config,
    run_remediation_execution_status_sync_job,
    run_remediation_execution_status_sync_worker_batch,
    run_remediation_execution_status_sync_worker_once,
)
from nex_runtime import (
    ERROR,
    FAILED,
    IDLE,
    QUEUED,
    SUCCEEDED,
    InMemoryJobQueue,
    InMemoryServiceLogStore,
    InMemoryWorkerHeartbeatStore,
    ServiceLogEmitter,
    WorkerHeartbeatEmitter,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
NOW = "2026-08-27T00:00:00Z"
LATER = "2026-08-27T00:00:01Z"


class StaticClock:
    def __init__(self) -> None:
        self.ticks = 0

    def __call__(self) -> str:
        self.ticks += 1
        return f"2026-08-27T00:00:{self.ticks:02d}Z"


def remediation_record(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "remediation_action_id": "ag-remediation-action-001",
        "tenant_id": "tenant-001",
        "action_type": "citation_repair",
        "action_status": "WAITING_ON_CX",
        "priority": "HIGH",
        "reason_codes": ["citation_quality"],
        "owner_ref": {
            "owner_type": "service",
            "owner_id": "nex-ag",
            "tenant_id": "tenant-001",
        },
        "source_refs": [
            {
                "source_service": "nex-ag",
                "ref_type": "generation_quality",
                "ref_id": "cx-gen-001",
                "relation": "caused_by",
            }
        ],
        "evidence_hashes": [
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ],
        "evidence_previews": ["citation quality failed"],
    }
    payload.update(overrides)
    return build_generation_remediation_action(
        payload,
        cx_generation_id=str(overrides.get("cx_generation_id", "cx-gen-001")),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at=NOW,
    )


def cx_execution_result(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "result_schema_version": "cx_remediation_execution_result.v1",
        "remediation_action_id": "ag-remediation-action-001",
        "parent_cx_generation_id": "cx-gen-001",
        "repair_cx_generation_id": "cx-gen-repair-001",
        "tenant_id": "tenant-001",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "action_type": "citation_repair",
        "lineage_type": "repair",
        "execution_status": "SUCCEEDED",
        "result_ref": {
            "source_service": "nex-cx",
            "ref_type": "repair_execution",
            "ref_id": "cx-repair-run-001",
            "relation": "result_of",
        },
        "failure": None,
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return payload


def cx_execution_detail(**overrides: Any) -> dict[str, Any]:
    execution = overrides.pop("execution", None) or cx_execution_result(**overrides)
    return {
        "detail_schema_version": "cx_remediation_execution_detail.v1",
        "projection_status": "READY",
        "parent_cx_generation_id": execution["parent_cx_generation_id"],
        "remediation_action_id": execution["remediation_action_id"],
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "execution_status": execution["execution_status"],
        "execution": execution,
        "attention_required": execution["execution_status"] in {"FAILED", "CANCELLED"},
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
    }


def status_sync_operation(**overrides: Any) -> dict[str, Any]:
    operation: dict[str, Any] = {
        "operation_timestamp": NOW,
        "remediation_action_id": "ag-remediation-action-001",
        "cx_generation_id": "cx-gen-001",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "tenant_id": "tenant-001",
        "task_status": "WAITING_ON_CX",
        "execution_status": "SUCCEEDED",
        "target_task_status": "COMPLETED",
        "status_sync_state": "SYNC_REQUIRED",
        "attention_required": True,
        "attempt_no": 1,
    }
    operation.update(overrides)
    return operation


def status_sync_job(**overrides: Any) -> dict[str, Any]:
    return build_remediation_execution_status_sync_job(
        status_sync_operation(**overrides),
        requested_at=LATER,
    )


class FakeRemediationTaskStore:
    def __init__(self, *records: dict[str, Any]) -> None:
        self.records = {
            record["remediation_action_id"]: record for record in records
        }
        self.saved: list[dict[str, Any]] = []

    def get(self, remediation_action_id: str) -> dict[str, Any] | None:
        return self.records.get(remediation_action_id)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records[record["remediation_action_id"]] = record
        self.saved.append(record)
        return record


class FakeCxExecutionStatusClient:
    def __init__(
        self,
        *,
        execution_status: str = "SUCCEEDED",
        fail: bool = False,
    ) -> None:
        self.execution_status = execution_status
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def get_remediation_execution_detail(
        self,
        *,
        parent_cx_generation_id: str,
        remediation_action_id: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        if self.fail:
            raise CxRemediationExecutionClientError(
                status_code=503,
                error_code="ag.cx_remediation_execution_unavailable",
                detail="cx status detail unavailable",
                retryable=True,
            )
        self.calls.append(
            {
                "parent_cx_generation_id": parent_cx_generation_id,
                "remediation_action_id": remediation_action_id,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        return cx_execution_detail(
            remediation_action_id=remediation_action_id,
            parent_cx_generation_id=parent_cx_generation_id,
            execution_status=self.execution_status,
        )


def heartbeat_emitter(
    *,
    worker_id: str = "ag-remediation-execution-status-sync-worker-001",
) -> tuple[WorkerHeartbeatEmitter, InMemoryWorkerHeartbeatStore]:
    store = InMemoryWorkerHeartbeatStore()
    return (
        WorkerHeartbeatEmitter(
            service_id="nex-ag",
            worker_id=worker_id,
            worker_type=AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_TYPE,
            store=store,
            started_at=NOW,
            metadata={"queue": AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE},
        ),
        store,
    )


def service_log_emitter() -> tuple[ServiceLogEmitter, InMemoryServiceLogStore]:
    store = InMemoryServiceLogStore()
    return (
        ServiceLogEmitter(
            service_id="nex-ag",
            logger_name="nex_ag.remediation_execution_status_sync_worker",
            store=store,
            default_attributes={"runtime_component": "ag_status_sync_worker"},
        ),
        store,
    )


def test_status_sync_worker_handler_updates_task_and_returns_safe_summary() -> None:
    store = FakeRemediationTaskStore(remediation_record())
    cx_status_client = FakeCxExecutionStatusClient()

    result = run_remediation_execution_status_sync_job(
        status_sync_job(),
        store=store,
        cx_status_client=cx_status_client,
        observed_at="2026-08-27T00:00:02Z",
    )

    assert result["worker_result_schema_version"] == (
        AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_RESULT_SCHEMA_VERSION
    )
    assert result["sync_status"] == "UPDATED"
    assert result["previous_action_status"] == "WAITING_ON_CX"
    assert result["final_action_status"] == "COMPLETED"
    assert result["status_update_count"] == 1
    assert result["result_ref"]["repair_cx_generation_id"] == "cx-gen-repair-001"
    assert result["redaction_summary"]["task_snapshot_included"] is False
    assert "evidence_previews" not in str(result)
    assert store.saved[-1]["action_status"] == "COMPLETED"
    assert cx_status_client.calls == [
        {
            "parent_cx_generation_id": "cx-gen-001",
            "remediation_action_id": "ag-remediation-action-001",
            "request_id": REQUEST_ID,
            "trace_id": TRACE_ID,
        }
    ]


def test_status_sync_worker_handler_uses_runtime_timestamp_when_payload_has_none() -> None:
    job = status_sync_job()
    job["payload"] = {
        **job["payload"],
        "requested_at": None,
        "task_status": 123,
        "execution_status": None,
        "target_task_status": " ",
    }
    store = FakeRemediationTaskStore(remediation_record())

    result = run_remediation_execution_status_sync_job(
        job,
        store=store,
        cx_status_client=FakeCxExecutionStatusClient(),
    )

    assert result["sync_status"] == "UPDATED"
    assert result["final_action_status"] == "COMPLETED"
    assert store.saved[-1]["updated_at"].endswith("Z")


def test_status_sync_worker_once_claims_completes_and_logs_job() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(status_sync_job())
    heartbeat, heartbeat_store = heartbeat_emitter()
    log_emitter, log_store = service_log_emitter()
    store = FakeRemediationTaskStore(remediation_record())

    execution = run_remediation_execution_status_sync_worker_once(
        queue=queue,
        store=store,
        cx_status_client=FakeCxExecutionStatusClient(),
        heartbeat_emitter=heartbeat,
        service_log_emitter=log_emitter,
        clock=StaticClock(),
    )

    stored_job = queue.list_jobs(job_type=AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE)[0]
    stored_heartbeat = heartbeat_store.get_heartbeat(
        "nex-ag",
        "ag-remediation-execution-status-sync-worker-001",
    )
    logs = log_store.list_logs(limit=10)
    assert execution.status == SUCCEEDED
    assert execution.handler_result is not None
    assert execution.handler_result["sync_status"] == "UPDATED"
    assert stored_job["status"] == SUCCEEDED
    assert stored_job["attempt_count"] == 1
    assert stored_heartbeat is not None
    assert stored_heartbeat["status"] == IDLE
    assert [entry["message"] for entry in logs] == [
        "Worker completed a job.",
        "Worker claimed a job.",
        "Worker polling started.",
    ]
    assert logs[0]["attributes"]["worker_type"] == (
        AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_TYPE
    )


def test_status_sync_worker_batch_processes_until_idle() -> None:
    first = status_sync_job(remediation_action_id="ag-remediation-action-001")
    second = status_sync_job(
        remediation_action_id="ag-remediation-action-002",
        cx_generation_id="cx-gen-002",
    )
    queue = InMemoryJobQueue()
    queue.enqueue(first)
    queue.enqueue(second)
    heartbeat, _ = heartbeat_emitter()
    store = FakeRemediationTaskStore(
        remediation_record(remediation_action_id="ag-remediation-action-001"),
        remediation_record(
            remediation_action_id="ag-remediation-action-002",
            cx_generation_id="cx-gen-002",
        ),
    )

    result = run_remediation_execution_status_sync_worker_batch(
        queue=queue,
        store=store,
        cx_status_client=FakeCxExecutionStatusClient(),
        heartbeat_emitter=heartbeat,
        max_jobs=5,
        stop_on_failure=False,
        clock=StaticClock(),
    )

    assert result.claimed_count == 2
    assert result.succeeded_count == 2
    assert result.idle_count == 1
    assert [record["action_status"] for record in store.saved] == [
        "COMPLETED",
        "COMPLETED",
    ]
    assert result.to_summary()["job_type"] == (
        AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE
    )


def test_status_sync_worker_reports_idle_when_no_job_is_available() -> None:
    queue = InMemoryJobQueue()
    heartbeat, _ = heartbeat_emitter()

    execution = run_remediation_execution_status_sync_worker_once(
        queue=queue,
        store=FakeRemediationTaskStore(remediation_record()),
        cx_status_client=FakeCxExecutionStatusClient(),
        heartbeat_emitter=heartbeat,
        clock=StaticClock(),
    )

    assert execution.status == IDLE
    assert execution.job is None


def test_status_sync_worker_requeues_when_sync_facade_fails() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue(status_sync_job())
    heartbeat, heartbeat_store = heartbeat_emitter()

    execution = run_remediation_execution_status_sync_worker_once(
        queue=queue,
        store=FakeRemediationTaskStore(remediation_record()),
        cx_status_client=FakeCxExecutionStatusClient(fail=True),
        heartbeat_emitter=heartbeat,
        clock=StaticClock(),
    )

    stored_job = queue.list_jobs()[0]
    stored_heartbeat = heartbeat_store.get_heartbeat(
        "nex-ag",
        "ag-remediation-execution-status-sync-worker-001",
    )
    assert execution.status == FAILED
    assert execution.error_code == "ag.cx_remediation_execution_unavailable"
    assert stored_job["status"] == QUEUED
    assert stored_job["error"]["retryable"] is True
    assert stored_heartbeat is not None
    assert stored_heartbeat["status"] == ERROR
    assert stored_heartbeat["metadata"]["error_code"] == (
        "ag.cx_remediation_execution_unavailable"
    )


def test_status_sync_worker_config_validates_worker_id_and_max_jobs() -> None:
    config = build_remediation_execution_status_sync_worker_config(
        worker_id="ag-sync-worker-custom",
        max_jobs=2,
    )

    assert config.service_id == "nex-ag"
    assert config.worker_id == "ag-sync-worker-custom"
    assert config.worker_type == AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_TYPE
    assert config.job_type == AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE
    assert config.max_jobs == 2

    with pytest.raises(RemediationExecutionStatusSyncWorkerError) as blank_worker:
        build_remediation_execution_status_sync_worker_config(worker_id=" ")
    assert blank_worker.value.error_code == (
        "ag.remediation_execution_status_sync_worker.worker_id_required"
    )


@pytest.mark.parametrize(
    ("job_override", "error_code"),
    [
        (
            {"job_type": "ag.other"},
            "ag.remediation_execution_status_sync_worker.job_type_invalid",
        ),
        (
            {"payload": None},
            "ag.remediation_execution_status_sync_worker.payload_invalid",
        ),
        (
            {"payload": {"payload_schema_version": "old"}},
            "ag.remediation_execution_status_sync_worker.payload_schema_invalid",
        ),
        (
            {"payload": {**status_sync_job()["payload"], "trace_id": "other"}},
            "ag.remediation_execution_status_sync_worker.correlation_mismatch",
        ),
        (
            {"payload": {**status_sync_job()["payload"], "status_sync_state": "IN_SYNC"}},
            "ag.remediation_execution_status_sync_worker.state_not_ready",
        ),
        (
            {"subject_ref": {"type": "ag.remediation_execution.status_sync", "id": "other"}},
            "ag.remediation_execution_status_sync_worker.subject_mismatch",
        ),
        (
            {"subject_ref": None},
            "ag.remediation_execution_status_sync_worker.subject_invalid",
        ),
        (
            {"payload": {**status_sync_job()["payload"], "raw_prompt": "nope"}},
            "ag.remediation_execution_status_sync_worker.sensitive_payload",
        ),
    ],
)
def test_status_sync_worker_validates_job_shape(
    job_override: dict[str, Any],
    error_code: str,
) -> None:
    job = status_sync_job()
    job.update(job_override)

    with pytest.raises(RemediationExecutionStatusSyncWorkerError) as exc_info:
        run_remediation_execution_status_sync_job(
            job,
            store=FakeRemediationTaskStore(remediation_record()),
            cx_status_client=FakeCxExecutionStatusClient(),
        )

    assert exc_info.value.error_code == error_code


def test_status_sync_worker_rejects_non_mapping_job_and_missing_required_payload() -> None:
    with pytest.raises(RemediationExecutionStatusSyncWorkerError) as non_mapping:
        run_remediation_execution_status_sync_job(
            "not-a-job",
            store=FakeRemediationTaskStore(remediation_record()),
            cx_status_client=FakeCxExecutionStatusClient(),
        )
    job = status_sync_job()
    job["payload"] = {**job["payload"], "remediation_action_id": " "}

    with pytest.raises(RemediationExecutionStatusSyncWorkerError) as missing:
        run_remediation_execution_status_sync_job(
            job,
            store=FakeRemediationTaskStore(remediation_record()),
            cx_status_client=FakeCxExecutionStatusClient(),
        )

    assert non_mapping.value.error_code == (
        "ag.remediation_execution_status_sync_worker.job_invalid"
    )
    assert str(missing.value) == "Status sync worker requires remediation_action_id."
