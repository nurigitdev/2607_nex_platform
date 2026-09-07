from __future__ import annotations

import json

import pytest
from sqlalchemy.exc import SQLAlchemyError

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_EVENT_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_RECORD_SCHEMA_VERSION,
    SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore,
    build_artifact_retention_scheduler_daemon_supervised_process_event,
    build_artifact_retention_scheduler_daemon_supervised_process_record,
    build_artifact_retention_scheduler_daemon_supervised_process_snapshot,
    build_artifact_retention_scheduler_daemon_supervisor_command,
    validate_artifact_retention_scheduler_daemon_supervised_process_event,
    validate_artifact_retention_scheduler_daemon_supervised_process_record,
)
from nex_ae_api.artifacts import ArtifactHandoffError, sha256_json
from test_nex_ae_artifacts import sqlite_artifact_session_factory


CHECKED_AT = "2026-09-08T02:00:00Z"
OBSERVED_AT = "2026-09-08T02:00:05Z"
STARTED_AT = "2026-09-08T02:00:07Z"


def _supervised_process_snapshot(
    *,
    action: str = "status_probe",
    observed_at: str = OBSERVED_AT,
    process_status: str | None = None,
    process_id: int | str | None = None,
    started_at: str | None = None,
) -> dict[str, object]:
    command = build_artifact_retention_scheduler_daemon_supervisor_command(
        action=action,
        enabled=action == "start_daemon",
        explicit_opt_in=action == "start_daemon",
        checked_at=CHECKED_AT,
        max_cycles=2,
        run_worker=action == "start_daemon",
        requested_by={"actor_type": "operator", "actor_id": "ag-admin"},
        reason="slice_0573_regression",
    )
    return build_artifact_retention_scheduler_daemon_supervised_process_snapshot(
        supervisor_command=command,
        process_status=process_status,
        process_id=process_id,
        host_id="ae-node-0573",
        observed_at=observed_at,
        started_at=started_at,
        message="safe process evidence",
    )


def test_supervised_process_store_persists_records_events_and_filters() -> None:
    store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore(
        sqlite_artifact_session_factory()
    )
    store.ensure_schema()
    store.ensure_available()
    missing_snapshot = _supervised_process_snapshot()
    running_snapshot = _supervised_process_snapshot(
        action="start_daemon",
        observed_at="2026-09-08T02:00:06Z",
        process_status="RUNNING",
        process_id="5151",
        started_at=STARTED_AT,
    )

    saved_missing = store.record_supervised_process_snapshot(missing_snapshot)
    saved_running = store.record_supervised_process_snapshot(running_snapshot)
    second_save = store.record_supervised_process_snapshot(missing_snapshot)
    missing_record = saved_missing["supervised_process_record"]
    missing_event = saved_missing["supervised_process_event"]
    running_record = saved_running["supervised_process_record"]
    serialized_record = json.dumps(
        missing_record,
        ensure_ascii=False,
        sort_keys=True,
    )

    assert missing_record["daemon_supervised_process_record_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_RECORD_SCHEMA_VERSION
    )
    assert missing_event["daemon_supervised_process_event_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_EVENT_SCHEMA_VERSION
    )
    assert missing_record["process_status"] == "MISSING"
    assert missing_record["process_id"] is None
    assert missing_record["process_running"] is False
    assert missing_record["subprocess_adapter_required"] is False
    assert missing_record["metadata"]["supervised_process_record_persisted"] is True
    assert missing_record["metadata"]["supervised_process_event_persisted"] is True
    assert missing_record["metadata"]["database_write_performed"] is True
    assert missing_record["metadata"]["ag_direct_process_control_allowed"] is False
    assert missing_record["supervised_process_snapshot_hash"] == sha256_json(
        missing_snapshot
    )
    assert missing_event["event_type"] == "SUPERVISED_PROCESS_SNAPSHOT_RECORDED"
    assert missing_event["summary"]["process_status"] == "MISSING"
    assert missing_event["summary"]["process_running"] is False
    assert running_record["process_status"] == "RUNNING"
    assert running_record["process_id"] == 5151
    assert running_record["process_running"] is True
    assert second_save == saved_missing
    assert "/data/nex-platform" not in serialized_record
    assert "postgresql://" not in serialized_record
    assert "nuri1004" not in serialized_record
    assert "ed6@c496em" not in serialized_record

    fetched = store.get_supervised_process_record(
        missing_record["daemon_supervised_process_record_id"]
    )
    fetched_by_snapshot = store.get_supervised_process_record_by_snapshot_id(
        missing_snapshot["daemon_supervised_process_id"]
    )
    missing_events = store.list_supervised_process_events(
        missing_record["daemon_supervised_process_record_id"]
    )
    status_records = store.list_supervised_process_records(
        scheduler_id=missing_snapshot["scheduler_id"],
        action="STATUS_PROBE",
        process_status="missing",
        limit="1",
    )
    running_records = store.list_supervised_process_records(
        process_status="RUNNING"
    )

    assert fetched == missing_record
    assert fetched_by_snapshot == missing_record
    assert missing_events == [missing_event]
    assert status_records == [missing_record]
    assert running_records == [running_record]
    assert store.list_supervised_process_records(scheduler_id="missing") == []
    assert store.get_supervised_process_record("missing") is None
    assert store.get_supervised_process_record_by_snapshot_id("missing") is None

    assert store.delete_supervised_process_record(
        missing_record["daemon_supervised_process_record_id"]
    ) == {
        "daemon_supervised_process_events": 1,
        "daemon_supervised_process_records": 1,
    }
    assert store.list_supervised_process_events(
        missing_record["daemon_supervised_process_record_id"]
    ) == []
    assert store.delete_supervised_process_record(
        missing_record["daemon_supervised_process_record_id"]
    ) == {
        "daemon_supervised_process_events": 0,
        "daemon_supervised_process_records": 0,
    }


