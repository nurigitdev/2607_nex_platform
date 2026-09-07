from __future__ import annotations

import json

import pytest
from sqlalchemy.exc import SQLAlchemyError

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_EVENT_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RECORD_SCHEMA_VERSION,
    FakeArtifactRetentionSchedulerDaemonSupervisorAdapter,
    SqlAlchemyArtifactRetentionSchedulerDaemonSupervisorStore,
    build_artifact_retention_scheduler_daemon_supervisor_command,
    build_artifact_retention_scheduler_daemon_supervisor_event,
    build_artifact_retention_scheduler_daemon_supervisor_record,
    run_artifact_retention_scheduler_daemon_supervisor_command,
    validate_artifact_retention_scheduler_daemon_supervisor_event,
    validate_artifact_retention_scheduler_daemon_supervisor_record,
)
from nex_ae_api.artifacts import ArtifactHandoffError, sha256_json
from test_nex_ae_artifacts import sqlite_artifact_session_factory


CHECKED_AT = "2026-09-01T01:00:00Z"
OBSERVED_AT = "2026-09-01T01:00:03Z"


def _supervisor_result(*, action: str = "status_probe", observed_at: str = OBSERVED_AT):
    command = build_artifact_retention_scheduler_daemon_supervisor_command(
        action=action,
        enabled=action == "start_daemon",
        explicit_opt_in=action == "start_daemon",
        checked_at=CHECKED_AT,
        requested_by={"actor_type": "operator", "actor_id": "ag-admin"},
        reason="slice_0564_regression",
    )
    return run_artifact_retention_scheduler_daemon_supervisor_command(
        supervisor_command=command,
        supervisor_adapter=FakeArtifactRetentionSchedulerDaemonSupervisorAdapter(),
        observed_at=observed_at,
    )


def test_supervisor_store_persists_records_events_and_read_filters() -> None:
    store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisorStore(
        sqlite_artifact_session_factory()
    )
    store.ensure_schema()
    store.ensure_available()
    status_result = _supervisor_result()
    start_result = _supervisor_result(
        action="start_daemon",
        observed_at="2026-09-01T01:00:04Z",
    )

    saved_status = store.record_supervisor_result(status_result)
    saved_start = store.record_supervisor_result(start_result)
    second_save = store.record_supervisor_result(status_result)
    status_record = saved_status["supervisor_record"]
    status_event = saved_status["supervisor_event"]
    serialized_record = json.dumps(status_record, ensure_ascii=False, sort_keys=True)

    assert status_record["daemon_supervisor_record_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RECORD_SCHEMA_VERSION
    )
    assert status_event["daemon_supervisor_event_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_EVENT_SCHEMA_VERSION
    )
    assert status_record["result_status"] == "READY"
    assert status_record["supervisor_adapter_invoked"] is True
    assert status_record["metadata"]["supervisor_result_persisted"] is True
    assert status_record["metadata"]["supervisor_event_persisted"] is True
    assert status_record["metadata"]["ag_direct_process_control_allowed"] is False
    assert status_record["metadata"]["database_write_performed"] is True
    assert status_record["supervisor_result_hash"] == sha256_json(status_result)
    assert status_event["event_type"] == "SUPERVISOR_RESULT_RECORDED"
    assert status_event["summary"]["process_started"] is False
    assert "/data/nex-platform" not in serialized_record
    assert "postgresql://" not in serialized_record
    assert second_save == saved_status

    fetched = store.get_supervisor_record(
        status_record["daemon_supervisor_record_id"]
    )
    fetched_by_result = store.get_supervisor_record_by_result_id(
        status_result["daemon_supervisor_result_id"]
    )
    status_events = store.list_supervisor_events(
        status_record["daemon_supervisor_record_id"]
    )
    status_records = store.list_supervisor_records(
        scheduler_id=status_result["scheduler_id"],
        action="STATUS_PROBE",
        result_status="ready",
        limit="1",
    )
    blocked_records = store.list_supervisor_records(result_status="BLOCKED")

    assert fetched == status_record
    assert fetched_by_result == status_record
    assert len(status_events) == 1
    assert status_events[0] == status_event
    assert status_records == [status_record]
    assert blocked_records == [saved_start["supervisor_record"]]
    assert store.list_supervisor_records(scheduler_id="missing") == []
    assert store.get_supervisor_record("missing") is None
    assert store.get_supervisor_record_by_result_id("missing") is None

    assert store.delete_supervisor_record(
        status_record["daemon_supervisor_record_id"]
    ) == {
        "daemon_supervisor_events": 1,
        "daemon_supervisor_records": 1,
    }
    assert store.list_supervisor_events(
        status_record["daemon_supervisor_record_id"]
    ) == []
    assert store.delete_supervisor_record(
        status_record["daemon_supervisor_record_id"]
    ) == {
        "daemon_supervisor_events": 0,
        "daemon_supervisor_records": 0,
    }


