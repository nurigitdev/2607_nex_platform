from __future__ import annotations

import io
import json
from copy import deepcopy
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import nex_ae_api.artifact_retention_scheduler_daemon as daemon_module
from nex_ae_api.artifact_retention_scheduler import (
    ArtifactRetentionSchedulerLeaseStore,
)
from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_RESULT_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LIFECYCLE_EVENT_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_RECORD_SCHEMA_VERSION,
    SqlAlchemyArtifactRetentionSchedulerDaemonRunStore,
    build_artifact_retention_scheduler_daemon_lifecycle_events,
    build_artifact_retention_scheduler_daemon_process_lock,
    build_artifact_retention_scheduler_daemon_run_record,
    build_artifact_retention_scheduler_daemon_run_metadata,
    build_artifact_retention_scheduler_daemon_signal_shutdown_adapter,
    execution_result_summary_line,
    main,
    run_artifact_retention_scheduler_daemon_cli_execution,
    summarize_artifact_retention_scheduler_daemon_cli_execution_result,
    validate_artifact_retention_scheduler_daemon_lifecycle_event,
    validate_artifact_retention_scheduler_daemon_cli_execution_result,
    validate_artifact_retention_scheduler_daemon_run_record,
)
from nex_ae_api.artifacts import (
    AE_ARTIFACT_RETENTION_CANDIDATE_COLLECTION_SCHEMA_VERSION,
    ArtifactHandoffError,
    build_artifact_retention_batch_plan,
    build_artifact_retention_candidate_filter,
    build_artifact_retention_scheduler_config,
)
from nex_runtime import InMemoryJobQueue
from test_nex_ae_artifacts import sqlite_artifact_session_factory


CHECKED_AT = "2026-08-31T17:30:00Z"
SECOND_TICK_AT = "2026-08-31T17:32:00Z"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