def test_supervised_process_record_and_event_validation_edges() -> None:
    snapshot = _supervised_process_snapshot()
    record = build_artifact_retention_scheduler_daemon_supervised_process_record(
        snapshot
    )
    event = build_artifact_retention_scheduler_daemon_supervised_process_event(
        supervised_process_record=record,
        supervised_process_snapshot=snapshot,
    )

    record_error = (
        "ae.artifact_retention_scheduler_daemon_supervised_process_record_invalid"
    )
    record_cases: tuple[tuple[object, str], ...] = (
        ([], "object"),
        (
            {
                **record,
                "daemon_supervised_process_record_schema_version": "wrong",
            },
            "schema",
        ),
        ({**record, "service_id": "nex-ag"}, "service"),
        ({**record, "action": "restart"}, "action"),
        ({**record, "process_status": "PAUSED"}, "status"),
        ({**record, "process_mode": "continuous"}, "mode"),
        ({**record, "process_id": 0}, "positive integer"),
        ({**record, "process_running": "yes"}, "boolean"),
        ({**record, "summary": []}, "summary"),
        ({**record, "metadata": []}, "metadata"),
        ({**record, "host_id": "wrong"}, "record host_id"),
        (
            {**record, "summary": {**record["summary"], "process_status": "RUNNING"}},
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
            "metadata",
        ),
        (
            {**record, "daemon_supervised_process_record_id": "wrong"},
            "id",
        ),
        ({**record, "supervised_process_snapshot_hash": "0" * 64}, "hash"),
        ({**record, "unexpected": True}, "keys"),
    )
    for payload, detail in record_cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_supervised_process_record(
                payload
            )
        assert exc_info.value.error_code == record_error
        assert detail in exc_info.value.detail

    event_cases: tuple[tuple[object, str], ...] = (
        ([], "object"),
        (
            {
                **event,
                "daemon_supervised_process_event_schema_version": "wrong",
            },
            "schema",
        ),
        ({**event, "service_id": "nex-ag"}, "service"),
        ({**event, "action": "restart"}, "action"),
        ({**event, "process_status": "PAUSED"}, "status"),
        ({**event, "event_type": "PROCESS_STARTED"}, "type"),
        ({**event, "summary": []}, "summary"),
        ({**event, "metadata": []}, "metadata"),
        ({**event, "daemon_supervised_process_event_id": "wrong"}, "id"),
        ({**event, "unexpected": True}, "keys"),
    )
    for payload, detail in event_cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_supervised_process_event(
                payload
            )
        assert exc_info.value.error_code == (
            "ae.artifact_retention_scheduler_daemon_supervised_process_event_invalid"
        )
        assert detail in exc_info.value.detail

    with pytest.raises(ArtifactHandoffError) as scope_exc:
        build_artifact_retention_scheduler_daemon_supervised_process_event(
            supervised_process_record=record,
            supervised_process_snapshot=_supervised_process_snapshot(
                observed_at="2026-09-08T02:00:07Z"
            ),
        )
    assert "scope" in scope_exc.value.detail


def test_supervised_process_store_rejects_invalid_filters_before_querying() -> None:
    store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore(
        sqlite_artifact_session_factory()
    )

    for kwargs, detail in (
        ({"action": "restart"}, "action"),
        ({"process_status": "PAUSED"}, "status"),
        ({"limit": 101}, "exceeds"),
        ({"limit": "many"}, "positive integer"),
    ):
        with pytest.raises(ArtifactHandoffError) as exc_info:
            store.list_supervised_process_records(**kwargs)
        assert exc_info.value.error_code == (
            "ae.artifact_retention_scheduler_daemon_supervised_process_collection_invalid"
        )
        assert detail in exc_info.value.detail


def test_supervised_process_store_unavailable() -> None:
    class BrokenSessionFactory:
        def __call__(self) -> object:
            raise SQLAlchemyError("database offline")

    store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore(
        BrokenSessionFactory()
    )
    snapshot = _supervised_process_snapshot()

    for operation in (
        store.ensure_schema,
        store.ensure_available,
        lambda: store.record_supervised_process_snapshot(snapshot),
        lambda: store.get_supervised_process_record(
            "daemon-supervised-process-record"
        ),
        lambda: store.get_supervised_process_record_by_snapshot_id(
            "daemon-supervised-process"
        ),
        lambda: store.list_supervised_process_records(limit=1),
        lambda: store.list_supervised_process_events(
            "daemon-supervised-process-record"
        ),
        lambda: store.delete_supervised_process_record(
            "daemon-supervised-process-record"
        ),
    ):
        with pytest.raises(ArtifactHandoffError) as exc_info:
            operation()
        assert exc_info.value.error_code == (
            "ae.artifact_retention_scheduler_daemon_supervised_process_store_unavailable"
        )