def test_supervisor_record_and_event_validation_edges() -> None:
    result = _supervisor_result()
    record = build_artifact_retention_scheduler_daemon_supervisor_record(result)
    event = build_artifact_retention_scheduler_daemon_supervisor_event(
        supervisor_record=record,
        supervisor_result=result,
    )

    record_error = "ae.artifact_retention_scheduler_daemon_supervisor_record_invalid"
    command_error = "ae.artifact_retention_scheduler_daemon_supervisor_command_invalid"
    record_cases: tuple[tuple[object, str, str], ...] = (
        ([], record_error, "object"),
        (
            {**record, "daemon_supervisor_record_schema_version": "wrong"},
            record_error,
            "schema",
        ),
        ({**record, "service_id": "nex-ag"}, record_error, "service"),
        ({**record, "action": "restart"}, record_error, "action"),
        ({**record, "result_status": "STARTED"}, record_error, "status"),
        ({**record, "runtime_ready": "yes"}, record_error, "runtime_ready"),
        ({**record, "summary": []}, record_error, "summary"),
        ({**record, "metadata": []}, record_error, "metadata"),
        (
            {
                **record,
                "supervisor_command": {
                    **record["supervisor_command"],
                    "scheduler_id": "other",
                },
            },
            command_error,
            "scope",
        ),
        (
            {**record, "summary": {**record["summary"], "action": "wrong"}},
            record_error,
            "summary",
        ),
        (
            {
                **record,
                "metadata": {
                    **record["metadata"],
                    "database_url_included": True,
                },
            },
            record_error,
            "metadata",
        ),
        ({**record, "daemon_supervisor_record_id": "wrong"}, record_error, "id"),
        ({**record, "supervisor_result_hash": "0" * 64}, record_error, "hash"),
        ({**record, "unexpected": True}, record_error, "keys"),
    )
    for payload, error_code, detail in record_cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_supervisor_record(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail

    event_cases: tuple[tuple[object, str], ...] = (
        ([], "object"),
        ({**event, "daemon_supervisor_event_schema_version": "wrong"}, "schema"),
        ({**event, "service_id": "nex-ag"}, "service"),
        ({**event, "action": "restart"}, "action"),
        ({**event, "result_status": "STARTED"}, "status"),
        ({**event, "event_type": "SUPERVISOR_STARTED"}, "type"),
        ({**event, "summary": []}, "summary"),
        ({**event, "metadata": []}, "metadata"),
        ({**event, "daemon_supervisor_event_id": "wrong"}, "id"),
        ({**event, "unexpected": True}, "keys"),
    )
    for payload, detail in event_cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_supervisor_event(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == (
            "ae.artifact_retention_scheduler_daemon_supervisor_event_invalid"
        )
        assert detail in exc_info.value.detail

    with pytest.raises(ArtifactHandoffError) as scope_exc:
        build_artifact_retention_scheduler_daemon_supervisor_event(
            supervisor_record=record,
            supervisor_result=_supervisor_result(
                observed_at="2026-09-01T01:00:05Z",
            ),
        )
    assert "scope" in scope_exc.value.detail


def test_supervisor_store_rejects_invalid_filters_before_querying() -> None:
    store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisorStore(
        sqlite_artifact_session_factory()
    )

    for kwargs, detail in (
        ({"action": "restart"}, "action"),
        ({"result_status": "started"}, "status"),
        ({"limit": 101}, "exceeds"),
        ({"limit": "many"}, "positive integer"),
    ):
        with pytest.raises(ArtifactHandoffError) as exc_info:
            store.list_supervisor_records(**kwargs)
        assert exc_info.value.error_code == (
            "ae.artifact_retention_scheduler_daemon_supervisor_collection_invalid"
        )
        assert detail in exc_info.value.detail


def test_supervisor_store_unavailable() -> None:
    class BrokenSessionFactory:
        def __call__(self) -> object:
            raise SQLAlchemyError("database offline")

    store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisorStore(
        BrokenSessionFactory()
    )
    result = _supervisor_result()

    for operation in (
        store.ensure_schema,
        store.ensure_available,
        lambda: store.record_supervisor_result(result),
        lambda: store.get_supervisor_record("daemon-supervisor-record"),
        lambda: store.get_supervisor_record_by_result_id("daemon-supervisor-result"),
        lambda: store.list_supervisor_records(limit=1),
        lambda: store.list_supervisor_events("daemon-supervisor-record"),
        lambda: store.delete_supervisor_record("daemon-supervisor-record"),
    ):
        with pytest.raises(ArtifactHandoffError) as exc_info:
            operation()
        assert exc_info.value.error_code == (
            "ae.artifact_retention_scheduler_daemon_supervisor_store_unavailable"
        )