class FakeArtifactRetentionStore:
    def __init__(self, *, candidate_count: int = 1) -> None:
        self.candidate_count = candidate_count
        self.calls: list[dict[str, Any]] = []

    def plan_retention_batch(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        candidate_filter = build_artifact_retention_candidate_filter(
            tenant_id=kwargs["tenant_id"],
            workspace_id=kwargs["workspace_id"],
            owner_user_id=kwargs["owner_user_id"],
            retention_days=kwargs.get("retention_days"),
            as_of=kwargs.get("as_of"),
            limit=kwargs.get("scan_limit"),
        )
        items = [
            {
                "artifact_id": f"artifact-retention-candidate-{index}",
                "display_title": f"Old artifact {index}",
                "artifact_status": "DELETED",
                "logical_purged_at": "2026-07-31T00:00:00Z",
                "purge_eligible_at": "2026-08-30T00:00:00Z",
                "age_days_after_logical_purge": 32,
                "version_count": 1,
                "file_count": 1,
                "link_count": 0,
                "render_job_count": 1,
            }
            for index in range(self.candidate_count)
        ]
        return build_artifact_retention_batch_plan(
            {
                "artifact_retention_candidate_collection_schema_version": (
                    AE_ARTIFACT_RETENTION_CANDIDATE_COLLECTION_SCHEMA_VERSION
                ),
                "filter": candidate_filter,
                "count": len(items),
                "limit": candidate_filter["limit"],
                "items": items,
            },
            max_delete_count=kwargs.get("max_delete_count"),
            checked_at=kwargs.get("checked_at"),
            requested_by=kwargs.get("requested_by"),
            idempotency_key=kwargs.get("idempotency_key"),
        )


class FailingArtifactRetentionStore(FakeArtifactRetentionStore):
    def plan_retention_batch(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        raise RuntimeError("artifact store unavailable")


def _run_execution(**overrides: Any) -> tuple[dict[str, Any], FakeArtifactRetentionStore, InMemoryJobQueue]:
    artifact_store = overrides.pop(
        "artifact_store",
        FakeArtifactRetentionStore(candidate_count=1),
    )
    job_queue = overrides.pop("job_queue", InMemoryJobQueue())
    lease_store = overrides.pop("lease_store", ArtifactRetentionSchedulerLeaseStore())
    execution_kwargs: dict[str, Any] = {
        "artifact_store": artifact_store,
        "job_queue": job_queue,
        "lease_store": lease_store,
        "tenant_id": "tenant-001",
        "workspace_id": "workspace-001",
        "owner_user_id": "user-001",
        "checked_at": CHECKED_AT,
        "interval_seconds": 120,
        "jitter_seconds": 0,
        "max_cycles": "2",
        "retention_days": 30,
        "as_of": "2026-09-01T00:00:00Z",
        "scan_limit": 10,
        "max_delete_count": 1,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "idempotency_key": "daemon-cli-execution-0555",
        "process_id": "4242",
        "host_id": "ae-node-01",
        "stale_after_seconds": "900",
    }
    execution_kwargs.update(overrides)
    result = run_artifact_retention_scheduler_daemon_cli_execution(**execution_kwargs)
    return result, artifact_store, job_queue


def test_artifact_retention_scheduler_daemon_cli_execution_runs_bounded_loop() -> None:
    result, artifact_store, job_queue = _run_execution()
    summary = summarize_artifact_retention_scheduler_daemon_cli_execution_result(
        result
    )
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)

    assert result["daemon_cli_execution_result_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_RESULT_SCHEMA_VERSION
    )
    assert result["service_id"] == "nex-ae-api"
    assert result["result_status"] == "SUCCEEDED"
    assert result["stop_reason"] == "max_cycles_reached"
    assert result["daemon_cli_execute_command_id"] == (
        result["execute_command"]["daemon_cli_execute_command_id"]
    )
    assert result["daemon_process_lock_id"] == (
        result["process_lock"]["daemon_process_lock_id"]
    )
    assert result["started_run_metadata"]["lifecycle"]["run_status"] == "RUNNING"
    assert result["started_run_metadata"]["lifecycle"]["started_at"] == CHECKED_AT
    assert result["completed_run_metadata"]["lifecycle"]["run_status"] == "SUCCEEDED"
    assert result["completed_run_metadata"]["lifecycle"]["completed_at"] == (
        SECOND_TICK_AT
    )
    assert result["bounded_loop_result"]["cycle_count"] == 2
    assert result["bounded_loop_result"]["max_cycles"] == 2
    assert result["bounded_loop_result"]["worker_requested"] is False
    assert result["execution_plan"]["runs_existing_bounded_loop_adapter"] is True
    assert result["execution_plan"]["cycles_executed"] == 2
    assert result["execution_plan"]["job_queue_enqueue_performed"] is True
    assert result["execution_plan"]["worker_execution_performed"] is False
    assert result["guardrails"]["bounded_loop_is_finite"] is True
    assert result["guardrails"]["process_lock_acquired"] is False
    assert result["guardrails"]["run_record_persisted"] is False
    assert result["metadata"]["bounded_loop_started"] is True
    assert result["metadata"]["job_enqueued"] is True
    assert result["metadata"]["process_id"] == 4242
    assert result["metadata"]["host_id"] == "ae-node-01"
    assert summary["cycle_count"] == 2
    assert summary["job_enqueued"] is True
    assert summary["run_record_persisted"] is False
    assert validate_artifact_retention_scheduler_daemon_cli_execution_result(
        result
    ) == result
    assert "ae_scheduler_daemon_cli_execution=pass" in (
        execution_result_summary_line(result)
    )
    assert "cycles=2" in execution_result_summary_line(result)
    assert len(artifact_store.calls) == 2
    assert len(job_queue.list_jobs()) == 2
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "dummy-secret-token" not in serialized


def test_artifact_retention_scheduler_daemon_cli_execution_handles_signal_stop() -> None:
    result, artifact_store, job_queue = _run_execution(
        max_cycles="3",
        shutdown_signal_name="sigterm",
        shutdown_received_at=CHECKED_AT,
    )

    assert result["result_status"] == "STOPPED"
    assert result["stop_reason"] == "stop_requested"
    assert result["bounded_loop_result"]["cycle_count"] == 0
    assert result["shutdown_signal_adapter"]["signal"]["signal_name"] == "SIGTERM"
    assert result["shutdown_signal_adapter"]["shutdown_transition"][
        "decision_status"
    ] == "READY"
    assert result["execution_plan"]["shutdown_signal_adapter_invoked"] is True
    assert result["metadata"]["shutdown_signal_adapter_invoked"] is True
    assert result["metadata"]["bounded_loop_started"] is False
    assert artifact_store.calls == []
    assert job_queue.list_jobs() == []


def test_artifact_retention_scheduler_daemon_cli_execution_main_context() -> None:
    summary_stream = io.StringIO()
    error_stream = io.StringIO()
    artifact_store = FakeArtifactRetentionStore(candidate_count=1)
    job_queue = InMemoryJobQueue()

    assert main(
        [
            "--execute",
            "--summary",
            "--enabled",
            "--explicit-opt-in",
            "--checked-at",
            CHECKED_AT,
            "--interval-seconds",
            "120",
            "--jitter-seconds",
            "0",
            "--max-cycles",
            "1",
        ],
        out=summary_stream,
        execution_context={
            "artifact_store": artifact_store,
            "job_queue": job_queue,
            "lease_store": ArtifactRetentionSchedulerLeaseStore(),
            "tenant_id": "tenant-cli-001",
            "workspace_id": "workspace-cli-001",
            "owner_user_id": "user-cli-001",
            "process_id": "5252",
            "host_id": "ae-node-cli",
            "retention_days": 30,
            "as_of": "2026-09-01T00:00:00Z",
            "scan_limit": 10,
            "max_delete_count": 1,
            "trace_id": TRACE_ID,
            "request_id": REQUEST_ID,
            "idempotency_key": "daemon-cli-main-0555",
        },
    ) == 0
    assert "ae_scheduler_daemon_cli_execution=pass" in summary_stream.getvalue()
    assert "cycles=1" in summary_stream.getvalue()
    assert len(artifact_store.calls) == 1
    assert len(job_queue.list_jobs()) == 1

    assert main(
        [
            "--execute",
            "--enabled",
            "--explicit-opt-in",
            "--checked-at",
            CHECKED_AT,
        ],
        out=error_stream,
    ) == 1
    payload = json.loads(error_stream.getvalue())
    assert payload["error_code"] == (
        "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid"
    )
    assert "execution context is required" in payload["detail"]

    missing_field_stream = io.StringIO()
    assert main(
        [
            "--execute",
            "--enabled",
            "--explicit-opt-in",
            "--checked-at",
            CHECKED_AT,
        ],
        out=missing_field_stream,
        execution_context={
            "job_queue": InMemoryJobQueue(),
            "tenant_id": "tenant-cli-001",
            "workspace_id": "workspace-cli-001",
            "owner_user_id": "user-cli-001",
        },
    ) == 1
    missing_payload = json.loads(missing_field_stream.getvalue())
    assert "artifact_store is required" in missing_payload["detail"]


def test_artifact_retention_scheduler_daemon_cli_execution_marks_failed_run() -> None:
    result, artifact_store, job_queue = _run_execution(
        artifact_store=FailingArtifactRetentionStore(),
        max_cycles="1",
    )

    assert result["result_status"] == "FAILED"
    assert result["stop_reason"] == "cycle_failed"
    assert result["completed_run_metadata"]["lifecycle"]["run_status"] == "FAILED"
    assert result["bounded_loop_result"]["consecutive_failure_count"] == 1
    assert result["metadata"]["completed_run_status"] == "FAILED"
    assert len(artifact_store.calls) == 1
    assert job_queue.list_jobs() == []


def test_artifact_retention_scheduler_daemon_cli_execution_persists_run_store() -> None:
    session_factory = sqlite_artifact_session_factory()
    run_store = SqlAlchemyArtifactRetentionSchedulerDaemonRunStore(session_factory)
    run_store.ensure_schema()

    result, artifact_store, job_queue = _run_execution(
        run_store=run_store,
        idempotency_key="daemon-cli-execution-persisted-0557",
    )
    summary = summarize_artifact_retention_scheduler_daemon_cli_execution_result(
        result
    )
    run_record = run_store.get_run_record_by_execution_result_id(
        result["daemon_cli_execution_result_id"]
    )
    assert run_record is not None
    lifecycle_events = run_store.list_lifecycle_events(
        run_record["daemon_run_record_id"]
    )

    assert result["execution_plan"]["writes_run_record"] is True
    assert result["execution_plan"]["writes_lifecycle_event"] is True
    assert result["guardrails"]["run_record_persisted"] is True
    assert result["guardrails"]["lifecycle_event_persisted"] is True
    assert result["metadata"]["run_record_persisted"] is True
    assert result["metadata"]["lifecycle_event_persisted"] is True
    assert summary["run_record_persisted"] is True
    assert run_record["daemon_run_record_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_RECORD_SCHEMA_VERSION
    )
    assert run_record["daemon_cli_execution_result_id"] == (
        result["daemon_cli_execution_result_id"]
    )
    assert run_record["run_status"] == "SUCCEEDED"
    assert run_record["result_status"] == "SUCCEEDED"
    assert run_record["cycle_count"] == 2
    assert run_record["job_enqueued"] is True
    assert run_record["worker_executed"] is False
    assert len(lifecycle_events) == 2
    assert [item["daemon_lifecycle_event_schema_version"] for item in lifecycle_events] == [
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LIFECYCLE_EVENT_SCHEMA_VERSION,
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LIFECYCLE_EVENT_SCHEMA_VERSION,
    ]
    assert [item["event_type"] for item in lifecycle_events] == [
        "RUN_STARTED",
        "RUN_COMPLETED",
    ]
    assert [item["run_status"] for item in lifecycle_events] == [
        "RUNNING",
        "SUCCEEDED",
    ]
    assert lifecycle_events[0]["result_status"] is None
    assert lifecycle_events[1]["result_status"] == "SUCCEEDED"
    assert len(artifact_store.calls) == 2
    assert len(job_queue.list_jobs()) == 2

    second_save = run_store.record_cli_execution(result)
    assert second_save["run_record"] == run_record
    assert run_store.delete_run_record(run_record["daemon_run_record_id"]) == {
        "daemon_lifecycle_events": 2,
        "daemon_run_records": 1,
    }
    assert run_store.get_run_record(run_record["daemon_run_record_id"]) is None
    assert run_store.list_lifecycle_events(run_record["daemon_run_record_id"]) == []


def test_artifact_retention_scheduler_daemon_run_record_validation_edges() -> None:
    session_factory = sqlite_artifact_session_factory()
    run_store = SqlAlchemyArtifactRetentionSchedulerDaemonRunStore(session_factory)
    run_store.ensure_schema()
    result, _, _ = _run_execution(
        run_store=run_store,
        idempotency_key="daemon-cli-execution-validation-0557",
    )
    run_record = build_artifact_retention_scheduler_daemon_run_record(result)
    lifecycle_events = build_artifact_retention_scheduler_daemon_lifecycle_events(
        run_record=run_record,
        execution_result=result,
    )

    run_record_cases: tuple[tuple[object, str], ...] = (
        ([], "object"),
        ({**run_record, "daemon_run_record_schema_version": "wrong"}, "schema"),
        ({**run_record, "service_id": "nex-ag"}, "service"),
        ({**run_record, "cycle_count": 3}, "cycle count"),
        ({**run_record, "run_status": "STOPPED"}, "run status"),
        ({**run_record, "result_status": "UNKNOWN"}, "result status"),
        ({**run_record, "summary": []}, "summary"),
        ({**run_record, "metadata": []}, "metadata"),
        ({**run_record, "execution_result_hash": "bad"}, "hash"),
        ({**run_record, "extra": True}, "keys"),
    )
    for payload, detail in run_record_cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_run_record(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == (
            "ae.artifact_retention_scheduler_daemon_run_record_invalid"
        )
        assert detail in exc_info.value.detail

    started_event = lifecycle_events[0]
    completed_event = lifecycle_events[1]
    event_cases: tuple[tuple[object, str], ...] = (
        ([], "object"),
        (
            {
                **started_event,
                "daemon_lifecycle_event_schema_version": "wrong",
            },
            "schema",
        ),
        ({**started_event, "service_id": "nex-ag"}, "service"),
        ({**started_event, "event_type": "RUN_PAUSED"}, "type"),
        ({**started_event, "result_status": "SUCCEEDED"}, "start event"),
        ({**completed_event, "result_status": None}, "completion event"),
        ({**completed_event, "summary": []}, "summary"),
        ({**completed_event, "metadata": []}, "metadata"),
        ({**completed_event, "extra": True}, "keys"),
    )
    for payload, detail in event_cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_lifecycle_event(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == (
            "ae.artifact_retention_scheduler_daemon_lifecycle_event_invalid"
        )
        assert detail in exc_info.value.detail


def test_artifact_retention_scheduler_daemon_run_store_unavailable() -> None:
    class BrokenSessionFactory:
        def __call__(self) -> object:
            raise SQLAlchemyError("database offline")

    store = SqlAlchemyArtifactRetentionSchedulerDaemonRunStore(
        BrokenSessionFactory()
    )

    with pytest.raises(ArtifactHandoffError) as exc_info:
        store.ensure_schema()
    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_run_store_unavailable"
    )


def test_artifact_retention_scheduler_daemon_cli_execution_validation_edges() -> None:
    result, _, _ = _run_execution()
    max_one_result, _, _ = _run_execution(
        max_cycles="1",
        idempotency_key="daemon-cli-execution-one-0555",
    )
    shifted_result, _, _ = _run_execution(
        checked_at="2026-08-31T17:31:00Z",
        idempotency_key="daemon-cli-execution-shifted-0555",
    )
    other_queue = InMemoryJobQueue()
    other_scheduler_config = {
        **build_artifact_retention_scheduler_config(job_queue=other_queue),
        "scheduler_id": "other-ae-artifact-retention-scheduler",
    }
    other_result, _, _ = _run_execution(
        job_queue=other_queue,
        scheduler_config=other_scheduler_config,
        process_id="6262",
        host_id="ae-node-other",
        idempotency_key="daemon-cli-execution-other-0555",
    )
    other_signal_queue = InMemoryJobQueue()
    other_signal_config = {
        **build_artifact_retention_scheduler_config(job_queue=other_signal_queue),
        "scheduler_id": "other-ae-artifact-retention-signal-scheduler",
    }
    other_signal_result, _, _ = _run_execution(
        job_queue=other_signal_queue,
        scheduler_config=other_signal_config,
        shutdown_signal_name="SIGTERM",
        shutdown_received_at=CHECKED_AT,
        process_id="6363",
        host_id="ae-node-other-signal-scope",
        idempotency_key="daemon-cli-execution-other-signal-0555",
    )
    stopped_result, _, _ = _run_execution(
        max_cycles="1",
        shutdown_signal_name="SIGTERM",
        shutdown_received_at=CHECKED_AT,
        idempotency_key="daemon-cli-execution-stopped-0555",
    )
    other_stopped_result, _, _ = _run_execution(
        max_cycles="1",
        shutdown_signal_name="SIGTERM",
        shutdown_received_at=CHECKED_AT,
        process_id="7373",
        host_id="ae-node-other-signal",
        idempotency_key="daemon-cli-execution-other-stopped-0555",
    )
    alternate_process_lock = build_artifact_retention_scheduler_daemon_process_lock(
        execute_command=result["execute_command"],
        process_id="5252",
        host_id="ae-node-alt",
        requested_at=CHECKED_AT,
        stale_after_seconds="900",
    )
    started_stopping = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=result["execute_command"],
        process_lock=result["process_lock"],
        run_status="STOPPING",
        requested_at=result["process_lock"]["timing"]["requested_at"],
        started_at=result["started_run_metadata"]["lifecycle"]["started_at"],
    )
    started_other_process = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=result["execute_command"],
        process_lock=alternate_process_lock,
        run_status="RUNNING",
        requested_at=alternate_process_lock["timing"]["requested_at"],
        started_at=CHECKED_AT,
    )
    failed_completed = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=result["execute_command"],
        process_lock=result["process_lock"],
        run_status="FAILED",
        requested_at=result["process_lock"]["timing"]["requested_at"],
        started_at=result["started_run_metadata"]["lifecycle"]["started_at"],
        completed_at=result["bounded_loop_result"]["finished_at"],
    )
    completed_requested_diff = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=result["execute_command"],
        process_lock=result["process_lock"],
        run_status="SUCCEEDED",
        requested_at="2026-08-31T17:29:00Z",
        started_at=result["started_run_metadata"]["lifecycle"]["started_at"],
        completed_at=result["bounded_loop_result"]["finished_at"],
    )
    completed_started_diff = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=result["execute_command"],
        process_lock=result["process_lock"],
        run_status="SUCCEEDED",
        requested_at=result["process_lock"]["timing"]["requested_at"],
        started_at="2026-08-31T17:29:00Z",
        completed_at=result["bounded_loop_result"]["finished_at"],
    )
    completed_time_diff = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=result["execute_command"],
        process_lock=result["process_lock"],
        run_status="SUCCEEDED",
        requested_at=result["process_lock"]["timing"]["requested_at"],
        started_at=result["started_run_metadata"]["lifecycle"]["started_at"],
        completed_at="2026-08-31T17:34:00Z",
    )
    completed_for_shifted_loop = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=result["execute_command"],
        process_lock=result["process_lock"],
        run_status="SUCCEEDED",
        requested_at=result["process_lock"]["timing"]["requested_at"],
        started_at=result["started_run_metadata"]["lifecycle"]["started_at"],
        completed_at=shifted_result["bounded_loop_result"]["finished_at"],
    )
    completed_for_max_one_loop = build_artifact_retention_scheduler_daemon_run_metadata(
        execute_command=result["execute_command"],
        process_lock=result["process_lock"],
        run_status="SUCCEEDED",
        requested_at=result["process_lock"]["timing"]["requested_at"],
        started_at=result["started_run_metadata"]["lifecycle"]["started_at"],
        completed_at=max_one_result["bounded_loop_result"]["finished_at"],
    )
    shutdown_signal_adapter = (
        build_artifact_retention_scheduler_daemon_signal_shutdown_adapter(
            current_state=result["execute_command"]["runtime_state"],
            process_lock=result["process_lock"],
            run_metadata=result["started_run_metadata"],
            signal_name="SIGTERM",
            received_at=CHECKED_AT,
        )
    )

    cases: tuple[tuple[object, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "object",
        ),
        (
            {**result, "daemon_cli_execution_result_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_schema_invalid",
            "schema",
        ),
        (
            {**result, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "service id",
        ),
        (
            {**result, "scheduler_id": "other-scheduler"},
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "command scope",
        ),
        (
            {**result, "daemon_cli_execute_command_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "command id",
        ),
        (
            {**result, "daemon_process_lock_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "process lock id",
        ),
        (
            {
                **result,
                "daemon_process_lock_id": other_result["daemon_process_lock_id"],
                "process_lock": other_result["process_lock"],
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "process scope",
        ),
        (
            {
                **result,
                "daemon_process_lock_id": max_one_result["daemon_process_lock_id"],
                "process_lock": max_one_result["process_lock"],
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "process command scope",
        ),
        (
            {**result, "started_daemon_run_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "started run id",
        ),
        (
            {
                **result,
                "started_daemon_run_id": started_stopping["daemon_run_id"],
                "started_run_metadata": started_stopping,
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "started run status",
        ),
        (
            {
                **result,
                "started_daemon_run_id": other_result["started_daemon_run_id"],
                "started_run_metadata": other_result["started_run_metadata"],
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "started run scope",
        ),
        (
            {
                **result,
                "started_daemon_run_id": max_one_result["started_daemon_run_id"],
                "started_run_metadata": max_one_result["started_run_metadata"],
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "started run command scope",
        ),
        (
            {
                **result,
                "started_daemon_run_id": started_other_process["daemon_run_id"],
                "started_run_metadata": started_other_process,
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "started run process scope",
        ),
        (
            {
                **result,
                "completed_daemon_run_id": failed_completed["daemon_run_id"],
                "completed_run_metadata": failed_completed,
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "completed run status",
        ),
        (
            {
                **result,
                "completed_daemon_run_id": completed_requested_diff["daemon_run_id"],
                "completed_run_metadata": completed_requested_diff,
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "lifecycle request scope",
        ),
        (
            {
                **result,
                "completed_daemon_run_id": completed_started_diff["daemon_run_id"],
                "completed_run_metadata": completed_started_diff,
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "lifecycle start scope",
        ),
        (
            {
                **result,
                "completed_daemon_run_id": completed_time_diff["daemon_run_id"],
                "completed_run_metadata": completed_time_diff,
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "lifecycle completion time",
        ),
        (
            {**result, "result_status": "FAILED"},
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "result status",
        ),
        (
            {**result, "stop_reason": "cycle_failed"},
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "stop reason",
        ),
        (
            {
                **result,
                "bounded_loop_result": other_result["bounded_loop_result"],
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "bounded loop scope",
        ),
        (
            {
                **result,
                "completed_daemon_run_id": completed_for_shifted_loop[
                    "daemon_run_id"
                ],
                "completed_run_metadata": completed_for_shifted_loop,
                "bounded_loop_result": shifted_result["bounded_loop_result"],
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "bounded loop start time",
        ),
        (
            {
                **result,
                "completed_daemon_run_id": completed_for_max_one_loop[
                    "daemon_run_id"
                ],
                "completed_run_metadata": completed_for_max_one_loop,
                "bounded_loop_result": max_one_result["bounded_loop_result"],
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "bounded loop max_cycles",
        ),
        (
            {
                **result,
                "shutdown_signal_adapter": shutdown_signal_adapter,
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "shutdown signal stop reason",
        ),
        (
            {
                **stopped_result,
                "shutdown_signal_adapter": other_signal_result[
                    "shutdown_signal_adapter"
                ],
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "shutdown signal scope",
        ),
        (
            {
                **stopped_result,
                "shutdown_signal_adapter": other_result["shutdown_signal_adapter"],
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "execution plan",
        ),
        (
            {
                **stopped_result,
                "shutdown_signal_adapter": other_stopped_result[
                    "shutdown_signal_adapter"
                ],
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "shutdown signal run scope",
        ),
        (
            {
                **result,
                "execution_plan": {
                    **result["execution_plan"],
                    "cycles_executed": 99,
                },
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "execution plan",
        ),
        (
            {
                **result,
                "guardrails": {
                    **result["guardrails"],
                    "run_record_persisted": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "guardrails",
        ),
        (
            {
                **result,
                "metadata": {
                    **result["metadata"],
                    "job_enqueued": False,
                },
            },
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "metadata",
        ),
        (
            {**result, "daemon_cli_execution_result_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "result id",
        ),
        (
            {**result, "database_url": "postgresql://secret"},
            "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid",
            "keys",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_cli_execution_result(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail


def test_artifact_retention_scheduler_daemon_cli_execution_rejects_worker_flag_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _, _ = _run_execution()
    crafted_bounded_loop = deepcopy(result["bounded_loop_result"])
    crafted_bounded_loop["worker_requested"] = True

    monkeypatch.setattr(
        daemon_module,
        "validate_artifact_retention_scheduler_daemon_bounded_loop_result",
        lambda value: dict(value),
    )

    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_cli_execution_result(
            {
                **result,
                "bounded_loop_result": crafted_bounded_loop,
            }
        )
    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_cli_execution_result_invalid"
    )
    assert "bounded loop worker flag" in exc_info.value.detail
